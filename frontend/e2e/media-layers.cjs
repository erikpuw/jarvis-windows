// E2E: thứ tự lớp khi đang xem video (người dùng chốt 2026-10-23): chat (30) → video → điều khiển → island (80) → reader (85)
//  → thanh phiên (95) → Bảng điều khiển (100). Video chỉ nằm trên khung chat: trên điện thoại khung 16:9 ở top 56px, menu điều khiển
//  thả xuống đè lên video thì nút của menu vẫn phải bấm được (trước đây --z-media 70 > --z-controls 50 nên video che mất).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/media-layers.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { dismissWelcome } = require("./_welcome.cjs");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const IDS = ["btn-webcam-toggle", "btn-mute", "btn-tts-toggle", "btn-cmd-bar", "btn-orb-toggle"];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  await page.addInitScript(() => localStorage.setItem("jarvis_token", "tok-media-layers")); // đã đăng nhập (auth gate)
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true }, user: { id: "admin", username: "admin", role: "admin" } } }));
  await page.route("**/blank-video.html**", (r) => r.fulfill({ contentType: "text/html", body: "<html><body style='background:#000'></body></html>" }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await dismissWelcome(page);
  await page.waitForTimeout(800);

  sock.send(JSON.stringify({ type: "media_open", query: "thử", title: "Video thử", embed_url: "http://localhost:5173/blank-video.html?x=1" }));
  await page.waitForTimeout(600);
  check(await page.evaluate(() => !document.getElementById("media-player").classList.contains("hidden")), "1. trình phát video đã mở");

  await page.click("#btn-controls");
  await page.waitForTimeout(500);
  // mỗi nút của menu có phần chồng lên video: phần tử ở tâm vùng chồng đó phải là chính nút (hoặc con của nó), không phải video
  const r = await page.evaluate((IDS) => {
    const v = document.getElementById("media-player").getBoundingClientRect();
    const out = [];
    for (const id of IDS) {
      const b = document.getElementById(id);
      const rb = b.getBoundingClientRect();
      const l = Math.max(rb.left, v.left), t = Math.max(rb.top, v.top), rr = Math.min(rb.right, v.right), bb = Math.min(rb.bottom, v.bottom);
      if (rr <= l || bb <= t) continue;
      const el = document.elementFromPoint((l + rr) / 2, (t + bb) / 2);
      out.push({ id, onTop: !!el && b.contains(el) });
    }
    return out;
  }, IDS);
  check(r.length > 0, "2. menu điều khiển mở ra có nút đè lên vùng video", JSON.stringify(r));
  check(r.length > 0 && r.every((x) => x.onTop), "3. nút điều khiển nằm TRÊN video (bấm được)", JSON.stringify(r));

  // video vẫn nằm trên khung chat, dưới island
  const z = await page.evaluate(() => {
    const n = (sel) => parseInt(getComputedStyle(document.querySelector(sel)).zIndex, 10);
    return { chat: n("#command-container"), media: n(".media-player"), controls: n("#controls"), island: n("#error-text") };
  });
  check(z.chat < z.media && z.media < z.controls && z.controls < z.island, "4. thứ tự z: chat < video < điều khiển < island", JSON.stringify(z));

  await browser.close();
  console.log(failed ? `\n${failed} check(s) FAILED` : "\nall passed");
  process.exit(failed ? 1 : 0);
})();
