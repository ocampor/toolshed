"""pytest wrapper around the same scenario list ``llm-browser-check`` runs.

Browsers are expensive and this package is validated in CI like any other, so
the whole suite is skipped unless ``--real`` is passed.
"""

from collections.abc import Iterator

import pytest
from llm_browser.session import BrowserSession

from llm_browser_conformance.drivers import (
    installed_drivers,
    launched_session,
    unavailable,
)
from llm_browser_conformance.scenario import DEFAULT_DELAY_MS, Context, Scenario
from llm_browser_conformance.scenarios import ALL_SCENARIOS
from llm_browser_conformance.server import serve_site


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--real",
        action="store_true",
        default=False,
        help="Actually launch browsers and run the conformance scenarios.",
    )
    parser.addoption(
        "--driver",
        action="append",
        default=[],
        metavar="NAME",
        help="Driver to check; repeatable. Defaults to every installed driver.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--real"):
        return
    skip_real = pytest.mark.skip(reason="real-browser suite: pass --real to run it")
    for item in items:
        item.add_marker(skip_real)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "driver_name" in metafunc.fixturenames:
        selected: list[str] = list(metafunc.config.getoption("--driver"))
        metafunc.parametrize(
            "driver_name",
            selected or installed_drivers(),
            indirect=True,
            scope="module",
        )
    if "scenario" in metafunc.fixturenames:
        metafunc.parametrize(
            "scenario", ALL_SCENARIOS, ids=lambda s: s.name.replace(" ", "-")
        )


@pytest.fixture(scope="session")
def site_url() -> Iterator[str]:
    with serve_site() as url:
        yield url


@pytest.fixture(scope="module")
def driver_name(request: pytest.FixtureRequest) -> str:
    name: str = request.param
    return name


@pytest.fixture(scope="module")
def session(driver_name: str) -> Iterator[BrowserSession]:
    reason = unavailable(driver_name)
    if reason:
        pytest.skip(f"{driver_name}: {reason}")
    with launched_session(driver_name) as browser:
        yield browser


@pytest.fixture
def ctx(session: BrowserSession, driver_name: str, site_url: str) -> Context:
    return Context(session, site_url, driver_name, DEFAULT_DELAY_MS)


@pytest.fixture
def scenario(request: pytest.FixtureRequest) -> Scenario:
    scenario: Scenario = request.param
    return scenario
