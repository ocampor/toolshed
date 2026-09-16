(rows, { spec, exclude }) => {
  const properties = EXTRACT_PROPERTIES_JSON;
  const excluded = exclude.join(", ");
  // Attributes carry no subtree, so only a property read needs the pruning —
  // done on a copy, never on the live page.
  const withoutExcluded = (el) => {
    if (!excluded) return el;
    const copy = el.cloneNode(true);
    copy.querySelectorAll(excluded).forEach((node) => node.remove());
    return copy;
  };
  const read = (el, attribute) => {
    if (!el) return null;
    if (!properties.includes(attribute)) return el.getAttribute(attribute);
    return withoutExcluded(el)[attribute];
  };
  return rows.map((row) => {
    const record = {};
    for (const [field, { child_selector, attribute }] of Object.entries(spec)) {
      const el = child_selector ? row.querySelector(child_selector) : row;
      const value = read(el, attribute);
      record[field] = value == null ? null : String(value);
    }
    return record;
  });
};
