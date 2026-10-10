"""download ``extract:`` over files generated in the test."""

import hashlib
import io
import sys
import zipfile

import pypdfium2
import pytest
from PIL import ExifTags, Image

from llm_browser.download_extract import ImageExtract, TextExtract
from llm_browser.file_extract import extract_file
from llm_browser.redact import redact_secrets
from llm_browser.results import BytesResult, DocumentResult, ImagePage, TextPage


def pdf_bytes(texts: list[str]) -> bytes:
    """A 200x300pt page per text, drawn in Helvetica; ``""`` is a blank page."""
    count = len(texts)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects = [
        "<</Type/Catalog/Pages 2 0 R>>",
        f"<</Type/Pages/Kids[{kids}]/Count {count}>>",
    ]
    font = "<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>"
    for i, text in enumerate(texts):
        stream = f"BT /F1 12 Tf 20 250 Td ({text}) Tj ET" if text else ""
        objects.append(
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 300]/Resources{font}"
            f"/Contents {4 + 2 * i} 0 R>>"
        )
        objects.append(f"<</Length {len(stream)}>>stream\n{stream}\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    trailer = (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF"
    )
    out.write(trailer.encode())
    return out.getvalue()


def image_bytes(image: Image.Image, fmt: str, **save: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save)
    return buffer.getvalue()


def red_left_blue_right() -> Image.Image:
    image = Image.new("RGB", (40, 20), "blue")
    image.paste("red", (0, 0, 20, 20))
    return image


def exif_jpeg() -> bytes:
    """Orientation 6 (shown rotated 90 degrees clockwise) plus a GPS fix."""
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (19.0, 25.0, 0.0)
    return image_bytes(red_left_blue_right(), "JPEG", exif=exif)


def run(
    content: bytes, spec: TextExtract | ImageExtract, name: str = "f"
) -> DocumentResult:
    return extract_file(BytesResult(name=name, content=content), spec)


def texts(result: DocumentResult) -> list[str]:
    return [page.text for page in result.pages if isinstance(page, TextPage)]


def images(result: DocumentResult) -> list[ImagePage]:
    return [page for page in result.pages if isinstance(page, ImagePage)]


def test_text_reads_each_pdf_page() -> None:
    result = run(pdf_bytes(["alpha", "", "gamma"]), TextExtract(mode="text"))
    assert texts(result) == ["alpha", "", "gamma"]
    assert (result.page_count, result.truncated, result.next_pages) == (3, False, None)
    assert (
        result.sha256 == hashlib.sha256(pdf_bytes(["alpha", "", "gamma"])).hexdigest()
    )


@pytest.mark.parametrize(
    ("max_chars", "pages", "expected", "next_pages"),
    [
        (9, None, ["aaaa", "bbbb"], "3"),
        (9, "3", ["cccc"], None),
        (2, None, ["aa"], "2-3"),
    ],
)
def test_text_stops_at_max_chars(
    max_chars: int, pages: str | None, expected: list[str], next_pages: str | None
) -> None:
    """``max_chars`` is a hard ceiling: an over-long first page is clipped."""
    spec = TextExtract(mode="text", max_chars=max_chars, pages=pages)
    result = run(pdf_bytes(["aaaa", "bbbb", "cccc"]), spec)
    assert texts(result) == expected
    assert result.next_pages == next_pages
    assert result.truncated == (expected != ["cccc"])
    assert sum(map(len, texts(result))) <= max_chars


def test_text_file_is_cut_into_pages_of_max_chars() -> None:
    result = run(b"col\n1\n2\n", TextExtract(mode="text", max_chars=5), "r.csv")
    assert texts(result) == ["col\n1"]
    assert (result.page_count, result.next_pages) == (2, "2")


def test_images_render_requested_pdf_pages_within_budget() -> None:
    spec = ImageExtract(mode="images", max_long_side=100, max_images=1, pages="2-3")
    result = run(pdf_bytes(["a", "b", "c"]), spec)
    [page] = images(result)
    assert page.page == 2
    assert (page.width, page.height) == (67, 100)
    assert (page.original_width, page.original_height) == (200, 300)
    assert page.image.startswith(b"\xff\xd8")
    assert (result.truncated, result.next_pages) == (True, "3")


def test_images_shrink_a_large_image() -> None:
    content = image_bytes(Image.new("RGB", (3000, 1500)), "PNG")
    [page] = images(run(content, ImageExtract(mode="images")))
    assert (page.width, page.height) == (1000, 500)
    assert (page.original_width, page.original_height) == (3000, 1500)


def test_images_strip_exif_and_turn_the_photo_upright() -> None:
    content = exif_jpeg()
    assert Image.open(io.BytesIO(content)).getexif().get_ifd(ExifTags.IFD.GPSInfo)

    [page] = images(run(content, ImageExtract(mode="images")))
    out = Image.open(io.BytesIO(page.image))
    assert not out.getexif()
    assert "exif" not in out.info
    assert out.size == (20, 40)
    red, green, blue = out.getpixel((10, 5))
    assert red > 200 and blue < 60
    red, green, blue = out.getpixel((10, 35))
    assert blue > 200 and red < 60


def test_images_give_one_page_per_tiff_frame() -> None:
    frames = [Image.new("RGB", (10, 10), color) for color in ("red", "blue")]
    content = image_bytes(frames[0], "TIFF", save_all=True, append_images=frames[1:])
    result = run(content, ImageExtract(mode="images"))
    assert [page.page for page in images(result)] == [1, 2]
    assert result.page_count == 2


def docx_like() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("content", "spec"),
    [
        (exif_jpeg(), TextExtract(mode="text")),
        (b"col\n1\n", ImageExtract(mode="images")),
        (docx_like(), TextExtract(mode="text")),
        (docx_like(), ImageExtract(mode="images")),
    ],
)
def test_a_mode_the_file_cannot_serve_returns_metadata_only(
    content: bytes, spec: TextExtract | ImageExtract
) -> None:
    result = run(content, spec)
    assert result.pages == []
    assert result.page_count is None
    assert result.size == len(content)


@pytest.mark.parametrize(
    ("content", "pages", "match"),
    [
        (b"%PDF-1.4 garbage", None, "not a readable PDF"),
        (pdf_bytes(["a"]), "2", "past the last page"),
    ],
)
def test_unreadable_input_is_a_step_failure(
    content: bytes, pages: str | None, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        run(content, TextExtract(mode="text", pages=pages))


@pytest.mark.parametrize(
    ("method", "spec"),
    [
        ("get_textpage", TextExtract(mode="text")),
        ("render", ImageExtract(mode="images")),
    ],
)
def test_a_page_pdfium_cannot_read_is_a_step_failure(
    monkeypatch: pytest.MonkeyPatch, method: str, spec: TextExtract | ImageExtract
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise pypdfium2.PdfiumError("bad page")

    monkeypatch.setattr(pypdfium2.PdfPage, method, broken)
    with pytest.raises(ValueError, match="page 1 unreadable"):
        run(pdf_bytes(["a"]), spec)


def test_extracted_text_is_redacted() -> None:
    result = run(pdf_bytes(["token s3cret here"]), TextExtract(mode="text"))
    assert texts(redact_secrets(result, ["s3cret"])) == ["token *** here"]


def test_missing_documents_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(ValueError, match=r"llm-browser\[documents\]"):
        run(b"text", TextExtract(mode="text"))
