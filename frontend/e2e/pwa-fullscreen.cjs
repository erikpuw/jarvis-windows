// E2E: JARVIS mở từ Màn hình chính iPhone như một ứng dụng toàn màn hình.
//  - Có manifest display standalone + meta web app, KHÔNG có apple-mobile-web-app-status-bar-style (như GeForce NOW):
//    đo trên iPhone 2026-10-12 thì đáy kín. black-translucent làm app Màn hình chính hụt một thanh trạng thái ở đáy (797/844).
//  - iPhone: apple-touch-icon 180px.
//  - Các lớp phủ toàn màn hình (xem ảnh) cao theo 100dvh: vừa khít vùng nhìn thấy cả khi thanh công cụ trình
//    duyệt hiện hay ẩn (100vh trên Safari cao hơn vùng nhìn thấy, đáy bị che).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/pwa-fullscreen.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(800);

  const head = await page.evaluate(() => ({
    manifest: document.querySelector('link[rel="manifest"]')?.getAttribute("href") || "",
    touchIcon: document.querySelector('link[rel="apple-touch-icon"]')?.getAttribute("href") || "",
    capable: document.querySelector('meta[name="apple-mobile-web-app-capable"]')?.getAttribute("content"),
    fullscreen: document.querySelector('meta[name="apple-touch-fullscreen"]')?.getAttribute("content"),
    status: document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]')?.getAttribute("content"),
    viewport: document.querySelector('meta[name="viewport"]')?.getAttribute("content") || "",
    theme: document.querySelector('meta[name="theme-color"]')?.getAttribute("content"),
  }));
  // standalone manifest without a status-bar-style meta: the home-screen app fills the screen (black-translucent left a gap at the bottom)
  const mf = head.manifest ? await page.evaluate(async (u) => { try { return (await (await fetch(u)).json()).display; } catch { return ""; } }, head.manifest) : "";
  check(mf === "standalone", "1. có manifest display standalone", `${head.manifest || "không có"} · ${mf}`);
  const touch = head.touchIcon ? await page.evaluate(async (u) => { const img = new Image(); img.src = u; try { await img.decode(); return img.naturalWidth; } catch { return 0; } }, head.touchIcon) : 0;
  check(touch === 180, "5. iPhone: apple-touch-icon 180px cho icon trên màn hình chính", `${head.touchIcon} · ${touch}px`);
  check(head.capable === "yes" && head.fullscreen === "yes" && head.status === undefined && /viewport-fit=cover/.test(head.viewport),
    "6. meta web app + apple-touch-fullscreen, không có status-bar-style (black-translucent làm hở đáy), viewport-fit=cover", JSON.stringify(head));
  const dvh = await page.evaluate(() => {
    const out = {};
    for (const sheet of document.styleSheets) { let rules; try { rules = sheet.cssRules; } catch { continue; } for (const r of rules) if (r.selectorText && ["#image-lightbox"].includes(r.selectorText)) out[r.selectorText] = r.style.height; }
    return out;
  });
  check(dvh["#image-lightbox"] === "100dvh", "7. lớp phủ toàn màn hình cao 100dvh (vừa khít vùng nhìn thấy, không bị thanh công cụ che đáy)", JSON.stringify(dvh));

  // the root's CSS as it was when the home-screen app filled the whole screen (10:57): the only root rule added since,
  // overscroll-behavior:none on html, came with the viewport stopping a status bar short of the bottom
  const root = await page.evaluate(() => getComputedStyle(document.documentElement).overscrollBehaviorY);
  check(root === "auto", "8. gốc trang (html) không đặt overscroll-behavior, như lúc app Màn hình chính còn kéo đủ màn hình", root);

  // html/body as tall as what is shown (100dvh), not the small viewport (100svh): in the iPhone home-screen app the small
  // viewport is the screen minus the status bar, WebKit keeps the layout viewport inside the document, and everything fixed to
  // the bottom (command bar, JARVIS label) stopped a status bar short of the screen's bottom
  const rootH = await page.evaluate(() => {
    for (const sheet of document.styleSheets) { let rules; try { rules = sheet.cssRules; } catch { continue; }
      for (const r of rules) if (r.selectorText && r.selectorText.replace(/\s+/g, " ") === "html, body") return r.style.height; }
    return "";
  });
  check(rootH === "100dvh", "10. html/body cao 100dvh (vùng đang hiển thị), không phải 100svh (app Màn hình chính iPhone: svh = màn hình trừ thanh trạng thái)", rootH);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
