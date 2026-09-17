// `(el) => bool` — does the page render the wanted text? `el` is the element
// the wait is scoped to; page-wide calls pass nothing and get `document.body`.
(el) => {
  const ELEMENT_NODE = 1;
  const TEXT_NODE = 3;
  const normalize = (value) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim();
  const wanted = normalize(TEXT_MATCH_TEXT_JSON);
  const exact = TEXT_MATCH_EXACT_BOOL;
  const root = el || document.body;
  if (!root) return false;
  // `innerText` is rendered text only while the element itself is rendered;
  // the spec's getter otherwise falls back to `textContent`, which would read a
  // `display:none` scope's text as still on the page. A `display:contents` root
  // draws no box of its own either, yet lays out its children — text nodes as
  // much as elements — as usual, so it is worth exactly what they render.
  const rendered = (node) =>
    Boolean(node.offsetParent || node.getClientRects?.().length);
  const laysOutText = (node) => getComputedStyle(node).display === "contents";
  const renderedText = (node) => {
    if (rendered(node)) return normalize(node.innerText);
    const showsText = laysOutText(node);
    const parts = [...node.childNodes].map((child) => {
      if (child.nodeType === ELEMENT_NODE) return renderedText(child);
      return showsText && child.nodeType === TEXT_NODE ? child.data : "";
    });
    return normalize(parts.join(" "));
  };
  if (!exact) return renderedText(root).includes(wanted);
  // Exact asks for one element whose whole text is the wanted string, so every
  // node in the scope is asked in turn. `script`/`style`/`template` hold source
  // rather than rendered text, and answer with their `textContent`.
  const scope = root.querySelectorAll("*:not(script):not(style):not(template)");
  return [root, ...scope].some(
    (node) =>
      (rendered(node) || laysOutText(node)) && renderedText(node) === wanted,
  );
}
