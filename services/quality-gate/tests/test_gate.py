import io

import pytest
from PIL import Image

import gate
from app import contract


class FakeClient:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def check_photo(self, prompt, url):
        self.prompts.append(prompt)
        return self.reply


def jpeg():
    b = io.BytesIO()
    Image.new("RGB", (200, 300), (120, 120, 120)).save(b, "JPEG")
    return b.getvalue()


OK = '{"loose_clothing":"ok","posture":"ok","arms_touching_body":"ok","lighting":"ok","occlusion":"ok","not_full_body":"ok"}'


def test_clean_photo_passes():
    v = gate.check_view(FakeClient(OK), jpeg(), "front")
    assert v == {"view": "front", "passed": True, "borderline": False, "issues": []}


def test_major_fault_rejects_with_fix_message():
    v = gate.check_view(FakeClient(OK.replace('"loose_clothing":"ok"', '"loose_clothing":"major"')), jpeg(), "front")
    assert not v["passed"] and v["issues"][0]["code"] == "loose_clothing"
    assert "fitted" in v["issues"][0]["message"]


def test_minor_fault_passes_but_is_borderline():
    v = gate.check_view(FakeClient(OK.replace('"posture":"ok"', '"posture":"minor"')), jpeg(), "front")
    assert v["passed"] and v["borderline"] and v["issues"][0]["code"] == "posture"


def test_pidgin_messages():
    v = gate.check_view(FakeClient(OK.replace('"lighting":"ok"', '"lighting":"major"')), jpeg(), "front", locale="pcm")
    assert v["issues"][0]["message"] == gate.MESSAGES["pcm"]["lighting"]


def test_unknown_locale_falls_back_to_english():
    v = gate.build_verdict("front", {"lighting": "major"}, locale="fr")
    assert v["issues"][0]["message"] == gate.MESSAGES["en"]["lighting"]


def test_every_code_has_both_languages():
    for loc in gate.LOCALES:
        assert set(gate.MESSAGES[loc]) == set(gate.CODES)


def test_reply_wrapped_in_code_fence_is_parsed():
    v = gate.check_view(FakeClient("```json\n" + OK.replace('"occlusion":"ok"', '"occlusion":"major"') + "\n```"), jpeg(), "front")
    assert not v["passed"] and v["issues"][0]["code"] == "occlusion"


@pytest.mark.parametrize("reply", ["", "I cannot help with that", "{not json}", "[1,2]"])
def test_unreadable_reply_fails_open_as_borderline(reply):
    v = gate.check_view(FakeClient(reply), jpeg(), "front")
    assert v["passed"] and v["borderline"] and v["issues"] == []


def test_junk_values_are_ignored_not_trusted():
    assert gate.parse_ratings('{"posture":"terrible","lighting":"major","extra":"major"}') == {"lighting": "major"}


def test_side_view_does_not_ask_about_arms():
    c = FakeClient(OK)
    gate.check_view(c, jpeg(), "side")
    assert "arms_touching_body" not in c.prompts[0] and "SIDE" in c.prompts[0]
    c2 = FakeClient(OK)
    gate.check_view(c2, jpeg(), "front")
    assert "arms_touching_body" in c2.prompts[0]


def test_tilt_from_the_phone_sensor():
    assert gate.build_verdict("front", {}, tilt_degrees=2)["issues"] == []
    minor = gate.build_verdict("front", {}, tilt_degrees=7)
    assert minor["passed"] and minor["borderline"]
    major = gate.build_verdict("front", {}, tilt_degrees=-14)
    assert not major["passed"] and major["issues"][0]["code"] == "tilted"


def test_add_issue_from_another_check():
    v = gate.build_verdict("front", {})
    gate.add_issue(v, "not_full_body")
    assert not v["passed"] and v["issues"][0]["code"] == "not_full_body"
    gate.add_issue(v, "not_full_body")  # no duplicates
    assert len(v["issues"]) == 1


def test_verdicts_match_the_contract():
    for v in (gate.build_verdict("front", {}), gate.build_verdict("side", {"posture": "major", "lighting": "minor"}),
              gate.add_issue(gate.build_verdict("front", {}), "not_full_body")):
        contract.validate("QualityVerdict", v)
