// Where an element sits relative to the viewport, for the wheel loop a
// humanized click runs before its move. Read from the page because the
// drivers launch with `no_viewport`, where Playwright reports no size at all.
(el) => {
  const box = el.getBoundingClientRect();
  // How far to wheel down (negative: up) to bring the box in, 0 once it is
  // in. A box taller than the viewport is brought to its top edge.
  const below = box.top + Math.min(box.height, innerHeight) - innerHeight;
  return {
    gap: Math.round(below > 0 ? below : Math.min(0, box.top)),
    centre: [innerWidth / 2, innerHeight / 2],
  };
};
