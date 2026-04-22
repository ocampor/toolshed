# Cross-driver geo alignment

## Context

Bot-detection sites triangulate identity across four signals that must agree:

1. **Locale / `Accept-Language`** — sent by the browser per navigator.languages.
2. **Timezone** — reported via `Intl.DateTimeFormat().resolvedOptions().timeZone` and `Date.getTimezoneOffset()`.
3. **Geolocation** — returned by the `navigator.geolocation` API (when permitted).
4. **Outgoing IP** — what the server actually sees.

When these disagree (e.g. `locale=fr-FR` but IP is in the US and timezone is `America/Los_Angeles`), the mismatch is a clean signal. Camoufox has a one-shot `geoip=True` that resolves this by deriving tz + geolocation from the outgoing IP; the Camoufox-hardening plan (`~/.claude/plans/what-are-the-best-wondrous-toucan.md`) uses it. **Patchright and nodriver have no such flag.** They expose the *primitives* to pin tz and geolocation, but the IP→geo lookup has to be done by us.

This plan adds a driver-agnostic `auto_align_geo` facility that does the lookup once at launch and applies the result through each driver's native mechanism, so a single `BrowserSession(..., align_geo=True)` works identically across patchright, camoufox, and nodriver.

## Per-driver primitives

| Driver | Timezone pin | Geolocation pin | Native IP→geo |
|---|---|---|---|
| patchright / playwright | `browser.new_context(timezone_id=...)` | `context.set_geolocation({latitude, longitude, accuracy})` + `context.grant_permissions(["geolocation"])` | none |
| camoufox | `Camoufox(timezone=...)` | `Camoufox(geolocation={...})` | `Camoufox(geoip=True)` |
| nodriver | CDP `Emulation.setTimezoneOverride(timezoneId=...)` | CDP `Emulation.setGeolocationOverride(latitude, longitude, accuracy)` | none |

## Design

### 1. IP lookup helper — `llm_browser/geoip.py` (new)

Single pure-stdlib function, no new deps:

```python
@dataclass(frozen=True)
class GeoInfo:
    timezone: str              # IANA, e.g. "Europe/Paris"
    latitude: float
    longitude: float
    accuracy: float = 50.0     # meters
    country_code: str | None = None
    ip: str | None = None

def lookup_public_geo(timeout_s: float = 5.0) -> GeoInfo: ...
```

- Uses `urllib.request` against `https://ipapi.co/json/` (free, no key, 1000/day unauthenticated; documented ToS allows programmatic use).
- Parses `timezone`, `latitude`, `longitude`, `country_code`, `ip` out of the JSON.
- Fallback provider chain: `ipapi.co` → `ip-api.com/json/` → raise `GeoLookupError`. Two providers is enough — if both fail, bail loudly rather than silently misaligning.
- Configurable override for tests: `LLM_BROWSER_GEOIP_URL` env var, or pass a `fetch` callable.

### 2. `Driver.apply_geo(handle, geo: GeoInfo)` — new abstract method

Added to `drivers/base.py`:

```python
@abstractmethod
def apply_geo(self, handle: DriverHandle, geo: GeoInfo) -> None: ...
```

Default is *not* a no-op — it must be implemented per driver so silent omissions are caught by mypy / tests.

**Per-driver impls:**

- **`PlaywrightDriverBase`** — default impl using the context API:
  ```python
  def apply_geo(self, handle, geo):
      ctx = self._context(handle)   # each subclass exposes its BrowserContext
      ctx.set_geolocation({
          "latitude": geo.latitude,
          "longitude": geo.longitude,
          "accuracy": geo.accuracy,
      })
      ctx.grant_permissions(["geolocation"])
      # timezone must be set at context-creation time → see §3
  ```
  Requires `PlaywrightDriverBase` to expose a `_context(handle)` hook. Patchright already holds the context; Camoufox holds it too (`self._context`). Straightforward.

- **`CamoufoxDriver`** — overrides to a no-op when `geoip=True` was passed (Camoufox handles it natively); otherwise defers to the Playwright base impl.

- **`NodriverDriver`** — runs the CDP calls through the existing sync bridge:
  ```python
  async def do_apply_geo(self, handle, geo):
      nodriver = load_optional_module("nodriver", "nodriver")
      cdp = nodriver.cdp
      tab = self.page(handle)
      await tab.send(cdp.emulation.set_timezone_override(timezone_id=geo.timezone))
      await tab.send(cdp.emulation.set_geolocation_override(
          latitude=geo.latitude,
          longitude=geo.longitude,
          accuracy=geo.accuracy,
      ))
  ```

### 3. Timezone at context-creation (Playwright family)

Playwright's `timezone_id` can only be set when the context is created, not mutated afterward. That means the lookup has to happen *before* `launch()` calls `browser.new_context(...)` on Patchright. Two options:

- **A. Lookup in `launch()` prologue.** Cleanest; `launch()` becomes: `geo = lookup_public_geo(); ctx = browser.new_context(timezone_id=geo.timezone, ...); self.apply_geo(handle, geo)`.
- **B. Pre-launch hook.** `BrowserSession.launch()` does the lookup and passes `GeoInfo` into `driver.launch(..., geo=geo)`.

Choosing **B**: keeps the network call out of the driver (easier to stub in tests), lets a future `align_geo=False` or a pre-fetched `GeoInfo` flow through uniformly, and makes Camoufox's native `geoip=True` path a clean conditional (`if align_geo and not self._has_native_geoip(): geo = lookup_public_geo(); kwargs["timezone"] = geo.timezone; ...`).

### 4. `BrowserSession` wiring

```python
class BrowserSession:
    def __init__(
        self,
        ...,
        align_geo: bool | GeoInfo = False,
    ) -> None:
        self._align_geo = align_geo

    def launch(self, url, headed):
        geo = self._resolve_geo()   # None | GeoInfo
        handle = self.driver.launch(..., geo=geo)
        if geo is not None:
            self.driver.apply_geo(handle, geo)
        ...
```

`align_geo=True` → lookup at launch. `align_geo=<GeoInfo>` → pre-supplied, no lookup (useful for tests and for callers who already have an IP→geo service). `False` (default) → unchanged behavior.

### 5. Camoufox coexistence

When the user passes both `align_geo=True` *and* a `CamoufoxDriver(...)` that already has `geoip=True`, we skip the lookup — Camoufox does it natively, and two overlapping sources would race. The `CamoufoxDriver` advertises this via a `supports_native_geo: ClassVar[bool] = True` class flag; `BrowserSession._resolve_geo()` checks it before calling `lookup_public_geo`.

### 6. CLI

Add `--align-geo` flag to `llm-browser` root command, stored in `SessionInfo` so subsequent commands inherit it. No positional `GeoInfo` support in CLI — if the user wants pinned values they can pass them directly via driver kwargs in Python.

## Critical files

**Create:**
- `src/llm_browser/geoip.py` — `GeoInfo`, `lookup_public_geo`, `GeoLookupError`.
- `tests/test_geoip.py` — lookup + fallback behavior with mocked `urlopen`.
- `tests/test_drivers_geo_alignment.py` — per-driver `apply_geo` dispatch.

**Modify:**
- `src/llm_browser/drivers/base.py` — add `apply_geo` abstract method, import `GeoInfo`.
- `src/llm_browser/drivers/playwright_base.py` — default `apply_geo` impl + `_context()` hook.
- `src/llm_browser/drivers/patchright.py` — expose context, ensure `timezone_id` is passed at `new_context`.
- `src/llm_browser/drivers/camoufox.py` — `supports_native_geo = True`, override `apply_geo` with native-geoip short-circuit.
- `src/llm_browser/drivers/nodriver.py` — `do_apply_geo` async impl + sync wrapper.
- `src/llm_browser/session.py` — `align_geo` param, `_resolve_geo`, pipe `GeoInfo` into `driver.launch` and `driver.apply_geo`.
- `src/llm_browser/cli.py` — `--align-geo` flag.
- `src/llm_browser/models.py` — `align_geo: bool = False` on `SessionInfo`.
- `README.md` — usage example + ToS note on the lookup provider.

## Verification

1. `uv run pytest tests/test_geoip.py -v` — mocked HTTP returns primary success, primary fail + secondary success, both fail → `GeoLookupError`.
2. `uv run pytest tests/test_drivers_geo_alignment.py -v` — each driver receives `apply_geo(GeoInfo(...))` and issues the expected native calls (mocked context / mocked CDP `send`).
3. `uv run pytest -v` — full suite green. `uv run mypy .` and `uv run ruff check` clean.
4. Manual (patchright): `BrowserSession(driver="patchright", align_geo=True).launch("https://browserleaks.com/ip")` — reported timezone/IP/geolocation agree.
5. Manual (camoufox, with extra): same URL with `driver="camoufox"` and `align_geo=True` — verify lookup is *skipped* (log or breakpoint confirms Camoufox's native geoip took over).
6. Manual (nodriver, with extra): same URL with `driver="nodriver"` — `Emulation.setTimezoneOverride` and `Emulation.setGeolocationOverride` show up in the CDP log; `browserleaks` reports matching tz/geo.
7. Offline test: block network to the lookup providers; confirm `launch()` raises `GeoLookupError` rather than silently launching misaligned.

## Out of scope

- A self-hosted IP→geo database (MaxMind etc.) to avoid third-party calls. Users who need that can pass `GeoInfo` directly.
- Matching locale *to* the IP (reverse direction). If the user pins `locale="fr-FR"` on a US IP with `align_geo=True`, we still set US tz/geo — the locale mismatch is the caller's responsibility because we can't know what they intended.
- Re-applying geo after navigation / context recreation — set once at launch.
- Proxy rotation hooks (re-lookup when IP changes mid-session).

## Dependencies

Builds on the already-approved Camoufox hardening plan (`~/.claude/plans/what-are-the-best-wondrous-toucan.md`). That plan leaves Camoufox's `geoip=True` as the locale-alignment default; this plan generalizes the same alignment to the other two drivers via a separate opt-in (`align_geo=True`), and keeps Camoufox's native path as the fast path when both are enabled.
