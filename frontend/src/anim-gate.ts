// One switch for every decorative animation loop (status orb, bot on the command bar, send-button shader and halo). main.ts
// flips it whenever something covers the screen (settings, media), the same moments the Three.js orb is paused, so a covered page costs no frames — on a phone
// the hidden loops were still drawing 60 times a second and heating it. A hidden tab stops them too, and so does a page that is
// still loading: nothing starts before window "load" and the fonts (the effects used to jump in while the page was arriving).
let paused = false;
let loading = document.readyState !== "complete";
const listeners = new Set<(paused: boolean) => void>();

export const animPaused = (): boolean => paused || loading || document.hidden;

// a resource that never finishes (or fonts that never settle) must not keep every effect, and the orb, off for good
const LOAD_CAP_MS = 4000;
const FONTS_CAP_MS = 1000;
const wait = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

/** Resolves once the page has loaded (window "load", then fonts), or after a few seconds at most: the moment the decorations may start. */
const pageReady: Promise<void> = new Promise<void>((r) => {
  if (!loading) { r(); return; }
  window.addEventListener("load", () => r(), { once: true });
  window.setTimeout(r, LOAD_CAP_MS);
}).then(() => Promise.race([document.fonts?.ready, wait(FONTS_CAP_MS)])).then(() => {
  loading = false;
  notify();
});

function notify(): void {
  // CSS animations too (clock radar, status shimmer, island spinner…): style.css pauses every one outside Settings
  document.documentElement.classList.toggle("anim-paused", animPaused());
  for (const f of [...listeners]) f(animPaused());
  notifyBar();
}

// The command bar (bot, send-button shader and its halo) also stops while the bar is hidden (#btn-cmd-bar). Hiding only fades it
// to opacity 0, so its loops kept drawing 60 times a second behind nothing. The status row (status orb + label) stays outside.
let barHidden = false;
const barListeners = new Set<(paused: boolean) => void>();

export const barPaused = (): boolean => animPaused() || barHidden;

function notifyBar(): void { for (const f of [...barListeners]) f(barPaused()); }

export function setBarHidden(h: boolean): void {
  if (h === barHidden) return;
  barHidden = h;
  notifyBar();
}

/** Like onAnimGate, for the command bar's own animations: paused when everything is, or when only the bar is hidden. */
export function onBarGate(f: (paused: boolean) => void): void {
  barListeners.add(f);
  f(barPaused());
}

export function setAnimPaused(p: boolean): void {
  if (p === paused) return;
  paused = p;
  notify();
}

/** Calls `f` with the current state now, then again whenever animations are paused or resumed. */
export function onAnimGate(f: (paused: boolean) => void): void {
  listeners.add(f);
  f(animPaused());
}

document.addEventListener("visibilitychange", notify);
document.documentElement.classList.toggle("anim-paused", animPaused()); // still loading: CSS animations wait too

export interface Loop { wake(): void }

/**
 * requestAnimationFrame loop that stops while animations are paused and restarts on resume. `frame`
 * gets the frame time and the (clamped) ms since its previous run; returning false puts the loop to
 * sleep until wake(). `minMs` caps the rate (e.g. 1000/30), which also keeps 120 Hz screens at 60 fps. `inBar`: the loop
 * belongs to the command bar and also stops while the bar is hidden.
 */
export function gatedLoop(frame: (now: number, dt: number) => boolean | void, minMs = 1000 / 60, inBar = false): Loop {
  const isPaused = inBar ? barPaused : animPaused;
  let raf = 0;
  let prev = 0;
  const tick = (now: number): void => {
    raf = 0;
    if (isPaused()) return;
    raf = requestAnimationFrame(tick);
    const dt = prev ? now - prev : 0;
    if (dt && dt < minMs - 2) return; // frame cap: skip, keep `prev`
    prev = now;
    if (frame(now, Math.min(dt, 100)) === false) { cancelAnimationFrame(raf); raf = 0; prev = 0; }
  };
  const wake = (): void => {
    if (raf || isPaused()) return;
    prev = 0;
    raf = requestAnimationFrame(tick);
  };
  (inBar ? onBarGate : onAnimGate)((p) => { if (!p) wake(); });
  wake();
  return { wake };
}
