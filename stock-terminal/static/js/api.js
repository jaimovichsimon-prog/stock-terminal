// ---------------------------------------------------------------------------
// apiFetch — centralised fetch with AbortController timeout + error surfacing
// ---------------------------------------------------------------------------
const API_TIMEOUT_MS = 15000;

async function apiFetch(url, opts = {}, timeoutMs = API_TIMEOUT_MS) {
  const ctrl  = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res;
  } finally {
    clearTimeout(timer);
  }
}

// Safe ticker sanitiser — prevents XSS when building innerHTML template literals
function safeTicker(s) {
  return String(s).replace(/[^A-Z0-9.\-\^]/gi, '').slice(0, 10).toUpperCase();
}
