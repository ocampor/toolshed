// `(el) => bool` — does the page render the wanted text? `el` is the element
// the wait is scoped to; page-wide calls pass nothing and get `document.body`.
(el) => {
  const ELEMENT_NODE = 1;
  const TEXT_NODE = 3;
  // `script`/`style`/`template` hold source rather than rendered text.
  const SOURCE_TAGS = new Set(["SCRIPT", "STYLE", "TEMPLATE"]);
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
  // A computed `display` is the node's own, not its ancestors': a
  // `display:contents` node buried under `display:none` still reports
  // "contents". So neither walk below enters a node that lays nothing out —
  // a wholly non-rendered subtree is opaque, as `is_hidden` already treats one.
  const renderedText = (node) => {
    if (rendered(node)) return normalize(node.innerText);
    if (!laysOutText(node)) return "";
    const parts = [...node.childNodes].map((child) => {
      if (child.nodeType === ELEMENT_NODE) return renderedText(child);
      return child.nodeType === TEXT_NODE ? child.data : "";
    });
    return normalize(parts.join(" "));
  };
  if (!exact) return renderedText(root).includes(wanted);
  // Exact asks for one element whose whole text is the wanted string, so every
  // node the scope lays out is asked in turn.
  const textBearing = (node) => {
    if (SOURCE_TAGS.has(node.tagName)) return [];
    if (!(rendered(node) || laysOutText(node))) return [];
    const children = [...node.childNodes].filter(
      (child) => child.nodeType === ELEMENT_NODE,
    );
    return [node, ...children.flatMap(textBearing)];
  };
  return textBearing(root).some((node) => renderedText(node) === wanted);
}
