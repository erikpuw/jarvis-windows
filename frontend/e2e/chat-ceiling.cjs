// E2E: đồng hồ đã gỡ (2026-10-15). Khung chat dài kéo lên tới ngay dưới viên đảo thông báo (Dynamic Island, #error-text),
//  chừa một khoảng nhỏ (GAP trong main.ts initChatAutoCeiling), không đè lên đảo; trên điện thoại lẫn máy tính.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/chat-ceiling.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  for (const [tag, opts] of [["điện thoại 390×844", { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }], ["máy tính 1280×800", { viewport: { width: 1280, height: 800 } }]]) {
    const page = await (await browser.newContext(opts)).newPage();
    let sock = null;
    await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
    await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
    await page.goto(BASE);
    for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
    await page.waitForTimeout(1500);
    for (let k = 0; k < 20; k++) {
      sock.send(JSON.stringify({ type: "stream_start" }));
      sock.send(JSON.stringify({ type: "text_chunk", text: `Dạ thưa Ngài, câu trả lời số ${k}, đủ dài để khung chat đầy lên tới đỉnh màn hình.` }));
      await page.waitForTimeout(150);
      sock.send(JSON.stringify({ type: "stream_end" }));
    }
    await page.waitForTimeout(800);
    const m = await page.evaluate(() => {
      const pill = document.querySelector("#error-text .island-pill").getBoundingClientRect(), chat = document.getElementById("chat-history").getBoundingClientRect();
      return { clock: !!document.getElementById("jarvis-clock"), pillBottom: Math.round(pill.bottom), chatTop: Math.round(chat.top) };
    });
    check(!m.clock, `[${tag}] 1. không còn đồng hồ`, JSON.stringify(m));
    const gap = m.chatTop - m.pillBottom;
    check(gap >= 10 && gap <= 30, `[${tag}] 2. khung chat đầy kéo lên ngay dưới đảo thông báo, chừa một khoảng (10–30px), không đè`, JSON.stringify({ ...m, gap }));
    await page.close();
  }
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
