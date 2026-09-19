// `(el) => {text, secret}` — what a field holds: `value` for a form control, the
// rendered text for a contenteditable. A <label> answers for its control, as
// the Playwright family resolves one before filling it. An emptied
// contenteditable keeps a <br>, so whitespace alone reads as empty; `secret`
// marks a password field, whose contents never reach a message.
(el) => {
  const field = el.tagName === "LABEL" && el.control ? el.control : el;
  const secret = field.type === "password";
  if (!field.isContentEditable) return { text: String(field.value ?? ""), secret };
  const text = field.innerText;
  return { text: text.trim() === "" ? "" : text, secret };
}
