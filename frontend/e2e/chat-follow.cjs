// E2E: after the user sends, the chat keeps the newest answer in view (2026-10-18: on the phone the answer was pushed
// below and had to be dragged up). Covers a plain send, a send where the screen height changes (the keyboard closing), and a
// send made while the user had scrolled up to read (the chat must jump back to the newest message).
// Run: PW=<playwright module> node frontend/e2e/chat-follow.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const LONG = Array.from({ length: 14 }, (_, i) => `Dòng trả lời số ${i + 1} của Jarvis, đủ dài để xuống dòng trên điện thoại.`).join("\n\n");

async function run(viewport, name, keyboard, longAsk = false, readUp = false, viaButton = false) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: keyboard ? { width: viewport.width, height: 480 } : viewport });
  const socks = [];
  await page.routeWebSocket(/\/ws/, (ws) => { socks.push(ws); });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !socks.length; i++) await page.waitForTimeout(100);
  const send = (o) => socks[socks.length - 1].send(JSON.stringify(o));
  await page.waitForTimeout(600);
  const typing = [];
  // ceiling = the island's bottom: the chat box must stay under it, and the newest bubble at the box's bottom
  const measure = () => page.evaluate(() => {
    const ch = document.getElementById("chat-history"), r = ch.getBoundingClientRect();
    const island = document.getElementById("error-text"), pill = island.querySelector(".island-pill");
    const ceiling = island.offsetTop + pill.offsetTop + pill.offsetHeight;
    const last = [...ch.querySelectorAll(".chat-bubble")].pop()?.getBoundingClientRect();
    return { top: Math.round(r.top), ceiling, gap: last ? Math.round(r.bottom - last.bottom) : 0 };
  });
  // the user drags the chat up to read an older message, then types and sends (2026-10-18: the chat stayed up there)
  const scrollUp = async () => {
    const box = await page.evaluate(() => { const r = document.getElementById("chat-history").getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    if (viewport.width > 768) { await page.mouse.move(box.x, box.y); await page.mouse.wheel(0, -2000); }
    else await page.evaluate(() => { const ch = document.getElementById("chat-history"); ch.scrollTop = 0; ch.dispatchEvent(new TouchEvent("touchmove", { bubbles: true })); });
    await page.waitForTimeout(400);
    return page.evaluate(() => Math.round(document.getElementById("chat-history").scrollTop));
  };
  let upAt = null, sentSeen = null;
  const turn = async (q, up = false) => {
    if (up) upAt = await scrollUp();
    if (keyboard) { await page.setViewportSize({ width: viewport.width, height: 480 }); await page.waitForTimeout(300); } // keyboard opens to type
    if (longAsk) { // a long question: the input grows to its 140px cap while typing
      await page.fill("#command-input", (q + " ").repeat(40));
      await page.waitForTimeout(300);
      typing.push(await measure());
    }
    await page.fill("#command-input", longAsk ? (q + " ").repeat(40) : q);
    if (viaButton) await page.click("#cmd-send"); else await page.press("#command-input", "Enter");
    if (up) { // the send itself jumps to the newest message: the user's own bubble is in view at once, before any answer
      await page.waitForTimeout(80);
      sentSeen = await page.evaluate(() => { const ch = document.getElementById("chat-history"), r = ch.getBoundingClientRect();
        const b = [...ch.querySelectorAll(".chat-bubble.user")].pop().getBoundingClientRect(); return b.bottom <= r.bottom + 2 && b.top >= r.top - 2; });
    }
    if (keyboard) { await page.waitForTimeout(50); await page.setViewportSize(viewport); } // keyboard closes: the page grows
    await page.waitForTimeout(150);
    send({ type: "stream_start" });
    for (const part of LONG.match(/[\s\S]{1,120}/g)) { send({ type: "text_chunk", text: part }); await page.waitForTimeout(30); }
    send({ type: "stream_end" });
    await page.waitForTimeout(2500); // typewriter drains
  };
  await turn("câu hỏi một");
  await turn("câu hỏi hai", readUp);
  await page.waitForTimeout(300);
  const m = await page.evaluate(() => {
    const ch = document.getElementById("chat-history"), r = ch.getBoundingClientRect();
    const last = [...ch.querySelectorAll(".chat-bubble")].pop().getBoundingClientRect();
    return { lastBottom: Math.round(last.bottom), chatBottom: Math.round(r.bottom), gap: Math.round(r.bottom - last.bottom) };
  });
  check(m.lastBottom <= m.chatBottom + 2 && m.gap < 60 && sentSeen !== false, `${name}: câu trả lời mới nhất nằm trọn trong khung, không phải kéo`, JSON.stringify({ ...m, upAt, sentSeen }));
  const after = await measure();
  if (longAsk) check(typing.every((t) => t.top >= t.ceiling && t.gap >= -2 && t.gap < 60) && after.top >= after.ceiling && after.top - after.ceiling < 30,
    `${name}: lúc gõ và sau khi gửi, khung chat không trèo lên đảo, không tụt xuống, tin mới nhất vẫn ở đáy`, JSON.stringify({ typing, after }));
  await browser.close();
}

(async () => {
  await run({ width: 390, height: 844 }, "1. điện thoại", false);
  await run({ width: 390, height: 844 }, "2. điện thoại, bàn phím đóng sau khi gửi", true);
  await run({ width: 1280, height: 800 }, "3. PC", false);
  await run({ width: 390, height: 844 }, "4. điện thoại, câu hỏi dài", false, true);
  await run({ width: 1280, height: 800 }, "5. PC, câu hỏi dài", false, true);
  await run({ width: 390, height: 844 }, "6. điện thoại, đang kéo lên đọc rồi gửi", false, false, true);
  await run({ width: 1280, height: 800 }, "7. PC, đang cuộn lên đọc rồi gửi", false, false, true);
  await run({ width: 390, height: 844 }, "8. điện thoại, đang kéo lên đọc rồi bấm nút gửi", false, false, true, true);
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
