// E2E: bong bóng trợ lý khi `stream_start` → chữ bắt đầu chạy.
//  - Có loader (khối bong bóng) giữa stream_start và chữ đầu tiên; khi chữ đầu tiên tới, khối bong bóng GOM VỀ giữa rồi thu nhỏ và tan đi (animation),
//    chữ gõ ra từng chữ.
//  - KHÔNG nẩy: khung bong bóng chat không được co rồi giãn lại / nhảy kích thước ở khoảnh khắc chuyển từ loader sang chữ
//    (chiều cao chỉ được tăng đơn điệu theo số dòng chữ, mép dưới của khung không nhảy lên xuống), bong bóng không bị giật ngang.
//  - Khung bong bóng PHẢI ôm hết chữ của nó (không co lại thấp hơn chữ: chữ tràn ra ngoài khung) — các bong bóng trong #chat-history là flex item nên cần flex-shrink:0.
//  - Chữ gõ ra theo từng câu thì khung chat PHẢI tự cuộn xuống theo, đẩy giao diện lên để người dùng luôn thấy chữ mới (mép dưới bong bóng luôn nằm
//    trong vùng nhìn thấy của #chat-history), cả khi chữ rất dài, trên máy tính lẫn điện thoại. Người dùng tự cuộn lên xem thì không bị kéo xuống.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/stream-start.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const SENTENCES = Array.from({ length: 30 }, (_, i) => `Đây là câu số ${i + 1} của câu trả lời dài, viết ra từng câu một để kiểm tra khung chat có tự cuộn theo hay không. `);
const OLD = Array.from({ length: 16 }, (_, i) => `Tin nhắn cũ số ${i + 1} để khung chat đã đầy và phải cuộn.`);

async function run(label, opts) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  const send = (m) => sock.send(JSON.stringify(m));
  const tag = `[${label}]`;

  // đầy khung chat bằng vài lượt cũ
  for (const t of OLD) {
    send({ type: "stream_start" }); await page.waitForTimeout(60);
    send({ type: "text_chunk", text: t }); await page.waitForTimeout(260);
    send({ type: "stream_end" }); await page.waitForTimeout(120);
  }
  await page.waitForTimeout(600);

  // đo mỗi khung hình từ stream_start tới khi chữ chạy
  await page.evaluate(() => {
    window.__log = [];
    const h = document.getElementById("chat-history");
    const tick = () => {
      const b = [...h.querySelectorAll(".chat-bubble.assistant")].pop(), hr = h.getBoundingClientRect();
      if (b) { const r = b.getBoundingClientRect(), tb = b.querySelector(".bubble-text")?.getBoundingClientRect().bottom ?? r.bottom; window.__log.push({ t: performance.now(), top: r.top, bottom: r.bottom, textBottom: tb, h: r.height, w: r.width, hostCls: b.querySelector(".stream-bubble-host")?.className || "", loader: b.classList.contains("typing-loader"), visBottom: hr.bottom, visTop: hr.top, text: (b.querySelector(".bubble-text")?.textContent || "").length }); }
      window.__raf = requestAnimationFrame(tick);
    };
    window.__raf = requestAnimationFrame(tick);
  });
  send({ type: "stream_start" });
  await page.waitForTimeout(900); // loader quay một lúc
  const mark = await page.evaluate(() => window.__log.length);
  send({ type: "text_chunk", text: "Xin chào." });
  await page.waitForTimeout(1200);
  const afterFirst = await page.evaluate((m) => window.__log.slice(m), mark);
  const loaderLog = await page.evaluate((m) => window.__log.slice(0, m), mark);

  check(loaderLog.some((s) => s.loader) && loaderLog.some((s) => /stream-bubble-host/.test(s.hostCls)), `${tag} 1a. giữa stream_start và chữ đầu có loader (khối bong bóng)`);
  check(afterFirst.some((s) => /collapsing/.test(s.hostCls)), `${tag} 1b. khi chữ đầu tới, khối bong bóng GOM VỀ (collapsing) rồi tan đi`);
  check(afterFirst.at(-1).text >= 5 && !/stream-bubble-host/.test(afterFirst.at(-1).hostCls), `${tag} 1c. sau đó chỉ còn chữ, khối bong bóng đã gỡ hẳn`, JSON.stringify({ text: afterFirst.at(-1).text, host: afterFirst.at(-1).hostCls }));
  const lastLoader = loaderLog.at(-1), oneLine = afterFirst.at(-1);
  check(Math.abs(lastLoader.h - oneLine.h) <= 1, `${tag} 2c. nẩy: bong bóng lúc còn loader cao bằng đúng bong bóng một dòng chữ (không nhảy chiều cao khi chữ hiện ra)`, `loader ${lastLoader.h.toFixed(1)}px → một dòng chữ ${oneLine.h.toFixed(1)}px`);

  // không nẩy: chiều cao đơn điệu không giảm (cho phép 1px), mép dưới không nhảy ngược lên, bề ngang không dao động quá lớn
  let drop = 0, dropAt = -1, bottomUp = 0, wJitter = 0;
  const seq = [...loaderLog.slice(-5), ...afterFirst];
  for (let i = 1; i < seq.length; i++) {
    const dh = seq[i - 1].h - seq[i].h; if (dh > drop) { drop = dh; dropAt = i; }
    const db = seq[i - 1].bottom - seq[i].bottom; if (db > bottomUp && seq[i].h >= seq[i - 1].h) bottomUp = db;
  }
  const ws = afterFirst.map((s) => s.w); for (let i = 2; i < ws.length; i++) { if ((ws[i - 1] - ws[i - 2]) * (ws[i] - ws[i - 1]) < 0 && Math.abs(ws[i] - ws[i - 1]) > 3) wJitter++; }
  check(drop <= 2, `${tag} 2a. không nẩy: chiều cao khung bong bóng không co lại khi chuyển từ loader sang chữ`, `giảm lớn nhất ${drop.toFixed(1)}px tại khung ${dropAt}`);
  check(wJitter === 0, `${tag} 2b. bề ngang khung không dao động qua lại`, `${wJitter} lần`);

  // chữ dài chạy theo từng câu: khung chat tự cuộn theo
  for (let i = 0; i < SENTENCES.length; i++) { send({ type: "text_chunk", text: SENTENCES[i] }); await page.waitForTimeout(300); }
  await page.waitForTimeout(1500);
  const tail = await page.evaluate(() => { const h = document.getElementById("chat-history"), b = [...h.querySelectorAll(".chat-bubble.assistant")].pop(), t = b.querySelector(".bubble-text"), r = b.getBoundingClientRect(), tr = t.getBoundingClientRect(), hr = h.getBoundingClientRect(); return { bottom: Math.round(r.bottom), textBottom: Math.round(tr.bottom), visBottom: Math.round(hr.bottom), bubbleH: Math.round(r.height), textH: Math.round(tr.height), chatH: Math.round(hr.height), scrollTop: Math.round(h.scrollTop), text: t.textContent.length }; });
  check(tail.text > 400, `${tag} 3a. chữ dài đã gõ ra`, JSON.stringify(tail));
  check(tail.bubbleH >= tail.textH, `${tag} 3a2. khung bong bóng ôm hết chữ (chữ không tràn ra ngoài khung)`, JSON.stringify({ bubbleH: tail.bubbleH, textH: tail.textH }));
  const shrunk = await page.evaluate(() => [...document.querySelectorAll("#chat-history .chat-bubble")].filter((b) => b.offsetHeight > 0 && b.scrollHeight > b.clientHeight + 2).length);
  check(shrunk === 0, `${tag} 3a3. không bong bóng nào (kể cả bong bóng cũ) bị bóp thấp hơn nội dung của nó`, `${shrunk} bong bóng`);
  check(tail.textBottom <= tail.visBottom + 2, `${tag} 3b. đang stream mà mép dưới CHỮ vẫn nằm trong vùng nhìn thấy (khung chat tự cuộn theo chữ)`, JSON.stringify(tail));
  const worst = await page.evaluate(() => { const h = document.getElementById("chat-history"); return Math.max(0, ...window.__log.slice(-200).map((s) => s.textBottom - s.visBottom)); });
  check(worst <= 40, `${tag} 3c. suốt lúc gõ, chữ mới không tụt khỏi tầm nhìn quá 40px (không chờ cả câu mới nhảy xuống)`, `${worst.toFixed(0)}px`);

  // người dùng cuộn lên xem thì không bị kéo xuống
  await page.evaluate(() => { const h = document.getElementById("chat-history"); h.scrollTop = 0; h.dispatchEvent(new WheelEvent("wheel", { deltaY: -40 })); });
  const before = await page.evaluate(() => document.getElementById("chat-history").scrollTop);
  send({ type: "text_chunk", text: "Thêm một câu nữa trong lúc người dùng đang cuộn lên xem lại phần trước. " }); await page.waitForTimeout(900);
  const kept = await page.evaluate(() => document.getElementById("chat-history").scrollTop);
  check(kept <= before + 30, `${tag} 3d. người dùng cuộn lên xem lại thì không bị kéo xuống giữa chừng`, `${before} → ${kept}`);

  send({ type: "stream_end" }); await page.waitForTimeout(500);
  await page.evaluate(() => cancelAnimationFrame(window.__raf));
  await browser.close();
}

(async () => {
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  await run("điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
