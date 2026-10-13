const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";

function getStatus() {
  return {
    success: true,
    intelligence_core_ok: true,
    server_engine_ok: true,
    llm_server_ok: true,
    tts_server_ok: true,
    memory_count: 142,
    semantic_memory_count: 89,
    conversation_turn_count: 1204,
    task_count: 36,
    skill_count: 3,
    command_count: 3,
    plugins_loaded: 3,
    server_port: 8000,
    uptime_seconds: 7320,
    open_apps: ["code.exe", "chrome.exe", "terminal.exe"],
    env_keys_set: { llama: true, fish_audio: true, fish_voice_id: true, user_name: "Erik" },
    system: {
      cpu_percent: 24.5,
      ram_percent: 48.2,
      ram_used_gb: 7.7,
      ram_total_gb: 16.0,
      gpus: [{ name: "NVIDIA RTX 4090", mem_used_mb: 8192, vram_total_mb: 24576 }],
      npus: [],
    },
    session_tokens: { input: 12450, output: 8320, total: 20770 },
    agents: [
      {
        id: "desktop",
        name: "Agent Desktop",
        file: "agent_desktop.py",
        description: "Điều khiển ứng dụng và thao tác giao diện máy tính Windows.",
        example: "mở notepad",
        tools: ["launch_app", "click", "type_text"],
      },
      {
        id: "search",
        name: "Agent Web Search",
        file: "agent_search.py",
        description: "Tìm kiếm thông tin thời gian thực trên Internet và tổng hợp dữ liệu.",
        example: "tìm kiếm tin tức thời tiết hôm nay",
        tools: ["google_search", "fetch_url"],
      },
    ],
    plugins_list: [
      {
        name: "superpowers",
        description: "Bộ công cụ tự động hóa quy trình phần mềm thông minh và agent song song.",
        runtime: "node / typescript",
        active: true,
        file_path: "plugins/superpowers/index.ts",
      },
      {
        name: "context-mode",
        description: "Tối ưu hóa và kiểm soát ngữ cảnh, lọc đầu ra hạn chế tràn token.",
        runtime: "node / python",
        active: true,
        file_path: "plugins/context-mode/index.ts",
      },
      {
        name: "ponytail",
        description: "Công cụ tinh giản code và kiến trúc tối giản theo triết lý YAGNI.",
        runtime: "python",
        active: true,
        file_path: "plugins/ponytail/plugin.py",
      },
    ],
    skills_list: [
      {
        name: "brainstorming",
        description: "Khám phá yêu cầu, thiết kế kiến trúc và giải pháp trước khi viết code.",
        category: "design",
        tags: ["architecture", "spec", "planning"],
      },
      {
        name: "ui-ux-pro-max",
        description: "Thiết kế giao diện người dùng cao cấp, bảng màu bento grid và micro-interactions.",
        category: "frontend",
        tags: ["ui", "ux", "aesthetics"],
      },
      {
        name: "systematic-debugging",
        description: "Truy vết nguyên nhân gốc rễ và kiểm chứng lỗi kỹ thuật có hệ thống.",
        category: "quality",
        tags: ["debug", "testing", "root-cause"],
      },
    ],
    commands_list: [
      {
        name: "status",
        description: "Kiểm tra toàn diện trạng thái sức khỏe phần cứng và dịch vụ hệ thống.",
        usage: "/status --verbose",
        category: "system",
      },
      {
        name: "memory-clean",
        description: "Dọn dẹp và nén các bản ghi bộ nhớ trùng lặp trong cơ sở dữ liệu.",
        usage: "/memory-clean --threshold 0.85",
        category: "maintenance",
      },
      {
        name: "agent-run",
        description: "Kích hoạt trực tiếp một tác nhân chuyên biệt xử lý công việc độc lập.",
        usage: "/agent-run <agent_id> <prompt>",
        category: "orchestration",
      },
    ],
  };
}

const MCP_DATA = {
  success: true,
  total: 3,
  connected: 3,
  servers: [
    { name: "gitnexus", type: "stdio", status: "connected", command: "npx", args: ["gitnexus", "serve"] },
    { name: "context-mode", type: "stdio", status: "connected", command: "npx", args: ["context-mode"] },
    { name: "headroom", type: "stdio", status: "connected", command: "npx", args: ["headroom-mcp"] },
  ],
};

const README_CONTENT = `# JARVIS — AI Desktop Companion
Hệ thống trợ lý ảo thông minh chạy độc lập trên Windows.
`;

async function run() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  await page.routeWebSocket(/\/ws/, () => {});
  const json = (r, body) => r.fulfill({ json: body });
  await page.route("**/api/**", (r) => json(r, { success: true }));
  await page.route("**/api/settings/status**", (r) => json(r, getStatus()));
  await page.route("**/api/mcp/servers**", (r) => json(r, MCP_DATA));
  await page.route("**/api/system/readme**", (r) => json(r, { success: true, content: README_CONTENT }));
  await page.route("**/api/learnings/list**", (r) => json(r, {
    success: true,
    learnings: [{ id: 1, content: "Port 8340", category: "system", validation_count: 5 }],
    total: 1,
  }));
  await page.route("**/api/memory-control/summary", (r) => json(r, { success: true, counts: { learning: 1 } }));
  await page.route("**/api/settings/preferences", (r) => json(r, { user_name: "Erik", honorific: "sir", calendar_accounts: "auto" }));

  await page.goto(BASE);
  await page.waitForSelector("#btn-menu");
  await page.click("#btn-menu");
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForSelector("#settings-container.open");
  await page.waitForTimeout(400);

  const brainDir = "C:/Users/erikpuw/.gemini/antigravity-ide/brain/3985ccd9-bf5e-40f3-a6b7-89f701c686e2";

  // Check sidebar item order: info MUST be last!
  const lastNavPage = await page.$eval(".sd-nav-list .sd-nav-item:last-child", el => el.dataset.page);
  console.log(`Sidebar last item is: "${lastNavPage}"`);
  if (lastNavPage !== "info") throw new Error(`Info page must be last! Found: ${lastNavPage}`);

  // 1. Plugins Page
  console.log("Checking Plugins page...");
  await page.click('.sd-nav-item[data-page="plugins"]');
  await page.waitForSelector("#plugins-grid .sd-agent-card");
  const pluginsCount = await page.textContent("#plugins-count-val");
  const firstPlugin = await page.textContent("#plugins-grid .sd-agent-card:first-child .sd-agent-name");
  console.log(`Plugins: count=${pluginsCount}, first=${firstPlugin}`);
  await page.screenshot({ path: `${brainDir}/settings-dashboard-plugins.png` });

  // 2. Skill Page
  console.log("Checking Skill page...");
  await page.click('.sd-nav-item[data-page="skills"]');
  await page.waitForSelector("#skills-grid .sd-agent-card");
  const skillsCount = await page.textContent("#skills-count-val");
  const firstSkill = await page.textContent("#skills-grid .sd-agent-card:first-child .sd-agent-name");
  console.log(`Skills: count=${skillsCount}, first=${firstSkill}`);
  await page.screenshot({ path: `${brainDir}/settings-dashboard-skills.png` });

  // 3. Command Page
  console.log("Checking Command page...");
  await page.click('.sd-nav-item[data-page="commands"]');
  await page.waitForSelector("#commands-grid .sd-agent-card");
  const commandsCount = await page.textContent("#commands-count-val");
  const firstCmd = await page.textContent("#commands-grid .sd-agent-card:first-child .sd-agent-name");
  console.log(`Commands: count=${commandsCount}, first=${firstCmd}`);
  await page.screenshot({ path: `${brainDir}/settings-dashboard-commands.png` });

  // 4. Graphfy Page
  console.log("Checking Graphfy page...");
  await page.click('.sd-nav-item[data-page="graphfy"]');
  await page.waitForSelector("#graphfy-canvas .sd-graph-node");
  const nodeCount = await page.$$eval("#graphfy-canvas .sd-graph-node", els => els.length);
  const wiresCount = await page.$$eval("#graphfy-canvas .sd-graphfy-wires path", els => els.length);
  console.log(`Graphfy: nodes=${nodeCount}, wires=${wiresCount}`);
  if (nodeCount < 4) throw new Error("Graphfy canvas missing nodes");
  await page.screenshot({ path: `${brainDir}/settings-dashboard-graphfy.png` });

  console.log("All new sidebar verifications passed!");
  await browser.close();
}

run().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});
