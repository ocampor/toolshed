// `(el) => string` — what a field holds: `value` for a form control, the
// rendered text for a contenteditable.
(el) => (el.isContentEditable ? el.innerText : String(el.value ?? ""))
