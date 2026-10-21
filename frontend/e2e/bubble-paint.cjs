// E2E: chat bubbles cost nothing once they are drawn (user 2026-10-17: the more bubbles, the hotter the iPhone; with no bubbles
//  the orb, bot and metal ring run cool for an hour). On iPhone Safari each bubble kept its own GPU layers: a translucent
//  "liquid glass" overlay (::before, asked to be removed long ago) and the finished slide-up animation, all re-blended every
//  frame over the moving orb. Now: no overlay; the slide-up is dropped once it ends; older bubbles skip painting off screen.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/bubble-paint.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { dismissWelcome } = require("./_welcome.cjs");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await dismissWelcome(page);
  const send = (o) => sock.send(JSON.stringify(o));
  send({ type: "stream_start" }); send({ type: "text_chunk", text: "Dạ chào ngài." }); send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  for (let i = 0; i < 4; i++) {
    await page.fill("#command-input", "câu " + i); await page.$eval("#cmd-send", (x) => x.click());
    await page.waitForTimeout(200);
    send({ type: "stream_start" }); send({ type: "text_chunk", text: "Trả lời số " + i + " thưa ngài." }); send({ type: "stream_end" }); send({ type: "status", state: "idle" });
    await page.waitForTimeout(500);
  }
  await page.waitForTimeout(1000);
  const r = await page.evaluate(() => {
    const bs = [...document.querySelectorAll("#chat-history .chat-bubble")];
    return {
      n: bs.length,
      anims: bs.map((b) => getComputedStyle(b).animationName),
      before: bs.filter((b) => !b.classList.contains("pending")).map((b) => getComputedStyle(b, "::before").content),
      oldCv: bs.slice(0, -1).filter((b) => !b.classList.contains("pending")).map((b) => getComputedStyle(b).contentVisibility),
      lastCv: getComputedStyle(bs[bs.length - 1]).contentVisibility,
      bg: getComputedStyle(bs[bs.length - 1]).backgroundColor,
      running: document.getAnimations().filter((a) => a.effect?.target?.classList?.contains("chat-bubble")).length,
    };
  });
  check(r.n >= 9, "0. có đủ bong bóng", String(r.n));
  check(r.anims.every((a) => a === "none") && r.running === 0, "1. hiệu ứng trượt lên được gỡ khỏi bong bóng khi chạy xong", JSON.stringify({ anims: r.anims, running: r.running }));
  check(r.before.every((c) => c === "none"), "2. không còn lớp phủ liquid glass (::before) trên bong bóng", JSON.stringify(r.before));
  check(r.oldCv.length >= 8 && r.oldCv.every((c) => c === "auto") && r.lastCv !== "auto", "3. bong bóng cũ bỏ qua vẽ khi ngoài màn hình (content-visibility: auto), bong bóng mới nhất vẽ bình thường", JSON.stringify({ old: r.oldCv, last: r.lastCv }));
  check(r.bg === "rgba(0, 0, 0, 0)", "4. câu trả lời không có nền bong bóng (thiết kế 2026-10-17), không lớp kính đè lên orb", r.bg);
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
