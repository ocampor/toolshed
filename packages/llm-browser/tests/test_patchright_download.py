from types import SimpleNamespace
from typing import Any

import pytest

from llm_browser.drivers.patchright_download import file_name, find_url, frame_for


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


TREE = {
    "frame": {"id": "ROOT", "url": "https://bank.test/"},
    "childFrames": [
        {
            "frame": {"id": "MID", "url": "https://bank.test/mid"},
            "childFrames": [{"frame": {"id": "LEAF", "url": "https://bank.test/leaf"}}],
        }
    ],
}


@pytest.mark.parametrize(
    ("frame_id", "expected"),
    [
        ("ROOT", "https://bank.test/"),
        ("LEAF", "https://bank.test/leaf"),
        ("GONE", None),
    ],
)
def test_find_url_walks_the_frame_tree(frame_id: str, expected: str | None) -> None:
    assert find_url(TREE, frame_id) == expected


def fake_frame(url: str, tree: dict[str, Any] | None) -> SimpleNamespace:
    """A frame whose CDP session reports ``tree``; None has no session of its own."""

    def new_cdp_session(frame: SimpleNamespace) -> SimpleNamespace:
        if tree is None:
            raise RuntimeError("in-process frame")
        return SimpleNamespace(
            send=lambda method: {"frameTree": tree}, detach=lambda: None
        )

    context = SimpleNamespace(new_cdp_session=new_cdp_session)
    return SimpleNamespace(url=url, page=SimpleNamespace(context=context))


def fake_tab() -> SimpleNamespace:
    main = fake_frame("https://bank.test/", TREE)
    leaf = fake_frame("https://bank.test/leaf", None)
    oopif = fake_frame(
        "https://pay.test/", {"frame": {"id": "OOPIF", "url": "https://pay.test/"}}
    )
    return SimpleNamespace(frames=[main, leaf, oopif])


@pytest.mark.parametrize(
    ("frame_id", "url", "expected"),
    [
        ("ROOT", "blob:https://bank.test/x", 0),
        ("OOPIF", "blob:https://pay.test/x", 2),
        ("LEAF", "blob:https://bank.test/x", 1),
        ("ELSEWHERE", "blob:https://pay.test/x", 2),
        ("ELSEWHERE", "blob:https://other.test/x", None),
    ],
    ids=["root", "out-of-process", "in-process child", "origin", "not this tab"],
)
def test_frame_for_maps_a_download_to_this_tab_only(
    frame_id: str, url: str, expected: int | None
) -> None:
    tab = fake_tab()
    frame = frame_for([tab], frame_id, url)
    assert frame is (None if expected is None else tab.frames[expected])
