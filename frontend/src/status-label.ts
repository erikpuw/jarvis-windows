// Status label motion (row = #status-row, label = #status-text):
//  - a text change slides + fades ("mask-reveal-up" rhythm, no blur): the old text slides out as a ghost, the new one slides in,
//    upward or downward, picked at random on every state change;
//  - after 10 s of quiet in idle (JARVIS has answered and nothing is going on, mic off) the text slides back
//    to the left and collapses (the orb stays, dimmed); any state change, key press or click slides it out again
//    from the left ("line-by-line-slide", CSS transitions on #status-text). The active
//    states (listening, thinking, working, speaking) never roll in: the user always sees what JARVIS is doing.
// The label's text/class are written by main.ts (updateStatus/transition); we only observe them.
const QUIET_MS = 10_000;
// rhythm of "mask-reveal-up" from the animate-text catalog (no blur), travel trimmed to the 24 px row: the old text
// leaves very fast (ease-in) to make room, the new one starts just before it is gone and settles slowly (ease-out);
// the label's overflow:hidden is the mask
const IN_PX = 12;
const OUT_PX = 9;
const OUT_MS = 200;
const IN_MS = 547;
const IN_DELAY_MS = 90;
const EASE_OUT = "cubic-bezier(0.22, 1, 0.36, 1)";
const EASE_IN = "cubic-bezier(0.64, 0, 0.78, 0)";

const QUIET = new Set(["idle"]);

export function mountStatusLabel(row: HTMLElement, label: HTMLElement): void {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- slide on text change ----
  let dir = 1; // +1 = new text comes from below, -1 = from above; random on every state change
  let lastText = label.textContent ?? "";
  let prevClass = label.className;

  const slide = (oldText: string, oldClass: string) => {
    row.querySelectorAll(".status-ghost").forEach((g) => g.remove());
    const ghost = label.cloneNode(false) as HTMLElement;
    ghost.removeAttribute("id");
    ghost.className = `status-ghost ${oldClass}`;
    ghost.textContent = oldText;
    ghost.setAttribute("aria-hidden", "true");
    ghost.style.left = `${label.offsetLeft}px`;
    ghost.style.top = `${label.offsetTop}px`;
    row.appendChild(ghost);
    // the ghost holds its last frame until removed; the label must NOT (fill would pin opacity: 1
    // and override the rolled-in state)
    ghost.animate([{ opacity: 1, transform: "translateY(0)" }, { opacity: 0, transform: `translateY(${-dir * OUT_PX}px)` }],
      { duration: OUT_MS, easing: EASE_IN, fill: "forwards" }).onfinish = () => ghost.remove();
    // "backwards" keeps the label hidden during the delay; no forward fill, it must not pin opacity afterwards
    label.animate([{ opacity: 0, transform: `translateY(${dir * IN_PX}px)` }, { opacity: 1, transform: "translateY(0)" }],
      { duration: IN_MS, delay: IN_DELAY_MS, easing: EASE_OUT, fill: "backwards" });
  };

  new MutationObserver((records) => {
    let oldClass = prevClass;
    for (const r of records) if (r.type === "attributes" && r.attributeName === "class") { oldClass = r.oldValue ?? oldClass; break; }
    prevClass = label.className;
    const text = label.textContent ?? "";
    if (text === lastText) return;
    const oldText = lastText;
    lastText = text;
    if (!reduced && oldText && !row.classList.contains("quiet")) slide(oldText, oldClass);
  }).observe(label, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["class"], attributeOldValue: true });

  // ---- roll in after quiet ----
  let state = "idle";
  let timer = 0;
  const arm = () => {
    clearTimeout(timer);
    if (QUIET.has(state)) timer = window.setTimeout(() => row.classList.add("quiet"), QUIET_MS);
  };
  const wake = () => { row.classList.remove("quiet"); arm(); };

  window.addEventListener("jarvis:mascot", (e) => {
    const next = String((e as CustomEvent).detail);
    const wasQuietState = QUIET.has(state);
    dir = Math.random() < 0.5 ? 1 : -1;
    state = next;
    if (!QUIET.has(next)) { clearTimeout(timer); row.classList.remove("quiet"); }
    else if (!wasQuietState) wake(); // calmed down: count 10 s from now
  });
  for (const type of ["keydown", "pointerdown"]) {
    window.addEventListener(type, () => { if (row.classList.contains("quiet")) wake(); else arm(); }, { passive: true });
  }
  arm();
}

// ---- row changes place when the command bar hides/shows (#command-container loses/gains .visible) ----
// justify-content can't be animated, so the row would jump from the left to the middle. Instead it fades out and shrinks to 85 %
// where it was, then fades in and grows back to 100 % where it is now (the same both ways, 250 ms in total). The layout is already
// the new one when the observer runs, so the old spot is faked with a translateX on the whole row; orb and label keep their own motion.
const MOVE_MS = 250;
const MOVE_SCALE = 0.85;

export function mountStatusRowFade(row: HTMLElement, label: HTMLElement): void {
  const box = row.parentElement;
  const orb = row.querySelector<HTMLElement>("#status-orb");
  if (!box || !orb || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let visible = box.classList.contains("visible");
  let anim: Animation | null = null;

  new MutationObserver(() => {
    const now = box.classList.contains("visible");
    if (now === visible) return;
    visible = now;
    const rr = row.getBoundingClientRect(), o = orb.getBoundingClientRect(), l = label.getBoundingClientRect();
    const left = o.left, right = Math.max(o.right, l.right), centre = (left + right) / 2;
    const leftCentre = rr.left + parseFloat(getComputedStyle(row).paddingLeft) + (right - left) / 2, midCentre = rr.left + rr.width / 2;
    const dx = visible ? midCentre - centre : leftCentre - centre; // from where the content was to where it is now
    anim?.cancel();
    row.style.transformOrigin = `${centre - rr.left}px 50%`;
    anim = row.animate([
      { offset: 0, transform: `translateX(${dx}px) scale(1)`, opacity: 1, easing: "ease-in" },
      { offset: 0.5, transform: `translateX(${dx}px) scale(${MOVE_SCALE})`, opacity: 0 },
      { offset: 0.5, transform: `scale(${MOVE_SCALE})`, opacity: 0, easing: "ease-out" },
      { offset: 1, transform: "scale(1)", opacity: 1 },
    ], { duration: MOVE_MS });
  }).observe(box, { attributes: true, attributeFilter: ["class"] });
}
