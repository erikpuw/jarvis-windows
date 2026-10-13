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
    }
  });

  // Images in chat bubble
  if (isBubble) {
    root.querySelectorAll("img").forEach((img) => {
      img.classList.add("bubble-img");
      if (!img.getAttribute("loading")) {
        img.setAttribute("loading", "lazy");
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
 * Main formatMarkdown function used across Jarvis:
 * Parses Markdown, polishes HTML elements, and sanitizes output against XSS.
 */
export function formatMarkdown(md: string, options?: { isBubble?: boolean }): string {
  if (!md) return "";
  const isBubble = options?.isBubble ?? false;
  try {
    const normalized = normalizeMarkdownTables(md.replace(/\r\n/g, "\n"));
    const raw = marked.parse(normalized, { async: false });
    const polished = polishMarkdownHtml(typeof raw === "string" ? raw : String(raw), isBubble);
    const sanitized = DOMPurify.sanitize(polished, {
      ADD_ATTR: ["target", "rel", "data-lang", "loading", "style"],
    }).trimEnd();
    return isBubble ? `<div class="sd-prose bubble-prose">${sanitized}</div>` : `<div class="sd-prose">${sanitized}</div>`;
  } catch (err) {
    console.error("[markdown] parse failed:", err);
    return `<div class="sd-prose">${escapeHtml(md)}</div>`;
  }
}
