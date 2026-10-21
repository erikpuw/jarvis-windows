// /api/settings/status probes GPUs/NPUs via PowerShell (~2–4s), so 8s timed out under load.
export const REQUEST_TIMEOUT_MS = 20000;

// Memory Control, chat history and the system log are locked on the backend (engine/UIUX/memory_lock.py): its data endpoints need the token the lock screen got.
const MEMORY_API = /^\/api\/(learnings|memories|workflows|outcomes|corrections|conversations|evolution|memory-control|history|logs|users)(\/|\?|$)/;
export const MEMORY_LOCKED_EVENT = "jarvis:memory-locked";
let memoryToken = "";
try {
  memoryToken = (typeof localStorage !== "undefined" && (localStorage.getItem("jarvis_token") || localStorage.getItem("jarvis_memory_token"))) || "";
} catch {}

export function getMemoryToken(): string {
  if (memoryToken) return memoryToken;
  try {
    return (typeof localStorage !== "undefined" && (localStorage.getItem("jarvis_token") || localStorage.getItem("jarvis_memory_token"))) || "";
  } catch {
    return "";
  }
}

export function setMemoryToken(token: string): void {
  memoryToken = token;
  try {
    if (typeof localStorage !== "undefined") {
      if (token) {
        localStorage.setItem("jarvis_token", token);
        localStorage.setItem("jarvis_memory_token", token);
      } else {
        localStorage.removeItem("jarvis_token");
        localStorage.removeItem("jarvis_memory_token");
      }
    }
  } catch {}
}

export async function fetchWithTimeout(url: string, init?: RequestInit): Promise<Response> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  const memory = MEMORY_API.test(url);
  const token = getMemoryToken();
  try {
    const headers = new Headers(init?.headers);
    if (token) {
      headers.set("X-Memory-Token", token);
      headers.set("Authorization", `Bearer ${token}`);
    }
    const res = await fetch(url, { ...init, headers, signal: ctrl.signal });
    if (memory && res.status === 401) window.dispatchEvent(new Event(MEMORY_LOCKED_EVENT));
    return res;
  } catch (err) {
    if (ctrl.signal.aborted) throw new Error(`Máy chủ không phản hồi sau ${REQUEST_TIMEOUT_MS / 1000}s`);
    throw err;
  } finally {
    clearTimeout(t);
  }
}

/** Parses the JSON body even on HTTP errors so the backend's own `error`/`code` reaches the UI. */
async function readJson<T>(res: Response, label: string): Promise<T> {
  let body: any = null;
  try { body = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) throw new Error(body?.error || body?.code || body?.detail || `${label} → HTTP ${res.status}`);
  return body as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  return readJson<T>(await fetchWithTimeout(path), `GET ${path}`);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithTimeout(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson<T>(res, `POST ${path}`);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(path, { method: "DELETE" });
  return readJson<T>(res, `DELETE ${path}`);
}

export function escapeHtml(str: any): string {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function formatNumber(n: number | undefined): string {
  if (n === undefined || n === null || isNaN(n)) return "--";
  return n.toLocaleString("vi-VN");
}

export function formatUptime(seconds: number | undefined): string {
  if (!seconds || seconds < 0) return "--";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
