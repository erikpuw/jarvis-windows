// E2E: thông báo lỗi hệ thống (showError: webcam/mic/upload/bản đồ lỗi) nay vào đảo thông báo (#error-text, xem notify-island.cjs cho phần đảo đầy đủ).
//  Lỗi hiện ở đảo, nằm trong màn hình; khi đã thu lại thành viên thuốc thì không đè lên hàng nút điều khiển. (Lúc bung popup đảo che cả hàng nút: đó là thiết kế.)
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/error-text.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function run(label, opts) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...opts, permissions: [] });
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.addInitScript(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError")); });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  const tag = `[${label}]`;
  await page.evaluate(() => document.getElementById("btn-webcam-toggle").click()); // mở webcam thất bại → showError
  await page.waitForTimeout(900);
  const read = () => page.evaluate(() => {
    const e = document.getElementById("error-text"), pill = e.querySelector(".island-pill").getBoundingClientRect(), cs = getComputedStyle(e);
    const over = [...document.querySelectorAll("#controls button")].filter((b) => {
      const s = getComputedStyle(b); if (s.display === "none" || s.visibility === "hidden" || parseFloat(s.opacity) < 0.05) return false;
      const q = b.getBoundingClientRect(); if (!q.width || !q.height) return false;
      return !(q.right <= pill.left || q.left >= pill.right || q.bottom <= pill.top || q.top >= pill.bottom);
    }).map((b) => b.id);
    return { state: e.dataset.state, kind: e.dataset.kind, text: e.querySelector(".island-error").textContent, vis: cs.visibility, l: pill.left, r: pill.right, vw: innerWidth, over };
  });
  let r = await read();
  check(r.kind === "error" && r.vis === "visible" && /Webcam/.test(r.text), `${tag} 0. lỗi hiện ở khu thông báo`, JSON.stringify({ kind: r.kind, text: r.text, state: r.state }));
  check(r.l >= 0 && r.r <= r.vw, `${tag} 1. nằm gọn trong màn hình`, `trái ${Math.round(r.l)} phải ${Math.round(r.r)} / ${r.vw}`);
  await page.mouse.move(2, 500);
  await page.waitForTimeout(5400); // popup 5 giây rồi thu lại thành viên thuốc
  r = await read();
  check(r.state === "pill" && r.over.length === 0, `${tag} 2. thu lại thành viên thuốc thì không đè lên nút điều khiển nào`, JSON.stringify({ state: r.state, over: r.over }));
  await browser.close();
}

(async () => {
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  await run("iPhone 390", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  await run("điện thoại nhỏ 320", { viewport: { width: 320, height: 640 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
