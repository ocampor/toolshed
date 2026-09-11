(el) => {
  if (el.tagName !== "SELECT") return "not-a-select";
  const option = Array.from(el.options).find((o) => o.value === SELECT_VALUE_JSON);
  if (!option) return "missing";
  if (option.disabled || option.parentElement.disabled) return "disabled";
  // The select is closed, so there is no option to click: set the value and
  // announce it the way the browser would. Chromium exposes no CDP command
  // for choosing an option, and Playwright resolves the same problem the
  // same way.
  el.selectedIndex = option.index;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return "ok";
}
