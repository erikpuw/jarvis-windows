/**
 * Reader Card Component for JARVIS.
 * Floating distraction-free reader bounded between Dynamic Island and Command Bar.
 * 95% opacity neutral dark background, no blur (preserves performance), auto-scales by screen proportions.
 */

export interface ReaderData {
  title: string;
  source: string;
  url: string;
  content: string;
}

let cardEl: HTMLElement | null = null;
let backdropEl: HTMLElement | null = null;
let currentAbortCtrl: AbortController | null = null;

export function mountReaderCard(): void {
  if (cardEl) return;

  backdropEl = document.createElement("div");
  backdropEl.id = "reader-backdrop";
  backdropEl.setAttribute("aria-hidden", "true");
  document.body.appendChild(backdropEl);

  cardEl = document.createElement("div");
  cardEl.id = "reader-card";
  cardEl.setAttribute("role", "dialog");
  cardEl.setAttribute("aria-modal", "true");
  cardEl.setAttribute("aria-label", "Trình đọc bài viết");
  cardEl.innerHTML = `
    <div id="reader-header">
      <div id="reader-meta">
        <span id="reader-source"></span>
        <h3 id="reader-title"></h3>
      </div>
      <button type="button" id="reader-close" title="Đóng" aria-label="Đóng">&#10005;</button>
    </div>
    <div id="reader-body"></div>
    <div id="reader-footer">
      <span class="reader-hint">Bấm Esc hoặc chạm bên ngoài để đóng</span>
      <a id="reader-open-external" href="#" target="_blank" rel="noopener noreferrer">Mở bài gốc &#8599;</a>
    </div>
  `;
  document.body.appendChild(cardEl);

  // Close events
  const close = () => closeReaderCard();
  backdropEl.addEventListener("click", close);
  cardEl.querySelector("#reader-close")?.addEventListener("click", close);

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isReaderCardOpen()) {
      close();
    }
  });

  // Global click delegate for .reader-trigger-btn
  document.addEventListener("click", (e) => {
    const target = (e.target as HTMLElement).closest(".reader-trigger-btn") as HTMLElement | null;
    if (target && target.dataset.url) {
      e.preventDefault();
      e.stopPropagation();
      if (target.dataset.kind === "product") openProductCard(target.dataset.url, target.dataset.title || "");
      else openReaderCard(target.dataset.url, target.dataset.title || "");
    }
  });
}

export function isReaderCardOpen(): boolean {
  return cardEl?.classList.contains("open") ?? false;
}

export function closeReaderCard(): void {
  if (currentAbortCtrl) {
    currentAbortCtrl.abort();
    currentAbortCtrl = null;
  }
  cardEl?.classList.remove("open");
  backdropEl?.classList.remove("open");
}

/** Opens the shared card shell (loading state) and returns its parts; the reader and the product view fill it. */
function openShell(url: string, fallbackTitle: string, linkText: string) {
  mountReaderCard();
  if (!cardEl || !backdropEl) return null;
  const sourceEl = cardEl.querySelector("#reader-source") as HTMLElement;
  const titleEl = cardEl.querySelector("#reader-title") as HTMLElement;
  const bodyEl = cardEl.querySelector("#reader-body") as HTMLElement;
  const externalLink = cardEl.querySelector("#reader-open-external") as HTMLAnchorElement;
  externalLink.innerHTML = `${linkText} &#8599;`;
  sourceEl.textContent = "";
  titleEl.textContent = fallbackTitle || "Đang tải...";
  bodyEl.innerHTML = `
    <div class="reader-loading">
      <div class="reader-skeleton-line reader-skeleton-w80"></div>
      <div class="reader-skeleton-line reader-skeleton-w60"></div>
      <div class="reader-skeleton-line reader-skeleton-w90"></div>
    </div>
  `;
  externalLink.href = url;
  cardEl.classList.add("open");
  backdropEl.classList.add("open");
  if (currentAbortCtrl) currentAbortCtrl.abort();
  currentAbortCtrl = new AbortController();
  return { sourceEl, titleEl, bodyEl, signal: currentAbortCtrl.signal };
}

interface ProductData {
  name: string;
  price: string;
  rating: number | null;
  sold: number;
  source: string;
  url: string;
  image: string | null;
}

/** Product view for 👁 next to a price-table link: picture, name, price, rating, sold, shop (user 2026-10-19). */
export async function openProductCard(url: string, fallbackTitle = ""): Promise<void> {
  const shell = openShell(url, fallbackTitle, "Mở trang gốc");
  if (!shell) return;
  const { sourceEl, titleEl, bodyEl, signal } = shell;
  try {
    const res = await fetch(`/api/product?url=${encodeURIComponent(url)}`, { signal });
    if (!res.ok) throw new Error(`Lỗi máy chủ (${res.status})`);
    const p: ProductData = await res.json();
    sourceEl.textContent = p.source ? `🛒 ${p.source}` : "";
    titleEl.textContent = p.name || fallbackTitle || "Sản phẩm";
    const facts = [
      p.price && `<span class="product-price">${escapeHtml(p.price)}</span>`,
      p.rating && `<span>${p.rating.toFixed(1)}★</span>`,
      p.sold > 0 && `<span>Đã bán ${p.sold.toLocaleString("vi-VN")}</span>`,
    ].filter(Boolean);
    bodyEl.innerHTML =
      (p.image ? `<img class="product-image" src="${escapeHtml(p.image)}" alt="" referrerpolicy="no-referrer">` : "") +
      (facts.length ? `<div class="product-facts">${facts.join("")}</div>` : "") +
      (!p.image && !facts.length ? `<p class="reader-empty">Không lấy được ảnh và giá của sản phẩm này.</p>` : "");
  } catch (err: any) {
    if (err.name === "AbortError") return;
    bodyEl.innerHTML = `<p class="reader-empty">Không lấy được thông tin sản phẩm, ngài mở trang gốc để xem.</p>`;
  }
}

export async function openReaderCard(url: string, fallbackTitle = ""): Promise<void> {
  const shell = openShell(url, fallbackTitle, "Mở bài gốc");
  if (!shell) return;
  const { sourceEl, titleEl, bodyEl, signal } = shell;
  const externalLink = cardEl!.querySelector("#reader-open-external") as HTMLAnchorElement;

  try {
    const res = await fetch(`/api/reader?url=${encodeURIComponent(url)}`, { signal });
    if (!res.ok) {
      throw new Error(`Lỗi máy chủ (${res.status})`);
    }
    const data: ReaderData = await res.json();
    sourceEl.textContent = data.source ? `\uD83D\uDCF0 ${data.source}` : "";
    titleEl.textContent = data.title || fallbackTitle || "Bài viết";
    externalLink.href = data.url || url;

    // Render clean text paragraphs
    const paragraphs = (data.content || "")
      .split(/\n\s*\n|\n/)
      .map((p) => p.trim())
      .filter((p) => p.length > 0);

    if (paragraphs.length) {
      bodyEl.innerHTML = paragraphs.map((p) => `<p>${escapeHtml(p)}</p>`).join("");
    } else {
      bodyEl.innerHTML = `<p class="reader-empty">Không có nội dung văn bản bóc tách được từ trang này.</p>`;
    }
  } catch (err: any) {
    if (err.name === "AbortError") return;
    sourceEl.textContent = "";
    titleEl.textContent = fallbackTitle || "Không thể tải bài viết";
    bodyEl.innerHTML = `
      <div class="reader-error">
        <p>Không thể trích xuất nội dung tự động từ trang này (có thể do trang yêu cầu JavaScript hoặc bảo vệ chống bot).</p>
        <p><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="reader-error-link">Bấm vào đây để mở trực tiếp bài viết gốc &#8599;</a></p>
      </div>
    `;
  }
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
