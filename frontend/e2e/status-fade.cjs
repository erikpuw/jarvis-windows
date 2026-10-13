// E2E: hàng trạng thái (#status-row: quả cầu + chữ) đổi vị trí khi thanh lệnh ẩn/hiện.
//  Lỗi cũ: gỡ `.visible` thì hàng nhảy tức thời từ trái ra giữa (justify-content không có chuyển động), không có animation nào.
//  Đúng (mẫu B2 người dùng chọn): MỜ + PHÓNG NHẸ, cả hai chiều như nhau, 0,25 giây: hàng mờ đi và co về 85% ở chỗ cũ,
//  rồi mờ vào và phóng lên 100% ở chỗ mới. Không có lúc nào thấy hàng trượt/nhảy khi còn rõ; quả cầu và chữ giữ hiệu ứng riêng của chúng.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/status-fade.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function setup(opts) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  return { browser, page };
}

// bật/tắt .visible rồi ghi từng khung hình: độ mờ, tỉ lệ, tâm của quả cầu
async function film(page, show) {
  await page.evaluate(() => {
    window.__f = [];
    const row = document.getElementById("status-row"), orb = document.getElementById("status-orb");
    window.__t0 = performance.now();
    const tick = () => {
      const cs = getComputedStyle(row), m = new DOMMatrixReadOnly(cs.transform === "none" ? undefined : cs.transform), r = orb.getBoundingClientRect();
      window.__f.push({ t: performance.now() - window.__t0, op: parseFloat(cs.opacity), sc: Math.hypot(m.a, m.b), cx: r.left + r.width / 2, cs: cs.transform });
      window.__raf = requestAnimationFrame(tick);
    };
    window.__raf = requestAnimationFrame(tick);
  });
  await page.evaluate((s) => document.getElementById("command-container").classList.toggle("visible", s), show);
  await page.waitForTimeout(700);
  await page.evaluate(() => cancelAnimationFrame(window.__raf));
  return page.evaluate(() => window.__f);
}

async function run(label, opts) {
  const { browser, page } = await setup(opts);
  const tag = `[${label}]`;
  await page.evaluate(() => document.getElementById("command-container").classList.add("visible"));
  await page.waitForTimeout(800);

  for (const [dir, show] of [["ẩn thanh lệnh (trái → giữa)", false], ["hiện lại thanh lệnh (giữa → trái)", true]]) {
    const f = await film(page, show);
    const from = f[0].cx, to = f.at(-1).cx;
    const t = `${tag} ${dir}`;
    check(Math.abs(to - from) > 40, `${t}: 1. quả cầu thật sự đổi chỗ`, `${from.toFixed(0)} → ${to.toFixed(0)}`);
    // thời gian chạy: từ lúc bắt đầu tới khung cuối còn mờ/co
    const moving = f.filter((x) => x.op < 0.995 || Math.abs(x.sc - 1) > 0.002);
    const dur = moving.length ? moving.at(-1).t : 0;
    check(dur >= 190 && dur <= 330, `${t}: 2. chạy khoảng 0,25 giây (không tức thời, không chậm)`, `${dur.toFixed(0)}ms, ${moving.length} khung`);
    check(Math.min(...f.map((x) => x.op)) <= 0.2,`${t}: 3. có lúc mờ hẳn ở giữa (mờ đi rồi mờ vào)`, `thấp nhất ${Math.min(...f.map((x) => x.op)).toFixed(2)}`);
    const smin = Math.min(...f.map((x) => x.sc)), smax = Math.max(...f.map((x) => x.sc));
    check(smin >= 0.8 && smin <= 0.92 && smax <= 1.005, `${t}: 4. phóng nhẹ: co về khoảng 85% rồi phóng lên 100%, không vượt quá`, `nhỏ nhất ${smin.toFixed(2)}, lớn nhất ${smax.toFixed(2)}`);
    // vị trí chỉ được đổi khi hàng đã mờ gần hết
    let jumpVisible = 0;
    for (let i = 1; i < f.length; i++) if (Math.abs(f[i].cx - f[i - 1].cx) > 3 && Math.max(f[i].op, f[i - 1].op) > 0.15) jumpVisible = Math.max(jumpVisible, Math.abs(f[i].cx - f[i - 1].cx));
    check(jumpVisible === 0, `${t}: 5. không nhảy/trượt vị trí khi còn nhìn thấy rõ`, `nhảy lúc còn rõ ${jumpVisible.toFixed(0)}px`);
    const last = f.at(-1);
    check(last.op === 1 && last.cs === "none", `${t}: 6. kết thúc sạch: rõ 100%, không còn transform treo lại`, `op ${last.op} transform ${last.cs}`);
  }
  // vị trí cuối đúng
  const ends = await page.evaluate(() => { const c = document.getElementById("command-container").getBoundingClientRect(), o = document.getElementById("status-orb").getBoundingClientRect(), tx = document.getElementById("status-text").getBoundingClientRect(); return { cc: c.left + c.width / 2, orbL: o.left - c.left, contentC: (o.left + tx.right) / 2 }; });
  check(ends.orbL < 20, `${tag} 7. hiện thanh lệnh: hàng nằm lại sát trái`, `cách mép trái ${ends.orbL.toFixed(0)}px`);
  await film(page, false);
  const hid = await page.evaluate(() => { const c = document.getElementById("command-container").getBoundingClientRect(), o = document.getElementById("status-orb").getBoundingClientRect(), tx = document.getElementById("status-text").getBoundingClientRect(); return { cc: c.left + c.width / 2, contentC: (o.left + Math.max(o.right, tx.right)) / 2 }; });
  check(Math.abs(hid.contentC - hid.cc) < 8, `${tag} 8. ẩn thanh lệnh: hàng nằm giữa`, `lệch ${(hid.contentC - hid.cc).toFixed(1)}px`);
  await browser.close();
}

async function reduced() {
  const { browser, page } = await setup({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
  await page.evaluate(() => document.getElementById("command-container").classList.add("visible"));
  await page.waitForTimeout(800);
  const before = await page.evaluate(() => { const r = document.getElementById("status-orb").getBoundingClientRect(); return r.left + r.width / 2; });
  const f = await film(page, false);
  check(f.every((x) => x.op === 1 && x.cs === "none") && Math.abs(f.at(-1).cx - before) > 40, "[giảm chuyển động] 9. đổi chỗ ngay, không mờ/phóng", `op thấp nhất ${Math.min(...f.map((x) => x.op)).toFixed(2)}`);
  await browser.close();
}

(async () => {
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  await run("điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await reduced();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
