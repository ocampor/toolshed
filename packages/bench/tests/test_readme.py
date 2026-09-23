import ast
import re
import shutil
import zipfile
from pathlib import Path

import pytest
from hatchling.build import build_wheel

README = Path(__file__).parent.parent / "README.md"
FIXTURES = Path(__file__).parent / "fixtures"

BLOCK = re.compile(r'```\w+ title="(?P<title>[^"]+)"\n(?P<body>.*?)```', re.DOTALL)


def readme_files() -> dict[str, str]:
    return {match["title"]: match["body"] for match in BLOCK.finditer(README.read_text())}


def readme_header(docgen: str) -> str:
    match = re.search(r'header=("(?:[^"\\]|\\.)*")', docgen)
    assert match is not None
    return str(ast.literal_eval(match.group(1)))


def test_readme_quickstart_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = readme_files()
    for title, body in files.items():
        target = tmp_path / title
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)

    package = tmp_path / "src" / "my_package"
    shutil.copy(FIXTURES / "sample" / "models.py", package / "models.py")
    (package / "__init__.py").write_text("")

    monkeypatch.chdir(tmp_path)
    wheel = build_wheel(str(tmp_path / "dist"))

    with zipfile.ZipFile(tmp_path / "dist" / wheel) as built:
        text = built.read("my_package/docs/reference/models.md").decode()

    assert text.startswith(readme_header(files["src/my_package/docgen.py"]))
    assert "### `Answer.limit`" in text
