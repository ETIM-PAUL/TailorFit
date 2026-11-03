import io

from pypdf import PdfReader

from tests.test_dashboard import anon, env, measure, new_order, tailor  # noqa: F401  (fixtures)


def measured(c, monkeypatch, **kw):
    o = new_order(c, **kw)
    assert measure(c, o, monkeypatch=monkeypatch).status_code == 200
    return o["id"]


def parts(view):
    return {r["part"]: r for r in view["finished"]}


def test_finished_sizes_show_ease_and_where_each_number_came_from(tailor, monkeypatch):
    v = tailor.get(f"/v1/orders/{measured(tailor, monkeypatch)}").json()
    tunic = parts(v)["Tunic chest"]
    assert abs(tunic["cm"] - (92 + 6 * 2.54)) < 0.2  # bust 92 cm + 6 in of ease
    assert tunic["sources"] == [{"name": "bust_chest", "label": "high"}] and "6 in ease" in tunic["how"]
    assert v["ease"] == {"defaults": {"chest": 6.0, "hip": 4.0, "thigh": 4.0}, "values": {"chest": 6.0, "hip": 4.0, "thigh": 4.0}}


def test_a_finished_size_is_only_as_trustworthy_as_its_weakest_body_number(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)  # fake sheet: waist is low confidence
    assert parts(tailor.get(f"/v1/orders/{oid}").json())["Trouser waist"]["confidence_label"] == "low"
    v = tailor.put(f"/v1/orders/{oid}/measurements", json={"edits": {"waist": 77.0}}).json()
    assert parts(v)["Trouser waist"]["confidence_label"] == "high"  # taped, so trusted
    assert parts(v)["Trouser waist"]["cm"] == 77.0


def test_tailor_sets_ease_and_it_changes_size_and_yardage_then_resets(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)
    base = tailor.get(f"/v1/orders/{oid}").json()
    loose = tailor.patch(f"/v1/orders/{oid}", json={"allowances": {"chest_ease_in": 10}}).json()
    assert loose["ease"]["values"]["chest"] == 10 and "10 in ease" in parts(loose)["Tunic chest"]["how"]
    assert abs(parts(loose)["Tunic chest"]["cm"] - parts(base)["Tunic chest"]["cm"] - 4 * 2.54) < 0.2  # 4 in more ease
    assert loose["yardage"]["yards_exact"] > base["yardage"]["yards_exact"]
    reset = tailor.patch(f"/v1/orders/{oid}", json={"allowances": {"chest_ease_in": None}}).json()
    assert reset["ease"]["values"]["chest"] == 6.0 and parts(reset)["Tunic chest"]["cm"] == parts(base)["Tunic chest"]["cm"]


def test_zero_ease_is_kept_and_out_of_range_ease_is_refused(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)
    assert tailor.patch(f"/v1/orders/{oid}", json={"allowances": {"chest_ease_in": 0}}).json()["ease"]["values"]["chest"] == 0
    assert tailor.patch(f"/v1/orders/{oid}", json={"allowances": {"chest_ease_in": 60}}).status_code == 422
    assert tailor.patch(f"/v1/orders/{oid}", json={"allowances": {"hip_ease_in": -2}}).status_code == 422


def test_changing_style_uses_the_new_styles_default_ease(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)
    v = tailor.patch(f"/v1/orders/{oid}", json={"style_id": "kaftan"}).json()
    assert v["ease"]["values"]["chest"] == 18.0 and "Robe chest" in parts(v)


def test_no_style_means_no_finished_sizes(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch, style_id=None)
    v = tailor.get(f"/v1/orders/{oid}").json()
    assert v["finished"] is None and v["ease"] is None


def test_cutting_sheet_pdf_has_the_finished_garment_table(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)
    pdf = tailor.get(f"/v1/orders/{oid}/cutting-sheet.pdf")
    assert pdf.status_code == 200
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Finished garment (Senator)" in text and "Tunic chest" in text and "6 in ease" in text


import pytest  # noqa: E402

from app import pipeline  # noqa: E402


@pytest.mark.parametrize("style_id", list(pipeline.CATALOG))
def test_every_style_gives_yardage_finished_sizes_and_a_cutting_sheet(tailor, monkeypatch, style_id):
    oid = measured(tailor, monkeypatch, style_id=style_id)
    v = tailor.get(f"/v1/orders/{oid}").json()
    assert v["style"]["id"] == style_id and "display" in v["yardage"], v["yardage"]
    assert v["finished"] and all(r["confidence_label"] in ("high", "medium", "low") for r in v["finished"])
    assert set(v["ease"]["values"]) == set(v["ease"]["defaults"])
    pdf = tailor.get(f"/v1/orders/{oid}/cutting-sheet.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
