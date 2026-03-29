// Clear a field's value, dispatch input event, and optionally focus.
// Args: { id: string, focus: boolean }
(args) => {
  var el = document.getElementById(args.id);
  el.value = "";
  el.dispatchEvent(new Event("input", { bubbles: true }));
  if (args.focus) el.focus();
}
