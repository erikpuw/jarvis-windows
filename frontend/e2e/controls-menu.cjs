// E2E: 6 nút điều khiển (webcam, mic, tiếng TTS, thanh lệnh, orb, cài đặt) gom sau MỘT nút chính tròn ở góc trên phải.
//  Bấm nút chính → cả 6 nút TRÒN nhỏ (ôm sát icon, 30px) hiện CÙNG LÚC trên hai vòng cung quanh nút chính (3 trong + 3 ngoài), không tràn khỏi màn hình,
//  không chồng nhau; mỗi nút vẫn làm đúng việc cũ. Không chạm gì 4 giây thì tự thu lại (chạm nút nào cũng đếm lại 4 giây);
//  bấm nút chính hoặc Escape thì thu lại ngay. Đóng: chỉ còn một nút chính, các nút kia không bấm/không focus được.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/controls-menu.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { dismissWelcome } = require("./_welcome.cjs");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const IDS = ["btn-webcam-toggle", "btn-mute", "btn-tts-toggle", "btn-cmd-bar", "btn-orb-toggle", "btn-settings"];

async function run(label, opts) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.addInitScript(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError")); });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  // lớp chào khoá nút orb (disabled, mờ 0.35) tới tin đầu (spec 2026-10-16): gửi một tin để nút orb mở khoá trước khi đo menu
  await dismissWelcome(page);
  await page.waitForTimeout(1800);
  const tag = `[${label}]`;
  const state = () => page.evaluate((IDS) => {
    const root = document.getElementById("controls"), main = document.getElementById("btn-controls");
    const info = (b) => { const cs = getComputedStyle(b), r = b.getBoundingClientRect(); return { op: parseFloat(cs.opacity), pe: cs.pointerEvents, vis: cs.visibility, w: r.width, h: r.height, cx: r.left + r.width / 2, cy: r.top + r.height / 2, br: cs.borderRadius }; };
    return { open: root.classList.contains("open"), expanded: main && main.getAttribute("aria-expanded"), main: main ? info(main) : null, items: IDS.map((id) => info(document.getElementById(id))), vw: innerWidth, vh: innerHeight };
  }, IDS);

  let s = await state();
  check(!!s.main && s.main.w >= 34 && s.main.w <= 40 && s.main.br.startsWith("50%") && s.main.cx > s.vw - 60, `${tag} 1. có nút chính tròn ở góc trên phải`, JSON.stringify(s.main));
  check(s.items.every((i) => i.op === 0 && i.pe === "none" && i.vis === "hidden"), `${tag} 2. đóng: 6 nút kia ẩn hẳn (không bấm, không focus được)`, JSON.stringify(s.items.map((i) => [i.op, i.pe, i.vis])));

  // mở: ghi lại thời điểm từng nút bắt đầu hiện
  await page.evaluate((IDS) => {
    window.__t = {};
    const t0 = performance.now();
    const tick = () => {
      for (const id of IDS) if (window.__t[id] === undefined && parseFloat(getComputedStyle(document.getElementById(id)).opacity) > 0.3) window.__t[id] = performance.now() - t0;
      if (Object.keys(window.__t).length < IDS.length && performance.now() - t0 < 2500) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, IDS);
  await page.click("#btn-controls");
  await page.waitForTimeout(700);
  const times = await page.evaluate(() => Object.values(window.__t));
  s = await state();
  check(s.open && s.expanded === "true" && times.length === 6 && Math.max(...times) - Math.min(...times) <= 50, `${tag} 3. bấm nút chính: cả 6 nút hiện CÙNG LÚC (không hiện lần lượt)`, `lệch nhau ${times.length ? Math.round(Math.max(...times) - Math.min(...times)) : "?"}ms, ${times.length}/6 nút`);
  check(s.items.every((i) => i.op === 1 && i.pe === "auto" && i.vis === "visible"), `${tag} 4. mở xong: cả 6 nút rõ và bấm được`, JSON.stringify(s.items.map((i) => i.op)));
  check(s.items.every((i) => i.w >= 28 && i.w <= 32 && Math.abs(i.w - i.h) < 0.5 && i.br.startsWith("50%")), `${tag} 5. nút tròn nhỏ, ôm sát icon (28–32px, bo 50%)`, JSON.stringify(s.items.map((i) => [Math.round(i.w), i.br])));
  check(s.items.every((i) => i.cx - 15 >= 0 && i.cx + 15 <= s.vw && i.cy - 15 >= 0 && i.cy + 15 <= s.vh), `${tag} 6. không nút nào tràn khỏi màn hình`, JSON.stringify(s.items.map((i) => [Math.round(i.cx), Math.round(i.cy)])));
  let minD = 1e9;
  for (let a = 0; a < 6; a++) for (let b = a + 1; b < 6; b++) minD = Math.min(minD, Math.hypot(s.items[a].cx - s.items[b].cx, s.items[a].cy - s.items[b].cy));
  check(minD >= 31, `${tag} 7. các nút không chồng lên nhau`, `cách nhau gần nhất ${minD.toFixed(1)}px`);
  const dist = s.items.map((i) => Math.hypot(i.cx - s.main.cx, i.cy - s.main.cy));
  check(Math.max(...dist) <= 96 && Math.min(...dist) >= 43, `${tag} 8. xếp trên hai vòng cung ôm nút chính, cụm gọn (bán kính ${Math.round(Math.min(...dist))}–${Math.round(Math.max(...dist))}px)`, JSON.stringify(dist.map(Math.round)));
  check(s.items.every((i) => i.cx <= s.main.cx + 1 && i.cy >= s.main.cy - 1), `${tag} 9. các nút nằm về phía trái và phía dưới nút chính`, "");

  // mỗi nút vẫn làm việc cũ (bấm chuột thật)
  const before = await page.evaluate(() => document.getElementById("btn-mute").classList.contains("muted"));
  await page.click("#btn-mute");
  await page.waitForTimeout(250);
  const after = await page.evaluate(() => document.getElementById("btn-mute").classList.contains("muted"));
  check(before !== after, `${tag} 10. bấm nút mic vẫn bật/tắt mic như cũ`, `${before} → ${after}`);
  const tMute = Date.now();

  // tự thu lại: chạm nút làm đếm lại 4 giây
  await page.waitForTimeout(Math.max(0, 3200 - (Date.now() - tMute)));
  check((await state()).open, `${tag} 11. 3,2 giây sau lần chạm cuối: vẫn đang mở`, "");
  await page.click("#btn-mute");
  const tTouch = Date.now();
  await page.waitForTimeout(3000);
  check((await state()).open, `${tag} 12. chạm một nút thì đếm lại 4 giây (3 giây sau vẫn mở)`, `${Date.now() - tTouch}ms sau lần chạm`);
  await page.waitForTimeout(1900);
  s = await state();
  check(!s.open && s.expanded === "false" && s.items.every((i) => i.op === 0), `${tag} 13. không chạm gì 4 giây thì tự thu lại`, `${Date.now() - tTouch}ms sau lần chạm cuối`);

  // nút chính bật/tắt và Escape
  await page.click("#btn-controls");
  await page.waitForTimeout(450);
  check((await state()).open, `${tag} 14. bấm nút chính lại mở ra`, "");
  await page.click("#btn-controls");
  await page.waitForTimeout(450);
  check(!(await state()).open, `${tag} 15. bấm nút chính lần nữa thì thu lại ngay`, "");
  await page.click("#btn-controls");
  await page.waitForTimeout(450);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(450);
  check(!(await state()).open, `${tag} 16. Escape thu menu lại`, "");

  // nút thanh lệnh vẫn hoạt động khi bấm thật
  await page.click("#btn-controls");
  await page.waitForTimeout(450);
  const cv0 = await page.evaluate(() => document.getElementById("command-container").classList.contains("visible"));
  await page.click("#btn-cmd-bar");
  await page.waitForTimeout(300);
  const cv1 = await page.evaluate(() => document.getElementById("command-container").classList.contains("visible"));
  check(cv0 !== cv1, `${tag} 17. bấm nút thanh lệnh vẫn ẩn/hiện thanh lệnh`, `${cv0} → ${cv1}`);
  await browser.close();
}

(async () => {
  await run("iPhone 390", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  await run("điện thoại nhỏ 320", { viewport: { width: 320, height: 640 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await run("máy tính 1280", { viewport: { width: 1280, height: 800 } });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
