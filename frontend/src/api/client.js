const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body);
    throw new Error(message || `Request failed (${response.status})`);
  }
  return body;
}
