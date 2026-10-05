/**
 * Settings → Nhật ký: one page, four tabs — chat history, jarvis.log, security log, TTS log — like the categories of Memory Control.
 * It replaces the history panel and the "Jarvis Logs" button of the main screen. Password-locked like Memory Control
 * (settings/lock.ts; /api/history, /api/conversations and /api/logs* are gated by engine/UIUX/memory_lock.py): one unlock opens all four tabs.
 * It is its own page, not a card of the System page: that page checks connections every few seconds and every check writes an
 * httpx line into jarvis.log, so the log would fill with its own noise.
 * Chat sessions are not a tab of their own: the chat-history tab has two sub-views, "Toàn bộ" (everything in time order) and "Phiên chat".
 * "Phiên chat" is two frames like Memory Control: the list of sessions and the frame that reads the chosen one. On a phone only one frame
 * shows at a time (list → tap a session → reader, with the back button above the reader and outside its scroll).
 * Everything is shown as plain text (textContent), so a stored message or log line can never inject markup into the page.
 */
import { apiGet } from "./api";
import { registerLockable, isUnlocked } from "./lock";
import { makeIcon } from "../icons";
import { MessagesSquare, ScrollText, ShieldAlert, AudioLines, type IconNode } from "lucide";

type TabId = "history" | "jarvis" | "security" | "tts";
type HistView = "all" | "sessions";
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
interface SessionRow { session_id: string; source: Source; msg_count: number; started_at: number; last_msg: number }

const SOURCE_LABEL: Record<Source, string> = { web: "Web", telegram: "Telegram", legacy: "Cũ (chưa có phiên)" };
const SOURCE_SHORT: Record<Source, string> = { web: "Web", telegram: "Telegram", legacy: "Cũ" };
const SPLIT_MIN_WIDTH = 769; // from here the two frames sit side by side (the settings drawer layout breaks at 768, like Memory Control)

let active: TabId = "history";
let histView: HistView = "all"; // sub-view of the chat-history tab
let openSession: string | null = null; // the session shown in the reader frame
let openSessionSource: Source | undefined;
let loadSeq = 0; // a slow answer of a tab the user already left must not overwrite the one on screen
let listSeq = 0;
let detailSeq = 0;

const historyEl = () => document.getElementById("history-settings-list"); // reader frame / "Toàn bộ" column
const sessionsEl = () => document.getElementById("history-sessions-list");
const logEl = () => document.getElementById("logs-content");
const tabOf = (id: TabId) => TABS.find(t => t.id === id)!;
const isListTab = (id: TabId) => id === "history";
const noteClass = (id: TabId) => (isListTab(id) ? "history-empty" : "log-line");
const splitLayout = () => window.matchMedia(`(min-width: ${SPLIT_MIN_WIDTH}px)`).matches;

function renderNav(): void {
  const nav = document.getElementById("logs-category-nav");
  if (!nav) return;
  if (!nav.childElementCount) {
    for (const tab of TABS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sd-mem-cat-btn";
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
  nav.querySelectorAll<HTMLElement>("[data-log-tab]").forEach(b => b.classList.toggle("active", b.dataset.logTab === active));
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
    body.textContent = String(msg.content ?? "").trim();
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

/** Which frames show: sub-view buttons only on the history tab, the session list only in "Phiên chat", the back bar only while a session is open. */
function updateView(): void {
  const sessions = active === "history" && histView === "sessions";
  const reading = sessions && openSession !== null;
  const bar = document.getElementById("history-subbar");
  if (bar) bar.hidden = active !== "history";
  bar?.querySelectorAll<HTMLElement>("[data-hist-view]").forEach(b => b.classList.toggle("active", b.dataset.histView === histView));
  const split = document.getElementById("history-view");
  if (split) {
    split.dataset.view = active === "history" ? histView : "";
    split.dataset.reading = reading ? "1" : "0";
  }
  const list = sessionsEl();
  if (list) list.hidden = !sessions;
  document.getElementById("card-logs")?.classList.toggle("reading", reading); // phone: hides the title/sub-view buttons while reading
  const back = document.getElementById("history-back");
  if (back) back.hidden = !reading;
  const title = document.getElementById("history-back-title");
  if (title) title.textContent = reading ? `${openSessionSource ? SOURCE_LABEL[openSessionSource] + " · " : ""}${openSession}` : "";
  sessionsEl()?.querySelectorAll<HTMLElement>(".sd-session-row").forEach(r => r.classList.toggle("selected", reading && r.dataset.session === openSession));
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
    src.textContent = SOURCE_SHORT[s.source];
    const id = document.createElement("span");
    id.className = "sd-session-id";
    id.textContent = s.session_id;
    const when = new Date(s.last_msg * 1000);
    const meta = document.createElement("span");
    meta.className = "sd-session-meta";
    meta.textContent = `${s.msg_count} tin · ${dayLabel(when)} ${when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    btn.append(src, id, meta);
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
    const data = await apiGet<{ success: boolean; sessions?: SessionRow[]; error?: string }>("/api/conversations/sessions?limit=50");
    if (seq !== listSeq || !isUnlocked("logs")) return;
    if (!data.success) return showNote(list, `Không tải được danh sách phiên chat: ${data.error ?? "lỗi không rõ"}`, "history-empty");
    const sessions = data.sessions ?? [];
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
  if (tab.id === "history" && histView === "sessions") {
    await loadSessionList();
    if (openSession) await loadSessionDetail();
    return;
  }
  const target = isListTab(tab.id) ? historyEl() : logEl();
  showNote(target, "Đang tải…", noteClass(tab.id));
  try {
    if (tab.id === "history") {
      const data = await apiGet<{ success: boolean; history?: ChatMessage[]; error?: string }>("/api/history?limit=100");
      if (seq !== loadSeq || !isUnlocked("logs")) return; // another tab was opened, or it locked again while loading
      if (data.success) renderHistory(data.history ?? []);
      else showNote(target, `Không tải được ${tab.label}: ${data.error ?? "lỗi không rõ"}`, noteClass(tab.id));
    } else {
      const data = await apiGet<{ success: boolean; logs?: string; error?: string }>(tab.path!);
      if (seq !== loadSeq || !isUnlocked("logs")) return;
      if (data.success) renderLog(data.logs ?? "");
      else showNote(target, `Không tải được ${tab.label}: ${data.error ?? "lỗi không rõ"}`, noteClass(tab.id));
    }
  } catch {
    if (seq === loadSeq && isUnlocked("logs")) showNote(target, "Lỗi kết nối khi tải.", noteClass(tab.id));
  }
}

function showTab(id: TabId): void {
  active = id;
  histView = "all";
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
  histView = "all";
  openSession = null;
  active = "history";
  for (const el of [historyEl(), sessionsEl(), logEl()]) if (el) el.textContent = "";
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
  document.getElementById("history-subbar")?.addEventListener("click", (event) => {
    const btn = (event.target as HTMLElement).closest<HTMLElement>("[data-hist-view]");
    if (!btn || !isUnlocked("logs") || btn.dataset.histView === histView) return;
    histView = btn.dataset.histView as HistView;
    openSession = null;
    detailSeq++;
    updateView();
    void load();
  });
  document.getElementById("history-back-btn")?.addEventListener("click", () => {
    if (!isUnlocked("logs")) return;
    openSession = null;
    detailSeq++;
    updateView();
    showNote(historyEl(), "Chọn một phiên ở bên trái để xem.", "history-empty");
  });
  document.getElementById("logs-refresh")?.addEventListener("click", () => { if (isUnlocked("logs")) void load(); });
}
