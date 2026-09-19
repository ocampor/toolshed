// `(el) => string` — what a field holds: `value` for a form control, the
// rendered text for a contenteditable. A <label> answers for its control, as
// the Playwright family resolves one before filling it.
(el) => {
  const field = el.tagName === "LABEL" && el.control ? el.control : el;
  return field.isContentEditable ? field.innerText : String(field.value ?? "");
}
