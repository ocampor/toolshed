(rows, spec) => {
  const properties = EXTRACT_PROPERTIES_JSON;
  return rows.map((row) => {
    const record = {};
    for (const [field, { child_selector, attribute }] of Object.entries(spec)) {
      const el = child_selector ? row.querySelector(child_selector) : row;
      const value = el
        ? properties.includes(attribute)
          ? el[attribute]
          : el.getAttribute(attribute)
        : null;
      record[field] = value == null ? null : String(value);
    }
    return record;
  });
};
