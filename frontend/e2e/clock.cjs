// E2E cho đồng hồ lật kiểu HTC Sense trên màn hình chính (src/clock.ts).
// Mọi /api và /ws đều bị mock — không chạm JARVIS thật. Giờ bị đóng băng bằng page.clock.
// Chạy: PW=<module playwright> node frontend/e2e/clock.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

async function open(browser, viewport) {
  const page = await browser.newPage({ viewport });
  await page.clock.install({ time: new Date(2026, 8, 28, 10, 59, 30) });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  return page;
}
const shown = (page) => page.$$eval("#jarvis-clock .fc", (cards) => { const d = cards.map((c) => c.dataset.value); return d.slice(0, 2).join("") + ":" + d.slice(2).join(""); });

(async () => {
  const browser = await chromium.launch();
  const page = await open(browser, { width: 1280, height: 800 });
  const el = await page.waitForSelector("#jarvis-clock", { timeout: 5000 }).catch(() => null);
  check(!!el, "1. có #jarvis-clock");
  if (!el) { await browser.close(); process.exit(1); }

  check((await shown(page)) === "10:59", "2a. hiện HH:MM hiện tại", await shown(page));
  const cards = await page.$$eval("#jarvis-clock .fc", (cs) => cs.map((c) => [".fc-top", ".fc-bottom"].every((s) => c.querySelector(s))));
  check(cards.length === 4 && cards.every(Boolean), "2b. 4 thẻ, mỗi chữ số một thẻ, có nửa trên/dưới");
  const order = await page.$$eval("#jarvis-clock > *", (els) => els.map((e) => e.classList.contains("fc-colon") ? ":" : "d").join(""));
  check(order === "dd:dd", "2c. có dấu : giữa giờ và phút", order);
  const colon = await page.$eval("#jarvis-clock .fc-colon", (e) => [...e.querySelectorAll("i")].map((i) => { const cs = getComputedStyle(i); return [cs.animationName, cs.animationDuration, cs.animationDelay].join(" "); }));
  check(colon.length === 2 && colon[0] === "fc-radar 2s 0s" && colon[1] === "fc-radar 2s 1s", "2d. dấu : là 2 chấm, sóng radar luân phiên", JSON.stringify(colon));

  await page.clock.pauseAt(new Date(2026, 8, 28, 10, 59, 55)); // real load time must not skip the flip
  let flapping = false;
  for (let i = 0; i < 80 && !flapping; i++) { await page.clock.runFor(100); flapping = !!(await page.$("#jarvis-clock .fc-flap-top")); }
  check(flapping, "3a. đổi phút → nửa trên số cũ gập xuống");
  const flippingCards = await page.$$eval("#jarvis-clock .fc", (cs) => cs.map((c) => !!c.querySelector(".fc-flap-top")).join(","));
  check(flippingCards === "false,true,true,true", "3a2. chỉ lật chữ số thay đổi (10:59→11:00: giữ số 1 đầu)", flippingCards);
  await page.clock.runFor(1500);
  check((await shown(page)) === "11:00", "3b. lật xong hiện giờ mới", await shown(page));
  check(!(await page.$("#jarvis-clock .fc-flap-top, #jarvis-clock .fc-flap-bottom")), "3c. dọn tấm lật sau khi xong");

  const g = await page.evaluate(() => {
    const c = document.getElementById("jarvis-clock"), cs = getComputedStyle(c), r = c.getBoundingClientRect();
    const ctl = document.getElementById("controls").getBoundingClientRect();
    const zOf = (id) => +getComputedStyle(document.getElementById(id)).zIndex;
    return { cx: r.left + r.width / 2, top: r.top, ctlBottom: ctl.bottom, z: +cs.zIndex, zOrb: zOf("orb-canvas"), zCtl: zOf("controls"), pe: cs.pointerEvents, font: getComputedStyle(c.querySelector(".fc")).fontFamily, weight: getComputedStyle(c.querySelector(".fc")).fontWeight, half: (() => { const h = getComputedStyle(c.querySelector(".fc-top")); return [h.backgroundColor, h.borderTopWidth, h.borderLeftWidth]; })(), split: getComputedStyle(c.querySelector(".fc"), "::after").height };
  });
  check(Math.abs(g.cx - 640) <= 2, "4a. giữa màn hình theo chiều ngang", String(g.cx));
  check(g.top >= g.ctlBottom && g.top <= g.ctlBottom + 40, "4b. ngay dưới hàng nút", JSON.stringify(g));
  check(g.z > g.zOrb && g.z < g.zCtl && g.pe === "none", "4c. chỉ trên orb (dưới hàng nút), không chặn click", `${g.zOrb} < ${g.z} < ${g.zCtl} / ${g.pe}`);
  check(g.font.includes("Oswald") && g.weight === "300", "5a. font Oswald Light", `${g.font} ${g.weight}`);
  check(g.half[0] === "rgba(0, 0, 0, 0)" && g.half[1] === "0px" && g.half[2] === "0px", "5c. không khung (không nền, không viền)", g.half.join(" "));
  check(parseFloat(g.split) >= 1, "5d. còn đường cắt ngang", g.split);
  await page.evaluate(() => document.fonts.ready);
  check(await page.evaluate(() => document.fonts.check('300 40px Oswald')), "5b. font đã nhúng, tải được offline");
  await page.close();

  const rm = await browser.newPage({ reducedMotion: "reduce" });
  await rm.routeWebSocket(/\/ws/, () => {});
  await rm.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await rm.goto(BASE);
  await rm.waitForSelector("#jarvis-clock .fc-colon");
  check((await rm.$$eval("#jarvis-clock .fc-colon i", (els) => els.map((e) => getComputedStyle(e).animationName).join())) === "none,none", "2e. giảm chuyển động → dấu : đứng yên");
  await rm.close();

  const m = await open(browser, { width: 375, height: 812 });
  await m.waitForSelector("#jarvis-clock");
  const mg = await m.evaluate(() => {
    const r = document.getElementById("jarvis-clock").getBoundingClientRect();
    return { l: r.left, r: r.right, top: r.top, ctlBottom: document.getElementById("controls").getBoundingClientRect().bottom };
  });
  check(mg.l >= 0 && mg.r <= 375 && mg.top >= mg.ctlBottom, "6. mobile: không tràn, dưới hàng nút", JSON.stringify(mg));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
