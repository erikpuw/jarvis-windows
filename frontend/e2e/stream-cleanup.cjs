// E2E: sau mỗi lượt trả lời không còn gì chạy nền: vòng gõ chữ (requestAnimationFrame trong main.ts) dừng, loader 4 giọt (bộ lọc goo) bị gỡ.
// Kể cả khi backend không gửi stream_end: lượt bị huỷ (engine/turn/loop.py out.abort(), dọn bằng stream_start sau hoặc cancel của chính frontend), lỗi (gói "text"/"audio" dự phòng), hoặc stream_end tới ngay sau stream_start. Gõ hết chữ là vòng gõ chữ dừng, kể cả giữa lượt.
// Đọc rAF theo nơi gọi từ bảng ?debug=1 (window.__perf). WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/stream-cleanup.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const leftover = (p) => p.evaluate(() => ({
  typewriter: Object.keys(window.__perf.rafBy).filter((k) => k.startsWith("main.ts")),
  loaders: document.querySelectorAll(".stream-bubble-host").length,
  spinning: document.getAnimations().filter((a) => a.playState === "running" && /^stream-/.test(a.animationName || "")).length,
}));
const clean = (r) => r.typewriter.length === 0 && r.loaders === 0 && r.spinning === 0;

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE + "?debug=1");
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  const send = (o) => sock.send(JSON.stringify(o));
  const settle = () => page.waitForTimeout(2300); // the debug panel samples once a second

  // 1. lượt bình thường
  send({ type: "stream_start" }); await page.waitForTimeout(600);
  for (let i = 0; i < 10; i++) { send({ type: "text_chunk", text: `Câu thử ${i}. ` }); await page.waitForTimeout(40); }
  await page.waitForTimeout(800);
  send({ type: "stream_end" }); send({ type: "status", state: "idle" }); await settle();
  let r = await leftover(page);
  check(clean(r), "1. lượt bình thường: hết vòng gõ chữ, hết loader", JSON.stringify(r));

  // 2. stream_end tới ngay sau stream_start (trả lời rỗng/rất ngắn)
  send({ type: "stream_start" }); send({ type: "stream_end" }); await settle();
  r = await leftover(page);
  check(clean(r), "2. stream_end liền sau stream_start: vòng gõ chữ không chạy mãi", JSON.stringify(r));

  // 3. lỗi trong generate_response_stream (server.py): chỉ một gói "text" chứa câu dự phòng, không stream_end, không idle
  send({ type: "stream_start" }); await page.waitForTimeout(300); send({ type: "text", text: "Xin lỗi, có lỗi xảy ra." }); await settle();
  r = await leftover(page);
  const fallback = await page.$eval("#chat-history .chat-bubble.assistant:last-child", (e) => e.textContent.trim());
  check(clean(r) && fallback === "Xin lỗi, có lỗi xảy ra.", "3. lỗi (gói text, không stream_end): bong bóng loader trống bị gỡ, câu dự phòng hiện riêng", JSON.stringify({ ...r, fallback }));

  // 4. lượt bị huỷ rồi lượt mới bắt đầu ngay: loader của lượt cũ không quay mãi trong lịch sử chat
  send({ type: "stream_start" }); await page.waitForTimeout(300);
  send({ type: "stream_start" }); await page.waitForTimeout(300);
  send({ type: "text_chunk", text: "Lượt mới." }); await page.waitForTimeout(600);
  send({ type: "stream_end" }); send({ type: "status", state: "idle" }); await settle();
  r = await leftover(page);
  const last = await page.$eval("#chat-history .chat-bubble.assistant:last-child", (e) => e.textContent.trim());
  check(clean(r) && last === "Lượt mới.", "4. lượt mới đè lượt bị huỷ: loader cũ được gỡ, lượt mới hiện đủ chữ", JSON.stringify({ ...r, last }));

  // 5. chữ tới sau idle của TTS vẫn không bị cắt khi lượt còn đang chạy (idle chỉ dọn khi lượt đã xong)
  send({ type: "stream_start" }); await page.waitForTimeout(300);
  send({ type: "text_chunk", text: "Phần một. " }); send({ type: "status", state: "idle", source: "tts" });
  send({ type: "text_chunk", text: "Phần hai." }); await page.waitForTimeout(800);
  send({ type: "stream_end" }); send({ type: "status", state: "idle" }); await settle();
  const full = await page.$eval("#chat-history .chat-bubble.assistant:last-child", (e) => e.textContent.trim());
  check(full === "Phần một. Phần hai.", "5. idle của TTS giữa lượt không cắt chữ đang tới", full);

  // 7. vòng lặp turn: say trước tool → chờ tool (chưa stream_end) → đợt chữ trả lời. Gõ xong đợt đầu là vòng gõ chữ dừng hẳn, đợt sau đánh thức lại
  send({ type: "stream_start" }); await page.waitForTimeout(300);
  send({ type: "text_chunk", text: "Để tôi kiểm tra. " }); await settle();
  r = await leftover(page);
  const loaderGone = await page.$$eval("#chat-history .chat-bubble.typing-loader", (e) => e.length);
  check(r.typewriter.length === 0 && loaderGone === 0 && r.loaders === 0, "7a. gõ xong đợt chữ đầu, đang chờ tool: không còn vòng gõ chữ, loader đã tắt từ text_chunk đầu", JSON.stringify({ ...r, loaderGone }));
  send({ type: "text_chunk", text: "Máy đang chạy ổn định." }); await page.waitForTimeout(300);
  const mid = await page.evaluate(() => document.querySelector("#chat-history .chat-bubble.assistant:last-child .bubble-text").textContent);
  await page.waitForTimeout(900);
  const typed = await page.$eval("#chat-history .chat-bubble.assistant:last-child .bubble-text", (e) => e.textContent.trim());
  check(mid.length < "Để tôi kiểm tra. Máy đang chạy ổn định.".length && typed === "Để tôi kiểm tra. Máy đang chạy ổn định.", "7b. đợt chữ sau vẫn gõ dần ra đủ (không hiện cả cục)", JSON.stringify({ mid, typed }));
  send({ type: "stream_end" }); send({ type: "status", state: "idle" }); await settle();
  r = await leftover(page);
  check(clean(r), "7c. hết lượt: sạch", JSON.stringify(r));

  check(errors.length === 0, "6. không có lỗi trang", errors.slice(0, 2).join(" | "));
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
