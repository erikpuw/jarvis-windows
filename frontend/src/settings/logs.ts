/**
 * Settings → Nhật ký: one page, four tabs — chat history, jarvis.log, security log, TTS log — like the categories of Memory Control.
 * It replaces the history panel and the "Jarvis Logs" button of the main screen. No password of its own: the page follows the Auth
 * Gateway session (settings/lock.ts), and the server answers the admin-only routes (/api/conversations, /api/logs*) to admins only.
 * It is its own page, not a card of the System page: that page checks connections every few seconds and every check writes an
 * httpx line into jarvis.log, so the log would fill with its own noise.
 * The chat-history tab is admin only and lists chat sessions, each with its title and owner (user_name). The admin filters the list
 * by owner (#history-owner-filter); the reader frame opens a session read-only (no send or continue control).
 * It is two frames like Memory Control: the list of sessions and the frame that reads the chosen one. On a phone only one frame
 * shows at a time (list → tap a session → reader, with the back button above the reader and outside its scroll).
 * Members have no tab here: the Dashboard hides the Nhật ký item for them (settings/pages.ts MEMBER_HIDDEN_PAGES).
 * List rows and log lines use textContent, so a stored line can never inject markup into the page; the chat reader renders its
 * messages through formatMarkdown (markdown.ts).
 */
import { apiGet, apiDelete } from "./api";
import { registerLockable, isUnlocked } from "./lock";
import { getCurrentUserRole } from "../auth-gate";
import { makeIcon } from "../icons";
import { MessagesSquare, ScrollText, ShieldAlert, AudioLines, type IconNode } from "lucide";
import { formatMarkdown } from "../markdown";

type TabId = "history" | "jarvis" | "security" | "tts";
interface Tab { id: TabId; label: string; icon: IconNode; color: string; path?: string }

const LOG_LINES = 300;
const TABS: Tab[] = [
  { id: "history", label: "Lịch sử chat", icon: MessagesSquare, color: "#60a5fa" },
  { id: "jarvis", label: "Jarvis log", icon: ScrollText, color: "#a78bfa", path: `/api/logs?lines=${LOG_LINES}` },
  { id: "security", label: "Log bảo mật", icon: ShieldAlert, color: "#f59e0b", path: `/api/logs/security?lines=${LOG_LINES}` },
  { id: "tts", label: "Log TTS", icon: AudioLines, color: "#22d3ee", path: `/api/logs/tts?lines=${LOG_LINES}` },
];

interface ChatMessage { role: string; content: string; created_at: number; session_id?: string }
type Source = "web" | "telegram" | "legacy";
interface SessionRow { session_id: string; source: Source; device?: string; msg_count: number; started_at: number; last_msg: number; title?: string; user_id?: string; user_name?: string }
interface Owner { id: string; name: string }

const SOURCE_LABEL: Record<Source, string> = { web: "Web", telegram: "Telegram", legacy: "Cũ (chưa có phiên)" };
const SOURCE_SHORT: Record<Source, string> = { web: "Web", telegram: "Telegram", legacy: "Cũ" };
// the device that opened a web session (engine/core/memory.py session_devices; none for sessions older than that)
const DEVICE_SHORT: Record<string, string> = { ios: "iOS", android: "Android", desktop: "PC", mobile: "Mobile" };
const SPLIT_MIN_WIDTH = 769; // from here the two frames sit side by side (the settings drawer layout breaks at 768, like Memory Control)

let active: TabId = "history";
let ownerFilter = ""; // user id the session list is filtered by ("" = every owner)
let openSession: string | null = null; // the session shown in the reader frame
let openSessionSource: Source | undefined;
let loadSeq = 0; // a slow answer of a tab the user already left must not overwrite the one on screen
let listSeq = 0;
let detailSeq = 0;

const historyEl = () => document.getElementById("history-settings-list"); // reader frame
const sessionsEl = () => document.getElementById("history-sessions-list");
const ownerEl = () => document.getElementById("history-owner-filter") as HTMLSelectElement | null;
const logEl = () => document.getElementById("logs-content");
const tabOf = (id: TabId) => TABS.find(t => t.id === id)!;
const isListTab = (id: TabId) => id === "history";
const noteClass = (id: TabId) => (isListTab(id) ? "history-empty" : "log-line");
const splitLayout = () => window.matchMedia(`(min-width: ${SPLIT_MIN_WIDTH}px)`).matches;

function renderNav(): void {
  const nav = document.getElementById("logs-category-nav");
  if (!nav) return;
  // members get no tab at all: the Dashboard does not offer this page to them
  const availableTabs = getCurrentUserRole() === "admin" ? TABS : [];

  nav.innerHTML = "";
  for (const tab of availableTabs) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sd-mem-cat-btn" + (tab.id === active ? " active" : "");
    btn.dataset.logTab = tab.id;
    btn.style.setProperty("--cat-color", tab.color);
    const icon = document.createElement("span");
    icon.className = "sd-mem-cat-icon";
    icon.style.color = tab.color;
    icon.appendChild(makeIcon(tab.icon, 16, 2));
    const label = document.createElement("span");
    label.className = "sd-mem-cat-label";
    label.textContent = tab.label;
    btn.append(icon, label);
    nav.appendChild(btn);
  }
}

function dayLabel(date: Date): string {
  const key = date.toLocaleDateString();
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  return key === today.toLocaleDateString() ? "Hôm nay" : key === yesterday.toLocaleDateString() ? "Hôm qua" : key;
}

function showNote(el: HTMLElement | null, text: string, cls: string): void {
  if (!el) return;
  el.textContent = "";
  const note = document.createElement("div");
  note.className = cls;
  note.textContent = text;
  el.appendChild(note);
}

function renderHistory(history: ChatMessage[]): void {
  const el = historyEl();
  if (!el) return;
  if (!history.length) return showNote(el, "Chưa có hội thoại nào được lưu.", "history-empty");
  el.textContent = "";
  let lastDay = "";
  for (const msg of history) {
    const date = new Date(msg.created_at * 1000);
    const day = dayLabel(date);
    if (day !== lastDay) {
      lastDay = day;
      const sep = document.createElement("div");
      sep.className = "history-date-sep";
      sep.textContent = day;
      el.appendChild(sep);
    }
    const item = document.createElement("div");
    item.className = `history-item ${msg.role}`;
    const body = document.createElement("div");
    body.className = "history-content";
    body.innerHTML = formatMarkdown(String(msg.content ?? "").trim());
    const time = document.createElement("span");
    time.className = "history-time";
    time.textContent = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    item.append(body, time);
    el.appendChild(item);
  }
  el.scrollTop = el.scrollHeight;
}

function renderLog(text: string): void {
  const el = logEl();
  if (!el) return;
  el.textContent = "";
  for (const line of text.split("\n")) {
    const row = document.createElement("div");
    row.className = "log-line" + (line.includes("ERROR") ? " error" : line.includes("WARNING") ? " warning" : line.includes("INFO") ? " info" : "");
    row.textContent = line;
    el.appendChild(row);
  }
  el.scrollTop = el.scrollHeight;
}

// ── sessions: list frame + reader frame ──────────────────────────────────────────────────────────────────────────────────────

/** Which frames show: the back bar only while a session is open; the list and the reader sit side by side on a PC, one at a time on a phone. */
function updateView(): void {
  const reading = active === "history" && openSession !== null;
  const bar = document.getElementById("history-subbar");
  if (bar) bar.hidden = active !== "history";
  const split = document.getElementById("history-view");
  if (split) split.dataset.reading = reading ? "1" : "0";
  document.getElementById("card-logs")?.classList.toggle("reading", reading); // phone: hides the title/filter while reading
  const back = document.getElementById("history-back");
  if (back) back.hidden = !reading;
  const title = document.getElementById("history-back-title");
  if (title) title.textContent = reading ? `${openSessionSource ? SOURCE_LABEL[openSessionSource] + " · " : ""}${openSession}` : "";
  sessionsEl()?.querySelectorAll<HTMLElement>(".sd-session-row").forEach(r => r.classList.toggle("selected", reading && r.dataset.session === openSession));
}

function renderOwnerFilter(owners: Owner[]): void {
  const sel = ownerEl();
  if (!sel) return;
  sel.textContent = "";
  sel.append(new Option("Tất cả", ""), ...owners.map(o => new Option(o.name || o.id, o.id)));
  sel.value = ownerFilter;
}

function renderSessions(sessions: SessionRow[]): void {
  const el = sessionsEl();
  if (!el) return;
  if (!sessions.length) return showNote(el, "Chưa có phiên chat nào.", "history-empty");
  el.textContent = "";
  for (const s of sessions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sd-session-row";
    btn.dataset.session = s.session_id;
    const src = document.createElement("span");
    src.className = `sd-session-src ${s.source}`;
    const device = s.source === "web" && s.device ? DEVICE_SHORT[s.device] : "";
    src.textContent = device ? `${SOURCE_SHORT.web} · ${device}` : SOURCE_SHORT[s.source];
    const title = document.createElement("span");
    title.className = "sd-session-title";
    title.textContent = s.title || s.session_id;
    const owner = document.createElement("span");
    owner.className = "sd-session-owner";
    owner.textContent = s.user_name || s.user_id || "";
    const when = new Date(s.last_msg * 1000);
    const meta = document.createElement("span");
    meta.className = "sd-session-meta";
    meta.textContent = `${s.msg_count} tin · ${dayLabel(when)} ${when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    btn.append(src, title, owner, meta);
    btn.addEventListener("click", () => selectSession(s.session_id, s.source));
    el.appendChild(btn);
  }
}

function selectSession(id: string, source: Source | undefined): void {
  openSession = id;
  openSessionSource = source;
  updateView();
  void loadSessionDetail();
}

async function loadSessionDetail(): Promise<void> {
  const id = openSession;
  const reader = historyEl();
  if (!id) return showNote(reader, "Chọn một phiên ở bên trái để xem.", "history-empty");
  const seq = ++detailSeq;
  showNote(reader, "Đang tải…", "history-empty");
  try {
    const data = await apiGet<{ success: boolean; messages?: ChatMessage[]; error?: string }>(`/api/conversations/session/${encodeURIComponent(id)}`);
    if (seq !== detailSeq || openSession !== id || !isUnlocked("logs")) return;
    if (data.success) renderHistory(data.messages ?? []);
    else showNote(reader, `Không tải được phiên chat: ${data.error ?? "lỗi không rõ"}`, "history-empty");
  } catch {
    if (seq === detailSeq && isUnlocked("logs")) showNote(reader, "Lỗi kết nối khi tải.", "history-empty");
  }
}

async function loadSessionList(): Promise<void> {
  const seq = ++listSeq;
  const list = sessionsEl();
  showNote(list, "Đang tải…", "history-empty");
  if (!openSession) showNote(historyEl(), "Chọn một phiên ở bên trái để xem.", "history-empty");
  try {
    const data = await apiGet<{ success: boolean; sessions?: SessionRow[]; users?: Owner[]; error?: string }>(`/api/conversations/sessions?limit=50&user=${encodeURIComponent(ownerFilter)}`);
    if (seq !== listSeq || !isUnlocked("logs")) return;
    if (!data.success) return showNote(list, `Không tải được danh sách phiên chat: ${data.error ?? "lỗi không rõ"}`, "history-empty");
    const sessions = data.sessions ?? [];
    renderOwnerFilter(data.users ?? []); // the owner list always names every owner, whatever the filter
    renderSessions(sessions);
    // two frames side by side: open the newest session right away; on a phone stay on the list (opening would hide it)
    if (!openSession && sessions.length && splitLayout()) selectSession(sessions[0].session_id, sessions[0].source);
    else updateView();
  } catch {
    if (seq === listSeq && isUnlocked("logs")) showNote(list, "Lỗi kết nối khi tải.", "history-empty");
  }
}

// ── tabs ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

async function load(): Promise<void> {
  const seq = ++loadSeq;
  const tab = tabOf(active);
  if (tab.id === "history") {
    await loadSessionList();
    if (openSession) await loadSessionDetail();
    return;
  }
  const target = logEl();
  showNote(target, "Đang tải…", noteClass(tab.id));
  try {
    const data = await apiGet<{ success: boolean; logs?: string; error?: string }>(tab.path!);
    if (seq !== loadSeq || !isUnlocked("logs")) return;
    if (data.success) renderLog(data.logs ?? "");
    else showNote(target, `Không tải được ${tab.label}: ${data.error ?? "lỗi không rõ"}`, noteClass(tab.id));
  } catch {
    if (seq === loadSeq && isUnlocked("logs")) showNote(target, "Lỗi kết nối khi tải.", noteClass(tab.id));
  }
}

function showTab(id: TabId): void {
  active = id;
  openSession = null;
  renderNav();
  updateView();
  const title = document.getElementById("logs-title");
  if (title) title.textContent = tabOf(id).label;
  const hist = document.getElementById("history-view");
  const log = logEl();
  if (hist) hist.hidden = !isListTab(id);
  if (log) log.hidden = isListTab(id);
  void load();
}

/** Locked: nothing stays in the page (lock.ts) and the next unlock starts on the first tab again. */
function clear(): void {
  loadSeq++;
  listSeq++;
  detailSeq++;
  ownerFilter = "";
  openSession = null;
  active = "history";
  for (const el of [historyEl(), sessionsEl(), logEl(), ownerEl()]) if (el) el.textContent = "";
  renderNav();
  updateView();
}

export function initLogsPage(): void {
  renderNav();
  registerLockable({
    id: "logs",
    root: () => document.getElementById("page-logs"),
    onUnlock: () => showTab("history"),
    onLock: clear,
  });
  document.getElementById("logs-category-nav")?.addEventListener("click", (event) => {
    const btn = (event.target as HTMLElement).closest<HTMLElement>("[data-log-tab]");
    if (btn && isUnlocked("logs") && btn.dataset.logTab !== active) showTab(btn.dataset.logTab as TabId);
  });
  ownerEl()?.addEventListener("change", () => {
    if (!isUnlocked("logs")) return;
    ownerFilter = ownerEl()?.value ?? "";
    void loadSessionList(); // the reader keeps the session it shows
  });
  document.getElementById("history-back-btn")?.addEventListener("click", () => {
    if (!isUnlocked("logs")) return;
    openSession = null;
    detailSeq++;
    updateView();
    showNote(historyEl(), "Chọn một phiên ở bên trái để xem.", "history-empty");
  });
  document.getElementById("history-delete-session-btn")?.addEventListener("click", async () => {
    if (!isUnlocked("logs") || !openSession) return;
    const sid = openSession;
    if (!confirm(`Bạn có chắc chắn muốn xóa toàn bộ lịch sử của phiên chat "${sid}" không?`)) return;
    try {
      const res = await apiDelete<{ success: boolean; deleted_count?: number; error?: string }>(`/api/conversations/session/${encodeURIComponent(sid)}`);
      if (res.success) {
        // main.ts decides whether the deleted session is the one the chat has open
        window.dispatchEvent(new CustomEvent("jarvis:session-deleted", { detail: { id: sid } }));
        openSession = null;
        detailSeq++;
        updateView();
        showNote(historyEl(), "Đã xóa phiên chat.", "history-empty");
        await loadSessionList();
      } else {
        alert(`Không thể xóa phiên: ${res.error || "lỗi không rõ"}`);
      }
    } catch (e: any) {
      alert(`Lỗi khi xóa phiên: ${e?.message || e}`);
    }
  });
  document.getElementById("logs-refresh")?.addEventListener("click", () => { if (isUnlocked("logs")) void load(); });
}
