// Status orb: a small dotted orb (thinking-orbs engine, canvas 2D, no React) that
// replaces the bare status text. The orb state follows the JARVIS state through the
// "jarvis:mascot" event that transition() already fires. A state change morphs: the
// dots fly from the old shape into the new one instead of the picture being swapped.
import { gatedLoop } from "./anim-gate";
import { MODE_FRAMES, paintFrame, finalizeFrame, resolvePreset, type OrbState, type OrbFrame, type Dot } from "thinking-orbs/engine";

// JARVIS state → orb state (+ speed). Idle (mic muted / audio finishing) keeps a
// slow "working" orb so the hub never looks dead.
const MAP: Record<string, { orb: OrbState; speed: number }> = {
  idle: { orb: "working", speed: 0.6 },
  listening: { orb: "listening", speed: 1 },
  thinking: { orb: "connecting", speed: 1 },
  working: { orb: "solving", speed: 1 },
  speaking: { orb: "composing", speed: 1 },
  restarting: { orb: "connecting", speed: 1 },
};

const DRAW_SIZE = 32; // hand-tuned scale 32; the canvas is shown a little smaller
const SHOW_PX = 32;
const MORPH_MS = 700;

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const ease = (k: number) => (k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2); // easeInOutCubic

/**
 * Mid-way frame between two orb frames. Dots are ranked by angle round the centre and
 * paired by rank, so each one travels a short way; when the counts differ the spare dots
 * fade in/out in place (alpha) rather than popping. Lines cross-fade.
 */
export function blendFrames(a: OrbFrame, b: OrbFrame, k: number, size: number): OrbFrame {
  const c = size / 2;
  const byAngle = (f: OrbFrame) => [...f.dots].sort((p, q) => Math.atan2(p.y - c, p.x - c) - Math.atan2(q.y - c, q.x - c));
  const A = byAngle(a), B = byAngle(b);
  const n = Math.max(A.length, B.length);
  const seenA = new Set<number>(), seenB = new Set<number>();
  const pick = (S: Dot[], i: number, seen: Set<number>) => {
    if (!S.length) return null;
    const j = Math.min(S.length - 1, Math.floor((i * S.length) / n));
    const real = !seen.has(j); // a repeated pick is a spare copy: it starts/ends invisible
    seen.add(j);
    return { d: S[j], real };
  };
  const dots: Dot[] = [];
  for (let i = 0; i < n; i++) {
    const pa = pick(A, i, seenA), pb = pick(B, i, seenB);
    const da = (pa ?? pb)!.d, db = (pb ?? pa)!.d;
    dots.push({
      x: lerp(da.x, db.x, k), y: lerp(da.y, db.y, k), z: lerp(da.z, db.z, k),
      r: lerp(da.r, db.r, k), white: lerp(da.white, db.white, k),
      a: lerp(pa?.real ? (da.a ?? 1) : 0, pb?.real ? (db.a ?? 1) : 0, k),
    });
  }
  const lines = [
    ...a.lines.map((l) => ({ ...l, a: (l.a ?? 1) * (1 - k) })),
    ...b.lines.map((l) => ({ ...l, a: (l.a ?? 1) * k })),
  ];
  return finalizeFrame(dots, lines);
}

export function mountStatusOrb(host: HTMLElement): void {
  const canvas = document.createElement("canvas");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = canvas.height = Math.round(DRAW_SIZE * dpr);
  canvas.style.width = canvas.style.height = `${SHOW_PX}px`;
  host.appendChild(canvas);
  const ctx = canvas.getContext("2d")!;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

  let cur = MAP.idle;
  let preset = resolvePreset(cur.orb, DRAW_SIZE);
  let t = 1.5;
  let from: OrbFrame | null = null; // snapshot of what was on screen when the state changed
  let morphStart = 0;
  let shown: OrbFrame | null = null;

  const draw = (now: number) => {
    let frame = MODE_FRAMES[preset.mode](DRAW_SIZE, t * preset.speed * cur.speed, preset.opts);
    if (from) {
      const k = (now - morphStart) / MORPH_MS;
      if (k >= 1) { from = null; delete host.dataset.morph; }
      else frame = blendFrames(from, frame, ease(k), DRAW_SIZE);
    }
    shown = frame;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, DRAW_SIZE, DRAW_SIZE);
    paintFrame(ctx, frame, true);
  };

  const set = (state: string) => {
    const next = MAP[state] ?? MAP.idle;
    // morph from whatever is on screen right now, even mid-morph, so quick changes stay continuous
    if (!still && shown && next.orb !== cur.orb) {
      from = shown;
      morphStart = performance.now();
      host.dataset.morph = "1";
    }
    cur = next;
    preset = resolvePreset(cur.orb, DRAW_SIZE);
    host.dataset.orb = cur.orb;
    host.dataset.speed = String(cur.speed);
    if (still) draw(performance.now());
  };

  window.addEventListener("jarvis:mascot", (e) => set(String((e as CustomEvent).detail)));
  set("idle");
  draw(performance.now());
  if (still) return;

  gatedLoop((now, dt) => { t += dt / 1000; draw(now); });
}
