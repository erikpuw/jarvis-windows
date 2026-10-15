// The send button's halo: the glow of metal-fx v2 (Libraries.dev metal, © 2026 Jakub Antalik, MIT,
// https://libraries.dev/metal.html) ported to plain DOM/canvas — the package itself needs React.
// Same recipe: a short streak along the ring stroked four times (wide → thin) with a box blur each, plus a small hot core
// just outside it; painted on a 2D canvas that overhangs the button, full strength on the ring's outer band, half strength
// outside the ring, nothing inside the button. The wrapper's opacity fades it out on one spot and back in on the next
// (a 3 s beat as asked: 1 s fading in, 1 s lit, 1 s fading out, then a new spot).
// The glow takes its colour from the ring itself: at the spot it lights up, a small patch of the live shader canvas is
// sampled (the metal keeps changing colour) and normalised to full brightness like metal-fx's tint; it follows the metal
// while it stays lit. Not ported: picking the brightest spot of the live shader (we pick a random spot on the ring),
// the slow wander along the ring and the cursor catch-light.
import { onBarGate } from "./anim-gate";

// metal-fx GLOW_DEFAULTS
const HALO = [
  { stroke: 26.4, blur: 8.4, opacity: 0.385 },
  { stroke: 15.6, blur: 4.8, opacity: 0.595 },
  { stroke: 7.2, blur: 2.1, opacity: 0.7 },
  { stroke: 3, blur: 0.9, opacity: 0.7 },
];
const CORE = [
  { stroke: 4 / 3, blur: 2 / 3, opacity: 0.85 },
  { stroke: 2 / 3, blur: 1.35 / 3, opacity: 1 },
];
const HALO_HALF_LEN = 7.8;
const CORE_HALF_LEN = 9.13952 / 3;
const CORE_FADE_R = 13 / 3;
const INSET = 1.5; // streak centre this far inside the ring's outer edge
const CORE_OUTWARD = 1;
const RING_PX = 2; // band drawn at full strength (metal-fx: 2 px for a circle)
const REF_PERIM = 2 * 100 + 0 + 2 * Math.PI * 20; // metal-fx scales arc lengths to a 140×40 r20 pill
const GLOW_OPACITY = 0.3; // just under metal-fx glowOpacity at its dim end (baseOp 0.34): a soft halo that stays inside the bar's frame
const HALO_ALPHA = Math.min(1, GLOW_OPACITY * 2); // haloOpMul
const CORE_ALPHA = 0.3; // metal-fx gives min(1, glowOpacity * 3.51); a full-white core read too hot on the dark bar
const TINT = [155, 231, 255]; // fallback when the ring cannot be sampled (#9be7ff, the shader's tint)
const BEAT_MS = 3000;
// dark, fade in (ease-in-out) to full at 1 s, hold to 2 s, fade out (ease-in-out) to dark at 3 s
const BEAT_KEYS: Keyframe[] = [
  { offset: 0, opacity: 0 }, { offset: 0.01, opacity: 0, easing: "ease-in-out" },
  { offset: 0.333, opacity: 1 }, { offset: 0.667, opacity: 1, easing: "ease-in-out" }, { offset: 1, opacity: 0 },
];
const RECOLOUR_MS = 400; // while lit, re-sample the ring this often and ease towards its colour
const EASE = 0.5;
const MIN_JUMP = Math.PI / 3; // a new spot is at least 60° away from the last one

type Layer = { stroke: number; blur: number; opacity: number };
type Sprite = { canvas: HTMLCanvasElement; ax: number; ay: number; w: number; h: number };

/** Box sizes approximating a gaussian of sigma `s` with `n` passes. */
function boxes(s: number, n: number): number[] {
  let lo = Math.floor(Math.sqrt((12 * s * s) / n + 1));
  if (lo % 2 === 0) lo--;
  const hi = lo + 2, m = Math.round((12 * s * s - n * lo * lo - 4 * n * lo - 3 * n) / (-4 * lo - 4));
  return Array.from({ length: n }, (_, i) => (i < m ? lo : hi));
}

function blurPass(src: Float32Array, dst: Float32Array, w: number, h: number, r: number, horizontal: boolean): void {
  const k = 1 / (r + r + 1), lines = horizontal ? h : w, len = horizontal ? w : h;
  const at = (line: number, i: number) => (horizontal ? line * w + i : i * w + line);
  for (let line = 0; line < lines; line++) {
    let sum = 0;
    for (let i = -r; i <= r; i++) sum += src[at(line, Math.min(len - 1, Math.max(0, i)))];
    for (let i = 0; i < len; i++) {
      dst[at(line, i)] = sum * k;
      sum += src[at(line, Math.min(len - 1, i + r + 1))] - src[at(line, Math.max(0, i - r))];
    }
  }
}

function blur(a: Float32Array, w: number, h: number, sigma: number): Float32Array {
  if (sigma <= 0.05) return a;
  const tmp = new Float32Array(a.length);
  for (const b of boxes(sigma, 3)) {
    const r = (b - 1) / 2;
    blurPass(a, tmp, w, h, r, true);
    blurPass(tmp, a, w, h, r, false);
  }
  return a;
}

/** Alpha of a round-capped horizontal line centred on (cx, cy), `half` long each side. */
function streak(half: number, width: number, cw: number, ch: number, dpr: number, cx: number, cy: number): Float32Array {
  const c = document.createElement("canvas");
  c.width = cw; c.height = ch;
  const g = c.getContext("2d", { willReadFrequently: true })!;
  g.scale(dpr, dpr);
  g.strokeStyle = "#fff"; g.lineCap = "round"; g.lineWidth = width;
  g.beginPath(); g.moveTo(cx - half, cy); g.lineTo(cx + half, cy); g.stroke();
  const px = g.getImageData(0, 0, cw, ch).data, out = new Float32Array(cw * ch);
  for (let i = 0, j = 3; i < out.length; i++, j += 4) out[i] = px[j] / 255;
  return out;
}

/** metal-fx's layered glow sprite, tinted, anchored on the streak's centre. */
function sprite(layers: Layer[], half: number, dpr: number, fadeR: number, tint: number[]): Sprite {
  const pad = Math.max(...layers.map((l) => l.stroke / 2 + 3 * l.blur));
  const r = Math.ceil(pad) + 1, w = 2 * half + 2 * r, h = 2 * r, cw = Math.ceil(w * dpr), ch = Math.ceil(h * dpr);
  const acc = new Float32Array(cw * ch);
  for (const l of layers) {
    const v = blur(streak(half, l.stroke, cw, ch, dpr, r, r), cw, ch, l.blur * dpr);
    for (let i = 0; i < acc.length; i++) acc[i] += v[i] * l.opacity * (1 - acc[i]);
  }
  if (fadeR > 0) { // the hot core falls off with distance from its centre
    const c0 = r * dpr, rr = fadeR * dpr;
    for (let y = 0; y < ch; y++) for (let x = 0; x < cw; x++) {
      const d = Math.hypot(x + 0.5 - c0, y + 0.5 - c0) / rr;
      acc[y * cw + x] *= d <= 0.3 ? 1 : d <= 0.65 ? 1 - ((d - 0.3) / 0.35) * 0.75 : d < 1 ? 0.25 * (1 - (d - 0.65) / 0.35) : 0;
    }
  }
  const canvas = document.createElement("canvas");
  canvas.width = cw; canvas.height = ch;
  const g = canvas.getContext("2d")!, img = g.createImageData(cw, ch);
  for (let i = 0, j = 0; i < acc.length; i++, j += 4) {
    img.data[j] = tint[0]; img.data[j + 1] = tint[1]; img.data[j + 2] = tint[2];
    img.data[j + 3] = Math.round(Math.min(1, acc[i]) * 255);
  }
  g.putImageData(img, 0, 0);
  return { canvas, ax: r, ay: r, w, h };
}

export function mountMetalHalo(wrap: HTMLElement, face: HTMLElement): void {
  const env = document.createElement("span");
  env.className = "metal-glow";
  env.setAttribute("aria-hidden", "true");
  const canvas = document.createElement("canvas");
  env.appendChild(canvas);
  wrap.prepend(env);
  const g = canvas.getContext("2d", { willReadFrequently: true })!;

  // Everything that depends on the button's size or the screen's pixel density lives here and is rebuilt when either
  // changes (a phone turned round, a fold opened, the browser zoomed, the window dragged to another screen: the send
  // button goes 30 ↔ 34 px across the 768 px breakpoint). offsetWidth is the layout size: unlike getBoundingClientRect it
  // ignores transforms, so an entrance animation running at mount time cannot skew it.
  let size = 0, dpr = 0, R = 0, k = 1, c = 0;
  let halo!: Sprite, core!: Sprite;
  let outer: Path2D, band: Path2D, surround: Path2D;
  function layout(): boolean {
    const nextSize = wrap.offsetWidth || 30, nextDpr = Math.min(3, window.devicePixelRatio || 1);
    if (nextSize === size && nextDpr === dpr) return false;
    size = nextSize; dpr = nextDpr; R = size / 2; k = (2 * Math.PI * R) / REF_PERIM;
    halo = sprite(HALO, Math.max(1, HALO_HALF_LEN * k), dpr, 0, [255, 255, 255]);
    core = sprite(CORE, Math.max(0.6, CORE_HALF_LEN * k), dpr, CORE_FADE_R, [255, 255, 255]);
    const margin = Math.ceil(Math.max(halo.ay, core.ay) + CORE_OUTWARD * k + 2), full = size + 2 * margin;
    canvas.width = canvas.height = Math.ceil(full * dpr);
    canvas.style.cssText = `position:absolute;left:${-margin}px;top:${-margin}px;width:${full}px;height:${full}px;pointer-events:none`;
    c = margin + R; // the button's centre in canvas CSS px
    outer = new Path2D(); outer.arc(c, c, R, 0, 2 * Math.PI);
    band = new Path2D(); band.arc(c, c, R, 0, 2 * Math.PI); band.arc(c, c, R - RING_PX, 0, 2 * Math.PI);
    surround = new Path2D(); surround.rect(0, 0, full, full); surround.addPath(outer);
    return true;
  }
  layout();

  // average colour of the live metal at the ring's outer band, at `angle`, normalised so its brightest channel is 255
  const probe = document.createElement("canvas");
  probe.width = probe.height = 3;
  const pg = probe.getContext("2d", { willReadFrequently: true })!;
  function ringColour(angle: number): number[] {
    const src = face.querySelector("canvas");
    if (!src || !src.width || !src.height) return TINT;
    const scale = src.width / size, r = (R - 1) * scale;
    pg.clearRect(0, 0, 3, 3);
    try {
      pg.drawImage(src, src.width / 2 + r * Math.cos(angle) - 1.5 * scale, src.height / 2 + r * Math.sin(angle) - 1.5 * scale, 3 * scale, 3 * scale, 0, 0, 3, 3);
      const d = pg.getImageData(0, 0, 3, 3).data;
      let sr = 0, sg = 0, sb = 0;
      for (let i = 0; i < d.length; i += 4) { sr += d[i]; sg += d[i + 1]; sb += d[i + 2]; }
      const m = Math.max(sr, sg, sb);
      return m < 24 ? TINT : [sr, sg, sb].map((v) => Math.round((255 * v) / m));
    } catch {
      return TINT;
    }
  }

  function paint(angle: number, tint: number[]): void {
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, canvas.width, canvas.height);
    const tangent = angle + Math.PI / 2;
    const at = (radius: number) => [c + radius * Math.cos(angle), c + radius * Math.sin(angle)];
    const [hx, hy] = at(R - INSET), [ex, ey] = at(R - INSET + CORE_OUTWARD * k);
    const draw = (s: Sprite, x: number, y: number, a: number) => {
      // outside the ring at half strength, on the ring's outer band at full, never inside the button
      for (const [clip, mul] of [[surround, 0.5], [band, 1]] as const) {
        g.save(); g.scale(dpr, dpr); g.clip(clip, "evenodd");
        g.translate(x, y); g.rotate(tangent); g.globalAlpha = a * mul;
        g.drawImage(s.canvas, -s.ax, -s.ay, s.w, s.h); g.restore();
      }
    };
    draw(halo, hx, hy, HALO_ALPHA);
    g.save(); g.globalCompositeOperation = "source-in"; g.fillStyle = `rgb(${tint[0]},${tint[1]},${tint[2]})`; g.fillRect(0, 0, canvas.width, canvas.height); g.restore(); // the halo takes the metal's colour, the core stays white
    draw(core, ex, ey, CORE_ALPHA);
    env.dataset.angle = (((((angle * 180) / Math.PI) % 360) + 360) % 360).toFixed(3); // read by the e2e test
    env.dataset.tint = tint.join(",");
  }

  // one beat = 3 s: fade in 1 s, hold 1 s, fade out 1 s. JS runs each beat and paints the next spot before it starts the next one.
  // It used to be a CSS animation with the move on animationiteration: the fade runs off the main thread but the event waits for it,
  // so on a busy main thread (a phone loading the page) the next fade began at the old spot and the halo jumped while lit.
  let angle = Math.random() * 2 * Math.PI;
  let tint = ringColour(angle);
  paint(angle, tint);
  const refit = () => { if (layout()) paint(angle, tint); };
  window.addEventListener("resize", refit);
  new ResizeObserver(refit).observe(wrap);
  const watchDpr = () => matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`).addEventListener("change", () => { refit(); watchDpr(); }, { once: true });
  watchDpr();
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { env.style.opacity = "1"; return; }
  let beat: Animation | null = null;
  let stopped = false;
  const nextBeat = () => {
    beat = env.animate(BEAT_KEYS, { duration: BEAT_MS });
    if (stopped) beat.pause();
    beat.finished.then(() => {
      angle += MIN_JUMP + Math.random() * (2 * Math.PI - 2 * MIN_JUMP);
      tint = ringColour(angle); // a new spot starts dark, so its colour can jump
      paint(angle, tint);
      env.dispatchEvent(new Event("metal-glow-beat")); // read by the e2e test
      nextBeat();
    }, () => { /* cancelled */ });
  };
  nextBeat();
  // the metal keeps changing colour: while the halo is lit, ease towards the ring's colour at its spot
  setInterval(() => {
    refit(); // also catches a density change that raised neither resize nor a media-query event
    if (env.classList.contains("paused") || document.hidden || Number(getComputedStyle(env).opacity) < 0.05) return;
    const target = ringColour(angle);
    tint = tint.map((v, i) => Math.round(v + (target[i] - v) * EASE));
    paint(angle, tint);
  }, RECOLOUR_MS);
  onBarGate((paused) => {
    stopped = paused;
    env.classList.toggle("paused", paused);
    if (paused) beat?.pause(); else beat?.play();
  });
}
