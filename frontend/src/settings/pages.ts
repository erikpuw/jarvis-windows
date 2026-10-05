/**
 * Settings dashboard markup (spec 2026-09-27). Legacy element ids are kept on
 * purpose: settings.ts and settings-memory.ts find their elements by id.
 */
import {
  AudioLines, Cpu, Database, KeyRound, LayoutDashboard, UserRound,
  LayoutGrid, Key, Volume2, UserCheck, Activity, HardDrive,
  Bot, BotMessageSquare, Boxes, Network, BookOpen, Info,
  Puzzle, Plug, Sparkles, Flame, Terminal, SquareCode, Workflow, GitFork,
  Webhook, Anchor, ScrollText, FileText, FileClock,
  type IconNode,
} from "lucide";
import type { SettingsPageDef, SettingsPageId } from "./types";

export type { SettingsPageDef, SettingsPageId };

export const SETTINGS_PAGES: SettingsPageDef[] = [
  { id: "overview", label: "Tổng quan", description: "Tình trạng phần cứng, dịch vụ và dữ liệu của JARVIS.", icon: LayoutDashboard, activeIcon: LayoutGrid, needsKey: true },
  { id: "connect", label: "Kết nối & API", description: "Khoá API và địa chỉ máy chủ mô hình.", icon: KeyRound, activeIcon: Key, needsKey: false },
  { id: "voice", label: "Giọng đọc", description: "Chọn giọng đọc và tạo giọng clone.", icon: AudioLines, activeIcon: Volume2, needsKey: false },
  { id: "user", label: "Người dùng", description: "Tên, cách xưng hô và tài khoản lịch.", icon: UserRound, activeIcon: UserCheck, needsKey: false },
  { id: "system", label: "Hệ thống", description: "Chi tiết phần cứng, dịch vụ và ứng dụng đang chạy.", icon: Cpu, activeIcon: Activity, needsKey: true },
  { id: "memory", label: "Bộ nhớ", description: "Xem, sửa và xoá có kiểm tra quan hệ toàn bộ dữ liệu học và bộ nhớ của JARVIS.", icon: Database, activeIcon: HardDrive, needsKey: true },
  { id: "logs", label: "Nhật ký", description: "Lịch sử chat, Jarvis log, log bảo mật và log TTS. Một trang riêng, không kiểm tra kết nối nên không tự ghi thêm dòng vào log. Cần mật khẩu giống Bộ nhớ.", icon: FileClock, activeIcon: ScrollText, needsKey: true },
  { id: "agents", label: "Agents", description: "Danh sách và hướng dẫn câu lệnh của các AI Agent chuyên biệt.", icon: Bot, activeIcon: BotMessageSquare, needsKey: true },
  { id: "hooks", label: "Hooks", description: "Các hooks xử lý vòng đời sự kiện quét trực tiếp từ thư mục hooks/.", icon: Webhook, activeIcon: Anchor, needsKey: true },
  { id: "skills", label: "Skills", description: "Các kỹ năng chuyên môn tự động hóa quét trực tiếp từ thư mục skills/.", icon: Sparkles, activeIcon: Flame, needsKey: true },
  { id: "prompts", label: "Prompts", description: "Các khuôn mẫu prompt hệ thống định nghĩa hành vi quét từ thư mục prompt/.", icon: ScrollText, activeIcon: FileText, needsKey: true },
  { id: "commands", label: "Commands", description: "Các lệnh điều khiển nhanh, shortcut và shell commands từ thư mục commands/.", icon: Terminal, activeIcon: SquareCode, needsKey: true },
  { id: "plugins", label: "Plugins", description: "Quản lý và kích hoạt các plugin mở rộng chức năng hệ thống từ plugins/.", icon: Puzzle, activeIcon: Plug, needsKey: false },
  { id: "mcp", label: "MCP Connect", description: "Quản lý kết nối các máy chủ Model Context Protocol nạp từ config/mcp_config.json.", icon: Boxes, activeIcon: Network, needsKey: false },
  { id: "graphfy", label: "Graphfy", description: "Bản đồ cấu trúc JARVIS tự sinh từ code: module nào gọi module nào, và mọi chỗ gọi LLM.", icon: Workflow, activeIcon: GitFork, needsKey: false },
  { id: "info", label: "Thông tin", description: "Kiến trúc hệ thống, hướng dẫn sử dụng và tài liệu chi tiết từ README.md.", icon: BookOpen, activeIcon: Info, needsKey: false },
];

const pageHead = (id: SettingsPageId): string => {
  const page = SETTINGS_PAGES.find(p => p.id === id)!;
  return `<header class="sd-page-head"><h3>${page.label}</h3><p>${page.description}</p></header>`;
};

const feedback = (buttonId: string): string =>
  `<span class="settings-feedback" data-feedback-for="${buttonId}" role="status" aria-live="polite"></span>`;

/** Password screen over a protected area (settings/lock.ts): the root gets class "sd-lockable locked", its content "sd-lock-content". */
const lockScreen = (id: string, title: string): string => `
    <div id="${id}-lock" class="sd-lock-screen">
      <form id="${id}-lock-form" class="sd-card sd-lock-card" autocomplete="off">
        <div class="sd-lock-icon">${svgIcon(ICONS.lock, 26)}</div>
        <h4>${title}</h4>
        <p id="${id}-lock-msg" class="sd-lock-msg">Nhập mật khẩu để mở.</p>
        <input type="password" id="${id}-lock-input" placeholder="Mật khẩu" aria-label="Mật khẩu" autocomplete="off" />
        <button type="submit" class="settings-btn primary" id="${id}-lock-btn">Mở khóa</button>
      </form>
    </div>`;

const statusRow = (dotId: string, name: string, detailId = ""): string =>
  `<div class="status-row"><span class="status-dot" id="${dotId}"></span><span class="status-name">${name}</span>${detailId ? `<span class="status-detail" id="${detailId}"></span>` : ""}<span class="status-text">—</span></div>`;

const serviceRow = (rowId: string, name: string): string =>
  `<div class="status-row" id="${rowId}"><span class="status-dot"></span><span class="status-name">${name}</span><span class="status-detail">Đang kiểm tra…</span></div>`;

const kv = (label: string, id: string): string => `<dt>${label}</dt><dd id="${id}">—</dd>`;

const svgIcon = (path: string, size = 16, stroke = 1.75): string =>
  `<svg class="sd-h-icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;

const ICONS = {
  cpu: `<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>`,
  ram: `<path d="M6 19v-3"/><path d="M10 19v-3"/><path d="M14 19v-3"/><path d="M18 19v-3"/><rect width="20" height="8" x="2" y="8" rx="2"/>`,
  gpu: `<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="8" cy="12" r="2"/><circle cx="16" cy="12" r="2"/><path d="M2 10h20"/>`,
  uptime: `<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>`,
  shield: `<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>`,
  lock: `<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>`,
  brain: `<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M12 18v4"/>`,
  network: `<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>`,
  activity: `<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.48 12H2"/>`,
  key: `<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>`,
  server: `<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>`,
  volume: `<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>`,
  user: `<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>`,
  apps: `<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>`,
  info: `<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>`,
  bot: `<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>`,
  boxes: `<path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l6 3.43a2 2 0 0 0 2.06 0l6-3.43a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L12 9.49l-9.03 3.43Z"/><path d="m12 9.49 9.03 3.43"/><path d="m12 9.49-9.03 3.43"/><path d="M12 22.92V9.49"/>`,
  book: `<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/><path d="M6 2v20"/>`,
  terminal: `<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>`,
  search: `<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>`,
  hook: `<path d="M18 8a6 6 0 0 0-9.33-5"/><path d="m14 15-4-4 4-4"/><path d="M2 12h12a4 4 0 0 1 4 4v2a2 2 0 0 1-4 0v-2"/>`,
  file: `<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/>`,
};

const tile = (prefix: string, label: string, iconKey: keyof typeof ICONS, subId = ""): string => `
  <div class="sd-card sd-tile span-3">
    <div class="sd-tile-label">${svgIcon(ICONS[iconKey], 14, 2)} <span>${label}</span></div>
    <div class="sd-tile-value" id="${prefix}-val">—</div>
    <div class="sd-meter"><span id="${prefix}-bar"></span></div>
    ${subId ? `<div class="sd-tile-sub" id="${subId}"></div>` : ""}
  </div>`;

const meterRow = (label: string, prefix: string, iconKey?: keyof typeof ICONS): string => `
  <div class="sd-meter-row">
    <div class="sd-meter-head"><span>${iconKey ? svgIcon(ICONS[iconKey], 14, 2) : ""} ${label}</span><span id="${prefix}-val">—</span></div>
    <div class="sd-meter"><span id="${prefix}-bar"></span></div>
  </div>`;

const overviewPage = (): string => `
  <section class="sd-page" data-page="overview" id="page-overview" hidden>
    ${pageHead("overview")}
    <div class="sd-grid">
      ${tile("ov-cpu", "CPU", "cpu")}
      ${tile("ov-ram", "RAM", "ram", "ov-ram-sub")}
      ${tile("ov-gpu", "VRAM GPU", "gpu", "ov-gpu-name")}
      <div class="sd-card sd-tile span-3">
        <div class="sd-tile-label">${svgIcon(ICONS.uptime, 14, 2)} <span>Thời gian chạy</span></div>
        <div class="sd-tile-value" id="sysinfo-uptime">—</div>
        <div class="sd-tile-sub">Cổng máy chủ <span id="sysinfo-port">—</span></div>
      </div>
      <div class="sd-card span-4" id="section-status">
        <h4>${svgIcon(ICONS.shield, 17)} Dịch vụ</h4>
        <div class="sd-status-grid">
          ${statusRow("status-intelligence-core", "Intelligence Core")}
          ${statusRow("status-server-engine", "Server Engine")}
          ${statusRow("status-llm-server", "LLM Server")}
          ${statusRow("status-tts-server", "TTS Server")}
          <div class="status-row"><span class="status-dot" id="ov-dot-llm"></span><span class="status-name">LLM Service</span><span class="status-text" id="ov-infra-llm">Đang kiểm tra…</span></div>
          <div class="status-row"><span class="status-dot" id="ov-dot-rag"></span><span class="status-name">RAG</span><span class="status-text" id="ov-infra-rag">Đang kiểm tra…</span></div>
          <div class="status-row"><span class="status-dot" id="ov-dot-db"></span><span class="status-name">SQLite DB</span><span class="status-text" id="ov-infra-db">Đang kiểm tra…</span></div>
          <div class="status-row"><span class="status-dot" id="ov-dot-redis"></span><span class="status-name">Redis</span><span class="status-text" id="ov-infra-redis">Đang kiểm tra…</span></div>
          ${statusRow("status-server", "System Hub", "status-server-detail")}
        </div>
      </div>
      <div class="sd-card span-4">
        <h4>${svgIcon(ICONS.server, 17)} Mô hình & kết nối</h4>
        <dl class="sd-kv">
          ${kv("Mô hình LLM", "ov-llm-model")}
          ${kv("Mô hình embedding", "ov-embed-model")}
          ${kv("TTS đang chạy", "ov-tts-engine")}
          ${kv("MCP đã kết nối", "ov-mcp")}
          ${kv("Agents", "ov-agents")}
          ${kv("Kỹ năng · Lệnh", "ov-skills-cmds")}
        </dl>
      </div>
      <div class="sd-card span-4">
        <h4>${svgIcon(ICONS.brain, 17)} Dữ liệu tri thức</h4>
        <dl class="sd-kv">
          ${kv("Bản ghi bộ nhớ", "sysinfo-memory")}
          ${kv("Hội thoại", "sysinfo-turns")}
          ${kv("Tác vụ", "sysinfo-tasks")}
          ${kv("Kỹ năng đã nạp", "sysinfo-skills")}
          ${kv("Lệnh hỗ trợ", "sysinfo-commands")}
        </dl>
      </div>
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.activity, 17)} Token phiên làm việc</h4>
        <div class="sd-session-tokens">
          <div class="sd-token-tile"><span class="sd-token-num" id="ov-token-total">0</span><span class="sd-token-lbl">Tổng</span></div>
          <div class="sd-token-tile"><span class="sd-token-num" id="ov-token-in">0</span><span class="sd-token-lbl">Input</span></div>
          <div class="sd-token-tile"><span class="sd-token-num" id="ov-token-out">0</span><span class="sd-token-lbl">Output</span></div>
        </div>
      </div>
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.apps, 17)} Ứng dụng đang mở</h4>
        <div id="ov-apps-badges" class="sd-badge-list"><span class="sd-empty" style="padding: 0;">Đang quét…</span></div>
      </div>
    </div>
  </section>`;

const connectPage = (): string => `
  <section class="sd-page" data-page="connect" id="page-connect" hidden>
    ${pageHead("connect")}
    <div class="sd-grid">
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.key, 17)} Mô hình ngôn ngữ (LLM API)</h4>
        <p class="sd-lead">JARVIS dùng server API Key để xác thực các cuộc gọi mô hình. Khoá được lưu vào file <code>.env</code> tại máy chủ cục bộ.</p>
        <div class="form-group">
          <label for="input-llama-key">Server API Key (LOCAL_API_KEY)</label>
          <div class="sd-input-row">
            <input type="password" id="input-llama-key" placeholder="Nhập khoá API..." autocomplete="off">
            <button type="button" class="settings-btn" id="btn-test-llama">Kiểm tra</button>
            ${feedback("btn-test-llama")}
          </div>
          <div class="sd-field-note" id="status-llama">Chưa cấu hình khoá.</div>
        </div>
        <div class="form-group">
          <label for="input-llama-url">Endpoint máy chủ LLM (LOCAL_URL)</label>
          <div class="sd-input-row">
            <input type="text" id="input-llama-url" placeholder="http://127.0.0.1:8080/v1" autocomplete="off">
            <button type="button" class="settings-btn" id="btn-save-llama-url">Lưu URL</button>
            ${feedback("btn-save-llama-url")}
          </div>
        </div>
      </div>
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.volume, 17)} Dịch vụ giọng nói & TTS (Tuỳ chọn)</h4>
        <div class="form-group">
          <label for="input-fish-key">Fish Audio / VieNeu API Key</label>
          <div class="sd-input-row">
            <input type="password" id="input-fish-key" placeholder="Nhập khoá TTS nếu dùng dịch vụ đám mây..." autocomplete="off">
            <button type="button" class="settings-btn" id="btn-test-fish">Kiểm tra TTS</button>
            ${feedback("btn-test-fish")}
          </div>
          <div class="sd-field-note" id="status-fish">Đang sử dụng VieNeu TTS Engine nội bộ (cục bộ).</div>
        </div>
        <div class="sd-action-row" style="margin-top: 16px;">
          <button type="button" class="settings-btn primary" id="btn-save-keys">Lưu toàn bộ cài đặt kết nối</button>
          ${feedback("btn-save-keys")}
        </div>
      </div>
    </div>
  </section>`;

const voicePage = (): string => `
  <section class="sd-page" data-page="voice" id="page-voice" hidden>
    ${pageHead("voice")}
    <div class="sd-grid">
      <div class="sd-card span-4">
        <h4>${svgIcon(ICONS.activity, 17)} Engine đang chạy</h4>
        <div class="sd-status-grid sd-status-grid-1">
          <div class="status-row"><span class="status-dot" id="voice-dot-vieneu"></span><span class="status-name">VieNeu TTS</span><span class="status-text" id="voice-vieneu-current">—</span></div>
          <div class="status-row"><span class="status-dot" id="voice-dot-edge"></span><span class="status-name">Edge-TTS</span><span class="status-text" id="voice-edge-current">—</span></div>
        </div>
        <p class="sd-field-note">Chỉ đọc từ <code>.env</code>. Muốn đổi engine: sửa <code>VIENEU_TTS_ENABLED</code> / <code>EDGE_TTS_ENABLED</code> (chỉ bật một), giọng Edge ở <code>TTS_LOCAL_MODEL</code>, rồi khởi động lại JARVIS.</p>
      </div>
      <div class="sd-card span-4">
        <h4>${svgIcon(ICONS.volume, 17)} Giọng VieNeu</h4>
        <div class="form-group" id="field-vieneu-voice">
          <label for="select-vieneu-voice">Chọn giọng nói</label>
          <select id="select-vieneu-voice"><option value="">Đang tải danh sách giọng…</option></select>
          <div class="sd-field-note" id="voice-hint">Giọng được áp dụng ngay cho phản hồi âm thanh tiếp theo.</div>
        </div>
        <div class="sd-action-row">
          <button type="button" class="settings-btn primary" id="btn-save-voice-id">Lưu giọng</button>
          ${feedback("btn-save-voice-id")}
        </div>
      </div>
      <div class="sd-card span-4">
        <h4>${svgIcon(ICONS.user, 17)} Tạo giọng clone</h4>
        <p class="sd-lead">Mẫu 3–8 giây, một người nói, ít tạp âm, đọc rõ và chậm — tốc độ đọc sẽ theo mẫu.</p>
        <div class="form-group">
          <label for="input-clone-name">Tên giọng clone</label>
          <input type="text" id="input-clone-name" placeholder="Ví dụ: Giọng trợ lý cá nhân" autocomplete="off">
        </div>
        <div class="form-group">
          <label for="input-clone-file">Tệp mẫu âm thanh</label>
          <input type="file" id="input-clone-file" accept="audio/*">
        </div>
        <button type="button" class="settings-btn" id="btn-upload-clone">Tải lên & Huấn luyện</button>
        ${feedback("btn-upload-clone")}
      </div>
    </div>
  </section>`;

const userPage = (): string => `
  <section class="sd-page" data-page="user" id="page-user" hidden>
    ${pageHead("user")}
    <div class="sd-grid">
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.user, 17)} Hồ sơ người dùng & Tương tác</h4>
        <div class="form-group">
          <label for="input-user-name">Tên hiển thị của bạn</label>
          <input type="text" id="input-user-name" placeholder="Ví dụ: Erik" autocomplete="off">
        </div>
        <div class="form-group">
          <label for="input-honorific">Cách JARVIS xưng hô với bạn</label>
          <input type="text" id="input-honorific" placeholder="Ví dụ: Bạn, Anh, Boss..." autocomplete="off">
        </div>
        <div class="form-group">
          <label for="input-calendar-accounts">Tài khoản Google Calendar đồng bộ</label>
          <input type="text" id="input-calendar-accounts" placeholder="email@gmail.com" autocomplete="off">
        </div>
        <div class="sd-action-row">
          <button type="button" class="settings-btn primary" id="btn-save-prefs">Lưu thông tin cá nhân</button>
          ${feedback("btn-save-prefs")}
        </div>
      </div>
    </div>
  </section>`;

const systemPage = (): string => `
  <section class="sd-page" data-page="system" id="page-system" hidden>
    ${pageHead("system")}
    <div class="sd-grid">
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.cpu, 17)} Tài nguyên máy chủ</h4>
        ${meterRow("Vi xử lý CPU", "health-cpu", "cpu")}
        ${meterRow("Bộ nhớ RAM", "health-ram", "ram")}
        <div class="sd-field-note" id="sysinfo-memory-detail">Đang tải thông số…</div>
      </div>
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.gpu, 17)} Card đồ họa & Bộ tăng tốc (GPU / NPU)</h4>
        <div id="health-gpus-container" class="sd-gpu-list"><div class="sd-empty">Đang quét phần cứng tăng tốc…</div></div>
      </div>
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.server, 17)} Trạng thái chi tiết dịch vụ nội bộ</h4>
        <div class="status-list">
          ${serviceRow("row-status-llm", "llama.cpp / Mô hình suy luận")}
          ${serviceRow("row-status-redis", "Redis Message Hub")}
          ${serviceRow("row-status-db", "SQLite Memory Storage")}
          ${serviceRow("row-status-rag", "ChromaDB / Vector Search Engine")}
        </div>
      </div>
      <div class="sd-card span-6">
        <h4>${svgIcon(ICONS.apps, 17)} Ứng dụng Desktop đang phát hiện</h4>
        <div id="apps-list-container" class="sd-apps-list"><div class="sd-empty">Đang quét ứng dụng chạy nền…</div></div>
      </div>
    </div>
  </section>`;

const memoryPage = (): string => `
  <section class="sd-page sd-page-memory sd-lockable locked" data-page="memory" id="page-memory" hidden>
    ${pageHead("memory")}
    <div class="memory-control-layout sd-memory sd-lock-content">
      <div class="sd-card sd-memory-cats">
        <div class="sd-mem-panel-head">
          <h4>${svgIcon(ICONS.brain, 14)} Nhóm dữ liệu</h4>
          <span class="sd-mem-badge-pill" id="memory-cats-count">7 phân loại</span>
        </div>
        <div id="memory-category-nav"></div>
      </div>
      <div class="sd-card sd-memory-list">
        <div class="sd-mem-search-bar">
          <input type="search" id="memory-search-input" placeholder="Tìm trong nhóm đang chọn…" aria-label="Tìm bản ghi" />
          <button type="button" class="settings-btn sd-mem-search-btn" id="btn-memory-search">Tìm</button>
        </div>
        <div class="sd-memory-toolbar">
          <label class="sd-check"><input type="checkbox" id="memory-select-all" /> <span>Chọn tất cả</span></label>
          <button type="button" class="settings-btn danger sd-btn-bulk-delete" id="memory-bulk-delete" data-action="delete" disabled>
            <span class="btn-label">Xoá đã chọn (0)</span>
          </button>
        </div>
        <div id="memory-list-container" class="memory-control-scroll">
          <div class="sd-empty sd-loading-state"><span>Đang tải dữ liệu…</span></div>
        </div>
        <div class="sd-pager">
          <button type="button" class="settings-btn" id="memory-page-prev"><span>Trước</span></button>
          <span id="memory-page-status" class="sd-pager-status">0 / 0</span>
          <button type="button" class="settings-btn" id="memory-page-next"><span>Sau</span></button>
        </div>
      </div>
      <div id="memory-detail-container" class="sd-card memory-control-scroll sd-memory-detail">
        <div class="sd-empty">Chọn một bản ghi để xem chi tiết.</div>
      </div>
    </div>
    ${lockScreen("memory", "Memory Control đang khóa")}
  </section>`;

const logsPage = (): string => `
  <section class="sd-page sd-page-memory sd-lockable locked" data-page="logs" id="page-logs" hidden>
    ${pageHead("logs")}
    <div class="memory-control-layout sd-memory sd-logs-layout sd-lock-content">
      <div class="sd-card sd-memory-cats">
        <div class="sd-mem-panel-head">
          <h4>${svgIcon(ICONS.shield, 14)} Nhóm nhật ký</h4>
        </div>
        <div id="logs-category-nav"></div>
      </div>
      <div class="sd-card sd-memory-list" id="card-logs">
        <div class="sd-logs-head">
          <h4 id="logs-title">Lịch sử chat</h4>
          <button type="button" class="settings-btn" id="logs-refresh">Làm mới</button>
        </div>
        <div id="history-subbar" class="sd-subbar">
          <div class="sd-subtabs">
            <button type="button" class="sd-subtab active" data-hist-view="all">Toàn bộ</button>
            <button type="button" class="sd-subtab" data-hist-view="sessions">Phiên chat</button>
          </div>
          <div id="history-back" class="sd-session-back" hidden>
            <button type="button" class="settings-btn" id="history-back-btn">← Danh sách phiên chat</button>
            <span id="history-back-title" class="sd-session-back-title"></span>
          </div>
        </div>
        <div id="history-view" class="sd-history-split" data-view="all" data-reading="0">
          <div id="history-sessions-list" class="sd-sessions-list" hidden></div>
          <div id="history-settings-list" class="sd-history-list"></div>
        </div>
        <div id="logs-content" class="sd-log-content" hidden></div>
      </div>
    </div>
    ${lockScreen("logs", "Nhật ký đang khóa")}
  </section>`;

const agentsPage = (): string => `
  <section class="sd-page" data-page="agents" id="page-agents" hidden>
    ${pageHead("agents")}
    <div class="sd-agents-toolbar">
      <div class="sd-search-box">
        ${svgIcon(ICONS.search, 16, 2)}
        <input type="text" id="agents-search-input" placeholder="Tìm kiếm AI Agent theo tên, chức năng hoặc lệnh gọi..." autocomplete="off">
      </div>
      <div class="sd-agents-counter">
        <span class="sd-agents-count-val" id="agents-count-val">0</span>
        <span class="sd-agents-count-lbl">Agents sẵn sàng</span>
      </div>
    </div>
    <div class="sd-agents-grid" id="agents-grid">
      <div class="sd-empty sd-loading-state"><span>Đang nạp danh sách Agents…</span></div>
    </div>
  </section>`;

const hooksPage = (): string => `
  <section class="sd-page" data-page="hooks" id="page-hooks" hidden>
    ${pageHead("hooks")}
    <div class="sd-agents-toolbar">
      <div class="sd-search-box">
        ${svgIcon(ICONS.search, 16, 2)}
        <input type="text" id="hooks-search-input" placeholder="Tìm kiếm Hook theo tên, sự kiện, tệp tin..." autocomplete="off">
      </div>
      <div class="sd-agents-counter">
        <span class="sd-agents-count-val" id="hooks-count-val">0</span>
        <span class="sd-agents-count-lbl">Hooks từ hooks/</span>
      </div>
    </div>
    <div class="sd-agents-grid" id="hooks-grid">
      <div class="sd-empty sd-loading-state"><span>Đang nạp danh sách Hooks từ thư mục hooks/…</span></div>
    </div>
  </section>`;

const skillsPage = (): string => `
  <section class="sd-page" data-page="skills" id="page-skills" hidden>
    ${pageHead("skills")}
    <div class="sd-agents-toolbar">
      <div class="sd-search-box">
        ${svgIcon(ICONS.search, 16, 2)}
        <input type="text" id="skills-search-input" placeholder="Tìm kiếm Kỹ năng theo tên, danh mục, từ khoá..." autocomplete="off">
      </div>
      <div class="sd-agents-counter">
        <span class="sd-agents-count-val" id="skills-count-val">0</span>
        <span class="sd-agents-count-lbl">Skills từ skills/</span>
      </div>
    </div>
    <div class="sd-agents-grid" id="skills-grid">
      <div class="sd-empty sd-loading-state"><span>Đang nạp danh sách Skills từ thư mục skills/…</span></div>
    </div>
  </section>`;

const promptsPage = (): string => `
  <section class="sd-page" data-page="prompts" id="page-prompts" hidden>
    ${pageHead("prompts")}
    <div class="sd-agents-toolbar">
      <div class="sd-search-box">
        ${svgIcon(ICONS.search, 16, 2)}
        <input type="text" id="prompts-search-input" placeholder="Tìm kiếm Prompt theo tên, tệp tin, mục đích..." autocomplete="off">
      </div>
      <div class="sd-agents-counter">
        <span class="sd-agents-count-val" id="prompts-count-val">0</span>
        <span class="sd-agents-count-lbl">Prompts từ prompt/</span>
      </div>
    </div>
    <div class="sd-agents-grid" id="prompts-grid">
      <div class="sd-empty sd-loading-state"><span>Đang nạp danh sách Prompts từ thư mục prompt/…</span></div>
    </div>
    <div class="sd-modal-backdrop" id="prompt-preview-modal" hidden>
      <div class="sd-modal-dialog">
        <div class="sd-modal-head">
          <h4 id="prompt-preview-title">Xem trước Prompt</h4>
          <button type="button" class="sd-icon-btn" id="prompt-preview-close" aria-label="Đóng">&times;</button>
        </div>
        <div class="sd-modal-body">
          <textarea class="sd-prompt-editor" id="prompt-preview-code" spellcheck="false" aria-label="Nội dung prompt"></textarea>
        </div>
        <div class="sd-modal-foot">
          <span class="sd-agent-cmd-note">Lưu ghi đè <code id="prompt-preview-file"></code> và có hiệu lực ngay ở lượt kế tiếp.</span>
          ${feedback("btn-prompt-save")}
          <button type="button" class="settings-btn primary" id="btn-prompt-save" data-action="save">Lưu prompt</button>
        </div>
      </div>
    </div>
  </section>`;

const commandsPage = (): string => `
  <section class="sd-page" data-page="commands" id="page-commands" hidden>
    ${pageHead("commands")}
    <div class="sd-agents-toolbar">
      <div class="sd-search-box">
        ${svgIcon(ICONS.search, 16, 2)}
        <input type="text" id="commands-search-input" placeholder="Tìm kiếm Lệnh theo tên, cú pháp, tệp tin..." autocomplete="off">
      </div>
      <div class="sd-agents-counter">
        <span class="sd-agents-count-val" id="commands-count-val">0</span>
        <span class="sd-agents-count-lbl">Commands từ commands/</span>
      </div>
    </div>
    <div class="sd-agents-grid" id="commands-grid">
      <div class="sd-empty sd-loading-state"><span>Đang nạp danh sách Commands từ thư mục commands/…</span></div>
    </div>
  </section>`;

const pluginsPage = (): string => `
  <section class="sd-page" data-page="plugins" id="page-plugins" hidden>
    ${pageHead("plugins")}
    <div class="sd-agents-toolbar">
      <div class="sd-search-box">
        ${svgIcon(ICONS.search, 16, 2)}
        <input type="text" id="plugins-search-input" placeholder="Tìm kiếm Plugin theo tên, runtime, tệp tin..." autocomplete="off">
      </div>
      <div class="sd-agents-counter">
        <span class="sd-agents-count-val" id="plugins-count-val">0</span>
        <span class="sd-agents-count-lbl">Plugins từ plugins/</span>
      </div>
    </div>
    <div class="sd-agents-grid" id="plugins-grid">
      <div class="sd-empty sd-loading-state"><span>Đang nạp danh sách Plugins từ thư mục plugins/…</span></div>
    </div>
  </section>`;

const mcpPage = (): string => `
  <section class="sd-page" data-page="mcp" id="page-mcp" hidden>
    ${pageHead("mcp")}
    <div class="sd-mcp-container">
      <div class="sd-card sd-mcp-summary">
        <div class="sd-mcp-stat">
          <span class="sd-mcp-stat-num" id="mcp-total-val">0</span>
          <span class="sd-mcp-stat-lbl">Máy chủ cấu hình</span>
        </div>
        <div class="sd-mcp-stat">
          <span class="sd-mcp-stat-num text-success" id="mcp-connected-val">0</span>
          <span class="sd-mcp-stat-lbl">Đang kích hoạt</span>
        </div>
        <div class="sd-mcp-file-badge">
          <span class="sd-badge-k">Tệp cấu hình:</span>
          <code>config/mcp_config.json</code>
        </div>
      </div>

      <div class="sd-agents-toolbar" style="margin-top: 6px;">
        <div class="sd-search-box">
          ${svgIcon(ICONS.search, 16, 2)}
          <input type="text" id="mcp-search-input" placeholder="Lọc máy chủ MCP..." autocomplete="off">
        </div>
        <button type="button" class="settings-btn" id="btn-toggle-mcp-json">Xem JSON cấu hình</button>
      </div>

      <div class="sd-card sd-mcp-json-box" id="mcp-json-container" hidden>
        <div class="sd-mcp-json-head">
          <span>Nội dung <code>config/mcp_config.json</code></span>
          <span class="sd-json-copy-btn" id="btn-copy-mcp-json">Sao chép</span>
        </div>
        <pre class="sd-json-pre" id="mcp-raw-json-viewer"></pre>
      </div>

      <div class="sd-card sd-mcp-list-card" style="margin-top: 0px;">
        <h4>Danh sách máy chủ ngoại vi (MCP Servers)</h4>
        <div class="sd-mcp-list" id="mcp-servers-list">
          <div class="sd-empty sd-loading-state"><span>Đang nạp thông tin MCP Servers từ config/mcp_config.json…</span></div>
        </div>
      </div>

      <div class="sd-card sd-mcp-add-card" style="margin-top: 6px;">
        <h4>Thêm máy chủ MCP</h4>
        <div class="sd-field-note">Loại <code>stdio</code> chạy một lệnh ngay trên máy này: chỉ thêm lệnh bạn tin tưởng. Chỉ thêm và bật/tắt được từ chính máy chạy JARVIS.</div>
        <div class="form-group">
          <label for="mcp-add-name">Tên</label>
          <input type="text" id="mcp-add-name" placeholder="Ví dụ: context7" autocomplete="off">
        </div>
        <div class="form-group">
          <label for="mcp-add-type">Loại</label>
          <select id="mcp-add-type">
            <option value="stdio">stdio (chạy lệnh trên máy)</option>
            <option value="http">http</option>
            <option value="sse">sse</option>
          </select>
        </div>
        <div class="form-group" data-mcp-field="stdio">
          <label for="mcp-add-command">Lệnh</label>
          <input type="text" id="mcp-add-command" placeholder="Ví dụ: npx" autocomplete="off">
        </div>
        <div class="form-group" data-mcp-field="stdio">
          <label for="mcp-add-args">Tham số (mỗi dòng một tham số)</label>
          <textarea id="mcp-add-args" rows="3" spellcheck="false" placeholder="-y&#10;@upstash/context7-mcp"></textarea>
        </div>
        <div class="form-group" data-mcp-field="url" hidden>
          <label for="mcp-add-url">URL</label>
          <input type="text" id="mcp-add-url" placeholder="https://..." autocomplete="off">
        </div>
        <div class="sd-action-row">
          <button type="button" class="settings-btn primary" id="btn-mcp-add">Thêm và kết nối</button>
          ${feedback("btn-mcp-add")}
        </div>
      </div>
    </div>
  </section>`;

const graphfyPage = (): string => `
  <section class="sd-page sd-page-graphfy" data-page="graphfy" id="page-graphfy" hidden>
    ${pageHead("graphfy")}
    <div class="gf-toolbar">
      <span class="gf-legend"><i style="background:#38bdf8"></i>Import giữa module (màu theo làn nguồn)</span>
      <span class="gf-legend"><i style="background:#c084fc"></i>Gọi LLM</span>
      <span class="gf-hint">Tự sinh từ code · rê chuột để lọc đường và xem file · kéo thả để sắp xếp</span>
      <button type="button" class="settings-btn" id="btn-graphfy-reset">Bố cục mặc định</button>
    </div>
    <div class="sd-card gf-card"><div id="graphfy-map" class="gf-map"><div class="sd-empty">Đang dựng sơ đồ…</div></div></div>
  </section>`;

const infoPage = (): string => `
  <section class="sd-page" data-page="info" id="page-info" hidden>
    ${pageHead("info")}
    <div class="sd-info-container">
      <div class="sd-card sd-info-bar">
        <div class="sd-info-bar-stats">
          <div class="sd-info-stat-pill">
            <span class="sd-info-stat-k">Phiên bản:</span>
            <span class="sd-info-stat-v">v${APP_VERSION}</span>
          </div>
          <div class="sd-info-stat-pill">
            <span class="sd-info-stat-k">Nền tảng:</span>
            <span class="sd-info-stat-v">Windows · Desktop Native</span>
          </div>
          <div class="sd-info-stat-pill">
            <span class="sd-info-stat-k">Nguồn dữ liệu:</span>
            <code class="sd-info-file-tag">README.md</code>
          </div>
        </div>
        <button type="button" class="settings-btn" id="btn-refresh-readme" style="margin-left: auto;">
          ${svgIcon(ICONS.activity, 14, 2)} <span>Tải lại tài liệu</span>
        </button>
      </div>
      <div class="sd-card sd-readme-card">
        <div id="readme-viewer" class="sd-readme-content">
          <div class="sd-empty sd-loading-state"><span>Đang nạp nội dung tài liệu README.md…</span></div>
        </div>
      </div>
    </div>
  </section>`;

export const APP_VERSION = typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "dev";

export function buildSettingsHTML(): string {
  const nav = SETTINGS_PAGES.map(p =>
    `<button type="button" class="sd-nav-item" data-page="${p.id}" title="${p.label}"><span class="sd-nav-icon" data-nav-icon="${p.id}"></span><span class="sd-nav-label">${p.label}</span></button>`,
  ).join("");
  return `
    <div class="sd-root" id="settings-panel-inner" role="dialog" aria-modal="true" aria-labelledby="sd-title">
      <header class="sd-topbar">
        <button type="button" class="sd-icon-btn sd-menu-btn" id="settings-menu-toggle" aria-label="Mở danh mục cài đặt" aria-expanded="false" aria-controls="settings-nav"></button>
        <div class="sd-brand-group">
          <h2 class="sd-title" id="sd-title">JARVIS <span>· Dashboard</span></h2>
          <button type="button" class="sd-icon-btn sd-collapse-btn" id="settings-sidebar-toggle" aria-label="Thu nhỏ thanh điều hướng" title="Thu nhỏ thanh điều hướng">
            <span class="sd-nav-icon" id="sidebar-toggle-icon"></span>
          </button>
        </div>
        <span class="sd-page-title" id="settings-page-title"></span>
        <button type="button" class="sd-icon-btn" id="settings-close" aria-label="Đóng cài đặt"></button>
      </header>
      <div class="settings-welcome" id="settings-welcome" hidden>Chào mừng đến với JARVIS — hãy nhập Server API Key để bắt đầu.</div>
      <div class="sd-body">
        <nav class="sd-nav" id="settings-nav" aria-label="Danh mục cài đặt">
          <div class="sd-nav-list">${nav}</div>
          <div class="sd-nav-footer">
            <div class="sd-brand-card" title="JARVIS System · v${APP_VERSION}">
              <div class="sd-brand-name">JARVIS</div>
              <div class="sd-version-badge">
                <span class="sd-version-dot"></span>
                <span class="sd-version-label">v${APP_VERSION}</span>
              </div>
            </div>
          </div>
        </nav>
        <div class="sd-scrim" id="settings-scrim" hidden></div>
        <main class="sd-content" id="settings-content">
          ${overviewPage()}
          ${connectPage()}
          ${voicePage()}
          ${userPage()}
          ${systemPage()}
          ${memoryPage()}
          ${logsPage()}
          ${agentsPage()}
          ${hooksPage()}
          ${skillsPage()}
          ${promptsPage()}
          ${commandsPage()}
          ${pluginsPage()}
          ${mcpPage()}
          ${graphfyPage()}
          ${infoPage()}
          <div class="setup-nav" id="setup-nav" hidden>
            <button type="button" class="settings-btn primary" id="btn-setup-next">Tiếp</button>
          </div>
        </main>
      </div>
    </div>`;
}
