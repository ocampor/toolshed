// Read all non-empty form field values matching a CSS selector.
// Args: selector (string)
// Returns: { fieldId: value, ... }
(selector) => {
  var result = {};
  document.querySelectorAll(selector).forEach((el) => {
    if (el.value && el.value.trim()) {
      result[el.id || el.name] = el.value;
    }
  });
  return result;
}
