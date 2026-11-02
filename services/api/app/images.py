"""One place where uploaded photos are checked and cleaned before anything else sees them.

Every upload is decoded (so garbage is refused with a plain message instead of crashing later),
turned upright using its EXIF orientation (phone photos are often stored sideways), stripped of
all metadata (including GPS location and device details) by re-encoding, and shrunk to a sane size.
"""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 50_000_000   # refuse absurdly large images (decompression bombs)
MIN_SIDE = 200            # too small to measure anyone
MAX_SIDE = 2048           # SAM and the models don't need more

Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# Pillow can read dozens of formats, and most of its published vulnerabilities are in the rare ones (TIFF, raw,
# FlashPix, SPIDER, TAR, XBM, WMF...). Phones send JPEG, PNG or WebP, so nothing else is ever decoded.
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")


class ImageError(ValueError):
    """The upload can't be used; the message is safe to show the customer."""


def normalize(data: bytes, what: str = "photo", max_side: int = MAX_SIDE) -> bytes:
    try:
        im = Image.open(io.BytesIO(data), formats=ALLOWED_FORMATS)
        if im.width * im.height > MAX_PIXELS:  # check the header before decoding anything
            raise ImageError(f"The {what} is too large. Please use a normal phone photo.")
        im.load()
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError, EOFError):
        raise ImageError(f"We couldn't read the {what}. Please use a JPEG or PNG photo.") from None
    im = ImageOps.exif_transpose(im)
    if min(im.size) < MIN_SIDE:
        raise ImageError(f"The {what} is too small. Please use a normal phone photo.")
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=92)  # no exif= argument: every tag is dropped
    return out.getvalue()
