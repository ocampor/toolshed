// Where an element sits relative to the viewport, for the wheel loop a
// humanized click runs before its move. Read from the page because the
// drivers launch with `no_viewport`, where Playwright reports no size at all.
(el) => {
  const box = el.getBoundingClientRect();
  // How far to wheel down (negative: up) to put the box's middle in the
  // viewport's middle, the rule `Driver.scroll_into_view` follows: the caller
  // is here because a fixed header or footer swallowed a click, and only the
  // middle is clear of both. A box already clear of both edges by `margin` is
  // left alone, so an in-view target is not nudged on every click. A box
  // taller than the viewport cannot be centred and is brought to its top edge.
  const margin = innerHeight * 0.15;
  const tall = box.height > innerHeight;
  const clear = box.top >= margin && box.bottom <= innerHeight - margin;
  const gap = tall ? box.top : box.top + box.height / 2 - innerHeight / 2;
  return {
    gap: !tall && clear ? 0 : Math.round(gap),
    centre: [innerWidth / 2, innerHeight / 2],
    scrollY: Math.round(scrollY),
  };
};
