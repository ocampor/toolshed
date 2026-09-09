() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    // known gap: an element an ancestor clips or parks off-screen still counts as
    // visible. Hit-testing would catch it but would also miss a real login form
    // below the fold.
    return el.checkVisibility({
      checkVisibilityCSS: true,
      opacityProperty: true,
      contentVisibilityAuto: true,
    });
  };
  const anyVisible = (selector) =>
    Array.from(document.querySelectorAll(selector)).some(visible);
  const selector = PROBE_SELECTOR_JSON;
  const element = selector ? document.querySelector(selector) : null;
  return {
    password_visible: anyVisible(PASSWORD_SELECTOR_JSON),
    challenge: anyVisible(CHALLENGE_SELECTOR_JSON),
    text: (document.body ? document.body.innerText : "").slice(0, MAX_CHARS_INT),
    selector_text: element ? element.innerText.slice(0, MAX_CHARS_INT) : null,
  };
}
