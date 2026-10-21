// E2E: on a touch phone (Capacitor app, Safari) opening the app or showing the command bar does NOT focus the input, so the
// keyboard only comes up when the user taps the input (user 2026-10-18: the PC habit of putting the caret in the bar popped
// the phone keyboard at launch). A PC still gets the caret in the bar.
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/no-autofocus-touch.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, ctx) {
  const page = await (await browser.newContext(ctx)).newPage();
  // count focus() calls on the input: headless Chrome drops a scripted focus on its own, a phone keeps it (keyboard up)
  await page.addInitScript(() => { window.__inputFocus = 0; const o = HTMLElement.prototype.focus;
    HTMLElement.prototype.focus = function (...a) { if (this.id === "command-input") window.__inputFocus++; return o.apply(this, a); }; });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  return page;
}
const focused = (page) => page.evaluate(() => document.activeElement?.id || document.activeElement?.tagName);
const focusCalls = (page) => page.evaluate(() => window.__inputFocus);
const press = (page, id) => page.evaluate((id) => document.getElementById(id).click(), id);

(async () => {
  const browser = await chromium.launch();

  const ph = await open(browser, { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  check((await focusCalls(ph)) === 0, "1. điện thoại: mở app, không gọi focus ô nhập (không bật bàn phím)", String(await focusCalls(ph)));
  // hide and show the bar again from the controls menu
  await press(ph, "btn-controls"); await ph.waitForTimeout(400);
  await press(ph, "btn-cmd-bar"); await ph.waitForTimeout(300);
  await press(ph, "btn-cmd-bar"); await ph.waitForTimeout(300);
  check((await focusCalls(ph)) === 0, "2. điện thoại: hiện lại thanh lệnh cũng không tự focus", String(await focusCalls(ph)));
  await ph.tap("#command-input"); await ph.waitForTimeout(200);
  check((await focused(ph)) === "command-input", "3. điện thoại: chạm vào ô nhập thì mới focus", await focused(ph));
  await ph.context().close();

  const pc = await open(browser, { viewport: { width: 1440, height: 900 } });
  check((await focusCalls(pc)) >= 1, "4. PC: vẫn đặt sẵn dấu nháy vào ô nhập", String(await focusCalls(pc)));
  await pc.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
