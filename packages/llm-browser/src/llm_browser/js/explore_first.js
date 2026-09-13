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

  // Read before the wait: how long the page has been up when the element is
  // first seen, not a hundred milliseconds later.
  const since_navigation_ms = Math.round(performance.now());

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

  // A label and the control it labels are one target: clicking either drives
  // the same thing, so neither covers the other.
  const labels = (a, b) => a.tagName === "LABEL" && a.control === b;
  const at = document.elementFromPoint(
    rect.left + rect.width / 2,
    rect.top + rect.height / 2,
  );
  const same_target =
    !at || at === el || el.contains(at) || labels(el, at) || labels(at, el);
  const covered_by = same_target
    ? null
    : {
        tag: at.tagName.toLowerCase(),
        text: squeeze(at.innerText || at.textContent, limits.cover_text_max),
      };

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

  // A control inside the target is what a loose click lands on instead: a
  // card-sized anchor wrapping its own "dismiss" button hides the card.
  const nested_controls = Array.from(el.querySelectorAll("button, a, input"))
    .slice(0, limits.max_nested_controls)
    .map((child) => ({
      tag: child.tagName.toLowerCase(),
      text: squeeze(child.innerText || child.value || child.textContent, limits.nested_text_max),
    }));

  // Raw material for the caller's selector rules, which own what counts as a
  // generated id or a hashed class. The test id may sit on an ancestor: it is
  // the row that carries it, and the child is what the selector descends to.
  const testid = { attribute: null, value: null, depth: 0 };
  let node = el;
  for (let depth = 0; node && depth <= limits.ancestor_levels; depth += 1) {
    for (const attribute of limits.testid_attributes) {
      const value = node.getAttribute && node.getAttribute(attribute);
      if (value && testid.value === null) {
        testid.attribute = attribute;
        testid.value = value;
        testid.depth = depth;
      }
    }
    node = node.parentElement;
  }

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
      why_not,
      nested_controls,
    },
    locators: {
      tag,
      testid_attribute: testid.attribute,
      testid: testid.value,
      testid_depth: testid.depth,
      aria_label,
      role: role || limits.implicit_roles[tag] || null,
      name: name || null,
      id: el.getAttribute("id"),
      href: el.getAttribute("href"),
      classes: Array.from(el.classList),
    },
    since_navigation_ms,
  };
}
