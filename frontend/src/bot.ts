// The command bar's mascot: one bot (bot-avatars, drawn on a plain canvas with the library's own
// simulation — no React) perched above the send button. It replaces the old fox sprite and the bots that
// used to sit in every chat bubble, so the whole page has exactly one animated character.
// It has its own behaviour for each JARVIS state ("jarvis:mascot" event), see PROFILE:
//   idle      awake, looks around (left/right/up/down) for DOZE_MS, then sleeps
//   listening awake, looks straight out at the speaker for DOZE_MS, then sleeps; nods when speech is heard ("jarvis:heard")
//   typing    (idle/listening while the user types in #command-input) looks down at the box: down-left, down, down-right
//   thinking  awake, watches the chat with three dots rising over its head, calm (no hops), never sleeps
//   working   the library's busy state (hops)
//   speaking  awake, watches the chat with a mouth that opens and shuts (bot-mouth.ts), calm, never sleeps
// idle <-> listening only swap the look script; the DOZE_MS clock keeps running. The clock measures time
// since the last activity (pointer near the bot, a tap/click or a key anywhere): activity wakes a sleeping
// bot back to idle (looks around) and restarts the 30 s, so it does not stay asleep for good.
// The pointer only steers the head; hopping is for a click on the bot (and a nod), never for a pointer nearby.
import { gatedLoop } from "./anim-gate";
import { createTalk, drawMouth, drawThinkDots } from "./bot-mouth";
import {
  BotAvatarSim, drawBotAvatarFrame, botAvatarShapes, botAvatarPresets, autoInk,
  BOT_AVATAR_OVERSCAN, botAvatarJumpDefaults, type BotAvatarState, type BotAvatarFace,
} from "bot-avatars";

const TYPE = "square" as const; // any key of botAvatarShapes: clover flower triangle square blob ghost circle drop star droid mech alien hexagon cat cloud pill pebble puddle
const BOX = 32; // css px of the bot's square
const dpr = Math.min(window.devicePixelRatio || 1, 3); // up to 3 (iPhone): at 2 the edges of a 32px sprite look jagged
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const SHADING = "plastic" as const; // "smooth" is the library's other option

const preset = botAvatarPresets[TYPE];
const cfg = {
  path: new Path2D(botAvatarShapes[TYPE]),
  ...preset,
  ink: autoInk(preset.color),
  shading: SHADING,
  typeKey: TYPE,
  theme: "dark" as const,
  dpr,
};

// Pointer play: the head follows a pointer within a few head widths; a click on the bot hops twice.
const FOLLOW_PX = BOX * 5;
const NOD_EVERY_MS = 1500; // at most one nod per this while speech keeps coming in
const DOZE_MS = 30_000; // awake this long after going idle / listening, then it sleeps

// gaze targets in head-widths from the head's centre (-1..1); x right, y down
interface Look { name: string; x: number; y: number }
const LOOK_AROUND: Look[] = [
  { name: "left", x: -1, y: 0 }, { name: "right", x: 1, y: 0 }, { name: "up", x: 0, y: -1 }, { name: "down", x: 0, y: 1 },
  { name: "left", x: -1, y: -0.6 }, { name: "right", x: 1, y: 0.6 }, { name: "center", x: 0, y: 0 },
];
const FRONT: Look[] = [
  { name: "front", x: 0, y: 0.05 }, { name: "front-left", x: -0.25, y: 0.1 }, { name: "front", x: 0, y: 0.05 }, { name: "front-right", x: 0.25, y: 0.1 },
];
const TYPING: Look[] = [
  { name: "down-left", x: -0.5, y: 0.7 }, { name: "down", x: 0, y: 0.8 }, { name: "down-right", x: 0.5, y: 0.7 }, { name: "down", x: 0, y: 0.8 },
];
const TYPING_EVERY_MS = 1500;
const TYPING_MS = 3000; // typing counts until this long after the last keystroke
const CHAT_GAZE = 0.85; // how far the head turns towards the chat, 1 = as far as the eyes go

interface Profile { state: BotAvatarState; face?: BotAvatarFace; looks?: Look[]; everyMs?: number; doze?: boolean; chat?: boolean; dots?: boolean }
const PROFILE: Record<string, Profile> = {
  idle: { state: "default", looks: LOOK_AROUND, everyMs: 1300, doze: true },
  listening: { state: "default", looks: FRONT, everyMs: 2200, doze: true },
  thinking: { state: "default", chat: true, dots: true },
  working: { state: "working" },
  restarting: { state: "working" },
  speaking: { state: "default", face: "mouth", chat: true },
};
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function mountBot(parent: HTMLElement): void {
  const host = document.createElement("div");
  host.id = "jarvis-bot";
  host.setAttribute("aria-hidden", "true");
  host.dataset.shape = TYPE;
  host.dataset.shading = SHADING;
  const canvas = document.createElement("canvas");
  // the canvas draws bigger than its box so a hop is never clipped (bot-avatars convention)
  canvas.width = canvas.height = Math.round(BOX * BOT_AVATAR_OVERSCAN * dpr);
  canvas.style.width = canvas.style.height = `${BOX * BOT_AVATAR_OVERSCAN}px`;
  host.appendChild(canvas);
  parent.appendChild(host);
  const ctx = canvas.getContext("2d")!;
  const sim = new BotAvatarSim(Math.random(), "default");
  sim.setJump({ spin: 0 }); // hops are light bounces, never a full turn

  let ptr: { x: number; y: number } | null = null;
  let gaze: Look | null = null; // current look-around target
  let talking = false; // speaking: the bot draws its own mouth (the library's cannot open and shut)
  let open = 0; // how wide that mouth is, 0 shut … 1 wide
  const talk = createTalk();
  let cur: BotAvatarState = "default"; // the state the behaviour wants (the pointer can wake a sleeping bot)
  let hops = 0;
  let nods = 0;
  let lastNod = -NOD_EVERY_MS;
  let dots = false; // thinking: three dots over the head
  let typing = false; // the user is typing in the command box
  let typingTimer = 0;
  let lastNow = performance.now();
  let doze = 0; // pending "go to sleep" timer; 0 = not winding down
  let lastActive = performance.now();
  let sys = "idle"; // the last JARVIS state seen, so a waking bot behaves like that state
  let look = 0; // the look script's interval
  let lookIdx = 0;
  let looks: Look[] = [];

  function paint(): void {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawBotAvatarFrame(ctx, BOX, sim.pose, { ...cfg, still: reduced });
    if (talking) drawMouth(ctx, sim.pose, BOX, dpr, cfg, open);
    if (dots) drawThinkDots(ctx, BOX, dpr, lastNow);
  }

  function hop(): void {
    sim.poke(); // a hop (no turn, see spin above)
    host.dataset.hops = String(++hops);
  }

  /** Aims the gaze at the pointer when it is near. */
  function pointerPlay(): void {
    let following = false;
    if (ptr) {
      const r = host.getBoundingClientRect();
      const dx = ptr.x - (r.left + r.width / 2), dy = ptr.y - (r.top + r.height / 2);
      const d = Math.hypot(dx, dy);
      following = d <= FOLLOW_PX;
      if (following) sim.setPointer(clamp(dx / (BOX * 2), -1, 1), clamp(dy / (BOX * 2), -1, 1), 1);
      host.dataset.follow = following ? "1" : "0";
      if (following) activity();
    } else {
      host.dataset.follow = "0";
    }
    // no pointer to follow: the look-around (if any) steers the head, else it is left free
    if (!following) { if (gaze) sim.setPointer(gaze.x, gaze.y, 1); else sim.setPointer(0, 0, 0); }
  }

  /** `times` hops, `height` x the stock height, then the stock height comes back. */
  function jump(height: number, times: number): void {
    sim.setJump({ height: botAvatarJumpDefaults.height * height });
    hop();
    for (let i = 1; i < times; i++) setTimeout(hop, i * 420);
    setTimeout(() => sim.setJump({ height: botAvatarJumpDefaults.height }), times * 420 + 500);
  }
  /** Click: two happy hops. */
  const excite = () => jump(1.2, 2);

  function apply(state: BotAvatarState, f: BotAvatarFace = preset.face, thinking = false): void {
    cur = state;
    dots = thinking;
    if (thinking) host.dataset.dots = "1"; else delete host.dataset.dots;
    if (reduced) lastNow = 1500; // a still frame shows all three dots
    talking = f === "mouth";
    if (!talking) delete host.dataset.mouth;
    if (reduced) open = talking ? 0.45 : 0; // a still frame: mouth half open
    host.dataset.state = state;
    host.dataset.face = f;
    host.dataset.awake = "0";
    sim.setState(state);
    if (reduced) paint();
  }

  function lookAt(i: number): void {
    gaze = looks[i % looks.length];
    host.dataset.look = gaze.name;
  }

  /** The library flips/jumps at random while awake; during a look script that would break the calm. */
  function idleJumps(on: boolean): void {
    sim.setJump({ every: on ? botAvatarJumpDefaults.every : 0 });
    host.dataset.idlejumps = on ? "on" : "off";
  }

  /** The look script of a resting state (idle/listening): down at the command box while the user types, else the state's own. */
  function restLooks(p: Profile): void {
    if (typing) setLooks(TYPING, TYPING_EVERY_MS);
    else setLooks(p.looks!, p.everyMs!);
  }

  function setLooks(list: Look[], everyMs: number): void {
    clearInterval(look);
    delete host.dataset.gaze; // only the chat watch sets it
    looks = list;
    lookIdx = 0;
    lookAt(0);
    idleJumps(false);
    look = window.setInterval(() => lookAt(++lookIdx), everyMs);
  }

  /** Where the latest assistant bubble is, as a unit direction from the bot (up and left if there is none yet). */
  function chatLook(): Look {
    const r = host.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const bubbles = document.querySelectorAll<HTMLElement>("#chat-history .chat-bubble.assistant"), b = bubbles[bubbles.length - 1];
    let dx = -1, dy = -1;
    if (b) { const q = b.getBoundingClientRect(); dx = (q.left + q.right) / 2 - cx; dy = (q.top + q.bottom) / 2 - cy; }
    const d = Math.hypot(dx, dy) || 1;
    return { name: "chat", x: (dx / d) * CHAT_GAZE, y: (dy / d) * CHAT_GAZE };
  }

  /** Watches the chat: re-aims twice a second, so a bubble that grows or is scrolled away is followed. */
  function watchChat(): void {
    clearInterval(look);
    idleJumps(false);
    const aim = () => {
      gaze = chatLook();
      host.dataset.look = "chat";
      host.dataset.gaze = `${gaze.x.toFixed(2)},${gaze.y.toFixed(2)}`;
    };
    aim();
    look = window.setInterval(aim, 500);
  }

  function stopBehavior(): void {
    clearTimeout(doze);
    clearInterval(look);
    doze = look = 0;
    gaze = null;
    delete host.dataset.grace;
    delete host.dataset.look;
    delete host.dataset.gaze;
    idleJumps(true);
  }

  function startDoze(): void {
    clearTimeout(doze);
    lastActive = performance.now();
    const arm = (ms: number) => {
      doze = window.setTimeout(() => {
        const left = DOZE_MS - (performance.now() - lastActive);
        if (left > 50) { arm(left); return; } // there was activity meanwhile: wait out the rest
        stopBehavior();
        apply("sleeping");
      }, ms);
    };
    arm(DOZE_MS);
    host.dataset.grace = "1";
  }

  /** Something happened near the bot: a sleeping one wakes to idle (or listening), an awake one stays up another DOZE_MS. */
  function activity(): void {
    lastActive = performance.now();
    if (cur !== "sleeping") return;
    const p = PROFILE[sys];
    if (!p?.doze) return;
    startDoze();
    apply("default", p.face);
    restLooks(p);
  }

  window.addEventListener("jarvis:mascot", (e) => {
    const name = String((e as CustomEvent).detail);
    const p = PROFILE[name];
    if (!p) return;
    sys = name;
    if (reduced) { stopBehavior(); apply(p.doze ? "sleeping" : p.state, p.face); return; }
    if (p.doze) {
      if (cur === "sleeping" && !doze) return; // asleep: quiet states do not wake it
      if (!doze) startDoze(); // calming down from busy: DOZE_MS starts now (idle <-> listening keeps the clock)
      apply("default", p.face);
      restLooks(p);
      return;
    }
    stopBehavior();
    apply(p.state, p.face, p.dots);
    if (p.chat) watchChat();
    else if (p.looks) setLooks(p.looks, p.everyMs!);
  });

  if (!reduced) {
    // typing in the command box: a resting bot looks down at it, and goes back to its own script 3 s after the last key
    document.addEventListener("input", (e) => {
      if ((e.target as HTMLElement | null)?.id !== "command-input") return;
      const was = typing;
      typing = true;
      host.dataset.typing = "1";
      clearTimeout(typingTimer);
      typingTimer = window.setTimeout(() => {
        typing = false;
        delete host.dataset.typing;
        const p = PROFILE[sys];
        if (cur !== "sleeping" && p?.doze && doze) restLooks(p);
      }, TYPING_MS);
      const p = PROFILE[sys];
      if (!was && cur !== "sleeping" && p?.doze && doze) restLooks(p);
    }, true);
    // speech recognition returned something: the speaker is talking, so a listening bot nods now and then
    window.addEventListener("jarvis:heard", () => {
      activity();
      const now = performance.now();
      if (sys !== "listening" || cur !== "default" || now - lastNod < NOD_EVERY_MS) return;
      lastNod = now;
      host.dataset.nods = String(++nods);
      jump(0.45, 1);
    });
    window.addEventListener("pointermove", (e) => { ptr = { x: e.clientX, y: e.clientY }; }, { passive: true });
    for (const ev of ["pointerdown", "keydown", "touchstart"]) window.addEventListener(ev, activity, { passive: true });
    const release = () => { ptr = null; };
    window.addEventListener("blur", release);
    document.addEventListener("mouseleave", release);
    host.addEventListener("click", excite);
  }

  // start awake as if it had just gone idle: looks around, then dozes off after DOZE_MS
  apply(reduced ? "sleeping" : "default");
  if (!reduced) { startDoze(); setLooks(LOOK_AROUND, PROFILE.idle.everyMs!); }
  paint();
  if (!reduced) gatedLoop((now, dt) => { lastNow = now; pointerPlay(); sim.update(Math.min(dt / 1000, 0.05)); if (talking) { open = talk(now, dt); const m = open.toFixed(1); if (host.dataset.mouth !== m) host.dataset.mouth = m; } paint(); }, 1000 / 60); // 60 fps on phones too: a 32px sprite is cheap, and 30 fps looked choppy
}
