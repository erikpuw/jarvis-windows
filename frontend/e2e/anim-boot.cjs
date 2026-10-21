// E2E: hiệu ứng chỉ bắt đầu khi trang đã nạp xong (sự kiện load + font sẵn sàng), không nhảy ngay lúc script vừa chạy.
//  Trước khi load: không vòng vẽ trang trí nào (bot, quả cầu trạng thái, shader nút gửi). Orb thì dựng ngay (từ 2026-10-15: chờ
//  load làm orb trống lâu trên iPhone), nên vòng của three không tính,
//  animation CSS đứng yên. Sau load: tất cả chạy. Một ảnh chậm 2 giây giữ sự kiện load lại. WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/anim-boot.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await ctx.addInitScript(() => {
    window.__raf = 0;
    const raf = window.requestAnimationFrame.bind(window);
    // morphicons draws each button icon once as it appears (~1 s, then stops): that is the icon itself, not a decoration
    window.requestAnimationFrame = (cb) => { if (!/morphicons|three/.test(new Error().stack)) window.__raf++; return raf(cb); }; // the orb (three) starts at once
    // an image that answers after 2 s keeps window "load" back
    document.addEventListener("DOMContentLoaded", () => { const i = new Image(); i.src = "/__slow.png"; i.style.display = "none"; document.body.appendChild(i); });
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/__slow.png", async (r) => { await new Promise((ok) => setTimeout(ok, 2500)); r.fulfill({ status: 204 }); });
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900); // the app script has run, the slow image still holds "load"

  const state = () => page.evaluate(async () => {
    const a = window.__raf; await new Promise((r) => setTimeout(r, 500));
    const c = document.getElementById("orb-canvas");
    return {
      ready: document.readyState,
      rafPerSec: (window.__raf - a) * 2,
      orb: c?.dataset.backend ?? "not built",
      css: document.getAnimations().filter((x) => x.playState === "running").map((x) => x.animationName).filter(Boolean),
    };
  });
  const before = await state();
  check(before.ready !== "complete", "0. đang nạp: sự kiện load chưa tới (ảnh chậm giữ lại)", before.ready);
  check(before.rafPerSec <= 4, "1. đang nạp: không vòng vẽ trang trí nào chạy", JSON.stringify(before));
  check(before.orb !== "not built", "1b. orb dựng ngay, không chờ load (chờ load làm orb trống lâu trên iPhone)", before.orb);
  check(before.css.length === 0, "2. đang nạp: animation CSS đứng yên", before.css.join(","));

  await page.waitForLoadState("load");
  await page.waitForTimeout(1500);
  const after = await state();
  check(after.rafPerSec > 100 && after.orb !== "not built" && after.css.length > 0, "3. nạp xong: orb, các vòng vẽ và animation CSS chạy", JSON.stringify(after));
  check(errors.length === 0, "4. không có lỗi trang", errors.slice(0, 2).join(" | "));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
