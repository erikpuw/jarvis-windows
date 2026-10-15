// E2E: chữ trạng thái chỉ theo gói status (user chốt 2026-10-15; backend 444477c). stream_start/text_chunk/stream_end chỉ dành
//  cho bong bóng gõ chữ, không đổi chữ trạng thái. Thứ tự backend gửi trong một lượt:
//    working "Công cụ: …" (tool chạy) → thinking (LLM tổng hợp) → idle không source NGAY khi LLM xong (loop.run_loop, trước stream_end)
//    → TTS riêng: speaking source=tts (lúc worker bắt đầu: "Đang chuẩn bị…"; đầu mỗi câu: không message) và idle source=tts khi
//    dừng → server.py gửi thêm một idle không source cuối lượt (trùng, vô hại).
//  Khi TTS đang đọc / chuẩn bị đọc, working/thinking/idle không source không đè chữ đọc; đọc xong thì hiện trạng thái mới nhất.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/status-speech.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const tone = (sec) => { const n = 24000 * sec, a = new Int16Array(n); for (let i = 0; i < n; i++) a[i] = Math.sin((2 * Math.PI * 330 * i) / 24000) * 9000; return Buffer.from(a.buffer).toString("base64"); };
const idleLabel = (t) => t === "Sẵn sàng" || t === "Đang nghe…";

(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  const send = (o) => sock.send(JSON.stringify(o));
  const label = () => page.$eval("#status-text", (e) => e.textContent.trim());

  // A. tool turn, loud: the "say" is read while the tool runs
  send({ type: "stream_start" }); send({ type: "status", state: "thinking" }); await page.waitForTimeout(200);
  send({ type: "text_chunk", text: "Để tôi tra giá giúp Ngài. " });
  send({ type: "status", state: "speaking", message: "Đang chuẩn bị…", source: "tts" }); await page.waitForTimeout(100);
  send({ type: "status", state: "working", message: "Công cụ: Tra giá" }); await page.waitForTimeout(300);
  check((await label()) === "Đang chuẩn bị…", "1. TTS chuẩn bị đọc câu say: working của tool không đè", await label());
  send({ type: "status", state: "speaking", source: "tts" }); send({ type: "pcm_chunk", data: tone(1.2), sample_rate: 24000, gap_ms: 0 });
  await page.waitForTimeout(300);
  check((await label()) === "Đang đọc…", "2. câu say phát: Đang đọc…", await label());
  send({ type: "status", state: "thinking" }); await page.waitForTimeout(300);
  check((await label()) === "Đang đọc…", "3. đang đọc mà tool xong (thinking): vẫn Đang đọc…", await label());
  await page.waitForTimeout(1900); // the say is over, the LLM is still summarising
  check((await label()) === "Đang nghĩ…", "4. đọc xong câu say, LLM còn tổng hợp: Đang nghĩ…", await label());
  send({ type: "text_chunk", text: "Giá rẻ nhất là 15 triệu. Ngài có muốn theo dõi giá không?" }); await page.waitForTimeout(200);
  send({ type: "stream_end" }); await page.waitForTimeout(200);
  check((await label()) === "Đang nghĩ…", "5. text_chunk/stream_end không đổi chữ trạng thái (chỉ cho bong bóng)", await label());
  send({ type: "status", state: "idle" }); await page.waitForTimeout(200); // loop.py finish: the LLM is done
  // the LLM's idle is the LLM's own state: off at once; the reading label only comes from the TTS's own packets
  check(idleLabel(await label()), "6. idle không source (LLM xong), TTS chưa gửi gì: về rảnh ngay", await label());
  send({ type: "status", state: "speaking", source: "tts" }); send({ type: "pcm_chunk", data: tone(0.6), sample_rate: 24000, gap_ms: 0 });
  await page.waitForTimeout(300);
  check((await label()) === "Đang đọc…", "7. câu trả lời phát: Đang đọc…", await label());
  await page.waitForTimeout(1300); // the first sentence is over, the next one is still being synthesised
  check((await label()) === "Đang đọc…", "8. nghỉ giữa 2 câu (TTS chưa báo xong): vẫn Đang đọc…, không về Sẵn sàng", await label());
  send({ type: "status", state: "speaking", source: "tts" }); send({ type: "pcm_chunk", data: tone(0.6), sample_rate: 24000, gap_ms: 0 });
  await page.waitForTimeout(200);
  send({ type: "status", state: "idle", source: "tts" }); // everything synthesised
  await page.waitForTimeout(300);
  check((await label()) === "Đang đọc…", "9. idle TTS khi tiếng còn phát: đợi phát hết", await label());
  await page.waitForTimeout(1200);
  check(idleLabel(await label()), "10. phát hết: về rảnh", await label());
  send({ type: "status", state: "idle" }); await page.waitForTimeout(200); // server.py end of turn, duplicate
  check(idleLabel(await label()), "11. idle cuối lượt (trùng): vẫn rảnh", await label());

  // B. plain chat, loud: the TTS opens while the LLM is still writing; the LLM's idle must not cover the speech
  send({ type: "stream_start" }); send({ type: "status", state: "thinking" }); await page.waitForTimeout(200);
  check((await label()) === "Đang nghĩ…", "12. LLM đang trả lời: Đang nghĩ…", await label());
  send({ type: "text_chunk", text: "Dạ, hôm nay trời nắng nhẹ." });
  send({ type: "status", state: "speaking", message: "Đang chuẩn bị…", source: "tts" }); await page.waitForTimeout(150);
  send({ type: "stream_end" }); send({ type: "status", state: "idle" }); await page.waitForTimeout(200);
  check((await label()) === "Đang chuẩn bị…", "13. LLM xong (idle) khi TTS đang chuẩn bị: không đè Đang chuẩn bị…", await label());
  send({ type: "status", state: "speaking", source: "tts" }); send({ type: "pcm_chunk", data: tone(0.5), sample_rate: 24000, gap_ms: 0 });
  await page.waitForTimeout(250);
  check((await label()) === "Đang đọc…", "14. phát: Đang đọc…", await label());
  send({ type: "status", state: "idle", source: "tts" }); await page.waitForTimeout(1300);
  check(idleLabel(await label()), "15. đọc xong: về rảnh", await label());
  send({ type: "status", state: "idle" }); await page.waitForTimeout(200);

  // B2. loud, the TTS says it is preparing, then has nothing to read (its idle comes with no sound): idle on the TTS's idle
  send({ type: "stream_start" }); send({ type: "status", state: "thinking" });
  send({ type: "status", state: "speaking", message: "Đang chuẩn bị…", source: "tts" });
  send({ type: "text_chunk", text: "Dạ." }); send({ type: "status", state: "idle" }); await page.waitForTimeout(200);
  check((await label()) === "Đang chuẩn bị…", "15b. LLM xong khi TTS đang chuẩn bị (gói của TTS): giữ Đang chuẩn bị…", await label());
  send({ type: "stream_end" }); send({ type: "status", state: "idle", source: "tts" }); await page.waitForTimeout(200);
  check(idleLabel(await label()), "15c. TTS báo xong mà không có tiếng: về rảnh", await label());
  send({ type: "status", state: "idle" }); await page.waitForTimeout(200);

  // D. answer round, loud: backend sends thinking "Đang trả lời…" when the answer's first sentence comes out (user 2026-10-15)
  send({ type: "stream_start" }); send({ type: "status", state: "thinking" }); await page.waitForTimeout(150);
  send({ type: "status", state: "thinking", message: "Đang trả lời…" }); send({ type: "text_chunk", text: "Dạ, câu một. " });
  await page.waitForTimeout(150);
  check((await label()) === "Đang trả lời…", "18. câu trả lời bắt đầu về: Đang trả lời…", await label());
  send({ type: "status", state: "speaking", message: "Đang chuẩn bị…", source: "tts" }); send({ type: "status", state: "speaking", source: "tts" });
  send({ type: "pcm_chunk", data: tone(0.6), sample_rate: 24000, gap_ms: 0 }); await page.waitForTimeout(250);
  check((await label()) === "Đang đọc…", "19. TTS phát trong lúc LLM còn viết: Đang đọc… (TTS ưu tiên)", await label());
  await page.waitForTimeout(1200); // sound over, the LLM is still writing
  check((await label()) === "Đang trả lời…", "20. nghỉ giữa 2 câu, LLM còn viết: Đang trả lời… (trạng thái thật)", await label());
  send({ type: "status", state: "idle" }); await page.waitForTimeout(150); // LLM done
  const d = await label();
  check(d === "Sẵn sàng" || d === "Đang nghe…" || d === "Đang đọc…", "21. LLM xong: hết Đang trả lời…", d);
  send({ type: "stream_end" }); send({ type: "status", state: "idle", source: "tts" }); await page.waitForTimeout(300);
  send({ type: "status", state: "idle" }); await page.waitForTimeout(150);

  // C. TTS off in the browser: the LLM's idle ends "Đang nghĩ…" at once, whatever the typing is doing
  await page.evaluate(() => localStorage.setItem("jarvis_tts_disabled", "true"));
  await page.reload(); await page.waitForTimeout(2500);
  send({ type: "stream_start" }); send({ type: "status", state: "thinking" });
  send({ type: "text_chunk", text: "Dạ, hôm nay trời nắng nhẹ, khoảng ba mươi độ, Ngài nhớ mang ô nhé." });
  send({ type: "status", state: "speaking", message: "Đang chuẩn bị…", source: "tts" }); await page.waitForTimeout(150);
  send({ type: "stream_end" }); await page.waitForTimeout(100);
  check((await label()) === "Đang nghĩ…", "16. tắt loa: stream_end chưa phải tín hiệu trạng thái", await label());
  send({ type: "status", state: "idle" }); await page.waitForTimeout(150);
  check(idleLabel(await label()), "17. tắt loa: idle (LLM xong) → rảnh ngay, dù chữ còn đang gõ", await label());

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
