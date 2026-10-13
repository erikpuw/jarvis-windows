const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";

function status() {
  return {
    success: true, intelligence_core_ok: true, server_engine_ok: true, llm_server_ok: true, tts_server_ok: true,
    memory_count: 142, semantic_memory_count: 89, conversation_turn_count: 1204, task_count: 36,
    skill_count: 18, command_count: 42, server_port: 8000, uptime_seconds: 7320, open_apps: ["code.exe", "chrome.exe", "terminal.exe"],
    env_keys_set: { llama: true, fish_audio: true, fish_voice_id: true, user_name: "Erik" },
    system: { cpu_percent: 24.5, ram_percent: 48.2, ram_used_gb: 7.7, ram_total_gb: 16.0,
      gpus: [{ name: "NVIDIA RTX 4090", mem_used_mb: 8192, vram_total_mb: 24576 }], npus: [] },
    session_tokens: { input: 12450, output: 8320, total: 20770 }, mcp_servers: {}, agents: [],
  };
}

async function capture() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  
  await page.routeWebSocket(/\/ws/, () => {});
  const json = (r, body) => r.fulfill({ json: body });
  await page.route("**/api/**", (r) => json(r, { success: true }));
  await page.route("**/api/settings/status**", (r) => json(r, status()));
  await page.route("**/api/health/detailed", (r) => json(r, {
    llm: { status: "online", response_time_ms: 120 }, redis: { status: "online" },
    database: { ok: true, size_kb: 512 }, rag: { enabled: true, total_chunks: 10, files_count: 2 },
  }));
  await page.route("**/api/settings/preferences", (r) => json(r, { user_name: "Erik", honorific: "sir", calendar_accounts: "auto" }));

  await page.goto(BASE);
  await page.waitForSelector("#btn-menu");
  await page.click("#btn-menu");
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForSelector("#settings-container.open");
  await page.waitForTimeout(600);

  const outPath = "C:/Users/erikpuw/.gemini/antigravity-ide/brain/3985ccd9-bf5e-40f3-a6b7-89f701c686e2/settings-dashboard-framed-icons.png";
  await page.screenshot({ path: outPath });
  console.log("Captured framed sidebar screenshot:", outPath);
  await browser.close();
}

capture().catch(e => {
  console.error(e);
  process.exit(1);
});
