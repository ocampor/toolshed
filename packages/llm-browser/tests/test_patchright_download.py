import pytest

from llm_browser.drivers.patchright_download import file_name


@pytest.mark.parametrize(
    ("content_disposition", "url", "expected"),
    [
        (
            'inline; filename="ComprobanteSATDPA.pdf"',
            "https://bank.test/billtax/print.action",
            "ComprobanteSATDPA.pdf",
        ),
        ("attachment; filename=report.zip", "https://site.test/get?id=1", "report.zip"),
        ("", "https://www.irs.gov/pub/irs-pdf/f1040.pdf", "f1040.pdf"),
        ('inline; filename="../../etc/passwd"', "https://site.test/x", "passwd"),
    ],
)
def test_file_name_prefers_the_header_and_keeps_only_a_basename(
    content_disposition: str, url: str, expected: str
) -> None:
    assert file_name(content_disposition, url) == expected
