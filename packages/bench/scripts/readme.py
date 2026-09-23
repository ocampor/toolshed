import re
from pathlib import Path

BLOCK = re.compile(r'(```\w+ title="(?P<title>[^"]+)"\n).*?(```)', re.DOTALL)


def render(readme: str, example: Path) -> str:
    return BLOCK.sub(lambda match: match[1] + (example / match["title"]).read_text() + match[3], readme)


if __name__ == "__main__":
    root = Path(__file__).parent.parent
    readme = root / "README.md"
    readme.write_text(render(readme.read_text(), root / "example"))
