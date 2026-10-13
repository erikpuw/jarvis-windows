// E2E: ô nhập lệnh (#command-input). Lỗi cũ: chữ gợi ý (placeholder "Nhập nội dung, / hành động, @ gọi tên") dài hơn bề ngang ô trên điện thoại nên xuống dòng;
//  khi người dùng xoá hết chữ, ô nhập đo scrollHeight (tính cả placeholder xuống dòng) rồi cao lên 2 dòng, đẩy cả thanh lệnh nhảy lên.
//  Cỡ chữ lớn hơn (thang --ui-scale) còn làm một dòng chữ cao hơn mức 24px cố định nên thanh lệnh giật lên vài px ngay khi gõ ký tự đầu.
//  Đúng: chữ gợi ý luôn MỘT dòng, tự rút gọn "…" cho vừa bề ngang ô (đầy đủ khi đủ chỗ); ô trống thì luôn cao đúng một dòng; gõ một dòng không đổi chiều cao;
//  gõ nhiều dòng thì cao dần; xoá hết thì về đúng chiều cao ban đầu, thanh lệnh không nhảy.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/input-placeholder.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const mobile = (width, height, dpr) => ({ viewport: { width, height }, deviceScaleFactor: dpr, isMobile: true, hasTouch: true });
const DEVICES = [
  ["iPhone 14 · 390", mobile(390, 844, 3), true],
  ["iPhone SE · 375", mobile(375, 667, 2), true],
  ["Galaxy S23 · 360", mobile(360, 780, 3), true],
  ["Galaxy S21 Ultra · 412", mobile(412, 915, 2.625), true],
  ["Galaxy Fold gập · 280", mobile(280, 653, 3), true],
  ["máy tính 1280", { viewport: { width: 1280, height: 800 } }, false],
];
const FULL = "Nhập nội dung, / hành động, @ gọi tên";

async function run(label, opts, isMobile) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(500);
  const tag = `[${label}]`;
  const measure = () => page.evaluate(() => {
    const el = document.getElementById("command-input"), bar = document.getElementById("command-bar-inner").getBoundingClientRect(), cs = getComputedStyle(el);
    const c = document.createElement("canvas").getContext("2d"); c.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const w = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    return { h: el.getBoundingClientRect().height, barH: bar.height, barBottom: bar.bottom, ph: el.placeholder, phW: c.measureText(el.placeholder).width, w, oneLine: el.scrollHeight <= el.clientHeight + 1, line: parseFloat(cs.lineHeight) };
  });

  const m0 = await measure();
  check(m0.phW <= m0.w + 0.5 && m0.oneLine, `${tag} 1. chữ gợi ý vừa MỘT dòng trong ô`, `chữ ${m0.phW.toFixed(0)}px / ô ${m0.w.toFixed(0)}px · «${m0.ph}»`);
  check(isMobile ? (m0.ph === FULL || /…$/.test(m0.ph)) : m0.ph === FULL, `${tag} 2. ${isMobile ? "rút gọn bằng … khi không đủ chỗ (đủ chỗ thì để nguyên)" : "đủ chỗ nên hiện đầy đủ"}`, `«${m0.ph}»`);
  check(m0.h >= m0.line && m0.h <= m0.line + 6, `${tag} 3. ô trống cao đúng một dòng chữ`, `ô ${m0.h.toFixed(1)}px · dòng ${m0.line.toFixed(1)}px`);

  await page.fill("#command-input", "a");
  const m1 = await measure();
  check(Math.abs(m1.h - m0.h) <= 0.5 && Math.abs(m1.barBottom - m0.barBottom) <= 0.5, `${tag} 4. gõ ký tự đầu: ô và thanh lệnh không đổi chiều cao (không giật)`, `ô ${m0.h.toFixed(1)} → ${m1.h.toFixed(1)}px`);
  await page.fill("#command-input", "dòng một\ndòng hai\ndòng ba");
  const m3 = await measure();
  check(m3.h > m0.h + m0.line, `${tag} 5. gõ nhiều dòng thì ô cao dần`, `${m0.h.toFixed(1)} → ${m3.h.toFixed(1)}px`);
  await page.fill("#command-input", "");
  await page.waitForTimeout(150);
  const m4 = await measure();
  check(Math.abs(m4.h - m0.h) <= 0.5 && Math.abs(m4.barH - m0.barH) <= 0.5 && Math.abs(m4.barBottom - m0.barBottom) <= 0.5 && m4.oneLine,
    `${tag} 6. xoá hết chữ: ô và thanh lệnh về đúng như ban đầu (placeholder hiện lại không làm thanh lệnh nhảy)`, `ô ${m0.h.toFixed(1)} → ${m4.h.toFixed(1)}px · thanh ${m0.barH.toFixed(1)} → ${m4.barH.toFixed(1)}px`);
  await browser.close();
}

(async () => {
  for (const [label, opts, mob] of DEVICES) await run(label, opts, mob);
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
