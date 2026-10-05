/**
 * Settings dashboard controller (spec 2026-09-27).
 * Modularized into frontend/src/settings/
 */
import { apiGet, apiPost, escapeHtml, formatNumber, formatUptime } from "./api";
import { buildSettingsHTML, SETTINGS_PAGES, APP_VERSION, type SettingsPageId } from "./pages";
import { initMemoryCenter } from "./memory";
import { initLogsPage } from "./logs";
import { enterLockable, lockAll } from "./lock";
import { renderGraphfy, resetGraphfyLayout } from "./graphfy";
import type {
  AgentItem, HookItem, SkillItem, PromptItem, CommandItem,
  PluginItem, McpServerItem, StatusResponse, PreferencesResponse
} from "./types";
import { makeIcon, decorateActionButton, runAction } from "../icons";
import type { MorphIconElement } from "morphicons/element";
import { Menu, X, ArrowLeft, ArrowRight, PanelLeftClose, PanelLeft } from "lucide";
import "./styles.css";

export type { SettingsPageId };
export { SETTINGS_PAGES, APP_VERSION };

const HEALTH_POLL_INTERVAL_MS = 5000;
const PAGE_STORAGE_KEY = "jarvis.settings.page";
const SIDEBAR_COLLAPSED_KEY = "jarvis.settings.sidebar_collapsed";

let container: HTMLElement | null = null;
let isOpen = false;
let currentPage: SettingsPageId = "overview";
let healthTimer: number | null = null;
let menuIcon: MorphIconElement | null = null;
let sidebarToggleIcon: MorphIconElement | null = null;
let isSidebarCollapsed = false;

// Cached data collections
let cachedAgents: AgentItem[] = [];
let cachedHooks: HookItem[] = [];
let cachedSkills: SkillItem[] = [];
let cachedPrompts: PromptItem[] = [];
let editingPromptId: string | null = null;
let cachedCommands: CommandItem[] = [];
let cachedPlugins: PluginItem[] = [];
let cachedMcpServers: McpServerItem[] = [];
let cachedMcpConfig: Record<string, any> = {};

function byId<T extends HTMLElement = HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

function setText(id: string, text: string): void {
  const el = byId(id);
  if (el) el.textContent = text;
}

function setVal(id: string, val: string): void {
  const el = byId<HTMLInputElement | HTMLSelectElement>(id);
  if (el) el.value = val;
}

function setDot(id: string, state: "ok" | "err" | "off"): void {
  const el = byId(id);
  if (!el) return;
  el.className = "status-dot " + (state === "ok" ? "status-green" : state === "err" ? "status-red" : "status-gray");
  const parent = el.closest(".status-row");
  const textEl = parent?.querySelector(".status-text");
  if (textEl) {
    textEl.textContent = state === "ok" ? "Sẵn sàng" : state === "err" ? "Lỗi kết nối" : "Chưa bật";
  }
}

function setMeter(prefix: string, pct: number, text: string): void {
  setText(`${prefix}-val`, text);
  const bar = byId(`${prefix}-bar`);
  if (bar) bar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
}

function setFeedback(buttonId: string, msg: string, kind: "ok" | "err" = "ok"): void {
  const el = document.querySelector<HTMLElement>(`[data-feedback-for="${buttonId}"]`);
  if (!el) return;
  el.textContent = msg;
  el.className = `settings-feedback ${kind === "err" ? "feedback-error" : "feedback-ok"}`;
  el.hidden = false;
}

function clearFeedback(buttonId: string): void {
  const el = document.querySelector<HTMLElement>(`[data-feedback-for="${buttonId}"]`);
  if (el) { el.textContent = ""; el.hidden = true; }
}

function setSidebarCollapsed(collapsed: boolean, save = true): void {
  isSidebarCollapsed = collapsed;
  const root = byId("settings-panel-inner");
  if (!root) return;
  root.classList.toggle("sidebar-collapsed", collapsed);
  const toggleBtn = byId("settings-sidebar-toggle");
  if (toggleBtn) {
    toggleBtn.setAttribute("title", collapsed ? "Mở rộng thanh điều hướng" : "Thu nhỏ thanh điều hướng");
    toggleBtn.setAttribute("aria-label", collapsed ? "Mở rộng thanh điều hướng" : "Thu nhỏ thanh điều hướng");
  }
  if (sidebarToggleIcon) {
    sidebarToggleIcon.morphTo(collapsed ? PanelLeft : PanelLeftClose);
  }
  if (save) {
    try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0"); } catch {}
  }
}

// ---------------------------------------------------------------------------
// Markdown formatter for README.md
// ---------------------------------------------------------------------------
function formatMarkdown(md: string): string {
  if (!md) return "";
  let html = md.replace(/\r\n/g, "\n");

  // Fenced code blocks
  html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, lang, code) =>
    `<div class="sd-code-block"><div class="sd-code-head"><span>${escapeHtml(lang || "text")}</span></div><pre><code>${escapeHtml(code.trim())}</code></pre></div>`
  );

  // Inline code
  html = html.replace(/`([^`]+)`/g, (_m, c) => `<code class="sd-inline-code">${escapeHtml(c)}</code>`);

  // Headings
  html = html.replace(/^###### (.*$)/gim, "<h6>$1</h6>");
  html = html.replace(/^##### (.*$)/gim, "<h5>$1</h5>");
  html = html.replace(/^#### (.*$)/gim, "<h4>$1</h4>");
  html = html.replace(/^### (.*$)/gim, "<h3>$1</h3>");
  html = html.replace(/^## (.*$)/gim, "<h2>$1</h2>");
  html = html.replace(/^# (.*$)/gim, "<h1>$1</h1>");

  // Blockquote
  html = html.replace(/^> (.*$)/gim, "<blockquote>$1</blockquote>");

  // Bold & italic
  html = html.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

  // Links — support anchor (#heading) and external
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, text, href) => {
    const isAnchor = href.startsWith("#");
    return `<a href="${escapeHtml(href)}"${isAnchor ? "" : ' target="_blank" rel="noopener noreferrer"'}>${text}</a>`;
  });

  // Markdown tables
  html = html.replace(/((?:^\|.+\|\s*\n)+)/gim, (tableBlock) => {
    const rows = tableBlock.trim().split("\n");
    if (rows.length < 2) return tableBlock;
    const isSeperator = (r: string) => /^\|[\s\-:|]+\|/.test(r);
    let thead = "", tbody = "";
    let pastSep = false;
    for (const row of rows) {
      if (isSeperator(row)) { pastSep = true; continue; }
      const cells = row.replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const tag = !pastSep ? "th" : "td";
      const tr = "<tr>" + cells.map(c => `<${tag}>${c}</${tag}>`).join("") + "</tr>";
      if (!pastSep) thead += tr; else tbody += tr;
    }
    // the wrapper lets a wide table scroll inside itself instead of widening the whole page (phones)
    return `<div class="sd-table-wrap"><table class="sd-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
  });

  // Horizontal rule
  html = html.replace(/^\s*---\s*$/gim, "<hr class='sd-hr'>");

  // Ordered list
  html = html.replace(/^(\s*)\d+\.\s+(.*)$/gim, (_m, indent, item) =>
    `<li class="sd-ol-item" style="margin-left:${indent.length * 8}px">${item}</li>`
  );
  html = html.replace(/((?:<li class="sd-ol-item"[^>]*>.*<\/li>\s*)+)/g, "<ol>$1</ol>");

  // Unordered list
  html = html.replace(/^(\s*)[-*+]\s+(.*)$/gim, (_m, indent, item) =>
    `<li style="margin-left:${indent.length * 8}px">${item}</li>`
  );
  html = html.replace(/((?:<li(?! class="sd-ol-item")[^>]*>.*<\/li>\s*)+)/g, "<ul>$1</ul>");

  // Paragraphs
  const paragraphs = html.split(/\n{2,}/).map(block => {
    block = block.trim();
    if (!block) return "";
    if (/^<(h[1-6]|div|pre|blockquote|ul|ol|hr|table)/i.test(block)) return block;
    return `<p>${block.replace(/\n/g, "<br>")}</p>`;
  });
  return `<div class="sd-prose">${paragraphs.filter(Boolean).join("\n")}</div>`;
}

// ---------------------------------------------------------------------------
// Health and System status
// ---------------------------------------------------------------------------
async function loadDetailedHealth(): Promise<void> {
  try {
    const res = await apiGet<any>("/api/health/detailed");
    if (res.status === "online") {
      const llmOk = res.llm?.status === "online";
      const redisOk = res.redis?.status === "online";
      const dbOk = res.database?.ok === true;
      const ragOk = res.rag?.enabled === true;

      updateServiceRow("row-status-llm", llmOk,
        llmOk && res.llm?.response_time_ms ? `${res.llm.response_time_ms}ms` : (res.llm?.status ?? "offline"));
      updateServiceRow("row-status-redis", redisOk, res.redis?.status ?? "offline");
      updateServiceRow("row-status-db", dbOk,
        res.database?.size_kb ? `${res.database.size_kb} KB` : (dbOk ? "OK" : "offline"));
      updateServiceRow("row-status-rag", ragOk,
        ragOk ? `${res.rag?.total_chunks ?? 0} chunks` : "không hoạt động");

      // Overview "Hạ tầng" card mirrors the same probes.
      setInfra("llm", llmOk, llmOk ? "Sẵn sàng" : "Mất kết nối");
      setInfra("rag", ragOk, ragOk ? "Sẵn sàng" : "Không hoạt động");
      setInfra("db", dbOk, dbOk ? "Sẵn sàng" : "Lỗi");
      setInfra("redis", redisOk, redisOk ? "Sẵn sàng" : "Mất kết nối");
    }
  } catch (e) {
    console.error("[settings] failed to load detailed health:", e);
  }
}

function setInfra(key: string, ok: boolean, text: string): void {
  const dot = byId(`ov-dot-${key}`);
  if (dot) dot.className = "status-dot " + (ok ? "status-green" : "status-red");
  setText(`ov-infra-${key}`, text);
}

function updateServiceRow(rowId: string, ok: boolean, detail = ""): void {
  const row = byId(rowId);
  if (!row) return;
  const dot = row.querySelector<HTMLElement>(".status-dot");
  const detailEl = row.querySelector<HTMLElement>(".status-detail");
  if (dot) dot.className = "status-dot " + (ok ? "status-green" : "status-red");
  if (detailEl) detailEl.textContent = detail || (ok ? "Đang chạy" : "Mất kết nối");
}

async function loadStatus(): Promise<void> {
  try {
    const status = await apiGet<StatusResponse>("/api/settings/status?apps=true");
    setDot("status-intelligence-core", status.intelligence_core_ok ? "ok" : "err");
    setDot("status-server-engine", status.server_engine_ok ? "ok" : "err");
    setDot("status-llm-server", status.llm_server_ok ? "ok" : "err");
    setDot("status-tts-server", status.tts_server_ok ? "ok" : "off");
    setDot("status-server", status.server_engine_ok ? "ok" : "err");

    const cpu = status.system?.cpu_percent ?? 0;
    const ram = status.system?.ram_percent ?? 0;
    const ramUsed = status.system?.ram_used_gb ?? 0;
    const ramTotal = status.system?.ram_total_gb ?? 0;

    setMeter("ov-cpu", cpu, `${cpu}%`);
    setMeter("ov-ram", ram, `${ram}%`);
    setText("ov-ram-sub", `${ramUsed} / ${ramTotal} GB`);

    setMeter("health-cpu", cpu, `${cpu}%`);
    setMeter("health-ram", ram, `${ram}%`);
    setText("sysinfo-memory-detail", `Đã dùng ${ramUsed} GB trên tổng số ${ramTotal} GB (${ram}%)`);

    const gpus = status.system?.gpus || [];
    if (gpus.length > 0) {
      const g0 = gpus[0];
      const gMem = g0.mem_used_mb ?? 0;
      const gTot = g0.mem_total_mb ?? g0.vram_total_mb ?? 0;
      const gPct = gTot > 0 ? Math.round((gMem / gTot) * 100) : (g0.util_percent ?? 0);
      setMeter("ov-gpu", gPct, `${gPct}%`);
      setText("ov-gpu-name", `${g0.name.replace(/NVIDIA\s*/i, "")} · ${Math.round(gMem / 1024)}GB`);
    } else {
      setMeter("ov-gpu", 0, "0%");
      setText("ov-gpu-name", "Không phát hiện GPU chuyên dụng");
    }

    renderGpuList(gpus, status.system?.npus || []);
    renderAppBadges(status.open_apps || []);

    setText("sysinfo-uptime", formatUptime(status.uptime_seconds));
    setText("sysinfo-port", String(status.server_port || 8340));
    setText("sysinfo-memory", formatNumber(status.memory_count));
    setText("sysinfo-turns", formatNumber(status.conversation_turn_count));
    setText("sysinfo-tasks", formatNumber(status.task_count));
    setText("sysinfo-skills", formatNumber(status.skill_count));
    setText("sysinfo-commands", formatNumber(status.command_count));
    fillRuntime(status);
    setText("status-llama", status.env_keys_set?.llama ? "Đã cấu hình khoá và URL máy chủ." : "Chưa cấu hình khoá.");

    if (status.session_tokens) {
      setText("ov-token-total", formatNumber(status.session_tokens.total));
      setText("ov-token-in", formatNumber(status.session_tokens.input));
      setText("ov-token-out", formatNumber(status.session_tokens.output));
    }

    if (status.agents) {
      cachedAgents = Array.isArray(status.agents) ? status.agents : [];
      setText("agents-count-val", String(cachedAgents.length));
      renderAgentsList(cachedAgents);
    }

    // Hooks/skills/prompts/commands/plugins/README come from /api/settings/catalog and
    // /api/system/readme when their page opens; the MCP list from /api/mcp/servers.
  } catch (e) {
    console.error("[settings] failed to load status:", e);
  }
}

function renderGpuList(gpus: any[], npus: string[]): void {
  const container = byId("health-gpus-container");
  if (!container) return;
  if (!gpus.length && !npus.length) {
    container.innerHTML = `<div class="sd-empty">Không phát hiện GPU/NPU rời. Chạy trên CPU.</div>`;
    return;
  }
  let html = gpus.map(g => {
    const mem = g.mem_used_mb !== undefined ? `${Math.round(g.mem_used_mb)} MB` : "--";
    const tot = g.mem_total_mb || g.vram_total_mb ? `${Math.round(g.mem_total_mb || g.vram_total_mb)} MB` : "--";
    const temp = g.temp_c ? `${g.temp_c}°C` : "";
    return `
      <div class="sd-gpu-item">
        <div class="sd-gpu-name">${escapeHtml(g.name)}</div>
        <div class="sd-gpu-stat">Bộ nhớ: <strong>${mem} / ${tot}</strong> ${temp ? `· Nhiệt độ: <strong>${temp}</strong>` : ""}</div>
      </div>`;
  }).join("");
  if (npus.length) {
    html += npus.map(n => `
      <div class="sd-gpu-item npu-item">
        <div class="sd-gpu-name">${escapeHtml(n)}</div>
        <div class="sd-gpu-stat"><span class="sd-badge-dot"></span>Bộ tăng tốc trí tuệ nhân tạo NPU</div>
      </div>`).join("");
  }
  container.innerHTML = html;
}

function renderAppBadges(apps: string[]): void {
  const container = byId("ov-apps-badges");
  const fullList = byId("apps-list-container");
  if (container) {
    container.innerHTML = apps.length
      ? apps.slice(0, 6).map(a => `<span class="sd-badge">${escapeHtml(a)}</span>`).join("")
      : `<span class="sd-empty" style="padding:0;">Không có ứng dụng đáng chú ý.</span>`;
  }
  if (fullList) {
    fullList.innerHTML = apps.length
      ? apps.map(a => `<div class="sd-app-row"><span class="sd-dot"></span><span>${escapeHtml(a)}</span></div>`).join("")
      : `<div class="sd-empty">Không phát hiện ứng dụng desktop đang chạy.</div>`;
  }
}

/** Overview "Mô hình & kết nối" + Giọng đọc engine dots — read-only facts from .env. */
function fillRuntime(status: any): void {
  const rt = status.runtime || {};
  const engineName = rt.tts_engine === "vieneu" ? "VieNeu" : rt.tts_engine === "edge" ? "Edge-TTS" : "Chưa bật";
  const voice = rt.tts_engine === "vieneu" ? rt.vieneu_voice : rt.tts_engine === "edge" ? rt.edge_voice : "";
  setText("ov-llm-model", rt.llm_model || "—");
  setText("ov-embed-model", rt.embed_model || "—");
  setText("ov-tts-engine", voice ? `${engineName} · ${voice}` : engineName);
  setText("ov-mcp", `${status.mcp_connected ?? 0} / ${status.mcp_total ?? 0}`);
  setText("ov-agents", formatNumber(status.agents_count ?? (status.agents || []).length));
  setText("ov-skills-cmds", `${formatNumber(status.skill_count)} · ${formatNumber(status.command_count)}`);
  for (const [key, current] of [["vieneu", rt.vieneu_voice], ["edge", rt.edge_voice]] as const) {
    const running = rt.tts_engine === key;
    const dot = byId(`voice-dot-${key}`);
    if (dot) dot.className = "status-dot " + (running ? "status-green" : "status-gray");
    setText(`voice-${key}-current`, `${current || "—"}${running ? " · đang chạy" : ""}`);
  }
}

async function loadPreferences(): Promise<void> {
  try {
    const prefs = await apiGet<PreferencesResponse>("/api/settings/preferences");
    setVal("input-user-name", prefs.user_name || "");
    setVal("input-honorific", prefs.honorific || "");
    setVal("input-calendar-accounts", prefs.calendar_accounts || "");
  } catch (e) {
    console.error("[settings] failed to load preferences:", e);
  }
}

/** Heavy lists live in /api/settings/catalog (not in the 5s status poll); fetched once per open. */
let catalogPromise: Promise<any> | null = null;
function loadCatalog(): Promise<any> {
  catalogPromise ??= apiGet<any>("/api/settings/catalog").catch(err => { catalogPromise = null; throw err; });
  return catalogPromise;
}

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------
async function loadAgents(): Promise<void> {
  const grid = byId("agents-grid");
  const countEl = byId("agents-count-val");
  if (!grid) return;
  try {
    const catalog = await loadCatalog();
    cachedAgents = catalog.agents || [];
    if (countEl) countEl.textContent = String(cachedAgents.length);
    renderAgentsList(cachedAgents);
  } catch (err) {
    console.error("[settings] failed to load agents:", err);
    grid.innerHTML = `<div class="sd-empty sd-error-state">Lỗi nạp danh sách Agents: ${escapeHtml(err)}</div>`;
  }
}

/** `@id câu ví dụ` — what fast_paths.resolve_mention accepts. */
function agentCall(agent: AgentItem): string {
  const mention = agent.mention || `@${agent.id}`;
  return agent.example && !agent.example.startsWith("@") ? `${mention} ${agent.example}` : mention;
}

/** commands/*.md `usage` is a JSON param spec ({"name": "mô tả"}), not a syntax line. */
function commandParams(cmd: CommandItem): [string, string][] {
  try {
    // frontmatter keeps YAML quotes: usage: '{"max_results": "…"}'
    const raw = (cmd.usage || "").trim().replace(/^'([\s\S]*)'$/, "$1");
    const spec = JSON.parse(raw);
    if (spec && typeof spec === "object" && !Array.isArray(spec)) {
      return Object.entries(spec).map(([k, v]) => [k, String(v)]);
    }
  } catch { /* plain text / empty usage */ }
  return [];
}

function commandCall(cmd: CommandItem): string {
  const params = commandParams(cmd);
  return params.length ? `/${cmd.name} <${params.map(([k]) => k).join(", ")}>` : `/${cmd.name}`;
}

function commandParamsHtml(cmd: CommandItem): string {
  const params = commandParams(cmd);
  if (!params.length) return `<div class="sd-agent-cmd-note">Không cần tham số.</div>`;
  return `<ul class="sd-cmd-params">${params.map(([k, v]) =>
    `<li><code>${escapeHtml(k)}</code> — ${escapeHtml(v)}</li>`).join("")}</ul>
    <div class="sd-agent-cmd-note">Gõ <code>/${escapeHtml(cmd.name)}</code> không kèm tham số, JARVIS sẽ hỏi lại từng tham số.</div>`;
}

function renderAgentsList(agents: AgentItem[]): void {
  const grid = byId("agents-grid");
  if (!grid) return;
  if (!agents.length) {
    grid.innerHTML = `<div class="sd-empty">Không tìm thấy Agent nào phù hợp.</div>`;
    return;
  }
  grid.innerHTML = agents.map(agent => `
    <div class="sd-card sd-agent-card">
      <div class="sd-agent-card-head">
        <div class="sd-agent-icon-box">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
        </div>
        <div class="sd-agent-titles">
          <h4 class="sd-agent-name">${escapeHtml(agent.name)}</h4>
          <span class="sd-agent-id">${escapeHtml(agent.file)}</span>
        </div>
        <span class="sd-agent-status-badge"><span class="sd-badge-dot"></span>Sẵn sàng</span>
      </div>
      <p class="sd-agent-desc">${escapeHtml(agent.description)}</p>
      <div class="sd-agent-cmd-box">
        <div class="sd-agent-cmd-lbl">Gọi thẳng agent trong command-bar:</div>
        <div class="sd-agent-cmd-val">
          <code>${escapeHtml(agentCall(agent))}</code>
          <button type="button" class="sd-copy-cmd-btn" data-copy="${escapeHtml(agentCall(agent))}" title="Sao chép câu lệnh">Sao chép</button>
        </div>
        <div class="sd-agent-cmd-note">Hoặc nói/gõ tự nhiên, bộ định tuyến sẽ tự chọn agent.</div>
      </div>
      ${agent.tools && agent.tools.length ? (() => {
        const shown = agent.tools.slice(0, 5);
        const more = agent.tools.length - 5;
        return `<div class="sd-agent-tools-row">
          <span class="sd-agent-tools-lbl">Tools:</span>
          ${shown.map(t => `<span class="sd-tool-tag">${escapeHtml(t)}</span>`).join('<span class="sd-tool-sep">,</span>')}
          ${more > 0 ? `<span class="sd-tool-more">+${more}</span>` : ""}
        </div>`;
      })() : ""}
    </div>
  `).join("");
}

// ---------------------------------------------------------------------------
// Hooks (from hooks/ directory)
// ---------------------------------------------------------------------------
async function loadHooks(): Promise<void> {
  const grid = byId("hooks-grid");
  const countEl = byId("hooks-count-val");
  if (!grid) return;
  try {
    const catalog = await loadCatalog();
    cachedHooks = catalog.hooks || [];
    if (countEl) countEl.textContent = String(cachedHooks.length);
    renderHooksList(cachedHooks);
  } catch (err) {
    console.error("[settings] failed to load hooks:", err);
    grid.innerHTML = `<div class="sd-empty sd-error-state">Lỗi nạp danh sách Hooks: ${escapeHtml(err)}</div>`;
  }
}

function renderHooksList(hooks: HookItem[]): void {
  const grid = byId("hooks-grid");
  if (!grid) return;
  if (!hooks.length) {
    grid.innerHTML = `<div class="sd-empty">Chưa có Hook nào được nạp từ thư mục <code>hooks/</code>.</div>`;
    return;
  }
  grid.innerHTML = hooks.map(hook => `
    <div class="sd-card sd-agent-card">
      <div class="sd-agent-card-head">
        <div class="sd-agent-icon-box" style="background:rgba(236, 72, 153, 0.1); color:#f472b6; border-color:rgba(236, 72, 153, 0.25);">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-9.33-5"/><path d="m14 15-4-4 4-4"/><path d="M2 12h12a4 4 0 0 1 4 4v2a2 2 0 0 1-4 0v-2"/></svg>
        </div>
        <div class="sd-agent-titles">
          <h4 class="sd-agent-name">${escapeHtml(hook.name)}</h4>
          <span class="sd-agent-id">${escapeHtml(hook.file_path || hook.file)}</span>
        </div>
        <span class="sd-agent-status-badge"><span class="sd-badge-dot"></span>Đang kích hoạt</span>
      </div>
      <p class="sd-agent-desc">${escapeHtml(hook.description)}</p>
      <div class="sd-agent-tools-row" style="margin-top: 10px;">
        <span class="sd-agent-tools-lbl">Sự kiện lắng nghe:</span>
        ${(hook.events || []).map(ev => `<span class="sd-tool-tag" style="background:rgba(236, 72, 153, 0.15); color:#f472b6; border-color:rgba(236,72,153,0.3);">${escapeHtml(ev)}</span>`).join('<span class="sd-tool-sep">,</span>')}
      </div>
    </div>
  `).join("");
}

// ---------------------------------------------------------------------------
// Skills (from skills/ directory)
// ---------------------------------------------------------------------------
async function loadSkills(): Promise<void> {
  const grid = byId("skills-grid");
  const countEl = byId("skills-count-val");
  if (!grid) return;
  try {
    const catalog = await loadCatalog();
    cachedSkills = catalog.skills || [];
    if (countEl) countEl.textContent = String(cachedSkills.length);
    renderSkillsList(cachedSkills);
  } catch (err) {
    console.error("[settings] failed to load skills:", err);
    grid.innerHTML = `<div class="sd-empty sd-error-state">Lỗi nạp danh sách Skills: ${escapeHtml(err)}</div>`;
  }
}

function renderSkillsList(skills: SkillItem[]): void {
  const grid = byId("skills-grid");
  if (!grid) return;
  if (!skills.length) {
    grid.innerHTML = `<div class="sd-empty">Không tìm thấy Kỹ năng nào trong thư mục <code>skills/</code>.</div>`;
    return;
  }
  grid.innerHTML = skills.map(skill => `
    <div class="sd-card sd-agent-card">
      <div class="sd-agent-card-head">
        <div class="sd-agent-icon-box" style="background:rgba(245, 158, 11, 0.1); color:#fbbf24; border-color:rgba(245, 158, 11, 0.25);">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
        </div>
        <div class="sd-agent-titles">
          <h4 class="sd-agent-name">${escapeHtml(skill.name)}</h4>
          <span class="sd-agent-id">${escapeHtml(skill.file_path || skill.folder || "skills/")}</span>
        </div>
        <span class="sd-agent-status-badge"><span class="sd-badge-dot"></span>Đã nạp</span>
      </div>
      <p class="sd-agent-desc">${escapeHtml(skill.description)}</p>
      ${skill.tags && skill.tags.length ? `
        <div class="sd-agent-tools-row">
          <span class="sd-agent-tools-lbl">Từ khoá:</span>
          ${skill.tags.map(t => `<span class="sd-tool-tag">${escapeHtml(t)}</span>`).join('<span class="sd-tool-sep">,</span>')}
        </div>` : ""}
    </div>
  `).join("");
}

// ---------------------------------------------------------------------------
// Prompts (from prompt/ directory)
// ---------------------------------------------------------------------------
async function loadPrompts(): Promise<void> {
  const grid = byId("prompts-grid");
  const countEl = byId("prompts-count-val");
  if (!grid) return;
  try {
    const catalog = await loadCatalog();
    cachedPrompts = catalog.prompts || [];
    if (countEl) countEl.textContent = String(cachedPrompts.length);
    renderPromptsList(cachedPrompts);
  } catch (err) {
    console.error("[settings] failed to load prompts:", err);
    grid.innerHTML = `<div class="sd-empty sd-error-state">Lỗi nạp danh sách Prompts: ${escapeHtml(err)}</div>`;
  }
}

function renderPromptsList(prompts: PromptItem[]): void {
  const grid = byId("prompts-grid");
  if (!grid) return;
  if (!prompts.length) {
    grid.innerHTML = `<div class="sd-empty">Không tìm thấy Prompt nào trong thư mục <code>prompt/</code>.</div>`;
    return;
  }
  grid.innerHTML = prompts.map(p => `
    <div class="sd-card sd-agent-card">
      <div class="sd-agent-card-head">
        <div class="sd-agent-icon-box" style="background:rgba(59, 130, 246, 0.1); color:#60a5fa; border-color:rgba(59, 130, 246, 0.25);">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>
        </div>
        <div class="sd-agent-titles">
          <h4 class="sd-agent-name">${escapeHtml(p.title || p.name)}</h4>
          <span class="sd-agent-id">${escapeHtml(p.file_path || p.name)}</span>
        </div>
        <span class="sd-agent-status-badge"><span class="sd-badge-dot"></span>${p.lines_count || 0} dòng</span>
      </div>
      <p class="sd-agent-desc">${escapeHtml(p.description)}</p>
      <div class="sd-action-row" style="margin-top: 12px;">
        <button type="button" class="settings-btn btn-view-prompt" data-prompt-id="${escapeHtml(p.id)}">Xem nội dung prompt</button>
      </div>
    </div>
  `).join("");
}

// ---------------------------------------------------------------------------
// Commands (from commands/ directory)
// ---------------------------------------------------------------------------
async function loadCommands(): Promise<void> {
  const grid = byId("commands-grid");
  const countEl = byId("commands-count-val");
  if (!grid) return;
  try {
    const catalog = await loadCatalog();
    cachedCommands = catalog.commands || [];
    if (countEl) countEl.textContent = String(cachedCommands.length);
    renderCommandsList(cachedCommands);
  } catch (err) {
    console.error("[settings] failed to load commands:", err);
    grid.innerHTML = `<div class="sd-empty sd-error-state">Lỗi nạp danh sách Commands: ${escapeHtml(err)}</div>`;
  }
}

function renderCommandsList(commands: CommandItem[]): void {
  const grid = byId("commands-grid");
  if (!grid) return;
  if (!commands.length) {
    grid.innerHTML = `<div class="sd-empty">Không tìm thấy Lệnh nào trong thư mục <code>commands/</code>.</div>`;
    return;
  }
  grid.innerHTML = commands.map(cmd => `
    <div class="sd-card sd-agent-card">
      <div class="sd-agent-card-head">
        <div class="sd-agent-icon-box" style="background:rgba(34, 197, 94, 0.1); color:#4ade80; border-color:rgba(34, 197, 94, 0.25);">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>
        </div>
        <div class="sd-agent-titles">
          <h4 class="sd-agent-name">${escapeHtml(cmd.name)}</h4>
          <span class="sd-agent-id">${escapeHtml(cmd.file_path || cmd.file || "commands/")}</span>
        </div>
        <span class="sd-agent-status-badge"><span class="sd-badge-dot"></span>Sẵn sàng</span>
      </div>
      <p class="sd-agent-desc">${escapeHtml(cmd.description)}</p>
      <div class="sd-agent-cmd-box">
        <div class="sd-agent-cmd-lbl">Cú pháp trong command-bar:</div>
        <div class="sd-agent-cmd-val">
          <code>${escapeHtml(commandCall(cmd))}</code>
          <button type="button" class="sd-copy-cmd-btn" data-copy="/${escapeHtml(cmd.name)} " title="Sao chép">Sao chép</button>
        </div>
        ${commandParamsHtml(cmd)}
      </div>
    </div>
  `).join("");
}

// ---------------------------------------------------------------------------
// Plugins (from plugins/ directory)
// ---------------------------------------------------------------------------
async function loadPlugins(): Promise<void> {
  const grid = byId("plugins-grid");
  const countEl = byId("plugins-count-val");
  if (!grid) return;
  try {
    const catalog = await loadCatalog();
    cachedPlugins = catalog.plugins || [];
    if (countEl) countEl.textContent = String(cachedPlugins.length);
    renderPluginsList(cachedPlugins);
  } catch (err) {
    console.error("[settings] failed to load plugins:", err);
    grid.innerHTML = `<div class="sd-empty sd-error-state">Lỗi nạp danh sách Plugins: ${escapeHtml(err)}</div>`;
  }
}

function renderPluginsList(plugins: PluginItem[]): void {
  const grid = byId("plugins-grid");
  if (!grid) return;
  if (!plugins.length) {
    grid.innerHTML = `<div class="sd-empty">Chưa có Plugin nào được nạp từ thư mục <code>plugins/</code>.</div>`;
    return;
  }
  grid.innerHTML = plugins.map(p => `
    <div class="sd-card sd-agent-card">
      <div class="sd-agent-card-head">
        <div class="sd-agent-icon-box" style="background:rgba(168, 85, 247, 0.1); color:#c084fc; border-color:rgba(168, 85, 247, 0.25);">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19.439 7.85c0-1.57.84-2.85 2.561-2.85v-2c-1.721 0-2.561-1.28-2.561-2.85A2.56 2.56 0 0 0 16.88 0h-2c0 1.57-.84 2.85-2.56 2.85-1.72 0-2.56-1.28-2.56-2.85h-2c0 1.57-.84 2.85-2.56 2.85A2.56 2.56 0 0 0 4.64 0h-2A2.56 2.56 0 0 0 .08 2.56c0 1.57-.84 2.85-2.56 2.85v2c1.72 0 2.56 1.28 2.56 2.85 0 1.57-.84 2.85-2.56 2.85v2c1.72 0 2.56 1.28 2.56 2.85A2.56 2.56 0 0 0 2.64 20h2c0-1.57.84-2.85 2.56-2.85 1.72 0 2.56 1.28 2.56 2.85h2c0-1.57.84-2.85 2.56-2.85 1.72 0 2.56 1.28 2.56 2.85h2a2.56 2.56 0 0 0 2.56-2.56c0-1.57.84-2.85 2.56-2.85v-2c-1.72 0-2.56-1.28-2.56-2.85 0-1.57.84-2.85 2.56-2.85v-2a2.56 2.56 0 0 0-2.561-2.56Z"/></svg>
        </div>
        <div class="sd-agent-titles">
          <h4 class="sd-agent-name">${escapeHtml(p.name)}</h4>
          <span class="sd-agent-id">${escapeHtml(p.file_path || p.file || p.runtime || "python")}</span>
        </div>
        <span class="sd-agent-status-badge"><span class="sd-badge-dot"></span>Hoạt động</span>
      </div>
      <p class="sd-agent-desc">${escapeHtml(p.description)}</p>
    </div>
  `).join("");
}

// ---------------------------------------------------------------------------
// MCP Connect (from config/mcp_config.json)
// ---------------------------------------------------------------------------
async function loadMcpServers(): Promise<void> {
  const listEl = byId("mcp-servers-list");
  const totalEl = byId("mcp-total-val");
  const connEl = byId("mcp-connected-val");
  const jsonViewer = byId("mcp-raw-json-viewer");
  if (!listEl) return;
  try {
    const res = await apiGet<any>("/api/mcp/servers");
    if (!res.success) {
      console.error("[settings] MCP servers API error:", res.error);
      listEl.innerHTML = `<div class="sd-empty sd-error-state">Lỗi đọc cấu hình MCP: ${escapeHtml(res.error || "Unknown error")}</div>`;
      return;
    }
    cachedMcpServers = Array.isArray(res.servers) ? res.servers : [];
    // The API never returns args/env (they carry API keys); the viewer shows the safe summary.
    cachedMcpConfig = { servers: cachedMcpServers };
    if (jsonViewer) jsonViewer.textContent = JSON.stringify(cachedMcpConfig, null, 2);
    if (totalEl) totalEl.textContent = String(res.total ?? cachedMcpServers.length);
    if (connEl) connEl.textContent = String(res.connected ?? cachedMcpServers.filter((s: any) => s.status === "connected").length);
    renderMcpList(cachedMcpServers);
  } catch (err) {
    console.error("[settings] failed to load mcp servers:", err);
    listEl.innerHTML = `<div class="sd-empty sd-error-state">Lỗi kết nối API MCP: ${escapeHtml(String(err))}</div>`;
  }
}

function renderMcpList(servers: McpServerItem[]): void {
  const listEl = byId("mcp-servers-list");
  if (!listEl) return;
  if (!servers.length) {
    listEl.innerHTML = `<div class="sd-empty">Chưa có máy chủ MCP nào được cấu hình trong <code>config/mcp_config.json</code>.</div>`;
    return;
  }
  listEl.innerHTML = servers.map(s => {
    const isConn = s.status === "connected";
    // args arrive with secret values already masked by the backend (_redact_args).
    const cmdStr = [s.command || s.url || "stdio", ...(s.args || [])].join(" ");
    const stateText = isConn ? "Đã kết nối" : s.enabled === false ? "Tạm tắt" : s.status === "connecting" ? "Đang kết nối" : "Chưa kết nối";
    return `
      <div class="sd-mcp-item">
        <div class="sd-mcp-head">
          <span class="status-dot ${isConn ? "status-green" : "status-gray"}"></span>
          <span class="sd-mcp-name">${escapeHtml(s.name)}</span>
          <span style="font-size:12px;color:var(--sd-muted);margin-left:4px;">${escapeHtml(s.type || "stdio")}</span>
          <span style="margin-left:auto;font-size:12px;color:${isConn ? "var(--sd-ok)" : "var(--sd-muted)"};">${stateText}</span>
          <button type="button" class="settings-btn" data-mcp-toggle="${escapeHtml(s.name)}" data-mcp-enabled="${s.enabled === false ? "0" : "1"}">${s.enabled === false ? "Bật" : "Tắt"}</button>
        </div>
        <div class="sd-mcp-cmd">
          <code>${escapeHtml(cmdStr)}</code>
        </div>
      </div>
    `;
  }).join("");
}

// ---------------------------------------------------------------------------
// README.md Viewer
// ---------------------------------------------------------------------------
async function loadReadme(): Promise<void> {
  const viewer = byId("readme-viewer");
  if (!viewer) return;
  try {
    const res = await apiGet<any>("/api/system/readme");
    if (res.success && res.content) {
      viewer.innerHTML = formatMarkdown(res.content);
    } else {
      viewer.innerHTML = `<div class="sd-empty sd-error-state">Không tải được tài liệu README.md: ${escapeHtml(res.error || "File không tồn tại")}</div>`;
    }
  } catch (err) {
    console.error("[settings] failed to load readme:", err);
    viewer.innerHTML = `<div class="sd-empty sd-error-state">Lỗi nạp tài liệu README.md: ${escapeHtml(err)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Navigation and Switch Page
// ---------------------------------------------------------------------------
function switchPage(id: SettingsPageId, remember = true): void {
  const previous = currentPage;
  currentPage = id;
  document.querySelectorAll<HTMLElement>(".sd-page").forEach(p => {
    p.hidden = p.dataset.page !== id;
  });
  document.querySelectorAll<HTMLElement>(".sd-nav-item").forEach(item => {
    const pageItem = SETTINGS_PAGES.find(p => p.id === item.dataset.page);
    const iconEl = item.querySelector<MorphIconElement>("morph-icon");
    if (item.dataset.page === id) {
      item.setAttribute("aria-current", "page");
      if (iconEl && pageItem?.activeIcon) iconEl.morphTo(pageItem.activeIcon);
    } else {
      item.removeAttribute("aria-current");
      if (iconEl && pageItem?.icon) iconEl.morphTo(pageItem.icon);
    }
  });

  const pageDef = SETTINGS_PAGES.find(p => p.id === id);
  if (pageDef) setText("settings-page-title", pageDef.label);

  if (id === "overview" || id === "system") startHealthPolling();
  else stopHealthPolling();

  // Memory Control, chat history and the system log are password-locked: leaving a page locks them again, opening one asks for the password
  if (previous !== id) lockAll();
  if (id === "memory" || id === "logs") void enterLockable(id);
  if (id === "agents") void loadAgents();
  if (id === "hooks") void loadHooks();
  if (id === "skills") void loadSkills();
  if (id === "prompts") void loadPrompts();
  if (id === "commands") void loadCommands();
  if (id === "plugins") void loadPlugins();
  if (id === "mcp") void loadMcpServers();
  if (id === "info") void loadReadme();
  if (id === "graphfy") void renderGraphfy(loadCatalog);

  if (remember) {
    try { localStorage.setItem(PAGE_STORAGE_KEY, id); } catch {}
  }
  const content = byId("settings-content");
  if (content) content.scrollTop = 0;
  setDrawer(false);
}

function setDrawer(open: boolean): void {
  const root = byId("settings-panel-inner");
  if (!root) return;
  const wasOpen = root.classList.contains("nav-open");
  root.classList.toggle("nav-open", open);
  const scrim = byId("settings-scrim");
  if (scrim) scrim.hidden = !open;
  byId("settings-menu-toggle")?.setAttribute("aria-expanded", String(open));
  if (menuIcon && wasOpen !== open) menuIcon.morphTo(open ? X : Menu);
}

function startHealthPolling(): void {
  stopHealthPolling();
  void loadStatus();
  void loadDetailedHealth();
  healthTimer = window.setInterval(() => {
    if (document.hidden) return; // nobody is looking: no connection checks
    void loadStatus();
    void loadDetailedHealth();
  }, HEALTH_POLL_INTERVAL_MS);
}

function stopHealthPolling(): void {
  if (healthTimer !== null) {
    clearInterval(healthTimer);
    healthTimer = null;
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
/** Names must match `allowed` in engine/UIUX/ui_engine.py api_save_key (LOCAL_API_KEY, TTS_LOCAL_KEY, LOCAL_URL, …). */
async function saveKey(keyName: string, keyValue: string): Promise<void> {
  const result = await apiPost<{ success?: boolean; error?: string }>("/api/settings/keys", { key_name: keyName, key_value: keyValue });
  if (result?.success === false) throw new Error(result.error || `Không lưu được ${keyName}`);
}

// ---------------------------------------------------------------------------
// Voices (VieNeu)
// ---------------------------------------------------------------------------
interface VoiceItem { name: string; label: string; kind: "preset" | "clone"; }

function fillVoiceSelect(voices: VoiceItem[], selected: string): void {
  const select = byId<HTMLSelectElement>("select-vieneu-voice");
  if (!select) return;
  select.innerHTML = "";
  for (const [title, kind] of [["Giọng có sẵn", "preset"], ["Giọng clone của bạn", "clone"]] as const) {
    const items = voices.filter(v => v.kind === kind);
    if (!items.length) continue;
    const group = document.createElement("optgroup");
    group.label = title;
    for (const v of items) {
      const opt = document.createElement("option");
      opt.value = v.name;
      opt.textContent = v.label;
      group.appendChild(opt);
    }
    select.appendChild(group);
  }
  select.value = selected;
}

async function loadVoices(): Promise<void> {
  const field = byId("field-vieneu-voice");
  try {
    const data = await apiGet<{ engine: string; voices: VoiceItem[]; current: string }>("/api/tts/voices");
    const supported = data.engine === "vieneu"; // edge-tts: không chọn giọng ở đây
    if (field) field.hidden = !supported;
    if (supported) fillVoiceSelect(data.voices, data.current);
    else setText("voice-hint", "Engine TTS hiện tại không hỗ trợ chọn giọng ở đây.");
  } catch (e) {
    setText("voice-hint", `Không lấy được danh sách giọng (${(e as Error).message}). Kiểm tra TTS server.`);
  }
}

async function testKey(kind: "llama" | "fish", key?: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const result = await apiPost<{ valid: boolean; error?: string }>(`/api/settings/test-${kind}`, { key_value: key || undefined });
    return result;
  } catch (err: any) {
    return { valid: false, error: err?.message || String(err) };
  }
}

function bindActions(): void {
  // Save all keys
  const btnSaveKeys = byId<HTMLButtonElement>("btn-save-keys");
  if (btnSaveKeys) {
    decorateActionButton(btnSaveKeys, "save");
    btnSaveKeys.addEventListener("click", () => {
      runAction(btnSaveKeys, async () => {
        clearFeedback("btn-save-keys");
        const llamaKey = byId<HTMLInputElement>("input-llama-key")?.value.trim() ?? "";
        if (!llamaKey) {
          setFeedback("btn-save-keys", "Vui lòng nhập Server API Key", "err");
          throw new Error("Missing Server API Key");
        }
        await saveKey("LOCAL_API_KEY", llamaKey);
        const fishKey = byId<HTMLInputElement>("input-fish-key")?.value.trim() ?? "";
        if (fishKey) await saveKey("TTS_LOCAL_KEY", fishKey);
        setFeedback("btn-save-keys", "Đã lưu cài đặt kết nối thành công!", "ok");
        void loadStatus();
      });
    });
  }

  // Test LLM
  const btnTestLlama = byId<HTMLButtonElement>("btn-test-llama");
  if (btnTestLlama) {
    decorateActionButton(btnTestLlama, "test");
    btnTestLlama.addEventListener("click", () => {
      runAction(btnTestLlama, async () => {
        clearFeedback("btn-test-llama");
        const key = byId<HTMLInputElement>("input-llama-key")?.value.trim() ?? "";
        const res = await testKey("llama", key);
        if (!res.valid) {
          setFeedback("btn-test-llama", res.error || "Khoá không hợp lệ", "err");
          throw new Error(res.error || "Invalid key");
        }
        setFeedback("btn-test-llama", "Kết nối LLM thành công!", "ok");
      });
    });
  }

  // Test Fish/TTS
  const btnTestFish = byId<HTMLButtonElement>("btn-test-fish");
  if (btnTestFish) {
    decorateActionButton(btnTestFish, "test");
    btnTestFish.addEventListener("click", () => {
      runAction(btnTestFish, async () => {
        clearFeedback("btn-test-fish");
        const key = byId<HTMLInputElement>("input-fish-key")?.value.trim() ?? "";
        const res = await testKey("fish", key);
        if (!res.valid) {
          setFeedback("btn-test-fish", res.error || "Khoá TTS không hợp lệ", "err");
          throw new Error(res.error || "Invalid TTS key");
        }
        setFeedback("btn-test-fish", "Kết nối TTS thành công!", "ok");
      });
    });
  }

  // Save LLM URL
  const btnSaveLlamaUrl = byId<HTMLButtonElement>("btn-save-llama-url");
  if (btnSaveLlamaUrl) {
    decorateActionButton(btnSaveLlamaUrl, "save");
    btnSaveLlamaUrl.addEventListener("click", () => {
      runAction(btnSaveLlamaUrl, async () => {
        clearFeedback("btn-save-llama-url");
        const url = byId<HTMLInputElement>("input-llama-url")?.value.trim() ?? "";
        if (!url) throw new Error("Nhập URL máy chủ");
        await saveKey("LOCAL_URL", url);
        setFeedback("btn-save-llama-url", "Đã lưu URL máy chủ!", "ok");
      });
    });
  }

  // Save Voice ID
  const btnSaveVoice = byId<HTMLButtonElement>("btn-save-voice-id");
  if (btnSaveVoice) {
    decorateActionButton(btnSaveVoice, "save");
    btnSaveVoice.addEventListener("click", () => {
      runAction(btnSaveVoice, async () => {
        clearFeedback("btn-save-voice-id");
        const voice = byId<HTMLSelectElement>("select-vieneu-voice")?.value ?? "";
        if (!voice) throw new Error("Chưa chọn giọng");
        // /api/tts/voice switches the running TTS immediately (the .env key alone does not).
        const res = await apiPost<{ success: boolean; error?: string }>("/api/tts/voice", { voice });
        if (!res.success) throw new Error(res.error || "Không lưu được giọng");
        setFeedback("btn-save-voice-id", "Đã lưu giọng đọc!", "ok");
      });
    });
  }

  // Upload a clone sample
  const btnUploadClone = byId<HTMLButtonElement>("btn-upload-clone");
  if (btnUploadClone) {
    decorateActionButton(btnUploadClone, "upload");
    btnUploadClone.addEventListener("click", () => {
      runAction(btnUploadClone, async () => {
        clearFeedback("btn-upload-clone");
        const name = byId<HTMLInputElement>("input-clone-name")?.value.trim() ?? "";
        const file = byId<HTMLInputElement>("input-clone-file")?.files?.[0];
        if (!name || !file) throw new Error("Nhập tên giọng và chọn file mẫu trước");
        const form = new FormData();
        form.append("name", name);
        form.append("file", file);
        const res = await fetch("/api/tts/voices/clone", { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok || data.success === false) throw new Error(data.error || `Lỗi ${res.status}`);
        fillVoiceSelect(data.voices, name);
        setText("voice-hint", `Đã thêm giọng "${name}". Bấm "Lưu giọng" để dùng.`);
      }, "Đã tải mẫu");
    });
  }

  // Save Preferences
  const btnSavePrefs = byId<HTMLButtonElement>("btn-save-prefs");
  if (btnSavePrefs) {
    decorateActionButton(btnSavePrefs, "save");
    btnSavePrefs.addEventListener("click", () => {
      runAction(btnSavePrefs, async () => {
        clearFeedback("btn-save-prefs");
        const user_name = byId<HTMLInputElement>("input-user-name")?.value.trim() ?? "";
        const honorific = byId<HTMLInputElement>("input-honorific")?.value.trim() ?? "";
        const calendar_accounts = byId<HTMLInputElement>("input-calendar-accounts")?.value.trim() ?? "";
        await apiPost("/api/settings/preferences", { user_name, honorific, calendar_accounts });
        setFeedback("btn-save-prefs", "Đã lưu thông tin người dùng!", "ok");
      });
    });
  }

  // Save an edited prompt (prompt/<id>.md)
  const btnPromptSave = byId<HTMLButtonElement>("btn-prompt-save");
  if (btnPromptSave) {
    decorateActionButton(btnPromptSave, "save");
    btnPromptSave.addEventListener("click", () => {
      runAction(btnPromptSave, async () => {
        const id = editingPromptId;
        if (!id) throw new Error("Chưa chọn prompt");
        const content = byId<HTMLTextAreaElement>("prompt-preview-code")?.value ?? "";
        const res = await apiPost<{ success: boolean; error?: string }>("/api/prompts/save", { id, content });
        if (!res.success) throw new Error(res.error || "Không lưu được prompt");
        const cached = cachedPrompts.find(p => p.id === id);
        if (cached) cached.content = content;
      }, "Đã lưu prompt");
    });
  }

  byId("btn-graphfy-reset")?.addEventListener("click", () => resetGraphfyLayout(loadCatalog));

  // Refresh Readme
  byId("btn-refresh-readme")?.addEventListener("click", () => {
    void loadReadme();
  });

  // Toggle MCP JSON viewer
  byId("btn-toggle-mcp-json")?.addEventListener("click", () => {
    const box = byId("mcp-json-container");
    if (box) box.hidden = !box.hidden;
  });

  // Copy MCP JSON
  byId("btn-copy-mcp-json")?.addEventListener("click", () => {
    const text = JSON.stringify(cachedMcpConfig, null, 2);
    void navigator.clipboard.writeText(text);
    const btn = byId("btn-copy-mcp-json");
    if (btn) {
      btn.textContent = "Đã chép!";
      setTimeout(() => { if (btn) btn.textContent = "Sao chép"; }, 2000);
    }
  });

  // Search filters
  byId<HTMLInputElement>("agents-search-input")?.addEventListener("input", (e) => {
    const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
    const filtered = cachedAgents.filter(a => a.name.toLowerCase().includes(q) || a.description.toLowerCase().includes(q) || a.example.toLowerCase().includes(q));
    renderAgentsList(filtered);
  });

  byId<HTMLInputElement>("hooks-search-input")?.addEventListener("input", (e) => {
    const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
    const filtered = cachedHooks.filter(h => h.name.toLowerCase().includes(q) || h.description.toLowerCase().includes(q) || (h.events || []).some(ev => ev.toLowerCase().includes(q)));
    renderHooksList(filtered);
  });

  byId<HTMLInputElement>("skills-search-input")?.addEventListener("input", (e) => {
    const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
    const filtered = cachedSkills.filter(s => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q) || (s.tags || []).some(t => t.toLowerCase().includes(q)));
    renderSkillsList(filtered);
  });

  byId<HTMLInputElement>("prompts-search-input")?.addEventListener("input", (e) => {
    const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
    const filtered = cachedPrompts.filter(p => p.name.toLowerCase().includes(q) || p.title.toLowerCase().includes(q) || p.description.toLowerCase().includes(q));
    renderPromptsList(filtered);
  });

  byId<HTMLInputElement>("commands-search-input")?.addEventListener("input", (e) => {
    const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
    const filtered = cachedCommands.filter(c => c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q) || (c.usage || "").toLowerCase().includes(q));
    renderCommandsList(filtered);
  });

  byId<HTMLInputElement>("plugins-search-input")?.addEventListener("input", (e) => {
    const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
    const filtered = cachedPlugins.filter(p => p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q));
    renderPluginsList(filtered);
  });

  byId<HTMLInputElement>("mcp-search-input")?.addEventListener("input", (e) => {
    const q = (e.target as HTMLInputElement).value.toLowerCase().trim();
    const filtered = cachedMcpServers.filter(s => s.name.toLowerCase().includes(q) || (s.command || "").toLowerCase().includes(q));
    renderMcpList(filtered);
  });

  // MCP: bật/tắt một máy chủ (áp dụng ngay, không cần khởi động lại)
  byId("mcp-servers-list")?.addEventListener("click", async (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-mcp-toggle]");
    if (!btn) return;
    btn.disabled = true;
    try {
      await apiPost(`/api/mcp/servers/${encodeURIComponent(btn.dataset.mcpToggle || "")}/enabled`, { enabled: btn.dataset.mcpEnabled === "0" });
    } catch (err) {
      console.error("[settings] MCP toggle failed:", err);
      alert(`Không đổi được trạng thái MCP: ${err instanceof Error ? err.message : err}`);
    }
    await loadMcpServers();
    setTimeout(() => void loadMcpServers(), 4000);
  });

  // MCP: form thêm máy chủ
  const syncMcpAddFields = () => {
    const type = byId<HTMLSelectElement>("mcp-add-type")?.value || "stdio";
    document.querySelectorAll<HTMLElement>("[data-mcp-field]").forEach(el => {
      el.hidden = el.dataset.mcpField !== (type === "stdio" ? "stdio" : "url");
    });
  };
  byId("mcp-add-type")?.addEventListener("change", syncMcpAddFields);
  byId("btn-mcp-add")?.addEventListener("click", async () => {
    const val = (id: string) => byId<HTMLInputElement | HTMLTextAreaElement>(id)?.value.trim() ?? "";
    const type = byId<HTMLSelectElement>("mcp-add-type")?.value || "stdio";
    const body = {
      name: val("mcp-add-name"),
      type,
      command: type === "stdio" ? val("mcp-add-command") : null,
      args: type === "stdio" ? val("mcp-add-args").split(/\r?\n/).map(l => l.trim()).filter(Boolean) : [],
      url: type === "stdio" ? null : val("mcp-add-url"),
    };
    try {
      await apiPost("/api/mcp/servers", body);
      setFeedback("btn-mcp-add", "Đã thêm, đang kết nối…", "ok");
      ["mcp-add-name", "mcp-add-command", "mcp-add-args", "mcp-add-url"].forEach(id => {
        const el = byId<HTMLInputElement | HTMLTextAreaElement>(id);
        if (el) el.value = "";
      });
      await loadMcpServers();
      setTimeout(() => void loadMcpServers(), 4000);
    } catch (err) {
      setFeedback("btn-mcp-add", err instanceof Error ? err.message : String(err), "err");
    }
  });

  // Prompt preview modal open/close
  document.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;
    const viewBtn = target.closest<HTMLElement>(".btn-view-prompt");
    if (viewBtn) {
      const pid = viewBtn.dataset.promptId;
      const prompt = cachedPrompts.find(p => p.id === pid);
      if (prompt) {
        editingPromptId = prompt.id;
        setText("prompt-preview-title", `Prompt: ${prompt.title || prompt.name}`);
        setText("prompt-preview-file", prompt.file_path || `prompt/${prompt.id}.md`);
        const codeEl = byId<HTMLTextAreaElement>("prompt-preview-code");
        if (codeEl) codeEl.value = prompt.content ?? "";
        clearFeedback("btn-prompt-save");
        const modal = byId("prompt-preview-modal");
        if (modal) modal.hidden = false;
      }
    }
    if (target.id === "prompt-preview-close" || target.id === "prompt-preview-modal") {
      const modal = byId("prompt-preview-modal");
      if (modal) modal.hidden = true;
    }

    // Copy command buttons
    const copyBtn = target.closest<HTMLElement>(".sd-copy-cmd-btn");
    if (copyBtn) {
      const txt = copyBtn.dataset.copy;
      if (txt) {
        void navigator.clipboard.writeText(txt);
        const old = copyBtn.textContent;
        copyBtn.textContent = "Đã chép!";
        setTimeout(() => { copyBtn.textContent = old; }, 1500);
      }
    }
  });
}

// ---------------------------------------------------------------------------
// First-time setup
// ---------------------------------------------------------------------------
const SETUP_FLOW: SettingsPageId[] = ["connect", "voice", "user"];
let setupStep = 0;

function enterSetupMode(): void {
  byId("settings-panel-inner")?.classList.add("setup-mode");
  const welcome = byId("settings-welcome");
  if (welcome) welcome.hidden = false;
  const nav = byId("setup-nav");
  if (nav) nav.hidden = false;
  setupStep = 0;
  updateSetupStep();
}

function exitSetupMode(): void {
  byId("settings-panel-inner")?.classList.remove("setup-mode");
  const welcome = byId("settings-welcome");
  if (welcome) welcome.hidden = true;
  const nav = byId("setup-nav");
  if (nav) nav.hidden = true;
}

function updateSetupStep(): void {
  const pageId = SETUP_FLOW[setupStep];
  switchPage(pageId, false);
  const nextBtn = byId<HTMLButtonElement>("btn-setup-next");
  if (!nextBtn) return;
  const isLast = setupStep >= SETUP_FLOW.length - 1;
  nextBtn.textContent = isLast ? "Hoàn tất" : "Tiếp";
}

// ---------------------------------------------------------------------------
// Open and Close Settings Panel
// ---------------------------------------------------------------------------
export function openSettings(pageId?: SettingsPageId): void {
  ensureMounted();
  if (!container) return;
  isOpen = true;
  container.classList.add("open");
  container.removeAttribute("aria-hidden");
  // main.ts pauses the orb on this event and resumes it on close unless map/media is full screen.
  window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: true } }));
  catalogPromise = null;

  let saved: string | null = null;
  try { saved = localStorage.getItem(PAGE_STORAGE_KEY); } catch { /* storage blocked */ }
  const target = pageId || (saved as SettingsPageId) || "overview";
  switchPage(SETTINGS_PAGES.some(p => p.id === target) ? target : "overview", false);
  void loadStatus();
  void loadPreferences();
  void loadVoices();
}

export function closeSettings(): void {
  if (!container || !isOpen) return;
  isOpen = false;
  container.classList.remove("open");
  container.setAttribute("aria-hidden", "true");
  exitSetupMode();
  stopHealthPolling();
  setDrawer(false);
  lockAll();
  window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: false } }));
}

function ensureMounted(): void {
  if (container) return;
  container = document.createElement("div");
  container.id = "settings-container";
  container.setAttribute("aria-hidden", "true");
  container.innerHTML = buildSettingsHTML();
  document.body.appendChild(container);

  // Mount MorphIcons on Topbar
  menuIcon = makeIcon(Menu, 18);
  byId("settings-close")?.appendChild(makeIcon(X, 18));
  byId("settings-menu-toggle")?.appendChild(menuIcon);

  sidebarToggleIcon = makeIcon(PanelLeftClose, 18);
  byId("sidebar-toggle-icon")?.appendChild(sidebarToggleIcon);

  // Nav morph icons
  document.querySelectorAll<HTMLElement>(".sd-nav-item").forEach(item => {
    const pid = item.dataset.page as SettingsPageId;
    const def = SETTINGS_PAGES.find(p => p.id === pid);
    const box = item.querySelector<HTMLElement>(".sd-nav-icon");
    if (box && def) box.appendChild(makeIcon(def.icon, 18));
  });

  // Topbar and Nav events
  byId("settings-close")?.addEventListener("click", closeSettings);
  byId("settings-menu-toggle")?.addEventListener("click", () => {
    setDrawer(!byId("settings-panel-inner")?.classList.contains("nav-open"));
  });
  byId("settings-sidebar-toggle")?.addEventListener("click", () => {
    setSidebarCollapsed(!isSidebarCollapsed);
  });
  byId("settings-scrim")?.addEventListener("click", () => setDrawer(false));
  byId("settings-nav")?.addEventListener("click", (event) => {
    const item = (event.target as HTMLElement).closest<HTMLElement>(".sd-nav-item");
    if (!item) return;
    const id = item.dataset.page as SettingsPageId;
    if (id) switchPage(id);
  });

  // Setup Next button
  byId("btn-setup-next")?.addEventListener("click", () => {
    setupStep++;
    if (setupStep >= SETUP_FLOW.length) closeSettings();
    else updateSetupStep();
  });

  // Global keydown (Esc to close)
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen) {
      if (byId("prompt-preview-modal") && !byId("prompt-preview-modal")!.hidden) {
        byId("prompt-preview-modal")!.hidden = true;
        return;
      }
      closeSettings();
    }
  });

  // Initialize Memory Center and bind Actions
  initMemoryCenter(async () => { await loadStatus(); });
  initLogsPage();
  bindActions();

  // Restore sidebar collapsed preference
  try {
    if (localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1") {
      setSidebarCollapsed(true, false);
    }
  } catch {}
}

export async function checkFirstTimeSetup(): Promise<void> {
  try {
    const status = await apiGet<any>("/api/settings/status");
    if (!status.env_keys_set?.llama) {
      openSettings("connect");
      enterSetupMode();
    }
  } catch (err) {
    console.warn("[settings] first time setup check failed:", err);
  }
}
