"""Addressing a tab by its CDP target id instead of ``pages[-1]``."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.cli import build_session
from llm_browser.drivers.base import Driver, DriverHandle
from llm_browser.drivers.patchright import (
    PatchrightDriver,
    find_page_by_target_id,
    page_target_id,
)
from llm_browser.session import BrowserSession
from tests.test_attach import AttachStubDriver

CDP_URL = "http://127.0.0.1:9223"


def fake_context(target_ids: list[str]) -> Any:
    """A context whose pages answer ``Target.getTargetInfo`` with ``target_ids``."""
    pages = [MagicMock(name=f"page-{tid}") for tid in target_ids]
    by_page = {id(page): tid for page, tid in zip(pages, target_ids)}
    context = MagicMock()
    context.pages = pages

    def new_cdp_session(page: Any) -> Any:
        cdp = MagicMock()
        cdp.send.return_value = {"targetInfo": {"targetId": by_page[id(page)]}}
        return cdp

    context.new_cdp_session.side_effect = new_cdp_session
    return context


def fake_playwright(monkeypatch: pytest.MonkeyPatch, context: Any) -> Any:
    browser = MagicMock()
    browser.contexts = [context]
    pw = MagicMock()
    pw.chromium.connect_over_cdp.return_value = browser
    monkeypatch.setattr(
        "llm_browser.drivers.patchright.sync_playwright",
        lambda: MagicMock(start=lambda: pw),
    )
    return pw


def attached_handle(target_id: str | None) -> DriverHandle:
    extra = {"attached": "1"}
    if target_id is not None:
        extra["target_id"] = target_id
    return DriverHandle(
        driver="patchright", endpoint=CDP_URL, user_data_dir="", extra=extra
    )


def test_page_target_id_reads_and_detaches() -> None:
    context = fake_context(["ABC"])
    assert page_target_id(context, context.pages[0]) == "ABC"


@pytest.mark.parametrize("wanted", ["A", "C"])
def test_find_page_by_target_id_finds_any_position(wanted: str) -> None:
    context = fake_context(["A", "B", "C"])
    expected = context.pages[["A", "B", "C"].index(wanted)]
    assert find_page_by_target_id(context, wanted) is expected


def test_find_page_by_target_id_raises_when_closed() -> None:
    context = fake_context(["A", "B"])
    with pytest.raises(RuntimeError, match="Tab Z not found; it was closed."):
        find_page_by_target_id(context, "Z")


def test_attach_records_new_tab_target_id(monkeypatch: pytest.MonkeyPatch) -> None:
    context = fake_context(["NEW"])
    new_page = context.pages[0]
    context.new_page.return_value = new_page
    fake_playwright(monkeypatch, context)

    handle = PatchrightDriver().attach(CDP_URL)
    assert handle.extra["target_id"] == "NEW"
    assert handle.extra["attached"] == "1"


def test_attach_to_tab_resolves_existing_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    context = fake_context(["A", "B"])
    fake_playwright(monkeypatch, context)

    driver = PatchrightDriver()
    handle = driver.attach_to_tab(CDP_URL, "B")
    assert handle.extra["target_id"] == "B"
    assert driver.page(handle) is context.pages[1]


def test_attach_to_tab_raises_for_closed_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_playwright(monkeypatch, fake_context(["A"]))
    with pytest.raises(RuntimeError, match="not found"):
        PatchrightDriver().attach_to_tab(CDP_URL, "GONE")


def test_reattach_resolves_by_target_id_not_last_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = fake_context(["MINE", "SOMEONE-ELSES"])
    fake_playwright(monkeypatch, context)

    page = PatchrightDriver().page(attached_handle("MINE"))
    assert page is context.pages[0]


def test_reattach_without_target_id_picks_the_last_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy handle (pre-target-id state.json) reconnects to the last tab."""
    context = fake_context(["A", "B"])
    fake_playwright(monkeypatch, context)

    page = PatchrightDriver().page(attached_handle(None))
    assert page is context.pages[-1]


def test_find_page_by_target_id_skips_unhealthy_tabs() -> None:
    """A crashed sibling tab must not hide the tab we are addressing."""
    context = fake_context(["BROKEN", "MINE"])
    healthy = context.new_cdp_session.side_effect

    def new_cdp_session(page: Any) -> Any:
        if page is context.pages[0]:
            raise RuntimeError("Target closed")
        return healthy(page)

    context.new_cdp_session.side_effect = new_cdp_session

    assert find_page_by_target_id(context, "MINE") is context.pages[1]


def test_reattach_raises_when_target_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_playwright(monkeypatch, fake_context(["OTHER"]))
    with pytest.raises(RuntimeError, match="Tab MINE not found"):
        PatchrightDriver().page(attached_handle("MINE"))


def test_base_driver_attach_to_tab_raises() -> None:
    class NoAttach(AttachStubDriver):
        def attach_to_tab(self, cdp_url: str, target_id: str) -> DriverHandle:
            return Driver.attach_to_tab(self, cdp_url, target_id)

    with pytest.raises(NotImplementedError):
        NoAttach().attach_to_tab(CDP_URL, "A")


def test_session_attach_persists_target_id(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path, driver=AttachStubDriver())
    result = session.attach(CDP_URL)

    assert result.target_id == "stub-tab"
    info = session._load_state()
    assert info is not None and info.target_id == "stub-tab"
    assert session._handle_from_state(info).extra["target_id"] == "stub-tab"


def test_session_attach_to_tab_uses_driver(tmp_path: Path) -> None:
    driver = AttachStubDriver()
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    result = session.attach_to_tab(CDP_URL, "ABC")

    assert driver.attach_to_tab_calls == [(CDP_URL, "ABC")]
    assert result.target_id == "ABC"
    assert session.status().target_id == "ABC"


def test_stateless_session_never_writes_state(tmp_path: Path) -> None:
    session = BrowserSession(
        state_dir=tmp_path, driver=AttachStubDriver(), stateless=True
    )
    session.attach_to_tab(CDP_URL, "ABC")

    assert not session._state_file.exists()
    assert session.status().status == "open"
    session.close()
    assert not session._state_file.exists()


def test_stateless_session_ignores_an_existing_state_file(tmp_path: Path) -> None:
    stateful = BrowserSession(state_dir=tmp_path, driver=AttachStubDriver())
    stateful.attach(CDP_URL)

    fresh = BrowserSession(
        state_dir=tmp_path, driver=AttachStubDriver(), stateless=True
    )
    assert fresh.status().status == "closed"
    assert stateful._state_file.exists()


def test_build_session_without_cdp_url_is_stateful() -> None:
    session = build_session("default", None, None, None, None)
    assert session.stateless is False
    assert isinstance(session.driver, Driver)


def test_build_session_with_target_id_attaches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = AttachStubDriver()
    monkeypatch.setattr("llm_browser.session.resolve_driver", lambda _d: driver)

    session = build_session("default", None, None, CDP_URL, "ABC")
    assert session.stateless is True
    assert driver.attach_to_tab_calls == [(CDP_URL, "ABC")]


def test_build_session_with_cdp_url_only_does_not_attach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = AttachStubDriver()
    monkeypatch.setattr("llm_browser.session.resolve_driver", lambda _d: driver)

    session = build_session("default", None, None, CDP_URL, None)
    assert session.stateless is True
    assert driver.attach_to_tab_calls == []
    assert driver.attach_calls == []
