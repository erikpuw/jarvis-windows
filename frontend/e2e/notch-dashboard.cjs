// E2E: opening the Dashboard on a phone keeps iOS Safari's own fade under the status bar (user 2026-10-18: tapping the
// Dashboard button lost the gradient). Safari drops the fade and tints the bar the moment a painted layer touches the top
// screen edge: the drawer's dimming scrim (inset 0, black 55%) did. The scrim only covers the band the drawer uses: from
// under the Dynamic Island down to the command bar's bottom edge, touching neither screen edge. Also: the home button keeps
// the control buttons' blue when tapped (it turned white: the generic icon-button hover stuck after the tap).
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/notch-dashboard.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: 47, bottom: 34, left: 0, right: 0 } });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.click("#settings-menu-toggle"); // the sessions drawer (sessions.ts) ...
  await page.waitForTimeout(300);
  await page.click("#sessions-dash"); // ... ⚙ Bảng điều khiển opens the Dashboard menu drawer
  await page.waitForTimeout(500);

  // nothing painted (a background with colour) under the status bar strip while the drawer is open
  const m = await page.evaluate(() => {
    const scrim = document.getElementById("settings-scrim"), r = scrim.getBoundingClientRect();
    const painted = document.elementsFromPoint(innerWidth / 2, 2).filter((e) => {
      if (e === document.body || e === document.documentElement || e.tagName === "CANVAS") return false;
      const bg = getComputedStyle(e).backgroundColor;
      return bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent";
    }).map((e) => e.id || e.className);
    const nav = document.getElementById("settings-nav").getBoundingClientRect();
    return { scrimShown: getComputedStyle(scrim).display !== "none" && !scrim.hidden, scrimTop: Math.round(r.top), scrimBottom: Math.round(r.bottom),
      navTop: Math.round(nav.top), navBottom: Math.round(nav.bottom), vh: innerHeight, painted };
  });
  check(m.scrimShown && Math.abs(m.scrimTop - m.navTop) <= 1 && Math.abs(m.scrimBottom - m.navBottom) <= 1 && m.scrimBottom < m.vh && !m.painted.length,
    "1. mở ngăn kéo: lớp tối chỉ phủ từ dưới Dynamic Island tới mép dưới thanh lệnh, không chạm mép màn hình", JSON.stringify(m));
  // 2. the home button after the tap keeps the controls' blue
  const colors = await page.evaluate(() => ({ home: getComputedStyle(document.getElementById("settings-menu-toggle")).color, ctl: getComputedStyle(document.getElementById("btn-controls")).color }));
  check(/14, 165, 233/.test(colors.home) && /14, 165, 233/.test(colors.ctl), "2. nút Bảng điều khiển sau khi bấm vẫn xanh như nút điều khiển", JSON.stringify(colors));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
