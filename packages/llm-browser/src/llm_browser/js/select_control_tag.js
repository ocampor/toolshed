(el) => {
  // A <label> answers for the control it labels: the Playwright family
  // resolves one before acting, so asking the label's own tag would reject a
  // target those drivers accept.
  const control = el.tagName === "LABEL" ? el.control : el;
  return control ? control.tagName : el.tagName;
}
