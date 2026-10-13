// E2E: trên điện thoại cả trang không bao giờ cuộn/kéo được (kể cả khi bàn phím ảo hiện, lúc iOS cho kéo cả trang): chỉ khung
// bong bóng chat (và các khung có thanh cuộn riêng) cuộn được, và chỉ cuộn bên trong khung đó — kéo tới mép trên/dưới của khung
// rồi kéo tiếp cũng không kéo theo cả trang.
// Kiểm bằng sự kiện touchmove giả (cancelable): bị chặn = defaultPrevented.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/page-scroll-lock.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
const LONG = "Đây là một câu trả lời khá dài để khung chat có thanh cuộn riêng, đủ nhiều dòng trên màn hình điện thoại.";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true })).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  for (let i = 0; i < 18; i++) {
    sock.send(JSON.stringify({ type: "stream_start" })); await page.waitForTimeout(20);
    sock.send(JSON.stringify({ type: "text_chunk", text: `${i + 1}. ${LONG}` })); await page.waitForTimeout(40);
    sock.send(JSON.stringify({ type: "stream_end" })); await page.waitForTimeout(20);
  }
  await page.waitForTimeout(1200);
  await page.evaluate(() => document.getElementById("command-input").focus()); // bàn phím ảo đang hiện

  // drag(selector, dy): touchstart at the element's centre, touchmove by dy (positive = finger moves down) → was it blocked?
  const drag = (sel, dy, prep) => page.evaluate(([sel, dy, prep]) => {
    const el = document.querySelector(sel);
    if (prep === "top") el.scrollTop = 0;
    if (prep === "bottom") el.scrollTop = el.scrollHeight;
    if (prep === "middle") el.scrollTop = (el.scrollHeight - el.clientHeight) / 2;
    const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 60);
    const t = (yy) => new Touch({ identifier: 1, target: el, clientX: x, clientY: yy });
    el.dispatchEvent(new TouchEvent("touchstart", { bubbles: true, cancelable: true, touches: [t(y)], targetTouches: [t(y)], changedTouches: [t(y)] }));
    const move = new TouchEvent("touchmove", { bubbles: true, cancelable: true, touches: [t(y + dy)], targetTouches: [t(y + dy)], changedTouches: [t(y + dy)] });
    el.dispatchEvent(move);
    el.dispatchEvent(new TouchEvent("touchend", { bubbles: true, cancelable: true, touches: [], targetTouches: [], changedTouches: [t(y + dy)] }));
    return { blocked: move.defaultPrevented, scrollable: el.scrollHeight > el.clientHeight + 1 };
  }, [sel, dy, prep]);

  const chatInfo = await page.evaluate(() => { const c = document.getElementById("chat-history"); return { sh: c.scrollHeight, ch: c.clientHeight, ob: getComputedStyle(c).overscrollBehaviorY }; });
  check(chatInfo.sh > chatInfo.ch + 50, "0. khung chat có nhiều nội dung, cuộn được", JSON.stringify(chatInfo));

  let r = await drag("#jarvis-clock", 40);
  check(r.blocked, "1. bàn phím đang hiện: kéo ở đồng hồ (ngoài khung chat) không kéo được cả trang", JSON.stringify(r));
  r = await drag("#orb-canvas", -60);
  check(r.blocked, "2. kéo ở nền (quả cầu) không kéo được cả trang", JSON.stringify(r));
  r = await drag("#chat-history", 40, "middle");
  check(!r.blocked, "3. kéo trong khung chat (đang ở giữa) thì cuộn được", JSON.stringify(r));
  r = await drag("#chat-history", 40, "top");
  check(r.blocked, "4. khung chat đã ở trên cùng, kéo xuống tiếp: không kéo theo cả trang", JSON.stringify(r));
  r = await drag("#chat-history", -40, "bottom");
  check(r.blocked, "5. khung chat đã ở dưới cùng, kéo lên tiếp: không kéo theo cả trang", JSON.stringify(r));
  check(chatInfo.ob === "contain", "6. khung chat chặn cuộn lan ra trang (overscroll-behavior: contain)", chatInfo.ob);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
