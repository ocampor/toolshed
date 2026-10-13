// One base64 slice of a stashed download; a single evaluate dies near 256 MB.
([key, start, end]) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.slice(reader.result.indexOf(",") + 1));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(window.__k7d.get(key).slice(start, end));
  })
