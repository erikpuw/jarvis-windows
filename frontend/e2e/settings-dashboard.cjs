// E2E cho Settings dashboard toàn màn hình (spec 2026-09-27).
// Mọi /api và /ws đều bị mock — không chạm JARVIS thật.
// Chạy: PW=<module playwright> node frontend/e2e/settings-dashboard.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

function status(hasKey) {
  return {
    success: true, intelligence_core_ok: true, server_engine_ok: true, llm_server_ok: true, tts_server_ok: false,
    memory_count: 6, semantic_memory_count: 3, conversation_turn_count: 86, task_count: 0,
    skill_count: 2, command_count: 33, server_port: 8340, uptime_seconds: 3700, open_apps: ["notepad.exe"],
    env_keys_set: { llama: hasKey, fish_audio: true, fish_voice_id: false, user_name: "Erik" },
    system: { cpu_percent: 37, ram_percent: 52, ram_used_gb: 8.1, ram_total_gb: 15.7,
      gpus: [{ name: "RTX 4060", mem_used_mb: 4096, vram_total_mb: 8188 }], npus: [] },
    session_tokens: { input: 0, output: 0, total: 0 }, mcp_servers: {}, agents: [],
    runtime: { llm_model: "gemma-4", embed_model: "bge-m3", tts_engine: "vieneu", vieneu_voice: "Adam", edge_voice: "vi-VN-NamMinhNeural" },
  };
}

async function newPage(browser, { width, height, hasKey = true }) {
  const page = await browser.newPage({ viewport: { width, height } });
  const calls = [];
  // Đếm frame của orb: vòng lặp trong orb.ts là callback rAF tên "animate".
  await page.addInitScript(() => {
    window.__orbFrames = 0;
    const raf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (cb) => { if (cb.name === "animate") window.__orbFrames++; return raf(cb); };
  });
  await page.routeWebSocket(/\/ws/, () => {}); // không bao giờ nối tới JARVIS thật
  const json = (r, body) => r.fulfill({ json: body });
  let items = Array.from({ length: 4 }, (_, i) => ({ id: i + 1, semantic_key: `k${i + 1}`, content: `c${i + 1}` }));
  // Route đăng ký sau được ưu tiên trước: catch-all phải đứng đầu.
  await page.route("**/api/**", (r) => json(r, { success: true }));
  await page.route("**/api/settings/status**", (r) => json(r, status(hasKey)));
  await page.route("**/api/health/detailed", (r) => json(r, {
    llm: { status: "online", response_time_ms: 120 }, redis: { status: "online" },
    database: { ok: true, size_kb: 512 }, rag: { enabled: true, total_chunks: 10, files_count: 2 },
  }));
  await page.route("**/api/settings/preferences", (r) => {
    if (r.request().method() === "POST") { calls.push(["prefs", r.request().postDataJSON()]); return json(r, { success: true }); }
    return json(r, { user_name: "Erik", honorific: "sir", calendar_accounts: "auto" });
  });
  // Mirrors engine/UIUX/ui_engine.py api_save_key: only these names are accepted (400 otherwise).
  const ALLOWED_KEYS = new Set(["LOCAL_API_KEY", "TTS_LOCAL_KEY", "LOCAL_URL", "TTS_LOCAL_MODEL", "USER_NAME", "HONORIFIC"]);
  await page.route("**/api/settings/keys", (r) => {
    const b = r.request().postDataJSON(); calls.push(["keys", b]);
    if (!ALLOWED_KEYS.has(b.key_name)) return r.fulfill({ status: 400, json: { success: false, error: `Key không hợp lệ: ${b.key_name}` } });
    return json(r, { success: true });
  });
  await page.route("**/api/prompts/save", (r) => { calls.push(["prompt", r.request().postDataJSON()]); return json(r, { success: true }); });
  await page.route("**/api/tts/voice", (r) => { calls.push(["voice", r.request().postDataJSON()]); return json(r, { success: true }); });
  await page.route("**/api/settings/catalog", (r) => { calls.push(["catalog"]); return json(r, {
    success: true, hooks: [], skills: [], plugins: [],
    prompts: [{ id: "chat", name: "chat.md", title: "Chat", description: "d", content: "old prompt", file_path: "prompt/chat.md" }],
    commands: [{ name: "check_mail", file: "check_mail.md", description: "d", usage: `'{"max_results": "Số email"}'` }],
    agents: [{ id: "desktop", name: "Agent Desktop", file: "agent_desktop.py", description: "d", example: "mở notepad", tools: [] }],
  }); });
  await page.route("**/api/settings/test-llama", (r) => json(r, { valid: true }));
  await page.route("**/api/settings/test-fish", (r) => json(r, { valid: false, error: "bad key" }));
  await page.route("**/api/tts/voices", (r) => json(r, {
    engine: "vieneu", current: "a", voices: [{ name: "a", label: "Giọng A", kind: "preset" }],
  }));
  // Memory Control is password-locked: the fake backend accepts any password
  await page.route("**/api/memory-lock/status", (r) => r.fulfill({ json: { configured: true } }));
  await page.route("**/api/memory-lock/unlock", (r) => r.fulfill({ json: { success: true, token: "t" } }));
  await page.route("**/api/memory-lock/lock", (r) => r.fulfill({ json: { success: true } }));
  await page.route("**/api/memory-control/summary", (r) => json(r, { success: true, counts: { learnings: items.length } }));
  await page.route("**/api/learnings/list**", (r) => json(r, { success: true, learnings: items, total: items.length }));
  await page.route("**/api/memory-control/delete", (r) => {
    const b = r.request().postDataJSON(); calls.push(["delete", b]);
    items = items.filter((i) => i.id !== b.id);
    return json(r, { success: true });
  });
  page.on("dialog", (d) => { calls.push(["dialog", d.type(), d.message()]); d.accept(); });
  await page.goto(BASE);
  await page.waitForSelector("#btn-menu morph-icon path");
  return { page, calls };
}

async function openViaMenu(page) {
  await page.click("#btn-menu");
  await page.click("#btn-settings");
  await page.waitForSelector("#settings-container.open");
  await page.waitForTimeout(400);
}
const visiblePage = (page) =>
  page.$$eval(".sd-page", (els) => els.filter((e) => !e.hidden).map((e) => e.dataset.page).join(","));
const orbFramesIn = async (page, ms) => {
  const a = await page.evaluate(() => window.__orbFrames);
  await page.waitForTimeout(ms);
  return (await page.evaluate(() => window.__orbFrames)) - a;
};

const LEGACY_IDS = [
  "settings-close", "settings-welcome", "setup-nav", "btn-setup-next",
  "input-llama-key", "btn-test-llama", "status-llama", "input-llama-url", "btn-save-llama-url",
  "input-fish-key", "btn-test-fish", "status-fish", "btn-save-keys",
  "field-vieneu-voice", "select-vieneu-voice", "btn-save-voice-id", "input-clone-name", "input-clone-file",
  "btn-upload-clone", "voice-hint",
  "input-user-name", "input-honorific", "input-calendar-accounts", "btn-save-prefs",
  "health-cpu-val", "health-cpu-bar", "health-ram-val", "health-ram-bar", "health-gpus-container",
  "status-intelligence-core", "status-server-engine", "status-llm-server", "status-tts-server",
  "status-server", "status-server-detail",
  "row-status-llm", "row-status-redis", "row-status-db", "row-status-rag", "apps-list-container",
  "sysinfo-memory", "sysinfo-turns", "sysinfo-tasks", "sysinfo-skills",
  "sysinfo-commands", "sysinfo-port", "sysinfo-uptime",
  "memory-category-nav", "memory-search-input", "btn-memory-search", "memory-select-all",
  "memory-bulk-delete", "memory-list-container", "memory-page-prev", "memory-page-status",
  "memory-page-next", "memory-detail-container",
];
const PAGES = ["overview", "connect", "voice", "user", "system", "memory"];

(async () => {
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl"] });

  // ── Desktop 1920×1080 ──
  {
    const { page, calls } = await newPage(browser, { width: 1920, height: 1080 });
    check((await orbFramesIn(page, 500)) > 0, "0. orb chạy trước khi mở settings");
    await openViaMenu(page);
    const box = await page.$eval("#settings-panel-inner", (e) => {
      const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map(Math.round).join();
    });
    check(box === "0,0,1920,1080", "1. panel phủ toàn màn hình", box);
    check((await orbFramesIn(page, 500)) === 0, "5a. orb tạm dừng khi settings mở");
    check((await visiblePage(page)) === "overview", "2a. mặc định mở Tổng quan", await visiblePage(page));
    check((await page.textContent("#ov-cpu-val")).includes("37"), "2b. ô CPU lấy số từ status");
    check((await page.textContent("#ov-llm-model")) === "gemma-4" && (await page.textContent("#ov-tts-engine")).includes("VieNeu · Adam"),
      "16. Tổng quan hiện mô hình và TTS đang chạy");
    check(await page.$eval("#voice-dot-vieneu", (e) => e.classList.contains("status-green"))
      && await page.$eval("#voice-dot-edge", (e) => !e.classList.contains("status-green"))
      && (await page.textContent("#voice-edge-current")).includes("vi-VN-NamMinhNeural"),
      "17. Giọng đọc: chấm xanh đúng engine đang chạy, hiện giọng Edge đã lưu");
    for (const id of [...PAGES.slice(1), "overview"]) {
      await page.click(`.sd-nav-item[data-page="${id}"]`);
      check((await visiblePage(page)) === id, `2c. sidebar → ${id}`, await visiblePage(page));
    }
    const missing = await page.evaluate((ids) => ids.filter((id) => !document.getElementById(id)), LEGACY_IDS);
    check(missing.length === 0, "3. giữ đủ ID cũ", missing.join(","));

    await page.click('.sd-nav-item[data-page="connect"]');
    await page.fill("#input-llama-key", "k-123");
    await page.click("#btn-save-keys");
    check(await page.$eval("#btn-save-keys", (b) => b.classList.contains("is-busy") || b.classList.contains("is-ok")),
      "4a. nút Lưu vào trạng thái bận/xong");
    await page.waitForSelector("#btn-save-keys.is-ok", { timeout: 3000 }).catch(() => {});
    check(await page.$eval("#btn-save-keys", (b) => b.classList.contains("is-ok")), "4b. nút Lưu báo thành công");
    check(calls.some(([k, b]) => k === "keys" && b.key_name === "LOCAL_API_KEY" && b.key_value === "k-123"),
      "4c. Lưu gọi /api/settings/keys với LOCAL_API_KEY");
    check(!calls.some(([k, b]) => k === "keys" && !["LOCAL_API_KEY", "TTS_LOCAL_KEY", "LOCAL_URL"].includes(b.key_name)),
      "4c2. không gửi tên key backend từ chối", JSON.stringify(calls.filter(([k]) => k === "keys")));
    check(!!(await page.$("#btn-save-keys morph-icon")), "4d. nút Lưu có morph icon");
    await page.click("#btn-test-fish");
    await page.waitForSelector("#btn-test-fish.is-error", { timeout: 3000 }).catch(() => {});
    check(await page.$eval("#btn-test-fish", (b) => b.classList.contains("is-error")), "4e. Test lỗi → trạng thái lỗi");
    check((await page.textContent('[data-feedback-for="btn-test-fish"]')).includes("bad key"), "4f. lỗi hiện cạnh nút");

    await page.click('.sd-nav-item[data-page="voice"]');
    await page.waitForFunction(() => document.querySelector('#select-vieneu-voice option[value="a"]'), null, { timeout: 3000 }).catch(() => {});
    check(!!(await page.$('#select-vieneu-voice option[value="a"]')), "10a. nạp danh sách giọng từ /api/tts/voices");
    await page.click("#btn-save-voice-id");
    await page.waitForTimeout(400);
    check(calls.some(([k, b]) => k === "voice" && b.voice === "a"), "10b. Lưu giọng gọi /api/tts/voice");

    await page.click('.sd-nav-item[data-page="agents"]');
    await page.waitForTimeout(500);
    check(calls.some(([k]) => k === "catalog") && (await page.textContent("#agents-grid")).includes("Agent Desktop"),
      "11. trang Agents lấy dữ liệu từ /api/settings/catalog");

    await page.click('.sd-nav-item[data-page="commands"]');
    await page.waitForTimeout(400);
    const cmdText = await page.textContent("#commands-grid");
    check(cmdText.includes("/check_mail <max_results>") && cmdText.includes("Số email"),
      "14. Commands hiện cú pháp /lệnh và tham số thật", cmdText.slice(0, 160));

    await page.click('.sd-nav-item[data-page="prompts"]');
    await page.waitForTimeout(400);
    await page.click('.btn-view-prompt[data-prompt-id="chat"]');
    await page.fill("#prompt-preview-code", "new prompt");
    await page.click("#btn-prompt-save");
    await page.waitForTimeout(500);
    check(calls.some(([k, b]) => k === "prompt" && b.id === "chat" && b.content === "new prompt"), "15. sửa và lưu prompt");
    await page.click("#prompt-preview-close");

    await page.click('.sd-nav-item[data-page="memory"]');
    await page.fill("#memory-lock-input", "x"); await page.click("#memory-lock-btn"); // Memory Control đòi mật khẩu
    await page.waitForSelector('[data-memory-record-id="1"]');
    await page.click('[data-memory-record-id="1"]');
    await page.waitForTimeout(300);
    const widths = await page.evaluate(() => {
      const grid = document.querySelector(".sd-memory").getBoundingClientRect();
      const detail = document.getElementById("memory-detail-container").getBoundingClientRect();
      return { grid: Math.round(grid.width), detail: Math.round(detail.width), right: Math.round(grid.right - detail.right) };
    });
    check(widths.detail > widths.grid * 0.4 && widths.right < 4, "12. cột chi tiết Bộ nhớ lấp phần còn lại", JSON.stringify(widths));
    const shouting = await page.evaluate(() => [...document.querySelectorAll("#settings-container *")]
      .filter((e) => e.childElementCount === 0 && e.textContent.trim() && getComputedStyle(e).textTransform === "uppercase")
      .map((e) => e.textContent.trim().slice(0, 30)));
    check(shouting.length === 0, "13. không có chữ IN HOA ép bằng CSS", shouting.join(" | "));

    await page.click('.sd-nav-item[data-page="voice"]');
    await page.keyboard.press("Escape");
    check(await page.$eval("#settings-container", (e) => !e.classList.contains("open")), "6. Esc đóng settings");
    await page.waitForTimeout(400);
    check((await orbFramesIn(page, 500)) > 0, "5b. orb chạy lại sau khi đóng");
    await openViaMenu(page);
    check((await visiblePage(page)) === "voice", "2d. nhớ trang đang xem", await visiblePage(page));

    await page.click('.sd-nav-item[data-page="memory"]');
    await page.fill("#memory-lock-input", "x"); await page.click("#memory-lock-btn"); // Memory Control đòi mật khẩu
    await page.waitForSelector('[data-memory-record-id="4"]');
    await page.click("#memory-select-all");
    check((await page.textContent("#memory-bulk-delete")).includes("(4)"), "8a. đếm số mục đã chọn");
    await page.click("#memory-bulk-delete");
    await page.waitForFunction(() => document.querySelectorAll("[data-memory-record-id]").length === 0, null, { timeout: 6000 })
      .catch(() => {});
    check(calls.filter(([k]) => k === "delete").length === 4, "8b. xoá lần lượt 4 mục");
    check(calls.filter(([k, t]) => k === "dialog" && t === "confirm").length === 1, "8c. hỏi xác nhận đúng 1 lần");
    await page.close();
  }

  // ── Mobile 375×812 ──
  {
    const { page } = await newPage(browser, { width: 375, height: 812 });
    await openViaMenu(page);
    const navVisible = () => page.$eval("#settings-nav", (e) =>
      getComputedStyle(e).visibility === "visible" && e.getBoundingClientRect().right > 1);
    check(!(await navVisible()), "7a. ngăn kéo đóng mặc định");
    await page.click("#settings-menu-toggle");
    await page.waitForTimeout(300);
    check(await navVisible(), "7b. nút ☰ mở ngăn kéo");
    await page.click('.sd-nav-item[data-page="user"]');
    await page.waitForTimeout(300);
    check(!(await navVisible()) && (await visiblePage(page)) === "user", "7c. chọn trang thì đóng ngăn kéo");
    const overflow = [];
    for (const id of PAGES) {
      await page.click("#settings-menu-toggle");
      await page.waitForTimeout(250);
      await page.click(`.sd-nav-item[data-page="${id}"]`);
      await page.waitForTimeout(250);
      const o = await page.evaluate(() => {
        const c = document.getElementById("settings-content");
        return c.scrollWidth > c.clientWidth + 1 || document.documentElement.scrollWidth > innerWidth;
      });
      if (o) overflow.push(id);
    }
    check(overflow.length === 0, "7d. không cuộn ngang ở 375px", overflow.join(","));

    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    await page.click("#btn-map"); // mobile: map mở thẳng toàn màn hình
    await page.waitForTimeout(400);
    check((await orbFramesIn(page, 400)) === 0, "5c. map toàn màn hình dừng orb");
    await page.evaluate(async () => {
      const m = await import("/src/settings/index.ts");
      await m.openSettings();
      m.closeSettings();
    });
    await page.waitForTimeout(400);
    check((await orbFramesIn(page, 500)) === 0, "5d. đóng settings không chạy lại orb khi map toàn màn hình");
    await page.close();
  }

  // ── Thu nhỏ sidebar: icon đứng yên, chữ mờ dần (không nhảy) ──
  {
    const { page } = await newPage(browser, { width: 1280, height: 800 });
    await openViaMenu(page);
    const iconX = () => page.$eval('.sd-nav-item[data-page="overview"] .sd-nav-icon', (e) => Math.round(e.getBoundingClientRect().x));
    const before = await iconX();
    await page.click("#settings-sidebar-toggle");
    const mid = await page.$eval('.sd-nav-item[data-page="overview"]', (b) => {
      const l = b.querySelector(".sd-nav-label"); const cs = getComputedStyle(l);
      return { display: cs.display, wrap: cs.whiteSpace, h: Math.round(b.getBoundingClientRect().height) };
    });
    check(mid.display !== "none" && mid.wrap === "nowrap" && mid.h <= 40, "18a. chữ không biến mất/xuống dòng giữa hiệu ứng", JSON.stringify(mid));
    check(Math.abs((await iconX()) - before) <= 1, "18b. icon không nhảy khi bắt đầu thu nhỏ", `${before}→${await iconX()}`);
    await page.waitForTimeout(400);
    check(Math.abs((await iconX()) - before) <= 1, "18c. icon cùng vị trí khi đã thu nhỏ", `${before}→${await iconX()}`);
    check(await page.$eval(".sd-nav-label", (l) => getComputedStyle(l).opacity === "0"), "18d. chữ ẩn hẳn khi thu nhỏ");
    await page.click("#settings-sidebar-toggle");
    check(await page.$eval('.sd-nav-item[data-page="overview"]', (b) => b.getBoundingClientRect().height <= 40), "18e. mở lại không xuống dòng");
    await page.close();
  }

  // ── Cài đặt lần đầu (chưa có key) ──
  {
    const { page } = await newPage(browser, { width: 1280, height: 800, hasKey: false });
    await page.waitForSelector("#settings-container.open", { timeout: 6000 }).catch(() => {});
    await page.waitForTimeout(400);
    check(await page.$eval("#settings-panel-inner", (e) => e.classList.contains("setup-mode")), "9a. bật chế độ cài đặt lần đầu");
    check(await page.$eval("#settings-nav", (e) => getComputedStyle(e).display === "none"), "9b. ẩn sidebar khi cài đặt");
    check((await visiblePage(page)) === "connect", "9c. bắt đầu ở trang Kết nối", await visiblePage(page));
    await page.click("#btn-setup-next");
    await page.click("#btn-setup-next");
    check((await visiblePage(page)) === "user", "9d. bước 3 là trang Người dùng", await visiblePage(page));
    await page.click("#btn-setup-next");
    await page.waitForTimeout(400);
    check(await page.$eval("#settings-container", (e) => !e.classList.contains("open")), "9e. Hoàn tất thì đóng settings");
    await page.close();
  }

  await browser.close();
  console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
