// E2E: câu trả lời hai đoạn (đoạn 1 báo dùng tool, rồi "\n\n", tool chạy, đoạn 2 tổng hợp — engine/turn/loop.py out.gap())
//  không tự xuống dòng trống lúc tool đang chạy và không nhảy lên khi kết thúc (user 2026-10-17): lúc gõ, các dòng đã xong
//  hiện bằng markdown y như bản cuối, nên bản cuối không dời gì.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/stream-rounds.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
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
  await page.waitForTimeout(1500);
  const send = (o) => sock.send(JSON.stringify(o));
  const height = () => page.evaluate(() => Math.round([...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop().getBoundingClientRect().height));

  send({ type: "stream_start" });
  send({ type: "text_chunk", text: "🛠️ Tôi sẽ tra giá vàng cho Ngài ngay đây." });
  await page.waitForTimeout(1500);
  const h1 = await height();
  send({ type: "text_chunk", text: "\n\n" }); // round 1 done, the tool runs
  await page.waitForTimeout(1200);
  const hWait = await height();
  check(hWait === h1, "1. lúc tool đang chạy: không tự xuống dòng trống dưới đoạn 1", `${h1} → ${hWait}`);

  send({ type: "text_chunk", text: "Dạ, giá vàng SJC hôm nay là **140 triệu**/lượng, tăng nhẹ so với hôm qua.\n\nNgài cần theo dõi thêm mặt hàng nào ạ?" });
  await page.waitForTimeout(3000);
  const typed = await page.evaluate(() => {
    const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop();
    return { h: Math.round(b.getBoundingClientRect().height), text: b.textContent };
  });
  send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  await page.waitForTimeout(800);
  const hEnd = await height();
  check(typed.text.includes("Ngài cần theo dõi"), "2. đoạn 2 đã gõ xong trước khi kết thúc", typed.text.slice(-40));
  check(Math.abs(hEnd - typed.h) <= 1, "3. kết thúc: chữ không nhảy (cao như lúc vừa gõ xong)", `${typed.h} → ${hEnd}`);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
