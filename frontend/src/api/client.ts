// API base resolution:
// - Default "" → same-origin relative paths. Works in dev (vite /api proxy) and in
//   prod (this deployment serves the SPA behind Caddy, which reverse-proxies /api/*
//   to the backend on the same origin). Same-origin avoids the cross-origin :8000
//   trap: a separate :8000 host has no TLS here, so absolute URLs break the whole app.
// - Override with VITE_API_BASE only for cross-origin setups (e.g. backend on a
//   different host/port reachable directly).
const BASE = import.meta.env.VITE_API_BASE ?? "";

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
