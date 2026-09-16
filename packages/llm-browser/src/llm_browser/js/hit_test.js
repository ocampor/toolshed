// What the pointer is over right now, for the check a humanized click runs
// between its move and its mouse-down. The point and the text cap are
// substituted in, because drivers evaluate a bare script with no arguments.
(el) => {
  const [x, y] = HIT_POINT_JSON;
  const at = document.elementFromPoint(x, y);
  // The hit lands on the innermost node, so a descendant is the target; a
  // label answers for the control it labels. An ancestor is not the target:
  // the point fell in a gap in the target's own box, and the press there goes
  // to the ancestor, not to `el`.
  const labels = (a, b) => a.closest?.("label")?.control === b;
  const target =
    !at || at === el || el.contains(at) || labels(el, at) || labels(at, el);
  const squeeze = (value, max) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, max);
  return {
    target,
    hit: at && {
      tag: at.tagName.toLowerCase(),
      text: squeeze(at.innerText || at.textContent, HIT_TEXT_MAX_INT),
      class_name: squeeze(at.getAttribute("class"), HIT_TEXT_MAX_INT),
    },
  };
};
