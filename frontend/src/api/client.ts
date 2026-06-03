// API base resolution, in priority order:
// 1. VITE_API_BASE if explicitly set (incl. "" for same-origin).
// 2. Dev (vite): "" → same-origin relative paths, forwarded by vite's /api proxy
//    (works when the page is reached through a tunnel/proxy that can't see :8000).
// 3. Prod: backend on :8000 of whatever host served the page.
const BASE = import.meta.env.VITE_API_BASE ??
  (import.meta.env.DEV ? "" : `${window.location.protocol}//${window.location.hostname}:8000`);

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

export async function apiDelete<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`DELETE ${path} failed: ${r.status}`);
  return r.json() as Promise<T>;
}
