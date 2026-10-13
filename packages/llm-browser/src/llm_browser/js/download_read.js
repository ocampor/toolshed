// Stash a download's bytes under `key` for download_slice; returns their size.
async ([url, key]) => {
  let blob = window.__lbKeptBlob && window.__lbKeptBlob(url);
  if (!blob) {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok) throw new Error(`refetch answered ${response.status}`);
    blob = await response.blob();
  }
  if (!window.__lbDownloads) {
    Object.defineProperty(window, "__lbDownloads", { value: new Map() });
  }
  window.__lbDownloads.set(key, blob);
  return blob.size;
}
