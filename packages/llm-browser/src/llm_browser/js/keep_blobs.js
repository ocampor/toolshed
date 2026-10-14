// Run before an attached download's click. Blobs made from here on are kept
// for the in-page read, which a CSP blocking blob: fetches would otherwise
// stop; revokes are deferred ~30 s so any blob URL stays fetchable.
// `__k7b` is the non-enumerable lookup and the run-once marker.
(() => {
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
    setTimeout(() => {
      kept.delete(url);
      revoke.call(URL, url);
    }, 30000);
  };
  Object.defineProperty(window, "__k7b", { value: (url) => kept.get(url) });
})()
