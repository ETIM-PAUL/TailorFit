import base64
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import preview
import segment
from app import meta
from styles import CATALOG

FIXTURE = Path(__file__).resolve().parents[2] / "segmentation" / "tests" / "fixtures" / "avocado_sam.txt"
RECORDS = meta.parse_segmentation(FIXTURE.read_text())


def jpeg(w=1280, h=853, color=(120, 160, 90)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG")
    return b.getvalue()


def png_b64(w=400, h=600):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (10, 80, 160)).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


class FakeClient:
    def __init__(self, fabric_records=RECORDS, judge='{"body_matches": true, "problem": ""}', describe="a long tunic"):
        self.fabric_records, self.judge, self.describe = fabric_records, judge, describe
        self.edits = []

    def segment(self, prompt, url):
        return self.fabric_records

    def check_photo(self, prompt, url):
        return self.describe

    def compare_photos(self, prompt, urls):
        return self.judge

    def edit_image(self, prompt, images):
        self.edits.append((prompt, images))
        return {"data": [{"b64_json": png_b64()}]}


@pytest.fixture
def seg(monkeypatch):
    """Replace person segmentation with a canned result (blurred face by default)."""
    state = {"face_blurred": True}

    def fake(client, jpeg_bytes):
        return segment.ViewResult(mask=np.ones((10, 10), bool), blurred_jpeg=jpeg(400, 600), face_blurred=state["face_blurred"], quality=0.9)

    monkeypatch.setattr(preview.segment, "segment_view", fake)
    return state


# ---- fabric swatch ----

def test_swatch_is_a_crop_of_the_cloth_within_size_limit():
    sw = preview.fabric_swatch(FakeClient(), jpeg())
    assert max(sw.size) <= preview.SWATCH_SIDE and min(sw.size) > 100


def test_no_fabric_is_reported_plainly():
    with pytest.raises(preview.NoFabricFound, match="couldn't find the fabric"):
        preview.fabric_swatch(FakeClient(fabric_records=[]), jpeg())


def test_tiny_fabric_is_rejected():
    tiny = [{**RECORDS[0], "box": {**RECORDS[0]["box"], "x2": RECORDS[0]["box"]["x1"] + 20, "y2": RECORDS[0]["box"]["y1"] + 20}}]
    tiny[0] = {**tiny[0], "mask": {**RECORDS[0]["mask"]}}
    with pytest.raises(preview.NoFabricFound):
        preview.fabric_swatch(FakeClient(fabric_records=tiny), jpeg())


def test_unreadable_photo_is_a_plain_error():
    with pytest.raises(preview.PreviewError, match="couldn't read"):
        preview.fabric_swatch(FakeClient(), b"not an image")


# ---- inspiration photo ----

def test_describe_style_returns_trimmed_text():
    assert preview.describe_style(FakeClient(describe='  "a long tunic"  '), jpeg()) == "a long tunic"


def test_describe_style_empty_is_an_error():
    with pytest.raises(preview.PreviewError):
        preview.describe_style(FakeClient(describe=""), jpeg())


# ---- body check ----

@pytest.mark.parametrize("reply,expected", [
    ('{"body_matches": true, "problem": ""}', (True, "")),
    ('{"body_matches": false, "problem": "Body is wider."}', (False, "Body is wider.")),
    ('```json\n{"body_matches": false, "problem": "Cropped."}\n```', (False, "Cropped.")),
    ("no idea", (True, "body check unavailable")),
    ('{"body_matches": "maybe"}', (True, "body check unavailable")),
])
def test_check_body_parsing(reply, expected):
    img = Image.new("RGB", (100, 100))
    assert preview.check_body(FakeClient(judge=reply), img, img) == expected


# ---- label ----

def test_label_is_burned_into_the_bottom_of_the_image():
    img = Image.new("RGB", (800, 1200), (255, 255, 255))
    out = preview.add_label(img)
    assert out.size == img.size
    assert np.asarray(out)[-5:, :, :].mean() < 150  # dark bar at the bottom
    assert (np.asarray(out)[:100] == 255).all()      # top untouched


# ---- whole flow ----

def test_catalog_has_the_four_starting_styles():
    assert set(CATALOG) == {"senator", "kaftan", "gown", "iro_buba"}


def test_customer_preview_for_catalog_style(seg):
    c = FakeClient()
    r = preview.make_preview(c, jpeg(), jpeg(), style_id="senator")
    assert r["mode"] == "customer" and r["label"] == preview.LABEL and r["style_id"] == "senator"
    assert len(c.edits) == 1 and len(c.edits[0][1]) == 2          # customer photo + swatch
    assert CATALOG["senator"]["description"] in c.edits[0][0]
    Image.open(io.BytesIO(r["image_jpeg"])).verify()


def test_inspiration_photo_uses_the_described_cut(seg):
    c = FakeClient(describe="a cropped jacket with puff sleeves")
    r = preview.make_preview(c, jpeg(), jpeg(), inspiration_jpeg=jpeg())
    assert r["style_id"] == "inspiration" and "cropped jacket with puff sleeves" in c.edits[0][0]


def test_distorted_body_falls_back_to_neutral_model(seg):
    c = FakeClient(judge='{"body_matches": false, "problem": "Body is wider."}')
    r = preview.make_preview(c, jpeg(), jpeg(), style_id="gown")
    assert r["mode"] == "neutral_model" and any("Body is wider" in n for n in r["notes"])
    assert len(c.edits) == 2 and len(c.edits[1][1]) == 1 and "mannequin" in c.edits[1][0]


def test_unblurred_face_is_never_sent_or_shown(seg):
    seg["face_blurred"] = False
    c = FakeClient()
    r = preview.make_preview(c, jpeg(), jpeg(), style_id="kaftan")
    assert r["mode"] == "neutral_model"
    assert len(c.edits) == 1 and len(c.edits[0][1]) == 1            # only the swatch, no customer photo
    assert any("face could not be blurred" in n for n in r["notes"])


def test_no_person_is_a_plain_error(monkeypatch):
    def boom(client, b):
        raise segment.NoPersonFound("none")
    monkeypatch.setattr(preview.segment, "segment_view", boom)
    with pytest.raises(preview.PreviewError, match="couldn't find a person"):
        preview.make_preview(FakeClient(), jpeg(), jpeg(), style_id="gown")


@pytest.mark.parametrize("kw", [{}, {"style_id": "senator", "inspiration_jpeg": b"x"}, {"style_id": "toga"}])
def test_bad_style_choices_are_rejected(seg, kw):
    with pytest.raises(ValueError):
        preview.make_preview(FakeClient(), jpeg(), jpeg(), **kw)
