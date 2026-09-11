"""The library never writes output files; only the CLI does.

Written as a check over the source rather than over behaviour: a new call to
``write_text`` in an action or a driver would pass every other test in this
suite and quietly put the design decision back where it was.

The detector is deliberately broad. It is not a sandbox — anything determined
to write can — but every *ordinary* way to put bytes on disk should trip it,
because the failure mode being guarded against is a reasonable-looking edit,
not an adversary.
"""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "llm_browser"

# Methods that write wherever they are called.
WRITE_METHODS = {"write_text", "write_bytes"}

# Dotted helpers that write, copy or move a file. Matched on the whole dotted
# name so a local `move()` of your own is not mistaken for `shutil.move`.
WRITE_HELPERS = {
    "os.open",
    "os.rename",
    "os.replace",
    "os.link",
    "os.symlink",
    "os.mkfifo",
    "os.truncate",
    "os.writev",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.copyfileobj",
    "shutil.copytree",
    "shutil.move",
    "tempfile.NamedTemporaryFile",
    "tempfile.mkstemp",
    "json.dump",
    "pickle.dump",
    "csv.writer",
    "csv.DictWriter",
    "np.save",
    "numpy.save",
}

# `open(...)` in a mode that can create or change a file.
WRITE_MODES = set("wax+")

# Every module allowed to put bytes on disk, and why it earns the exemption.
ALLOWED = {
    "cli.py": "the CLI is what writes what a run returned",
    "state.py": "state.json is how a detached browser is found again",
    "skill_install.py": "`skill install` copies a packaged asset on request",
}


def dotted_name(node: ast.expr) -> str:
    """``shutil.copyfileobj`` for an Attribute chain, ``open`` for a Name."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def opens_for_writing(call: ast.Call) -> bool:
    """Whether ``call`` is an ``open`` in a writing mode.

    The mode is the second argument of ``open(path, mode)`` but the *first* of
    ``path.open(mode)``, which is why the position depends on the call shape —
    missing that is how ``Path.open("w")`` slips past a naive check.
    """
    name = dotted_name(call.func)
    if name != "open" and not name.endswith(".open"):
        return False
    positional = (
        call.args[0:1] if isinstance(call.func, ast.Attribute) else call.args[1:2]
    )
    modes = [*positional, *(kw.value for kw in call.keywords if kw.arg == "mode")]
    return any(
        isinstance(mode, ast.Constant)
        and isinstance(mode.value, str)
        and WRITE_MODES & set(mode.value)
        for mode in modes
    )


def file_handles(tree: ast.AST) -> set[str]:
    """Names bound to an ``open(...)`` call, by assignment or ``with``.

    ``handle.write(...)`` says nothing on its own — it could be a socket or a
    StringIO — so it only counts as a file write when the name came from
    ``open``.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _is_open(node.value):
                targets = list(node.targets)
        elif isinstance(node, ast.With | ast.AsyncWith):
            targets = [
                item.optional_vars
                for item in node.items
                if item.optional_vars is not None
                and isinstance(item.context_expr, ast.Call)
                and _is_open(item.context_expr)
            ]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _is_open(call: ast.Call) -> bool:
    name = dotted_name(call.func)
    return name == "open" or name.endswith(".open")


def writes_a_file(node: ast.AST, handles: frozenset[str] = frozenset()) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr in WRITE_METHODS:
            return True
        # `fp.write(...)` where `fp` came from `open(...)`.
        if func.attr in ("write", "writelines"):
            if isinstance(func.value, ast.Name) and func.value.id in handles:
                return True
    if dotted_name(func) in WRITE_HELPERS:
        return True
    return opens_for_writing(node)


def writing_modules() -> dict[str, list[int]]:
    """Module path (relative to the package) to the lines that write a file."""
    found = {}
    for source in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(source.read_text())
        handles = frozenset(file_handles(tree))
        lines = [n.lineno for n in ast.walk(tree) if writes_a_file(n, handles)]
        if lines:
            found[str(source.relative_to(SOURCE_ROOT))] = lines
    return found


def test_only_the_allowlisted_modules_write_files() -> None:
    assert set(writing_modules()) == set(ALLOWED)


def _expr(source: str) -> ast.Call:
    parsed = ast.parse(source).body[0]
    assert isinstance(parsed, ast.Expr)
    assert isinstance(parsed.value, ast.Call)
    return parsed.value


def test_the_check_sees_every_ordinary_way_to_write() -> None:
    """Guard the guard: a detector that recognises nothing always passes."""
    for source in (
        'p.write_bytes(b"x")',
        'p.write_text("x")',
        'open(p, "w")',
        'open(p, mode="wb")',
        'p.open("w")',
        'p.open(mode="a")',
        "shutil.copyfile(a, b)",
        "shutil.move(a, b)",
        "os.replace(a, b)",
        "os.open(p, flags)",
        "tempfile.NamedTemporaryFile(delete=False)",
        "json.dump(obj, fp)",
    ):
        assert writes_a_file(_expr(source)), f"missed a write: {source}"


def test_the_check_ignores_reads_and_non_file_writes() -> None:
    for source in (
        "p.read_bytes()",
        'open(p, "r")',
        "p.open()",
        "tempfile.TemporaryDirectory()",
        "shutil.rmtree(p)",
        "sock.write(data)",
    ):
        assert not writes_a_file(_expr(source)), f"false positive: {source}"


def test_a_handle_from_open_is_followed() -> None:
    """`fp.write(...)` counts only once `fp` is known to be a file."""
    tree = ast.parse('fp = open(p, "w")\nfp.write("x")\n')
    handles = frozenset(file_handles(tree))
    assert handles == {"fp"}
    assert any(writes_a_file(node, handles) for node in ast.walk(tree))
    bare = ast.parse('fp = socket()\nfp.write("x")\n')
    assert not any(
        writes_a_file(node, frozenset(file_handles(bare))) for node in ast.walk(bare)
    )


def test_a_with_statement_handle_is_followed() -> None:
    tree = ast.parse('with open(p, "w") as handle:\n    handle.write("x")\n')
    assert file_handles(tree) == {"handle"}
