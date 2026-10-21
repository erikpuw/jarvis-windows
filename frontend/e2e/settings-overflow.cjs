// E2E: mọi trang trong Settings (sidebar) phải gói gọn theo bề ngang màn hình, trên điện thoại (390px), máy tính bảng (768px) và máy tính (1280px):
//  không có chữ/khối nào tràn ra ngoài khung làm trang phải kéo ngang mới thấy hết; chuỗi dài không có dấu cách (ví dụ "a|b|c|d..." trong tham số lệnh,
//  đường dẫn file, tên dài) phải tự xuống dòng hoặc rút gọn "…", cột lưới co theo màn hình.
// Dữ liệu thật: danh mục Agents/Hooks/Skills/Prompts/Commands/Plugins lấy từ chính repo (api_settings_catalog gọi trực tiếp bằng Python, không mở server)
// cộng thêm vài mục "khó" (chuỗi rất dài). WebSocket và /api khác bị mock. Trang Bộ nhớ và Nhật ký khóa mật khẩu nên đã có test riêng.
// Chạy: PW=<module playwright> node frontend/e2e/settings-overflow.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { execFileSync } = require("child_process");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
const ROOT = path.join(__dirname, "..", "..");
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

function realCatalog() {
  try {
    const code = "import asyncio,json,sys\nsys.path.insert(0,'.')\nfrom engine.UIUX import ui_engine\nr=asyncio.run(ui_engine.api_settings_catalog())\nsys.stdout.buffer.write(json.dumps(json.loads(r.body) if hasattr(r,'body') else r,ensure_ascii=False).encode('utf-8'))";
    return JSON.parse(execFileSync("python", ["-c", code], { cwd: ROOT, maxBuffer: 64 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] }).toString("utf8"));
  } catch { return null; }
}
const LONG = "một_chuỗi_rất_dài_không_có_dấu_cách_" + "abcdefghij".repeat(12);
const catalog = realCatalog() || { success: true, mentions: [], hooks: [], skills: [], prompts: [], commands: [], plugins: [] };
catalog.commands.push({ name: "lenh_kho", file: "lenh_kho.md", file_path: "commands/" + LONG + ".md", description: "Mô tả " + LONG, usage: "/lenh_kho <" + LONG + ">" });
catalog.mentions.push({ id: "agent_kho", name: "agent_kho", file: LONG + ".py", description: LONG, example: "@agent_kho " + LONG, mention: "@agent_kho" });
catalog.plugins.push({ name: "Plugin " + LONG, file: LONG + ".py", description: LONG, runtime: "python" });
catalog.hooks.push({ name: LONG, file: LONG + ".py", description: LONG, events: ["a", "b"] });
catalog.skills.push({ name: LONG, file: LONG + "/skill.md", description: LONG });
const README = fs.readFileSync(path.join(ROOT, "README.md"), "utf8");
const MAP = { success: true, nodes: [{ id: "server", label: "server", lane: "input" }, { id: "router", label: "router", lane: "turn" }], edges: [{ from: "server", to: "router", kind: "import" }] };

async function audit(browser, label, vp) {
  const ctx = await browser.newContext(vp);
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/settings/status**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true }, intelligence_core_ok: true, server_engine_ok: true, llm_server_ok: true, system: { cpu_percent: 5, ram_percent: 40, ram_used_gb: 6, ram_total_gb: 16, gpus: [] } } }));
  await page.route("**/api/settings/catalog", (r) => r.fulfill({ json: catalog }));
  await page.route("**/api/system/readme", (r) => r.fulfill({ json: { success: true, content: README } }));
  await page.route("**/api/graphfy", (r) => r.fulfill({ json: MAP }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click());
  await page.waitForTimeout(500);
  const pages = await page.$$eval(".sd-nav-item[data-page]", (n) => n.map((x) => x.dataset.page));
  for (const id of pages) {
    if (id === "memory" || id === "logs") continue; // khóa mật khẩu, test riêng (settings-protected.cjs)
    await page.evaluate((x) => { document.querySelector(`.sd-nav-item[data-page="${x}"]`).click(); }, id);
    await page.waitForTimeout(900);
    const r = await page.evaluate((id) => {
      const root = document.querySelector(`.sd-page[data-page="${id}"]`), content = document.getElementById("settings-content");
      const cr = content.getBoundingClientRect();
      const clippedUntil = (el, stop) => { for (let n = el.parentElement; n && n !== stop; n = n.parentElement) { const o = getComputedStyle(n).overflowX; if (o !== "visible") return true; } return false; };
      const bad = [];
      for (const el of root.querySelectorAll("*")) {
        const b = el.getBoundingClientRect();
        if (b.width === 0 || b.height === 0) continue;
        // chữ tràn ra khỏi ô của chính nó (chuỗi dài không có chỗ ngắt, nowrap không rút gọn): khung phần tử không vượt nhưng chữ thì có
        const cs = getComputedStyle(el);
        if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1.5 && cs.overflowX === "visible" && !clippedUntil(el, content) && !el.matches("pre, svg, svg *")) bad.push(`${el.tagName.toLowerCase()}.${(el.className || "").toString().split(" ")[0]} chữ tràn ${el.scrollWidth - el.clientWidth}px khỏi ô của nó "${(el.textContent || "").trim().slice(0, 36)}"`);
        const card = el.closest(".sd-card, .sd-agent-card");
        if (b.right > cr.right + 1.5 && !clippedUntil(el, content)) bad.push(`${el.tagName.toLowerCase()}.${(el.className || "").toString().split(" ")[0]} +${Math.round(b.right - cr.right)}px ra ngoài trang "${(el.textContent || "").trim().slice(0, 28)}"`);
        else if (card && card !== el) { const r = card.getBoundingClientRect(); if (b.right > r.right + 1.5 && !clippedUntil(el, card.parentElement)) bad.push(`${el.tagName.toLowerCase()}.${(el.className || "").toString().split(" ")[0]} +${Math.round(b.right - r.right)}px ra ngoài thẻ "${(el.textContent || "").trim().slice(0, 28)}"`); }
      }
      return { sw: content.scrollWidth, cw: content.clientWidth, doc: document.documentElement.scrollWidth, vw: window.innerWidth, bad: bad.slice(0, 4), n: bad.length, cards: root.querySelectorAll(".sd-agent-card").length };
    }, id);
    check(r.sw <= r.cw + 1 && r.doc <= r.vw + 1 && r.n === 0, `[${label}] ${id}: gói gọn theo bề ngang${r.cards ? ` (${r.cards} thẻ)` : ""}`, r.sw <= r.cw + 1 && r.n === 0 ? "" : `nội dung ${r.sw}>${r.cw}; ${r.n} phần tử tràn: ${r.bad.join(" | ")}`);
  }
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  await audit(browser, "điện thoại 390", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await audit(browser, "máy tính bảng 768", { viewport: { width: 768, height: 1024 } });
  await audit(browser, "máy tính 1280", { viewport: { width: 1280, height: 800 } });
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
