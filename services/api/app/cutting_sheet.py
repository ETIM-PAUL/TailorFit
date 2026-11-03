"""Printable cutting sheet (PDF): measurements, style, preview and yardage for one order."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PRETTY = {
    "bust_chest": "Bust / chest", "waist": "Waist", "hip": "Hip", "neck": "Neck", "arm_round": "Arm round", "thigh": "Thigh",
    "shoulder_width": "Shoulder width", "sleeve_length": "Sleeve length", "top_length": "Top length",
    "trouser_length": "Trouser length", "inseam": "Inseam", "back_length": "Back length",
}
BRAND = colors.HexColor("#22306b")  # adire indigo, same as the app


def pretty(name: str) -> str:
    return PRETTY.get(name, name.replace("_", " ").capitalize())


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(text: str, style) -> Paragraph:
    # Paragraph parses markup, so escape anything that came from a person.
    return Paragraph(_esc(text), style)


def build_pdf(view: dict, preview_jpeg: bytes | None = None) -> bytes:
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=BRAND, fontSize=20, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=BRAND, fontSize=13, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Cutting sheet - order {view['id']}", author="TailorFit")
    story = [_p("TailorFit cutting sheet", h1)]

    style = view.get("style") or {}
    meta = [["Customer", view["customer"]["name"], "Order", f"#{view['id']}"],
            ["Phone", view["customer"].get("phone") or "-", "Date", (view.get("measured_at") or view["created_at"])[:10]],
            ["Style", style.get("name") or "not chosen", "Height", f"{view['height_cm']:.0f} cm" if view.get("height_cm") else "-"]]
    t = Table([[_p(c, body) for c in row] for row in meta], colWidths=[24 * mm, 62 * mm, 22 * mm, 62 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f0")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef2f0")),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [t, Spacer(1, 4)]

    rows = [["Measurement", "cm", "in", "Confidence", "Notes"]]
    any_edit = False
    for m in view["measurements"]:
        note = m["reason"]
        if m["edited"]:
            any_edit = True
            note = f"Edited by tailor (was {m['original_cm']:.1f} cm). " + note
        rows.append([_p(pretty(m["name"]), body), f"{m['value_cm']:.1f}", f"{m['value_in']:.1f}",
                     _p(m["confidence_label"] + (" (edited)" if m["edited"] else ""), body), _p(note, small)])
    mt = Table(rows, colWidths=[34 * mm, 17 * mm, 15 * mm, 26 * mm, 84 * mm], repeatRows=1)
    ts = [("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
          ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f4ef")])]
    for i, m in enumerate(view["measurements"], start=1):
        if m["confidence_label"] == "low" and not m["edited"]:
            ts.append(("BACKGROUND", (3, i), (3, i), colors.HexColor("#f9d6d2")))
        if m["edited"]:
            ts.append(("BACKGROUND", (0, i), (2, i), colors.HexColor("#fff3cd")))
    mt.setStyle(TableStyle(ts))
    story += [_p("Measurements", h2), mt]
    if any(m["confidence_label"] == "low" and not m["edited"] for m in view["measurements"]):
        story.append(_p("Red cells are low confidence: please check these with a tape before cutting.", small))
    if any_edit:
        story.append(_p("Yellow rows were edited by the tailor; the original estimate is shown in the notes.", small))

    fin = view.get("finished")
    if fin:
        rows = [["Garment part", "in", "cm", "How", "Confidence"]]
        for r in fin:
            rows.append([_p(r["part"], body), f"{r['inches']:.1f}", f"{r['cm']:.1f}", _p(r["how"], small), _p(r["confidence_label"], body)])
        ft = Table(rows, colWidths=[34 * mm, 15 * mm, 17 * mm, 84 * mm, 26 * mm], repeatRows=1)
        fts = [("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f4ef")])]
        fts += [("BACKGROUND", (4, i), (4, i), colors.HexColor("#f9d6d2")) for i, r in enumerate(fin, start=1) if r["confidence_label"] == "low"]
        ft.setStyle(TableStyle(fts))
        story.append(KeepTogether([_p(f"Finished garment ({style.get('name')})", h2), ft,
                                   _p("Finished sizes are the body measurement plus the ease for this style (editable on the dashboard). "
                                      "Red cells depend on a low-confidence body measurement: tape it first.", small)]))

    y = view.get("yardage")
    story.append(_p("Fabric", h2))
    if y and not y.get("error"):
        al = y["allowances"]
        by = ", ".join(f"{w}\": {v:g} yd" for w, v in y["yards_by_width"].items())
        story.append(Paragraph(f"<b>{_esc(y['display'])}</b> of {y['fabric_width_in']}-inch fabric. All widths: {_esc(by)}.", body))
        story.append(_p(f"Allowances: seam {al['seam_in']} in, hem {al['hem_in']} in, shrinkage {al['shrink_pct']}%, "
                        f"extra {al['extra_pct']}%, print matching {al['pattern_match_pct']}%.", small))
        for n in y.get("notes", []):
            story.append(_p("Note: " + n, small))
        story.append(_p(y["basis"], small))
    else:
        story.append(_p((y or {}).get("error") or "Choose a style to see the yardage.", body))

    if preview_jpeg:
        from PIL import Image as PILImage
        w, h = PILImage.open(io.BytesIO(preview_jpeg)).size
        box_h = 110 * mm
        img = Image(io.BytesIO(preview_jpeg), width=box_h * w / h, height=box_h)
        story.append(KeepTogether([_p("Style preview", h2), img, _p("Preview, not the final garment.", small)]))

    if view.get("notes"):
        story += [_p("Tailor's notes", h2), _p(view["notes"], body)]
    story += [Spacer(1, 8), _p("Measurements are estimates made from photos. Confirm before cutting.", small)]
    doc.build(story)
    return buf.getvalue()
