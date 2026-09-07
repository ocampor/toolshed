(rows, spec) =>
  rows.map((row) => {
    const record = {};
    for (const [field, { child_selector, attribute }] of Object.entries(spec)) {
      const el = child_selector ? row.querySelector(child_selector) : row;
      if (!el) {
        record[field] = null;
      } else if (attribute === "textContent") {
        record[field] = el.textContent;
      } else if (attribute === "value") {
        record[field] = el.value;
      } else {
        record[field] = el.getAttribute(attribute);
      }
    }
    return record;
  });
