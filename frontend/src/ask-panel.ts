// The question box: an `interactive` card the backend waits on (approve / select / input, engine/main/ask_verifi.py)
// rises just above the command bar, like a cookie banner (cuicui.day "Simple Cookie Banner"), instead of sitting in a
// chat bubble (user 2026-10-17: the box in the bubble was ugly and its width jumped). One box at a time: a new question
// replaces it, an answer removes it. Styles in ask-panel.css.
import "./ask-panel.css";

export type AskCard = {
  id: string;
  type: "approve" | "select" | "input";
  title?: string;
  description?: string;
  approveLabel?: string;
  rejectLabel?: string;
  options?: { value: string; label: string; selected?: boolean }[];
  multiple?: boolean;
  submitLabel?: string;
  cancelLabel?: string;
  placeholder?: string;
  value?: string;
};

type Answer = { action: string; value?: unknown };

const ASK_TYPES = new Set(["approve", "select", "input"]);
export const isAskCard = (card: { type?: string } | null | undefined): card is AskCard => !!card && ASK_TYPES.has(card.type || "");

let current: HTMLElement | null = null;

const LIFT_MS = 260; // = the box's rise (ask-in in ask-panel.css)
let basePad: number | null = null; // the chat's own bottom padding (CSS), read before the first lift

/** Glides the chat's bottom padding to `px` ("" = back to the CSS value) in step with the box, instead of one jump
 *  (user 2026-10-17: the chat jumped when the box came). A chat scrolled to its end stays at its end meanwhile. */
function padChat(chat: HTMLElement, px: string) {
  const pinned = chat.scrollHeight - chat.clientHeight - chat.scrollTop < 10;
  chat.style.transition = `padding-bottom ${LIFT_MS}ms cubic-bezier(0.2, 0.9, 0.3, 1)`;
  chat.style.paddingBottom = px;
  const end = performance.now() + LIFT_MS + 40;
  const pin = () => {
    if (pinned) chat.scrollTop = chat.scrollHeight;
    if (performance.now() < end) requestAnimationFrame(pin);
    else chat.style.removeProperty("transition");
  };
  requestAnimationFrame(pin);
}

/** The box hangs over the bottom of the chat: pad the chat so its last message sits just above the box (the message
 *  that led to the question stays readable). Measured from offsetHeight, not the rect: the box is still rising. */
function liftChat(panel: HTMLElement, host: HTMLElement) {
  const chat = document.getElementById("chat-history");
  if (!chat) return;
  if (!chat.style.paddingBottom) basePad = parseFloat(getComputedStyle(chat).paddingBottom);
  const boxTop = host.getBoundingClientRect().top - 8 - panel.offsetHeight;
  const overlap = chat.getBoundingClientRect().bottom - boxTop + 8;
  if (overlap > 0) padChat(chat, `${(basePad ?? 0) + overlap}px`);
}

function close(panel: HTMLElement) {
  if (current === panel) {
    current = null;
    const chat = document.getElementById("chat-history");
    if (chat?.style.paddingBottom) padChat(chat, "");
  }
  panel.classList.add("leaving");
  panel.addEventListener("animationend", () => panel.remove(), { once: true });
  setTimeout(() => panel.remove(), 400); // no animation (reduced motion / paused effects): still goes
}

function button(label: string, onClick: () => void, primary = false): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = primary ? "ask-btn primary" : "ask-btn";
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

/** Shows the question above the command bar; `send` carries the answer to the backend as an interactive_response. */
export function showAskPanel(card: AskCard, send: (msg: Record<string, unknown>) => void): void {
  const host = document.getElementById("command-bar");
  if (!host) return;
  if (current) close(current);

  const panel = document.createElement("div");
  panel.className = "ask-panel";
  panel.dataset.cardId = card.id;
  const answer = ({ action, value }: Answer) => {
    if (current !== panel) return; // already answered or replaced
    send({ type: "interactive_response", cardId: card.id, action, ...(value !== undefined ? { value } : {}) });
    close(panel);
  };

  if (card.title) {
    const t = document.createElement("div");
    t.className = "ask-title";
    t.textContent = card.title;
    panel.appendChild(t);
  }
  if (card.description) {
    const d = document.createElement("p");
    d.className = "ask-desc";
    d.textContent = card.description;
    panel.appendChild(d);
  }

  const actions = document.createElement("div");
  actions.className = "ask-actions";

  if (card.type === "approve") {
    actions.append(
      button(card.rejectLabel || "Từ chối", () => answer({ action: "reject" })),
      button(card.approveLabel || "Đồng ý", () => answer({ action: "approve" }), true),
    );
  } else if (card.type === "select") {
    const list = document.createElement("div");
    list.className = "ask-options";
    const picked = new Set((card.options || []).filter((o) => o.selected).map((o) => o.value));
    for (const opt of card.options || []) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "ask-option";
      row.classList.toggle("selected", picked.has(opt.value));
      row.textContent = opt.label;
      row.addEventListener("click", () => {
        // one choice: picking it is the answer; several: toggle, then "Xác nhận"
        if (!card.multiple) return answer({ action: "submit", value: [opt.value] });
        if (picked.has(opt.value)) picked.delete(opt.value);
        else picked.add(opt.value);
        row.classList.toggle("selected", picked.has(opt.value));
      });
      list.appendChild(row);
    }
    panel.appendChild(list);
    if (card.multiple) actions.append(button(card.submitLabel || "Xác nhận", () => answer({ action: "submit", value: [...picked] }), true));
  } else {
    const input = document.createElement("textarea");
    input.className = "ask-input";
    input.rows = 3;
    input.value = typeof card.value === "string" ? card.value : "";
    input.placeholder = card.placeholder || "Nhập nội dung...";
    panel.appendChild(input);
    actions.append(
      button(card.cancelLabel || "Hủy", () => answer({ action: "cancel" })),
      button(card.submitLabel || "Gửi", () => answer({ action: "submit", value: input.value }), true),
    );
  }

  if (actions.childElementCount) panel.appendChild(actions);
  host.appendChild(panel);
  current = panel;
  liftChat(panel, host);
}
