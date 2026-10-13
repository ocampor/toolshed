from types import SimpleNamespace
from typing import Any

import pytest

from llm_browser.drivers.patchright_inpage import find_url, frame_for

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


def detached_frame() -> SimpleNamespace:
    """A frame that goes away between its session opening and answering."""

    def gone(*args: object) -> None:
        raise RuntimeError("Target closed")

    session = SimpleNamespace(send=gone, detach=gone)
    context = SimpleNamespace(new_cdp_session=lambda frame: session)
    return SimpleNamespace(
        url="https://pay.test/gone", page=SimpleNamespace(context=context)
    )


def fake_tab() -> SimpleNamespace:
    main = fake_frame("https://bank.test/", TREE)
    leaf = fake_frame("https://bank.test/leaf", None)
    oopif = fake_frame(
        "https://pay.test/", {"frame": {"id": "OOPIF", "url": "https://pay.test/"}}
    )
    return SimpleNamespace(frames=[detached_frame(), main, leaf, oopif])


@pytest.mark.parametrize(
    ("frame_id", "expected"),
    [("ROOT", 1), ("OOPIF", 3), ("LEAF", 2), ("ELSEWHERE", None)],
    ids=["root", "out-of-process", "in-process child", "not this tab"],
)
def test_frame_for_maps_a_download_to_this_tab_only(
    frame_id: str, expected: int | None
) -> None:
    tab = fake_tab()
    frame = frame_for([tab], frame_id)
    assert frame is (None if expected is None else tab.frames[expected])
