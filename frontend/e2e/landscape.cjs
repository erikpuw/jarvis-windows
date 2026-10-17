// E2E: JARVIS trên điện thoại chỉ dùng chiều dọc (user 2026-10-15). iOS bỏ qua "orientation": "portrait" của manifest và Safari
//  không cho trang khoá hướng, nên khi điện thoại nằm ngang (cảm ứng, cao ≤ 500px) cả trang bị một lớp che "xoay dọc" phủ kín
//  và mọi hiệu ứng dừng như lúc mở Settings; xoay lại dọc thì lớp che biến mất, hiệu ứng chạy lại. Máy tính không bị che.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/landscape.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const state = (page) => page.evaluate(() => {
  const s = getComputedStyle(document.body, "::after");
  return {
    cover: s.content !== "none" && s.content !== "normal" && s.display !== "none",
    text: s.content,
    covers: s.position === "fixed" && parseFloat(s.zIndex) >= 1000,
    paused: document.documentElement.classList.contains("anim-paused"),
  };
});

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(2000);

  let s = await state(page);
  check(!s.cover && !s.paused, "1. điện thoại dọc: không che, hiệu ứng chạy", JSON.stringify(s));

  for (const [w, h] of [[844, 390], [844, 320], [932, 430]]) {
    await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(500);
    s = await state(page);
    check(s.cover && s.covers && /xoay/i.test(s.text) && s.paused, `2. nằm ngang ${w}×${h}: lớp che "xoay dọc" phủ kín, hiệu ứng dừng`, JSON.stringify(s));
  }

  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(500);
  s = await state(page);
  check(!s.cover && !s.paused, "3. xoay lại dọc: hết che, hiệu ứng chạy lại", JSON.stringify(s));

  // Settings open while sideways: rotating back must not wake the page behind Settings
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click()); await page.waitForTimeout(600);
  await page.setViewportSize({ width: 844, height: 390 }); await page.waitForTimeout(400);
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(400);
  s = await state(page);
  check(!s.cover && s.paused, "4. đang mở Settings mà xoay ngang rồi dọc: hiệu ứng vẫn dừng (Settings còn mở)", JSON.stringify(s));
  await page.evaluate(() => document.getElementById("settings-close").click()); await page.waitForTimeout(600);
  s = await state(page);
  check(!s.paused, "5. đóng Settings: chạy lại", JSON.stringify(s));
  await ctx.close();

  const pc = await (await browser.newContext({ viewport: { width: 1280, height: 400 } })).newPage(); // a short desktop window: no touch
  await pc.routeWebSocket(/\/ws/, () => {});
  await pc.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await pc.goto(BASE); await pc.waitForTimeout(1500);
  s = await state(pc);
  check(!s.cover && !s.paused, "6. máy tính (cửa sổ thấp, chuột): không che", JSON.stringify(s));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
