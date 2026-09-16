(rows, { spec, exclude }) => {
  const properties = EXTRACT_PROPERTIES_JSON;
  const excludable = EXCLUDABLE_PROPERTIES_JSON;
  const group = exclude.join(",");
  // One pruned copy per row, not per field: `exclude` is the step's, the same
  // for every field. A copy, because removing the live nodes would change the
  // page the flow is still driving.
  const pruned = (row) => {
    const copy = row.cloneNode(true);
    copy.querySelectorAll(group).forEach((node) => node.remove());
    return copy;
  };
  return rows.map((row) => {
    const copy = group ? pruned(row) : row;
    const record = {};
    for (const [field, { child_selector, attribute }] of Object.entries(spec)) {
      const host = excludable.includes(attribute) ? copy : row;
      const el = child_selector ? host.querySelector(child_selector) : host;
      const value = el
        ? properties.includes(attribute)
          ? el[attribute]
          : el.getAttribute(attribute)
        : null;
      record[field] = value == null ? null : String(value);
    }
    return record;
  });
}
