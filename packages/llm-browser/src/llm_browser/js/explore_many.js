// Every target of one `explore_many`, in one page call: the wait, the counts,
// the samples and the first-match read. Run against `<html>` rather than the
// page, because that is the evaluate path every driver awaits.
async (el) => {
  const exploreElement =
    EXPLORE_ELEMENT_JS;
  const limits = EXPLORE_LIMITS_JSON;
  const batch = EXPLORE_BATCH_JSON;
  const doc = el.ownerDocument;
  const started = performance.now();

  const matches = (target) => {
    try {
      return Array.from(doc.querySelectorAll(target.selector));
    } catch {
      return null;
    }
  };

  // One wait for the batch: the page is loading for all of them at once, so
  // the first target to arrive is the signal the rest are worth reading.
  const anyMatch = () => batch.targets.some((target) => (matches(target) || []).length);
  while (!anyMatch() && performance.now() - started < batch.timeout_ms)
    await new Promise((done) => setTimeout(done, batch.poll_ms));

  const readField = (row, field) => {
    const node = field.child_selector
      ? row.querySelector(field.child_selector)
      : row;
    if (!node) return null;
    const value = batch.properties.includes(field.attribute)
      ? node[field.attribute]
      : node.getAttribute(field.attribute);
    return value == null ? null : String(value).slice(0, batch.sample_chars);
  };

  const results = [];
  for (const target of batch.targets) {
    const nodes = matches(target);
    const sampled = (nodes || []).slice(0, batch.sample);
    results.push({
      selector: target.selector,
      invalid: nodes === null,
      count: (nodes || []).length,
      sample: sampled.map((row) =>
        Object.fromEntries(
          Object.entries(target.extract).map(([name, field]) => [
            name,
            readField(row, field),
          ]),
        ),
      ),
      text_chars: sampled.reduce(
        (total, row) => total + (row.innerText || "").length,
        0,
      ),
      element: nodes && nodes.length ? await exploreElement(nodes[0], limits) : null,
      since_call_ms: Math.round(performance.now() - started),
    });
  }
  return results;
}
