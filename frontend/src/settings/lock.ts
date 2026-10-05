/**
 * Password lock shared by the protected Settings areas: Memory Control, chat history and the system log
 * (docs/superpowers/specs/2026-10-04-memory-lock-design.md). The real blocking is on the backend
 * (engine/UIUX/memory_lock.py); this only asks for the password and keeps the token in a variable (never in storage).
 * One token at a time, tied to the area that asked for it: entering another area or leaving locks everything again.
 */
import { apiGet, fetchWithTimeout, setMemoryToken, MEMORY_LOCKED_EVENT } from "./api";

export interface Lockable {
  /** Element ids: `${id}-lock` (screen), `${id}-lock-form`, `-input`, `-btn`, `-msg`. */
  id: string;
  /** Element that gets the `locked` class (blur + password screen). */
  root: () => HTMLElement | null;
  /** Password accepted: load the data. */
  onUnlock: () => void | Promise<void>;
  /** Drop every loaded record from memory and page. */
  onLock: () => void;
}

const NOT_CONFIGURED = "Chưa đặt MEMORY_PASSWORD trong .env nên vùng này đang khóa. Thêm vào .env rồi khởi động lại JARVIS.";
const lockables = new Map<string, Lockable>();
let token = "";
let activeId = "";
let listening = false;

const part = (id: string, suffix: string) => document.getElementById(`${id}-lock-${suffix}`);

function setMessage(id: string, text: string, error = false): void {
  const el = part(id, "msg");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", error);
}

export function isUnlocked(id: string): boolean {
  return token !== "" && activeId === id;
}

/** Locks every area: forgets the token on both sides and empties what each area had loaded. */
export function lockAll(message = "Nhập mật khẩu để mở.", error = false): void {
  const old = token;
  token = "";
  activeId = "";
  setMemoryToken("");
  if (old) void fetchWithTimeout("/api/memory-lock/lock", { method: "POST", headers: { "X-Memory-Token": old } }).catch(() => {});
  for (const l of lockables.values()) {
    l.root()?.classList.add("locked");
    l.onLock();
    const input = part(l.id, "input") as HTMLInputElement | null;
    if (input) input.value = "";
    setMessage(l.id, message, error);
  }
}

async function submit(l: Lockable): Promise<void> {
  const input = part(l.id, "input") as HTMLInputElement | null;
  if (!input) return;
  try {
    const res = await fetchWithTimeout("/api/memory-lock/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: input.value }),
    });
    const body = await res.json().catch(() => ({} as Record<string, unknown>));
    if (!res.ok || !body.token) {
      input.value = "";
      setMessage(l.id, body.code === "not_configured" ? NOT_CONFIGURED : "Sai mật khẩu.", true);
      input.focus();
      return;
    }
    token = String(body.token);
    activeId = l.id;
    setMemoryToken(token);
    input.value = "";
    l.root()?.classList.remove("locked");
    await l.onUnlock();
  } catch (error) {
    setMessage(l.id, `Không mở khóa được: ${error instanceof Error ? error.message : error}`, true);
  }
}

/** Call once per area, after its markup exists. */
export function registerLockable(l: Lockable): void {
  lockables.set(l.id, l);
  document.getElementById(`${l.id}-lock-form`)?.addEventListener("submit", (event) => {
    event.preventDefault();
    void submit(l);
  });
  if (!listening) {
    listening = true;
    window.addEventListener(MEMORY_LOCKED_EVENT, () => { if (token) lockAll("Phiên đã hết hiệu lực, nhập lại mật khẩu.", true); });
  }
}

/** Opening a protected area always asks for the password again (unless this very area is already open). */
export async function enterLockable(id: string): Promise<void> {
  if (isUnlocked(id)) return;
  lockAll();
  const input = part(id, "input") as HTMLInputElement | null;
  const button = part(id, "btn") as HTMLButtonElement | null;
  try {
    const { configured } = await apiGet<{ configured: boolean }>("/api/memory-lock/status");
    if (input) input.disabled = !configured;
    if (button) button.disabled = !configured;
    if (!configured) setMessage(id, NOT_CONFIGURED, true);
    else input?.focus();
  } catch {
    setMessage(id, "Không kiểm tra được trạng thái khóa.", true);
  }
}
