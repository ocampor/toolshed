(rows, { spec, exclude }) => {
  const properties = EXTRACT_PROPERTIES_JSON;
  const excludable = EXCLUDABLE_PROPERTIES_JSON;
  const group = exclude.join(",");
  // A copy, because removing the live nodes would change the page the flow is
  // still driving. Every field resolves on the live row first, so `exclude` is
  // only ever about text -- it never decides whether a field's element exists.
  const pruned = (el) => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll(group).forEach((node) => node.remove());
    return copy;
  };
  return rows.map((row) => {
    const record = {};
    for (const [field, { child_selector, attribute }] of Object.entries(spec)) {
      const el = child_selector ? row.querySelector(child_selector) : row;
      const prune = el && group && excludable.includes(attribute);
      const target = prune ? pruned(el) : el;
      const value = target
        ? properties.includes(attribute)
          ? target[attribute]
          : target.getAttribute(attribute)
        : null;
      record[field] = value == null ? null : String(value);
    }
    return record;
  });
}
