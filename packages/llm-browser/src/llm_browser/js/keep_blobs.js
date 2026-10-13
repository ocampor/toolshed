// Run before an attached download's click: a page that revokes its blob URL
// right after the click leaves the in-page read nothing to fetch, so each
// Blob is held ~30 s past its revoke. Non-enumerable to stay out of sight.
(() => {
  // Every download step runs this again; wrap URL.* only once per document.
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
