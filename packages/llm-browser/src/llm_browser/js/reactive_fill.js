// Fill a reactive input (React/Angular) using execCommand for proper event dispatch.
// Args: { id?: string, xpath?: string, value: string }
(args) => {
  var el;
  if (args.xpath) {
    el = document.evaluate(args.xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  } else {
    el = document.getElementById(args.id);
  }
  el.focus();
  el.select();
  document.execCommand("insertText", false, args.value);
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.blur();
}
