/**
 * Memory Control Center (Settings → Bộ nhớ). Moved out of settings.ts; the
 * element ids are the ones settings-pages.ts renders.
 */
import { apiGet, apiPost, fetchWithTimeout } from "./api";
import { registerLockable, isUnlocked } from "./lock";
import { decorateActionButton, makeIcon, runAction, type ActionKind } from "../icons";
import type { MorphIconElement } from "morphicons/element";
import {
  Brain, Lightbulb, Dna, Sprout,
  Sparkles, Database,
  Workflow, RotateCw,
  Target, CheckCheck,
  Layers, Bookmark,
  MessageSquare, MessagesSquare,
  FileText, FileCheck,
  Search, ChevronLeft, ChevronRight,
  type IconNode,
} from "lucide";

let onMemoryDataChanged: () => Promise<unknown> = async () => {};


type MemoryCategoryId =
  | "learning"
  | "workflow"
  | "outcome"
  | "conversation"
  | "notes"
  | "evolution";

interface MemoryCategory {
  id: MemoryCategoryId;
  label: string;
  endpoint: string;
  responseKey: string;
  color: string;
  icon: IconNode;
  activeIcon: IconNode;
}

interface MemoryItem {
  id: number | string;
  created_at?: number;
  updated_at?: number;
  [key: string]: unknown;
}

const MEMORY_PAGE_SIZE = 50;
const MEMORY_CATEGORIES: MemoryCategory[] = [
  { id: 'learning', label: "Learnings", endpoint: "/api/learnings/list", responseKey: "learnings", color: "#a78bfa", icon: Brain, activeIcon: Lightbulb },
  { id: 'workflow', label: "Workflows", endpoint: "/api/workflows/list", responseKey: "workflows", color: "#22d3ee", icon: Workflow, activeIcon: RotateCw },
  { id: 'outcome', label: "Agent Outcomes", endpoint: "/api/outcomes/list", responseKey: "outcomes", color: "#f59e0b", icon: Target, activeIcon: CheckCheck },
  { id: 'conversation', label: "Conversations", endpoint: "/api/conversations", responseKey: "conversations", color: "#60a5fa", icon: MessageSquare, activeIcon: MessagesSquare },
  { id: 'notes', label: "Notes", endpoint: "/api/notes/list", responseKey: "notes", color: "#94a3b8", icon: FileText, activeIcon: FileCheck },
  // Hai file tiến hóa (STYLE.md đang áp dụng, Evolution.md nhật ký): đọc và sửa tay ở đây, không có chỗ nào khác. Là file nên không xoá được.
  { id: 'evolution', label: "Evolution", endpoint: "/api/evolution/list", responseKey: "items", color: "#34d399", icon: Dna, activeIcon: Sprout },
];

const EDITABLE_MEMORY_FIELDS: Record<MemoryCategoryId, string[]> = {
  learning: ["type", "semantic_key", "content", "source", "importance", "embedding"],
  workflow: ["agent", "intent", "tool_chain", "argument_keys", "sample_queries", "success_evidence", "validation_count", "status", "wiki_path"],
  outcome: ["agent", "query", "status", "result", "traces"],
  conversation: ["role", "content", "session_id"],
  notes: ["title", "content", "tags"],
  evolution: ["content"],
};

let activeMemoryKind: MemoryCategoryId = "learning";
let activeMemoryItems: MemoryItem[] = [];
let selectedMemoryId: string | null = null;
let memoryOffset = 0;
let memoryTotal = 0;
let memorySummary: Record<string, number> = {};
let mobileDetailActive = false;
// Chọn nhiều để xoá: chỉ trong trang đang hiển thị, xoá sạch mỗi lần tải lại danh sách.
const bulkSelectedIds = new Set<string>();
let bulkAnchorId: string | null = null;
let bulkDeleting = false;

function updateMobileLayoutState(): void {
  const layout = document.querySelector(".memory-control-layout");
  if (layout) {
    layout.classList.toggle("show-detail-mobile", mobileDetailActive);
  }
}

function escapeMemoryHtml(value: unknown): string {
  const chars: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  };
  return String(value ?? "").replace(/[&<>"']/g, char => chars[char]);
}

function memoryValueText(value: unknown): string {
  if (value && typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value ?? "");
}

function selectedMemoryItem(): MemoryItem | undefined {
  return activeMemoryItems.find(item => String(item.id) === selectedMemoryId);
}

function formatFieldLabel(field: string): string {
  const map: Record<string, string> = {
    type: "Loại (Type)",
    id: "Mã bản ghi (ID)",
    created_at: "Tạo lúc (Created At)",
    updated_at: "Cập nhật lúc (Updated At)",
    semantic_key: "Khóa ngữ nghĩa (Semantic Key)",
    mem_type: "Loại bộ nhớ (Type)",
    memory_id: "Memory ID",
    wiki_scope: "Wiki Scope",
    tool_chain: "Tool Chain",
    argument_keys: "Tham số đầu vào (Argument Keys)",
    sample_queries: "Mẫu câu truy vấn (Sample Queries)",
    success_evidence: "Bằng chứng thành công (Success Evidence)",
    validation_count: "Số lần kiểm chứng (Validation Count)",
    status: "Trạng thái (Status)",
    wiki_path: "Đường dẫn Wiki (Wiki Path)",
    query: "Câu hỏi / Truy vấn (Query)",
    result: "Kết quả (Result)",
    traces: "Dấu vết thực thi (Traces)",
    agent: "Tên Agent",
    importance: "Độ quan trọng (Importance 1-10)",
    source: "Nguồn gốc (Source)",
    content: "Nội dung (Content)",
    title: "Tiêu đề (Title)",
    tags: "Nhãn thẻ (Tags)",
    role: "Vai trò (Role)",
    session_id: "Phiên làm việc (Session ID)",
    embedding: "Vector embedding (JSON, để trống = xoá, gõ recompute = tính lại)",
    embedding_dim: "Số chiều embedding",
    embedding_model: "Model embedding",
  };
  if (map[field]) return map[field];
  return field
    .split("_")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function formatMetadataValue(key: string, value: unknown): string {
  if (typeof value === "number" && (key.includes("time") || key.includes("at") || (value > 1500000000 && value < 2500000000))) {
    const millis = value > 1e11 ? value : value * 1000;
    try {
      return new Date(millis).toLocaleString("vi-VN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return String(value);
    }
  }
  return memoryValueText(value);
}

function renderMemoryCategoryNav(): void {
  const nav = document.getElementById("memory-category-nav");
  if (!nav) return;
  const countKeys: Partial<Record<MemoryCategoryId, string>> = {
    learning: "learnings",
    workflow: "workflows",
    outcome: "outcomes",
    conversation: "conversations",
  };

  const existingButtons = nav.querySelectorAll<HTMLButtonElement>(".sd-mem-cat-btn");
  if (existingButtons.length === MEMORY_CATEGORIES.length) {
    existingButtons.forEach(btn => {
      const kind = btn.dataset.memoryKind as MemoryCategoryId;
      const category = MEMORY_CATEGORIES.find(c => c.id === kind);
      if (!category) return;
      const active = kind === activeMemoryKind;
      btn.classList.toggle("active", active);
      const iconEl = btn.querySelector<MorphIconElement>("morph-icon");
      if (iconEl) {
        iconEl.morphTo(active ? category.activeIcon : category.icon);
      }
      const countKey = countKeys[kind];
      const countNum = countKey ? (memorySummary[countKey] ?? 0) : null;
      let badgeEl = btn.querySelector<HTMLElement>(".sd-mem-cat-badge");
      if (countNum !== null) {
        if (!badgeEl) {
          badgeEl = document.createElement("span");
          badgeEl.className = "sd-mem-cat-badge";
          btn.appendChild(badgeEl);
        }
        badgeEl.textContent = String(countNum);
      } else if (badgeEl) {
        badgeEl.remove();
      }
    });
    return;
  }

  nav.innerHTML = "";
  MEMORY_CATEGORIES.forEach(category => {
    const active = category.id === activeMemoryKind;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `sd-mem-cat-btn${active ? " active" : ""}`;
    btn.dataset.memoryKind = category.id;
    btn.style.setProperty("--cat-color", category.color);

    const iconWrap = document.createElement("span");
    iconWrap.className = "sd-mem-cat-icon";
    iconWrap.style.color = category.color;
    iconWrap.appendChild(makeIcon(active ? category.activeIcon : category.icon, 16, 2));
    btn.appendChild(iconWrap);

    const labelWrap = document.createElement("span");
    labelWrap.className = "sd-mem-cat-label";
    labelWrap.textContent = category.label;
    btn.appendChild(labelWrap);

    const countKey = countKeys[category.id];
    const countNum = countKey ? (memorySummary[countKey] ?? 0) : null;
    if (countNum !== null) {
      const badge = document.createElement("span");
      badge.className = "sd-mem-cat-badge";
      badge.textContent = String(countNum);
      btn.appendChild(badge);
    }
    nav.appendChild(btn);
  });
}

async function loadMemorySummary(): Promise<void> {
  try {
    const data = await apiGet<{ success: boolean; counts: Record<string, number> }>("/api/memory-control/summary");
    if (data.success) memorySummary = data.counts;
  } catch (error) {
    console.error("[settings] failed to load memory summary:", error);
  }
  renderMemoryCategoryNav();
}

async function loadMemoryList(): Promise<void> {
  if (!isUnlocked("memory")) return;
  const container = document.getElementById("memory-list-container");
  if (!container) return;
  container.innerHTML = '<div class="sd-empty sd-loading-state"><span>Đang tải danh sách bản ghi…</span></div>';
  const searchQuery = (document.getElementById("memory-search-input") as HTMLInputElement)?.value.trim() || "";
  const category = MEMORY_CATEGORIES.find(item => item.id === activeMemoryKind)!;
  bulkSelectedIds.clear();
  bulkAnchorId = null;
  try {
    await loadMemorySummary();
    const query = new URLSearchParams({
      q: searchQuery,
      limit: String(MEMORY_PAGE_SIZE),
      offset: String(memoryOffset),
    });
    const notesPath = searchQuery ? "/api/notes/search" : "/api/notes/list";
    const endpoint = activeMemoryKind === "notes" ? notesPath : category.endpoint;
    const data = await apiGet<Record<string, unknown>>(`${endpoint}?${query.toString()}`);
    if (!data.success) throw new Error(String(data.error || "request_failed"));
    activeMemoryItems = (data.items || data[category.responseKey] || []) as MemoryItem[];
    memoryTotal = Number(data.total ?? activeMemoryItems.length);
    if (!selectedMemoryItem()) {
      selectedMemoryId = activeMemoryItems.length ? String(activeMemoryItems[0].id) : null;
    }
    renderMemoryItems();
  } catch (error) {
    if (!isUnlocked("memory")) return; // a 401 locked the page while loading: keep it empty
    container.innerHTML = `<div class="sd-empty sd-error-state">Lỗi tải bộ nhớ: ${escapeMemoryHtml(error)}</div>`;
  }
}

function memoryItemTitle(item: MemoryItem): string {
  return memoryValueText(
    item.title ?? item.semantic_key ?? item.intent ?? item.query ?? item.content ?? `#${item.id}`
  );
}

function memoryItemPreview(item: MemoryItem): string {
  const value = item.content ?? item.result ?? item.success_evidence ?? item.mem_type ?? item.source ?? "";
  return memoryValueText(value).replace(/\s+/g, " ").slice(0, 160);
}

function renderMemoryField(field: string, value: unknown): string {
  const text = memoryValueText(value);
  const rows = activeMemoryKind === "evolution" ? 16 : 4; // một file luật dài hơn một bản ghi
  const isLong = ["content", "result", "traces", "tool_chain", "argument_keys", "sample_queries", "success_evidence", "embedding"].includes(field);
  const isNumber = ["importance", "validation_count", "memory_id"].includes(field);
  const typeTag = isNumber ? "Số" : (isLong ? "Văn bản lớn" : "Chuỗi ký tự");
  const control = isLong
    ? `<textarea data-memory-field="${field}" rows="${rows}" class="sd-memory-input sd-memory-textarea" placeholder="Nhập ${escapeMemoryHtml(formatFieldLabel(field))}…">${escapeMemoryHtml(text)}</textarea>`
    : `<input data-memory-field="${field}" type="${isNumber ? "number" : "text"}" value="${escapeMemoryHtml(text)}" class="sd-memory-input" placeholder="Nhập ${escapeMemoryHtml(formatFieldLabel(field))}…" />`;
  return `
    <div class="sd-mem-field-card">
      <div class="sd-mem-field-head">
        <label class="sd-mem-field-label">${escapeMemoryHtml(formatFieldLabel(field))}</label>
        <span class="sd-mem-field-type">${typeTag}</span>
      </div>
      ${control}
    </div>
  `;
}

function renderMemoryItems(): void {
  const list = document.getElementById("memory-list-container");
  const detail = document.getElementById("memory-detail-container");
  const pageStatus = document.getElementById("memory-page-status");
  const previous = document.getElementById("memory-page-prev") as HTMLButtonElement | null;
  const next = document.getElementById("memory-page-next") as HTMLButtonElement | null;
  if (!list || !detail) return;
  const category = MEMORY_CATEGORIES.find(item => item.id === activeMemoryKind)!;
  renderMemoryCategoryNav();

  // Nút "Tính lại tất cả embedding": hàng riêng dưới toolbar (toolbar hẹp, nhét chung sẽ tràn khung); chỉ cho Learnings.
  const toolbar = list.parentElement?.querySelector(".sd-memory-toolbar");
  if (toolbar) {
    const row = list.parentElement!.querySelector<HTMLElement>("#memory-reembed-row");
    if (activeMemoryKind === "learning") {
      if (!row) {
        const newRow = document.createElement("div");
        newRow.id = "memory-reembed-row";
        newRow.className = "sd-memory-extra";
        newRow.innerHTML = `<button type="button" class="settings-btn sd-btn-reembed-all" id="memory-reembed-all-btn" data-action="refresh"><span class="btn-label">Tính lại tất cả embedding</span></button>`;
        const btn = newRow.querySelector<HTMLButtonElement>("button")!;
        decorateActionButton(btn, "refresh");
        btn.addEventListener("click", (e) => reembedAllLearnings(e.currentTarget as HTMLButtonElement));
        toolbar.insertAdjacentElement("afterend", newRow);
      }
    } else if (row) {
      row.remove();
    }
  }
  if (!activeMemoryItems.length) {
    list.innerHTML = `
      <div class="sd-mem-empty-box">
        <div class="sd-mem-empty-icon" data-empty-icon></div>
        <div class="sd-mem-empty-title">Không có dữ liệu</div>
        <div class="sd-mem-empty-sub">Nhóm ${escapeMemoryHtml(category.label)} chưa có bản ghi nào hoặc không khớp từ khóa tìm kiếm.</div>
      </div>
    `;
    detail.innerHTML = `
      <div class="sd-mem-empty-box" style="margin:auto;">
        <div class="sd-mem-empty-icon" data-empty-icon></div>
        <div class="sd-mem-empty-title">Chưa chọn bản ghi</div>
        <div class="sd-mem-empty-sub">Chọn một bản ghi từ danh sách bên cạnh để xem và chỉnh sửa thông tin chi tiết.</div>
      </div>
    `;
    list.querySelectorAll<HTMLElement>("[data-empty-icon]").forEach(el => el.replaceChildren(makeIcon(category.icon, 22, 2)));
    detail.querySelectorAll<HTMLElement>("[data-empty-icon]").forEach(el => el.replaceChildren(makeIcon(category.icon, 22, 2)));
  } else {
    list.innerHTML = activeMemoryItems.map(item => {
      const selected = String(item.id) === selectedMemoryId;
      const id = escapeMemoryHtml(item.id);
      const checked = bulkSelectedIds.has(String(item.id)) ? " checked" : "";
      const secondaryBadge = item.type || item.mem_type || item.status;
      const badgeHtml = secondaryBadge
        ? `<span class="sd-mem-card-type-tag">${escapeMemoryHtml(String(secondaryBadge))}</span>`
        : "";
      return `
        <div role="button" tabindex="0" data-memory-record-id="${id}" class="sd-mem-record-card${selected ? " selected" : ""}" style="--item-color:${category.color};">
          ${activeMemoryKind === "evolution" ? "" : `<input type="checkbox" data-memory-select="${id}" aria-label="Chọn bản ghi #${id}"${checked} class="sd-mem-card-check" />`}
          <div class="sd-mem-card-body">
            <div class="sd-mem-card-header">
              <span class="sd-mem-card-title">${escapeMemoryHtml(memoryItemTitle(item))}</span>
              ${badgeHtml}
            </div>
            <div class="sd-mem-card-preview">${escapeMemoryHtml(memoryItemPreview(item))}</div>
          </div>
        </div>
      `;
    }).join("");

    const item = selectedMemoryItem() || activeMemoryItems[0];
    selectedMemoryId = String(item.id);
    const fields = EDITABLE_MEMORY_FIELDS[activeMemoryKind];
    const metadataEntries = Object.entries(item).filter(([key]) => !fields.includes(key) && key !== "editable");
    const metadataHtml = metadataEntries.length > 0 ? `
      <div class="sd-mem-meta-card">
        <div class="sd-mem-meta-title">Thông tin hệ thống</div>
        <div class="sd-mem-meta-grid">
          ${metadataEntries.map(([key, value]) => `
            <div class="sd-mem-meta-row">
              <span class="sd-mem-meta-key">${escapeMemoryHtml(formatFieldLabel(key))}:</span>
              <span class="sd-mem-meta-val">${escapeMemoryHtml(formatMetadataValue(key, value))}</span>
            </div>
          `).join("")}
        </div>
      </div>
    ` : "";

    detail.innerHTML = `
      <div class="sd-mem-detail-head">
        <div class="sd-mem-detail-title-group">
          <button class="settings-btn memory-back-btn" data-memory-action="back">← Danh sách</button>
          <div>
            <div class="sd-mem-detail-badge" style="--cat-color:${category.color};">
              <span class="sd-mem-detail-badge-icon"></span>
              <span>${escapeMemoryHtml(category.label)}</span>
            </div>
            <h3 class="sd-mem-detail-id">${activeMemoryKind === "evolution" ? escapeMemoryHtml(item.title) : `Bản ghi #${escapeMemoryHtml(item.id)}`}</h3>
          </div>
        </div>
        ${activeMemoryKind === "evolution" ? "" : `<button class="settings-btn danger" id="memory-delete-btn" data-memory-action="delete" data-action="delete">
          Xóa
        </button>`}
      </div>
      <div class="sd-mem-detail-form">
        ${fields.map(field => renderMemoryField(field, item[field])).join("")}
      </div>
      ${metadataHtml}
      <div class="sd-mem-detail-actions">
        <button class="settings-btn primary" id="memory-save-btn" data-memory-action="save" data-action="save">
          Lưu thay đổi
        </button>
        ${activeMemoryKind === "learning" ? `
        <button class="settings-btn" id="memory-reembed-btn" data-memory-action="reembed" data-action="refresh">
          <span class="btn-label">Tính lại embedding</span>
        </button>
        ` : ""}
      </div>
    `;
    const badgeIconEl = detail.querySelector<HTMLElement>(".sd-mem-detail-badge-icon");
    if (badgeIconEl) {
      badgeIconEl.replaceChildren(makeIcon(category.activeIcon, 14, 2));
    }
    detail.querySelectorAll<HTMLButtonElement>("[data-action]").forEach(btn => decorateActionButton(btn, btn.dataset.action as ActionKind));
  }

  if (pageStatus) pageStatus.textContent = `${Math.min(memoryOffset + 1, memoryTotal)}–${Math.min(memoryOffset + activeMemoryItems.length, memoryTotal)} / ${memoryTotal}`;
  if (previous) previous.disabled = memoryOffset === 0;
  if (next) next.disabled = memoryOffset + MEMORY_PAGE_SIZE >= memoryTotal;
  const selectAll = document.getElementById("memory-select-all") as HTMLInputElement | null;
  if (selectAll) {
    selectAll.checked = activeMemoryItems.length > 0 && bulkSelectedIds.size === activeMemoryItems.length;
    selectAll.indeterminate = bulkSelectedIds.size > 0 && !selectAll.checked;
    selectAll.disabled = bulkDeleting || !activeMemoryItems.length || activeMemoryKind === "evolution";
  }
  const bulkButton = document.getElementById("memory-bulk-delete") as HTMLButtonElement | null;
  if (bulkButton) {
    const bulkLabel = bulkButton.querySelector(".btn-label");
    if (bulkLabel) bulkLabel.textContent = `Xoá đã chọn (${bulkSelectedIds.size})`;
    bulkButton.disabled = bulkDeleting || bulkSelectedIds.size === 0;
  }
  updateMobileLayoutState();
}

async function reembedSelectedLearning(btn: HTMLButtonElement): Promise<void> {
  const item = selectedMemoryItem();
  if (!item || activeMemoryKind !== "learning") return;
  await runAction(btn, async () => {
    const result = await apiPost<{ success: boolean; updated?: number; error?: string }>("/api/learnings/reembed", { id: Number(item.id) });
    if (!result.success) throw new Error(`Không thể tính lại embedding: ${result.error || "reembed_failed"}`);
  }, `Đã tính lại embedding cho #${item.id}`);
  await loadMemoryList();
}

async function reembedAllLearnings(btn: HTMLButtonElement): Promise<void> {
  if (activeMemoryKind !== "learning") return;
  await runAction(btn, async () => {
    if (!confirm("Tính lại embedding cho TOÀN BỘ bản ghi học? Đây có thể mất vài phút.")) return false;
    const result = await apiPost<{ success: boolean; updated?: number; error?: string }>("/api/learnings/reembed", { id: null });
    if (!result.success) throw new Error(`Không thể tính lại embedding: ${result.error || "reembed_failed"}`);
  }, `Đã tính lại embedding cho tất cả`);
  await loadMemoryList();
}

/** Xoá lần lượt từng mục đã chọn qua API xoá hiện có (một lần xác nhận cho cả nhóm). */
async function deleteBulkSelectedRecords(btn: HTMLButtonElement): Promise<void> {
  if (bulkDeleting || !bulkSelectedIds.size) return;
  const kind = activeMemoryKind;
  const category = MEMORY_CATEGORIES.find(item => item.id === kind)!;
  const targets = activeMemoryItems.filter(item => bulkSelectedIds.has(String(item.id)));
  const names = targets.slice(0, 10).map(item => `• ${memoryItemTitle(item).slice(0, 60)}`).join("\n");
  const more = targets.length > 10 ? `\n… và ${targets.length - 10} mục khác` : "";
  let ran = false;

  await runAction(btn, async () => {
    if (!confirm(`Xoá ${targets.length} bản ghi ${category.label}?\n\n${names}${more}`)) return false;
    ran = true;
    bulkDeleting = true;
    renderMemoryItems();
    const failures: string[] = [];
    for (const item of targets) {
      try {
        const result = kind === "notes"
          ? await (await fetchWithTimeout(`/api/notes/delete?id=${encodeURIComponent(String(item.id))}`, { method: "DELETE" })).json()
          : await apiPost<{ success: boolean; code?: string; error?: string }>("/api/memory-control/delete", { kind, id: Number(item.id) });
        if (!result.success) throw new Error(result.code || result.error || "delete_failed");
      } catch (error) {
        failures.push(`#${item.id} ${memoryItemTitle(item).slice(0, 40)}: ${error instanceof Error ? error.message : error}`);
      }
    }
    bulkDeleting = false;
    if (failures.length) {
      throw new Error(`Đã xoá ${targets.length - failures.length}/${targets.length}. Lỗi:\n${failures.join("\n")}`);
    }
  }, "Đã xoá");

  bulkDeleting = false;
  if (!ran) return;
  selectedMemoryId = null;
  await loadMemoryList();
  await onMemoryDataChanged();
}

async function saveSelectedMemoryRecord(btn: HTMLButtonElement): Promise<void> {
  const item = selectedMemoryItem();
  const detail = document.getElementById("memory-detail-container");
  if (!item || !detail) return;
  const values: Record<string, unknown> = {};
  detail.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("[data-memory-field]").forEach(control => {
    const field = control.dataset.memoryField!;
    values[field] = control.type === "number" ? Number(control.value) : control.value;
  });
  const ok = await runAction(btn, async () => {
    const result = activeMemoryKind === "notes"
      ? await apiPost<Record<string, unknown>>("/api/notes/update", { id: item.id, ...values })
      : activeMemoryKind === "evolution"
        ? await apiPost<Record<string, unknown>>("/api/evolution/update", { id: String(item.id), content: values.content })
        : await apiPost<Record<string, unknown>>("/api/memory-control/update", { kind: activeMemoryKind, id: Number(item.id), values });
    if (!result.success) throw new Error(`Không thể lưu bản ghi: ${String(result.error || result.code || "update_failed")}`);
  });
  if (ok) await loadMemoryList();
}

async function deleteSelectedMemoryRecord(btn: HTMLButtonElement): Promise<void> {
  const item = selectedMemoryItem();
  if (!item) return;
  const kind = activeMemoryKind;
  const ok = await runAction(btn, async () => {
    if (kind === "notes") {
      if (!confirm("Xóa ghi chú đã chọn?")) return false;
      const response = await fetchWithTimeout(`/api/notes/delete?id=${encodeURIComponent(String(item.id))}`, { method: "DELETE" });
      const result = await response.json();
      if (!result.success) throw new Error(`Không thể xóa bản ghi: ${result.error || "delete_failed"}`);
      return;
    }
    const dependencyUrl = `/api/memory-control/dependencies?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(String(item.id))}`;
    const dependency = await apiGet<{ success: boolean; preview?: unknown; code?: string }>(dependencyUrl);
    if (!dependency.success) throw new Error(`Không thể xóa bản ghi: ${dependency.code || "dependency_preview_failed"}`);
    const previewText = JSON.stringify(dependency.preview, null, 2);
    if (!confirm(`Xác nhận xóa sau khi kiểm tra quan hệ:\n\n${previewText}`)) return false;
    const result = await apiPost<{ success: boolean; code?: string }>("/api/memory-control/delete", { kind, id: Number(item.id) });
    if (!result.success) throw new Error(`Không thể xóa bản ghi: ${result.code || "delete_failed"}`);
  }, "Đã xoá");
  if (!ok) return;
  selectedMemoryId = null;
  await loadMemoryList();
  await onMemoryDataChanged();
}

/** While locked (settings/lock.ts) nothing stays loaded: drops every record from memory and page. */
function clearMemoryView(): void {
  activeMemoryItems = [];
  memorySummary = {};
  selectedMemoryId = null;
  memoryOffset = 0;
  memoryTotal = 0;
  mobileDetailActive = false;
  bulkSelectedIds.clear();
  for (const id of ["memory-list-container", "memory-detail-container"]) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = "";
  }
  const search = document.getElementById("memory-search-input") as HTMLInputElement | null;
  if (search) search.value = "";
  const pageStatus = document.getElementById("memory-page-status");
  if (pageStatus) pageStatus.textContent = "";
  renderMemoryCategoryNav();
}

/** Wires every Memory Center control. Call once, after the panel markup exists. */
export function initMemoryCenter(onDataChanged: () => Promise<unknown>): void {
  onMemoryDataChanged = onDataChanged;

  registerLockable({
    id: "memory",
    root: () => document.getElementById("page-memory"),
    onUnlock: async () => { memoryOffset = 0; await loadMemoryList(); },
    onLock: clearMemoryView,
  });

  const searchBtn = document.getElementById("btn-memory-search") as HTMLButtonElement | null;
  if (searchBtn && !searchBtn.querySelector("morph-icon")) {
    searchBtn.prepend(makeIcon(Search, 14, 2));
  }

  const bulkBtn = document.getElementById("memory-bulk-delete") as HTMLButtonElement | null;
  if (bulkBtn) {
    decorateActionButton(bulkBtn, "delete");
  }

  const prevBtn = document.getElementById("memory-page-prev") as HTMLButtonElement | null;
  if (prevBtn && !prevBtn.querySelector("morph-icon")) {
    prevBtn.prepend(makeIcon(ChevronLeft, 14, 2));
  }

  const nextBtn = document.getElementById("memory-page-next") as HTMLButtonElement | null;
  if (nextBtn && !nextBtn.querySelector("morph-icon")) {
    nextBtn.append(makeIcon(ChevronRight, 14, 2));
  }

  document.getElementById("btn-memory-search")?.addEventListener("click", () => {
    memoryOffset = 0;
    loadMemoryList();
  });
  document.getElementById("memory-search-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      memoryOffset = 0;
      loadMemoryList();
    }
  });
  document.getElementById("memory-category-nav")?.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-memory-kind]");
    if (!button) return;
    const kind = button.dataset.memoryKind as MemoryCategoryId;
    if (kind === activeMemoryKind) return;
    activeMemoryKind = kind;
    memoryOffset = 0;
    selectedMemoryId = null;
    mobileDetailActive = false;
    renderMemoryCategoryNav();
    button.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    loadMemoryList();
  });
  document.getElementById("memory-list-container")?.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const row = target.closest<HTMLElement>("[data-memory-record-id]");
    if (!row) return;
    const id = row.dataset.memoryRecordId!;
    // Ô tích / Ctrl+click / Shift+click chỉ chọn để xoá, không mở chi tiết.
    if (target.matches("[data-memory-select]") || event.ctrlKey || event.metaKey || event.shiftKey) {
      if (target.matches("[data-memory-select]")) event.stopPropagation();
      const ids = activeMemoryItems.map(item => String(item.id));
      if (event.shiftKey && bulkAnchorId && ids.includes(bulkAnchorId)) {
        const [a, b] = [ids.indexOf(bulkAnchorId), ids.indexOf(id)].sort((x, y) => x - y);
        ids.slice(a, b + 1).forEach(rangeId => bulkSelectedIds.add(rangeId));
      } else if (bulkSelectedIds.has(id)) {
        bulkSelectedIds.delete(id);
      } else {
        bulkSelectedIds.add(id);
      }
      bulkAnchorId = id;
      renderMemoryItems();
      return;
    }
    selectedMemoryId = id;
    mobileDetailActive = true;
    renderMemoryItems();
  });
  document.getElementById("memory-list-container")?.addEventListener("keydown", (event) => {
    const target = event.target as HTMLElement;
    if ((event.key === "Enter" || event.key === " ") && target.matches("[data-memory-record-id]")) {
      event.preventDefault();
      target.click();
    }
  });
  document.getElementById("memory-select-all")?.addEventListener("change", (event) => {
    const all = (event.target as HTMLInputElement).checked;
    bulkSelectedIds.clear();
    if (all) activeMemoryItems.forEach(item => bulkSelectedIds.add(String(item.id)));
    renderMemoryItems();
  });
  document.getElementById("memory-bulk-delete")?.addEventListener("click", (event) => {
    void deleteBulkSelectedRecords(event.currentTarget as HTMLButtonElement);
  });
  document.getElementById("memory-page-prev")?.addEventListener("click", () => {
    memoryOffset = Math.max(0, memoryOffset - MEMORY_PAGE_SIZE);
    mobileDetailActive = false;
    loadMemoryList();
  });
  document.getElementById("memory-page-next")?.addEventListener("click", () => {
    if (memoryOffset + MEMORY_PAGE_SIZE >= memoryTotal) return;
    memoryOffset += MEMORY_PAGE_SIZE;
    mobileDetailActive = false;
    loadMemoryList();
  });
  document.getElementById("memory-detail-container")?.addEventListener("click", (event) => {
    const btn = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-memory-action]");
    const action = btn?.dataset.memoryAction;
    if (action === "back") {
      mobileDetailActive = false;
      updateMobileLayoutState();
    }
    if (action === "save") void saveSelectedMemoryRecord(btn!);
    if (action === "delete") void deleteSelectedMemoryRecord(btn!);
    if (action === "reembed") void reembedSelectedLearning(btn!);
  });
}
