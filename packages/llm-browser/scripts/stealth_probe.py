"""Stealth probe: run a driver against known detection surfaces.

Usage:
    uv run python scripts/stealth_probe.py --driver patchright
    uv run python scripts/stealth_probe.py --driver patchright --url https://nowsecure.nl
    uv run python scripts/stealth_probe.py --driver camoufox --matrix all

Each probe navigates, collects a JS fingerprint snapshot, saves a
screenshot and DOM, and prints a pass/fail-ish verdict where possible.
Artifacts land under ./stealth-probe/<driver>/<slug>/.

These targets are flaky and rate-limited — keep this OUT of the test
suite. Run manually when evaluating a driver or before shipping a
stealth-sensitive flow.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from llm_browser.session import BrowserSession

# Probes are a mix of passive JS-leak pages and active vendor checks.
# "check": optional regex that, if found in page text, means DETECTED.
PROBES: dict[str, dict[str, str]] = {
    "sannysoft": {
        "url": "https://bot.sannysoft.com/",
        "check": r"(missing|failed)",
        "note": "classic JS-leak matrix (webdriver, chrome, permissions, plugins)",
    },
    "creepjs": {
        "url": "https://abrahamjuliot.github.io/creepjs/",
        "check": "",
        "note": "deep fingerprint + lie detection; inspect 'trust score' manually",
    },
    "antoinevastel-headless": {
        "url": "https://arh.antoinevastel.com/bots/areyouheadless",
        "check": r"(?i)you are (a )?(bot|headless)",
        "note": "headless browser detection",
    },
    "browserscan": {
        "url": "https://www.browserscan.net/bot-detection",
        "check": r"(?i)robot",
        "note": "aggregate bot-score page",
    },
    "cloudflare-nowsecure": {
        "url": "https://nowsecure.nl/",
        "check": r"(?i)(just a moment|checking your browser|attention required)",
        "note": "Cloudflare interstitial — hardest passive target",
    },
}

# Pulled out of page context to keep artifacts small and diffable.
FINGERPRINT_JS = """
({
  userAgent: navigator.userAgent,
  webdriver: navigator.webdriver,
  languages: navigator.languages,
  platform: navigator.platform,
  vendor: navigator.vendor,
  hardwareConcurrency: navigator.hardwareConcurrency,
  deviceMemory: navigator.deviceMemory,
  pluginCount: navigator.plugins.length,
  mimeTypeCount: navigator.mimeTypes.length,
  hasChrome: typeof window.chrome !== 'undefined',
  chromeRuntime: !!(window.chrome && window.chrome.runtime),
  permissionsQuery: typeof navigator.permissions?.query,
  webglVendor: (() => {
    try {
      const gl = document.createElement('canvas').getContext('webgl');
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      return gl.getParameter(ext.UNMASKED_VENDOR_WEBGL);
    } catch (e) { return null; }
  })(),
  webglRenderer: (() => {
    try {
      const gl = document.createElement('canvas').getContext('webgl');
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      return gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
    } catch (e) { return null; }
  })(),
})"""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def probe_one(
    session: BrowserSession,
    name: str,
    spec: dict[str, str],
    out_dir: Path,
    settle_s: float,
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    url = spec["url"]
    check = spec["check"]
    verdict: dict[str, object] = {"probe": name, "url": url}
    try:
        session.goto(url, wait_until="domcontentloaded")
        time.sleep(settle_s)
        page = session.get_page()
        fingerprint = session.driver.evaluate(page, FINGERPRINT_JS)
        (out_dir / "fingerprint.json").write_text(
            json.dumps(fingerprint, indent=2, default=str)
        )
        session.driver.screenshot(page, out_dir / "screenshot.png")
        content = session.driver.content(page)
        (out_dir / "page.html").write_text(content)
        detected = bool(check and re.search(check, content))
        verdict["detected"] = detected
        verdict["webdriver"] = fingerprint.get("webdriver")
        verdict["final_url"] = session.driver.page_url(page)
    except Exception as e:
        verdict["error"] = f"{type(e).__name__}: {e}"
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--driver",
        default="patchright",
        help="Driver name (patchright, camoufox, nodriver) or comma-separated list",
    )
    parser.add_argument("--url", help="Single custom URL to probe (overrides matrix)")
    parser.add_argument(
        "--matrix",
        default="passive",
        choices=["passive", "all"],
        help="passive = JS-leak pages only; all = include Cloudflare",
    )
    parser.add_argument("--headed", action="store_true", help="Visible browser")
    parser.add_argument(
        "--settle-s",
        type=float,
        default=3.0,
        help="Seconds to wait after domcontentloaded before sampling",
    )
    parser.add_argument("--out", default="stealth-probe", help="Artifacts directory")
    args = parser.parse_args()

    if args.url:
        probes = {"custom": {"url": args.url, "check": "", "note": "user-supplied"}}
    elif args.matrix == "passive":
        probes = {k: v for k, v in PROBES.items() if "cloudflare" not in k}
    else:
        probes = PROBES

    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, object]] = []

    for driver_name in [d.strip() for d in args.driver.split(",") if d.strip()]:
        print(f"\n=== driver: {driver_name} ===")
        session = BrowserSession(
            session_id=f"stealth-probe-{driver_name}",
            driver=driver_name,
        )
        session.launch(headed=args.headed)
        try:
            for probe_name, spec in probes.items():
                out = root / driver_name / slugify(probe_name)
                verdict = probe_one(session, probe_name, spec, out, args.settle_s)
                verdict["driver"] = driver_name
                summary.append(verdict)
                flag = (
                    "ERROR"
                    if "error" in verdict
                    else ("DETECTED" if verdict.get("detected") else "ok")
                )
                print(
                    f"  {probe_name:30s} {flag}  webdriver={verdict.get('webdriver')}"
                )
        finally:
            session.close()

    (root / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nArtifacts: {root.resolve()}")
    detected_any = any(v.get("detected") or v.get("error") for v in summary)
    return 1 if detected_any else 0


if __name__ == "__main__":
    sys.exit(main())
