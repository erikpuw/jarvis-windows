// E2E: the chat ceiling follows the island when the safe area changes after load without a resize event
// (Capacitor iOS 2026-10-18: WKWebView reports env(safe-area-inset-top) late, the chat ran up over the top buttons).
// Run: PW=<playwright module> node frontend/e2e/chat-safe-area.cjs   (needs `npm run dev` on :5173)
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
  await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: 0, bottom: 0, left: 0, right: 0 } });
  await page.goto(BASE);
  await page.waitForTimeout(1200);

  // the native shell hands over the real inset late: no window resize
  await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: 47, bottom: 34, left: 0, right: 0 } });
  await page.waitForTimeout(600);
  const m = await page.evaluate(() => {
    const ch = document.getElementById("chat-history"), cs = getComputedStyle(ch);
    const pill = document.querySelector("#error-text .island-pill"), island = document.getElementById("error-text");
    const pillBottom = island.offsetTop + pill.offsetTop + pill.offsetHeight;
    const top = ch.getBoundingClientRect().bottom - parseFloat(cs.maxHeight) - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    return { islandTop: island.offsetTop, pillBottom, chatTop: Math.round(top) };
  });
  check(m.islandTop >= 55 && m.chatTop >= m.pillBottom, "1. vùng an toàn đến muộn: trần chat vẫn nằm dưới đảo", JSON.stringify(m));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
