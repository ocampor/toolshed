// The per-element read `explore` and `explore_many` share: what one element
// is right now, and what it offers a selector. `limits` is the caller's so
// one substitution serves every script that composes this one.
async (el, limits) => {
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

  // `in_viewport` is what was true before this function touched anything.
  // Inclusive: an element flush against an edge is in view, not off it.
  const start = el.getBoundingClientRect();
  const boxless = start.width === 0 || start.height === 0;
  const in_viewport =
    start.bottom >= 0 &&
    start.right >= 0 &&
    start.top <= innerHeight &&
    start.left <= innerWidth;

  // Exploring may scroll. The hit-test only answers inside the viewport, and
  // scrolling first is what every driver does before it clicks, so this asks
  // the question the click would ask. Nothing with no box to scroll to.
  // `instant`: a page with `scroll-behavior: smooth` would still be animating
  // when the two rects below are read, and report the element as `moving`.
  if (!in_viewport && !boxless)
    el.scrollIntoView({ block: "center", behavior: "instant" });

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

  // A box of no size is nothing to click and nothing to hit-test.
  const sizeless = rect.width === 0 || rect.height === 0;
  const visible =
    !sizeless &&
    el.checkVisibility({
      checkVisibilityCSS: true,
      opacityProperty: true,
      contentVisibilityAuto: true,
    });
  // `:disabled` is the platform's own answer, and the only one that sees a
  // control disabled by the `<fieldset>` around it rather than by itself.
  const enabled =
    !el.matches(":disabled") && el.getAttribute("aria-disabled") !== "true";
  const pointer_events = style.pointerEvents !== "none";

  // A label and the control it labels are one target: clicking either drives
  // the same thing, so neither covers the other. `closest` because the hit
  // test lands on the innermost node -- the span inside the label, usually.
  const labels = (a, b) => a.closest?.("label")?.control === b;
  // `elementFromPoint` answers null outside the viewport, which reads as
  // "nothing over it" rather than "not asked": `hit_tested` says which.
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  const probeable =
    !sizeless && x >= 0 && y >= 0 && x <= innerWidth && y <= innerHeight;
  const at = probeable ? document.elementFromPoint(x, y) : null;
  const hit_tested = at !== null;
  // An ancestor at the centre means the point fell in a gap in the element's
  // own box -- a line-box gap, a wrapper around its children -- not that
  // something is painted over it. A real cover is never an ancestor.
  const same_target =
    !at ||
    at === el ||
    el.contains(at) ||
    at.contains(el) ||
    labels(el, at) ||
    labels(at, el);
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
  // A box of no size is nowhere, not off-screen: `hidden` is the whole story.
  if (!in_viewport && !boxless) why_not.push("offscreen");
  if (!stable) why_not.push("moving");
  if (!pointer_events) why_not.push("no-pointer-events");
  if (!interactive) why_not.push("not-interactive");

  // A control inside the target is what a loose click lands on instead: a
  // card-sized anchor wrapping its own "dismiss" button hides the card.
  const nested_controls = Array.from(el.querySelectorAll("button, a, input"))
    .slice(0, limits.max_nested_controls)
    .map((child) => ({
      tag: child.tagName.toLowerCase(),
      text: squeeze(
        child.innerText || child.value || child.textContent,
        limits.nested_text_max,
      ),
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
      hit_tested,
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
