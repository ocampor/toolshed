// Init script for attached browsers: a page that revokes its blob URL right
// after the click leaves the in-page download read nothing to fetch, so each
// Blob is held ~30 s past its revoke. Non-enumerable to stay out of sight.
(() => {
  // One CDP connection per tab adds this once each; wrap URL.* only once.
  if (window.__k7b) return;
  const kept = new Map();
  const create = URL.createObjectURL;
  const revoke = URL.revokeObjectURL;
  URL.createObjectURL = function (object) {
    const url = create.call(URL, object);
    if (object instanceof Blob) kept.set(url, object);
    return url;
  };
  URL.revokeObjectURL = function (url) {
    revoke.call(URL, url);
    setTimeout(() => kept.delete(url), 30000);
  };
  Object.defineProperty(window, "__k7b", { value: (url) => kept.get(url) });
})()
