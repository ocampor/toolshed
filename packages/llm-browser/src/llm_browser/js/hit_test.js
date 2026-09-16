// What the pointer is over right now, for the check a humanized click runs
// between its move and its mouse-down. The point and the text cap are
// substituted in, because drivers evaluate a bare script with no arguments.
(el) => {
  const [x, y] = HIT_POINT_JSON;
  const at = document.elementFromPoint(x, y);
  // `explore_element`'s `covered_by` rule: the hit lands on the innermost
  // node, so a descendant is the target; an ancestor means the point fell in
  // a gap in the target's own box; a label answers for the control it labels.
  const labels = (a, b) => a.closest?.("label")?.control === b;
  const target =
    !at ||
    at === el ||
    el.contains(at) ||
    at.contains(el) ||
    labels(el, at) ||
    labels(at, el);
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
      class: squeeze(at.getAttribute("class"), HIT_TEXT_MAX_INT),
    },
  };
};
