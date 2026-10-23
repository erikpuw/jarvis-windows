// Chat sessions panel (spec 2026-10-23 §2): the signed-in user's chats on the left of the PC screen (folded, a 60px icon rail like the
// Dashboard menu's), and on an iPhone the same panel as a drawer opened by the home button. Loading, switching and the lock while a turn runs are main.ts's job; this file
// only lists, highlights and reports clicks. Styles: style.css (#sessions).
import { createElement, MessageSquare, PanelLeft, PanelLeftClose, Plus, Settings } from "lucide";
import { apiGet } from "./settings/api";
import { onAnimGate } from "./anim-gate";

export interface SessionItem { session_id: string; title: string; last_msg: number }

export interface SessionsPanel {
  refresh(): Promise<void>;
  setActive(id: string | null): void;
  setLocked(on: boolean): void;
  openDrawer(): void;
  closeDrawer(): void;
}

const COLLAPSED_KEY = "jarvis_sessions_collapsed";
const DAY_MS = 86400000;

/** Hôm nay / Hôm qua / Cũ hơn by the local date of the last message (last_msg is epoch seconds). */
function groupLabel(lastMsgSec: number, now: Date = new Date()): string {
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(now) - startOfDay(new Date(lastMsgSec * 1000))) / DAY_MS);
  if (days <= 0) return "Hôm nay";
  if (days === 1) return "Hôm qua";
  return "Cũ hơn";
}

/** A button's text: hidden in the folded rail (style.css), so only its icon shows there. */
function label(text: string): HTMLSpanElement {
  const span = document.createElement("span");
  span.className = "sess-label";
  span.textContent = text;
  return span;
}

export function mountSessions(opts: { onPick(id: string): void; onNew(): void; onDashboard(): void }): SessionsPanel {
  const aside = document.createElement("aside");
  aside.id = "sessions";

  const head = document.createElement("div");
  head.className = "sess-head";
  const newBtn = document.createElement("button");
  newBtn.type = "button";
  newBtn.id = "sessions-new";
  newBtn.className = "sess-new";
  newBtn.title = "Phiên mới";
  newBtn.append(createElement(Plus, { width: 16, height: 16 }), label("Phiên mới"));
  const collapseBtn = document.createElement("button");
  collapseBtn.type = "button";
  collapseBtn.id = "sessions-collapse";
  collapseBtn.className = "sess-icon";
  collapseBtn.title = "Thu gọn thanh phiên";
  head.append(newBtn, collapseBtn);

  const list = document.createElement("div");
  list.className = "sess-list";

  const dash = document.createElement("button");
  dash.type = "button";
  dash.id = "sessions-dash";
  dash.className = "sess-dash";
  dash.title = "Bảng điều khiển";
  dash.append(createElement(Settings, { width: 16, height: 16 }), label("Bảng điều khiển"));

  aside.append(head, list, dash);

  const scrim = document.createElement("div");
  scrim.id = "sessions-scrim";
  document.body.append(aside, scrim);

  let rows: SessionItem[] = [];
  let active: string | null = null;
  let locked = false;
  let refreshSeq = 0;

  const setCollapsed = (on: boolean) => {
    document.documentElement.classList.toggle("sessions-collapsed", on);
    collapseBtn.replaceChildren(createElement(on ? PanelLeft : PanelLeftClose, { width: 18, height: 18 }));
    collapseBtn.title = on ? "Mở thanh phiên" : "Thu gọn thanh phiên";
    try { localStorage.setItem(COLLAPSED_KEY, on ? "1" : "0"); } catch { /* private window: the choice lasts this page only */ }
  };
  let collapsed = false;
  try { collapsed = localStorage.getItem(COLLAPSED_KEY) === "1"; } catch { /* unreadable: expanded */ }
  setCollapsed(collapsed);

  const openDrawer = () => {
    document.documentElement.classList.add("sessions-drawer");
    void refresh();
  };
  const closeDrawer = () => document.documentElement.classList.remove("sessions-drawer");

  const render = () => {
    list.replaceChildren();
    let group = "";
    for (const row of rows) {
      const groupName = groupLabel(row.last_msg);
      if (groupName !== group) {
        group = groupName;
        const h = document.createElement("div");
        h.className = "sess-group";
        h.textContent = groupName;
        list.append(h);
      }
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sess-row" + (row.session_id === active ? " on" : "");
      b.dataset.id = row.session_id;
      b.title = row.title;
      // the icon shows only in the folded rail, where it stands for the chat (style.css)
      const icon = createElement(MessageSquare, { width: 18, height: 18 });
      icon.classList.add("sess-row-icon");
      b.append(icon, label(row.title));
      list.append(b);
    }
  };

  async function refresh(): Promise<void> {
    const seq = ++refreshSeq;
    try {
      const res = await apiGet<{ success: boolean; sessions: SessionItem[] }>("/api/sessions/mine?limit=50");
      if (seq !== refreshSeq) return; // a newer list is on its way
      rows = res.sessions ?? [];
      render();
    } catch (err) {
      console.warn("[sessions] list failed:", err);
    }
  }

  // a click on a row while locked does nothing at all (the drawer stays where it is, the row does not change)
  list.addEventListener("click", (e) => {
    const row = (e.target as HTMLElement).closest<HTMLElement>(".sess-row");
    const id = row?.dataset.id;
    if (!id || locked) return;
    closeDrawer();
    opts.onPick(id);
  });
  newBtn.addEventListener("click", () => {
    if (locked) return;
    closeDrawer();
    opts.onNew();
  });
  dash.addEventListener("click", () => {
    closeDrawer();
    opts.onDashboard();
  });
  collapseBtn.addEventListener("click", () => setCollapsed(!document.documentElement.classList.contains("sessions-collapsed")));
  scrim.addEventListener("click", closeDrawer);
  window.addEventListener("jarvis:sessions-toggle", () => {
    if (document.documentElement.classList.contains("sessions-drawer")) closeDrawer();
    else openDrawer();
  });
  // the drawer is for a phone only: a window that grows to a PC width drops it
  window.matchMedia("(min-width: 769px)").addEventListener("change", (e) => { if (e.matches) closeDrawer(); });
  // no slide while Settings or a video covers the page (anim-gate): the drawer just appears and goes
  onAnimGate((paused) => aside.classList.toggle("still", paused));

  void refresh();

  return {
    refresh,
    setActive(id) {
      active = id;
      list.querySelectorAll<HTMLElement>(".sess-row").forEach((el) => el.classList.toggle("on", el.dataset.id === id));
    },
    setLocked(on) {
      locked = on;
      aside.classList.toggle("locked", on);
    },
    openDrawer,
    closeDrawer,
  };
}
