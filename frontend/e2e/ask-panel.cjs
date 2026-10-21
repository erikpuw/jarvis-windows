// E2E: bảng hỏi (thẻ approve / select / input từ backend) là một khung nổi lên ngay trên thanh lệnh, kiểu cookie banner
//  (cuicui.day), không nằm trong bong bóng chat (user 2026-10-17: "bảng trong bong bóng chat quá xấu").
//  Chọn xong thì khung biến mất; câu hỏi mới thay khung cũ. Nút nhỏ vừa chữ, không màu (không xanh/đỏ), khung luôn cùng bề rộng.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/ask-panel.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  let sock = null;
  const sent = [];
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; ws.onMessage((m) => { try { sent.push(JSON.parse(m)); } catch {} }); });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  const send = (o) => sock.send(JSON.stringify(o));
  const responses = () => sent.filter((m) => m.type === "interactive_response");
  const panel = () => page.evaluate(() => {
    const p = document.querySelectorAll(".ask-panel");
    const el = p[p.length - 1];
    if (!el) return { count: 0 };
    const r = el.getBoundingClientRect(), bar = document.getElementById("command-bar-inner").getBoundingClientRect();
    const btns = [...el.querySelectorAll("button")].map((b) => { const cs = getComputedStyle(b); return { text: b.textContent.trim(), w: Math.round(b.getBoundingClientRect().width), bg: cs.backgroundColor, color: cs.color }; });
    return { count: p.length, id: el.dataset.cardId, w: Math.round(r.width), bottom: Math.round(r.bottom), barTop: Math.round(bar.top), btns, options: el.querySelectorAll(".ask-option").length,
      inChat: !!document.querySelector("#chat-history .interactive-card .interactive-btn, #chat-history .ask-panel") };
  });
  const neutral = (c) => { const [r, g, b] = (c.match(/[\d.]+/g) || []).map(Number); return Math.max(r, g, b) - Math.min(r, g, b) < 24; };

  // the message that leads to the question stays readable above the box
  for (const o of [{ type: "stream_start" }, { type: "text_chunk", text: "Dạ, tôi cần Ngài xác nhận trước khi mở ứng dụng." }, { type: "stream_end" }, { type: "status", state: "idle" }]) send(o);
  await page.waitForTimeout(1500);

  // watch the last message every frame: it glides up above the box, it does not jump in one frame
  await page.evaluate(() => {
    const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop();
    window.__ys = [];
    const t0 = performance.now();
    const tick = () => { window.__ys.push(Math.round(b.getBoundingClientRect().bottom)); if (performance.now() - t0 < 1200) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
  await page.waitForTimeout(150);

  // approve
  send({ type: "interactive", card: { id: "c1", type: "approve", title: "YÊU CẦU XÁC NHẬN HÀNH ĐỘNG", description: "Mở Task Manager? (Hành động: open_app)", approveLabel: "Đồng ý", rejectLabel: "Từ chối" } });
  await page.waitForTimeout(600);
  const a = await panel();
  check(a.count === 1 && !a.inChat, "1. câu hỏi hiện thành khung riêng, không nằm trong bong bóng chat", JSON.stringify(a));
  check(a.bottom <= a.barTop && a.barTop - a.bottom <= 16, "2. khung nằm ngay trên thanh lệnh", `${a.bottom} / ${a.barTop}`);
  const seen = await page.evaluate(() => {
    const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop(), p = document.querySelector(".ask-panel");
    const bar = document.getElementById("command-bar").getBoundingClientRect();
    return { msgBottom: Math.round(b.getBoundingClientRect().bottom), panelTop: Math.round(bar.top - 8 - p.offsetHeight) };
  });
  const ys = await page.evaluate(() => window.__ys);
  const steps = ys.slice(1).map((y, i) => Math.abs(y - ys[i]));
  const moving = steps.filter((d) => d > 0);
  const total = ys[0] - ys[ys.length - 1];
  check(total > 20 && moving.length >= 6 && Math.max(...steps) <= total / 3, "2c. chat trượt lên êm qua nhiều khung hình (không nhảy một phát)", `từ ${ys[0]} tới ${ys[ys.length - 1]}: ${moving.join(",")}`);
  check(seen.msgBottom <= seen.panelTop + 1, "2b. tin nhắn cuối vẫn thấy được, nằm ngay trên khung (không bị che)", JSON.stringify(seen));
  check(a.btns.length === 2 && a.btns.every((b) => b.w <= 110 && neutral(b.color) && (neutral(b.bg) || /, 0\)$/.test(b.bg))), "3. nút nhỏ vừa chữ, không màu xanh/đỏ", JSON.stringify(a.btns));
  await page.click(".ask-panel button:has-text('Đồng ý')");
  await page.waitForTimeout(600);
  const r1 = responses().pop();
  check(r1 && r1.cardId === "c1" && r1.action === "approve", "4. bấm Đồng ý gửi câu trả lời cho backend", JSON.stringify(r1));
  check((await panel()).count === 0, "5. chọn xong khung biến mất");
  // answered = torn down: nothing left in the DOM, no animation, and the chat's inline padding/transition gone (the glide's rAF loop removes the transition when it stops)
  const gone = await page.evaluate(async () => {
    await new Promise((r) => setTimeout(r, 300));
    const chat = document.getElementById("chat-history");
    return { nodes: document.querySelectorAll(".ask-panel, .ask-btn, .ask-option, .ask-input").length,
      anims: document.getAnimations().filter((a) => String(a.animationName || "").startsWith("ask") || a.transitionProperty === "padding-bottom").length,
      chatStyle: chat.getAttribute("style") || "" };
  });
  check(gone.nodes === 0 && gone.anims === 0 && !/padding|transition/.test(gone.chatStyle), "5b. trả lời xong khung bị huỷ hẳn: không còn phần tử, hiệu ứng hay style chạy ngầm", JSON.stringify(gone));

  // a new question replaces the old one; the panel keeps the same width
  send({ type: "interactive", card: { id: "c2", type: "approve", title: "XÁC NHẬN", description: "Ngắn?" } });
  send({ type: "interactive", card: { id: "c3", type: "select", title: "CHỌN MỘT MỤC", description: "Chọn trình duyệt", options: [{ value: "a", label: "Chrome" }, { value: "b", label: "Edge" }, { value: "c", label: "Firefox" }], multiple: false } });
  await page.waitForTimeout(600);
  const s = await panel();
  check(s.count === 1 && s.id === "c3" && s.options === 3, "6. câu hỏi mới thay khung cũ (chỉ còn 1 khung)", JSON.stringify(s));
  check(Math.abs(s.w - a.w) <= 1, "7. khung luôn cùng bề rộng (không lúc ngắn lúc dài)", `${a.w} / ${s.w}`);
  await page.click(".ask-panel .ask-option:has-text('Edge')");
  await page.waitForTimeout(600);
  const r3 = responses().pop();
  check(r3 && r3.cardId === "c3" && r3.action === "submit" && JSON.stringify(r3.value) === '["b"]', "8. chọn một mục là gửi ngay", JSON.stringify(r3));
  check((await panel()).count === 0, "9. chọn xong khung biến mất");

  // input
  send({ type: "interactive", card: { id: "c4", type: "input", title: "NHẬP NỘI DUNG", description: "Tên tệp?", placeholder: "Nhập..." } });
  await page.waitForTimeout(600);
  await page.fill(".ask-panel textarea", "bao-cao.docx");
  await page.click(".ask-panel button:has-text('Gửi')");
  await page.waitForTimeout(600);
  const r4 = responses().pop();
  check(r4 && r4.cardId === "c4" && r4.action === "submit" && r4.value === "bao-cao.docx", "10. ô nhập: Gửi nội dung đã gõ", JSON.stringify(r4));
  check((await panel()).count === 0, "11. gửi xong khung biến mất");

  // PC: the box stays a compact card (~400px), it does not stretch across the 800px command bar
  const pc = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  let pcSock = null;
  await pc.routeWebSocket(/\/ws/, (ws) => { pcSock = ws; });
  await pc.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await pc.goto(BASE);
  for (let i = 0; i < 50 && !pcSock; i++) await pc.waitForTimeout(100);
  await pc.waitForTimeout(1500);
  pcSock.send(JSON.stringify({ type: "interactive", card: { id: "p1", type: "approve", title: "XÁC NHẬN", description: "Mở Task Manager?" } }));
  await pc.waitForTimeout(600);
  const pw = await pc.evaluate(() => {
    const b = document.querySelector(".ask-panel").getBoundingClientRect(), bar = document.getElementById("command-bar").getBoundingClientRect();
    return { box: Math.round(b.width), bar: Math.round(bar.width), boxMid: Math.round(b.left + b.width / 2), barMid: Math.round(bar.left + bar.width / 2) };
  });
  check(pw.box <= 420 && pw.bar > 600, "12. PC: khung gọn (~400px), không giãn theo bề ngang thanh lệnh", JSON.stringify(pw));
  check(Math.abs(pw.boxMid - pw.barMid) <= 2, "13. PC: khung nằm giữa (thẳng tâm thanh lệnh), không lệch trái", JSON.stringify(pw));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
