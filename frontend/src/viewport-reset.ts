// The page never scrolls; on a phone it cannot even be dragged (lockPageDrag below).
// iOS Safari can leave the page scrolled a few dozen pixels after a full-screen layer (Settings) or the keyboard
// goes away: the layout then sits low and the safe area at the top shows as a band of another colour. The page itself never
// scrolls (body is overflow:hidden), so any scroll offset is a leftover: put it back to 0 when a layer closes, when the page is
// shown again, and when the visual viewport grows back while no field has focus.
const FIELD = "input, textarea, select, [contenteditable]";

export function mountViewportReset(): void {
  const reset = () => {
    if (window.scrollX || window.scrollY) window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    refreshStatusBarTint();
  };
  const later = () => requestAnimationFrame(reset);
  window.addEventListener("jarvis:overlay", (e) => { if (!(e as CustomEvent<{ open: boolean }>).detail.open) later(); });
  window.addEventListener("pageshow", later);
  window.visualViewport?.addEventListener("resize", () => { if (!document.activeElement?.matches(FIELD)) later(); });
  lockPageDrag();
}

/** Ép WebKit/Safari trên iOS kích hoạt lại bộ lấy mẫu màu thanh trạng thái và khôi phục dải gradient */
export function refreshStatusBarTint(): void {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) {
    const orig = meta.getAttribute("content") || "#050508";
    meta.setAttribute("content", "#050509");
    requestAnimationFrame(() => {
      meta.setAttribute("content", orig);
    });
  }
}

/** The nearest box (from `el` up) that can scroll along the axis, or null. */
function scroller(el: Element | null, axis: "x" | "y"): HTMLElement | null {
  for (let e = el; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
    const o = getComputedStyle(e)[axis === "y" ? "overflowY" : "overflowX"];
    const h = e as HTMLElement;
    if ((o === "auto" || o === "scroll") && (axis === "y" ? h.scrollHeight > h.clientHeight + 1 : h.scrollWidth > h.clientWidth + 1)) return h;
  }
  return null;
}

/**
 * On a phone the page itself never moves: a finger drag only scrolls a box that has its own scrollbar (the chat, Settings, the
 * island's steps...) and only inside it. iOS otherwise lets the whole page be dragged while the soft keyboard is up, and drags a
 * box's scroll on into the page once the box reaches its top or bottom. The map handles its own touches.
 */
function lockPageDrag(): void {
  let x0 = 0, y0 = 0;
  document.addEventListener("touchstart", (e) => { x0 = e.touches[0]?.clientX ?? 0; y0 = e.touches[0]?.clientY ?? 0; }, { passive: true });
  document.addEventListener("touchmove", (e) => {
    if (e.touches.length !== 1 || !e.cancelable) return;
    const target = e.target as Element;
    if (target.closest?.("#map-panel")) return;
    const dx = e.touches[0].clientX - x0, dy = e.touches[0].clientY - y0;
    const axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
    const box = scroller(target, axis);
    if (!box) { e.preventDefault(); return; }
    // at its edge and pushed further: iOS would carry the drag on to the page
    const d = axis === "y" ? dy : dx;
    const pos = axis === "y" ? box.scrollTop : box.scrollLeft;
    const max = axis === "y" ? box.scrollHeight - box.clientHeight : box.scrollWidth - box.clientWidth;
    if ((d > 0 && pos <= 0) || (d < 0 && pos >= max - 1)) e.preventDefault();
  }, { passive: false });
}
