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
  const matches = (node) => {
    const text = normalize(node.innerText);
    return exact ? text === wanted : text.includes(wanted);
  };
  // A substring of any descendant is a substring of the root's own text, so
  // only an exact match has to look further down.
  if (matches(root)) return true;
  return exact && [...root.querySelectorAll("*")].some(matches);
}
