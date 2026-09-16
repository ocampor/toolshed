// `(el) => bool` — does the page render the wanted text? `el` is the element
// the wait is scoped to; page-wide calls pass nothing and get `document.body`.
(el) => {
  const normalize = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();
  const wanted = normalize(TEXT_MATCH_TEXT_JSON);
  const exact = TEXT_MATCH_EXACT_BOOL;
  const root = el || document.body;
  if (!root) return false;
  // `innerText` is rendered text only while the element itself is rendered;
  // the spec's getter otherwise falls back to `textContent`, which would read
  // a `display:none` scope's text as still on the page.
  const rendered = (node) =>
    Boolean(node.offsetParent || node.getClientRects?.().length);
  const matches = (node) => {
    if (!rendered(node)) return false;
    const text = normalize(node.innerText);
    return exact ? text === wanted : text.includes(wanted);
  };
  // A substring of any descendant is a substring of the root's own text, so
  // only an exact match has to look further down. `script`/`style`/`template`
  // hold source, not rendered text, and answer with their `textContent`.
  if (matches(root)) return true;
  const descendants = root.querySelectorAll("*:not(script):not(style):not(template)");
  return exact && [...descendants].some(matches);
}
