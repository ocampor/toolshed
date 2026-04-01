# llm-browser

Playwright browser automation with declarative YAML flows, designed for LLM-driven agents.

## Install

```bash
cd packages/llm-browser
uv sync
```

## Usage

### Python API

```python
from llm_browser import BrowserSession

session = BrowserSession()
session.launch("https://example.com", headed=True)

# Find and interact
session.find("#username").fill("admin")
session.find("#password").fill("secret")
session.find("button[type=submit]").click()

# Check element presence
if session.element_exists("#dashboard"):
    print("Logged in")

# Read page structure
html = session.dom("body", max_depth=2)

# Extract data
data = session.parse_elements("tr.row", {
    "name": {"child_selector": "td.name", "attribute": "textContent"},
    "email": {"child_selector": "td.email", "attribute": "textContent"},
})

session.close()
```

### CLI

```bash
llm-browser open --url https://example.com
llm-browser goto --url https://example.com/page2
llm-browser find --selector "#form"
llm-browser find-all --selector "li.item"
llm-browser dom --selector "#content" --max-depth 2
llm-browser screenshot
llm-browser close
```

### YAML Flows

```bash
llm-browser run --flow login.yaml --data '{"user": "admin", "pass": "secret"}'
llm-browser resume --data '{"confirm": true}'
```

See [FLOWS.md](FLOWS.md) for the complete flow language reference.

## Session methods

| Method | Description |
|--------|-------------|
| `launch(url, headed)` | Launch Chrome and connect |
| `close()` | Kill browser |
| `goto(url)` | Navigate |
| `find(selector)` | Find exactly one element (returns Playwright Locator) |
| `find_all(selector)` | Find all matching elements |
| `element_exists(selector)` | Check if element is present |
| `pick(selector, value)` | Click list item matching text |
| `dom(selector, max_depth)` | Cleaned HTML snippet |
| `parse_elements(selector, extract)` | Extract structured data |
| `take_screenshot()` | Screenshot to file |
| `get_page()` | Raw Playwright Page |
| `frame(selector)` | Enter iframe |
| `wait_for_load_state(state)` | Wait for page load |
| `latest_tab()` | Switch to newest tab |
