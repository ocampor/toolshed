"""Pixels to the JPEG an ``ImagePage`` carries: shrunk early, flattened,
and stripped of every byte of source metadata."""

import io
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from llm_browser.constants import TURNED_SIDEWAYS
from llm_browser.download_extract import ImageExtract
from llm_browser.results import ImagePage

if TYPE_CHECKING:
    from PIL.Image import Image


@dataclass
class Frame:
    """A page as pixels, with the size it had before any shrinking."""

    image: "Image"
    original_width: int
    original_height: int


def open_image(content: bytes) -> "Image | None":
    """``None`` unless Pillow can read the header; no pixels are decoded yet."""
    from PIL import Image as PILImage

    register_heif()
    try:
        return PILImage.open(io.BytesIO(content))
    except PILImage.DecompressionBombError as exc:
        raise ValueError(f"image too large to open: {exc}") from exc
    # Untrusted parse: Pillow raises far more than OSError on a mangled header.
    except Exception:
        return None


@cache
def register_heif() -> None:
    import pillow_heif

    pillow_heif.register_heif_opener()


def image_frame(image: "Image", spec: ImageExtract, page: int) -> Frame:
    """Shrunk before anything else touches the pixels: a JPEG decodes at the
    reduced size, and no full-size copy is ever made."""
    from PIL import ExifTags, ImageOps
    from PIL import Image as PILImage

    image.seek(page - 1)
    width, height = image.size
    limit = PILImage.MAX_IMAGE_PIXELS
    if limit is not None and width * height > limit:
        raise ValueError(
            f"image is {width}x{height}, over Pillow's decompression limit"
        )
    if image.getexif().get(ExifTags.Base.Orientation) in TURNED_SIDEWAYS:
        width, height = height, width
    # The box is square, so the 90-degree turn that follows cannot overflow it.
    box = (spec.max_long_side, spec.max_long_side)
    image.draft("RGB", box)
    image.thumbnail(box)
    upright = ImageOps.exif_transpose(image)
    return Frame(upright, width, height)


def flatten(image: "Image") -> "Image":
    """RGB pixels on white and nothing else: no EXIF, comment, ICC or XMP."""
    from PIL import Image as PILImage

    if image.mode.startswith("I"):
        # 16-bit grey (I;16, or I from a 16-bit PNG) clips to white in RGB.
        image = image.convert("I").point(lambda value: value * (1 / 256)).convert("L")
    if image.has_transparency_data:
        backdrop = PILImage.new("RGBA", image.size, "white")
        backdrop.alpha_composite(image.convert("RGBA"))
        image = backdrop
    rgb = image.convert("RGB")
    return PILImage.frombytes("RGB", rgb.size, rgb.tobytes())


def shrink(page: int, frame: Frame, spec: ImageExtract) -> ImagePage:
    rgb = flatten(frame.image)
    rgb.thumbnail((spec.max_long_side, spec.max_long_side))
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=spec.quality)
    return ImagePage(
        page=page,
        image=buffer.getvalue(),
        width=rgb.width,
        height=rgb.height,
        original_width=frame.original_width,
        original_height=frame.original_height,
    )
