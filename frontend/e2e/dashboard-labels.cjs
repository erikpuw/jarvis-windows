// E2E: Dashboard speaks Vietnamese (user approved the name table 2026-10-18; "Restart" stays) and the page head's
// Restart button lines up with the close button (same top and bottom), its icon a morphicon like the other buttons.
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/dashboard-labels.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const NAV = { agents: "Gọi tên (@)", commands: "Lệnh (/)", skills: "Kỹ năng", prompts: "Lời nhắc hệ thống", hooks: "Móc sự kiện",
  plugins: "Tiện ích mở rộng", mcp: "Kết nối MCP", graphfy: "Bản đồ mã" };
const SERVICES = ["Lõi trí tuệ", "Máy chủ chính", "Máy chủ LLM", "Máy chủ giọng đọc", "Dịch vụ LLM", "RAG", "Cơ sở dữ liệu", "Trung tâm hệ thống"];
const ENGLISH = /\b(Dashboard|Mention|Commands|Skills|Prompts|Hooks|Plugins|MCP Connect|Graphfy|Intelligence Core|Server Engine|System Hub|LLM Server|LLM Service|TTS Server|SQLite DB|Input|Output)\b/;

async function open(browser, viewport) {
  const page = await (await browser.newContext({ viewport })).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  return page;
}

(async () => {
  const browser = await chromium.launch();
  const pc = await open(browser, { width: 1440, height: 900 });

  // 1. menu + its title
  const nav = await pc.evaluate(() => ({ title: document.querySelector("#settings-nav .sd-title")?.textContent.trim(),
    items: Object.fromEntries([...document.querySelectorAll(".sd-nav-item")].map((b) => [b.dataset.page, b.textContent.trim()])) }));
  const navBad = Object.entries(NAV).filter(([id, label]) => nav.items[id] !== label);
  check(/^Bảng điều khiển/.test(nav.title || "") && !navBad.length, "1. menu và tiêu đề menu bằng tiếng Việt", JSON.stringify({ title: nav.title, navBad }));

  // 2. Tổng quan: service names and token labels
  await pc.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click());
  await pc.waitForTimeout(800);
  const ov = await pc.evaluate(() => ({ services: [...document.querySelectorAll("#section-status .status-name")].map((e) => e.textContent.trim()),
    text: document.getElementById("page-overview").innerText }));
  const eng = (ov.text.match(ENGLISH) || [])[0];
  check(JSON.stringify(ov.services) === JSON.stringify(SERVICES) && !eng, "2. Tổng quan: tên dịch vụ và nhãn tiếng Việt, không còn chữ Anh trong bảng",
    JSON.stringify({ services: ov.services, eng }));

  // 3-4. Restart keeps its name, lines up with the close button, morphicon (PC + phone)
  const head = async (page) => {
    await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="connect"]').click());
    await page.waitForTimeout(800);
    return page.evaluate(() => {
      const r = document.getElementById("btn-restart").getBoundingClientRect(), c = document.getElementById("settings-close").getBoundingClientRect();
      return { dt: Math.round(r.top - c.top), db: Math.round(r.bottom - c.bottom), text: document.getElementById("btn-restart").textContent.trim(),
        morph: !!document.querySelector("#btn-restart > morph-icon"), svg: !!document.querySelector("#btn-restart > svg") };
    });
  };
  const hp = await head(pc);
  check(hp.text === "Restart" && Math.abs(hp.dt) <= 1 && Math.abs(hp.db) <= 1 && hp.morph && !hp.svg, "3. PC: nút Restart giữ tên, thẳng hàng nút đóng, icon morphicon", JSON.stringify(hp));
  await pc.context().close();
  const ph = await open(browser, { width: 390, height: 844 });
  const hm = await head(ph);
  check(Math.abs(hm.dt) <= 1 && Math.abs(hm.db) <= 1 && hm.morph, "4. điện thoại: nút Restart thẳng hàng nút đóng", JSON.stringify(hm));
  await ph.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
