"""Customers and orders in SQLite (data/tailorfit.db, git-ignored: it holds real people's details).

The measurement sheet from the pipeline is stored as it came out; the tailor's edits are stored
separately next to it, so the original is never overwritten. Photos are not stored unless the
customer opted in, and then only the face-blurred versions (see photos_dir).
"""
import json
import os
import secrets
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS tailors (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, shop_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, tailor_id INTEGER NOT NULL REFERENCES tailors(id) ON DELETE CASCADE,
  expires_at REAL NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  capture_token TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'new',
  style_id TEXT, fabric_width_in INTEGER NOT NULL DEFAULT 45, height_cm REAL,
  sheet_json TEXT, edits_json TEXT NOT NULL DEFAULT '{}', allowances_json TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '',
  keep_photos INTEGER NOT NULL DEFAULT 0, has_preview INTEGER NOT NULL DEFAULT 0,
  deletion_requested_at TEXT, photos_deleted_at TEXT, created_at TEXT NOT NULL, measured_at TEXT);
CREATE TABLE IF NOT EXISTS tape_log (
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, name TEXT NOT NULL,
  predicted_cm REAL NOT NULL, raw_cm REAL NOT NULL, tape_cm REAL NOT NULL, label TEXT NOT NULL, recorded_at TEXT NOT NULL,
  PRIMARY KEY (order_id, name));
CREATE TABLE IF NOT EXISTS wa_seen (id TEXT PRIMARY KEY, seen_at TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    return Path(os.environ.get("TAILORFIT_DB") or ROOT / "data" / "tailorfit.db")


def photos_dir() -> Path:
    return Path(os.environ.get("TAILORFIT_PHOTOS") or ROOT / "data" / "photos")


def _conn() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    if "tailor_id" not in {r["name"] for r in c.execute("PRAGMA table_info(customers)")}:
        c.execute("ALTER TABLE customers ADD COLUMN tailor_id INTEGER REFERENCES tailors(id) ON DELETE CASCADE")  # who owns this customer
    cols = {r["name"] for r in c.execute("PRAGMA table_info(orders)")}
    if "applied_json" not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN applied_json TEXT NOT NULL DEFAULT '{}'")  # older databases
    if "carried_from" not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN carried_from INTEGER")  # id of the order whose measurements this one reuses
    return c


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("sheet_json", "edits_json", "allowances_json", "applied_json"):
        d[k[:-5]] = json.loads(d.pop(k)) if d.get(k) else ({} if k != "sheet_json" else None)
    return d


_ORDER_SQL = ("SELECT o.*, c.name AS customer_name, c.phone AS customer_phone, c.tailor_id AS tailor_id FROM orders o "
              "JOIN customers c ON c.id = o.customer_id ")


def create_order(name: str, phone: str | None, style_id: str | None, fabric_width_in: int = 45, *, tailor_id: int | None = None,
                 customer_id: int | None = None,
                 sheet: dict | None = None, height_cm: float | None = None, measured_at: str | None = None,
                 carried_from: int | None = None) -> dict:
    """A new order, for a new customer or (customer_id) a returning one. With `sheet` the order starts out measured,
    reusing an earlier order's numbers (carried_from says which one)."""
    with _lock, _conn() as c:
        cid = customer_id or c.execute("INSERT INTO customers (name, phone, tailor_id, created_at) VALUES (?, ?, ?, ?)",
                                       (name, phone, tailor_id, now())).lastrowid
        oid = c.execute("INSERT INTO orders (customer_id, capture_token, style_id, fabric_width_in, created_at, status, sheet_json, height_cm, measured_at, carried_from) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (cid, secrets.token_urlsafe(16), style_id, fabric_width_in, now(), "measured" if sheet else "new",
                         json.dumps(sheet) if sheet else None, height_cm, measured_at, carried_from)).lastrowid
        return _row(c.execute(_ORDER_SQL + "WHERE o.id = ?", (oid,)).fetchone())


def orders_for_customer(customer_id: int) -> list[dict]:
    with _conn() as c:
        return [_row(r) for r in c.execute(_ORDER_SQL + "WHERE o.customer_id = ? ORDER BY o.id", (customer_id,)).fetchall()]


def get_order(order_id: int) -> dict | None:
    with _conn() as c:
        return _row(c.execute(_ORDER_SQL + "WHERE o.id = ?", (order_id,)).fetchone())


def get_by_token(token: str) -> dict | None:
    with _conn() as c:
        return _row(c.execute(_ORDER_SQL + "WHERE o.capture_token = ?", (token,)).fetchone())


def list_orders(tailor_id: int | None = None) -> list[dict]:
    """Newest first. With tailor_id, only that tailor's orders (None means every order, for the WhatsApp webhook)."""
    with _conn() as c:
        if tailor_id is None:
            return [_row(r) for r in c.execute(_ORDER_SQL + "ORDER BY o.id DESC").fetchall()]
        return [_row(r) for r in c.execute(_ORDER_SQL + "WHERE c.tailor_id = ? ORDER BY o.id DESC", (tailor_id,)).fetchall()]


def attach_sheet(token: str, sheet: dict, height_cm: float, keep_photos: bool, applied: dict | None = None) -> None:
    """Customer finished capture. A retake replaces the sheet and clears the tailor's edits.

    `applied` is the learned offsets (cm) already added to this sheet, so tape comparisons can be made on raw values."""
    with _lock, _conn() as c:
        c.execute("UPDATE orders SET sheet_json = ?, edits_json = '{}', applied_json = ?, height_cm = ?, status = 'measured', measured_at = ?, "
                  "keep_photos = ?, deletion_requested_at = NULL, carried_from = NULL WHERE capture_token = ?",
                  (json.dumps(sheet), json.dumps(applied or {}), height_cm, now(), int(keep_photos), token))


def update_order(order_id: int, **fields) -> None:
    allowed = {"style_id", "fabric_width_in", "notes", "allowances", "edits"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(k)
        if k in ("allowances", "edits"):
            sets.append(f"{k}_json = ?")
            vals.append(json.dumps(v))
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    if sets:
        with _lock, _conn() as c:
            c.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id = ?", (*vals, order_id))


def update_phone(order_id: int, phone: str | None) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE customers SET phone = ? WHERE id = (SELECT customer_id FROM orders WHERE id = ?)", (phone, order_id))


def set_tape(order_id: int, rows: dict[str, dict | None]) -> None:
    """rows: name -> {predicted_cm, raw_cm, tape_cm, label}, or None to forget that measurement's tape value."""
    with _lock, _conn() as c:
        for name, r in rows.items():
            if r is None:
                c.execute("DELETE FROM tape_log WHERE order_id = ? AND name = ?", (order_id, name))
            else:
                c.execute("INSERT OR REPLACE INTO tape_log (order_id, name, predicted_cm, raw_cm, tape_cm, label, recorded_at) VALUES (?,?,?,?,?,?,?)",
                          (order_id, name, r["predicted_cm"], r["raw_cm"], r["tape_cm"], r["label"], now()))


def list_tape(tailor_id: int) -> list[dict]:
    """One tailor's tape values: each tailor's accuracy (and learned offsets) come from their own tape only."""
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT t.* FROM tape_log t JOIN orders o ON o.id = t.order_id JOIN customers c ON c.id = o.customer_id "
            "WHERE c.tailor_id = ? ORDER BY t.recorded_at, t.order_id, t.name", (tailor_id,))]


# ---- tailor accounts and their sessions ----

def create_tailor(name: str, shop_name: str, email: str, password_hash: str, is_demo: bool = False) -> dict | None:
    """None if the email is already taken."""
    with _lock, _conn() as c:
        try:
            tid = c.execute("INSERT INTO tailors (name, shop_name, email, password_hash, is_demo, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (name, shop_name, email, password_hash, int(is_demo), now())).lastrowid
        except sqlite3.IntegrityError:
            return None
        return dict(c.execute("SELECT * FROM tailors WHERE id = ?", (tid,)).fetchone())


def get_tailor(tailor_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM tailors WHERE id = ?", (tailor_id,)).fetchone()
        return dict(r) if r else None


def get_tailor_by_email(email: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM tailors WHERE email = ?", (email,)).fetchone()
        return dict(r) if r else None


def update_tailor(tailor_id: int, **fields) -> None:
    allowed = {"name", "shop_name", "password_hash"}
    if not fields or set(fields) - allowed:
        raise ValueError(set(fields) - allowed)
    with _lock, _conn() as c:
        c.execute(f"UPDATE tailors SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", (*fields.values(), tailor_id))


def claim_unowned(tailor_id: int) -> int:
    """Give customers from before accounts existed to this tailor. Returns how many."""
    with _lock, _conn() as c:
        return c.execute("UPDATE customers SET tailor_id = ? WHERE tailor_id IS NULL", (tailor_id,)).rowcount


def add_session(token_hash: str, tailor_id: int, expires_at: float) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < strftime('%s','now')")
        c.execute("INSERT INTO sessions (token_hash, tailor_id, expires_at, created_at) VALUES (?, ?, ?, ?)", (token_hash, tailor_id, expires_at, now()))


def session_tailor(token_hash: str, at: float) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT t.* FROM sessions s JOIN tailors t ON t.id = s.tailor_id WHERE s.token_hash = ? AND s.expires_at > ?",
                      (token_hash, at)).fetchone()
        return dict(r) if r else None


def delete_session(token_hash: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_other_sessions(tailor_id: int, keep_hash: str | None) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM sessions WHERE tailor_id = ? AND token_hash IS NOT ?", (tailor_id, keep_hash))


def set_preview_flag(order_id: int, has: bool) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE orders SET has_preview = ? WHERE id = ?", (int(has), order_id))


def delete_order(order_id: int) -> bool:
    with _lock, _conn() as c:
        row = c.execute("SELECT customer_id FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return False
        c.execute("DELETE FROM orders WHERE id = ?", (order_id,))  # cascades to its tape values
        if not c.execute("SELECT 1 FROM orders WHERE customer_id = ?", (row["customer_id"],)).fetchone():
            c.execute("DELETE FROM customers WHERE id = ?", (row["customer_id"],))  # the customer's last order: forget them too
    shutil.rmtree(order_dir(order_id), ignore_errors=True)
    return True


# ---- photos kept with the customer's consent (face-blurred only) ----

def order_dir(order_id: int) -> Path:
    return photos_dir() / str(order_id)


def save_file(order_id: int, name: str, data: bytes) -> None:
    d = order_dir(order_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)


def read_file(order_id: int, name: str) -> bytes | None:
    p = order_dir(order_id) / name
    return p.read_bytes() if p.is_file() else None


def clear_files(order_id: int) -> None:
    """Drop stored images without recording a deletion (used when a retake replaces them)."""
    shutil.rmtree(order_dir(order_id), ignore_errors=True)


def delete_photos(order_id: int, requested_by_customer: bool = False) -> int:
    """Remove every stored image for the order (kept photos and the preview). Measurements stay."""
    d = order_dir(order_id)
    n = len([p for p in d.iterdir() if p.is_file()]) if d.is_dir() else 0
    shutil.rmtree(d, ignore_errors=True)
    with _lock, _conn() as c:
        c.execute("UPDATE orders SET has_preview = 0, keep_photos = 0, photos_deleted_at = ?, "
                  "deletion_requested_at = CASE WHEN ? THEN ? ELSE deletion_requested_at END WHERE id = ?",
                  (now(), int(requested_by_customer), now(), order_id))
    return n


def mark_message_seen(message_id: str) -> bool:
    """True the first time a WhatsApp message id is seen, False for a re-delivery."""
    with _lock, _conn() as c:
        cur = c.execute("INSERT OR IGNORE INTO wa_seen (id, seen_at) VALUES (?, ?)", (message_id, now()))
        return cur.rowcount == 1
