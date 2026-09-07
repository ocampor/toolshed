"""Push notifications to an ntfy topic over stdlib urllib."""

import os
import urllib.error
import urllib.request

from llm_browser.constants import (
    NOTIFY_TIMEOUT_S,
    NTFY_TOKEN_ENV_VAR,
    NTFY_URL_ENV_VAR,
    VNC_URL_ENV_VAR,
)


class NotifyError(ValueError):
    """Notification could not be sent.

    A ``ValueError`` subclass so ``execute_action`` turns it into an
    ``ErrorResult`` (or swallows it on ``optional: true``) instead of
    unwinding the whole flow.
    """


def default_click_url() -> str | None:
    """Fallback ``Click`` target: the VNC console where a human can take over."""
    return os.environ.get(VNC_URL_ENV_VAR) or None


def build_headers(
    *, title: str | None, priority: int | None, click: str | None
) -> dict[str, str]:
    optional = {
        "Title": title,
        "Priority": priority,
        "Click": click or default_click_url(),
        "Authorization": _bearer(),
    }
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    headers.update({k: str(v) for k, v in optional.items() if v is not None})
    return headers


def _bearer() -> str | None:
    token = os.environ.get(NTFY_TOKEN_ENV_VAR)
    return f"Bearer {token}" if token else None


def send_notification(
    message: str,
    *,
    title: str | None = None,
    priority: int | None = None,
    click: str | None = None,
) -> None:
    """POST ``message`` to the ntfy topic in ``LLM_BROWSER_NTFY_URL``."""
    url = os.environ.get(NTFY_URL_ENV_VAR)
    if not url:
        raise NotifyError(f"{NTFY_URL_ENV_VAR} is not set; cannot send notification")
    request = urllib.request.Request(
        url,
        data=message.encode(),
        headers=build_headers(title=title, priority=priority, click=click),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=NOTIFY_TIMEOUT_S) as response:
            response.read()
    except OSError as exc:
        # URLError/HTTPError/socket timeouts all land here; a paging
        # failure should surface as a step error, not crash the run.
        raise NotifyError(f"notification POST to {url} failed: {exc}") from exc
