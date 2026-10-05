// E2E: avatar (bot) vẽ 60 khung/giây ở cả máy tính lẫn điện thoại (màn cảm ứng), orb trạng thái nhỏ cũng 60.
// Đếm số lần vẽ lại mỗi giây (các lệnh clearRect liền nhau trong 5ms là một khung) bằng init script. WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/bot-fps.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  for (const [name, o] of [["máy tính", { viewport: { width: 1280, height: 800 } }], ["điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }]]) {
    const ctx = await browser.newContext(o);
    await ctx.addInitScript(() => {
      window.__c = { bot: 0, status: 0 }; window.__last = {};
      const d = CanvasRenderingContext2D.prototype.clearRect;
      CanvasRenderingContext2D.prototype.clearRect = function (...a) {
        const c = this.canvas, k = c.closest && c.closest("#jarvis-bot") ? "bot" : c.closest && c.closest("#status-orb") ? "status" : null;
        if (k) { const n = performance.now(); if (n - (window.__last[k] ?? -99) > 5) window.__c[k]++; window.__last[k] = n; }
        return d.apply(this, a);
      };
    });
    const page = await ctx.newPage();
    await page.routeWebSocket(/\/ws/, () => {});
    await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
    await page.goto(BASE); await page.waitForTimeout(2000);
    await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
    await page.waitForTimeout(500);
    const a = await page.evaluate(() => ({ ...window.__c, t: performance.now() }));
    await page.waitForTimeout(2000);
    const z = await page.evaluate(() => ({ ...window.__c, t: performance.now() }));
    const dt = (z.t - a.t) / 1000, bot = (z.bot - a.bot) / dt, status = (z.status - a.status) / dt;
    check(bot >= 55, `[${name}] avatar vẽ ~60 khung/giây (không bị giảm còn 30)`, `${bot.toFixed(1)}/s`);
    check(status >= 55, `[${name}] orb trạng thái nhỏ ~60 khung/giây`, `${status.toFixed(1)}/s`);
    await ctx.close();
  }
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
