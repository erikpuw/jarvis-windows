// E2E: dải mờ trên đỉnh khung chat chỉ hiện khi tin nhắn đã cuộn qua mép trên (user 2026-10-16: lúc stream_start nó hiện
//  ngang giữa màn hình). WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/chat-fade.cjs   (cần `npm run dev`)
const { chromium } = require(process.env.PW || "playwright");
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto("http://localhost:5173/");
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  const send = (o) => sock.send(JSON.stringify(o));
  const probe = (tag) => page.evaluate((tag) => {
    const c = document.getElementById("command-container"), h = document.getElementById("chat-history");
        const cs = getComputedStyle(c, "::before");
    return { tag, bandTop: Math.round(c.getBoundingClientRect().top), bandOpacity: cs.opacity, bandBg: cs.backgroundImage, pageBg: getComputedStyle(document.body).backgroundColor, chatTop: Math.round(h.getBoundingClientRect().top), chatH: h.clientHeight, scrollH: h.scrollHeight, scrollTop: Math.round(h.scrollTop), cls: h.className + " | " + c.className, firstChild: c.firstElementChild?.id };
  }, tag);
  send({ type: "stream_start" }); await page.waitForTimeout(300);
  const first = await probe("after stream_start");
  check(first.bandOpacity === "0", "1. tin đầu (chat chưa chạm trần): không có dải mờ", JSON.stringify(first));
  send({ type: "text_chunk", text: "Dạ chào Ngài." }); send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  await page.waitForTimeout(800);
  for (let k = 0; k < 8; k++) { send({ type: "stream_start" }); send({ type: "text_chunk", text: "Câu trả lời dài số " + k + ". ".repeat(1) + "Lorem ipsum dolor sit amet ".repeat(4) }); send({ type: "stream_end" }); send({ type: "status", state: "idle" }); await page.waitForTimeout(700); }
  const many = await probe("many msgs");
  check(many.bandOpacity === "1" && many.bandTop === many.chatTop && many.scrollTop > 4, "2. tin đã cuộn qua mép trên: dải mờ hiện, nằm đúng mép trên khung chat", JSON.stringify(many));
  check(/^linear-gradient\(rgba\(0, 0, 0, [\d.]+\)/.test(many.bandBg) && many.pageBg === "rgb(0, 0, 0)", "3. dải mờ là gradient đen trùng màu nền #000", many.bandBg + " | nền " + many.pageBg);
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
