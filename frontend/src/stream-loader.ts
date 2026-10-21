// The loader of an assistant bubble between `stream_start` and the first text chunk (design and styles in
// stream-loader.css). It is built here and thrown away the moment text arrives, so main.ts only calls these two
// functions. The goo filter sits inside the loader's own markup: no SVG in index.html, and when the loader is
// cleared the filter goes with it.
import "./stream-loader.css";

// blur + alpha threshold = the liquid effect of uiverse.io/david_7366/tall-turkey-48 (MIT: blur 5 and "22 -9" on a
// 100px loader); the blur is scaled down to these ~13-16px blobs: 2.2 / "20 -8" (user 2026-10-19: 2.8 bridged them too
// thick). The wide filter region keeps the goo from being cut.
// The blobs are SVG shapes inside the SVG whose <g> holds the filter (2026-10-19): as HTML boxes spinning under a CSS
// url() filter, iOS WebKit drew each one on its own GPU layer and the filter never reached them — four separate balls on
// the phone. Coordinates are the old 66px blob layer's (inset -14px round the 38px pin); rx = 43% of each side.
const MARKUP =
  '<div class="stream-bubble-host">' +
  '<div class="loader-layer-pin">' +
  '<svg class="sl-svg" width="66" height="66" viewBox="0 0 66 66" aria-hidden="true">' +
  '<defs>' +
  '<filter id="sl-goo" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur in="SourceGraphic" stdDeviation="2.2"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -8"/></filter>' +
  '<linearGradient id="sl-ga" x1="0" y1="0" x2="1" y2="1"><stop offset="20%" stop-color="#00f5d4"/><stop offset="80%" stop-color="#38bdf8"/></linearGradient>' +
  '<linearGradient id="sl-gb" x1="0" y1="0" x2="1" y2="1"><stop offset="20%" stop-color="#38bdf8"/><stop offset="80%" stop-color="#00f5d4"/></linearGradient>' +
  '</defs>' +
  '<g filter="url(#sl-goo)">' +
  '<rect class="blob-c bc-1" x="11" y="11" width="16" height="16" rx="6.9" fill="url(#sl-ga)"/>' +
  '<rect class="blob-c bc-2" x="11.5" y="11.5" width="15" height="15" rx="6.45" fill="url(#sl-gb)"/>' +
  '<rect class="blob-c bc-3" x="12.5" y="12.5" width="13" height="13" rx="5.6" fill="#00f5d4"/>' +
  '<rect class="blob-c bc-4" x="12.5" y="12.5" width="13" height="13" rx="5.6" fill="#38bdf8"/>' +
  '</g>' +
  '</svg>' +
  '</div>' +
  '</div>';

const collapseTimers = new WeakMap<HTMLElement, number>();
const COLLAPSE_MS = 340; // a little longer than the 300 ms shrink animation in stream-loader.css (.collapsing)

export function showStreamLoader(bubble: HTMLElement): void {
  const existingTimer = collapseTimers.get(bubble);
  if (existingTimer) {
    clearTimeout(existingTimer);
    collapseTimers.delete(bubble);
  }
  bubble.classList.add("typing-loader");
  bubble.innerHTML = MARKUP;
}

export function clearStreamLoader(bubble: HTMLElement, immediate = false): void {
  const existingTimer = collapseTimers.get(bubble);
  if (existingTimer) {
    clearTimeout(existingTimer);
    collapseTimers.delete(bubble);
  }

  bubble.classList.remove("typing-loader");

  // Loại bỏ hoàn toàn text node khoảng trắng thừa để tránh bị pre-wrap tạo dòng trống
  [...bubble.childNodes].forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      node.remove();
    }
  });

  const host = bubble.querySelector<HTMLElement>(".stream-bubble-host"); // holds the SVG and its filter too
  if (!host) return;

  if (immediate) {
    host.remove();
    return;
  }

  if (host.classList.contains("collapsing")) {
    return;
  }

  host.classList.add("collapsing");

  const timer = window.setTimeout(() => {
    host.remove();
    collapseTimers.delete(bubble);
  }, COLLAPSE_MS);

  collapseTimers.set(bubble, timer);
}
