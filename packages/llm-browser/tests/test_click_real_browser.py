"""The humanized click against a real Chromium: does the hit test the click
trusts — run in patchright's isolated world — see what the page itself sees?

The fakes elsewhere can only prove the plumbing. Isolated-world
``elementFromPoint`` reading a different element than the main world's would
make every refusal and every reported hit a lie, and nothing but a browser
can answer that.
"""

import random
from pathlib import Path
from typing import Any, Iterator

import pytest

from llm_browser import session_input
from llm_browser.behavior import Behavior
from llm_browser.session import BrowserSession

# A fixed nav whose hover menu drops over the page, and a logout link far
# below the fold: the shape the hit test was written for.
PAGE = """
<style>
  body { margin: 0; height: 3000px; font: 16px sans-serif; }
  nav { position: fixed; top: 0; left: 0; right: 0; height: 60px;
        background: #223344; color: #fff; padding: 18px; }
  nav .menu { display: none; position: absolute; top: 60px; left: 0; right: 0;
              height: 200px; margin: 0; padding: 0; background: #cceeff; }
  nav:hover .menu { display: block; }
  nav .menu li { list-style: none; padding: 24px; }
  a.logout { position: absolute; top: 2400px; left: 120px; padding: 14px 22px;
             background: #eeeeee; }
</style>
<nav>Cuenta
  <ul class="menu"><li class="menu-item">Estados de cuenta</li></ul>
</nav>
<a class="logout" id="logout" href="#gone"><span class="label">Salir</span></a>
"""


@pytest.fixture
def live_session(tmp_path: Path) -> Iterator[BrowserSession]:
    session = BrowserSession(
        state_dir=tmp_path, driver="patchright", behavior=Behavior.human()
    )
    try:
        session.launch(headed=False)
    except Exception as exc:
        pytest.skip(f"patchright chromium would not launch: {exc}")
    try:
        yield session
    finally:
        session.close()


def main_world_at(cdp: Any, point: tuple[float, float]) -> str:
    """``tag|class`` of whatever the *page's own* world finds at ``point``.

    ``Runtime.evaluate`` with no context id is the main world; patchright's
    ``evaluate`` deliberately is not, which is the whole question here.
    """
    read = cdp.send(
        "Runtime.evaluate",
        {
            "expression": (
                f"(() => {{ const at = document.elementFromPoint{point};"
                " return at ? at.tagName.toLowerCase() + '|' + at.className"
                " : 'nothing'; })()"
            ),
            "returnByValue": True,
        },
    )
    return str(read["result"]["value"])


def test_hit_test_agrees_with_the_main_world_in_patchright(
    live_session: BrowserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    random.seed(20260916)
    page = live_session.get_page()
    page.set_content(PAGE)
    cdp = page.context.new_cdp_session(page)
    jumped: list[Any] = []
    monkeypatch.setattr(
        type(live_session.driver),
        "scroll_into_view",
        lambda self, el: jumped.append(el),
    )

    seen: list[str] = []
    checks = session_input.hit_test_after_move

    def watched(session: Any, element: Any, behavior: Behavior) -> Any:
        check = checks(session, element, behavior)

        def spy(point: tuple[float, float]) -> Any:
            seen.append(main_world_at(cdp, point))
            return check(point)

        return spy

    monkeypatch.setattr(session_input, "hit_test_after_move", watched)

    try:
        hit = live_session.click("#logout")
    except ValueError as refusal:
        # The path crossed the nav and the menu it opened took the point.
        assert "covered-after-move" in str(refusal)
        assert seen == ["li|menu-item"]
    else:
        assert hit is not None
        assert seen == [f"{hit.tag}|{hit.class_name}"]
        assert hit.tag in {"a", "span"}

    # The wheel, not the programmatic jump, is what brought the link in.
    assert page.evaluate("() => window.scrollY") > 0
    assert jumped == []
