// E2E: the Dashboard menu as an icon rail (user 2026-10-18): on a phone the drawer is the 60px rail (icons only), and in
// the rail (phone, or PC collapsed) the footer is the green dot over the version — no squeezed "JARVIS".
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/dashboard-rail.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, viewport) {
  const page = await (await browser.newContext({ viewport })).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  return page;
}
const footer = (page) => page.evaluate(() => {
  const nav = document.querySelector(".sd-nav").getBoundingClientRect();
  const name = document.querySelector(".sd-brand-name"), label = document.querySelector(".sd-version-label"), dot = document.querySelector(".sd-version-dot");
  const lr = label.getBoundingClientRect(), dr = dot.getBoundingClientRect();
  const shown = (e) => { const cs = getComputedStyle(e), r = e.getBoundingClientRect(); return cs.display !== "none" && cs.visibility !== "hidden" && +cs.opacity > 0.5 && r.width > 0; };
  return { navW: Math.round(nav.width), name: shown(name), label: shown(label), clipped: label.scrollWidth > label.clientWidth + 1,
    inside: lr.left >= nav.left && lr.right <= nav.right, stacked: dr.bottom <= lr.top + 1,
    navLabels: [...document.querySelectorAll(".sd-nav-label")].some(shown) };
});

(async () => {
  const browser = await chromium.launch();

  // 1. PC collapsed: dot over the version, no "JARVIS"
  const pc = await open(browser, { width: 1440, height: 900 });
  await pc.click("#settings-sidebar-toggle");
  await pc.waitForTimeout(500);
  const fp = await footer(pc);
  check(fp.navW <= 64 && !fp.name && fp.label && !fp.clipped && fp.inside && fp.stacked, "1. PC dải icon: chân menu = chấm xanh trên số phiên bản, không ép chữ JARVIS", JSON.stringify(fp));
  // 2. PC expanded again: name + version back on one line
  await pc.click("#settings-sidebar-toggle");
  await pc.waitForTimeout(500);
  const fe = await footer(pc);
  check(fe.name && fe.label && !fe.stacked, "2. PC mở rộng: JARVIS · phiên bản một dòng như cũ", JSON.stringify(fe));
  await pc.evaluate(() => { try { localStorage.clear(); } catch {} });
  await pc.context().close();

  // 3-4. phone: the drawer is the icon rail; an icon still opens its page
  const ph = await open(browser, { width: 390, height: 844 });
  await ph.click("#settings-menu-toggle");
  await ph.waitForTimeout(500);
  const fm = await footer(ph);
  check(fm.navW <= 64 && !fm.navLabels && !fm.name && fm.label && !fm.clipped && fm.inside && fm.stacked,
    "3. điện thoại: ngăn kéo là dải icon 60px, chân menu chấm xanh + phiên bản", JSON.stringify(fm));
  // 3b. the rail has its collapse button: it slides the menu out with the names, and back to icons (user 2026-10-18)
  const tog = await ph.isVisible("#settings-sidebar-toggle");
  if (tog) { await ph.click("#settings-sidebar-toggle"); await ph.waitForTimeout(500); }
  const wide = await footer(ph);
  if (tog) { await ph.click("#settings-sidebar-toggle"); await ph.waitForTimeout(500); }
  const back = await footer(ph);
  check(tog && wide.navW >= 180 && wide.navLabels && wide.name && back.navW <= 64 && !back.navLabels,
    "3b. điện thoại: nút thu/mở trượt menu ra đủ tên mục, bấm lại về dải icon", JSON.stringify({ tog, wide: wide.navW, labels: wide.navLabels, back: back.navW }));
  // 3c. the phone remembers its choice (user 2026-10-18): slid out, drawer closed and opened again, page reloaded — still slid
  // out; saved under its own key, the PC's choice untouched
  await ph.click("#settings-sidebar-toggle"); await ph.waitForTimeout(400);
  await ph.screenshot({ path: (process.env.SHOTS || require("os").tmpdir()) + "/rail-phone-wide.png" });
  await ph.click("#settings-menu-toggle"); await ph.waitForTimeout(400);
  await ph.click("#settings-menu-toggle"); await ph.waitForTimeout(500);
  const again = await footer(ph);
  await ph.reload(); await ph.waitForTimeout(1500);
  await ph.click("#settings-menu-toggle"); await ph.waitForTimeout(500);
  const reloaded = await footer(ph);
  const keys = await ph.evaluate(() => ({ phone: localStorage.getItem("jarvis.settings.sidebar_collapsed_phone"), pc: localStorage.getItem("jarvis.settings.sidebar_collapsed") }));
  check(again.navW >= 180 && reloaded.navW >= 180 && keys.phone === "0" && keys.pc === null,
    "3c. điện thoại: nhớ trạng thái thu/mở qua đóng–mở ngăn kéo và tải lại trang, lưu riêng không đụng PC", JSON.stringify({ again: again.navW, reloaded: reloaded.navW, keys }));
  await ph.click("#settings-sidebar-toggle"); await ph.waitForTimeout(400);
  await ph.screenshot({ path: (process.env.SHOTS || require("os").tmpdir()) + "/rail-phone.png" });
  await ph.click('.sd-nav-item[data-page="voice"]');
  await ph.waitForTimeout(600);
  const opened = await ph.evaluate(() => !document.getElementById("page-voice").hidden && document.getElementById("settings-container").classList.contains("open"));
  check(opened, "4. điện thoại: bấm icon mở đúng trang");
  await ph.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
