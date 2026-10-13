// Run before an attached download's click: a page that revokes its blob URL
// on the click would leave the in-page refetch nothing to read, so revokes in
// this document are deferred ~30 s. Non-enumerable marker to stay out of sight.
(() => {
  // Every download step runs this again; wrap only once per document.
  if (window.__k7b) return;
  const revoke = URL.revokeObjectURL;
  URL.revokeObjectURL = function (url) {
    setTimeout(() => revoke.call(URL, url), 30000);
  };
  Object.defineProperty(window, "__k7b", { value: true });
})()
