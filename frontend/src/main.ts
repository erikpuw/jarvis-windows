/**
 * JARVIS — Main entry point.
 *
 * Wires together the orb visualization, WebSocket communication,
 * speech recognition, and audio playback into a single experience.
 */

import { createOrb, type OrbState } from "./orb";
import { mountWelcome, type WelcomeData } from "./welcome";
import { createVoiceInput, createAudioPlayer, createInterruptDetector } from "./voice";
import { createSocket } from "./ws";
import { checkFirstTimeSetup, ensureMounted } from "./settings/index";
import { formatMarkdown } from "./markdown";
import { escapeHtml } from "./settings/api";
import "./style.css";
import { showStreamLoader, clearStreamLoader } from "./stream-loader";
import { isAskCard, showAskPanel } from "./ask-panel";
import { mountControlsMenu } from "./controls-menu";
import { mountViewportReset } from "./viewport-reset";
import { mountNotifyIsland } from "./notify-island";
import { mountStatusOrb } from "./status-orb";
import { mountStatusLabel, mountStatusRowFade } from "./status-label";
import { mountMetalRing } from "./metal-ring";
import { mountReaderCard } from "./reader-card";
import { setAnimPaused, setBarHidden } from "./anim-gate";
import { ensureAuthenticated } from "./auth-gate";

// Top-level gate: ensure user authentication before anything else initializes
await ensureAuthenticated();

const DEFAULT_FETCH_TIMEOUT_MS = 15000;
const UPLOAD_FETCH_TIMEOUT_MS = 120000;

/** fetch() has no timeout of its own, so a stalled backend left spinners
 *  turning forever with no error path. */
async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_FETCH_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}
// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

type State = "idle" | "listening" | "thinking" | "working" | "speaking" | "restarting";
let currentState: State = "idle";
let isMuted = true;
let isTtsDisabled = localStorage.getItem("jarvis_tts_disabled") === "true";
let isBusy = false;
let lastWorkState: "thinking" | "working" = "thinking";
let lastWorkMessage: string | undefined; // e.g. "Công cụ: Tra giá", shown again when the speech in front of it ends
// The turn's TTS (one VoiceStreamer per turn): open from its first "speaking" (source tts) to its idle, which comes after
// stream_end once every sentence is synthesised (backend c541345). Audio keeps arriving after stream_end.
let ttsOpen = false;
// The TTS said "speaking" for a sentence but no sound is out yet ("Đang chuẩn bị…"): the turn loop keeps sending
// working/thinking meanwhile (engine/turn/loop.py _run_tool), which must not cover it, nor "Đang đọc…" while sound plays.
let speechPreparing = false;
// The status label follows status packets only (user, 2026-10-15; backend 444477c): stream_start/text_chunk/stream_end are
// for the typing bubble. The LLM's own idle (no source) ends working/thinking; the TTS's speaking/idle (source tts) drive the
// reading label, which the LLM's idle and the tool's working/thinking never cover.

/** The speech went quiet. Still busy (the LLM writing, a tool running): show that work. LLM done: idle, unless the TTS has
 *  more to read (a pause between two sentences keeps "Đang đọc…" until its idle). */
function afterSpeech(): void {
  if (isBusy) transition(lastWorkState, lastWorkMessage);
  else if (!ttsOpen) transition("idle");
}
let isSpeaking = false;
let pendingQueriesQueue: { type: "voice" | "text", text: string, file?: File, bubbleElement?: HTMLElement }[] = [];

let activeAssistantBubble: HTMLElement | null = null;
let activeAssistantText = "";
let streamTextBuffer = "";
let streamTargetText = "";
let streamTypewriterTimer: any = null;
let streamTail: Text | null = null; // the line being typed (renderStreamText)
let streamDirty = false; // letters were shown since the turn started
let streamLastAppendAt = 0;
let streamHoldUntil = 0; // the typewriter waits for this time: the loader balls shrink first so they do not cover the first letter
let wasStreamed = false;
let isStreamActive = false;
let isBubbleFinalRendered = false;
let audioChunkBuffer: Uint8Array[] | null = null;
// Tải bản gốc upscale: chờ gắn nút icon ⬇ vào bong bóng phản hồi cuối lượt
// (stream_end), thay vì vẽ rời gây trùng lặp.

const chatHistory = document.getElementById("chat-history")!;
// A bubble's slide-up is dropped once it has played: iPhone Safari kept a GPU layer per animated bubble, re-blended every frame
// over the moving orb, so the phone heated up with every bubble added (user 2026-10-17)
chatHistory.addEventListener("animationend", (e) => {
  const el = e.target as HTMLElement;
  if (e.animationName === "slide-up" && el.classList.contains("chat-bubble")) el.style.animation = "none";
});
const statusEl = document.getElementById("status-text")!;
const island = mountNotifyIsland(document.getElementById("error-text")!); // flow tracker + system errors (notify-island.ts)
mountViewportReset();
mountControlsMenu(document.getElementById("controls")!, document.getElementById("btn-controls") as HTMLButtonElement);
mountStatusOrb(document.getElementById("status-orb")!);
mountStatusLabel(document.getElementById("status-row")!, statusEl);
mountStatusRowFade(document.getElementById("status-row")!, statusEl);
mountMetalRing(document.getElementById("cmd-send-wrap")!);
initChatAutoCeiling();
mountReaderCard();
const commandInput = document.getElementById("command-input") as HTMLTextAreaElement;
const filePinnedContainer = document.getElementById("file-pinned-container")!;
const filePinnedName = document.getElementById("file-pinned-name")!;
const btnFileRemove = document.getElementById("btn-file-remove")!;
let userHasScrolledUp = false;

/**
 * Tự động đo và điều chỉnh trần (maxHeight) của #chat-history theo thời gian thực:
 * - Dừng dưới viên đảo thông báo (#error-text, Dynamic Island) một khoảng GAP; đồng hồ đã gỡ (2026-10-15).
 * - Trên mobile: co xuống dưới mép Media Player hoặc Webcam HUD khi chúng mở.
 * - Thích ứng chính xác với mọi kích thước / tỉ lệ màn hình (iPhone SE, Pro Max, Android...).
 * - Hoàn toàn không can thiệp vào bàn phím ảo, để hệ điều hành đẩy giao diện tự nhiên.
 */
function initChatAutoCeiling(): void {
  const mediaEl = document.getElementById("media-player");
  const webcamEl = document.getElementById("webcam-hud");
  const isPhone = () => matchMedia("(max-width: 768px)").matches;
  const GAP = 10; // thụt xuống dưới đáy viên đảo/media/webcam một chút (~20px tính cả viền mờ mép trên), không sát
  const MIN_HEIGHT = 100;

  let frame = 0;
  const updateCeiling = () => {
    frame = 0;
    let topCeiling = 0;
    const phone = isPhone();

    if (phone && mediaEl && !mediaEl.classList.contains("hidden")) {
      topCeiling = Math.max(topCeiling, mediaEl.getBoundingClientRect().bottom);
    }
    if (phone && webcamEl && !webcamEl.classList.contains("hidden")) {
      topCeiling = Math.max(topCeiling, webcamEl.getBoundingClientRect().bottom);
    }
    // the island's resting pill, from layout offsets: its enter/leave scale and the card it opens over the chat must not move the chat
    const island = document.getElementById("error-text");
    const pill = island?.querySelector<HTMLElement>(".island-pill");
    if (island && pill) topCeiling = Math.max(topCeiling, island.offsetTop + pill.offsetTop + pill.offsetHeight);

    const bottom = chatHistory.getBoundingClientRect().bottom;
    // max-height is the content box: the list's own padding comes on top of it, so it is taken off here (it ate the GAP)
    const cs = getComputedStyle(chatHistory);
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const available = bottom - topCeiling - GAP - pad;
    if (available > 0) {
      chatHistory.style.maxHeight = `${Math.max(MIN_HEIGHT, Math.floor(available))}px`;
    }
  };

  // a new height scrolls nothing by itself: the newest message is put back at the bottom (unless the user scrolled up to read)
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(() => { updateCeiling(); scrollToBottomIfNeeded(); });
  };

  window.addEventListener("resize", schedule);
  // the island hangs below the safe area: a native shell (Capacitor iOS) reports the top inset after load with no resize event,
  // the island moved down and the chat ran up over the top buttons (2026-10-18). A probe as tall as the inset tells us.
  const insetProbe = document.createElement("div");
  insetProbe.style.cssText = "position:fixed;top:0;left:0;width:0;height:env(safe-area-inset-top,0px);visibility:hidden;pointer-events:none";
  document.body.appendChild(insetProbe);
  new ResizeObserver(schedule).observe(insetProbe);
  // the list sits right above the input in #command-container: a long question grows the input (up to 140px) and lifted the
  // list over the island and the top buttons, then sending shrank it and the list dropped (2026-10-18). Same for a pinned file.
  const below = new ResizeObserver(schedule);
  for (const id of ["command-input", "file-pinned-container"]) { const el = document.getElementById(id); if (el) below.observe(el); }
  const mo = new MutationObserver(schedule);
  if (mediaEl) mo.observe(mediaEl, { attributes: true, attributeFilter: ["class"] });
  if (webcamEl) mo.observe(webcamEl, { attributes: true, attributeFilter: ["class"] });
  updateCeiling();
}

function updateScrollFade() {
  if (!chatHistory) return;
  // Check if we are within 10px of the bottom
  const isAtBottom = Math.abs(chatHistory.scrollHeight - chatHistory.clientHeight - chatHistory.scrollTop) < 10;
  const isOverflowing = chatHistory.scrollHeight > chatHistory.clientHeight + 1;
  chatHistory.classList.toggle("at-bottom", isAtBottom);
  chatHistory.classList.toggle("overflowing", isOverflowing);
  const cmdContainer = document.getElementById("command-container");
  if (cmdContainer) {
    cmdContainer.classList.toggle("has-chat-fade", isOverflowing && chatHistory.scrollTop > 4);
  }

  // If user scrolled near the bottom, reset the flag so auto-scroll can resume
  if (isAtBottom) {
    userHasScrolledUp = false;
  }
}

/**
 * The scrollTop that puts the last real bubble at the bottom. scrollHeight is not used because it
 * also counts decorative overflow: the stream loader's gooey box spills ~30px below its bubble,
 * which scrolled the chat up and left an empty band under the loader.
 */
function contentBottomScrollTop(): number {
  let last = chatHistory.lastElementChild as HTMLElement | null;
  while (last && last.offsetHeight === 0) last = last.previousElementSibling as HTMLElement | null; // skip display:none
  if (!last) return 0;
  const pad = parseFloat(getComputedStyle(chatHistory).paddingBottom) || 0;
  return Math.max(0, last.offsetTop + last.offsetHeight + pad - chatHistory.clientHeight);
}

function scrollToBottomIfNeeded(force = false) {
  if (!chatHistory) return;
  if (force) {
    userHasScrolledUp = false;
  }

  if (force || !userHasScrolledUp) {
    chatHistory.scrollTop = contentBottomScrollTop();
    updateScrollFade();
  }
  // A jump from far up lands short: the bubbles it skips over were off screen, and off screen an older bubble only counts
  // its 48px placeholder (content-visibility, style.css). Once they are on screen they lay out at their real height, so the
  // bottom is measured again for a few frames (2026-10-18: after a send the chat stayed where the user had been reading).
  if (force) {
    let frames = 3;
    const settle = () => {
      const bottom = contentBottomScrollTop();
      if (Math.abs(chatHistory.scrollTop - bottom) > 1) { chatHistory.scrollTop = bottom; updateScrollFade(); }
      if (--frames > 0) requestAnimationFrame(settle);
    };
    requestAnimationFrame(settle);
  }
}

// Detect manual user scrolling
function handleManualScroll() {
  if (!chatHistory) return;
  const isAtBottom = Math.abs(contentBottomScrollTop() - chatHistory.scrollTop) < 15;
  if (!isAtBottom) {
    userHasScrolledUp = true;
  }
}

chatHistory.addEventListener("scroll", updateScrollFade);
// the list grows until it hits its max-height; that last resize is when it starts to overflow
new ResizeObserver(updateScrollFade).observe(chatHistory);
chatHistory.addEventListener("wheel", handleManualScroll, { passive: true });
chatHistory.addEventListener("touchmove", handleManualScroll, { passive: true });

/**
 * Reveals streamed text at a steady, frame-locked pace. It used to be setInterval(16ms), which does
 * not line up with the display's frames: some frames got 0 new characters and the next got 2-4,
 * which reads as stutter. Now one requestAnimationFrame loop turns elapsed time into characters
 * (fractional remainder carried over), at a base rate that speeds up with the backlog so it never
 * falls far behind the model.
 */
const STREAM_BASE_CPS = 60; // characters per second when keeping up
const STREAM_TEXT_AFTER_LOADER_MS = 200; // first chunk: the four loader balls shrink (300 ms) and the first letter shows when they are almost gone
const STREAM_CATCHUP_S = 0.3; // otherwise drain the backlog in about this long

/** Newlines at the very end of the streamed text are not shown yet: they would open blank lines under the last line before the
 *  next paragraph has a single letter, and the letters would then jump to where the blank lines are. They appear with the next letter. */
const withoutTrailingNewlines = (s: string) => s.replace(/\n+$/, "");

/**
 * Finalizes the markdown rendering for the current assistant bubble exactly once.
 * Replaces incomplete table skeletons with real HTML tables and locks further repaints.
 */
function finalizeBubbleMarkdown(container: HTMLElement, text: string): void {
  if (isBubbleFinalRendered) return;
  isBubbleFinalRendered = true;
  const shown = withoutTrailingNewlines(text);
  container.innerHTML = formatMarkdown(shown, { isBubble: true, isStreaming: false });
  streamTail = streamTailBox = null;
  scrollToBottomIfNeeded();
}

/**
 * Reveals streamed text the way the final render will show it, so the end moves nothing:
 * - The finished lines are rendered as markdown (isStreaming: true: an unfinished table shows as the skeleton, a finished
 *   one as the real table at once); the line being typed goes letter by letter into a text node placed where markdown
 *   will put it: after a <br> in the last paragraph (one newline, breaks: true) or in a new paragraph (a blank line).
 *   Raw text in pre-wrap showed a two-round answer's blank line (engine/turn/loop.py out.gap()) while the tool ran, and
 *   the final markdown closed it to a 6px paragraph gap: the text jumped up at the end (user 2026-10-17).
 * - Markdown is rendered again only when a line is finished, and the bubble rewritten only when that HTML changes: a table
 *   row being typed stays under the skeleton (a bare "|" stands for it), so rows arriving never rebuild the bubble.
 * - Final render: Applied once on completion via finalizeBubbleMarkdown (isStreaming: false).
 */
let streamLastHead: string | null = null; // the finished lines last rendered as markdown
let streamLastHtml = "";
let streamTailBox: Element | null = null; // the <p> or <br> the line being typed was placed with

function placeStreamTail(container: HTMLElement, newBlock: boolean) {
  streamTail?.remove();
  streamTailBox?.remove();
  streamTail = document.createTextNode("");
  const host = container.querySelector(".bubble-prose") ?? container;
  const last = host.lastElementChild;
  if (!newBlock && last?.tagName === "P") {
    streamTailBox = document.createElement("br");
    last.append(streamTailBox, streamTail);
  } else {
    streamTailBox = document.createElement("p");
    streamTailBox.append(streamTail);
    host.appendChild(streamTailBox);
  }
}

function renderStreamText(container: HTMLElement, chunk: string) {
  if (isBubbleFinalRendered) return;
  if (chunk) streamDirty = true;

  const cut = streamTextBuffer.lastIndexOf("\n") + 1;
  const tail = streamTextBuffer.slice(cut);
  const typingRow = tail.trimStart().startsWith("|");
  const typing = !typingRow && tail.trim() !== "";
  // once a line that is not a row is being typed, a table above is finished: keep the blank line that ends it
  const head = typingRow ? streamTextBuffer.slice(0, cut) + "|"
    : typing ? streamTextBuffer.slice(0, cut) + "\n" : withoutTrailingNewlines(streamTextBuffer);
  const newBlock = cut === 0 || /\n[ \t]*\n$/.test(streamTextBuffer.slice(0, cut));
  if (head !== streamLastHead) {
    streamLastHead = head;
    const html = formatMarkdown(head, { isBubble: true, isStreaming: true });
    if (html !== streamLastHtml) {
      streamLastHtml = html;
      container.innerHTML = html;
    }
    if (typing) placeStreamTail(container, newBlock);
    else {
      streamTail?.remove();
      streamTailBox?.remove();
      streamTail = streamTailBox = null;
    }
  }
  if (typing && streamTail) streamTail.data = tail;
}

let typeAcc = 0; // characters owed to the reader (fractional)
let typePrev = 0;

/** New turn: empty buffers. The loop itself only starts with the first text_chunk (wakeStreamTypewriter). */
function startStreamTypewriter() {
  stopStreamTypewriter();
  streamTextBuffer = "";
  streamTargetText = "";
  streamTail = streamTailBox = null;
  streamDirty = false;
  streamHoldUntil = 0;
  typeAcc = 0;
  isBubbleFinalRendered = false;
  streamLastHead = null;
  streamLastHtml = "";
}

/** Each text_chunk wakes the loop; it stops by itself once every letter is shown and the final render is done, so nothing runs
 *  while the turn waits for a tool between two rounds of text (the next round's text_chunk wakes it again). */
function wakeStreamTypewriter() {
  if (streamTypewriterTimer || !activeAssistantBubble) return;
  typePrev = performance.now();
  streamTypewriterTimer = requestAnimationFrame(typeStep);
}

function typeStep(now: number) {
  streamTypewriterTimer = null;
  if (!activeAssistantBubble) return;
  // Nếu text đích bắt đầu bằng prefix của Interactive Card, ta không hiển thị text thô qua typewriter
  if (streamTargetText.startsWith("[INTERACTIVE_CARD_JSON]:")) return;
  const dt = Math.min((now - typePrev) / 1000, 0.1);
  typePrev = now;
  const again = () => { streamTypewriterTimer = requestAnimationFrame(typeStep); };
  if (now < streamHoldUntil) return again();

  let textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement;
  if (!textContainer) {
    textContainer = document.createElement("div");
    textContainer.className = "bubble-text";
    activeAssistantBubble.appendChild(textContainer);
  }

  const backlog = streamTargetText.length - streamTextBuffer.length;
  if (backlog <= 0) {
    typeAcc = 0;
    if (isBubbleFinalRendered) return;
    // If stream is still active from server, do not prematurely finalize
    if (isStreamActive) return;
    // Stream ended and all characters caught up: finalize once
    if (now - streamLastAppendAt > 100 || !streamDirty) {
      finalizeBubbleMarkdown(textContainer, streamTextBuffer);
      return;
    }
    return again();
  }

  typeAcc += Math.max(STREAM_BASE_CPS, backlog / STREAM_CATCHUP_S) * dt;
  const take = Math.min(backlog, Math.floor(typeAcc));
  if (take > 0) {
    typeAcc -= take;
    const chunk = streamTargetText.slice(streamTextBuffer.length, streamTextBuffer.length + take);
    streamTextBuffer += chunk;
    streamLastAppendAt = now;
    renderStreamText(textContainer, chunk);
    scrollToBottomIfNeeded();
  }
  again();
}

function stopStreamTypewriter() {
  if (streamTypewriterTimer) {
    cancelAnimationFrame(streamTypewriterTimer);
    streamTypewriterTimer = null;
  }
  if (
    activeAssistantBubble &&
    streamTargetText &&
    !streamTargetText.startsWith("[INTERACTIVE_CARD_JSON]:") &&
    streamTextBuffer.length < streamTargetText.length
  ) {
    streamTextBuffer = streamTargetText;
  }
}

/** server.py's error fallback sends one "audio"/"text" packet and no stream_end: a bubble still waiting for its first letter
 *  would keep its loader forever, and the fallback text gets its own bubble anyway. */
function dropEmptyAssistantBubble(): void {
  if (!activeAssistantBubble || activeAssistantText) return;
  isStreamActive = false;
  stopStreamTypewriter();
  activeAssistantBubble.remove();
  activeAssistantBubble = null;
}

/** Ends the assistant bubble of the current turn: stops the typewriter, removes the loader, renders the full text.
 *  stream_end calls it; so do our own cancel and the next stream_start, because a cancelled turn (engine/turn/loop.py out.abort())
 *  gets neither stream_end nor idle, otherwise the goo loader and the typewriter loop kept running in the chat history. */
function closeAssistantBubble(): void {
  isStreamActive = false;
  stopStreamTypewriter();
  if (activeAssistantBubble) {
    if (activeAssistantBubble.classList.contains("typing-loader")) {
      clearStreamLoader(activeAssistantBubble, true);
    }
    activeAssistantBubble.querySelectorAll(".stream-bubble-host").forEach((el) => el.remove());
    [...activeAssistantBubble.childNodes].forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) node.remove();
    });
    let textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement;
    if (!textContainer) {
      textContainer = document.createElement("div");
      textContainer.className = "bubble-text";
      activeAssistantBubble.appendChild(textContainer);
    }
    finalizeBubbleMarkdown(textContainer, activeAssistantText || streamTextBuffer);
    scrollToBottomIfNeeded();
  }
  activeAssistantBubble = null;
}

let pendingFile: File | null = null;

export { formatMarkdown };


function addChatMessage(role: "user" | "assistant", text: string): HTMLElement | null {
  console.log(`[UI] Adding ${role} message: ${text}`);
  if (role === "user") welcome.dismiss(); // every user message passes here: the first one ends the welcome
  if (!chatHistory) {
    console.error("[UI] Chat history element not found!");
    return null;
  }

  // De-duplication: Don't add the exact same message twice in a row
  const lastBubble = chatHistory.lastElementChild as HTMLElement;
  if (lastBubble && lastBubble.classList.contains(role) && lastBubble.textContent === text) {
    console.log("[UI] Duplicate message detected, skipping add.");
    return lastBubble;
  }

  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  chatHistory.appendChild(bubble);

  // Helper check for interactive card pattern in text
  // Định dạng có cấu trúc dạng: [INTERACTIVE_CARD_JSON]: { ... }
  const prefix = "[INTERACTIVE_CARD_JSON]:";
  if (role === "assistant" && text.startsWith(prefix)) {
    try {
      const jsonStr = text.substring(prefix.length).trim();
      const cardData = JSON.parse(jsonStr);
      if (isAskCard(cardData)) {
        bubble.remove();
        showAskPanel(cardData, (m) => socket.send(m));
        return null;
      }
      renderInteractiveCard(bubble, cardData);
      // Cuộn xuống dưới
      requestAnimationFrame(() => {
        scrollToBottomIfNeeded();
      });
      return bubble;
    } catch (e) {
      console.error("[UI] Parse interactive card failed:", e);
    }
  }

  if (role === "user") {
    bubble.innerHTML = formatMarkdown(text, { isBubble: true });
    // Scroll to bottom (force since user just sent a message)
    requestAnimationFrame(() => {
      scrollToBottomIfNeeded(true);
    });
  } else {
    bubble.innerHTML = formatMarkdown(text, { isBubble: true });
    requestAnimationFrame(() => {
      scrollToBottomIfNeeded();
    });
  }

  // No cap on the bubbles: a chat session is one conversation (a reload starts a new one), so it keeps all of it.

  return bubble;
}


function openImageLightbox(src: string) {
  let lightbox = document.getElementById("image-lightbox") as HTMLElement;
  if (!lightbox) {
    lightbox = document.createElement("div");
    lightbox.id = "image-lightbox";

    const img = document.createElement("img");
    img.id = "lightbox-img";
    lightbox.appendChild(img);

    const closeBtn = document.createElement("button");
    closeBtn.innerHTML = "✕";
    closeBtn.id = "lightbox-close";
    closeBtn.style.cssText = "position:fixed; top:20px; right:20px; font-size:var(--fs-heading); color:#fff; background:rgba(8,10,18,0.7); border:1px solid rgba(0,212,255,0.3); border-radius:50%; width:44px; height:44px; display:flex; align-items:center; justify-content:center; cursor:pointer; z-index:1; box-shadow:0 0 10px rgba(0,212,255,0.2);";
    lightbox.appendChild(closeBtn);

    document.body.appendChild(lightbox);

    // Zoom & Pan state
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialDistance = 0;
    let initialScale = 1;
    let lastTap = 0;

    const resetTransform = () => {
      scale = 1;
      translateX = 0;
      translateY = 0;
      img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    };

    (lightbox as any)._resetTransform = resetTransform;

    const closeLightbox = () => {
      lightbox.classList.remove("active");
      setTimeout(() => {
        lightbox.style.display = "none";
        resetTransform();
      }, 250);
    };

    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeLightbox();
    });

    // Close when clicking outside the image container
    lightbox.addEventListener("click", (e) => {
      if (e.target === lightbox) {
        closeLightbox();
      }
    });

    // Touch events for pinch to zoom & drag to pan
    img.addEventListener("touchstart", (e) => {
      if (e.touches.length === 2) {
        e.preventDefault();
        initialDistance = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        initialScale = scale;
      } else if (e.touches.length === 1) {
        // Double tap detection
        const now = Date.now();
        if (now - lastTap <= 300) {
          e.preventDefault();
          if (scale > 1) {
            scale = 1;
            translateX = 0;
            translateY = 0;
          } else {
            scale = 2.5;
          }
          img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
        } else {
          if (scale > 1) {
            isDragging = true;
            startX = e.touches[0].clientX - translateX;
            startY = e.touches[0].clientY - translateY;
          }
        }
        lastTap = now;
      }
    });

    img.addEventListener("touchmove", (e) => {
      if (e.touches.length === 2) {
        e.preventDefault();
        const dist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        scale = Math.min(Math.max(initialScale * (dist / initialDistance), 1), 4);
        img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
      } else if (e.touches.length === 1 && isDragging) {
        e.preventDefault();
        translateX = e.touches[0].clientX - startX;
        translateY = e.touches[0].clientY - startY;
        img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
      }
    });

    img.addEventListener("touchend", () => {
      isDragging = false;
    });
  }

  const lightboxImg = lightbox.querySelector("#lightbox-img") as HTMLImageElement;
  if (lightboxImg) {
    lightboxImg.src = src;
  }

  // Reset scale and position whenever opening
  if ((lightbox as any)._resetTransform) {
    (lightbox as any)._resetTransform();
  }

  lightbox.style.display = "flex";
  lightbox.offsetHeight; // Force reflow
  lightbox.classList.add("active");
}

function handleInteractiveCardData(cardData: any) {
  if (!cardData || !cardData.id) return;
  // a question the backend waits on is a box above the command bar, not a chat bubble
  if (isAskCard(cardData)) return showAskPanel(cardData, (m) => socket.send(m));
  const existingBubble = document.querySelector(`.chat-bubble[data-card-id="${cardData.id}"]`) as HTMLElement;
  if (existingBubble) {
    renderInteractiveCard(existingBubble, cardData);
    return;
  }

  const cardBubble = document.createElement("div");
  cardBubble.className = "chat-bubble assistant";
  cardBubble.id = `card-${Date.now()}`;
  cardBubble.setAttribute("data-card-id", cardData.id);
  renderInteractiveCard(cardBubble, cardData);

  if (activeAssistantBubble && activeAssistantBubble.parentElement === chatHistory) {
    chatHistory.insertBefore(cardBubble, activeAssistantBubble);
  } else {
    chatHistory.appendChild(cardBubble);
  }

  requestAnimationFrame(() => {
    scrollToBottomIfNeeded();
  });
}


/** Icon trang tệp cho thẻ tài liệu: Word (xanh dương), Excel (xanh lá),
 *  PowerPoint (cam), PDF (đỏ); đuôi lạ thì tem màu xám kèm tên đuôi. */
function officeFileIconSvg(ext?: string, label?: string): string {
  const key = (label || ext || "").toLowerCase();
  const suffix = (ext || "").toLowerCase();
  let bg = "#64748b";
  let text = (suffix || "file").toUpperCase().slice(0, 4);
  if (["word", "doc", "docx", "odt"].includes(key) || ["doc", "docx", "odt"].includes(suffix)) {
    bg = "#2B579A";
    text = "W";
  } else if (["excel", "xls", "xlsx", "csv", "ods"].includes(key) || ["xls", "xlsx", "csv", "ods"].includes(suffix)) {
    bg = "#217346";
    text = "X";
  } else if (["powerpoint", "ppt", "pptx", "odp"].includes(key) || ["ppt", "pptx", "odp"].includes(suffix)) {
    bg = "#D24726";
    text = "P";
  } else if (key === "pdf" || suffix === "pdf") {
    bg = "#DC1F26";
    text = "PDF";
  }
  const fontSize = text.length > 3 ? 9 : 11;
  return `<svg viewBox="0 0 40 48" width="34" height="41" aria-hidden="true">
    <path d="M4 2h20l12 12v30a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" fill="#e8eef7" stroke="#c3d0e3"/>
    <path d="M24 2l12 12H26a2 2 0 0 1-2-2V2z" fill="#c3d0e3"/>
    <rect x="3" y="26" width="34" height="17" rx="3" fill="${bg}"/>
    <text x="20" y="38.5" text-anchor="middle" font-size="${fontSize}" font-weight="700"
      fill="#ffffff" font-family="system-ui, sans-serif">${text}</text>
  </svg>`;
}

const DOWNLOAD_SVG = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/></svg>';

/** Plain download icon (no colour), used on a file card and on the corner of an image. */
function downloadLink(className: string, href: string, name?: string): HTMLAnchorElement {
  const a = document.createElement("a");
  a.className = className;
  a.href = href;
  a.setAttribute("download", name || "tệp");
  a.title = `Tải về ${name || "tệp"}`;
  a.innerHTML = DOWNLOAD_SVG;
  return a;
}

/** "240 KB" from the byte count the backend sends with output_file (engine/core/output_delivery.py); "" when unknown. */
function formatSize(n?: number | null): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function renderInteractiveCard(container: HTMLElement, data: any) {
  const existingCard = container.querySelector(".interactive-card");
  if (existingCard) existingCard.remove();
  if (data.id) {
    container.setAttribute("data-card-id", data.id);
  }
  const card = document.createElement("div");
  card.className = "interactive-card";

  if (data.title) {
    const title = document.createElement("div");
    title.className = "interactive-card-title";
    title.textContent = data.title;
    card.appendChild(title);
  }

  if (data.type === "image_result") {
    // Ảnh nằm ngay trong câu trả lời (kiểu claude.ai): bấm là phóng to; ảnh có bản gốc để tải
    // (upscale) thì nút tải nhỏ nằm trên góc ảnh. Ảnh chụp màn hình không có nút.
    if (data.url) {
      const wrap = document.createElement("div");
      wrap.className = "image-result";
      const img = document.createElement("img");
      img.className = "image-result-preview";
      img.src = data.url;
      img.alt = data.name || "ảnh";
      img.addEventListener("click", () => openImageLightbox(img.src));
      img.addEventListener("load", () => scrollToBottomIfNeeded());
      wrap.appendChild(img);
      if (data.downloadUrl) wrap.appendChild(downloadLink("image-download", data.downloadUrl, data.name));
      card.appendChild(wrap);
    }
  } else if (data.type === "file") {
    // Thẻ tài liệu Office: icon Word/Excel/PowerPoint/PDF + tên tệp + nút
    // Tải về trỏ tới /api/outputs/{token}?download=1. Ảnh không qua đây nữa:
    // ảnh upscale và ảnh chụp màn hình là khung xem trước image_result (nhánh trên).
    card.classList.add("file-card");
    const name = data.name || "tệp";
    // PDF xem được ngay trong trình duyệt: bấm thẻ là mở ở tab mới; Word/Excel/PPT bấm thẻ là tải về.
    const open = document.createElement("a");
    open.className = "file-open";
    if ((data.ext || "").toLowerCase() === "pdf" && data.url) {
      open.href = data.url;
      open.target = "_blank";
      open.rel = "noopener";
    } else {
      open.href = data.downloadUrl || data.url || "#";
      open.setAttribute("download", name);
    }
    const icon = document.createElement("span");
    icon.className = "file-icon";
    icon.innerHTML = officeFileIconSvg(data.ext, data.label);
    const meta = document.createElement("div");
    meta.className = "file-meta";
    const nameEl = document.createElement("div");
    nameEl.className = "file-name";
    nameEl.textContent = name;
    nameEl.title = name;
    const line = document.createElement("div");
    line.className = "file-meta-line";
    const kind = data.label || (data.ext || "").toUpperCase();
    const caption = (data.caption || "").trim();
    line.textContent = [kind, formatSize(data.size), caption].filter(Boolean).join(" · ");
    meta.append(nameEl, line);
    open.append(icon, meta);
    card.append(open, downloadLink("file-download", data.downloadUrl || data.url || "#", name));
  }

  const textContainer = container.querySelector(".bubble-text");
  if (textContainer) {
    container.insertBefore(card, textContainer);
  } else {
    container.appendChild(card);
  }
}


function showError(msg: string) {
  island.error(msg);
  window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: "error" }));
}

let currentTurnId: string = Date.now().toString();



// ---------------------------------------------------------------------------
// Webcam HUD Logic
// ---------------------------------------------------------------------------

const webcamHud = document.getElementById("webcam-hud")!;
const webcamVideo = document.getElementById("webcam-video") as HTMLVideoElement;
const webcamOverlay = document.getElementById("webcam-overlay") as HTMLImageElement;
const webcamSelect = document.getElementById("webcam-device-select") as HTMLSelectElement;
let webcamStream: MediaStream | null = null;
let selectedCameraId: string | null = null;

// Giao diện lắng nghe sự thay đổi camera thiết bị từ select dropdown
if (webcamSelect) {
  webcamSelect.addEventListener("change", async () => {
    selectedCameraId = webcamSelect.value;
    if (webcamStream) {
      // Tắt stream cũ đi trước khi mở stream mới
      webcamStream.getTracks().forEach(track => track.stop());
      webcamStream = null;
    }
    await startWebcamStream();
  });
}

// Chức năng bật webcam thực tế
async function startWebcamStream() {
  try {
    console.log("[Webcam] Starting webcam stream with deviceId:", selectedCameraId);
    const constraints: MediaStreamConstraints = {
      video: selectedCameraId
        ? {
          deviceId: { ideal: selectedCameraId },
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 15 }
        }
        : {
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 15 }
        }
    };
    webcamStream = await navigator.mediaDevices.getUserMedia(constraints);
    webcamVideo.srcObject = webcamStream;

    webcamVideo.onloadedmetadata = () => {
      const labelEl = document.querySelector(".hud-label-cam");
      if (labelEl) {
        labelEl.textContent = `CAM-01 ACTIVE (${webcamVideo.videoWidth}x${webcamVideo.videoHeight})`;
      }
      console.log(`[Webcam] Current Active Resolution: ${webcamVideo.videoWidth}x${webcamVideo.videoHeight}`);
      if (webcamStream) {
        const track = webcamStream.getVideoTracks()[0];
        if (track && typeof track.getCapabilities === "function") {
          console.log("[Webcam] Hardware Capabilities (Supported Range):", track.getCapabilities());
        }
      }
    };

    // Đảm bảo video được phát ngay lập tức
    await webcamVideo.play().catch(err => console.warn("[Webcam] Autoplay prevented, waiting for interaction:", err));

    // Cập nhật lại dropdown danh sách thiết bị
    await populateCameraDevices();

  } catch (err) {
    console.error("[Webcam] Error starting webcam:", err);
    showError("Không thể truy cập Webcam, thưa Ngài.");
  }
}

// Lấy danh sách các camera của máy hoặc điện thoại gắn vào
async function populateCameraDevices() {
  if (!webcamSelect) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const videoDevices = devices.filter(d => d.kind === "videoinput");

    // Lưu lại giá trị đang chọn
    const currentVal = webcamSelect.value || selectedCameraId;
    webcamSelect.innerHTML = "";

    videoDevices.forEach((device, idx) => {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `Camera ${idx + 1}`;
      if (device.deviceId === currentVal) {
        option.selected = true;
      }
      webcamSelect.appendChild(option);
    });

    // Nếu chưa cấu hình camera mặc định, chọn thiết bị đầu tiên làm mặc định
    if (!selectedCameraId && videoDevices.length > 0) {
      selectedCameraId = videoDevices[0].deviceId;
    }
  } catch (err) {
    console.error("[Webcam] Error enumerating video devices:", err);
  }
}

async function toggleWebcam(show: boolean) {
  const btnWebcam = document.getElementById("btn-webcam-toggle");
  if (show) {
    try {
      console.log("[Webcam] Requesting access...");
      await startWebcamStream();
      webcamHud.classList.remove("hidden");
      // Small delay to ensure display:flex is applied before animation
      requestAnimationFrame(() => {
        webcamHud.classList.add("visible");
        if (btnWebcam) btnWebcam.classList.add("active");
      });
    } catch (e) {
      console.error("[Webcam] Access denied or error:", e);
      showError("Không thể truy cập Webcam, thưa Ngài.");
    }
  } else {
    webcamHud.classList.remove("visible");
    if (btnWebcam) btnWebcam.classList.remove("active");
    if (webcamOverlay) webcamOverlay.style.display = "none";
    setTimeout(() => {
      webcamHud.classList.add("hidden");
      if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
        webcamVideo.srcObject = null;
      }
    }, 800); // Match CSS transition
  }
}

// Chụp ảnh hiện tại trên thẻ video và gửi trả về server
function captureAndSendWebcamFrame() {
  if (webcamOverlay) webcamOverlay.style.display = "none";
  if (!webcamVideo || !webcamStream) {
    socket.send({ type: "webcam_capture_response", image: "ERROR:NO_STREAM" });
    return;
  }

  try {
    const canvas = document.createElement("canvas");
    canvas.width = webcamVideo.videoWidth || 640;
    canvas.height = webcamVideo.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.drawImage(webcamVideo, 0, 0, canvas.width, canvas.height);
      // Chuyển sang dạng JPEG chất lượng cao
      const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
      const base64Data = dataUrl.split(",")[1];
      socket.send({ type: "webcam_capture_response", image: base64Data });
      console.log("[Webcam] Frame captured and sent successfully via WebSocket.");
    } else {
      socket.send({ type: "webcam_capture_response", image: "ERROR:CANVAS_CONTEXT_FAIL" });
    }
  } catch (err) {
    console.error("[Webcam] Error capturing frame:", err);
    socket.send({ type: "webcam_capture_response", image: `ERROR:${err}` });
  }
}

// ---------------------------------------------------------------------------
// Init components
// ---------------------------------------------------------------------------

const canvas = document.getElementById("orb-canvas") as HTMLCanvasElement;
// Off until the first message: the welcome layer greets an empty screen (spec 2026-10-16)
const orb = createOrb(canvas, { enabled: false });

// Orb on/off button (top-right controls). Off = no drawing at all and the WebGL context goes back to the GPU. Locked while the
// welcome layer shows; the first message turns the orb on.
const btnOrb = document.getElementById("btn-orb-toggle") as HTMLButtonElement;
btnOrb.disabled = true;
btnOrb.classList.add("orb-off"); // the icon follows this class: off at load
btnOrb.setAttribute("aria-pressed", "false");
btnOrb.title = "Bật orb";
const welcome = mountWelcome(() => {
  btnOrb.disabled = false;
  btnOrb.classList.remove("orb-off");
  btnOrb.setAttribute("aria-pressed", "true");
  btnOrb.title = "Tắt orb (ngừng vẽ, trả GPU)";
  orb.setEnabled(true);
});
btnOrb.addEventListener("click", () => {
  const turnOn = btnOrb.classList.contains("orb-off");
  orb.setEnabled(turnOn);
  btnOrb.classList.toggle("orb-off", !turnOn);
  btnOrb.setAttribute("aria-pressed", String(turnOn));
  btnOrb.title = turnOn ? "Tắt orb (ngừng vẽ, trả GPU)" : "Bật orb";
});

// Something covers the screen (settings, media): stop the orb and every decorative loop together.
const pauseScene = () => { orb.pause(); setAnimPaused(true); };
const resumeScene = () => { orb.resume(); setAnimPaused(false); };

const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${wsProto}//${window.location.host}/ws/voice`;
const socket = createSocket(WS_URL);

const audioPlayer = createAudioPlayer();
orb.setAnalyser(audioPlayer.getAnalyser());

// What the last call showed: transition(), the mic button and the mic's own state change all call updateStatus for one press, so a call that
// would change nothing (same state, text, listening and busy flags) is skipped instead of repeating the work and the log line.
let lastStatusKey = "";

function updateStatus(state: State, message?: string) {
  // Determine if we should show "listening"
  const isCurrentlyListening = voiceInput.isListening();
  const canListen = isCurrentlyListening && document.activeElement !== commandInput;

  const labels: Record<State, string> = {
    idle: canListen ? "Đang nghe…" : "Sẵn sàng",
    listening: "Đang nghe…",
    thinking: "Đang nghĩ…",
    working: "Đang làm việc…",
    speaking: "Đang đọc…",
    restarting: "Đang khởi động lại…",
  };

  const newText = message || labels[state];
  const key = `${state}|${message ?? ""}|${canListen}|${isBusy}`;
  if (key === lastStatusKey && statusEl.textContent === newText) return;
  lastStatusKey = key;

  console.log(`[UI] updateStatus: state=${state}, message=${message}, canListen=${canListen}, isBusy=${isBusy}`);

  // Track the type of work for the "speaking" state fallback
  if (state === "thinking" || state === "working") {
    lastWorkState = state;
    lastWorkMessage = message;
  }

  if (statusEl.textContent !== newText) {
    statusEl.textContent = newText;
  }
}



function updateInputControls(state: State) {
  const inner = document.getElementById("command-bar-inner");
  if (!inner) return;
  const busy = state === "thinking" || state === "working" || state === "speaking" || audioPlayer.isPlaying();
  if (busy) {
    inner.classList.add("busy");
  } else {
    inner.classList.remove("busy");
  }
}

function transition(newState: State, message?: string) {
  let effectiveState = newState;
  if (newState === "idle" && !isMuted && !audioPlayer.isPlaying()) {
    effectiveState = "listening";
  }

  if (effectiveState === currentState && !message) return;
  currentState = effectiveState;
  orb.setState(effectiveState as OrbState);
  window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: effectiveState }));

  // Update class for CSS styling (e.g., color changes)
  statusEl.className = `status-${effectiveState}`;

  updateStatus(effectiveState, message);
  updateInputControls(effectiveState);

  switch (effectiveState) {
    case "listening":
      if (!isMuted && document.activeElement !== commandInput) {
        voiceInput.resume();
      }
      break;
    case "idle":
      voiceInput.pause();
      break;
    case "thinking":
    case "working":
    case "speaking":
      voiceInput.pause();
      break;
  }
}

// ---------------------------------------------------------------------------
// Voice input
// ---------------------------------------------------------------------------

const voiceInput = createVoiceInput(
  (text: string) => {
    const cleanedTranscript = text.trim().toLowerCase();
    const currentSpeakingLower = (activeAssistantText || "").toLowerCase();

    // Text Matching Filter: Avoid self-interruption if transcript matches Jarvis's own TTS output
    const isSelfEcho = currentSpeakingLower.length > 5 && (
      currentSpeakingLower.includes(cleanedTranscript) ||
      cleanedTranscript.includes(currentSpeakingLower)
    );

    if ((isSpeaking || audioPlayer.isPlaying()) && !isSelfEcho) {
      console.log("[voice] Natural Interruption: User spoke during playback ->", text);
      audioPlayer.stop();
      isSpeaking = false;
      isBusy = false;

      // Notify backend to cancel current response stream
      socket.send({ type: "cancel" });
      closeAssistantBubble(); // a cancelled turn gets neither stream_end nor idle from the backend
      ttsOpen = speechPreparing = false; // nor, with the socket gone, its TTS idle

      // Immediately process user's new spoken query
      addChatMessage("user", text);
      addToCommandHistory(text);
      if (deliverTranscript(text)) transition("thinking");
    } else if (isSpeaking || audioPlayer.isPlaying() || isBusy || currentState === "thinking" || currentState === "working") {
      const bubble = addChatMessage("user", text);
      if (bubble) bubble.classList.add("pending");
      pendingQueriesQueue.push({ type: "voice", text, bubbleElement: bubble || undefined });
      console.log("[voice] Jarvis is busy/speaking. Enqueued query:", text);
    } else {
      // Cancel any current JARVIS response before sending new input
      audioPlayer.stop();
      // User spoke — send transcript
      addChatMessage("user", text);
      addToCommandHistory(text); // Sync voice to command bar history
      if (deliverTranscript(text)) transition("thinking");
    }
  },
  (msg: string) => {
    showError(msg);
  },
  () => {
    // the recognizer ended 6 times in a row without hearing anything: the mic is stopped, switch its button off too
    showError("Mic không nghe được gì nên đã tắt. Bấm nút mic để bật lại.");
    if (!isMuted) btnMute.click();
  }
);

// Wire up microphone status change to UI update
voiceInput.onStatusChange(() => {
  console.log("[voice] microphone state changed:", voiceInput.isListening());
  updateStatus(currentState);
});

// ---------------------------------------------------------------------------
// Audio playback finished
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Barge-in detector — ngắt JARVIS ngay khi phát hiện người dùng bắt đầu nói,
// không chờ STT (Web Speech API / Whisper) trả về transcript cuối cùng. STT
// vẫn chạy song song như cũ để biết NÓI GÌ; detector này chỉ lo việc NGẮT LỜI
// càng sớm càng tốt bằng cách theo dõi năng lượng mic độc lập.
// ---------------------------------------------------------------------------

const interruptDetector = createInterruptDetector(() => {
  if (!(isSpeaking || audioPlayer.isPlaying())) return; // an toàn, tránh kích hoạt thừa
  console.log("[voice] Barge-in detected — stopping playback and cancelling response");
  audioPlayer.stop();
  isSpeaking = false;
  isBusy = false;
  socket.send({ type: "cancel" });
  closeAssistantBubble(); // a cancelled turn gets neither stream_end nor idle from the backend
  ttsOpen = speechPreparing = false; // nor, with the socket gone, its TTS idle
  transition("listening");
});

audioPlayer.onStarted(() => {
  isSpeaking = true;
  speechPreparing = false;
  if (currentState !== "speaking") {
    transition("speaking");
  } else {
    updateStatus("speaking"); // "Đang chuẩn bị…" (TTS still synthesising) → "Đang đọc…" now the sound is out
  }
  if (!isMuted) {
    interruptDetector.start();
  }
});

audioPlayer.onFinished(() => {
  isSpeaking = false;
  speechPreparing = false;
  interruptDetector.stop();

  if (pendingQueriesQueue.length > 0) {
    const nextQuery = pendingQueriesQueue.shift()!;
    console.log("[queue] Processing next enqueued query:", nextQuery.text);
    if (nextQuery.bubbleElement) {
      nextQuery.bubbleElement.classList.remove("pending");
    }
    if (nextQuery.type === "text" && nextQuery.file) {
      uploadAndSend(nextQuery.text, nextQuery.file);
    } else {
      socket.send({ type: "transcript", text: nextQuery.text, isFinal: true });
      addToCommandHistory(nextQuery.text);
      transition("thinking");
    }
  } else if (isTtsDisabled) {
    isBusy = false;
    transition("idle");
  } else {
    afterSpeech();
  }
});

// ---------------------------------------------------------------------------
// WebSocket messages
// ---------------------------------------------------------------------------

socket.onMessage((msg) => {
  const type = msg.type as string;
  // ?debug=1 only (perf-debug.ts sets the array): every packet except audio data, with the wall clock, to compare with jarvis.log
  (window as unknown as { __wsEvents?: object[] }).__wsEvents?.push({ at: Date.now(), type, state: msg.state, source: msg.source, message: msg.message });

  if (type === "audio" || type === "text") dropEmptyAssistantBubble();
  if (type === "audio") {
    const audioData = msg.data as string;
    console.log("[audio] received", audioData ? `${audioData.length} chars` : "EMPTY", "state:", currentState);
    if (isTtsDisabled) return;
    if (audioData) {
      // isSpeaking/transition("speaking") is driven by audioPlayer.onStarted()
      // instead of here — it only fires once real playback begins, so stale
      // audio for an already-cancelled turn can't force the UI into a
      // "speaking" state that never actually plays anything.
      audioPlayer.enqueue(audioData);
    } else {
      // TTS failed — no audio but still need to return to idle
      console.warn("[audio] no data received, returning to idle");
      isSpeaking = false;
      transition("idle");
    }
    // Log text for debugging and show in UI if provided
    if (msg.text) {
      console.log("[JARVIS]", msg.text);
      if (!wasStreamed) {
        addChatMessage("assistant", msg.text as string);
      }
    }
  } else if (type === "stream_start") {
    closeAssistantBubble(); // the previous turn was cancelled without a stream_end: do not leave its loader spinning
    wasStreamed = false;
    isStreamActive = true;
    isBubbleFinalRendered = false;
    activeAssistantText = "";
    island.resetFlow();
    currentTurnId = Date.now().toString();

    // 2. Tạo bong bóng chat cho phản hồi của Assistant (LLM)
    activeAssistantBubble = document.createElement("div");
    activeAssistantBubble.className = "chat-bubble assistant";
    showStreamLoader(activeAssistantBubble); // loader until the first text (stream-loader.ts)
    chatHistory.appendChild(activeAssistantBubble);

    startStreamTypewriter();
    requestAnimationFrame(() => scrollToBottomIfNeeded(true)); // Force scroll when new stream starts
  } else if (type === "text_chunk") {
    const chunkText = msg.text as string;
    if (chunkText && activeAssistantBubble) {
      if (activeAssistantBubble.classList.contains("typing-loader")) {
        clearStreamLoader(activeAssistantBubble);
        streamHoldUntil = performance.now() + STREAM_TEXT_AFTER_LOADER_MS;
        if (!activeAssistantBubble.querySelector(".bubble-text")) {
          const textContainer = document.createElement("div");
          textContainer.className = "bubble-text";
          activeAssistantBubble.appendChild(textContainer);
        }
      }
      isBubbleFinalRendered = false;
      activeAssistantText += chunkText;
      streamTargetText = activeAssistantText; // Feed typewriter target buffer
      wakeStreamTypewriter();
    }
  } else if (type === "audio_chunk") {
    const chunkBase64 = msg.data as string;
    if (!chunkBase64) return;
    if (isTtsDisabled) return;
    // isSpeaking/transition("speaking") driven by audioPlayer.onStarted() —
    // this only buffers raw bytes; real playback starts at audio_chunk_end.
    const binary = atob(chunkBase64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    if (!audioChunkBuffer) {
      audioChunkBuffer = [];
    }
    audioChunkBuffer.push(bytes);
  } else if (type === "pcm_chunk") {
    // VieNeu: phát ngay từng đoạn PCM, tách khỏi nhánh edge (audio_chunk) ở trên.
    const pcmBase64 = msg.data as string;
    if (!pcmBase64 || isTtsDisabled) return;
    audioPlayer.enqueuePcm(pcmBase64, (msg.sample_rate as number) || 48000, (msg.gap_ms as number) || 0);
  } else if (type === "audio_chunk_end") {
    if (!isTtsDisabled && audioChunkBuffer && audioChunkBuffer.length > 0) {
      const totalLen = audioChunkBuffer.reduce((sum, b) => sum + b.length, 0);
      const combined = new Uint8Array(totalLen);
      let offset = 0;
      for (const b of audioChunkBuffer) {
        combined.set(b, offset);
        offset += b.length;
      }
      audioChunkBuffer = null;
      audioPlayer.enqueueRaw(combined.buffer);
    } else {
      audioChunkBuffer = null;
    }
  } else if (type === "stream_end") {
    wasStreamed = true;
    isStreamActive = false;
    closeAssistantBubble(); // the bubble only: the status label follows the status packets
    // The flow steps that arrive after stream_end still go to the island (island.flowStep).
  } else if (type === "status") {
    const state = msg.state as string;
    const message = msg.message as string;
    if (msg.source === "tts" && isTtsDisabled) return;
    if (state === "thinking" || state === "working") {
      isBusy = true;
      if (speechPreparing || isSpeaking) { lastWorkState = state; lastWorkMessage = message; return; } // shown when the speech ends
      if (currentState !== state) {
        transition(state as State, message);
      } else {
        updateStatus(state as State, message);
      }
    } else if (state === "idle") {
      if (msg.source === "tts") {
        // the turn's VoiceStreamer stopped (one per turn; greeting and @rag have their own): the speech is over, not
        // necessarily the turn, so only the LLM's idle (no source) clears isBusy
        ttsOpen = speechPreparing = false;
        if (!audioPlayer.isPlaying() && !isSpeaking) afterSpeech();
        return;
      }
      // the LLM is done and sends nothing more (loop.run_loop, before stream_end and the TTS; server.py sends it again at the
      // end): its working/thinking end now, straight to idle. A reading label on screen is the TTS's own state, set by its own
      // packets (sound playing, a sentence being prepared, a pause between two sentences): that stays until the TTS's idle
      isBusy = false;
      if (currentState !== "speaking") transition("idle");
    } else if (state === "speaking") {
      if (msg.source === "tts") { ttsOpen = true; if (!isSpeaking) speechPreparing = true; } // voice_streamer.py, at each sentence
      if (currentState !== "speaking") {
        transition("speaking", message);
      } else {
        updateStatus("speaking", message);
      }
    }
  } else if (type === "text") {
    // Text fallback when TTS fails
    console.log("[JARVIS]", msg.text);
    if (!wasStreamed || (msg.text as string).startsWith("💡")) {
      addChatMessage("assistant", msg.text as string);
    }
  } else if (type === "media_open") {
    const query = msg.query as string;
    const embedUrl = msg.embed_url as string;
    const title = msg.title as string;
    if (embedUrl) {
      const sep = embedUrl.includes('?') ? '&' : '?';
      const html = `<iframe src="${escapeHtml(`${embedUrl}${sep}autoplay=1`)}" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen scrolling="no"></iframe>`;
      openMediaPlayer(title || query, html);
    }
  } else if (type === "webcam_capture_request") {
    captureAndSendWebcamFrame();
  } else if (type === "webcam_processed") {
    const imgB64 = msg.image as string;
    if (imgB64 && webcamOverlay) {
      webcamOverlay.src = "data:image/jpeg;base64," + imgB64;
      webcamOverlay.style.display = "block";
      setTimeout(() => {
        if (webcamOverlay.style.display === "block") {
          webcamOverlay.style.display = "none";
        }
      }, 4000);
    }
  } else if (type === "screenshot_processed") {
    let url = (msg.url as string) || "";
    if (url) {
      if (!url.includes("?")) {
        url = `${url}?t=${Date.now()}`;
      }
      handleInteractiveCardData({
        id: `screenshot_${currentTurnId}_${Date.now()}`,
        type: "image_result",
        name: "Ảnh chụp màn hình",
        url
      });
    }
  } else if (type === "output_file") {
    // Ảnh upscale: ảnh nằm trong câu trả lời, nút tải bản gốc trên góc ảnh.
    // Tài liệu Office: thẻ tệp (icon Word/Excel/PDF + tên + loại · dung lượng + nút tải).
    const kind = msg.kind === "image" ? "image" : "document";
    if (kind === "image") {
      const url = (msg.url as string) || "";
      if (url) {
        handleInteractiveCardData({
          id: `output_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          type: "image_result",
          name: (msg.name as string) || "tệp",
          url,
          downloadUrl: (msg.download_url as string) || url,
        });
      }
    } else {
      handleInteractiveCardData({
        id: `output_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        type: "file",
        kind,
        name: (msg.name as string) || "tệp",
        ext: (msg.ext as string) || "",
        label: (msg.label as string) || "",
        caption: (msg.caption as string) || "",
        url: (msg.url as string) || "",
        downloadUrl: (msg.download_url as string) || "",
        size: typeof msg.size === "number" ? msg.size : null,
      });
    }
  } else if (type === "interactive") {
    const cardData = (msg as any).card;
    handleInteractiveCardData(cardData);
  } else if (type === "flow_step") {
    const step = msg.step as any;
    if (step && step.id) island.flowStep(step);
  } else if (type === "welcome") {
    welcome.update(msg as unknown as WelcomeData);
  } else if (type === "memory_updated") {
    console.log("[UI] Memory updated");
  }
});

// ---------------------------------------------------------------------------
// Kick off
// ---------------------------------------------------------------------------

// Ngăn ngừa các lỗi tự động zoom/pinch-to-zoom gây lệch tọa độ canvas/Orb trên mobile
(() => {
  let lastTouchEnd = 0;
  document.addEventListener("touchend", (e) => {
    const now = Date.now();
    if (now - lastTouchEnd <= 300) {
      e.preventDefault();
    }
    lastTouchEnd = now;
  }, { passive: false });

  document.addEventListener("gesturestart", (e) => {
    e.preventDefault();
  });
})();

// Start listening after a brief delay for the orb to render
setTimeout(() => {
  // Initialize mute state visually
  btnMute.classList.toggle("muted", isMuted);
  btnTtsToggle.classList.toggle("muted", isTtsDisabled);

  if (!isMuted) {
    voiceInput.start();
    transition("listening");
  } else {
    voiceInput.pause();
    transition("idle");
  }

  toggleCommandBar(true); // Always show command bar by default
  updateScrollFade(); // Initial check
}, 1000);



// The audio context is started when it is needed, not on the first tap anywhere: sending the first chat message and pressing the mic
// button (both user gestures, which iOS needs) call audioPlayer.unlock(), and the player starts it itself when TTS is about to be read.
// A context that is already running is skipped.
if (new URLSearchParams(location.search).has("debug")) {
  void import("./perf-debug").then((m) => m.mountPerfDebug(audioPlayer.getAnalyser().context as AudioContext));
}

// ---------------------------------------------------------------------------
// UI Controls
// ---------------------------------------------------------------------------

const btnMute = document.getElementById("btn-mute")!;
const btnTtsToggle = document.getElementById("btn-tts-toggle")!;

btnMute.addEventListener("click", (e) => {
  e.stopPropagation();
  void audioPlayer.unlock(); // pressing the mic is a user gesture too (someone who only talks never sends a chat)
  isMuted = !isMuted;
  btnMute.classList.toggle("muted", isMuted);
  btnMute.classList.toggle("active", !isMuted);
  if (isMuted) {
    voiceInput.stop(); // the user switched the mic off (not a pause: the audio player may suspend now)
    interruptDetector.stop();
    if (currentState === "listening" || currentState === "idle") {
      transition("idle");
    }
  } else {
    voiceInput.start();
    if (isSpeaking || audioPlayer.isPlaying()) {
      interruptDetector.start();
    }
    if (currentState === "idle") {
      transition("listening");
    }
  }
  updateStatus(currentState);
});

btnTtsToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  isTtsDisabled = !isTtsDisabled;
  localStorage.setItem("jarvis_tts_disabled", isTtsDisabled ? "true" : "false");
  btnTtsToggle.classList.toggle("muted", isTtsDisabled);
  socket.send({ type: "toggle_tts", enabled: !isTtsDisabled });
  if (isTtsDisabled) {
    isBusy = false;
    isSpeaking = false;
    audioPlayer.stop();
    audioChunkBuffer = null;
    transition("idle");
  }
  console.log("[TTS] Toggled TTS. Disabled:", isTtsDisabled);
});

// Top-right controls: Direct Settings button (no dropdown menu)
// Global copy button for code blocks & image lightbox in chat bubbles
document.addEventListener("click", (e) => {
  const copyBtn = (e.target as HTMLElement).closest(".sd-copy-btn") as HTMLButtonElement | null;
  if (copyBtn) {
    const block = copyBtn.closest(".sd-code-block");
    const codeEl = block?.querySelector("code");
    if (codeEl) {
      void navigator.clipboard.writeText(codeEl.textContent || "");
      const orig = copyBtn.textContent;
      copyBtn.textContent = "Đã chép!";
      setTimeout(() => { copyBtn.textContent = orig; }, 1500);
    }
    return;
  }

  const img = (e.target as HTMLElement).closest(".chat-bubble img") as HTMLImageElement | null;
  if (img && img.src) {
    openImageLightbox(img.src);
  }
});

// Top-left controls
const btnWebcamToggle = document.getElementById("btn-webcam-toggle")!;
btnWebcamToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  const isVisible = webcamHud.classList.contains("visible");
  toggleWebcam(!isVisible);
});

// Restart status tracking — the WebSocket reconnecting to the new worker is
// the "restart succeeded" signal (mirrors the Telegram restart-notice flow),
// so "restarting..." is cleared the moment the new server accepts the socket.
let restartPending = false;
// Loading the models takes a while; 30s was shorter than a normal start (and than the WebSocket's own
// backoff, 1+2+4+8+16s), so a healthy restart was reported as failed.
const RESTART_RETURN_TIMEOUT_MS = 90000;
const RESTART_POLL_MS = 2000;
let restartPoll = 0;

export async function triggerRestart(): Promise<void> {
  restartPending = true;
  currentState = "restarting";
  statusEl.textContent = "Đang khởi động lại…";
  statusEl.className = "status-restarting";
  try {
    await fetchWithTimeout("/api/restart", { method: "POST" });
  } catch {
    restartPending = false;
    transition("idle");
    statusEl.textContent = "Khởi động lại thất bại";
    return;
  }
  // Thử nối lại mỗi 2s thay vì chờ nhịp lùi dần của WebSocket (tối đa 30s giữa hai lần).
  clearInterval(restartPoll);
  restartPoll = window.setInterval(() => socket.retryNow(), RESTART_POLL_MS);
  // Nếu server không quay lại kịp, đừng để UI kẹt mãi ở "restarting...".
  setTimeout(() => {
    if (restartPending) {
      restartPending = false;
      clearInterval(restartPoll);
      transition("idle");
      statusEl.textContent = "Khởi động lại thất bại (server không phản hồi)";
    }
  }, RESTART_RETURN_TIMEOUT_MS);
}

// the Settings Restart button (settings/index.ts) dispatches this; a second document-level click handler used to restart twice
window.addEventListener("jarvis:restart", () => {
  void triggerRestart();
});

socket.onReconnect(() => {
  if (restartPending) {
    restartPending = false;
    clearInterval(restartPoll);
    // Worker mới đã lên → xóa "restarting...".
    transition("idle");
  }
});

// Mount settings container early so it is ready for clicks
ensureMounted();

// First-time setup detection — check after a short delay for server readiness
setTimeout(() => {
  checkFirstTimeSetup();
}, 2000);

// ---------------------------------------------------------------------------
// Command Bar
// ---------------------------------------------------------------------------

// Command Bar controls
const cmdSend = document.getElementById("cmd-send") as HTMLButtonElement;
const btnCmdBar = document.getElementById("btn-cmd-bar")!;
const btnUpload = document.getElementById("btn-upload") as HTMLButtonElement;
const fileUploadInput = document.getElementById("file-upload") as HTMLInputElement;

let cmdBarVisible = false;
let cmdHistory: string[] = [];
let cmdHistoryIdx = -1;

function addToCommandHistory(text: string) {
  if (!text) return;
  // Remove duplicate if it exists to bring it to top
  cmdHistory = cmdHistory.filter(h => h !== text);
  cmdHistory.unshift(text);
  if (cmdHistory.length > 30) cmdHistory.pop();
  cmdHistoryIdx = -1;
}

function toggleCommandBar(forceShow?: boolean) {
  cmdBarVisible = forceShow !== undefined ? forceShow : !cmdBarVisible;
  const commandContainer = document.getElementById("command-container")!;

  commandContainer.classList.toggle("visible", cmdBarVisible);
  btnCmdBar.classList.toggle("active", cmdBarVisible);
  setBarHidden(!cmdBarVisible); // the bar only fades out: stop its send-button shader and halo too
  if (cmdBarVisible) {
    // the caret goes into the bar on a PC only: on a touch phone (Capacitor app, Safari) a scripted focus pops the keyboard,
    // at launch too; there it comes up when the user taps the input (2026-10-18). Checked in the timeout: this first runs
    // during start-up, before enterMakesNewLine is declared.
    setTimeout(() => { if (!enterMakesNewLine) commandInput.focus(); }, 50);
  } else {
    commandInput.blur();
  }
}

async function uploadAndSend(text: string, file: File) {
  if (currentState === "idle" || currentState === "listening") {
    transition("thinking", `Đang tải ${file.name}…`);
  }
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetchWithTimeout("/api/upload", { method: "POST", body: formData }, UPLOAD_FETCH_TIMEOUT_MS);
    const data = await res.json();

    if (data.success) {
      socket.send({
        type: "transcript",
        text,
        attachmentId: data.attachment_id,
        isFinal: true
      });
    } else {
      showError(`Upload failed: ${data.error}`);
      if (currentState === "thinking") {
        transition("idle");
      }
    }
  } catch (e) {
    showError("Upload failed due to a network error.");
    if (currentState === "thinking") {
      transition("idle");
    }
  }
}

function deliverTranscript(text: string): boolean {
  if (socket.send({ type: "transcript", text, isFinal: true })) return true;
  // The socket used to swallow this silently while the caller went on to
  // transition("thinking"), leaving the UI spinning forever on a message the
  // server never received.
  addChatMessage("assistant", "⚠️ Mất kết nối tới máy chủ — tin nhắn chưa gửi được, đang thử kết nối lại.");
  transition("idle");
  return false;
}

/** Touch screens: after sending, drop the focus so the on-screen keyboard goes away and the main screen is back (desktop keeps the caret in the box). */
function dismissKeyboardOnMobile() {
  commandInput.blur();
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  document.body.scrollTop = 0;
  document.documentElement.scrollTop = 0;
}

async function sendCommand() {
  const text = commandInput.value.trim();
  if (!text && !pendingFile) return;
  void audioPlayer.unlock(); // the first chat is a user gesture: start the audio context now so the TTS reply can play (skipped when running)

  // Clear input immediately for responsiveness; desktop keeps the caret focused, a phone drops the keyboard
  commandInput.value = "";
  adjustInputHeight(); // back to one line
  if (enterMakesNewLine) dismissKeyboardOnMobile();
  else commandInput.focus();

  // Trigger hiệu ứng morphicons: máy bay giấy -> Check (đã gửi) -> quay lại máy bay giấy
  cmdSend.classList.add("sent");
  setTimeout(() => {
    cmdSend.classList.remove("sent");
  }, 1000);

  if (isSpeaking || audioPlayer.isPlaying() || isBusy || currentState === "thinking" || currentState === "working") {
    const bubble = addChatMessage("user", pendingFile ? `📎 [${pendingFile.name}] ${text}` : text);
    if (bubble) bubble.classList.add("pending");
    pendingQueriesQueue.push({ type: "text", text, file: pendingFile || undefined, bubbleElement: bubble || undefined });
    clearPendingFile();
    console.log("[command] Jarvis is busy/speaking. Enqueued query:", text);
    return;
  }

  if (pendingFile) {
    const file = pendingFile;
    clearPendingFile(); // Hide chip

    // Show as user message with file icon
    addChatMessage("user", `📎 [${file.name}] ${text}`);
    uploadAndSend(text, file);
  } else {
    // Standard text message
    addChatMessage("user", text);
    if (deliverTranscript(text) && (currentState === "idle" || currentState === "listening")) {
      transition("thinking");
    }
  }

  // Save to history
  addToCommandHistory(text);
}

function clearPendingFile() {
  pendingFile = null;
  fileUploadInput.value = "";
  filePinnedContainer.style.display = "none";
}

// Shortcut: Ctrl+K
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "k") {
    e.preventDefault();
    toggleCommandBar();
  }
});

// Toggle button
btnCmdBar.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleCommandBar();
});

btnUpload.addEventListener("click", (e) => {
  e.stopPropagation();
  fileUploadInput.click();
});

fileUploadInput.addEventListener("change", () => {
  if (fileUploadInput.files && fileUploadInput.files.length > 0) {
    pendingFile = fileUploadInput.files[0];
    filePinnedName.textContent = pendingFile.name;
    filePinnedContainer.style.display = "flex";
    commandInput.focus();
  }
});

btnFileRemove.addEventListener("click", (e) => {
  e.stopPropagation();
  clearPendingFile();
});

// The input's height: one line (line-height + padding, so any text scale fits) while empty or one line long, taller as lines are
// added up to 140px. An empty box never measures scrollHeight: that would count a wrapped placeholder as content and make the
// whole command bar jump up when the user deletes everything.
function inputBaseHeight(): number {
  const cs = getComputedStyle(commandInput);
  return parseFloat(cs.lineHeight) + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
}

function adjustInputHeight() {
  const base = inputBaseHeight();
  commandInput.style.height = `${base}px`;
  if (!commandInput.value) return;
  const h = commandInput.scrollHeight;
  if (h > base + 1) commandInput.style.height = `${Math.min(h, 140)}px`;
}

// The placeholder is always one line: it is cut with "…" to the width of the box (a phone is narrower than the full hint) and
// the full text stays in aria-label. Re-fitted when the box or its font changes size (rotation, text scale, fonts loading).
const FULL_PLACEHOLDER = commandInput.placeholder;
const placeholderProbe = document.createElement("canvas").getContext("2d")!;
function fitPlaceholder() {
  const cs = getComputedStyle(commandInput);
  const avail = commandInput.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  if (avail <= 0) return;
  placeholderProbe.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  const fits = (t: string) => placeholderProbe.measureText(t).width <= avail;
  let text = FULL_PLACEHOLDER;
  if (!fits(text)) {
    let lo = 0, hi = FULL_PLACEHOLDER.length;
    while (lo < hi) { // longest prefix that still fits with the ellipsis
      const mid = (lo + hi + 1) >> 1;
      if (fits(FULL_PLACEHOLDER.slice(0, mid).trimEnd() + "…")) lo = mid; else hi = mid - 1;
    }
    text = FULL_PLACEHOLDER.slice(0, lo).trimEnd() + "…";
  }
  if (commandInput.placeholder !== text) commandInput.placeholder = text;
  commandInput.setAttribute("aria-label", FULL_PLACEHOLDER);
}
new ResizeObserver(fitPlaceholder).observe(commandInput);
void document.fonts.ready.then(fitPlaceholder);
fitPlaceholder();

// ---------------------------------------------------------------------------
// Suggestions Autocomplete Logic
// ---------------------------------------------------------------------------
let suggestCommands: any[] = [];
let suggestMentions: { name: string; description: string }[] = [];  // chế độ + tool, sinh từ registry ở backend
let suggestFiles: string[] = [];
let suggestActiveIndex = -1;
let suggestFilteredList: any[] = [];
let suggestType: "/" | "@" | null = null;
let suggestActiveTab = "all";
const commandSuggestEl = document.getElementById("command-suggest")!;

// Prevent the command input from blurring (and hiding the panel via the blur
// handler) when the user clicks inside the suggestion panel, e.g. switching tabs.
commandSuggestEl.addEventListener("mousedown", (e) => {
  e.preventDefault();
});

async function fetchSuggestionsData() {
  try {
    const resSkills = await fetchWithTimeout("/api/command-bar/skills");
    const dataSkills = await resSkills.json();
    if (dataSkills.success) {
      suggestCommands = dataSkills.commands || [];
    }
    const resCtx = await fetchWithTimeout("/api/command-bar/context");
    const dataCtx = await resCtx.json();
    if (dataCtx.success) {
      suggestMentions = dataCtx.mentions || [];
      suggestFiles = dataCtx.files || [];
    }
  } catch (e) {
    console.error("[Suggestions] Failed to fetch suggestions data:", e);
  }
}

function getActiveToken(input: HTMLTextAreaElement) {
  const value = input.value;
  const selStart = input.selectionStart || 0;

  // Find start of current token (separated by whitespace)
  let start = selStart - 1;
  while (start >= 0 && !/\s/.test(value[start])) {
    start--;
  }
  start++;

  const token = value.slice(start, selStart);
  return { token, start, end: selStart };
}

function renderSuggestions(type: "/" | "@", filterText: string) {
  commandSuggestEl.innerHTML = "";
  suggestFilteredList = [];
  const q = filterText.toLowerCase();

  // Render Tabs Header
  const tabsContainer = document.createElement("div");
  tabsContainer.className = "suggest-tabs";

  // "/" và "@" đều lấy tên tool từ registry backend (engine/tools/catalog), không viết tay ở đây.
  const tabs = type === "/"
    ? [{ id: "all", label: "Lệnh" }]
    : [
      { id: "all", label: "Tất cả" },
      { id: "feature", label: "Tính năng" },
      { id: "file", label: "Tệp tin" }
    ];

  tabs.forEach(t => {
    const tabEl = document.createElement("span");
    tabEl.className = "suggest-tab" + (suggestActiveTab === t.id ? " active" : "");
    tabEl.textContent = t.label;
    tabEl.addEventListener("click", (e) => {
      e.stopPropagation();
      suggestActiveTab = t.id;
      suggestActiveIndex = 0;
      renderSuggestions(type, filterText);
    });
    tabsContainer.appendChild(tabEl);
  });
  commandSuggestEl.appendChild(tabsContainer);

  if (type === "/") {
    const filteredCmds = suggestCommands
      .filter(c => c.name.toLowerCase().includes(q) || (c.description || "").toLowerCase().includes(q))
      .map(c => ({ name: "/" + c.name, desc: c.description || "", tabType: "command", icon: "⚡" }));
    const combined = filteredCmds;

    // De-duplicate by name
    const seen = new Set<string>();
    for (const item of combined) {
      if (!seen.has(item.name)) {
        seen.add(item.name);
        if (suggestActiveTab === "all" || item.tabType === suggestActiveTab) {
          suggestFilteredList.push({ ...item, type: "command" });
        }
      }
    }
  } else if (type === "@") {
    const filteredMentions = suggestMentions
      .filter(m => m.name.toLowerCase().includes(q) || (m.description || "").toLowerCase().includes(q))
      .map(m => ({ name: "@" + m.name, desc: m.description || "", tabType: "feature", type: "feature", icon: "✨" }));
    const filteredFiles = suggestFiles
      .filter(f => f.toLowerCase().includes(q))
      .map(f => ({ name: "@" + f, desc: f, tabType: "file", type: "file", icon: "📄" }));

    for (const item of [...filteredMentions, ...filteredFiles]) {
      if (suggestActiveTab === "all" || item.tabType === suggestActiveTab) {
        suggestFilteredList.push(item);
      }
    }
  }

  if (suggestFilteredList.length === 0) {
    // If no filtered items, we still show the tabs header but show an empty state
    const emptyEl = document.createElement("div");
    emptyEl.className = "suggest-empty";
    emptyEl.textContent = "Không tìm thấy kết quả phù hợp.";
    commandSuggestEl.appendChild(emptyEl);
    commandSuggestEl.classList.remove("hidden");
    return;
  }

  // Ensure index is within range
  if (suggestActiveIndex >= suggestFilteredList.length) {
    suggestActiveIndex = suggestFilteredList.length - 1;
  }
  if (suggestActiveIndex < 0 && suggestFilteredList.length > 0) {
    suggestActiveIndex = 0;
  }

  // Render items
  suggestFilteredList.forEach((item, index) => {
    const el = document.createElement("div");
    el.className = "suggest-item" + (index === suggestActiveIndex ? " active" : "");
    el.innerHTML = `
      <div class="suggest-item-left">
        <span class="suggest-item-icon">${item.icon}</span>
        <span class="suggest-item-name">${item.name}</span>
      </div>
      <span class="suggest-item-desc" title="${item.desc}">${item.desc}</span>
    `;

    el.addEventListener("click", () => {
      selectSuggestion(item.name);
    });

    commandSuggestEl.appendChild(el);
  });

  commandSuggestEl.classList.remove("hidden");
}

function selectSuggestion(selectedValue: string) {
  const { start, end } = getActiveToken(commandInput);
  const val = commandInput.value;

  // Replace the token with selected value
  commandInput.value = val.slice(0, start) + selectedValue + " " + val.slice(end);
  const newCursorPos = start + selectedValue.length + 1;
  commandInput.setSelectionRange(newCursorPos, newCursorPos);

  hideSuggestions();
  commandInput.focus();
  adjustInputHeight();
}

function hideSuggestions() {
  commandSuggestEl.classList.add("hidden");
  suggestType = null;
  suggestActiveIndex = -1;
  suggestFilteredList = [];
}

// Adjust height as user types and update suggestions
commandInput.addEventListener("input", () => {
  adjustInputHeight();

  const { token } = getActiveToken(commandInput);
  if (token.startsWith("/") || token.startsWith("@")) {
    const newType = token[0] as "/" | "@";
    if (newType !== suggestType) {
      suggestActiveTab = "all";
      suggestActiveIndex = 0;
    }
    suggestType = newType;
    const filterText = token.slice(1);
    renderSuggestions(suggestType, filterText);
  } else {
    hideSuggestions();
  }
});

// Phone keyboards have no Shift+Enter: there Enter starts a new line and the send button sends. Desktop: Enter sends, Shift+Enter new line.
const enterMakesNewLine = matchMedia("(pointer: coarse)").matches;
commandInput.enterKeyHint = enterMakesNewLine ? "enter" : "send";
if (enterMakesNewLine) cmdSend.title = "Gửi";

// Send on Enter, history on Up/Down, navigation in suggestions
commandInput.addEventListener("keydown", (e) => {
  // Navigation in suggestions dropdown if open
  if (!commandSuggestEl.classList.contains("hidden") && suggestFilteredList.length > 0) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      suggestActiveIndex = (suggestActiveIndex + 1) % suggestFilteredList.length;
      renderSuggestions(suggestType!, getActiveToken(commandInput).token.slice(1));
      return;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      suggestActiveIndex = (suggestActiveIndex - 1 + suggestFilteredList.length) % suggestFilteredList.length;
      renderSuggestions(suggestType!, getActiveToken(commandInput).token.slice(1));
      return;
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (suggestActiveIndex >= 0 && suggestActiveIndex < suggestFilteredList.length) {
        selectSuggestion(suggestFilteredList[suggestActiveIndex].name);
      }
      return;
    } else if (e.key === "Escape") {
      e.preventDefault();
      hideSuggestions();
      return;
    }
  }

  if (e.key === "Enter" && !e.shiftKey && !enterMakesNewLine) {
    e.preventDefault();
    sendCommand();
  } else if (e.key === "Escape") {
    toggleCommandBar(false);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (cmdHistory.length > 0) {
      cmdHistoryIdx = Math.min(cmdHistoryIdx + 1, cmdHistory.length - 1);
      commandInput.value = cmdHistory[cmdHistoryIdx];
      commandInput.setSelectionRange(commandInput.value.length, commandInput.value.length);
      adjustInputHeight();
    }
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    cmdHistoryIdx = Math.max(cmdHistoryIdx - 1, -1);
    commandInput.value = cmdHistoryIdx >= 0 ? cmdHistory[cmdHistoryIdx] : "";
    adjustInputHeight();
  }
});

// Send button click
cmdSend.addEventListener("click", () => {
  sendCommand();
});
cmdSend.addEventListener("mousedown", (e) => {
  e.preventDefault();
});

// Auto-mute when input is focused or clicked and prefetch suggestions
commandInput.addEventListener("focus", () => {
  voiceInput.pause();
  fetchSuggestionsData(); // prefetch skills and files list
});

commandInput.addEventListener("mousedown", (e) => {
  e.stopPropagation();
  voiceInput.pause();
});

commandInput.addEventListener("blur", () => {
  // Hide suggestions with delay to allow clicks
  setTimeout(() => {
    hideSuggestions();
  }, 200);

  // Resume if not muted and not busy
  if (!isMuted && !isBusy) {
    voiceInput.resume();
    if (currentState === "idle") {
      transition("listening");
    }
  }
});

// Ctrl+K global shortcut to focus command bar
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "k") {
    e.preventDefault();
    toggleCommandBar(true);
  }
});

// ---------------------------------------------------------------------------
// Media Player
// ---------------------------------------------------------------------------

const mediaPlayer = document.getElementById("media-player")!;
const mediaPlayerInner = document.getElementById("media-player-inner")!;

const closeMediaPlayer = function () {
  mediaPlayer.classList.add("hidden");
  document.body.classList.remove("media-playing");
  mediaPlayerInner.innerHTML = "";
  resumeScene();
  socket.send({ type: "media_state", active: false });
  // Khôi phục trạng thái nếu không còn phát audio
  if (!audioPlayer.isPlaying()) {
    transition("idle");
  }
}

// Settings phủ toàn màn hình: tạm dừng orb. Khi đóng chỉ chạy lại hết nếu trình phát media không còn mở.
window.addEventListener("jarvis:overlay", (event) => {
  const { open } = (event as CustomEvent<{ open: boolean }>).detail;
  document.getElementById("controls")?.classList.toggle("hidden", open);
  if (open) {
    pauseScene();
    return;
  }
  const mediaOpen = !mediaPlayer.classList.contains("hidden");
  if (mediaOpen) setAnimPaused(false); // a video is open: the big orb stays paused, the small orb and the avatar run again
  else resumeScene();
});

// Phones are portrait only: on its side a phone shows style.css's full-screen "Xoay dọc" cover, so everything behind it stops like
// under Settings. Rotating back wakes the page only if nothing else (Settings, a video) still covers it.
const sideways = matchMedia("(orientation: landscape) and (max-height: 500px) and (pointer: coarse)");
sideways.addEventListener("change", () => {
  if (sideways.matches) { pauseScene(); return; }
  if (document.getElementById("settings-container")?.classList.contains("open")) return;
  if (!mediaPlayer.classList.contains("hidden")) setAnimPaused(false);
  else resumeScene();
});
if (sideways.matches) pauseScene();

function openMediaPlayer(title: string, embedHtml: string) {
  document.body.classList.add("media-playing");
  orb.pause(); // only the big WebGL orb: the status orb and the avatar stay visible next to the video and keep animating
  socket.send({ type: "media_state", active: true });
  // Server chỉ chặn TTS mới; audio đã xếp lịch trong trình duyệt phải dừng ngay, không đọc chồng lên media.
  audioPlayer.stop();
  audioChunkBuffer = null;

  // Luồng Youtube/Phim dạng Iframe/HTML5 video
  mediaPlayerInner.innerHTML = `
    <div style="position:absolute;top:10px;left:12px;font-size:var(--fs-label);letter-spacing:2px;color:rgba(0,212,255,0.5);z-index:5;text-transform:uppercase">${escapeHtml(title || "NOW PLAYING")}</div>
    <div class="media-player-close" id="btn-close-media-player">&#10005;</div>
    ${embedHtml}
  `;

  mediaPlayer.classList.remove("hidden");
  document.getElementById("btn-close-media-player")?.addEventListener("click", closeMediaPlayer);
}

// Đóng trình phát khi bấm nút Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!mediaPlayer.classList.contains("hidden")) {
      closeMediaPlayer();
    }
  }
});

