// Default to the backend on :8000 of whatever host served the page, so external
// access works (browser reaches <host>:8000). Override with VITE_API_BASE if needed.
const BASE = import.meta.env.VITE_API_BASE ??
  `${window.location.protocol}//${window.location.hostname}:8000`;

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`GET ${path} failed: ${r.status}`);
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST ${path} failed: ${r.status}`);
  return r.json() as Promise<T>;
}
