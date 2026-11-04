import httpx
import pytest
from app import meta

SAMPLE = "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~ab;c!|>,1<|box;x1=1;y1=2;x2=3;y2=4;w=320;h=334|><|mask;x=5;y=6;data=2,3,!zz|>"


def client(handler, **kw):
    return meta.MetaClient(api_key="k", transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)


def test_parse_segmentation_two_records_and_semicolon_payload():
    recs = meta.parse_segmentation(SAMPLE)
    assert [r["id"] for r in recs] == [0, 1]
    assert recs[0]["box"] == {"x1": 211, "y1": 228, "x2": 270, "y2": 254, "w": 320, "h": 334}
    assert recs[0]["mask"]["H"] == 27 and recs[0]["mask"]["W"] == 60
    assert recs[0]["mask"]["payload"] == "ab;c!"
    assert recs[1]["mask"]["enc"] == "!"


def test_parse_empty_output():
    assert meta.parse_segmentation("") == []


def test_request_shape_and_auth():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = req.read()
        return httpx.Response(200, json={"output_text": "ok"})

    assert client(handler).check_photo("hi", "data:image/jpeg;base64,AA") == "ok"
    assert seen["auth"] == "Bearer k"
    assert b'"input_image"' in seen["body"] and b"muse-spark-1.3" in seen["body"]


def test_retries_429_then_succeeds():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}) if n["c"] < 3 else httpx.Response(200, json={"output_text": "x"})

    c = client(handler)
    assert c.check_photo("p", "u") == "x"
    assert c.calls[-1].attempts == 3 and c.calls[-1].ok


def test_gives_up_after_max_retries():
    c = client(lambda req: httpx.Response(503), max_retries=2)
    with pytest.raises(meta.MetaAPIError):
        c.check_photo("p", "u")
    assert c.calls[-1].attempts == 3 and not c.calls[-1].ok


def test_no_retry_on_400():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(400, text="bad")

    with pytest.raises(meta.MetaAPIError):
        client(handler).check_photo("p", "u")
    assert n["c"] == 1


def test_timeout_is_retried():
    def handler(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(meta.MetaAPIError):
        client(handler, max_retries=1).check_photo("p", "u")


def test_a_pasted_key_with_quotes_or_spaces_still_works(monkeypatch):
    import httpx
    from app import meta
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"ok": True})
    for raw in ('  "abc123"  ', "'abc123'\n", "abc123 "):
        monkeypatch.setenv("MODEL_API_KEY", raw)
        meta.MetaClient(transport=httpx.MockTransport(handler))._post("/responses", meta.SPARK, {})
        assert seen["auth"] == "Bearer abc123", raw


def test_refusals_are_logged_without_the_key(monkeypatch, caplog):
    import httpx
    from app import meta
    monkeypatch.setenv("MODEL_API_KEY", "secret-key-123")
    client = meta.MetaClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "Invalid API key"}})))
    with caplog.at_level("WARNING", logger="tailorfit.meta"):
        try:
            client._post("/responses", meta.SPARK, {})
        except meta.MetaAPIError:
            pass
    assert "HTTP 401" in caplog.text and "Invalid API key" in caplog.text and "secret-key-123" not in caplog.text
