"""Tests for the patchright coreBundle.js request-interception guard."""

import stat

import pytest

from llm_browser.drivers import patchright_shim
from llm_browser.drivers.patchright_shim import (
    GUARDED,
    UNGUARDED,
    ensure_request_interception_guarded,
)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    path = tmp_path / "coreBundle.js"
    monkeypatch.setattr(patchright_shim, "BUNDLE_PATH", path)
    monkeypatch.setattr(patchright_shim, "_guarded", False)
    return path


@pytest.mark.parametrize("body", [GUARDED, "no interception call here"])
def test_bundle_with_no_unguarded_call_is_left_alone(bundle, body):
    bundle.write_text(body, encoding="utf-8")

    ensure_request_interception_guarded()

    assert bundle.read_text(encoding="utf-8") == body


def test_unguarded_bundle_is_patched(bundle):
    bundle.write_text(f"before {UNGUARDED} after", encoding="utf-8")
    bundle.chmod(0o644)

    ensure_request_interception_guarded()

    patched = bundle.read_text(encoding="utf-8")
    assert UNGUARDED not in patched
    assert GUARDED in patched
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o644


def test_bundle_with_two_unguarded_calls_raises_with_version(bundle):
    bundle.write_text(f"{UNGUARDED}\n{UNGUARDED}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="patchright"):
        ensure_request_interception_guarded()


def test_second_call_skips_rereading_the_bundle(bundle):
    bundle.write_text(GUARDED, encoding="utf-8")
    ensure_request_interception_guarded()
    bundle.unlink()

    ensure_request_interception_guarded()
