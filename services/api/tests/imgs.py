"""Small real images for tests (the server now refuses bytes that are not a decodable photo)."""
import io

from PIL import Image


def jpeg(w=300, h=400, color=(120, 140, 160)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG")
    return b.getvalue()


GOOD = jpeg()
