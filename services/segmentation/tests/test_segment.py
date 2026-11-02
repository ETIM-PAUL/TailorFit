import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import segment
from app import meta

FIXTURE = (Path(__file__).parent / "fixtures" / "avocado_sam.txt").read_text()
W, H = 1280, 853  # frame size of the fixture image


@pytest.fixture(scope="module")
def records():
    return meta.parse_segmentation(FIXTURE)


def test_decodes_real_sam_masks_into_their_boxes(records):
    masks = segment.records_to_masks(records, W, H)
    assert len(masks) == 2
    for m, box in masks:
        ys, xs = np.nonzero(m)
        assert xs.min() >= box["x1"] - 1 and xs.max() <= box["x2"] + 1
        assert ys.min() >= box["y1"] - 1 and ys.max() <= box["y2"] + 1
        assert m.sum() > 100_000
    # Regression: pixel counts from the first live decode, checked by eye against the photo.
    assert [int(m.sum()) for m, _ in masks] == [162028, 171018]


def test_small_raster_is_scaled_up_to_its_box(records):
    """SAM caps raster size (~1024px), so a raster smaller than its box must be enlarged."""
    r = records[0]
    big = {**r, "box": {**r["box"], "x2": r["box"]["x1"] + 2 * 512 - 1, "y2": r["box"]["y1"] + 2 * 416 - 1}}
    (small, _), = segment.records_to_masks([r], 3000, 2000)  # frame big enough that nothing is clipped
    (large, _), = segment.records_to_masks([big], 3000, 2000)
    assert large.sum() == pytest.approx(4 * small.sum(), rel=0.02)


def test_mask_quality_clean_vs_cut_off():
    m = np.zeros((1000, 600), bool)
    m[100:900, 200:400] = True
    q, notes = segment.mask_quality(m, 0.95, 1)
    assert q > 0.9 and notes == []
    cut = m.copy(); cut[:100] = cut[100]  # extends to the top edge
    cut[0:100, 200:400] = True
    q2, notes2 = segment.mask_quality(cut, 0.95, 1)
    assert q2 < q * 0.6 and any("cut off" in n for n in notes2)


def test_mask_quality_flags_small_fragmented_and_crowded():
    m = np.zeros((1000, 600), bool)
    m[400:700, 200:300] = True
    q, notes = segment.mask_quality(m, None, 2)
    assert any("small" in n for n in notes) and any("more than one person" in n for n in notes)
    frag = np.zeros((1000, 600), bool)
    frag[100:900, 200:400] = True
    frag[100:900, 450:520] = True
    _, notes = segment.mask_quality(frag, None, 1)
    assert any("pieces" in n for n in notes)


def test_clean_mask_keeps_largest_blob_and_fills_only_small_holes():
    m = np.zeros((400, 400), bool)
    m[50:350, 100:300] = True
    m[360:370, 10:20] = True          # speckle
    m[100:104, 150:154] = True        # (already inside)
    m[200:204, 200:204] = False       # small hole
    m[250:330, 120:140] = False       # big enclosed gap
    m[250:330, 119:121] = True        # wall closing it on the left
    m[250:330, 140:142] = True
    m[248:252, 119:142] = True
    m[328:332, 119:142] = True
    c = segment.clean_mask(m)
    assert not c[365, 15]
    assert c[202, 202]                # small hole filled
    assert not c[290, 130]            # big hole kept


def test_blur_face_changes_only_the_face_region():
    rng = np.random.default_rng(0)
    img = Image.fromarray(rng.integers(0, 255, (300, 200, 3), dtype=np.uint8))
    face = np.zeros((300, 200), bool)
    face[40:100, 70:130] = True
    out = np.asarray(segment.blur_face(img, face)).astype(int)
    src = np.asarray(img).astype(int)
    assert np.abs(out[40:100, 70:130] - src[40:100, 70:130]).mean() > 20
    assert (out[200:, :] == src[200:, :]).all()


class FakeClient:
    def __init__(self, person, face):
        self._r = {"person": person, "face": face}

    def segment(self, prompt, url):
        return self._r[prompt]


def jpeg():
    b = io.BytesIO()
    Image.new("RGB", (W, H), (200, 200, 200)).save(b, "JPEG")
    return b.getvalue()


def test_no_person_raises(records):
    with pytest.raises(segment.NoPersonFound):
        segment.segment_view(FakeClient([], []), jpeg())


def test_missing_face_is_reported_not_hidden(records):
    r = segment.segment_view(FakeClient(records[:1], []), jpeg())
    assert r.face_blurred is False
    assert "no face found to blur" in r.notes


# ---- live framing ----

def body(top, bottom, left=250, right=350, h=1000, w=600):
    m = np.zeros((h, w), bool)
    m[top:bottom, left:right] = True
    return m


@pytest.mark.parametrize("top,bottom,status", [
    (100, 900, "ok"),            # head and feet inside the frame
    (0, 900, "head_cut"), (100, 1000, "feet_cut"), (0, 1000, "both_cut"),
    (330, 670, "too_small"),     # only 34% of the frame: could step closer
])
def test_framing_status(top, bottom, status):
    assert segment.classify_framing(body(top, bottom))["status"] == status


def test_framing_reports_height_and_sides_and_empty():
    assert segment.classify_framing(body(100, 900))["height_fraction"] == 0.8
    assert segment.classify_framing(body(100, 900, left=0, right=200))["status"] == "sides_cut"
    assert segment.classify_framing(np.zeros((100, 60), bool)) == {"status": "no_person", "height_fraction": 0.0}


def test_just_inside_the_edge_is_fine_and_55_percent_is_not_too_small():
    assert segment.classify_framing(body(30, 970))["status"] == "ok"
    assert segment.classify_framing(body(225, 775))["status"] == "ok"  # exactly 55%


def test_framing_end_to_end_with_a_fake_client(records):
    img = jpeg()  # framing() shrinks photos to 640px, so give it a record in that coordinate space
    half = {**records[0], "box": {k: round(v * 0.5) if k != "c" else v for k, v in records[0]["box"].items()}}
    r = segment.framing(FakeClient([half], []), img)
    assert r["status"] in {"ok", "too_small", "head_cut", "feet_cut", "both_cut", "sides_cut"} and 0 < r["height_fraction"] <= 1
    assert segment.framing(FakeClient([], []), img)["status"] == "no_person"
    with pytest.raises(ValueError):
        segment.framing(FakeClient([], []), b"not an image")
