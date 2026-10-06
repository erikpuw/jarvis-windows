/**
 * Morphing icons for the static buttons (morphicons + lucide data).
 *
 * Each button's state is already written to the DOM by main.ts (a class on
 * the button, or a display style on a related element). We observe that and
 * morph — so no state-changing code path needs to know about icons.
 */

import { defineMorphIcon, type MorphIconElement } from "morphicons/element";
import {
  Video, VideoOff, Mic, MicOff, Volume2, VolumeX, SquareTerminal, X,
  History, MapPin, EllipsisVertical, Plus, ChevronDown,
  Paperclip, Send, LoaderCircle, Check, CircleDashed,
  Save, PlugZap, Upload, Trash2, RefreshCw, type IconNode,
  AppWindow, Monitor, Moon, Mail, Bird, Image, Music, NotebookPen, FolderOpen,
  Wrench, FileText, Search, Shield, Eye, Camera, Bot, Slash, AtSign, Orbit, CircleOff,
} from "lucide";

defineMorphIcon();

type Spec = {
  btn: string;               // button id that hosts the icon
  watch?: string;            // element whose attributes carry the state (default: the button)
  on: (el: HTMLElement) => boolean;
  off: IconNode;
  onIcon: IconNode;
  size: number;
  stroke?: number;           // default 1.5
};

const cls = (c: string) => (el: HTMLElement) => el.classList.contains(c);
const shown = (el: HTMLElement) => el.style.display !== "none" && el.style.display !== "";

const SPECS: Spec[] = [
  { btn: "btn-webcam-toggle", on: cls("active"), off: VideoOff, onIcon: Video, size: 18 },
  { btn: "btn-mute", on: cls("muted"), off: Mic, onIcon: MicOff, size: 18 },
  { btn: "btn-tts-toggle", on: cls("muted"), off: Volume2, onIcon: VolumeX, size: 18 },
  { btn: "btn-cmd-bar", on: cls("active"), off: SquareTerminal, onIcon: ChevronDown, size: 18 },
  { btn: "btn-orb-toggle", on: cls("orb-off"), off: Orbit, onIcon: CircleOff, size: 18 },
  { btn: "btn-map", on: cls("active"), off: MapPin, onIcon: X, size: 18 },
  { btn: "btn-menu", watch: "menu-dropdown", on: shown, off: EllipsisVertical, onIcon: X, size: 18 },
  { btn: "btn-upload", watch: "file-pinned-container", on: shown, off: Plus, onIcon: Paperclip, size: 14, stroke: 2.5 },
  { btn: "cmd-send", on: cls("sent"), off: Send, onIcon: Check, size: 14 },
];

const STATUS_ICON: Record<string, IconNode> = { active: LoaderCircle, completed: Check, failed: X };

/**
 * Status glyph (spinner / check / x) inside `host`, kept mounted across updates
 * so a status change morphs in place. Callers must patch, not rebuild, `host`:
 * a detached <morph-icon> destroys its animation driver.
 * Classes go on a wrapper span because <morph-icon> is display:contents.
 */
export function setStatusIcon(host: Element, status: string, prefix: "flow" | "tracker", size: number): void {
  const icon = STATUS_ICON[status] ?? CircleDashed;
  let wrap = host.querySelector<HTMLElement>(":scope > .status-glyph");
  if (!wrap) {
    const mi = document.createElement("morph-icon");
    mi.setAttribute("size", String(size));
    mi.setAttribute("stroke-width", "2.5");
    mi.set(icon);
    wrap = document.createElement("span");
    wrap.appendChild(mi);
    host.appendChild(wrap);
  } else if (wrap.dataset.status !== status) {
    wrap.querySelector("morph-icon")!.morphTo(icon);
  }
  wrap.dataset.status = status;
  const variant = status === "active" ? "ring" : status in STATUS_ICON ? status : "pending";
  wrap.className = `status-glyph ${prefix}-status-icon ${prefix}-${variant}`;
}

for (const s of SPECS) {
  const btn = document.getElementById(s.btn);
  const watched = s.watch ? document.getElementById(s.watch) : btn;
  if (!btn || !watched) continue;

  const icon = document.createElement("morph-icon");
  icon.setAttribute("size", String(s.size));
  icon.setAttribute("stroke-width", String(s.stroke ?? 1.5));
  btn.replaceChildren(icon);

  let state = s.on(watched);
  icon.set(state ? s.onIcon : s.off);
  // Attribute mutations fire for every class/style write; morph only on real flips.
  new MutationObserver(() => {
    const next = s.on(watched);
    if (next === state) return;
    state = next;
    icon.morphTo(next ? s.onIcon : s.off); // morphTo retargets an in-flight morph
  }).observe(watched, { attributes: true, attributeFilter: ["class", "style"] });
}

/** A static lucide icon as a <morph-icon> (sidebar, close/menu buttons). */
export function makeIcon(icon: IconNode, size = 18, strokeWidth = 1.75): MorphIconElement {
  const mi = document.createElement("morph-icon");
  mi.setAttribute("size", String(size));
  mi.setAttribute("stroke-width", String(strokeWidth));
  mi.set(icon);
  return mi;
}

const ACTION_ICON = { save: Save, test: PlugZap, upload: Upload, delete: Trash2, refresh: RefreshCw } as const;
export type ActionKind = keyof typeof ACTION_ICON;
const ACTION_FEEDBACK_MS = 1200;

/** Prepends the idle icon for an action button (idempotent). */
export function decorateActionButton(btn: HTMLButtonElement, kind: ActionKind): void {
  btn.dataset.action = kind;
  if (btn.querySelector(":scope > morph-icon")) return;
  btn.prepend(makeIcon(ACTION_ICON[kind], 15, 2));
}

/**
 * Runs `task` behind a morphing icon: idle → spinner → ✓/✗ → idle.
 * `task` returning `false` means "cancelled" (restore silently); throwing means
 * failure. The result text goes to `[data-feedback-for="<btn.id>"]` when present;
 * a failure with no feedback slot falls back to alert() so it is never silent.
 * The button's `disabled` is never touched — callers own it — so the busy lock
 * is a class (pointer-events) plus an early return on re-entry.
 */
export async function runAction(
  btn: HTMLButtonElement,
  task: () => Promise<void | false>,
  okText = "Đã lưu",
): Promise<boolean> {
  if (btn.classList.contains("is-busy")) return false;
  const kind = (btn.dataset.action ?? "save") as ActionKind;
  decorateActionButton(btn, kind);
  const icon = btn.querySelector<MorphIconElement>(":scope > morph-icon")!;
  const slot = btn.id ? document.querySelector<HTMLElement>(`[data-feedback-for="${btn.id}"]`) : null;
  if (slot) { slot.textContent = ""; delete slot.dataset.state; }

  btn.classList.remove("is-ok", "is-error");
  btn.classList.add("is-busy");
  btn.setAttribute("aria-busy", "true");
  icon.morphTo(LoaderCircle);

  let outcome: "ok" | "error" | "cancel";
  let message = "";
  try {
    outcome = (await task()) === false ? "cancel" : "ok";
  } catch (error) {
    outcome = "error";
    message = error instanceof Error ? error.message : String(error);
  }
  btn.classList.remove("is-busy");
  btn.removeAttribute("aria-busy");

  if (outcome === "cancel") {
    icon.morphTo(ACTION_ICON[kind]);
    return false;
  }
  const ok = outcome === "ok";
  btn.classList.add(ok ? "is-ok" : "is-error");
  icon.morphTo(ok ? Check : X);
  if (slot) {
    slot.textContent = ok ? okText : message;
    slot.dataset.state = ok ? "ok" : "error";
  } else if (!ok) {
    alert(message);
  }
  await new Promise((resolve) => setTimeout(resolve, ACTION_FEEDBACK_MS));
  btn.classList.remove("is-ok", "is-error");
  icon.morphTo(ACTION_ICON[kind]);
  return ok;
}

// Agent cards: backend titles are "<emoji> Agent <Name>" (engine/agents/agent_*.py).
// Keyed by the name after "Agent "; an agent missing here still renders, with Bot.
const AGENT_ICON: Record<string, IconNode> = {
  control: AppWindow, desktop: Monitor, dream: Moon, email: Mail, goose: Bird,
  history: History, image: Image, media: Music, notes: NotebookPen,
  office: FolderOpen, project: Wrench, rag: FileText, search: Search, security: Shield,
  vision: Eye, webcam: Camera,
};

/** "💻 Agent Desktop" → { name: "Agent Desktop", icon }. */
export function agentBadge(title: string): { name: string; icon: MorphIconElement } {
  const name = title.replace(/^[^\p{L}\p{N}]+/u, "").trim() || "Agent";
  const key = name.toLowerCase().replace(/^agent\s+/, "").split(/\s+/)[0];
  return { name, icon: makeIcon(AGENT_ICON[key] ?? Bot, 15, 1.75) };
}
