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
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  capture_token TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'new',
  style_id TEXT, fabric_width_in INTEGER NOT NULL DEFAULT 45, height_cm REAL,
  sheet_json TEXT, edits_json TEXT NOT NULL DEFAULT '{}', allowances_json TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '',
  keep_photos INTEGER NOT NULL DEFAULT 0, has_preview INTEGER NOT NULL DEFAULT 0,
  deletion_requested_at TEXT, photos_deleted_at TEXT, created_at TEXT NOT NULL, measured_at TEXT);
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
    return c


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("sheet_json", "edits_json", "allowances_json"):
        d[k[:-5]] = json.loads(d.pop(k)) if d.get(k) else ({} if k != "sheet_json" else None)
    return d


_ORDER_SQL = ("SELECT o.*, c.name AS customer_name, c.phone AS customer_phone FROM orders o "
              "JOIN customers c ON c.id = o.customer_id ")


def create_order(name: str, phone: str | None, style_id: str | None, fabric_width_in: int = 45) -> dict:
    with _lock, _conn() as c:
        cid = c.execute("INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)", (name, phone, now())).lastrowid
        oid = c.execute("INSERT INTO orders (customer_id, capture_token, style_id, fabric_width_in, created_at) VALUES (?, ?, ?, ?, ?)",
                        (cid, secrets.token_urlsafe(16), style_id, fabric_width_in, now())).lastrowid
        return _row(c.execute(_ORDER_SQL + "WHERE o.id = ?", (oid,)).fetchone())


def get_order(order_id: int) -> dict | None:
    with _conn() as c:
        return _row(c.execute(_ORDER_SQL + "WHERE o.id = ?", (order_id,)).fetchone())


def get_by_token(token: str) -> dict | None:
    with _conn() as c:
        return _row(c.execute(_ORDER_SQL + "WHERE o.capture_token = ?", (token,)).fetchone())


def list_orders() -> list[dict]:
    with _conn() as c:
        return [_row(r) for r in c.execute(_ORDER_SQL + "ORDER BY o.id DESC").fetchall()]


def attach_sheet(token: str, sheet: dict, height_cm: float, keep_photos: bool) -> None:
    """Customer finished capture. A retake replaces the sheet and clears the tailor's edits."""
    with _lock, _conn() as c:
        c.execute("UPDATE orders SET sheet_json = ?, edits_json = '{}', height_cm = ?, status = 'measured', measured_at = ?, "
                  "keep_photos = ?, deletion_requested_at = NULL WHERE capture_token = ?",
                  (json.dumps(sheet), height_cm, now(), int(keep_photos), token))


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


def set_preview_flag(order_id: int, has: bool) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE orders SET has_preview = ? WHERE id = ?", (int(has), order_id))


def delete_order(order_id: int) -> bool:
    with _lock, _conn() as c:
        row = c.execute("SELECT customer_id FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return False
        c.execute("DELETE FROM customers WHERE id = ?", (row["customer_id"],))  # cascades to the order
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
