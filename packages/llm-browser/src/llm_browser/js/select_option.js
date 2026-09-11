(el) => {
  // A <label> stands in for the control it labels, which is what the
  // Playwright family resolves before acting.
  const select = el.tagName === "LABEL" ? el.control : el;
  if (!select || select.tagName !== "SELECT") return "not-a-select";
  if (select.disabled) return "select-disabled";
  const options = Array.from(select.options);
  // Value or label, like Playwright's select_option: a flow written against
  // the text a person reads has to work on every driver.
  const option =
    options.find((o) => o.value === SELECT_VALUE_JSON) ??
    options.find((o) => o.label === SELECT_VALUE_JSON) ??
    options.find((o) => o.text.trim() === SELECT_VALUE_JSON);
  if (!option) return "missing";
  if (option.disabled) return "option-disabled";
  if (option.closest("optgroup")?.disabled) return "group-disabled";
  // The select is closed, so there is no option to click: set the value and
  // announce it the way the browser would. Chromium exposes no CDP command
  // for choosing an option, and Playwright resolves the same problem the
  // same way.
  select.selectedIndex = option.index;
  select.dispatchEvent(new Event("input", { bubbles: true }));
  select.dispatchEvent(new Event("change", { bubbles: true }));
  return "ok";
}
