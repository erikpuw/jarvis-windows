// The new-session welcome layer (spec 2026-10-16): greeting by time slot (sent by the server), weather, a question, and the tools rotating in a
// clipped slot. Shown on every page load; the first user message (addChatMessage "user") dismisses it and the orb opens.
// Transparent on purpose: iOS Safari tints its status/address bar from painted layers at the screen edges.
import "@fontsource/lexend/200.css";
import "@fontsource/lexend/300.css";
import "@fontsource/lexend/400.css";
import { createElement, Cloud, Sun, CloudRain, CloudLightning, Snowflake, CloudFog, Haze, type IconNode } from "lucide";
import { onAnimGate } from "./anim-gate";

export interface WelcomeData {
  greeting?: string; // by time slot, from the server's clock (engine/core/clock.py: one table for this and the chat)
  tools?: string[];
  weather?: { desc: string; temp: number | null; kind: string | null; place: string };
}
export interface Welcome { update(d: WelcomeData): void; dismiss(): void }

const ROTATE_MS = 2200;
const ICONS: Record<string, IconNode> = { clear: Sun, cloudy: Cloud, rain: CloudRain, storm: CloudLightning, snow: Snowflake, fog: CloudFog, haze: Haze };

export function mountWelcome(onDismiss: () => void): Welcome {
  const el = document.createElement("section");
  el.id = "welcome";
  el.innerHTML = `<h1 class="welcome-hello"></h1><p class="welcome-weather"></p>` +
    `<p class="welcome-sub">Tôi có thể giúp gì cho ngài hôm nay?</p><p class="welcome-try">Thử hỏi về <span class="welcome-slot"></span></p>`;
  document.body.appendChild(el);
  const hello = el.querySelector<HTMLHeadingElement>(".welcome-hello")!;
  const slot = el.querySelector<HTMLSpanElement>(".welcome-slot")!;
  const weatherEl = el.querySelector<HTMLParagraphElement>(".welcome-weather")!;

  let active = true, words: string[] = [], i = 0, cur: HTMLSpanElement | null = null, timer = 0, paused = false;

  // The slot follows the current word's real width: measured when it is added, and again whenever it changes size — a word
  // first laid out in the fallback font (Lexend 400 still loading) grew once the font came and was clipped (2026-10-16).
  const fit = () => { if (cur) slot.style.width = Math.ceil(cur.getBoundingClientRect().width) + 1 + "px"; }; // round up: never clip
  const sizes = new ResizeObserver(fit);

  // each change slides up or down at random (user 2026-10-16): in from below and out the top, or the other way round
  function show(word: string) {
    const down = Math.random() < 0.5;
    const next = document.createElement("span");
    next.textContent = word;
    next.className = down ? "above" : "below";
    slot.appendChild(next);
    if (cur) { const old = cur; sizes.unobserve(old); old.className = down ? "out-down" : "out"; setTimeout(() => old.remove(), 500); }
    cur = next;
    fit();
    sizes.observe(next);
    requestAnimationFrame(() => requestAnimationFrame(() => { next.className = ""; }));
  }
  const tick = () => { if (words.length) show(words[++i % words.length]); };
  const run = () => { window.clearInterval(timer); timer = active && !paused && words.length > 1 ? window.setInterval(tick, ROTATE_MS) : 0; };
  onAnimGate((p) => { paused = p; run(); });

  return {
    update(d) {
      if (!active) return; // weather or a reconnect after the first message: the layer is gone for good
      if (d.greeting) hello.textContent = d.greeting;
      if (d.tools?.length && !words.length) {
        words = [...d.tools].sort(() => Math.random() - 0.5);
        // the slot's own face (Lexend 400) is loaded only once something asks for it: ask, then show
        void document.fonts.load("400 17px Lexend").catch(() => undefined).then(() => { if (active) { show(words[0]); run(); } });
      }
      if (d.weather) {
        const w = d.weather;
        const parts = [w.temp != null ? `${Math.round(w.temp)}°C` : "", w.desc.charAt(0).toUpperCase() + w.desc.slice(1), w.place].filter(Boolean);
        weatherEl.replaceChildren(createElement(ICONS[w.kind ?? ""] ?? Cloud, { width: 16, height: 16, "stroke-width": 1.5 }));
        parts.forEach((t, n) => {
          if (n) { const dot = document.createElement("span"); dot.className = "dot"; dot.textContent = "·"; weatherEl.append(dot); }
          const s = document.createElement("span"); s.textContent = t; weatherEl.append(s);
        });
        el.classList.add("has-weather");
      }
    },
    dismiss() {
      if (!active) return;
      active = false;
      run();
      sizes.disconnect();
      el.classList.add("gone");
      window.setTimeout(() => el.remove(), 450);
      onDismiss();
    },
  };
}
