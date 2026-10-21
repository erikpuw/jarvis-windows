// E2E: quầng sáng của nút gửi (src/metal-halo.ts) phải ÔM ĐÚNG vòng kim loại (metal-ring) trên MỌI màn hình: điện thoại iOS/Android nhiều cỡ
//  (mật độ điểm ảnh 2, 2,625, 3) và máy tính (1, 1,25). Lỗi cũ: tâm/bán kính quầng sáng tính từ kích thước đo lúc khởi động (nút còn đang có
//  hiệu ứng vào, đo theo getBoundingClientRect nên bị biến dạng) nên trên một số máy quầng sáng lệch khỏi vòng, không ôm trọn.
//  Đo: tâm canvas quầng sáng trùng tâm vòng; chỗ sáng nhất nằm đúng trên mép ngoài vòng (cách tâm ≈ bán kính vòng) và đúng hướng đã chọn.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/metal-glow-fit.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"];
const mobile = (width, height, dpr) => ({ viewport: { width, height }, deviceScaleFactor: dpr, isMobile: true, hasTouch: true });
const DEVICES = [
  ["iPhone 14 · 390×844 · 3x", mobile(390, 844, 3)],
  ["iPhone SE · 375×667 · 2x", mobile(375, 667, 2)],
  ["Galaxy S23 · 360×780 · 3x", mobile(360, 780, 3)],
  ["Galaxy S21 Ultra · 412×915 · 2,625x", mobile(412, 915, 2.625)],
  ["máy tính 1280×800 · 1x", { viewport: { width: 1280, height: 800 } }],
  ["máy tính 1536×864 · 1,25x", { viewport: { width: 1536, height: 864 }, deviceScaleFactor: 1.25 }],
];

const measure = (page) => page.evaluate(() => {
    const wrap = document.getElementById("cmd-send-wrap"), ring = wrap.querySelector(".metal-ring"), env = wrap.querySelector(".metal-glow"), cv = env && env.querySelector("canvas");
    if (!ring || !cv) return null;
    const rr = ring.getBoundingClientRect(), cr = cv.getBoundingClientRect(), g = cv.getContext("2d", { willReadFrequently: true });
    const d = g.getImageData(0, 0, cv.width, cv.height).data;
    let max = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > max) max = d[i];
    let sx = 0, sy = 0, n = 0;
    for (let y = 0; y < cv.height; y++) for (let x = 0; x < cv.width; x++) if (d[(y * cv.width + x) * 4 + 3] >= max * 0.9) { sx += x; sy += y; n++; }
    const kx = cr.width / cv.width, ky = cr.height / cv.height;
    const px = cr.left + (sx / n) * kx, py = cr.top + (sy / n) * ky, rcx = rr.left + rr.width / 2, rcy = rr.top + rr.height / 2;
    return {
      ringW: rr.width, ringH: rr.height, off: Math.hypot(cr.left + cr.width / 2 - rcx, cr.top + cr.height / 2 - rcy),
      dist: Math.hypot(px - rcx, py - rcy), ang: ((Math.atan2(py - rcy, px - rcx) * 180) / Math.PI + 360) % 360, want: parseFloat(env.dataset.angle), n, wrapW: wrap.offsetWidth,
    };
  });

function verify(tag, r) {
  if (!r) { check(false, `${tag} có vòng kim loại và quầng sáng`, "thiếu"); return; }
  const R = r.ringW / 2, dAng = Math.abs(((r.ang - r.want + 540) % 360) - 180);
  check(r.off <= 0.8, `${tag} tâm canvas quầng sáng trùng tâm vòng kim loại`, `lệch ${r.off.toFixed(2)}px`);
  check(Math.abs(r.dist - (R - 1.5)) <= 2.2, `${tag} chỗ sáng nhất nằm đúng trên mép ngoài vòng (bán kính ${R.toFixed(1)}px)`, `cách tâm ${r.dist.toFixed(1)}px, cần ≈ ${(R - 1.5).toFixed(1)}px`);
  check(dAng <= 10, `${tag} đúng hướng đã chọn`, `${Math.round(r.ang)}° so với ${Math.round(r.want)}°`);
}

// Đổi cỡ sau khi đã chạy: xoay màn hình / gập mở / thu phóng trình duyệt làm nút gửi đổi cỡ (30px ↔ 34px qua mốc 768px) và đổi mật độ điểm ảnh.
async function runResize(label, opts, widths) {
  const browser = await chromium.launch({ args: ARGS });
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(2200);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  for (const w of widths) {
    await page.setViewportSize({ width: w, height: opts.viewport.height });
    await page.waitForTimeout(1200);
    verify(`[${label}] sau khi đổi bề ngang thành ${w}px:`, await measure(page));
  }
  await browser.close();
}

async function runDpr(label) {
  const browser = await chromium.launch({ args: ARGS });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 })).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(2200);
  const density = () => page.evaluate(() => { const c = document.querySelector("#cmd-send-wrap .metal-glow canvas"); return c.width / c.getBoundingClientRect().width; });
  const d1 = await density();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 800, deviceScaleFactor: 3, mobile: false });
  await page.waitForTimeout(1200);
  const d3 = await density();
  check(d3 >= 2.9 && d1 <= 1.1, `[${label}] đổi mật độ điểm ảnh 1x → 3x (kéo cửa sổ sang màn hình khác, thu phóng): canvas quầng sáng vẽ lại sắc nét theo`, `${d1.toFixed(2)} → ${d3.toFixed(2)} điểm ảnh mỗi px`);
  verify(`[${label}] sau khi đổi mật độ:`, await measure(page));
  await browser.close();
}

async function run(label, opts) {
  const browser = await chromium.launch({ args: ARGS });
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(2200);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(900);
  const r = await measure(page);
  const tag = `[${label}]`;
  if (!r) { check(false, `${tag} 0. có vòng kim loại và quầng sáng`, "thiếu"); await browser.close(); return; }
  const R = r.ringW / 2, dAng = Math.abs(((r.ang - r.want + 540) % 360) - 180);
  check(Math.abs(r.ringW - r.ringH) < 0.5 && Math.abs(r.ringW - r.wrapW) < 0.5, `${tag} 1. vòng kim loại tròn, đúng cỡ nút`, `${r.ringW.toFixed(1)}×${r.ringH.toFixed(1)}px · nút ${r.wrapW}px`);
  check(r.off <= 0.8, `${tag} 2. tâm canvas quầng sáng trùng tâm vòng kim loại`, `lệch ${r.off.toFixed(2)}px`);
  check(Math.abs(r.dist - (R - 1.5)) <= 2.2, `${tag} 3. chỗ sáng nhất nằm đúng trên mép ngoài vòng (bán kính ${R.toFixed(1)}px)`, `cách tâm ${r.dist.toFixed(1)}px, cần ≈ ${(R - 1.5).toFixed(1)}px`);
  check(dAng <= 10, `${tag} 4. đúng hướng đã chọn`, `${Math.round(r.ang)}° so với ${Math.round(r.want)}°`);
  await browser.close();
}

(async () => {
  for (const [label, opts] of DEVICES) await run(label, opts);
  await runResize("máy tính → hẹp → rộng", { viewport: { width: 1280, height: 800 } }, [700, 1280]);
  await runResize("điện thoại → rộng → hẹp", mobile(390, 844, 3), [820, 390]);
  await runDpr("máy tính");
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
