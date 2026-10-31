# A source check: a new write_text in an action would pass every behaviour test.

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "llm_browser"

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

WRITE_MODES = set("wax+")

ALLOWED = {
    "cli.py": "the CLI is what writes what a run returned",
    "state.py": "state.json is how a detached browser is found again",
    "drivers/patchright_shim.py": "it patches patchright's own Node bundle in place",
}


def dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def opens_for_writing(call: ast.Call) -> bool:
    # The mode is open's second argument but path.open's first; missing that lets Path.open("w") by.
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
    # handle.write could be a socket or StringIO, so it counts only when the name came from open.
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
        if func.attr in ("write", "writelines"):
            if isinstance(func.value, ast.Name) and func.value.id in handles:
                return True
    if dotted_name(func) in WRITE_HELPERS:
        return True
    return opens_for_writing(node)


def writing_modules() -> dict[str, list[int]]:
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
