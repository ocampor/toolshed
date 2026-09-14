// How many elements each selector matches page-wide, so a reported `count` is
// the number the author's own selector is about to return. One
// `querySelectorAll` per selector, over the capped lists `survey` reports.
(el) => {
  const doc = el.ownerDocument;
  const counts = {};
  for (const selector of COUNT_SELECTORS_JSON) {
    try {
      counts[selector] = doc.querySelectorAll(selector).length;
    } catch {
      counts[selector] = 0;
    }
  }
  return counts;
}
