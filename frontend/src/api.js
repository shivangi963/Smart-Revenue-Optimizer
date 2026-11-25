// Tiny fetch wrapper. Backend URL can be overridden with REACT_APP_API_URL.
export const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// The session token lives in localStorage so a page refresh keeps you signed in.
// (Trade-off: any script injected into the page could read it - fine for this project; a production
// deployment would use an httpOnly cookie plus HTTPS.)
const TOKEN_KEY = 'sro_token';
export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; } };
export const setToken = (t) => {
  try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); } catch (e) { /* private mode */ }
};

let onUnauthorized = null;
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

function describeError(body, status) {
  if (!body) return `Request failed (HTTP ${status})`;
  const d = body.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join('.') || 'input'}: ${e.msg}`).join('; ');
  return `Request failed (HTTP ${status})`;
}

async function request(path, options = {}) {
  const token = getToken();
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
  } catch (e) {
    throw new Error(`Cannot reach the backend at ${API_BASE}`);
  }
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* not json */ }
    const err = new Error(describeError(body, res.status));
    err.status = res.status;
    if (res.status === 401 && token) { setToken(null); if (onUnauthorized) onUnauthorized(err.message); }
    throw err;
  }
  return res.json();
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  put: (path, body) => request(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  del: (path) => request(path, { method: 'DELETE' }),
};

export async function login(username, password) {
  let res;
  try {
    res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username, password }),
    });
  } catch (e) {
    throw new Error(`Cannot reach the backend at ${API_BASE}`);
  }
  let body = null;
  try { body = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) throw new Error(describeError(body, res.status));
  setToken(body.access_token);
  return body;
}
