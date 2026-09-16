(rows, spec) => {
  const properties = EXTRACT_PROPERTIES_JSON;
  // A property is read off a pruned copy: removing the live nodes would
  // change the page the flow is still driving.
  const without = (el, exclude) => {
    if (!exclude || !exclude.length) return el;
    const copy = el.cloneNode(true);
    copy.querySelectorAll(exclude.join(",")).forEach((node) => node.remove());
    return copy;
  };
  return rows.map((row) => {
    const record = {};
    for (const [field, { child_selector, attribute, exclude }] of Object.entries(
      spec,
    )) {
      const el = child_selector ? row.querySelector(child_selector) : row;
      const value = el
        ? properties.includes(attribute)
          ? without(el, exclude)[attribute]
          : el.getAttribute(attribute)
        : null;
      record[field] = value == null ? null : String(value);
    }
    return record;
  });
};
