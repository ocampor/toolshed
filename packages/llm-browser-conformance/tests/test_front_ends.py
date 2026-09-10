"""The CLI and the pytest wrapper must report the same run the same way.

They share ``run_scenario``, so this pins the only place they could drift:
the translation of a verdict into a pytest report. Runs pytest in a
subprocess over the synthetic scenarios — no browser, about a second.
"""

import subprocess
import sys
from collections import Counter
from pathlib import Path

from llm_browser_conformance.runner import run_scenario
from tests.fakes import FAKE_SCENARIOS, fake_context
from tests.support import PYTEST_VERDICT

TESTS_DIR = Path(__file__).parent

GENERATED = """
import pytest

from llm_browser_conformance.runner import run_scenario
from tests.fakes import FAKE_SCENARIOS, fake_context
from tests.support import check


@pytest.mark.parametrize("scenario", FAKE_SCENARIOS, ids=lambda s: s.name)
def test_scenario(scenario):
    check(run_scenario(scenario, fake_context()))
"""


def test_the_two_front_ends_agree(tmp_path: Path) -> None:
    module = tmp_path / "test_generated_front_end.py"
    module.write_text(GENERATED)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(module)],
        check=False,
        capture_output=True,
        text=True,
        cwd=TESTS_DIR.parent,
    )
    from_pytest = parse_counts(completed.stdout)
    from_cli = Counter(
        PYTEST_VERDICT[run_scenario(s, fake_context()).outcome] for s in FAKE_SCENARIOS
    )
    assert from_pytest == dict(from_cli), completed.stdout


def parse_counts(output: str) -> dict[str, int]:
    """The last summary line, e.g. ``2 failed, 3 passed, 1 skipped, 1 xfailed``."""
    summary = [
        line for line in output.splitlines() if " passed" in line or " failed" in line
    ]
    assert summary, output
    counts: dict[str, int] = {}
    for chunk in summary[-1].replace("=", " ").split(","):
        parts = chunk.split()
        for index, word in enumerate(parts[:-1]):
            if word.isdigit() and parts[index + 1] in PYTEST_VERDICT.values():
                counts[parts[index + 1]] = int(word)
    return counts
