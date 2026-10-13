// The notification island ("Dynamic Island"): one capsule at the top centre of the screen that carries the flow tracker
// (the steps JARVIS goes through for a turn) and system errors. The agent cards (flow agents) stay in the chat.
//
// Built the way Sileo (sileo.aaryan.design) builds its toast, read from the `sileo` package: a fixed-size SVG with two <rect>s,
// the pill and the card body, under a light goo filter (blur, threshold, composite) that melts them together; JS moves the
// rects' attributes on each frame along Sileo's spring (island-shape.ts). Opening pulls the pill's lower half down and the
// full-width body grows below it while it fades in, so the body seems to stretch out of the pill. See-through black, the text on
// top; the same on a computer and a phone.
//
//   hidden   nothing to report
//   pill     the capsule alone: status icon, current step (or the error), step count
//   open     the card has dropped below the capsule and lists the steps (or the full error); it sits above the clock, the chat,
//            the media player and the webcam, below Settings and the full map (those cover it)
//   leaving  the capsule narrows to nothing towards its centre while everything in it (icon, text, count) is wiped out and
//            fades with it (no sliver left behind, no sliding away)
//
// Nothing ever pops open by itself: a notification only shows the capsule, a tap opens the card. An open card folds back into
// the capsule after IDLE_OPEN_MS without any touch on it (and, with a mouse, only once the pointer has left it). When the work is
// done, or an error has been shown for a while, and nobody is looking, the capsule leaves.
import { setStatusIcon } from "./icons";
import { easeOut, pop, spring, tweener } from "./island-shape";

export interface FlowStep { id: string | number; label: string; status: string }
export interface NotifyIsland {
  /** A new turn: forget the previous steps. */
  resetFlow(): void;
  /** One step of the flow tracker (new, or an update of an earlier one). */
  flowStep(step: FlowStep): void;
  /** A system error. */
  error(message: string): void;
}

const IDLE_OPEN_MS = 5000; // an opened card folds after this long without a touch (a mouse resting on it keeps it open)
const DONE_MS = 900; // no step active for this long = the flow is finished (the last steps arrive in a burst)
const LINGER_MS = 2500; // a finished flow stays in the capsule this long before it leaves
const ERROR_MS = 8000; // an error stays in the capsule this long
const LEAVE_MS = 300; // leaving: the pill narrows to nothing in 0.3 s (its content follows faster, 0.25 s) while it fades out
const PANEL_MAX_W = 320;
const PANEL_MIN_W = 200;
const CONTROLS_GAP = 56; // clear of the control button on the right (and as much on the left), so the card never covers it
const NARROW_W = 0; // the capsule's width when it has narrowed away (entering starts from it too)
const PILL_H = 34;
const PILL_DROP = 24; // open: the pill reaches this far down into the body (Sileo: 3 x its blur), the goo makes the neck there

/** "Định tuyến → general" → ["Định tuyến", "general"]; drops a trailing "..." / "…". */
function splitStepLabel(label: string): [string, string] {
  const clean = (label || "").replace(/(\.{3}|…)\s*$/, "").trim();
  const i = clean.indexOf("→");
  return i < 0 ? [clean, ""] : [clean.slice(0, i).trim(), clean.slice(i + 1).trim()];
}

type State = "hidden" | "pill" | "open" | "leaving";

export function mountNotifyIsland(root: HTMLElement): NotifyIsland {
  root.classList.add("island");
  root.dataset.state = "hidden";
  root.innerHTML = `
    <div class="island-canvas" aria-hidden="true"><svg class="island-svg" focusable="false">
      <defs><filter id="island-goo" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB">
        <feGaussianBlur in="SourceGraphic" stdDeviation="8" result="blur" />
        <feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -10" result="goo" />
        <feComposite in="SourceGraphic" in2="goo" operator="atop" />
      </filter></defs>
      <rect class="island-pill-rect" rx="17" ry="17" height="${PILL_H}" />
      <rect class="island-body-rect" rx="16" ry="16" y="${PILL_H}" height="0" opacity="0" />
    </svg></div>
    <button class="island-pill" type="button" aria-expanded="false" aria-controls="island-panel">
      <span class="island-pill-content"><span class="island-icon"></span><span class="island-label"></span><span class="island-count"></span></span>
    </button>
    <div class="island-panel" id="island-panel"><div class="island-panel-inner">
      <div class="island-steps"></div>
      <div class="island-error"></div>
    </div></div>`;
  const pill = root.querySelector<HTMLButtonElement>(".island-pill")!;
  const pillContent = root.querySelector<HTMLElement>(".island-pill-content")!;
  const iconHost = root.querySelector<HTMLElement>(".island-icon")!;
  const labelEl = root.querySelector<HTMLElement>(".island-label")!;
  const countEl = root.querySelector<HTMLElement>(".island-count")!;
  const stepsEl = root.querySelector<HTMLElement>(".island-steps")!;
  const errorEl = root.querySelector<HTMLElement>(".island-error")!;
  const panel = root.querySelector<HTMLElement>(".island-panel")!;
  const svg = root.querySelector<SVGSVGElement>(".island-svg")!;
  const pillRect = root.querySelector<SVGRectElement>(".island-pill-rect")!;
  const bodyRect = root.querySelector<SVGRectElement>(".island-body-rect")!;
  let svgW = 0;
  const shape = tweener({ pillW: 0, pillH: PILL_H, bodyH: 0, bodyO: 0, clipW: 0 }, (cur) => {
    pillRect.setAttribute("x", String((svgW - cur.pillW) / 2));
    pillRect.setAttribute("width", String(Math.max(0, cur.pillW)));
    pillRect.setAttribute("height", String(cur.pillH));
    bodyRect.setAttribute("height", String(Math.max(0, cur.bodyH)));
    bodyRect.setAttribute("opacity", String(Math.min(1, Math.max(0, cur.bodyO))));
    pill.style.width = `${cur.clipW}px`; // the pill button clips its content to the pill, on the same frame
  });

  let steps: FlowStep[] = [];
  let errorMsg = "";
  let state: State = "hidden";
  let covered = false; // Settings or the full map is on top
  let flowDone = false;
  let naturalW = NARROW_W; // the capsule's width for its current text
  let doneTimer = 0, goAwayTimer = 0, errorTimer = 0, idleTimer = 0, leaveTimer = 0;

  const canHover = matchMedia("(hover: hover)").matches; // touch screens keep :hover stuck after a tap, so it only counts for a mouse
  const hovering = () => canHover && root.matches(":hover");
  const viewing = () => state === "open" || hovering();
  const clear = (...ids: number[]) => ids.forEach((t) => clearTimeout(t));

  // ---- drawing ----
  function render(): void {
    if (errorMsg) {
      root.dataset.kind = "error";
      setStatusIcon(iconHost, "failed", "flow", 14);
      labelEl.textContent = errorMsg;
      countEl.textContent = "";
    } else if (steps.length) {
      root.dataset.kind = "flow";
      const failed = steps.some((s) => s.status === "failed");
      const isDone = flowDone && !steps.some((s) => s.status === "active");
      setStatusIcon(iconHost, failed ? "failed" : isDone ? "completed" : "active", "flow", 14);
      labelEl.textContent = failed ? "Lỗi xử lý" : isDone ? "Hoàn thành" : "Đang xử lý";
      countEl.textContent = "";
    }
    errorEl.textContent = errorMsg;
    // rows keyed by step id so a status change patches in place (the dot colour transitions)
    for (const step of steps) {
      let row = stepsEl.querySelector<HTMLElement>(`:scope > [data-step-id="${CSS.escape(String(step.id))}"]`);
      if (!row) {
        row = document.createElement("div");
        row.className = "island-step";
        row.dataset.stepId = String(step.id);
        row.innerHTML = `
          <div class="island-step-indicator" aria-hidden="true">
            <span class="timeline-dot"><span class="timeline-dot-inner"></span></span>
            <span class="timeline-connector"></span>
          </div>
          <div class="island-step-content">
            <span class="island-step-text"></span><span class="island-step-detail"></span>
          </div>`;
        stepsEl.appendChild(row);
      }
      const [main, detail] = splitStepLabel(step.label);
      row.dataset.status = step.status;
      const dotInner = row.querySelector<HTMLElement>(".timeline-dot-inner");
      if (dotInner) {
        if (step.status === "completed") {
          dotInner.innerHTML = `<svg viewBox="0 0 12 12" width="7" height="7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.3 2.3L9.5 3.5"/></svg>`;
        } else if (step.status === "failed") {
          dotInner.innerHTML = `<svg viewBox="0 0 12 12" width="7" height="7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l6 6M9 3l-6 6"/></svg>`;
        } else {
          dotInner.innerHTML = "";
        }
      }
      row.querySelector(".island-step-text")!.textContent = main;
      row.querySelector(".island-step-detail")!.textContent = detail;
    }
    for (const row of [...stepsEl.children] as HTMLElement[]) if (!steps.some((s) => String(s.id) === row.dataset.stepId)) row.remove();
    root.classList.toggle("has-steps", steps.length > 0);
    layout();
  }

  // Sizes are explicit pixels so the pill and the card can grow and shrink with a transition (auto cannot be animated):
  // the pill is as wide as its text (a sliver while it enters or leaves). The pill button gets the same width and transition as
  // the pill rect and clips its (centred, max-content) content, so a longer or shorter text is revealed or wiped together with
  // the pill instead of spilling out before it. Opening runs on Sileo's spring; folding and leaving are quick and plain. The SVG
  // keeps one size while the card moves (as in Sileo) so the filter does not resize on every frame.
  function layout(): void {
    if (state === "pill" || state === "open") naturalW = Math.max(NARROW_W, pillContent.offsetWidth); // offsetWidth: the content's own size, not the 0.9 scale it has while the card is open
    const narrow = state === "leaving" || root.dataset.enter === "1";
    const pillW = narrow ? NARROW_W : naturalW;
    const openW = Math.max(PANEL_MIN_W, Math.min(window.innerWidth - 2 * CONTROLS_GAP, PANEL_MAX_W));
    const open = state === "open";
    root.style.setProperty("--island-open-w", `${openW}px`);
    const contentH = panel.offsetHeight; // the panel is out of the flow: its height holds the last row's bottom margin too
    if (svgW !== openW) { svgW = openW; svg.setAttribute("width", String(openW)); bodyRect.setAttribute("width", String(openW)); }
    svg.setAttribute("height", String(PILL_H + contentH + PILL_DROP));
    const [ms, ease] = open ? [600, spring] : [220, easeOut];
    shape.to("bodyH", open ? contentH : 0, ms, ease);
    shape.to("bodyO", open ? 1 : 0, ms, ease);
    shape.to("pillH", open ? PILL_H + PILL_DROP : PILL_H, ms, ease);
    shape.to("pillW", pillW, 300, state === "leaving" ? easeOut : pop);
    shape.to("clipW", pillW, state === "leaving" ? 250 : 300, state === "leaving" ? easeOut : pop); // leaving: the content goes a little sooner
  }

  function setState(next: State): void {
    state = next;
    root.dataset.state = next;
    pill.setAttribute("aria-expanded", String(next === "open"));
    layout();
  }

  // ---- showing and leaving ----
  function show(): void {
    clear(leaveTimer, goAwayTimer);
    if (state === "hidden") {
      root.dataset.enter = "1"; // starts as a narrow sliver with its content wiped out...
      setState("pill");
      requestAnimationFrame(() => requestAnimationFrame(() => { delete root.dataset.enter; layout(); })); // ...and grows to its text
    } else if (state === "leaving") {
      setState("pill");
    }
  }

  function leave(): void {
    if (covered || state === "hidden" || state === "leaving") return;
    clear(idleTimer, goAwayTimer);
    setState("leaving");
    leaveTimer = window.setTimeout(() => setState("hidden"), LEAVE_MS);
  }

  /** The capsule leaves when there is nothing more to say: a finished flow, no error showing. A running flow keeps its capsule. */
  function maybeGoAway(delay = LINGER_MS): void {
    clear(goAwayTimer);
    if (covered || errorMsg || !flowDone || state !== "pill") return;
    goAwayTimer = window.setTimeout(() => {
      if (state === "open" || hovering()) { maybeGoAway(600); return; } // someone is looking
      leave();
    }, delay);
  }

  // ---- the card: opened by a tap, folded after 5 s without a touch ----
  function openCard(): void {
    clear(leaveTimer, goAwayTimer);
    setState("open");
    armIdle();
  }

  function foldCard(): void {
    clear(idleTimer);
    if (state === "open") setState("pill");
    maybeGoAway();
  }

  function armIdle(): void {
    clear(idleTimer);
    if (state !== "open") return;
    idleTimer = window.setTimeout(() => { if (!hovering()) foldCard(); }, IDLE_OPEN_MS); // a resting mouse waits for mouseleave
  }

  // ---- the three kinds of event ----
  function resetFlow(): void {
    clear(doneTimer, goAwayTimer);
    steps = [];
    flowDone = false;
    stepsEl.replaceChildren();
    if (!errorMsg && state === "pill") leave();
  }

  function flowStep(step: FlowStep): void {
    const i = steps.findIndex((s) => String(s.id) === String(step.id));
    if (i >= 0) steps[i] = step; else steps.push(step);
    flowDone = false;
    clear(doneTimer, goAwayTimer);
    render();
    if (!errorMsg) show();
    if (!steps.some((s) => s.status === "active")) {
      doneTimer = window.setTimeout(() => { flowDone = true; render(); maybeGoAway(); }, DONE_MS);
    }
  }

  function error(message: string): void {
    errorMsg = message;
    clear(errorTimer, goAwayTimer);
    render();
    show();
    const settle = () => {
      if (viewing()) { errorTimer = window.setTimeout(settle, 800); return; }
      errorMsg = "";
      render();
      if (steps.length) maybeGoAway(400); else leave();
    };
    errorTimer = window.setTimeout(settle, ERROR_MS);
  }

  // ---- the user ----
  pill.addEventListener("click", () => { if (state === "open") foldCard(); else openCard(); });
  for (const ev of ["pointermove", "pointerdown", "wheel", "touchstart", "touchmove", "scroll", "focusin"]) root.addEventListener(ev, armIdle, { capture: true, passive: true });
  root.addEventListener("mouseleave", armIdle);
  document.addEventListener("pointerdown", (e) => { if (state === "open" && !root.contains(e.target as Node)) foldCard(); }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state === "open") foldCard(); });

  // ---- covered by Settings ----
  let settingsFlag = false;
  let savedStateBeforeCover: State | null = null;
  const syncCovered = (settingsOpen?: boolean) => {
    if (settingsOpen !== undefined) settingsFlag = settingsOpen;
    const wasCovered = covered;
    covered = settingsFlag;
    root.dataset.covered = covered ? "1" : "0";

    if (covered && !wasCovered) {
      // Khi Settings mở: tạm dừng đếm thời gian tự ẩn và lưu trạng thái
      clear(goAwayTimer, leaveTimer, idleTimer);
      if (state !== "hidden") {
        savedStateBeforeCover = state;
      }
    } else if (!covered && wasCovered) {
      // Khi đóng Settings: nếu trước đó đảo động đang chạy, khôi phục lại
      if (savedStateBeforeCover && savedStateBeforeCover !== "hidden") {
        setState(savedStateBeforeCover === "open" ? "pill" : savedStateBeforeCover);
        savedStateBeforeCover = null;
        layout();
        maybeGoAway();
      }
    }
  };
  window.addEventListener("jarvis:overlay", (e) => syncCovered((e as CustomEvent<{ open: boolean }>).detail.open));
  window.addEventListener("resize", layout);
  // Steps added while the card is open make it taller. Watch the content (not the animated panel) and only act when a HEIGHT
  // changes: the content's width changes on every frame of the card opening, which must not trigger layout() each time.
  const heights = new Map<Element, number>();
  const contentWatch = new ResizeObserver((entries) => {
    let changed = false;
    for (const e of entries) if (heights.get(e.target) !== e.contentRect.height) { heights.set(e.target, e.contentRect.height); changed = true; }
    if (changed) layout();
  });
  contentWatch.observe(stepsEl);
  contentWatch.observe(errorEl);
  void document.fonts.ready.then(layout);
  syncCovered(false);
  render();
  return { resetFlow, flowStep, error };
}
