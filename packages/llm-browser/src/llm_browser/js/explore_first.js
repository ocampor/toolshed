async (el) => {
  const limits = EXPLORE_LIMITS_JSON;
  const squeeze = (value, max) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, max);
  const box = () => {
    const r = el.getBoundingClientRect();
    return [r.x, r.y, r.width, r.height].map(Math.round).join(",");
  };

  // Two reads a beat apart: an element still sliding into place is one a click
  // would land beside, and a single rect cannot tell.
  const before = box();
  await new Promise((done) => setTimeout(done, limits.stable_delay_ms));
  const stable = box() === before;

  const rect = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  const tag = el.tagName.toLowerCase();
  const role = el.getAttribute("role");
  const aria_label = el.getAttribute("aria-label");
  const text = squeeze(el.innerText || el.textContent, limits.text_max);
  const name = squeeze(
    aria_label || text || el.value || el.title || el.alt || el.placeholder,
    limits.text_max,
  );

  const visible =
    rect.width > 0 &&
    rect.height > 0 &&
    el.checkVisibility({
      checkVisibilityCSS: true,
      opacityProperty: true,
      contentVisibilityAuto: true,
    });
  const enabled = !el.disabled && el.getAttribute("aria-disabled") !== "true";
  const in_viewport =
    rect.bottom > 0 &&
    rect.right > 0 &&
    rect.top < innerHeight &&
    rect.left < innerWidth;
  const pointer_events = style.pointerEvents !== "none";

  const at = document.elementFromPoint(
    rect.left + rect.width / 2,
    rect.top + rect.height / 2,
  );
  const covering = at && at !== el && !el.contains(at) ? at : null;
  const covered_by = covering
    ? {
        tag: covering.tagName.toLowerCase(),
        text: squeeze(
          covering.innerText || covering.textContent,
          limits.cover_text_max,
        ),
      }
    : null;

  const interactive =
    limits.interactive_tags.includes(tag) ||
    limits.interactive_roles.includes(role) ||
    el.hasAttribute("onclick") ||
    style.cursor === "pointer";

  const why_not = [];
  if (!visible) why_not.push("hidden");
  if (!enabled) why_not.push("disabled");
  if (covered_by) why_not.push("covered");
  if (!in_viewport) why_not.push("offscreen");
  if (!stable) why_not.push("moving");
  if (!pointer_events) why_not.push("no-pointer-events");
  if (!interactive) why_not.push("not-interactive");

  // Proposals only: each is built from an attribute of this element, so the
  // caller's `count == 1` is what makes one a candidate.
  const quoted = (value) => JSON.stringify(String(value));
  const id = el.getAttribute("id");
  const generated = (value) => /\d/.test(value) || value.length > 40;
  const candidates = [];
  for (const attribute of ["data-testid", "data-testing-id"]) {
    const value = el.getAttribute(attribute);
    if (value) candidates.push(`[${attribute}=${quoted(value)}]`);
  }
  if (id && !generated(id)) candidates.push(`#${CSS.escape(id)}`);
  if (aria_label) candidates.push(`[aria-label=${quoted(aria_label)}]`);
  // The implicit role is what a `role=` selector matches on, and the one an
  // `<a>` or a `<button>` never spells out.
  const named_role = role || limits.implicit_roles[tag];
  if (named_role && name) candidates.push(`role=${named_role}[name=${quoted(name)}]`);

  return {
    first: {
      tag,
      text,
      role,
      aria_label,
      name: name || null,
      href: el.getAttribute("href"),
      visible,
      enabled,
      in_viewport,
      covered_by,
      stable,
      pointer_events,
      clickable: why_not.length === 0,
      why_not,
    },
    candidates,
  };
}
