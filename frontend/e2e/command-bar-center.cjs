// E2E: the command bar's + button, the typed text and the send button share one centre line (user 2026-10-24: the + and the
// text sat low). The bar aligns its items to the bottom (so with a long, multi-line question the + and send stay at the
// bottom); each item is as tall as the send button's row and centres its own content. Phone and PC.
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/command-bar-center.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const centres = (page) => page.evaluate(() => {
  const mid = (e) => { const r = e.getBoundingClientRect(); return r.top + r.height / 2; };
  const bar = document.getElementById("command-bar-inner"), input = document.getElementById("command-input");
  const cs = getComputedStyle(input), r = input.getBoundingClientRect();
  // the first text line: the top padding, then one line-height
  const line = r.top + parseFloat(cs.paddingTop) + parseFloat(cs.lineHeight) / 2;
  const lastLine = r.bottom - parseFloat(cs.paddingBottom) - parseFloat(cs.lineHeight) / 2;
  return { bar: +mid(bar).toFixed(1), plus: +mid(document.querySelector("#btn-upload svg")).toFixed(1), line: +line.toFixed(1),
    lastLine: +lastLine.toFixed(1), send: +mid(document.getElementById("cmd-send-wrap")).toFixed(1) };
});

(async () => {
  const browser = await chromium.launch();
  for (const [vp, tag] of [[{ width: 390, height: 844 }, "điện thoại"], [{ width: 1440, height: 900 }, "PC"]]) {
    const page = await browser.newPage({ viewport: vp });
    await page.routeWebSocket(/\/ws/, () => {});
    // signed in (auth-gate.ts): a stored token that /api/auth/me accepts
    await page.addInitScript(() => { try { localStorage.setItem("jarvis_token", "test"); } catch {} });
    await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true }, user: { id: "u1", username: "tester", role: "admin" } } }));
    await page.goto(BASE);
    await page.waitForTimeout(1500);
    const one = await centres(page);
    const off = (a, b) => Math.abs(a - b) <= 1;
    check(off(one.plus, one.send) && off(one.line, one.send) && off(one.send, one.bar), `1. ${tag}: một dòng — dấu +, chữ, nút gửi cùng đường giữa khung`, JSON.stringify(one));
    await page.evaluate(() => { const i = document.getElementById("command-input"); i.value = "câu hỏi rất dài ".repeat(30); i.dispatchEvent(new Event("input", { bubbles: true })); });
    await page.waitForTimeout(300);
    const many = await centres(page); // the bar grows upward: the bottom row (+, last line, send) stays put
    check(off(many.plus, many.send) && off(many.lastLine, many.send) && many.bar < one.bar - 10, `2. ${tag}: nhiều dòng — dấu + và nút gửi nằm cùng dòng cuối`, JSON.stringify(many));
    await page.close();
  }
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
