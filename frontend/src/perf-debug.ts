// Performance panel for debugging heat/CPU, loaded only with `?debug=1` (dynamic import, so it costs nothing otherwise).
// Once a second it prints what keeps the page busy: frames per second, requestAnimationFrame calls per caller (every
// loop that is still running shows up with its own rate), long tasks, which backend the orb runs on (webgpu / webgl2 / off), DOM size, running CSS animations, the audio
// context state, whether the animation gate has paused the decorative loops, and the JS heap. Also on `window.__perf`.
// Safari has no long-task API and no heap figure, so it also measures main-thread lag (how late a 100 ms timer fires: the
// busier the CPU, the later). Every sample is posted to the server (POST /api/perf-log, logs/perf.jsonl, a fresh file per
// page load), so a 5-minute session on the iPhone can be read back afterwards.
// Read it together with Edge DevTools (see README, "Debug hiệu năng").
import { animPaused } from "./anim-gate";
import { micStats } from "./voice";

export interface PerfSample {
  fps: number;
  rafPerSec: number;
  rafBy: Record<string, number>;
  longTasks: number;
  longTaskMaxMs: number;
  dom: number;
  bubbles: number;
  canvases: number;
  orb: string;
  orbFirstMs: number | null; // ms after page start when the orb drew its first frame (null: not yet)
  animations: number;
  animNames: string[];
  audio: string;
  gatePaused: boolean;
  heapMB: number | null;
  lagMaxMs: number;
  lagAvgMs: number;
  t: number;
  at: number; // wall clock (ms), to line up with the server's jarvis.log
  events: object[]; // status/stream packets and status-label changes since the previous sample
  status: string;
  hidden: boolean;
  chatOverflow: boolean;
  tables: number;
}

const LAG_STEP_MS = 100;
const POST_EVERY = 5; // samples per POST

const callerOf = (stack: string | undefined): string => {
  // stack[0] = "Error", [1] = the wrapper itself, [2] = whoever called requestAnimationFrame: "at fn (http://host/src/orb.ts?t=1:154:5)"
  const line = (stack ?? "").split(String.fromCharCode(10))[2] ?? "";
  const tail = line.slice(line.lastIndexOf("/") + 1).replace(")", "");
  const parts = tail.split(":");
  const q = parts[0].indexOf("?");
  const file = q >= 0 ? parts[0].slice(0, q) : parts[0];
  return file && parts.length >= 3 ? `${file}:${parts[parts.length - 2]}` : "other";
};

/** Speech recognition at a glance: on/off, starts, results (final), errors by code, and the last thing it heard. */
function micLine(): string {
  const m = micStats, err = Object.entries(m.errors).map(([k, v]) => `${k}×${v}`).join(" ") || "-";
  const last = m.results ? ` last ${((performance.now() - m.lastAt) / 1000).toFixed(1)}s ago conf ${m.lastConf.toFixed(2)} "${m.lastText.slice(0, 24)}"` : "";
  return `mic SR ${m.on ? "on" : "off"} starts ${m.starts} ends ${m.ends} results ${m.results} (final ${m.finals}) err ${err}${last}`;
}

export function mountPerfDebug(audioCtx: AudioContext): void {
  if (document.getElementById("perf-debug")) return;
  const el = document.createElement("pre");
  el.id = "perf-debug";
  el.style.cssText = "position:fixed;top:4px;left:4px;z-index:2147483000;margin:0;padding:6px 8px;max-width:92vw;pointer-events:none;" +
    "font:11px/1.35 ui-monospace,Consolas,monospace;color:#9ef0ff;background:rgba(0,0,0,.78);border:1px solid rgba(158,240,255,.35);" +
    "border-radius:6px;white-space:pre-wrap;word-break:break-all";
  document.body.appendChild(el);

  const nativeRaf = window.requestAnimationFrame.bind(window);
  let rafCalls = 0;
  let rafBy: Record<string, number> = {};
  window.requestAnimationFrame = (cb: FrameRequestCallback): number => {
    rafCalls++;
    const k = callerOf(new Error().stack);
    rafBy[k] = (rafBy[k] ?? 0) + 1;
    return nativeRaf(cb);
  };

  let frames = 0;
  const countFrame = () => { frames++; nativeRaf(countFrame); };
  nativeRaf(countFrame);

  let longTasks = 0;
  let longMax = 0;
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) { longTasks++; longMax = Math.max(longMax, e.duration); }
    }).observe({ entryTypes: ["longtask"] });
  } catch { /* not supported (Safari) */ }

  // main-thread lag: a 100 ms timer that fires late means the thread was busy (works on Safari, unlike long tasks)
  let lagMax = 0, lagSum = 0, lagN = 0, lagPrev = performance.now();
  window.setInterval(() => {
    const now = performance.now(), late = Math.max(0, now - lagPrev - LAG_STEP_MS);
    lagPrev = now; lagMax = Math.max(lagMax, late); lagSum += late; lagN++;
  }, LAG_STEP_MS);

  const started = performance.now();
  // packets as main.ts receives them (audio data skipped) and every change of the status label, with the wall clock
  const events: object[] = [];
  const w = window as unknown as { __wsEvents?: object[] };
  w.__wsEvents = { push: (e: { type?: string }) => { if (!/^(pcm_chunk|audio_chunk|audio)$/.test(e.type ?? "")) events.push(e); return events.length; } } as unknown as object[];
  const statusText = document.getElementById("status-text");
  if (statusText) new MutationObserver(() => events.push({ at: Date.now(), label: statusText.textContent })).observe(statusText, { childList: true, characterData: true, subtree: true });
  let batch: PerfSample[] = [];
  let first = true;
  const post = () => {
    if (!batch.length) return;
    const body = JSON.stringify({ samples: batch, reset: first });
    batch = []; first = false;
    fetch("/api/perf-log", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => { /* server down: keep showing the panel */ });
  };
  document.addEventListener("visibilitychange", () => { if (document.hidden) post(); });

  const tick = () => {
    const anims = document.getAnimations().filter((a) => a.playState === "running");
    const names = new Map<string, number>();
    for (const a of anims) {
      const n = (a as CSSAnimation).animationName || (a as CSSTransition).transitionProperty || "?";
      names.set(n, (names.get(n) ?? 0) + 1);
    }
    const heap = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    const s: PerfSample = {
      fps: frames,
      rafPerSec: rafCalls,
      rafBy,
      longTasks,
      longTaskMaxMs: Math.round(longMax),
      dom: document.getElementsByTagName("*").length,
      bubbles: document.querySelectorAll("#chat-history .chat-bubble").length,
      canvases: document.getElementsByTagName("canvas").length,
      orb: (document.getElementById("orb-canvas") as HTMLCanvasElement | null)?.dataset.backend ?? "loading",
      orbFirstMs: Number((document.getElementById("orb-canvas") as HTMLCanvasElement | null)?.dataset.first) || null,
      animations: anims.length,
      animNames: [...names].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([n, c]) => (c > 1 ? `${n}×${c}` : n)),
      audio: audioCtx.state,
      gatePaused: animPaused(),
      heapMB: heap ? Math.round(heap.usedJSHeapSize / 1e6) : null,
      lagMaxMs: Math.round(lagMax),
      lagAvgMs: lagN ? Math.round(lagSum / lagN) : 0,
      t: Math.round((performance.now() - started) / 1000),
      at: Date.now(),
      events: events.splice(0),
      status: document.getElementById("status-text")?.textContent?.trim() ?? "",
      hidden: document.hidden,
      chatOverflow: !!document.querySelector("#chat-history.overflowing"),
      tables: document.querySelectorAll("#chat-history .sd-table").length,
    };
    (window as unknown as { __perf: PerfSample }).__perf = s;
    const by = Object.entries(s.rafBy).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => `${k} ${v}`).join("\n    ");
    el.textContent =
      `perf debug (?debug)\n` +
      `fps ${s.fps}  rAF/s ${s.rafPerSec}  lag ${s.lagAvgMs}/${s.lagMaxMs}ms  longtask ${s.longTasks} (max ${s.longTaskMaxMs}ms)\n` +
      `rAF/s by caller:\n    ${by || "-"}\n` +
      `DOM ${s.dom}  bubbles ${s.bubbles}  canvases ${s.canvases}  orb ${s.orb}\n` +
      `CSS animations running ${s.animations}: ${s.animNames.join(", ") || "-"}\n` +
      `${micLine()}\n` +
      `AudioContext ${s.audio}  audioSession ${(navigator as unknown as { audioSession?: { type: string } }).audioSession?.type ?? "n/a"}  gate ${s.gatePaused ? "PAUSED" : "active"}  heap ${s.heapMB ?? "?"}MB`;
    frames = 0; rafCalls = 0; rafBy = {}; longTasks = 0; longMax = 0; lagMax = 0; lagSum = 0; lagN = 0;
    batch.push(s);
    if (batch.length >= POST_EVERY) post();
  };
  window.setInterval(tick, 1000);
  tick();
}
