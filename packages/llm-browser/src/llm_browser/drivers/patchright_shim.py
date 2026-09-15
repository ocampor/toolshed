"""Start patchright with its Node driver bundle guarded against closed CDP sessions."""

import importlib.metadata
import os
import shutil
import tempfile
from pathlib import Path

import patchright
from patchright.sync_api import Playwright, sync_playwright

# debt: patchright's CRPage constructor fires this uncaught, killing the Node driver on a closed session; drop once upstream guards it — ocampor/toolshed#41
UNGUARDED = "this._networkManager.setRequestInterception(true);"
GUARDED = "this._networkManager.setRequestInterception(true).catch(() => {});"

BUNDLE_PATH = Path(patchright.__file__).parent / "driver/package/lib/coreBundle.js"

_guarded = False


def start_playwright() -> Playwright:
    """The only supported way to start patchright: guard the bundle, then start."""
    ensure_request_interception_guarded()
    return sync_playwright().start()


def ensure_request_interception_guarded() -> None:
    global _guarded
    if _guarded:
        return
    text = BUNDLE_PATH.read_text(encoding="utf-8")
    unguarded = text.count(UNGUARDED)
    if unguarded == 0:
        _guarded = True
        return
    if unguarded != 1:
        version = importlib.metadata.version("patchright")
        raise RuntimeError(
            f"Cannot guard patchright {version}: {BUNDLE_PATH} holds {unguarded} "
            f"occurrences of {UNGUARDED!r}, expected exactly one. The shim no "
            "longer matches this patchright release and must be re-checked."
        )
    fd, tmp_name = tempfile.mkstemp(dir=BUNDLE_PATH.parent, suffix=".tmp")
    tmp = Path(tmp_name)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text.replace(UNGUARDED, GUARDED))
    shutil.copymode(
        BUNDLE_PATH, tmp
    )  # keep mode: a Node driver running as another user must still read it
    os.replace(tmp, BUNDLE_PATH)
    _guarded = True
