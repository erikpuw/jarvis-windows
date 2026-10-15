// E2E: lớp chào (src/welcome.ts) — dòng chào theo 8 khung giờ của greeting cũ, và chữ xoay tên công cụ ngẫu nhiên trượt lên
//  hoặc xuống (ngài 2026-10-16). Đồng hồ giả (page.clock); WS và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/welcome-rotate.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const SLOTS = [[0, "Đêm khuya rồi"], [5, "Chào buổi sáng sớm"], [7, "Chào buổi sáng"], [11, "Chào buổi trưa"],
  [13, "Chào buổi chiều"], [17, "Chào buổi xế chiều"], [19, "Chào buổi tối"], [22, "Khuya rồi"]];

async function open(browser, time) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.clock.install({ time });
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForSelector(".welcome-hello");
  return { page, sock: () => sock };
}

(async () => {
  const browser = await chromium.launch();
  // 1. 8 khung giờ: đầu và cuối mỗi khung
  const got = [];
  for (const [i, [start, want]] of SLOTS.entries()) {
    const end = (SLOTS[i + 1]?.[0] ?? 24) - 1;
    for (const h of [start, end]) {
      const { page } = await open(browser, new Date(2026, 9, 16, h, 30));
      const text = await page.$eval(".welcome-hello", (e) => e.textContent);
      if (text !== want) got.push(`${h}h: ${text} ≠ ${want}`);
      await page.close();
    }
  }
  check(got.length === 0, "1. dòng chào theo 8 khung giờ của greeting cũ (đầu và cuối mỗi khung)", got.join("; "));

  // 2. chữ xoay: mỗi lần đổi, ngẫu nhiên trượt lên hoặc xuống — 20 lần phải thấy cả hai chiều
  const { page, sock } = await open(browser, new Date(2026, 9, 16, 20, 0));
  for (let i = 0; i < 50 && !sock(); i++) await page.clock.runFor(100);
  await page.evaluate(() => {
    window.__dirs = [];
    new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => window.__dirs.push(n.className)))).observe(document.querySelector(".welcome-slot"), { childList: true });
  });
  sock().send(JSON.stringify({ type: "welcome", tools: ["Thời tiết", "Tin tức", "Lịch âm", "Tử vi", "Bách khoa"] }));
  await page.clock.runFor(500);
  for (let i = 0; i < 20; i++) await page.clock.runFor(2200);
  const dirs = await page.evaluate(() => window.__dirs);
  const up = dirs.filter((d) => d === "below").length, down = dirs.filter((d) => d === "above").length;
  check(up > 0 && down > 0 && up + down === dirs.length, "2. chữ xoay ngẫu nhiên trượt lên (vào từ dưới) và xuống (vào từ trên)", JSON.stringify({ up, down, n: dirs.length }));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
