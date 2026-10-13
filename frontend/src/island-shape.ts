// Motion for the notification island, done the way Sileo (sileo.aaryan.design, read from the `sileo` package) does it: the
// shapes are two SVG <rect>s (the pill and the card body) inside one fixed-size SVG under a light goo filter, and their
// attributes are moved by JS on each animation frame along Sileo's spring. Here: the easings and a tiny tweener.
// ---- easings ----
export type Ease = (t: number) => number;

/** CSS cubic-bezier(x1, y1, x2, y2) as a function of time (0..1). */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): Ease {
  const bx = (t: number) => 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3;
  const by = (t: number) => 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let lo = 0, hi = 1, t = x;
    for (let i = 0; i < 24; i++) { t = (lo + hi) / 2; if (bx(t) < x) lo = t; else hi = t; }
    return by(t);
  };
}

// Sileo's spring (bounce 0.25, 600 ms), the same points as its CSS linear() easing: [progress, time %]
const SPRING_POINTS: [number, number][] = [
  [0, 0], [0.002, 0.6], [0.007, 1.2], [0.015, 1.8], [0.026, 2.4], [0.041, 3.1], [0.06, 3.8], [0.108, 5.3], [0.157, 6.6],
  [0.214, 8], [0.467, 13.7], [0.577, 16.3], [0.631, 17.7], [0.682, 19.1], [0.73, 20.5], [0.771, 21.8], [0.808, 23.1],
  [0.844, 24.5], [0.874, 25.8], [0.903, 27.2], [0.928, 28.6], [0.952, 30.1], [0.972, 31.6], [0.988, 33.1], [1.01, 35.7],
  [1.025, 38.5], [1.034, 41.6], [1.038, 45], [1.035, 50.1], [1.012, 64.2], [1.003, 73], [0.999, 83.7], [1, 100],
];
export const spring: Ease = (x) => {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const p = x * 100;
  for (let i = 1; i < SPRING_POINTS.length; i++) {
    const [v1, t1] = SPRING_POINTS[i];
    if (p <= t1) { const [v0, t0] = SPRING_POINTS[i - 1]; return v0 + ((v1 - v0) * (p - t0)) / (t1 - t0); }
  }
  return 1;
};
export const easeOut = cubicBezier(0.4, 0, 0.2, 1);
export const pop = cubicBezier(0.34, 1.2, 0.64, 1);

// ---- the tweener ----
interface Tween { from: number; to: number; start: number; ms: number; ease: Ease }

/** Moves named values to their targets, each with its own easing and duration, and calls `onFrame` with all current values
 *  once per animation frame while any of them is moving. */
export function tweener<K extends string>(initial: Record<K, number>, onFrame: (cur: Record<K, number>) => void) {
  const cur = { ...initial };
  const tweens: Partial<Record<K, Tween>> = {};
  let frame = 0;
  const tick = (now: number) => {
    frame = 0;
    for (const key of Object.keys(tweens) as K[]) {
      const tw = tweens[key]!;
      const x = tw.ms <= 0 ? 1 : Math.min(1, Math.max(0, (now - tw.start) / tw.ms));
      cur[key] = tw.from + (tw.to - tw.from) * tw.ease(x);
      if (x >= 1) { cur[key] = tw.to; delete tweens[key]; }
    }
    onFrame(cur);
    if (Object.keys(tweens).length) frame = requestAnimationFrame(tick);
  };
  return {
    to(key: K, value: number, ms: number, ease: Ease): void {
      const tw = tweens[key];
      if (tw ? tw.to === value : cur[key] === value) return; // already there or on its way
      tweens[key] = { from: cur[key], to: value, start: Number(document.timeline?.currentTime ?? performance.now()), ms, ease };
      if (!frame) frame = requestAnimationFrame(tick);
    },
  };
}
