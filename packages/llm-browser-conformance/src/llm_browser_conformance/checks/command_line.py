"""End-to-end: the CLI is the one thing that writes what a run returned.

Every other scenario drives the library in-process, where the promise is that
nothing reaches disk. These drive the installed `llm-browser` console script
as a subprocess, because the other half of that promise — that `llm-browser
run` puts the results where the flow and the flags asked — is only true of the
command, and is exactly what an in-process test cannot see.

One driver is enough: what the CLI writes is decided above the driver, and
launching a second browser per column would triple the cost of the run to
re-check the same code.
"""

import contextlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from llm_browser_conformance.scenario import Context, Scenario, Section

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

CLI_DRIVER = "patchright"

DOWNLOAD_PAYLOAD = "conformance-payload"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# A flow this slow to fail would make the row the slowest in the table.
CLI_TIMEOUT_S = 120


@contextlib.contextmanager
def scratch() -> Iterator[Path]:
    """A throwaway tree for one scenario's output, capture and working dirs."""
    with tempfile.TemporaryDirectory(prefix="llm-browser-cli-") as directory:
        yield Path(directory)


def cli_executable(ctx: Context) -> Path:
    """The `llm-browser` script installed beside the interpreter running us."""
    executable = Path(sys.executable).parent / "llm-browser"
    if not executable.exists():
        raise ctx.skip(f"no llm-browser console script at {executable}")
    return executable


def only_on_the_cli_driver(ctx: Context) -> None:
    if ctx.driver != CLI_DRIVER:
        raise ctx.skip(
            f"the CLI writes the same files whichever driver runs the flow; "
            f"checked once, on {CLI_DRIVER}"
        )


def run_cli(
    ctx: Context, workdir: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    """One `llm-browser` invocation, from ``workdir``.

    ``workdir`` is the CWD on purpose: a relative path the library wrote
    itself would land there, which is what the scenarios check stayed empty.
    """
    return subprocess.run(
        [str(cli_executable(ctx)), "--session", "conformance-cli", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_S,
        # A non-zero exit is a result here, not an error: `run` exits 1 on a
        # failed flow and one scenario exists to check exactly that.
        check=False,
    )


def fail_on(step: str, done: subprocess.CompletedProcess[str]) -> None:
    assert done.returncode == 0, f"{step} exited {done.returncode}: {done.stderr[:400]}"


def payload(done: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The JSON `run` printed, which is the only contract its callers have."""
    try:
        parsed: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as broken:
        raise AssertionError(f"run printed no JSON: {done.stdout[:400]}") from broken
    return parsed


def files_under(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file()
    )


def cli_run(
    ctx: Context, page: str, flow: str, tmp: Path, *args: str, **data: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """`daemon` a headless browser, `run` the flow against it, always `stop`.

    `daemon` rather than `open` because these are two processes: a launched
    patchright session belongs to the process that launched it, and only the
    detached-over-CDP session survives to the next invocation. That is the
    documented multi-call story, and it is the one a CLI user is on.

    Returns the finished `run` and the working directory it ran in, which the
    caller asserts stayed empty.
    """
    workdir = tmp / "cwd"
    workdir.mkdir(parents=True)
    fail_on(
        "daemon",
        run_cli(ctx, workdir, "--driver", CLI_DRIVER, "daemon", "--headless"),
    )
    try:
        done = run_cli(
            ctx,
            workdir,
            "--driver",
            CLI_DRIVER,
            "run",
            "--flow",
            str(ctx.flow_file(flow)),
            "--data",
            json.dumps({"url": ctx.url(page), **data}),
            *args,
        )
    finally:
        run_cli(ctx, workdir, "--driver", CLI_DRIVER, "stop")
    return done, workdir


def cli_run_writes_every_output_where_it_was_asked(ctx: Context) -> None:
    """A `path:` lands under `--out-dir`; a payload with none lands there too,
    under the name it came with. Neither is base64 on stdout."""
    only_on_the_cli_driver(ctx)
    with scratch() as tmp:
        out_dir = tmp / "artifacts"
        done, workdir = cli_run(
            ctx, "download.html", "cli-outputs", tmp, "--out-dir", str(out_dir)
        )
        fail_on("run", done)

        shot = out_dir / "captures" / "page.png"
        grabbed = out_dir / "download.txt"
        assert shot.read_bytes().startswith(PNG_MAGIC), "the `path:` got no PNG"
        assert grabbed.read_text().strip() == DOWNLOAD_PAYLOAD, (
            "a download with no `path:` must still land, under its own name"
        )
        assert files_under(out_dir) == ["captures/page.png", "download.txt"]
        assert files_under(workdir) == [], (
            f"the run wrote into its working directory: {files_under(workdir)}"
        )

        outputs = payload(done)["outputs"]
        assert outputs["shot"] == str(shot), outputs["shot"]
        assert outputs["grab"] == str(grabbed), outputs["grab"]


def cli_run_writes_the_failure_captures(ctx: Context) -> None:
    """A failing run exits 1, writes its capture to `--capture-dir`, and
    reports the path where the bytes would otherwise have been."""
    only_on_the_cli_driver(ctx)
    with scratch() as tmp:
        out_dir = tmp / "artifacts"
        capture_dir = tmp / "diagnostics"
        done, workdir = cli_run(
            ctx,
            "never.html",
            "cli-failure",
            tmp,
            "--out-dir",
            str(out_dir),
            "--capture-dir",
            str(capture_dir),
        )
        assert done.returncode == 1, f"a failed flow must exit 1, got {done.returncode}"

        shot = capture_dir / "screenshot.png"
        assert shot.read_bytes().startswith(PNG_MAGIC)
        # `run` builds its session on the default capture mode, so the DOM
        # snapshot is not asked for and must not appear.
        assert files_under(capture_dir) == ["screenshot.png"]
        assert files_under(workdir) == [], (
            f"the run wrote into its working directory: {files_under(workdir)}"
        )

        reported = payload(done)
        assert reported["step"] == "never", reported["step"]
        assert reported["screenshot"] == str(shot), reported["screenshot"]


def cli_run_writes_typed_rows_as_json(ctx: Context) -> None:
    """A `parse` schema may declare `Decimal` and `date`; the rows reach the
    CLI writer as those objects and `json.dumps` cannot encode either.

    The library used to write this file itself, in JSON mode, and the crash
    this pins is what moving the write to the CLI reintroduced once.
    """
    only_on_the_cli_driver(ctx)
    with scratch() as tmp:
        out_dir = tmp / "artifacts"
        done, workdir = cli_run(
            ctx,
            "parse-rows.html",
            "cli-rows",
            tmp,
            "--out-dir",
            str(out_dir),
            schema=str(SCHEMAS_DIR / "invoice.yaml"),
        )
        fail_on("run", done)

        written = json.loads((out_dir / "typed" / "rows.json").read_text())
        assert written == [
            {"name": "alpha", "total": "10.25", "due": "2024-03-01"},
            {"name": "beta", "total": "7.50", "due": "2024-04-15"},
        ], written
        assert files_under(workdir) == []


SCENARIOS = [
    Scenario(
        "cli run writes outputs",
        Section.CLI,
        cli_run_writes_every_output_where_it_was_asked,
        covers=frozenset({"api:cli.out_dir"}),
    ),
    Scenario(
        "cli run writes typed rows",
        Section.CLI,
        cli_run_writes_typed_rows_as_json,
        covers=frozenset({"api:cli.typed_rows"}),
    ),
    Scenario(
        "cli run failure captures",
        Section.CLI,
        cli_run_writes_the_failure_captures,
        covers=frozenset({"api:cli.capture_dir"}),
    ),
]
