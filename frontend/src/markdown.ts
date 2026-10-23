/**
 * Unified Markdown renderer for JARVIS (Chat Bubbles + Settings Dashboard).
 * Uses marked (GFM parser) + highlight.js (syntax highlighting) + DOMPurify (sanitizer).
 */
import { marked } from "marked";
import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/common";
import "highlight.js/styles/github-dark.css";
import { escapeHtml } from "./settings/api";

const INLINE_CODE_NOWRAP_MAX = 24;

// Configure marked with GFM support
marked.setOptions({
  gfm: true,
  breaks: true,
});

/** Heading slug generator for anchor links */
function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-");
}

/**
 * Post-processes marked's generated HTML into styled components:
 * - Code blocks with header badges, copy button, and highlight.js
 * - Scrollable responsive table wrappers
 * - Styled inline code and horizontal rules
 * - Safe external links with target="_blank"
 */
function polishMarkdownHtml(raw: string, isBubble = false): string {
  const tpl = document.createElement("template");
  tpl.innerHTML = raw;
  const root = tpl.content;

  // Heading slugs
  const seen = new Map<string, number>();
  root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((h) => {
    const base = slugify(h.textContent || "") || "section";
    const n = seen.get(base) || 0;
    seen.set(base, n + 1);
    if (!h.id) h.id = n ? `${base}-${n}` : base;
  });

  // Fenced code blocks -> .sd-code-block with header, language badge, copy button, and hljs
  root.querySelectorAll("pre").forEach((pre) => {
    const code = pre.querySelector("code");
    if (!code || pre.parentElement?.classList.contains("sd-code-block")) return;

    const langMatch = code.className.match(/language-([\w+-]+)/);
    const lang = langMatch ? langMatch[1] : "";

    const head = document.createElement("div");
    head.className = "sd-code-head";

    const label = document.createElement("span");
    label.className = "sd-code-lang";
    label.textContent = lang || "code";
    head.appendChild(label);

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "sd-copy-btn";
    copyBtn.title = "Sao chép mã";
    copyBtn.setAttribute("aria-label", "Sao chép mã");
    copyBtn.textContent = "Sao chép";
    head.appendChild(copyBtn);

    const wrap = document.createElement("div");
    wrap.className = "sd-code-block";
    wrap.appendChild(head);
    pre.replaceWith(wrap);
    wrap.appendChild(pre);

    if (lang) {
      code.classList.add("hljs");
      try {
        hljs.highlightElement(code);
      } catch {
        /* unregistered language: keep plaintext */
      }
    }
  });

  // Tables -> wrap inside .sd-table-wrap for horizontal scrolling
  root.querySelectorAll("table").forEach((table) => {
    if (table.parentElement?.classList.contains("sd-table-wrap")) return;
    table.classList.add("sd-table");
    const wrap = document.createElement("div");
    wrap.className = "sd-table-wrap table-responsive-wrapper";
    table.replaceWith(wrap);
    wrap.appendChild(table);
  });

  // Card tables (one item per column, with a row of pictures: CGV movies, Epic games) -> a grid of cards that wraps by width:
  // several a row on a PC, 2 a row on a phone. One column per movie pushed the table past the bubble on phones (user 2026-10-16),
  // and cards read better than a sideways strip there.
  root.querySelectorAll<HTMLTableElement>("table.sd-table:not(.sd-table--skeleton)").forEach((table) => {
    const rows = [...table.rows];
    const cols = rows[0]?.cells.length ?? 0;
    if (cols < 2 || !rows.some((r) => r.cells.length === cols && [...r.cells].every((c) => c.querySelector("img")))) return;
    const grid = document.createElement("div");
    grid.className = "sd-card-grid";
    for (let c = 0; c < cols; c++) {
      const card = document.createElement("div");
      card.className = "sd-card";
      for (const r of rows) {
        const cell = r.cells[c];
        if (!cell || (!cell.textContent!.trim() && !cell.querySelector("img"))) continue;
        const part = document.createElement("div");
        part.className = r.parentElement?.tagName === "THEAD" ? "sd-card-head" : "sd-card-row";
        part.append(...cell.childNodes);
        card.appendChild(part);
      }
      grid.appendChild(card);
    }
    (table.closest(".sd-table-wrap") ?? table).replaceWith(grid);
  });

  // Preserve table cell alignments (e.g. :---: -> align="center") via inline style
  root.querySelectorAll("th, td").forEach((cell) => {
    const align = cell.getAttribute("align");
    if (align) {
      (cell as HTMLElement).style.textAlign = align;
    }
  });

  // Inline code tags
  root.querySelectorAll("code").forEach((code) => {
    if (!code.closest("pre")) {
      code.classList.add("sd-inline-code");
      // short, space-free code ("vi-VN", "/check_system") stays on one line; only long ones may break anywhere
      if (code.textContent!.length <= INLINE_CODE_NOWRAP_MAX && !/\s/.test(code.textContent!)) code.classList.add("sd-inline-code--nowrap");
    }
  });

  // Horizontal rules
  root.querySelectorAll("hr").forEach((hr) => {
    hr.classList.add("sd-hr");
  });

  // External links
  root.querySelectorAll("a").forEach((a) => {
    const href = a.getAttribute("href") || "";
    if (href && !href.startsWith("#")) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");

      // In chat bubbles: attach a quick-view trigger to web links (skip internal anchors & file links). Links in price
      // tables are shop/medicine pages: 👁 opens the product card (picture, price kept at search time), since the article
      // reader showed their menus and footers (user 2026-10-19). Card grids (CGV, Epic) already show their picture.
      if (isBubble && (href.startsWith("http://") || href.startsWith("https://")) && !a.closest(".sd-card-grid")) {
        const product = !!a.closest("table");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "reader-trigger-btn";
        btn.dataset.url = href;
        btn.dataset.title = (product ? a.closest("tr")?.cells[0]?.textContent : a.textContent)?.trim() || "";
        if (product) btn.dataset.kind = "product";
        btn.title = product ? "Xem sản phẩm" : "Đọc nhanh trong JARVIS";
        btn.setAttribute("aria-label", btn.title);
        btn.innerHTML = product
          ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>`
          : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>`;
        a.classList.add("has-reader-btn");
        a.after(btn);
      }
    }
  });

  // Images in chat bubble
  if (isBubble) {
    root.querySelectorAll("img").forEach((img) => {
      img.classList.add("bubble-img");
      if (!img.getAttribute("loading")) {
        img.setAttribute("loading", "lazy");
      }
      if (!img.getAttribute("decoding")) {
        img.setAttribute("decoding", "async");
      }
    });
  }

  // Strip trailing whitespace-only text nodes produced by marked around blocks
  const trimTrailingWhitespace = (node: Node) => {
    while (node.lastChild) {
      if (node.lastChild.nodeType === Node.TEXT_NODE && !node.lastChild.textContent?.trim()) {
        node.removeChild(node.lastChild);
      } else if (node.lastChild.nodeType === Node.ELEMENT_NODE) {
        trimTrailingWhitespace(node.lastChild);
        break;
      } else {
        break;
      }
    }
  };
  trimTrailingWhitespace(root);

  return tpl.innerHTML.trimEnd();
}

/**
 * Normalizes Markdown tables by ensuring blank lines before and after tables.
 * Standard GFM parser (marked) swallows text lines following a table (e.g. "**TP.HCM**")
 * into the previous table unless separated by blank lines.
 */
function normalizeMarkdownTables(md: string): string {
  if (!md || !md.includes("|")) return md;

  const lines = md.split("\n");
  const result: string[] = [];

  const isDelimiter = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(l);
  const isTableRow = (l: string) => {
    const t = l.trim();
    return t.startsWith("|") || (t.includes("|") && !t.startsWith("```"));
  };

  let inTable = false;
  let inCodeBlock = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const nextLine = i + 1 < lines.length ? lines[i + 1] : null;

    if (trimmed.startsWith("```")) {
      inCodeBlock = !inCodeBlock;
      inTable = false;
      result.push(line);
      continue;
    }

    if (inCodeBlock) {
      result.push(line);
      continue;
    }

    if (!trimmed) {
      inTable = false;
      result.push(line);
      continue;
    }

    const isHeader = isTableRow(line) && nextLine !== null && isDelimiter(nextLine);

    if (isHeader) {
      if (result.length > 0 && result[result.length - 1].trim() !== "") {
        result.push("");
      }
      inTable = true;
      result.push(line);
      continue;
    }

    if (inTable) {
      if (isDelimiter(line) || isTableRow(line)) {
        result.push(line);
      } else {
        inTable = false;
        if (result.length > 0 && result[result.length - 1].trim() !== "") {
          result.push("");
        }
        result.push(line);
      }
    } else {
      result.push(line);
    }
  }

  return result.join("\n");
}

/**
 * Generates a shadcn/ui Skeleton table block matching the exact geometry of final content
 * (movie/game horizontal cards or standard tabular data) with subtle shimmer animation.
 */
export function generateTableSkeleton(cols = 3, isCardTable = true): string {
  const safeCols = Math.max(1, Math.min(cols, 6));
  const colWidths = [78, 85, 68, 82, 72, 80];
  const genreWidths = [65, 75, 60, 70, 68, 62];
  const durationWidths = [50, 58, 46, 54, 48, 52];
  const dateWidths = [58, 64, 52, 60, 55, 58];

  let ths = "";
  for (let c = 0; c < safeCols; c++) {
    const w = colWidths[c % colWidths.length];
    ths += `<th><div class="sd-skeleton sd-skeleton-title" style="width: ${w}%;"></div></th>`;
  }

  let body = "";
  if (isCardTable) {
    // Row 1: Poster / Banner images (matching 80x110px exact geometry)
    let imgCells = "";
    for (let c = 0; c < safeCols; c++) {
      imgCells += `<td align="center"><div class="sd-skeleton sd-skeleton-img"></div></td>`;
    }
    body += `<tr>${imgCells}</tr>`;

    // Row 2: Genre / Category text line
    let genreCells = "";
    for (let c = 0; c < safeCols; c++) {
      const w = genreWidths[c % genreWidths.length];
      genreCells += `<td align="center"><div class="sd-skeleton sd-skeleton-text" style="width: ${w}%;"></div></td>`;
    }
    body += `<tr>${genreCells}</tr>`;

    // Row 3: Duration text line
    let durCells = "";
    for (let c = 0; c < safeCols; c++) {
      const w = durationWidths[c % durationWidths.length];
      durCells += `<td align="center"><div class="sd-skeleton sd-skeleton-text" style="width: ${w}%;"></div></td>`;
    }
    body += `<tr>${durCells}</tr>`;

    // Row 4: Release Date text line
    let dateCells = "";
    for (let c = 0; c < safeCols; c++) {
      const w = dateWidths[c % dateWidths.length];
      dateCells += `<td align="center"><div class="sd-skeleton sd-skeleton-text" style="width: ${w}%;"></div></td>`;
    }
    body += `<tr>${dateCells}</tr>`;

    // Row 5: Action Link text line
    let linkCells = "";
    for (let c = 0; c < safeCols; c++) {
      linkCells += `<td align="center"><div class="sd-skeleton sd-skeleton-text" style="width: 42%;"></div></td>`;
    }
    body += `<tr>${linkCells}</tr>`;
  } else {
    // Generic table skeleton: 3 data rows with natural varied text lines
    for (let r = 0; r < 3; r++) {
      let cells = "";
      for (let c = 0; c < safeCols; c++) {
        const w = [70, 85, 60, 80, 75, 65][(r * 2 + c) % 6];
        cells += `<td><div class="sd-skeleton sd-skeleton-text" style="width: ${w}%;"></div></td>`;
      }
      body += `<tr>${cells}</tr>`;
    }
  }

  return `\n\n<div class="sd-table-wrap table-responsive-wrapper sd-table-wrap--skeleton" aria-busy="true" role="status" aria-label="Đang nạp dữ liệu bảng..."><table class="sd-table sd-table--skeleton"><thead><tr>${ths}</tr></thead><tbody>${body}</tbody></table></div>\n\n`;
}

/**
 * Detects whether a markdown table is incomplete/loading during typewriter streaming.
 * While a table is still being streamed or lacks complete information, replaces it with
 * a shadcn/ui Skeleton table block matching the exact geometry to prevent layout shifts.
 */
function replaceStreamingIncompleteTables(md: string, isStreaming: boolean): string {
  if (!md) return md;

  // Support explicit placeholder
  if (md.includes("[TABLE_LOADING]")) {
    md = md.replace(/\[TABLE_LOADING\]/g, () => generateTableSkeleton(3, true));
  }

  if (!isStreaming || !md.includes("|")) return md;

  const lines = md.split("\n");
  const isDelimiter = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(l);
  const isTableRow = (l: string) => {
    const t = l.trim();
    return t.startsWith("|") || (t.includes("|") && !t.startsWith("```"));
  };

  let inCodeBlock = false;
  let inTable = false;
  let headerLine = "";
  let hasDelimiter = false;
  let rowCount = 0;
  let tableLines: string[] = [];

  const result: string[] = [];

  const flushTable = (isTail: boolean) => {
    if (!inTable) return;
    const isEpic = /\b(epic|game)\b/i.test(md) || headerLine.includes("![");
    const isCgv = /\b(cgv|phim|cinema|movie)\b/i.test(md);
    const isCardTable = isEpic || isCgv || headerLine.includes("![") || tableLines.some((l) => l.includes("!["));

    // the header line still being typed would change the column count letter by letter (skeleton redrawn, bubble jumps): 3 until it is whole
    const headerDone = tableLines.length > 1 || !isTail;
    const cols = (headerDone && headerLine.split("|").map((s) => s.trim()).filter(Boolean).length) || 3;

    // Minimum expected rows:
    // - CGV: 5 data rows (poster, genre, duration, release, link)
    // - Epic: 1 data row (since header contains images, 1 row for titles/dates)
    // - Generic: 1 data row
    const minRows = isCgv ? 5 : 1;
    const isComplete = hasDelimiter && rowCount >= minRows && !isTail;

    if (!isComplete) {
      result.push(generateTableSkeleton(cols, isCardTable));
    } else {
      result.push(...tableLines);
    }

    inTable = false;
    tableLines = [];
    headerLine = "";
    hasDelimiter = false;
    rowCount = 0;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inTable) flushTable(false);
      inCodeBlock = !inCodeBlock;
      result.push(line);
      continue;
    }
    if (inCodeBlock) {
      result.push(line);
      continue;
    }

    const nextLine = i + 1 < lines.length ? lines[i + 1] : null;
    // the delimiter line still being typed ("| :--") already marks the line above as a header, or that header shows as raw text for a moment
    const delimiterTyping = nextLine !== null && i + 1 === lines.length - 1 && /^\s*\|[\s|:-]*$/.test(nextLine);
    const isHeaderCandidate = isTableRow(line) && nextLine !== null && (isDelimiter(nextLine) || delimiterTyping);

    if (!inTable) {
      if (isHeaderCandidate || (isTableRow(line) && i === lines.length - 1)) {
        inTable = true;
        headerLine = line;
        hasDelimiter = false;
        rowCount = 0;
        tableLines = [line];
        continue;
      }
      result.push(line);
      continue;
    }

    // Inside table
    if (isDelimiter(line)) {
      hasDelimiter = true;
      tableLines.push(line);
      continue;
    }

    if (isTableRow(line)) {
      rowCount++;
      tableLines.push(line);
      continue;
    }

    // Line is not a table row -> Table has ended
    flushTable(false);
    result.push(line);
  }

  if (inTable) {
    // Table at the tail of streaming markdown
    flushTable(true);
  }

  return result.join("\n");
}

/**
 * Main formatMarkdown function used across Jarvis:
 * Parses Markdown, polishes HTML elements, and sanitizes output against XSS.
 */
export function formatMarkdown(
  md: string,
  options?: { isBubble?: boolean; isStreaming?: boolean; document?: boolean }
): string {
  if (!md) return "";
  const isBubble = options?.isBubble ?? false;
  const isStreaming = options?.isStreaming ?? false;
  try {
    const withSkeletons = replaceStreamingIncompleteTables(md.replace(/\r\n/g, "\n"), isStreaming);
    const normalized = normalizeMarkdownTables(withSkeletons);
    // a written document (README) joins consecutive lines into one paragraph as GitHub does (badges in a row, 2026-10-23); chat keeps
    // breaks: a model's single newline is a line break
    const raw = marked.parse(normalized, { async: false, ...(options?.document ? { breaks: false } : {}) });
    const polished = polishMarkdownHtml(typeof raw === "string" ? raw : String(raw), isBubble);
    const sanitized = DOMPurify.sanitize(polished, {
      ADD_ATTR: [
        "target",
        "rel",
        "data-lang",
        "loading",
        "decoding",
        "style",
        "aria-busy",
        "role",
        "aria-label",
      ],
    }).trimEnd();
    return isBubble ? `<div class="sd-prose bubble-prose">${sanitized}</div>` : `<div class="sd-prose">${sanitized}</div>`;
  } catch (err) {
    console.error("[markdown] parse failed:", err);
    return `<div class="sd-prose">${escapeHtml(md)}</div>`;
  }
}
