// Stash a download's bytes under `key` for download_slice; returns their size,
// or -1 when the refetch outlives the step's remaining `ms`.
async ([url, key, ms]) => {
  let blob = window.__k7b && window.__k7b(url);
  if (!blob) {
    try {
      const signal = AbortSignal.timeout(ms);
      const response = await fetch(url, { credentials: "include", signal });
      if (!response.ok) throw new Error(`refetch answered ${response.status}`);
      blob = await response.blob();
    } catch (error) {
      if (error.name === "TimeoutError") return -1;
      throw error;
    }
  }
  if (!window.__k7d) {
    Object.defineProperty(window, "__k7d", { value: new Map() });
  }
  window.__k7d.set(key, blob);
  return blob.size;
}
