/**
 * JARVIS — Main entry point.
 *
 * Wires together the orb visualization, WebSocket communication,
 * speech recognition, and audio playback into a single experience.
 */

import { createOrb, type OrbState } from "./orb";
import { createVoiceInput, createAudioPlayer, createInterruptDetector } from "./voice";
import { createSocket } from "./ws";
import { openSettings, checkFirstTimeSetup, ensureMounted } from "./settings/index";
import { formatMarkdown } from "./markdown";
import { escapeHtml } from "./settings/api";
import "./style.css";
import { mountBot } from "./bot";
import { showStreamLoader, clearStreamLoader } from "./stream-loader";
import { mountClock } from "./clock";
import { mountControlsMenu } from "./controls-menu";
import { mountViewportReset } from "./viewport-reset";
import { mountNotifyIsland } from "./notify-island";
import { mountStatusOrb } from "./status-orb";
import { mountStatusLabel, mountStatusRowFade } from "./status-label";
import { mountMetalRing } from "./metal-ring";
import { setAnimPaused, setBarHidden } from "./anim-gate";

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
let lastStreamRenderAt = 0;
let streamTail: Text | null = null; // last text node of the rendered stream: plain chunks are appended to it
let streamPendingFull = false; // a full markdown render was skipped (throttle) and is still owed
let streamDirty = false; // plain chunks were appended since the last full render
let streamHeld = false; // the last full render left out newlines at the very end of the text (they wait for the next letter)
let streamLastAppendAt = 0;
let streamHoldUntil = 0; // the typewriter waits for this time: the loader balls shrink first so they do not cover the first letter
let wasStreamed = false;
let audioChunkBuffer: Uint8Array[] | null = null;
// Tải bản gốc upscale: chờ gắn nút icon ⬇ vào bong bóng phản hồi cuối lượt
// (stream_end), thay vì vẽ rời gây trùng lặp.
let pendingDownload: { name: string; url: string } | null = null;

const chatHistory = document.getElementById("chat-history")!;
const statusEl = document.getElementById("status-text")!;
const island = mountNotifyIsland(document.getElementById("error-text")!); // flow tracker + system errors (notify-island.ts)
mountBot(document.getElementById("command-bar-inner")!);
mountClock();
mountViewportReset();
mountControlsMenu(document.getElementById("controls")!, document.getElementById("btn-controls") as HTMLButtonElement);
mountStatusOrb(document.getElementById("status-orb")!);
mountStatusLabel(document.getElementById("status-row")!, statusEl);
mountStatusRowFade(document.getElementById("status-row")!, statusEl);
mountMetalRing(document.getElementById("cmd-send-wrap")!);
initChatAutoCeiling();
const commandInput = document.getElementById("command-input") as HTMLTextAreaElement;
const filePinnedContainer = document.getElementById("file-pinned-container")!;
const filePinnedName = document.getElementById("file-pinned-name")!;
const btnFileRemove = document.getElementById("btn-file-remove")!;
let userHasScrolledUp = false;

/**
 * Tự động đo và điều chỉnh trần (maxHeight) của #chat-history theo thời gian thực:
 * - Dừng ngay dưới mép của thành phần thấp nhất đang hiển thị ở đỉnh (Đồng hồ, Media Player, Webcam HUD).
 * - Trên mobile: co xuống dưới mép Media Player hoặc Webcam HUD khi chúng mở.
 * - Thích ứng chính xác với mọi kích thước / tỉ lệ màn hình (iPhone SE, Pro Max, Android...).
 * - Hoàn toàn không can thiệp vào bàn phím ảo, để hệ điều hành đẩy giao diện tự nhiên.
 */
function initChatAutoCeiling(): void {
  const clockEl = document.getElementById("jarvis-clock");
  const mediaEl = document.getElementById("media-player");
  const webcamEl = document.getElementById("webcam-hud");
  const isPhone = () => matchMedia("(max-width: 768px)").matches;
  const GAP = 18; // Cách đáy đồng hồ/media/webcam 14px (thụt xuống dưới thêm 6px để không bị sát)
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
    if (clockEl) {
      const cb = clockEl.getBoundingClientRect().bottom;
      if (cb > 0) topCeiling = Math.max(topCeiling, cb);
    }

    const bottom = chatHistory.getBoundingClientRect().bottom;
    const available = bottom - topCeiling - GAP;
    if (available > 0) {
      chatHistory.style.maxHeight = `${Math.max(MIN_HEIGHT, Math.floor(available))}px`;
    }
  };

  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(updateCeiling);
  };

  window.addEventListener("resize", schedule);
  const mo = new MutationObserver(schedule);
  if (mediaEl) mo.observe(mediaEl, { attributes: true, attributeFilter: ["class"] });
  if (webcamEl) mo.observe(webcamEl, { attributes: true, attributeFilter: ["class"] });
  if (clockEl) new ResizeObserver(schedule).observe(clockEl);
  updateCeiling();
}

function updateScrollFade() {
  if (!chatHistory) return;
  // Check if we are within 10px of the bottom
  const isAtBottom = Math.abs(chatHistory.scrollHeight - chatHistory.clientHeight - chatHistory.scrollTop) < 10;
  chatHistory.classList.toggle("at-bottom", isAtBottom);
  chatHistory.classList.toggle("overflowing", chatHistory.scrollHeight > chatHistory.clientHeight + 1);

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

// characters that can change how markdown renders (emphasis, code, lists, headings, links, tables, entities)
const STREAM_MARKUP = /[*_`#\[\]()<>&|~=\\\n\-\d!]/;

function lastTextNode(el: HTMLElement): Text | null {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let last: Text | null = null;
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const t = n as Text;
    if (!t.textContent?.trim() && t.parentNode === el) continue;
    last = t;
  }
  return last;
}

/** The last text node, but only when nothing (a <br>, a block) follows it: letters appended to it must land at the very end. */
function tailAtEnd(el: HTMLElement): Text | null {
  const t = lastTextNode(el);
  if (!t) return null;
  for (let n: Node = t; n !== el; n = n.parentNode!) {
    let next = n.nextSibling;
    while (next && next.nodeType === Node.TEXT_NODE && !next.textContent?.trim()) {
      next = next.nextSibling;
    }
    if (next) return null;
  }
  return t;
}

/** Newlines at the very end of the streamed text are not shown yet: they would open blank lines under the last line before the
 *  next paragraph has a single letter, and the letters would then jump to where the blank lines are. They appear with the next letter. */
const withoutTrailingNewlines = (s: string) => s.replace(/\n+$/, "");

/**
 * Shows the newly revealed `chunk`. Re-parsing all the markdown and rewriting innerHTML every frame re-lays
 * out the whole bubble (and cost grew with the square of the reply length), which read as jitter. So a chunk
 * of plain text is just appended to the last text node; anything that may change the markup, a newline, or
 * the settle after a pause does the full render (throttled as the text grows).
 */
function renderStreamText(container: HTMLElement, chunk: string, now: number, final = false) {
  if (!final && !streamPendingFull && !streamHeld && streamTail?.isConnected && !STREAM_MARKUP.test(chunk)) {
    streamTail.appendData(chunk);
    streamDirty = true;
    return;
  }
  const gap = streamTextBuffer.length > 2000 ? 100 : streamTextBuffer.length > 500 ? 50 : 0;
  if (!final && now - lastStreamRenderAt < gap) { streamPendingFull = true; return; }
  lastStreamRenderAt = now;
  streamPendingFull = streamDirty = false;
  const shown = withoutTrailingNewlines(streamTextBuffer);
  streamHeld = shown.length < streamTextBuffer.length;
  container.innerHTML = formatMarkdown(shown, { isBubble: true });
  streamTail = tailAtEnd(container);
}

let typeAcc = 0; // characters owed to the reader (fractional)
let typePrev = 0;

/** New turn: empty buffers. The loop itself only starts with the first text_chunk (wakeStreamTypewriter). */
function startStreamTypewriter() {
  stopStreamTypewriter();
  streamTextBuffer = "";
  streamTargetText = "";
  lastStreamRenderAt = 0;
  streamTail = null;
  streamPendingFull = streamDirty = streamHeld = false;
  streamHoldUntil = 0;
  typeAcc = 0;
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
    if (!streamPendingFull && !streamDirty) return; // all shown and settled: stop
    // caught up and quiet for a moment: one full render fixes any markdown the plain appends skipped, then stop
    if (now - streamLastAppendAt > 150) { renderStreamText(textContainer, "", now, true); scrollToBottomIfNeeded(); return; }
    return again();
  }

  typeAcc += Math.max(STREAM_BASE_CPS, backlog / STREAM_CATCHUP_S) * dt;
  const take = Math.min(backlog, Math.floor(typeAcc));
  if (take > 0) {
    typeAcc -= take;
    const chunk = streamTargetText.slice(streamTextBuffer.length, streamTextBuffer.length + take);
    streamTextBuffer += chunk;
    streamLastAppendAt = now;
    renderStreamText(textContainer, chunk, now);
    scrollToBottomIfNeeded();
  }
  again();
}

function stopStreamTypewriter() {
  if (streamTypewriterTimer) {
    cancelAnimationFrame(streamTypewriterTimer);
    streamTypewriterTimer = null;
  }
  // Flush whatever the typewriter had not caught up to yet. It only ever
  // cleared the timer, so anything still queued when the stream ended was
  // simply never shown — and throttling the repaint widens that window.
  if (
    activeAssistantBubble &&
    streamTargetText &&
    !streamTargetText.startsWith("[INTERACTIVE_CARD_JSON]:") &&
    streamTextBuffer.length < streamTargetText.length
  ) {
    const textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement | null;
    if (textContainer) {
      streamTextBuffer = streamTargetText;
      textContainer.innerHTML = formatMarkdown(withoutTrailingNewlines(streamTextBuffer), { isBubble: true });
      scrollToBottomIfNeeded();
    }
  }
}

/** server.py's error fallback sends one "audio"/"text" packet and no stream_end: a bubble still waiting for its first letter
 *  would keep its loader forever, and the fallback text gets its own bubble anyway. */
function dropEmptyAssistantBubble(): void {
  if (!activeAssistantBubble || activeAssistantText) return;
  stopStreamTypewriter();
  activeAssistantBubble.remove();
  activeAssistantBubble = null;
}

/** Ends the assistant bubble of the current turn: stops the typewriter, removes the loader, renders the full text.
 *  stream_end calls it; so do our own cancel and the next stream_start, because a cancelled turn (engine/turn/loop.py out.abort())
 *  gets neither stream_end nor idle, otherwise the goo loader and the typewriter loop kept running in the chat history. */
function closeAssistantBubble(): void {
  stopStreamTypewriter();
  if (activeAssistantBubble) {
    if (activeAssistantBubble.classList.contains("typing-loader")) {
      clearStreamLoader(activeAssistantBubble, true);
    }
    activeAssistantBubble.querySelectorAll(".stream-bubble-host, .sl-defs").forEach((el) => el.remove());
    [...activeAssistantBubble.childNodes].forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) node.remove();
    });
    let textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement;
    if (!textContainer) {
      textContainer = document.createElement("div");
      textContainer.className = "bubble-text";
      activeAssistantBubble.appendChild(textContainer);
    }
    textContainer.innerHTML = formatMarkdown(withoutTrailingNewlines(activeAssistantText), { isBubble: true });
    // Nút icon ⬇ tải bản gốc upscale: gắn vào chính bong bóng phản hồi cuối
    // lượt (câu trả lời đã ghi tên tệp), không vẽ rời gây trùng lặp.
    if (pendingDownload) {
      const download = document.createElement("a");
      download.className = "icon-btn";
      download.href = pendingDownload.url;
      download.setAttribute("download", pendingDownload.name);
      download.title = `Tải về ${pendingDownload.name}`;
      download.textContent = "⬇";
      textContainer.appendChild(download);
      pendingDownload = null;
    }
    scrollToBottomIfNeeded();
  }
  activeAssistantBubble = null;
}

let pendingFile: File | null = null;

export { formatMarkdown };


function addChatMessage(role: "user" | "assistant", text: string): HTMLElement | null {
  console.log(`[UI] Adding ${role} message: ${text}`);
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

  // Mark existing messages as 'old'
  const oldBubbles = chatHistory.querySelectorAll(".chat-bubble");
  oldBubbles.forEach((m) => m.classList.add("old"));

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
    // Hiệu ứng stream gõ chữ cho assistant
    let currentText = "";
    // Sử dụng regex để tách từ nhưng giữ nguyên các dấu xuống dòng và khoảng trắng
    const tokens = text.split(/(\s+)/);
    let i = 0;

    const timer = setInterval(() => {
      if (i < tokens.length) {
        currentText += tokens[i];
        bubble.innerHTML = formatMarkdown(currentText, { isBubble: true });
        i++;

        // Tự động cuộn xuống dưới
        scrollToBottomIfNeeded();
      } else {
        clearInterval(timer);
      }
    }, 15); // Tốc độ tối ưu cho token
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

  if (data.type === "select") {
    const list = document.createElement("div");
    list.className = "interactive-select-list";

    const selectedValues = new Set<string>();

    data.options.forEach((opt: any) => {
      const optionEl = document.createElement("div");
      optionEl.className = "interactive-option";
      if (opt.selected) {
        optionEl.classList.add("selected");
        selectedValues.add(opt.value);
      }

      const dot = document.createElement("span");
      dot.className = "interactive-option-dot";
      optionEl.appendChild(dot);

      const label = document.createElement("span");
      label.textContent = opt.label;
      optionEl.appendChild(label);

      optionEl.addEventListener("click", () => {
        if (data.multiple) {
          if (selectedValues.has(opt.value)) {
            selectedValues.delete(opt.value);
            optionEl.classList.remove("selected");
          } else {
            selectedValues.add(opt.value);
            optionEl.classList.add("selected");
          }
        } else {
          list.querySelectorAll(".interactive-option").forEach(el => el.classList.remove("selected"));
          selectedValues.clear();
          selectedValues.add(opt.value);
          optionEl.classList.add("selected");
          submitBtn.disabled = false;
          submitBtn.textContent = data.submitLabel || "Xác nhận";
        }
      });

      list.appendChild(optionEl);
    });

    card.appendChild(list);

    const btnGroup = document.createElement("div");
    btnGroup.className = "interactive-btn-group";

    const submitBtn = document.createElement("button");
    submitBtn.className = "interactive-btn approve";
    submitBtn.textContent = data.submitLabel || "Xác nhận";
    submitBtn.addEventListener("click", () => {
      submitBtn.disabled = true;
      socket.send({
        type: "interactive_response",
        cardId: data.id,
        action: "submit",
        value: Array.from(selectedValues)
      });
      submitBtn.textContent = "Đã gửi";
    });

    btnGroup.appendChild(submitBtn);
    card.appendChild(btnGroup);

  } else if (data.type === "input") {
    if (data.description) {
      const desc = document.createElement("div");
      desc.className = "interactive-input-description";
      desc.textContent = data.description;
      card.appendChild(desc);
    }

    const input = document.createElement("textarea");
    input.className = "interactive-text-input";
    input.value = typeof data.value === "string" ? data.value : "";
    input.placeholder = data.placeholder || "Nhập nội dung...";
    input.rows = 4;
    input.setAttribute("aria-label", data.title || "Nhập nội dung");
    card.appendChild(input);

    const btnGroup = document.createElement("div");
    btnGroup.className = "interactive-btn-group";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "interactive-btn reject";
    cancelBtn.textContent = data.cancelLabel || "Hủy";
    const submitBtn = document.createElement("button");
    submitBtn.className = "interactive-btn approve";
    submitBtn.textContent = data.submitLabel || "Xác nhận nội dung";

    const lock = () => {
      input.disabled = true;
      cancelBtn.disabled = true;
      submitBtn.disabled = true;
    };
    cancelBtn.addEventListener("click", () => {
      lock();
      socket.send({ type: "interactive_response", cardId: data.id, action: "cancel" });
      cancelBtn.textContent = "Đã hủy";
    });
    submitBtn.addEventListener("click", () => {
      lock();
      socket.send({
        type: "interactive_response", cardId: data.id, action: "submit", value: input.value
      });
      submitBtn.textContent = "Đã gửi";
    });
    btnGroup.appendChild(cancelBtn);
    btnGroup.appendChild(submitBtn);
    card.appendChild(btnGroup);

  } else if (data.type === "approve") {
    if (data.description) {
      const desc = document.createElement("div");
      desc.className = "interactive-card-desc";
      desc.textContent = data.description;
      card.appendChild(desc);
    }

    const btnGroup = document.createElement("div");
    btnGroup.className = "interactive-btn-group";

    const rejectBtn = document.createElement("button");
    rejectBtn.className = "interactive-btn reject";
    rejectBtn.textContent = data.rejectLabel || "Từ chối";

    const approveBtn = document.createElement("button");
    approveBtn.className = "interactive-btn approve";
    approveBtn.textContent = data.approveLabel || "Đồng ý";

    rejectBtn.addEventListener("click", () => {
      rejectBtn.disabled = true;
      approveBtn.disabled = true;
      socket.send({
        type: "interactive_response",
        cardId: data.id,
        action: "reject"
      });
      rejectBtn.textContent = "Đã từ chối";
    });

    approveBtn.addEventListener("click", () => {
      rejectBtn.disabled = true;
      approveBtn.disabled = true;
      socket.send({
        type: "interactive_response",
        cardId: data.id,
        action: "approve"
      });
      approveBtn.textContent = "Đã đồng ý";
    });

    btnGroup.appendChild(rejectBtn);
    btnGroup.appendChild(approveBtn);
    card.appendChild(btnGroup);

  } else if (data.type === "image_result") {
    // Khung xem trước thuần túy: chỉ mỗi ảnh, không khung thẻ (bong bóng chat
    // đã là một khung), không chữ, không nút, không lớp thêm.
    if (data.url) {
      const img = document.createElement("img");
      img.className = "image-result-preview";
      img.src = data.url;
      img.alt = data.name || "ảnh";
      img.addEventListener("click", () => openImageLightbox(img.src));
      img.addEventListener("load", () => scrollToBottomIfNeeded());
      card.appendChild(img);
    }
  } else if (data.type === "file") {
    // Thẻ tài liệu Office: icon Word/Excel/PowerPoint/PDF + tên tệp + nút
    // Tải về trỏ tới /api/outputs/{token}?download=1. Ảnh không qua đây nữa:
    // ảnh upscale hiện cùng thẻ tracker với ảnh chụp màn hình (nhánh trên).
    card.classList.add("file-card");

    const row = document.createElement("div");
    row.className = "file-row";

    const icon = document.createElement("span");
    icon.className = "file-icon";
    icon.innerHTML = officeFileIconSvg(data.ext, data.label);
    row.appendChild(icon);

    const meta = document.createElement("div");
    meta.className = "file-meta";
    const nameEl = document.createElement("div");
    nameEl.className = "file-name";
    nameEl.textContent = data.name || "tệp";
    nameEl.title = data.name || "";
    meta.appendChild(nameEl);
    const caption = (data.caption || "").trim();
    if (caption) {
      const captionEl = document.createElement("div");
      captionEl.className = "file-caption";
      captionEl.textContent = caption;
      captionEl.title = caption;
      meta.appendChild(captionEl);
    }
    row.appendChild(meta);

    const download = document.createElement("a");
    download.className = "file-download";
    download.href = data.downloadUrl || data.url || "#";
    download.setAttribute("download", data.name || "tệp");
    download.textContent = "⬇ Tải về";
    row.appendChild(download);

    card.appendChild(row);
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
const webcamCanvas = document.getElementById("webcam-canvas") as HTMLCanvasElement;
const webcamOverlay = document.getElementById("webcam-overlay") as HTMLImageElement;
const webcamSelect = document.getElementById("webcam-device-select") as HTMLSelectElement;
let webcamStream: MediaStream | null = null;
let selectedCameraId: string | null = null;

let handLandmarker: any = null;
let handDetectionActive = false;
let isInitializingHandLandmarker = false;

async function initHandLandmarker() {
  if (handLandmarker) return handLandmarker;
  if (isInitializingHandLandmarker) return null;
  isInitializingHandLandmarker = true;
  try {
    console.log("[MediaPipe] Initializing Hand Landmarker...");
    const { FilesetResolver, HandLandmarker } =
      await import("@mediapipe/tasks-vision");
    const vision = await FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.8/wasm"
    );
    handLandmarker = await HandLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        delegate: "GPU"
      },
      runningMode: "VIDEO",
      numHands: 2
    });
    console.log("[MediaPipe] Hand Landmarker initialized successfully!");
    isInitializingHandLandmarker = false;
    return handLandmarker;
  } catch (err) {
    console.error("[MediaPipe] Failed to initialize Hand Landmarker:", err);
    isInitializingHandLandmarker = false;
    return null;
  }
}

// Releases the GPU-backed WASM model so its VRAM isn't held while the webcam is off.
function disposeHandLandmarker() {
  if (handLandmarker) {
    try {
      handLandmarker.close();
    } catch (err) {
      console.error("[MediaPipe] Failed to close Hand Landmarker:", err);
    }
    handLandmarker = null;
  }
}

function predictWebcamHands() {
  if (!handDetectionActive || !webcamStream || !webcamVideo || !handLandmarker || !webcamCanvas) {
    return;
  }

  const ctx = webcamCanvas.getContext("2d");
  if (!ctx) return;

  // Cập nhật kích thước canvas khớp với video thực tế
  webcamCanvas.width = webcamVideo.videoWidth || 640;
  webcamCanvas.height = webcamVideo.videoHeight || 480;

  ctx.clearRect(0, 0, webcamCanvas.width, webcamCanvas.height);

  if (webcamVideo.readyState >= 2 && webcamVideo.currentTime !== -1) {
    const startTimeMs = performance.now();
    try {
      const results = handLandmarker.detectForVideo(webcamVideo, startTimeMs);
      if (results && results.landmarks && results.landmarks.length > 0) {
        for (const landmarks of results.landmarks) {
          const tips = [4, 8, 12, 16, 20];
          for (const tipIdx of tips) {
            const lm = landmarks[tipIdx];
            if (lm) {
              const cx = lm.x * webcamCanvas.width;
              const cy = lm.y * webcamCanvas.height;

              // Vòng phát sáng neon mờ xung quanh (glow)
              ctx.beginPath();
              ctx.arc(cx, cy, tipIdx === 8 ? 10 : 7, 0, 2 * Math.PI);
              ctx.fillStyle = "rgba(0, 212, 255, 0.35)";
              ctx.fill();

              // Điểm nhân màu trắng rực rỡ
              ctx.beginPath();
              ctx.arc(cx, cy, tipIdx === 8 ? 4 : 3, 0, 2 * Math.PI);
              ctx.fillStyle = "#ffffff";
              ctx.fill();

              // Viền ngoài sắc nét
              ctx.beginPath();
              ctx.arc(cx, cy, tipIdx === 8 ? 13 : 9, 0, 2 * Math.PI);
              ctx.strokeStyle = "rgba(0, 212, 255, 0.8)";
              ctx.lineWidth = 1.5;
              ctx.stroke();
            }
          }
        }
      }
    } catch (err) {
      console.error("[MediaPipe] Detection error:", err);
    }
  }

  if (handDetectionActive) {
    requestAnimationFrame(predictWebcamHands);
  }
}

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

    // Khởi chạy nhận diện bàn tay thời gian thực
    handDetectionActive = true;
    initHandLandmarker().then((landmarker) => {
      if (landmarker && handDetectionActive) {
        requestAnimationFrame(predictWebcamHands);
      }
    });
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
    handDetectionActive = false;
    if (webcamCanvas) {
      const ctx = webcamCanvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, webcamCanvas.width, webcamCanvas.height);
    }
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
      disposeHandLandmarker();
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
const orb = createOrb(canvas);

// Orb on/off button (top-right controls). Off = no drawing at all and the WebGL context goes back to the GPU; always on at page load.
const btnOrb = document.getElementById("btn-orb-toggle")!;
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
    pendingDownload = null;
    activeAssistantText = "";
    island.resetFlow();
    currentTurnId = Date.now().toString();

    // Mark existing messages as 'old'
    const oldBubbles = chatHistory.querySelectorAll(".chat-bubble");
    oldBubbles.forEach((m) => m.classList.add("old"));

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
      const activeId = (window as any)._activeScreenshotTrackerId || `screenshot_tracker_${currentTurnId}_${Date.now()}`;
      handleInteractiveCardData({
        id: activeId,
        type: "image_result",
        name: "Ảnh chụp màn hình",
        url
      });
      // Reset ID
      delete (window as any)._activeScreenshotTrackerId;
    }
  } else if (type === "output_file") {
    // Ảnh upscale: chỉ vẽ khung xem trước thuần túy (không chữ, không nút).
    // Nút icon ⬇ tải bản gốc chờ gắn vào bong bóng phản hồi cuối lượt.
    // Tài liệu Office hiện thẻ tệp có icon Word/Excel/PDF (hàng tên + Tải về).
    const kind = msg.kind === "image" ? "image" : "document";
    if (kind === "image") {
      const url = (msg.url as string) || "";
      if (url) {
        handleInteractiveCardData({
          id: `output_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          type: "image_result",
          name: (msg.name as string) || "tệp",
          url,
        });
        pendingDownload = {
          name: (msg.name as string) || "tệp",
          url: (msg.download_url as string) || url,
        };
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
      });
    }
  } else if (type === "interactive") {
    const cardData = (msg as any).card;
    handleInteractiveCardData(cardData);
  } else if (type === "flow_step") {
    const step = msg.step as any;
    if (step && step.id) island.flowStep(step);
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
const btnSettings = document.getElementById("btn-settings");
if (btnSettings) {
  btnSettings.addEventListener("click", (e) => {
    e.stopPropagation();
    openSettings();
  });
}

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
  setBarHidden(!cmdBarVisible); // the bar only fades out: stop its bot, send-button shader and halo too
  if (cmdBarVisible) {
    setTimeout(() => commandInput.focus(), 50);
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

