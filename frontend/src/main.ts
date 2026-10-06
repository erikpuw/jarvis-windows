/**
 * JARVIS — Main entry point.
 *
 * Wires together the orb visualization, WebSocket communication,
 * speech recognition, and audio playback into a single experience.
 */

import { createOrb, type OrbState } from "./orb";
import { createVoiceInput, createAudioPlayer, createInterruptDetector } from "./voice";
import { createSocket } from "./ws";
import { openSettings, checkFirstTimeSetup } from "./settings/index";
import "./style.css";
import { setStatusIcon, agentBadge } from "./icons";
import { mountBot } from "./bot";
import { showStreamLoader, clearStreamLoader } from "./stream-loader";
import { mountEdgeAura } from "./edge-aura";
import { mountClock } from "./clock";
import { mountStatusOrb } from "./status-orb";
import { mountStatusLabel } from "./status-label";
import { mountMetalRing } from "./metal-ring";
import { setAnimPaused } from "./anim-gate";

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
let isSpeaking = false;
let pendingQueriesQueue: { type: "voice" | "text", text: string, file?: File, bubbleElement?: HTMLElement }[] = [];

let activeAssistantBubble: HTMLElement | null = null;
let activeFlowBubble: HTMLElement | null = null;
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
let wasStreamed = false;
let audioChunkBuffer: Uint8Array[] | null = null;

const chatHistory = document.getElementById("chat-history")!;
const statusEl = document.getElementById("status-text")!;
const errorEl = document.getElementById("error-text")!;
mountBot(document.getElementById("command-bar-inner")!);
mountEdgeAura(document.getElementById("command-bar-inner")!);
mountClock();
mountStatusOrb(document.getElementById("status-orb")!);
mountStatusLabel(document.getElementById("status-row")!, statusEl);
mountMetalRing(document.getElementById("cmd-send-wrap")!);
const commandInput = document.getElementById("command-input") as HTMLTextAreaElement;
const filePinnedContainer = document.getElementById("file-pinned-container")!;
const filePinnedName = document.getElementById("file-pinned-name")!;
const btnFileRemove = document.getElementById("btn-file-remove")!;
const btnMap = document.getElementById("btn-map")!;
const mapPanel = document.getElementById("map-panel")!;
const btnCloseMap = document.getElementById("btn-close-map")!;
let mapLibreMap: any = null;
let mapMarker: any = null;
let pinnedMarkers: any[] = [];
let cachedPins: any[] = [];
let isMap3D = false;
let isMapGlobe = false;
let isMapFullScreen = false;

let userHasScrolledUp = false;

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
const STREAM_CATCHUP_S = 0.3; // otherwise drain the backlog in about this long

// characters that can change how markdown renders (emphasis, code, lists, headings, links, tables, entities)
const STREAM_MARKUP = /[*_`#\[\]()<>&|~=\\\n\-\d!]/;

function lastTextNode(el: HTMLElement): Text | null {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let last: Text | null = null;
  for (let n = w.nextNode(); n; n = w.nextNode()) last = n as Text;
  return last;
}

/** The last text node, but only when nothing (a <br>, a block) follows it: letters appended to it must land at the very end. */
function tailAtEnd(el: HTMLElement): Text | null {
  const t = lastTextNode(el);
  if (!t) return null;
  for (let n: Node = t; n !== el; n = n.parentNode!) if (n.nextSibling) return null;
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
  container.innerHTML = formatMarkdown(shown);
  streamTail = tailAtEnd(container);
}

function startStreamTypewriter() {
  stopStreamTypewriter();
  streamTextBuffer = "";
  streamTargetText = "";
  lastStreamRenderAt = 0;
  streamTail = null;
  streamPendingFull = streamDirty = streamHeld = false;
  let acc = 0; // characters owed to the reader (fractional)
  let prev = performance.now();

  const step = (now: number) => {
    streamTypewriterTimer = requestAnimationFrame(step);
    const dt = Math.min((now - prev) / 1000, 0.1);
    prev = now;
    if (!activeAssistantBubble) return;

    // Nếu text đích bắt đầu bằng prefix của Interactive Card, ta không hiển thị text thô qua typewriter
    if (streamTargetText.startsWith("[INTERACTIVE_CARD_JSON]:")) {
      return;
    }

    let textContainer = activeAssistantBubble.querySelector(".bubble-text") as HTMLElement;
    if (!textContainer) {
      textContainer = document.createElement("div");
      textContainer.className = "bubble-text";
      activeAssistantBubble.appendChild(textContainer);
    }

    const backlog = streamTargetText.length - streamTextBuffer.length;
    if (backlog <= 0) {
      acc = 0;
      // caught up and quiet for a moment: one full render fixes any markdown the plain appends skipped
      if ((streamPendingFull || streamDirty) && now - streamLastAppendAt > 150) { renderStreamText(textContainer, "", now, true); scrollToBottomIfNeeded(); }
      return;
    }

    acc += Math.max(STREAM_BASE_CPS, backlog / STREAM_CATCHUP_S) * dt;
    const take = Math.min(backlog, Math.floor(acc));
    if (take <= 0) return;
    acc -= take;
    const chunk = streamTargetText.slice(streamTextBuffer.length, streamTextBuffer.length + take);
    streamTextBuffer += chunk;
    streamLastAppendAt = now;
    renderStreamText(textContainer, chunk, now);
    scrollToBottomIfNeeded();
  };
  streamTypewriterTimer = requestAnimationFrame(step);
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
      textContainer.innerHTML = formatMarkdown(withoutTrailingNewlines(streamTextBuffer));
      scrollToBottomIfNeeded();
    }
  }
}

let pendingFile: File | null = null;

export function formatMarkdown(text: string): string {
  if (!text) return "";

  let html = text;

  // 1. Render Links: [title](url) nhưng loại trừ các trường hợp bắt đầu bằng dấu chấm than (!)
  // Sử dụng regex: (?:^|[^!])\[([^\]]+)\]\(([^)]+)\) để chỉ bắt các link thông thường
  // Đồng thời giữ nguyên tiêu đề $1 thay vì đè thành chữ 'Xem tại đây'
  html = html.replace(/(^|[^!])\[([^\]]+)\]\(([^)]+)\)/g, '$1<a href="$3" target="_blank" style="color:#0ea5e9; text-decoration:none; font-weight:600; border-bottom:1px dashed #0ea5e9; transition:all 0.2s;" onmouseover="this.style.color=\'#38bdf8\'; this.style.borderBottomColor=\'#38bdf8\'" onmouseout="this.style.color=\'#0ea5e9\'; this.style.borderBottomColor=\'#0ea5e9\'">$2</a>');

  // 2. Render Images: ![alt](url)
  html = html.replace(/!\[(.*?)\]\((.*?)\)/g, '<img src="$2" alt="$1" style="max-width:100%; max-height:300px; object-fit:contain; border-radius:8px; margin:6px 0; display:block; border:1px solid rgba(255,255,255,0.1); box-shadow:0 4px 12px rgba(0,0,0,0.25);" />');

  html = html
    .replace(/^### (.*$)/gm, '<h3 style="color:var(--accent-blue);margin:2px 0 1px 0;font-size:12px;letter-spacing:1px;text-transform:uppercase;opacity:0.8">$1</h3>')
    .replace(/^## (.*$)/gm, '<h2 style="color:var(--accent-blue);margin:4px 0 2px 0;font-size:13px;letter-spacing:0.5px">$1</h2>')
    .replace(/^# (.*$)/gm, '<h1 style="color:var(--accent-blue);margin:8px 0 4px 0;font-size:16px;letter-spacing:0.5px;font-weight:700;">$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, '<strong style="color:#fff;font-weight:600">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em style="opacity:0.9">$1</em>')
    .replace(/^[\s]*[\*\-] (.*)/gm, '<div style="display:flex;gap:4px;margin:2px 0"><span style="flex:none">•</span><span style="min-width:0">$1</span></div>')
    .replace(/^[\s]*(\d+)\. (.*)/gm, '<div style="display:flex;gap:4px;margin:2px 0"><span style="flex:none;white-space:nowrap">$1.</span><span style="min-width:0">$2</span></div>')
    .replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.1);padding:1px 3px;border-radius:4px;font-family:monospace;font-size:0.9em;color:#00d4ff">$1</code>');

  // Hỗ trợ hiển thị bảng biểu đơn giản (Parse Table)
  if (html.includes('|')) {
    const lines = html.split('\n');
    let inTable = false;
    let tableHtml = '';
    const newLines: string[] = [];

    for (let line of lines) {
      if (line.trim().startsWith('|')) {
        // Bỏ qua dòng separator ví dụ: |---|---| hoặc | :--- | :--- |
        if (line.includes('---') || line.includes(':---')) {
          continue;
        }
        const cells = line.split('|').map(c => c.trim()).filter((c, i, a) => i > 0 && i < a.length - 1);
        if (!inTable) {
          inTable = true;
          tableHtml = '<div class="table-responsive-wrapper" style="width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; margin:8px 0; border-radius:6px; border:1px solid rgba(255,255,255,0.05);">';
          tableHtml += '<style>.table-responsive-wrapper table img { max-width:120px !important; max-height:190px !important; align-items: center; object-fit:contain; border-radius:6px; margin:4px auto; display:block; border:1px solid rgba(255,255,255,0.1); box-shadow:0 2px 6px rgba(0,0,0,0.25); }</style>';
          tableHtml += '<table style="width:100%; min-width:320px; border-collapse:collapse; font-size:12px; color:#e2e8f0; background:rgba(255,255,255,0.02);">';
          tableHtml += '<tr style="background:rgba(14,165,233,0.15); font-weight:600; color:#fff; border-bottom:1px solid rgba(255,255,255,0.1);">';
          // Kiểm tra xem đây có phải bảng hàng ngang (mỗi mục một cột) hay không
          // Bằng cách xem các tiêu đề cột có chứa Poster/Hình ảnh không
          const isHorizontalTable = !cells.some(c => {
            const lc = c.toLowerCase();
            return lc.includes('poster') || lc.includes('hình ảnh') || lc.includes('nội dung') || lc.includes('tập');
          });

          cells.forEach((cell, idx) => {
            let widthStyle = '';
            if (isHorizontalTable) {
              widthStyle = 'width:150px; min-width:140px; text-align:center;';
            } else {
              // Gán style độ rộng cân đối dựa vào tiêu đề cột (bảng dọc)
              const lowerCell = cell.toLowerCase();
              if (lowerCell.includes('poster') || lowerCell.includes('hình ảnh')) {
                widthStyle = 'width:90px; min-width:90px;';
              } else if (lowerCell.includes('tên bài') || lowerCell.includes('tên sản phẩm')) {
                widthStyle = 'width:130px; min-width:120px; text-align:left;';
              } else if (lowerCell.includes('nội dung') || lowerCell.includes('nghệ sĩ') || lowerCell.includes('giá')) {
                widthStyle = 'min-width:200px; text-align:left;';
              } else if (lowerCell.includes('tập') || lowerCell.includes('thời lượng') || lowerCell.includes('nguồn')) {
                widthStyle = 'width:80px; min-width:80px; white-space:nowrap;';
              }
            }
            tableHtml += `<th style="padding:6px 8px; text-align:center; border:1px solid rgba(255,255,255,0.05); ${widthStyle}">${cell}</th>`;
          });
          tableHtml += '</tr>';
        } else {
          // Kiểm tra lại dạng bảng ngang cho các hàng dữ liệu
          const isHorizontalTable = !cells.some((c, idx) => {
            // Xem xem hàng đầu tiên (th) có chứa Poster không
            const thElements = tableHtml.match(/<th[^>]*>(.*?)<\/th>/g);
            if (thElements && thElements[idx]) {
              const thText = thElements[idx].replace(/<[^>]*>/g, '').toLowerCase();
              return thText.includes('poster') || thText.includes('nội dung') || thText.includes('tập');
            }
            return false;
          });

          tableHtml += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05); transition:background 0.2s;" onmouseover="this.style.background=\'rgba(255,255,255,0.02)\'" onmouseout="this.style.background=\'none\'">';
          cells.forEach((cell, idx) => {
            let cellContent = cell;
            let isAlignCentered = false;
            let widthStyle = '';

            // Nếu ô chứa ảnh hoặc thẻ a/link, hoặc icon 🔗, thực hiện căn giữa
            if (cell.includes('<img ') || cell.includes('<a ') || cell.includes('🔗')) {
              isAlignCentered = true;
            }

            if (isHorizontalTable) {
              widthStyle = 'width:150px; min-width:140px; text-align:center;';
              isAlignCentered = true;
            } else {
              // Đồng bộ độ rộng td tương ứng với th ở trên để tránh trình duyệt bóp méo
              if (idx === 0) { // Thường là Poster
                widthStyle = 'width:90px; min-width:90px;';
              } else if (idx === 1) { // Thường là Phim/Tên bài
                widthStyle = 'width:130px; min-width:120px; text-align:left; white-space:normal;';
                isAlignCentered = false; // Luôn căn lề trái cho dễ đọc
              } else if (idx === 2) { // Thường là Thể loại hoặc Nội dung
                const lowerCell = cells[idx] ? cells[idx].toLowerCase() : '';
                if (lowerCell.includes('thể loại')) {
                  widthStyle = 'width:100px; min-width:100px; text-align:left;';
                } else {
                  widthStyle = 'min-width:200px; text-align:left; white-space:normal;';
                }
                isAlignCentered = false;
              } else if (idx === 3) { // Thường là Tập/Thời Lượng
                widthStyle = 'width:80px; min-width:80px; white-space:nowrap;';
                isAlignCentered = true;
              } else if (idx === 4) { // Thường là Chi tiết / Link xem
                widthStyle = 'width:90px; min-width:90px; white-space:nowrap;';
                isAlignCentered = true;
              }
            }

            const alignStyle = isAlignCentered ? 'text-align:center;' : 'text-align:left;';
            tableHtml += `<td style="padding:6px 8px; border:1px solid rgba(255,255,255,0.05); vertical-align:middle; ${alignStyle} ${widthStyle}">${cellContent}</td>`;
          });
          tableHtml += '</tr>';
        }
      } else {
        if (inTable) {
          tableHtml += '</table></div>';
          newLines.push(tableHtml);
          inTable = false;
          tableHtml = '';
        }
        newLines.push(line);
      }
    }
    if (inTable) {
      tableHtml += '</table></div>';
      newLines.push(tableHtml);
    }
    html = newLines.join('\n');
  }

  // Clean up double newlines caused by div/h interaction with pre-wrap
  html = html.replace(/<\/div>\r?\n/g, '</div>');
  html = html.replace(/<\/h3>\r?\n/g, '</h3>');
  html = html.replace(/<\/h2>\r?\n/g, '</h2>');
  html = html.replace(/<\/table>\r?\n/g, '</table>');

  // Chuyển newline thành <br> để hiển thị markdown đúng cách
  html = html.replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>');

  return html;
}


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
    bubble.innerHTML = formatMarkdown(text);
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
        bubble.innerHTML = formatMarkdown(currentText);
        i++;

        // Tự động cuộn xuống dưới
        scrollToBottomIfNeeded();
      } else {
        clearInterval(timer);
      }
    }, 15); // Tốc độ tối ưu cho token
  }

  // Keep reasonable history
  while (chatHistory.children.length > 36) {
    chatHistory.removeChild(chatHistory.firstChild!);
  }

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
    closeBtn.style.cssText = "position:fixed; top:20px; right:20px; font-size:20px; color:#fff; background:rgba(8,10,18,0.7); border:1px solid rgba(0,212,255,0.3); border-radius:50%; width:44px; height:44px; display:flex; align-items:center; justify-content:center; cursor:pointer; z-index:2010; box-shadow:0 0 10px rgba(0,212,255,0.2);";
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


/** Agent step labels arrive as "Thực thi: <việc>"; the card already says it is running. */
const trackerLabel = (label?: string) => (label || "").replace(/^Thực thi:\s*/, "");

function renderInteractiveCard(container: HTMLElement, data: any) {
  const existingCard = container.querySelector(".interactive-card");
  // Tracker đổi trạng thái (active → completed/failed) là render lại cùng một card:
  // vá tại chỗ để icon trạng thái giữ nguyên phần tử và morph.
  const existingName = existingCard?.querySelector(".tracker-name");
  const existingIcon = existingCard?.querySelector(".tracker-icon-container");
  if (data.type === "tracker" && !data.image && existingIcon && !existingCard!.querySelector("img")
      && !!existingName === !!data.title) {
    existingCard!.className = `interactive-card tracker-card${data.status ? " " + data.status : ""}`;
    if (existingName) {
      existingName.textContent = agentBadge(data.title).name;
    }
    const existingLabel = existingCard!.querySelector<HTMLElement>(".tracker-label")!;
    existingLabel.textContent = trackerLabel(data.label);
    existingLabel.title = trackerLabel(data.label);
    setStatusIcon(existingIcon, data.status, "tracker", 14);
    return;
  }
  if (existingCard) existingCard.remove();
  if (data.id) {
    container.setAttribute("data-card-id", data.id);
  }
  const card = document.createElement("div");
  card.className = "interactive-card";

  // tracker cards draw their own agent header (icon + name) below
  if (data.title && data.type !== "tracker") {
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

  } else if (data.type === "tracker") {
    card.classList.add("tracker-card");
    if (data.status) {
      card.classList.add(data.status);
    }
    const body = document.createElement("div");
    body.className = "tracker-body";

    const iconContainer = document.createElement("div");
    iconContainer.className = "tracker-icon-container";

    if (data.status) setStatusIcon(iconContainer, data.status, "tracker", 14);

    const label = document.createElement("div");
    label.className = "tracker-label";
    label.textContent = trackerLabel(data.label);
    label.title = trackerLabel(data.label); // the card shows one cut line; hovering shows the whole task

    if (data.image) {
      body.style.flexDirection = "column";
      body.style.alignItems = "flex-start";

      const headerRow = document.createElement("div");
      headerRow.style.display = "flex";
      headerRow.style.alignItems = "center";
      headerRow.style.gap = "12px";
      headerRow.appendChild(iconContainer);
      headerRow.appendChild(label);

      const img = document.createElement("img");
      img.src = `${data.image}?t=${Date.now()}`;
      img.alt = "Screenshot";
      img.style.maxWidth = "100%";
      img.style.maxHeight = "300px";
      img.style.objectFit = "contain";
      img.style.borderRadius = "6px";
      img.style.marginTop = "8px";
      img.style.display = "block";
      img.style.border = "1px solid rgba(255,255,255,0.1)";
      img.style.boxShadow = "0 4px 12px rgba(0,0,0,0.25)";
      img.style.cursor = "pointer";

      img.addEventListener("click", () => {
        openImageLightbox(img.src);
      });

      img.onload = () => {
        scrollToBottomIfNeeded();
      };

      body.appendChild(headerRow);
      body.appendChild(img);
    } else if (data.title) {
      const badge = agentBadge(data.title);
      const iconBox = document.createElement("span");
      iconBox.className = "tracker-agent-icon";
      iconBox.appendChild(badge.icon);
      const texts = document.createElement("div");
      texts.className = "tracker-texts";
      const name = document.createElement("div");
      name.className = "tracker-name";
      name.textContent = badge.name;
      texts.append(name, label);
      body.append(iconBox, texts, iconContainer);
    } else {
      body.appendChild(iconContainer);
      body.appendChild(label);
    }

    card.appendChild(body);
  }

  const textContainer = container.querySelector(".bubble-text");
  if (textContainer) {
    container.insertBefore(card, textContainer);
  } else {
    container.appendChild(card);
  }
}


function showError(msg: string) {

  errorEl.textContent = msg;
  errorEl.style.opacity = "1";
  window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: "error" }));
  setTimeout(() => {
    errorEl.style.opacity = "0";
  }, 5000);
}



// System status state for chat flow
let flowSteps: any[] = [];
let currentTurnId: string = Date.now().toString();

/** "Định tuyến → general" → ["Định tuyến", "general"]; drops trailing "..." / "…". */
function splitStepLabel(label: string): [string, string] {
  const clean = (label || "").replace(/(\.{3}|…)\s*$/, "").trim();
  const i = clean.indexOf("→");
  return i < 0 ? [clean, ""] : [clean.slice(0, i).trim(), clean.slice(i + 1).trim()];
}

function updateFlowMonitor() {
  if (!activeFlowBubble || flowSteps.length === 0) return;

  // Tìm bước đang active để hiển thị ở dòng tóm tắt accordion
  const activeStep = flowSteps.find(s => s.status === 'active');
  const lastCompleted = [...flowSteps].reverse().find(s => s.status === 'completed');
  const summaryStep = activeStep || lastCompleted;
  const hasFailure = flowSteps.some(s => s.status === 'failed');

  const completedCount = flowSteps.filter(s => s.status === 'completed').length;
  const totalCount = flowSteps.length;

  const summaryStatus = activeStep ? "active" : hasFailure ? "failed" : "completed";
  const summaryLabel = summaryStep ? summaryStep.label : 'Đang xử lý...';

  // Dựng khung một lần cho mỗi bubble; các lần sau chỉ vá nội dung để icon
  // trạng thái giữ nguyên phần tử và morph (vòng xoay → ✓) thay vì bị thay mới.
  let summary = activeFlowBubble.querySelector<HTMLElement>(".flow-accordion-summary");
  if (!summary) {
    activeFlowBubble.innerHTML = `
      <div class="flow-accordion-header" onclick="this.closest('.system-flow').classList.toggle('flow-expanded')">
        <div class="flow-accordion-summary">
          <span class="flow-summary-icon" style="display:contents"></span>
          <span class="flow-summary-label"></span>
          <span class="flow-step-count"></span>
        </div>
        <svg class="flow-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:10px;height:10px;flex-shrink:0;transition:transform 0.25s ease;">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </div>
      <div class="flow-accordion-body">
        <div class="flow-content-inline"></div>
      </div>
    `;
    summary = activeFlowBubble.querySelector<HTMLElement>(".flow-accordion-summary")!;
  }
  setStatusIcon(summary.querySelector(".flow-summary-icon")!, summaryStatus, "flow", 12);
  summary.querySelector(".flow-summary-label")!.textContent = splitStepLabel(summaryLabel)[0];
  summary.querySelector(".flow-step-count")!.textContent = `${completedCount}/${totalCount}`;
  activeFlowBubble.dataset.status = summaryStatus;

  // Chi tiết tất cả các bước (hiển thị khi expand), khớp theo step.id
  const list = activeFlowBubble.querySelector(".flow-content-inline")!;
  for (const step of flowSteps) {
    let row = list.querySelector<HTMLElement>(`:scope > [data-step-id="${CSS.escape(String(step.id))}"]`);
    if (!row) {
      row = document.createElement("div");
      row.className = "flow-step-row";
      row.dataset.stepId = String(step.id);
      row.innerHTML = `<span class="flow-step-label"><span class="flow-step-text"></span><span class="flow-step-detail"></span></span>`;
      list.appendChild(row);
    }
    // timeline dot is CSS, keyed on data-status
    const [main, detail] = splitStepLabel(step.label);
    row.dataset.status = step.status;
    row.querySelector(".flow-step-text")!.textContent = main;
    row.querySelector(".flow-step-detail")!.textContent = detail;
  }

  activeFlowBubble.style.display = "block";

  // Tự động cuộn xuống dưới
  requestAnimationFrame(() => {
    scrollToBottomIfNeeded();
  });
}



// ---------------------------------------------------------------------------
// Webcam HUD Logic
// ---------------------------------------------------------------------------

const webcamHud = document.getElementById("webcam-hud")!;
const webcamVideo = document.getElementById("webcam-video") as HTMLVideoElement;
const webcamCanvas = document.getElementById("webcam-canvas") as HTMLCanvasElement;
const webcamOverlay = document.getElementById("webcam-overlay") as HTMLImageElement;
const webcamSelect = document.getElementById("webcam-device-select") as HTMLSelectElement;
const btnWebcamFullscreen = document.getElementById("btn-webcam-fullscreen");
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

if (btnWebcamFullscreen) {
  btnWebcamFullscreen.addEventListener("click", () => {
    webcamHud.classList.toggle("full-view");
    btnWebcamFullscreen.classList.toggle("active");
  });
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
    webcamHud.classList.remove("full-view");
    if (btnWebcam) btnWebcam.classList.remove("active");
    if (btnWebcamFullscreen) btnWebcamFullscreen.classList.remove("active");
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

// Something covers the screen (settings, map, media): stop the orb and every decorative loop together.
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
  transition("listening");
});

audioPlayer.onStarted(() => {
  isSpeaking = true;
  if (currentState !== "speaking") {
    transition("speaking");
  }
  if (!isMuted) {
    interruptDetector.start();
  }
});

audioPlayer.onFinished(() => {
  isSpeaking = false;
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
    if (isBusy) {
      transition(lastWorkState);
    } else {
      transition("idle");
    }
  }
});

// ---------------------------------------------------------------------------
// WebSocket messages
// ---------------------------------------------------------------------------

socket.onMessage((msg) => {
  const type = msg.type as string;

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
    wasStreamed = false;
    activeAssistantText = "";
    flowSteps = [];
    currentTurnId = Date.now().toString();

    // Mark existing messages as 'old'
    const oldBubbles = chatHistory.querySelectorAll(".chat-bubble");
    oldBubbles.forEach((m) => m.classList.add("old"));

    activeFlowBubble = document.createElement("div");
    activeFlowBubble.className = "chat-bubble system-flow";
    activeFlowBubble.style.display = "none"; // Ẩn mặc định cho đến khi có step thực tế gửi từ backend
    activeFlowBubble.innerHTML = `<div class="flow-title"><span>Hoạt động hệ thống</span><span class="flow-monitor-pulse" style="width:5px;height:5px;border-radius:50%;background:#0ea5e9;box-shadow:0 0 6px #0ea5e9;display:inline-block;"></span></div><div class="flow-content-inline" style="opacity:0.6;">Đang khởi tạo tiến trình...</div>`;
    chatHistory.appendChild(activeFlowBubble);

    // 2. Tạo bong bóng chat cho phản hồi của Assistant (LLM)
    activeAssistantBubble = document.createElement("div");
    activeAssistantBubble.className = "chat-bubble assistant";
    showStreamLoader(activeAssistantBubble); // loader until the first text (stream-loader.ts)
    chatHistory.appendChild(activeAssistantBubble);

    requestAnimationFrame(() => {
      scrollToBottomIfNeeded(true); // Force scroll when new stream starts
      startStreamTypewriter();
    });
  } else if (type === "text_chunk") {
    const chunkText = msg.text as string;
    if (chunkText && activeAssistantBubble) {
      if (activeAssistantBubble.classList.contains("typing-loader")) {
        clearStreamLoader(activeAssistantBubble);
        if (!activeAssistantBubble.querySelector(".bubble-text")) {
          const textContainer = document.createElement("div");
          textContainer.className = "bubble-text";
          activeAssistantBubble.appendChild(textContainer);
        }
      }
      activeAssistantText += chunkText;
      streamTargetText = activeAssistantText; // Feed typewriter target buffer
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
    stopStreamTypewriter();

    // Đảm bảo xả toàn bộ chữ còn lại ra màn hình
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
      textContainer.innerHTML = formatMarkdown(withoutTrailingNewlines(activeAssistantText));
      scrollToBottomIfNeeded();
    }
    activeAssistantBubble = null;
    // Giữ flow bubble để nhận các flow_step completed gửi sau stream_end.
  } else if (type === "status") {
    const state = msg.state as string;
    const message = msg.message as string;
    if (msg.source === "tts" && isTtsDisabled) return;
    if (state === "thinking" || state === "working") {
      isBusy = true;
      if (currentState !== state) {
        transition(state as State, message);
      } else {
        updateStatus(state as State, message);
      }
    } else if (state === "idle") {
      isBusy = false;
      // Don't transition to idle while audio is still playing —
      // let audioPlayer.onFinished() handle the transition instead
      if (!audioPlayer.isPlaying() && !isSpeaking) {
        transition("idle");
      }
    } else if (state === "speaking") {
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
      const html = `<iframe src="${embedUrl}${sep}autoplay=1" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen scrolling="no"></iframe>`;
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
    const url = msg.url as string;
    if (url) {
      const activeId = (window as any)._activeScreenshotTrackerId || `screenshot_tracker_${currentTurnId}_${Date.now()}`;
      handleInteractiveCardData({
        id: activeId,
        type: "tracker",
        title: "📷 CHỤP MÀN HÌNH",
        status: "completed",
        label: "Đã chụp màn hình thành công.",
        image: url
      });
      // Reset ID
      delete (window as any)._activeScreenshotTrackerId;
    }
  } else if (type === "interactive") {
    const cardData = (msg as any).card;
    handleInteractiveCardData(cardData);
  } else if (type === "flow_step") {
    const step = msg.step as any;
    if (step && step.id) {
      const idx = flowSteps.findIndex(s => s.id === step.id);
      if (idx >= 0) {
        flowSteps[idx] = step;
      } else {
        flowSteps.push(step);
      }
      // Flow steps drive the inline chat system flow bubble
      updateFlowMonitor();
    }

  } else if (type === "pins") {
    const pins = msg.pins as any[];
    cachedPins = pins || [];
    if (mapLibreMap) {
      // Clear old markers
      pinnedMarkers.forEach(m => m.remove());
      pinnedMarkers = [];
      // Add new markers
      cachedPins.forEach(pin => addPinToMap(pin));
    }
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
const btnMenu = document.getElementById("btn-menu")!;
const menuDropdown = document.getElementById("menu-dropdown")!;
const btnRestart = document.getElementById("btn-restart")!;

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


btnMenu.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = menuDropdown.style.display === "none" ? "block" : "none";
});

document.addEventListener("click", () => {
  menuDropdown.style.display = "none";
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

btnRestart.addEventListener("click", async (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  restartPending = true;
  // Đẩy state machine về "restarting" để transition("idle") sau này không bị
  // early-return (statusEl đã được ghi trực tiếp, không qua updateStatus()).
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
});

socket.onReconnect(() => {
  if (restartPending) {
    restartPending = false;
    clearInterval(restartPoll);
    // Worker mới đã lên → xóa "restarting...".
    transition("idle");
  }
});

// Settings button
const btnSettings = document.getElementById("btn-settings")!;
btnSettings.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  openSettings();
});

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
  commandInput.style.height = "24px"; // Reset height
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
  menuDropdown.style.display = "none";
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

// Function to automatically adjust the height of the command input textarea
function adjustInputHeight() {
  commandInput.style.height = "24px"; // Reset to baseline
  const scrollHeight = commandInput.scrollHeight;
  // Use scrollHeight if it exceeds baseline, but clamp to max-height (140px)
  if (scrollHeight > 24) {
    commandInput.style.height = `${Math.min(scrollHeight, 140)}px`;
  }
}

// ---------------------------------------------------------------------------
// Suggestions Autocomplete Logic
// ---------------------------------------------------------------------------
let suggestCommands: any[] = [];
let suggestAgents: string[] = ["agent_desktop", "router_agent"];
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
      suggestAgents = dataCtx.agents || ["agent_desktop", "router_agent"];
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

  // "/" only lists commands/*.md — the only thing engine/server/slash_commands.py runs.
  const tabs = type === "/"
    ? [{ id: "all", label: "Lệnh" }]
    : [
      { id: "all", label: "Tất cả" },
      { id: "agent", label: "Tác nhân" },
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
    // 1. Filter agents
    const filteredAgents = suggestAgents
      .filter(a => a.toLowerCase().includes(q))
      .map(a => ({ name: "@" + a, desc: "Tác nhân Agent", tabType: "agent", type: "agent", icon: "🤖" }));

    // 2. Filter files
    const filteredFiles = suggestFiles
      .filter(f => f.toLowerCase().includes(q))
      .map(f => ({ name: "@" + f, desc: f, tabType: "file", type: "file", icon: "📄" }));

    const combined = [...filteredAgents, ...filteredFiles];
    for (const item of combined) {
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
// Map Panel
// ---------------------------------------------------------------------------

function toggleMap(forceShow?: boolean) {
  const isOpening = forceShow !== undefined ? forceShow : mapPanel.classList.contains("hidden");
  mapPanel.classList.toggle("hidden", !isOpening);
  btnMap.classList.toggle("active", isOpening);

  if (isOpening) {
    initMap();
    requestAnimationFrame(() => mapLibreMap?.resize()); // the container was display:none until now

    // On mobile, always open in full screen. On desktop, default to mini mode.
    const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth <= 768;

    if (isMobile) {
      mapPanel.classList.remove("mini-mode");
      mapPanel.classList.add("full-screen");
      isMapFullScreen = true;
      pauseScene(); // Pause only in full screen
    } else {
      mapPanel.classList.add("mini-mode");
      mapPanel.classList.remove("full-screen");
      isMapFullScreen = false;
      resumeScene(); // Keep orb running in mini mode
    }
  } else {
    resumeScene();
  }
}

function toggleMapFullScreen() {
  isMapFullScreen = !isMapFullScreen;
  mapPanel.classList.toggle("mini-mode", !isMapFullScreen);
  mapPanel.classList.toggle("full-screen", isMapFullScreen);
  document.getElementById("btn-map-full")?.classList.toggle("active", isMapFullScreen);

  // Orb control: pause if full screen, resume if mini
  if (isMapFullScreen) {
    pauseScene();
  } else {
    resumeScene();
  }

  // Trigger map resize after animation
  setTimeout(() => mapLibreMap?.resize(), 600);
}

let poiMarkers: any[] = [];

async function addRouteToMap(from: [number, number], to: [number, number]) {
  if (!mapLibreMap) return;
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${from[0]},${from[1]};${to[0]},${to[1]}?overview=full&geometries=geojson`;
    const res = await fetchWithTimeout(url);
    const data = await res.json();
    if (data.routes && data.routes.length > 0) {
      const route = data.routes[0].geometry;

      if (mapLibreMap.getLayer("route")) mapLibreMap.removeLayer("route");
      if (mapLibreMap.getSource("route")) mapLibreMap.removeSource("route");

      mapLibreMap.addSource("route", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: route
        }
      });

      mapLibreMap.addLayer({
        id: "route",
        type: "line",
        source: "route",
        layout: {
          "line-join": "round",
          "line-cap": "round"
        },
        paint: {
          "line-color": "#00d4ff",
          "line-width": 5,
          "line-opacity": 0.85
        }
      });

      const coordinates = route.coordinates;
      const bounds = coordinates.reduce((acc: any, coord: any) => {
        return acc.extend(coord);
      }, new (window as any).maplibregl.LngLatBounds(coordinates[0], coordinates[0]));

      mapLibreMap.fitBounds(bounds, { padding: 50, duration: 1500 });
    }
  } catch (e) {
    console.error("OSRM Route drawing failed:", e);
  }
}

function addPOIMarkers(pois: any[]) {
  if (!mapLibreMap) return;
  const maplibregl = (window as any).maplibregl;

  poiMarkers.forEach(m => m.remove());
  poiMarkers = [];

  pois.forEach(poi => {
    const el = document.createElement("div");
    el.className = "poi-marker";
    el.style.width = "20px";
    el.style.height = "20px";
    el.style.backgroundColor = "#00d4ff";
    el.style.border = "2px solid #fff";
    el.style.borderRadius = "50%";
    el.style.boxShadow = "0 0 10px rgba(0, 212, 255, 0.5)";
    el.style.cursor = "pointer";

    const popup = new maplibregl.Popup({ offset: 25 })
      .setHTML(`<div style="color:#000;padding:5px;font-size:12px;font-weight:bold;">${poi.name}</div>`);

    const marker = new maplibregl.Marker(el)
      .setLngLat([poi.lng, poi.lat])
      .setPopup(popup)
      .addTo(mapLibreMap);

    poiMarkers.push(marker);
  });

  if (pois.length > 0) {
    const bounds = new maplibregl.LngLatBounds();
    pois.forEach(poi => bounds.extend([poi.lng, poi.lat]));
    mapLibreMap.fitBounds(bounds, { padding: 80, duration: 1500 });
  }
}

function addAdminBoundaryToMap(geojson: any, bounds: number[] | null) {
  if (!mapLibreMap || !geojson) return;

  if (mapLibreMap.getLayer("admin-boundary-fill")) mapLibreMap.removeLayer("admin-boundary-fill");
  if (mapLibreMap.getLayer("admin-boundary-line")) mapLibreMap.removeLayer("admin-boundary-line");
  if (mapLibreMap.getSource("admin-boundary")) mapLibreMap.removeSource("admin-boundary");

  mapLibreMap.addSource("admin-boundary", { type: "geojson", data: geojson });
  mapLibreMap.addLayer({
    id: "admin-boundary-fill",
    type: "fill",
    source: "admin-boundary",
    paint: { "fill-color": "#00d4ff", "fill-opacity": 0.15 },
  });
  mapLibreMap.addLayer({
    id: "admin-boundary-line",
    type: "line",
    source: "admin-boundary",
    paint: { "line-color": "#00d4ff", "line-width": 2.5, "line-opacity": 0.9 },
  });

  if (bounds && bounds.length === 4) {
    mapLibreMap.fitBounds(
      [[bounds[0], bounds[1]], [bounds[2], bounds[3]]],
      { padding: 50, duration: 1500 }
    );
  }
}

const addPinToMap = (loc: { label: string, lat: number, lng: number }) => {
  if (!mapLibreMap) return;
  const maplibregl = (window as any).maplibregl;
  const popupContent = document.createElement("div");
  popupContent.style.color = "#fff";
  popupContent.style.padding = "5px";
  popupContent.innerHTML = `
    <div style="font-weight:bold;margin-bottom:5px;color:#fff">${loc.label}</div>
    <div style="font-size:10px;color:rgba(255,255,255,0.5)">${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)}</div>
    <div style="display:flex;gap:5px;margin-top:8px">
      <button class="btn-rename-pin" style="background:#00d4ff;color:#fff;border:none;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10px">SỬA TÊN</button>
      <button class="btn-delete-pin" style="background:#ef4444;color:#fff;border:none;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10px">XÓA</button>
    </div>
  `;

  const marker = new maplibregl.Marker({ color: "#ff4400" })
    .setLngLat([loc.lng, loc.lat])
    .setPopup(new maplibregl.Popup({ offset: 25 }).setDOMContent(popupContent))
    .addTo(mapLibreMap);

  // Fly to pin when marker element is clicked
  marker.getElement().addEventListener("click", () => {
    mapLibreMap.flyTo({ center: [loc.lng, loc.lat], zoom: 16, duration: 1500 });
  });

  popupContent.querySelector(".btn-rename-pin")?.addEventListener("click", () => {
    // Open custom dialog to rename existing pin
    // We can fetch these values and trigger the custom prompt
    const openCustomPromptFn = (window as any).openCustomMapPrompt;
    if (openCustomPromptFn) {
      openCustomPromptFn(loc.lat, loc.lng, loc.label, true, marker);
    }
  });

  popupContent.querySelector(".btn-delete-pin")?.addEventListener("click", () => {
    marker.remove();
    if (socket) {
      socket.send({ type: "delete_pin", lat: loc.lat, lng: loc.lng });
    }
  });

  pinnedMarkers.push(marker);
};

async function loadMapLibreScripts(): Promise<void> {
  if ((window as any).maplibregl) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css";
    document.head.appendChild(link);

    const script = document.createElement("script");
    script.src = "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load MapLibre GL script"));
    document.head.appendChild(script);
  });
}

async function initMap() {
  if (!mapLibreMap) {
    try {
      await loadMapLibreScripts();
    } catch (err) {
      console.error(err);
      showError("Không thể tải bản đồ MapLibre.");
      return;
    }

    const maplibregl = (window as any).maplibregl;
    if (!maplibregl) {
      console.error("MapLibre not loaded");
      return;
    }

    mapLibreMap = new maplibregl.Map({
      container: 'map-container',
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [105.8542, 21.0285], // Hanoi [lng, lat]
      zoom: 13,
      pitch: 60, // Default 3D tilt
      antialias: true,
      attributionControl: false, // Tắt ô trắng attribution/logo mặc định của MapLibre
    });

    isMap3D = true;
    document.getElementById("btn-map-3d")?.classList.add("active");

    mapLibreMap.on('load', () => {
      // Add 3D buildings layer
      const style = mapLibreMap.getStyle();
      const layers = style.layers;
      let labelLayerId;
      if (layers) {
        for (let i = 0; i < layers.length; i++) {
          if (layers[i].type === 'symbol' && layers[i].layout['text-field']) {
            labelLayerId = layers[i].id;
            break;
          }
        }
      }

      const sourceName = style.sources.openmaptiles ? 'openmaptiles' :
        style.sources.carto ? 'carto' :
          Object.keys(style.sources)[0];

      mapLibreMap.addLayer(
        {
          'id': '3d-buildings',
          'source': sourceName,
          'source-layer': 'building',
          'type': 'fill-extrusion',
          'minzoom': 15,
          'paint': {
            'fill-extrusion-color': '#00d4ff',
            'fill-extrusion-height': ['get', 'render_height'],
            'fill-extrusion-base': ['get', 'render_min_height'],
            'fill-extrusion-opacity': 0.6
          }
        },
        labelLayerId
      );

      // Load existing pins from server and render cached pins if any
      if (socket) {
        socket.send({ type: "get_pins" });
      }
      if (cachedPins && cachedPins.length > 0) {
        // Clear default mock/old pins to avoid duplication
        pinnedMarkers.forEach(m => m.remove());
        pinnedMarkers = [];
        cachedPins.forEach(pin => addPinToMap(pin));
      }

      // Temp variables for custom prompt coordinate storage
      let pendingPinLat = 0;
      let pendingPinLng = 0;
      let isRenameMode = false;
      let renameMarkerRef: any = null;

      const promptModal = document.getElementById("map-prompt-modal")!;
      const promptInput = document.getElementById("map-prompt-input") as HTMLInputElement;
      const promptCancel = document.getElementById("btn-map-prompt-cancel")!;
      const promptSave = document.getElementById("btn-map-prompt-save")!;

      const openCustomPrompt = (lat: number, lng: number, defaultText: string, renameMode = false, marker: any = null) => {
        pendingPinLat = lat;
        pendingPinLng = lng;
        isRenameMode = renameMode;
        renameMarkerRef = marker;

        promptInput.value = defaultText;
        promptModal.classList.remove("hidden");
        // Focus to input field with delay to ensure virtual keyboard pops up smoothly
        setTimeout(() => promptInput.focus(), 150);
      };

      // Export functions so other button triggers can call them
      (window as any).openCustomMapPrompt = openCustomPrompt;

      const closeCustomPrompt = () => {
        promptModal.classList.add("hidden");
        promptInput.value = "";
        promptInput.blur();
      };

      promptCancel.addEventListener("click", (e) => {
        e.stopPropagation();
        closeCustomPrompt();
      });

      promptSave.addEventListener("click", (e) => {
        e.stopPropagation();
        const text = promptInput.value.trim();
        if (!text) return;

        if (isRenameMode && renameMarkerRef) {
          // Send rename to server
          if (socket) {
            socket.send({ type: "save_pin", label: text, lat: pendingPinLat, lng: pendingPinLng });
          }
        } else {
          const loc = { label: text, lat: pendingPinLat, lng: pendingPinLng };
          addPinToMap(loc);
          if (socket) {
            socket.send({ type: "save_pin", label: text, lat: pendingPinLat, lng: pendingPinLng });
          }
        }
        closeCustomPrompt();
      });

      // Allow clicking on map to add a pin
      mapLibreMap.on('click', (e: any) => {
        // Prevent click trigger if clicking a marker
        if (e.originalEvent && e.originalEvent.target && e.originalEvent.target.closest('.maplibregl-marker')) {
          return;
        }
        const defaultName = `Vị trí tại ${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)}`;
        openCustomPrompt(e.lngLat.lat, e.lngLat.lng, defaultName, false);
      });
    });

    mapLibreMap.on('move', () => {
      const center = mapLibreMap.getCenter();
      const latEl = document.getElementById("map-lat");
      const lngEl = document.getElementById("map-lng");
      if (latEl) latEl.textContent = center.lat.toFixed(4);
      if (lngEl) lngEl.textContent = center.lng.toFixed(4);
    });

    // Controls
    document.getElementById("btn-map-3d")?.addEventListener("click", () => {
      isMap3D = !isMap3D;
      document.getElementById("btn-map-3d")?.classList.toggle("active", isMap3D);
      mapLibreMap.easeTo({
        pitch: isMap3D ? 60 : 0,
        duration: 1000
      });
    });

    document.getElementById("btn-map-globe")?.addEventListener("click", () => {
      isMapGlobe = !isMapGlobe;
      console.log("[Map] Toggling globe mode:", isMapGlobe);
      const btn = document.getElementById("btn-map-globe");
      if (btn) btn.classList.toggle("active", isMapGlobe);

      if (mapLibreMap) {
        try {
          mapLibreMap.setProjection({
            type: isMapGlobe ? 'globe' : 'mercator'
          });
        } catch (err) {
          console.error("[Map] setProjection error:", err);
        }

        if (isMapGlobe) {
          // Khi bật globe, reset độ nghiêng để nhìn thấy toàn cảnh quả cầu và zoom out
          mapLibreMap.easeTo({ pitch: 0, zoom: 1.5, duration: 1500 });
        } else {
          // Khi tắt, phục hồi pitch theo trạng thái 3D và zoom lại gần
          mapLibreMap.easeTo({ pitch: isMap3D ? 60 : 0, zoom: 13, duration: 1500 });
        }
      }
    });

    // Search Logic
    const searchInput = document.getElementById("map-search-input") as HTMLInputElement;
    const searchBtn = document.getElementById("btn-map-search-go");

    const performSearch = async () => {
      const query = searchInput.value.trim();
      if (!query) return;

      try {
        const res = await fetchWithTimeout(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`);
        const data = await res.json();
        if (data && data.length > 0) {
          const { lat, lon, display_name } = data[0];
          const latitude = parseFloat(lat);
          const longitude = parseFloat(lon);

          mapLibreMap.flyTo({
            center: [longitude, latitude],
            zoom: 15,
            essential: true
          });

          if (mapMarker) mapMarker.remove();
          const maplibregl = (window as any).maplibregl;
          mapMarker = new maplibregl.Marker({ color: "#ffaa00" })
            .setLngLat([longitude, latitude])
            .addTo(mapLibreMap);

          new maplibregl.Popup({ offset: 25 })
            .setLngLat([longitude, latitude])
            .setHTML(`<div style="color:#000;padding:5px;font-size:12px">${display_name}</div>`)
            .addTo(mapLibreMap);
        } else {
          showError("Không tìm thấy địa điểm này, thưa Ngài.");
        }
      } catch (e) {
        console.error("Search failed:", e);
        showError("Lỗi khi tìm kiếm địa điểm.");
      }
    };

    searchBtn?.addEventListener("click", performSearch);
    searchInput?.addEventListener("keypress", (e) => {
      if (e.key === "Enter") performSearch();
    });

    document.getElementById("btn-map-full")?.addEventListener("click", () => {
      toggleMapFullScreen();
    });

    // Locate Me
    document.getElementById("btn-map-locate")?.addEventListener("click", () => {
      if (!mapLibreMap) return;
      if ("geolocation" in navigator) {
        navigator.geolocation.getCurrentPosition((position) => {
          const { latitude, longitude } = position.coords;
          mapLibreMap.flyTo({ center: [longitude, latitude], zoom: 16, duration: 2000 });
        });
      }
    });

    // Saved Locations Cycling
    let currentSavedIndex = 0;
    document.getElementById("btn-map-saved")?.addEventListener("click", () => {
      if (!mapLibreMap || pinnedMarkers.length === 0) return;

      const marker = pinnedMarkers[currentSavedIndex];
      const lngLat = marker.getLngLat();

      mapLibreMap.flyTo({ center: [lngLat.lng, lngLat.lat], zoom: 16, duration: 1500 });
      if (!marker.getPopup().isOpen()) {
        marker.togglePopup();
      }

      currentSavedIndex = (currentSavedIndex + 1) % pinnedMarkers.length;
    });


    document.getElementById("btn-map-pin")?.addEventListener("click", () => {
      if (!mapLibreMap) return;
      const center = mapLibreMap.getCenter();

      const openCustomPromptFn = (window as any).openCustomMapPrompt;
      if (openCustomPromptFn) {
        openCustomPromptFn(center.lat, center.lng, `Vị trí ${new Date().toLocaleTimeString()}`, false);
      }
    });

    // Migration: If there are pins in localStorage, sync them to server
    const legacyPins = JSON.parse(localStorage.getItem("jarvis_pinned_locations") || "[]");
    if (legacyPins.length > 0 && socket) {
      console.log(`[Map] Migrating ${legacyPins.length} pins from localStorage to server...`);
      legacyPins.forEach((lp: any) => {
        socket.send({ type: "save_pin", label: lp.label, lat: lp.lat, lng: lp.lng });
      });
      localStorage.removeItem("jarvis_pinned_locations");
    }

    // Request current pins from server
    if (socket) {
      socket.send({ type: "get_pins" });
    }

    // Initial pins are loaded via WebSocket 'pins' message or from cache
    if (cachedPins.length > 0) {
      cachedPins.forEach((loc: any) => addPinToMap(loc));
    }

    // Get location
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition((position) => {
        const { latitude, longitude } = position.coords;
        mapLibreMap.flyTo({ center: [longitude, latitude], zoom: 15 });

        if (mapMarker) mapMarker.remove();
        mapMarker = new maplibregl.Marker({ color: "#00d4ff" })
          .setLngLat([longitude, latitude])
          .addTo(mapLibreMap);

        socket.send({ type: "geolocation", lat: latitude, lng: longitude });
      });
    }
  } else {
    setTimeout(() => mapLibreMap.resize(), 100);
  }
}

btnMap.addEventListener("click", () => {
  menuDropdown.style.display = "none";
  toggleMap();
});

btnCloseMap.addEventListener("click", () => {
  toggleMap(false);
});

// Listen for map update commands from WebSocket
socket.onMessage((msg: any) => {
  if (msg.type === "map_route") {
    toggleMap(true);
    setTimeout(() => {
      addRouteToMap([msg.from_lng, msg.from_lat], [msg.to_lng, msg.to_lat]);
    }, 500);
  } else if (msg.type === "map_pois") {
    toggleMap(true);
    setTimeout(() => {
      addPOIMarkers(msg.pois);
    }, 500);
  } else if (msg.type === "map_admin_boundary") {
    toggleMap(true);
    setTimeout(() => {
      addAdminBoundaryToMap(msg.geojson, msg.bounds);
    }, 500);
  } else if (msg.type === "pins") {
    console.log("[Map] Received pins from server:", msg.pins);
    cachedPins = Array.isArray(msg.pins) ? msg.pins : [];

    if (mapLibreMap) {
      // Clear existing pinned markers
      pinnedMarkers.forEach(m => m.remove());
      pinnedMarkers = [];
      // Add new pins
      cachedPins.forEach((loc: any) => addPinToMap(loc));

      // Automatically fly to the most recent pin on initial load if we just opened
      if (cachedPins.length > 0 && !pinnedMarkers.length) {
        const mostRecent = cachedPins[0];
        mapLibreMap.flyTo({
          center: [mostRecent.lng, mostRecent.lat],
          zoom: 15,
          duration: 2000
        });
      }
    }
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

// Settings phủ toàn màn hình: tạm dừng orb như map full-screen. Khi đóng chỉ chạy
// lại nếu không còn lớp toàn màn hình nào khác (map full-screen, trình phát media).
window.addEventListener("jarvis:overlay", (event) => {
  const { open } = (event as CustomEvent<{ open: boolean }>).detail;
  if (open) {
    pauseScene();
    return;
  }
  const mapFullScreen = isMapFullScreen && !mapPanel.classList.contains("hidden");
  const mediaOpen = !mediaPlayer.classList.contains("hidden");
  if (mapFullScreen) return; // the map still covers the screen
  if (mediaOpen) setAnimPaused(false); // a video is open: the big orb stays paused, the small orb and the avatar run again
  else resumeScene();
});

function openMediaPlayer(title: string, embedHtml: string) {
  document.body.classList.add("media-playing");
  orb.pause(); // only the big WebGL orb: the status orb and the avatar stay visible next to the video and keep animating
  socket.send({ type: "media_state", active: true });
  // Server chỉ chặn TTS mới; audio đã xếp lịch trong trình duyệt phải dừng ngay, không đọc chồng lên media.
  audioPlayer.stop();
  audioChunkBuffer = null;

  // Luồng Youtube/Phim dạng Iframe/HTML5 video
  mediaPlayerInner.innerHTML = `
    <div style="position:absolute;top:10px;left:12px;font-size:9px;letter-spacing:2px;color:rgba(0,212,255,0.5);z-index:5;text-transform:uppercase">${title || "NOW PLAYING"}</div>
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

