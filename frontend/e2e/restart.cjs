// E2E: nút Restart Server. Server khởi động chậm (ở đây 45s) thì giao diện vẫn phải tự nối lại và
// xóa "Đang khởi động lại…", không được báo thất bại chỉ vì WebSocket thử lại theo nhịp lùi dần.
// Đồng hồ giả của Playwright; WebSocket và /api bị mock (không chạm JARVIS thật).
// Chạy: PW=<module playwright> node frontend/e2e/restart.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function run(browser, bootSeconds) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  if (process.env.DBG) page.on('console', (m) => /\[ws\]/.test(m.text()) && console.log('  ', m.text().slice(0, 90)));
  await page.clock.install();
  let serverUp = true, first = null, restartCalls = 0;
  await page.routeWebSocket(/\/ws/, (ws) => {
    if (!serverUp) { ws.close(); return; }
    if (!first) first = ws;
  });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/restart", (r) => { restartCalls++; r.fulfill({ json: { status: "restarting" } }); });
  await page.goto(BASE);
  for (let i = 0; i < 50 && !first; i++) await page.waitForTimeout(100);
  await page.clock.fastForward(5000); // để các hẹn giờ khởi động của trang chạy xong trước
  await page.waitForTimeout(100);
  const text = () => page.$eval("#status-text", (e) => e.textContent);
  await page.evaluate(() => document.getElementById("btn-restart").click());
  await page.waitForTimeout(100);
  serverUp = false; first.close(); // server tắt
  const before = await text();
  let t = 0;
  for (; t < bootSeconds; t++) { await page.clock.fastForward(1000); await page.waitForTimeout(25); if (process.env.DBG && t % 5 === 0) console.log('  t=' + t, await text()); }
  const mid = await text();
  serverUp = true; // server khởi động xong
  for (let i = 0; i < 15; i++) { await page.clock.fastForward(1000); await page.waitForTimeout(40); }
  const after = await text();
  await page.close();
  return { before, mid, after, restartCalls };
}

(async () => {
  const browser = await chromium.launch();
  const r = await run(browser, 45);
  check(r.restartCalls === 1 && /khởi động lại/i.test(r.before), "1. bấm Restart → gọi /api/restart, hiện 'Đang khởi động lại…'", `${r.before} · gọi ${r.restartCalls} lần`);
  check(!/thất bại/.test(r.mid), "2. server còn đang khởi động (45s) → chưa báo thất bại", r.mid);
  check(!/khởi động lại|thất bại/i.test(r.after), "3. server lên rồi → giao diện tự nối lại và xóa trạng thái restart", r.after);
  const f = await run(browser, 140);
  check(/thất bại/.test(f.mid), "4. server không lên nổi (140s) → báo thất bại", f.mid);
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
