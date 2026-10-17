// E2E: bot linh vật đã gỡ hẳn (ngài 2026-10-17): không còn trên thanh lệnh, không còn thẻ chọn linh vật trong Settings > Người
//  dùng, và không tải thư viện bot-avatars. Chữ/quả cầu trạng thái vẫn theo trạng thái JARVIS (sự kiện jarvis:mascot giữ lại).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/no-mascot.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const urls = [];
  page.on("request", (r) => urls.push(r.url()));
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);

  check(!(await page.$("#jarvis-bot")), "1. thanh lệnh không còn bot linh vật (#jarvis-bot)");
  check(!urls.some((u) => /bot-avatars/.test(u)), "2. không tải thư viện bot-avatars", urls.filter((u) => /bot/i.test(u)).join(" ").slice(0, 200));

  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click());
  await page.waitForTimeout(800);
  await page.click('.sd-nav-item[data-page="user"]');
  await page.waitForTimeout(600);
  const s = await page.evaluate(() => ({ card: !!document.getElementById("card-bot-mascot"), grid: !!document.getElementById("bot-selector-grid"), page: !!document.querySelector("#page-user:not([hidden])") }));
  check(s.page && !s.card && !s.grid, "3. Settings > Người dùng không còn thẻ chọn linh vật", JSON.stringify(s));
  await page.evaluate(() => document.getElementById("settings-close").click());
  await page.waitForTimeout(600);

  // the status label still follows JARVIS's state through jarvis:mascot
  sock.send(JSON.stringify({ type: "status", state: "thinking" }));
  await page.waitForTimeout(400);
  const label = await page.$eval("#status-text", (e) => e.textContent.trim());
  check(label === "Đang nghĩ…", "4. chữ trạng thái vẫn theo trạng thái (không phụ thuộc bot)", label);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
