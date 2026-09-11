"""The library never writes output files; only the CLI does.

Written as a check over the source rather than over behaviour: a new call to
``write_text`` in an action or a driver would pass every other test in this
suite and quietly put the design decision back where it was.
"""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "llm_browser"

WRITE_METHODS = {"write_text", "write_bytes"}
WRITE_MODES = set("wax")

# Every module allowed to put bytes on disk, and why it earns the exemption.
ALLOWED = {
    "cli.py": "the CLI is what writes what a run returned",
    "session.py": "state.json is how a detached browser is found again",
    "skill_install.py": "`skill install` copies a packaged asset on request",
}


def writes_a_file(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS:
        return True
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name != "open":
        return False
    modes = [a for a in node.args[1:2] if isinstance(a, ast.Constant)]
    modes += [k.value for k in node.keywords if k.arg == "mode"]
    return any(
        isinstance(m, ast.Constant)
        and isinstance(m.value, str)
        and WRITE_MODES & set(m.value)
        for m in modes
    )


def writing_modules() -> dict[str, list[int]]:
    """Module path (relative to the package) to the lines that write a file."""
    found = {}
    for source in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(source.read_text())
        lines = [n.lineno for n in ast.walk(tree) if writes_a_file(n)]
        if lines:
            found[str(source.relative_to(SOURCE_ROOT))] = lines
    return found


def test_only_the_allowlisted_modules_write_files() -> None:
    assert set(writing_modules()) == set(ALLOWED)


def test_the_check_can_see_a_write() -> None:
    """Guard the guard: a check that recognises nothing always passes."""
    assert writes_a_file(ast.parse('p.write_bytes(b"x")').body[0].value)  # type: ignore[attr-defined]
    assert writes_a_file(ast.parse('open(p, "w")').body[0].value)  # type: ignore[attr-defined]
    assert not writes_a_file(ast.parse("p.read_bytes()").body[0].value)  # type: ignore[attr-defined]
    assert not writes_a_file(ast.parse('open(p, "r")').body[0].value)  # type: ignore[attr-defined]
