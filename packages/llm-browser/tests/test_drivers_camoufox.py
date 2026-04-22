"""Tests for CamoufoxDriver. Skipped when the camoufox extra is not installed."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("camoufox")

from llm_browser.drivers.camoufox import CamoufoxDriver  # noqa: E402


def _install_mock_camoufox(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub the Camoufox loader to return a mock factory."""
    page = MagicMock()
    context = MagicMock()
    context.pages = [page]
    factory = MagicMock()
    factory.return_value.__enter__.return_value = context
    factory.return_value.__exit__.return_value = None
    module = MagicMock()
    module.Camoufox = factory
    monkeypatch.setattr(
        "llm_browser.drivers.camoufox.load_optional_module", lambda *a, **kw: module
    )
    return factory


def test_registry_exposes_camoufox() -> None:
    from llm_browser.drivers import get_registry

    assert "camoufox" in get_registry()


def test_launch_invokes_camoufox_with_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver(locale="fr-FR", humanize=True)
    handle = driver.launch(
        user_data_dir=tmp_path, url="https://example.com", headed=False
    )

    assert handle.driver == "camoufox"
    assert handle.user_data_dir == str(tmp_path)
    factory.assert_called_once()
    kwargs = factory.call_args.kwargs
    assert kwargs["locale"] == "fr-FR"
    assert kwargs["humanize"] is True
    assert kwargs["headless"] is True
    assert kwargs["persistent_context"] is True
    assert kwargs["user_data_dir"] == str(tmp_path)


def test_launch_applies_stealth_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver()
    driver.launch(user_data_dir=tmp_path, url=None, headed=False)

    kwargs = factory.call_args.kwargs
    assert kwargs["humanize"] is True
    assert kwargs["block_webrtc"] is True


def test_user_kwargs_override_stealth_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver(humanize=False, block_webrtc=False)
    driver.launch(user_data_dir=tmp_path, url=None, headed=False)

    kwargs = factory.call_args.kwargs
    assert kwargs["humanize"] is False
    assert kwargs["block_webrtc"] is False


def test_locale_without_geo_keys_injects_geoip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver(locale="fr-FR")
    driver.launch(user_data_dir=tmp_path, url=None, headed=False)

    assert factory.call_args.kwargs["geoip"] is True


def test_locale_with_timezone_leaves_geoip_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver(locale="fr-FR", timezone="Europe/Paris")
    driver.launch(user_data_dir=tmp_path, url=None, headed=False)

    assert "geoip" not in factory.call_args.kwargs


def test_no_locale_no_geoip_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver()
    driver.launch(user_data_dir=tmp_path, url=None, headed=False)

    assert "geoip" not in factory.call_args.kwargs


def test_user_kwargs_override_lifecycle_positionals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver(persistent_context=False, headless=True)
    driver.launch(user_data_dir=tmp_path, url=None, headed=True)

    kwargs = factory.call_args.kwargs
    assert kwargs["persistent_context"] is False
    assert kwargs["headless"] is True


def test_fill_clears_then_types_per_char(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm_browser.behavior.time.sleep", lambda _s: None)
    driver = CamoufoxDriver()
    locator = MagicMock()
    driver.fill(locator, "hi")

    locator.fill.assert_called_once_with("")
    assert locator.type.call_args_list == [
        (("h",), {"delay": 0}),
        (("i",), {"delay": 0}),
    ]


def test_fill_empty_string_only_clears() -> None:
    driver = CamoufoxDriver()
    locator = MagicMock()
    driver.fill(locator, "")

    locator.fill.assert_called_once_with("")
    locator.type.assert_not_called()


def test_type_default_delay_jitters_per_char(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("llm_browser.behavior.time.sleep", lambda s: sleeps.append(s))
    driver = CamoufoxDriver()
    locator = MagicMock()
    driver.type(locator, "abc")

    assert locator.type.call_count == 3
    assert len(sleeps) == 3
    assert all(0.030 <= s <= 0.090 for s in sleeps)


def test_type_explicit_delay_uses_playwright_uniform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept = False

    def _record_sleep(_s: float) -> None:
        nonlocal slept
        slept = True

    monkeypatch.setattr("llm_browser.behavior.time.sleep", _record_sleep)
    driver = CamoufoxDriver()
    locator = MagicMock()
    driver.type(locator, "hi", delay_ms=50)

    locator.type.assert_called_once_with("hi", delay=50)
    assert slept is False


def test_page_returns_active_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver()
    handle = driver.launch(user_data_dir=tmp_path, url=None, headed=False)
    page = driver.page(handle)

    assert page is factory.return_value.__enter__.return_value.pages[0]


def test_page_without_launch_raises(tmp_path: Path) -> None:
    driver = CamoufoxDriver()
    with pytest.raises(RuntimeError, match="no live page"):
        driver.page(MagicMock())


def test_close_tears_down_camoufox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    driver = CamoufoxDriver()
    handle = driver.launch(user_data_dir=tmp_path, url=None, headed=False)
    driver.close(handle)

    factory.return_value.__exit__.assert_called_once_with(None, None, None)
    assert driver.status(handle) is False


def test_status_false_before_launch() -> None:
    driver = CamoufoxDriver()
    assert driver.status(MagicMock()) is False


def test_latest_tab_returns_last_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _install_mock_camoufox(monkeypatch)
    context = factory.return_value.__enter__.return_value
    first, second = MagicMock(), MagicMock()
    context.pages = [first, second]

    driver = CamoufoxDriver()
    handle = driver.launch(user_data_dir=tmp_path, url=None, headed=False)
    assert driver.latest_tab(handle) is second
