// E2E: bảng markdown trong câu trả lời đang stream không làm bong bóng chat nhảy (user 2026-10-16: "nhảy tung trời").
//  Trong lúc bảng chưa đủ dữ liệu, bong bóng hiện skeleton CỐ ĐỊNH (không dựng lại, không đổi chiều cao theo từng dòng về);
//  đủ dữ liệu (có dòng khác sau bảng, hoặc hết câu trả lời) thì mới hiện bảng thật một lần.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/stream-table.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const rows = Array.from({ length: 12 }, (_, i) => `| Samsung Galaxy S${20 + i} Ultra 256GB | ${15 + i}.990.000₫ | cellphones |`);
const TABLE = "| Sản phẩm | Giá | Nguồn |\n| :--- | ---: | :--- |\n" + rows.join("\n") + "\n";

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

  send({ type: "stream_start" });
  send({ type: "text_chunk", text: "Dạ, đây là bảng giá thưa Ngài:\n\n" });
  await page.waitForTimeout(800);
  // watch the bubble: full re-renders (its children replaced) and height changes, every frame
  await page.evaluate(() => {
    const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop();
    window.__rebuilds = 0; window.__heights = [];
    new MutationObserver((ms) => { for (const m of ms) if (m.target.classList?.contains("bubble-text") && m.removedNodes.length) window.__rebuilds++; })
      .observe(b, { childList: true, subtree: true });
    let last = -1;
    const tick = () => { const h = Math.round(b.getBoundingClientRect().height); if (h !== last) { window.__heights.push(h); last = h; } window.__tick = requestAnimationFrame(tick); };
    tick();
  });
  // the table arrives line by line, like a tool display table streamed in
  for (const line of TABLE.split("\n")) { send({ type: "text_chunk", text: line + "\n" }); await page.waitForTimeout(180); }
  await page.waitForTimeout(800);
  const during = await page.evaluate(() => ({ rebuilds: window.__rebuilds, heights: window.__heights.slice(), skeleton: !!document.querySelector("#chat-history .sd-table--skeleton"), real: !!document.querySelector("#chat-history .sd-table:not(.sd-table--skeleton)") }));
  check(during.skeleton && !during.real, "1. bảng đang về (chưa đủ dữ liệu): hiện skeleton, chưa hiện bảng dở", JSON.stringify(during));
  check(during.rebuilds <= 2, "2. trong lúc bảng về từng dòng, bong bóng không bị dựng lại liên tục", `${during.rebuilds} lần dựng lại`);
  check(during.heights.length <= 3, "3. chiều cao bong bóng giữ yên trong lúc chờ (không nhảy theo từng dòng)", JSON.stringify(during.heights));

  // the answer goes on after the table → the table is complete and shows at once, while the text after it keeps typing
  //  letter by letter (not in 150 ms lumps) and the table is not rebuilt meanwhile
  await page.evaluate(() => {
    const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop();
    window.__lens = []; window.__rebuilds = 0; window.__tableAt = -1;
    const tick = () => { const n = b.textContent.length; if (n !== window.__lens[window.__lens.length - 1]) window.__lens.push(n);
      if (window.__tableAt < 0 && b.querySelector(".sd-table:not(.sd-table--skeleton)")) window.__tableAt = window.__lens.length;
      requestAnimationFrame(tick); };
    tick();
  });
  send({ type: "text_chunk", text: "\nNgài muốn tôi theo dõi giá máy nào ạ? Tôi có thể báo khi giá giảm dưới mức Ngài đặt." });
  await page.waitForTimeout(2500);
  const after = await page.evaluate(() => ({ steps: window.__lens.length, tableAt: window.__tableAt, rebuilds: window.__rebuilds }));
  check(after.tableAt > 0 && after.tableAt < after.steps - 10, "5. đủ dữ liệu giữa chừng: bảng thật hiện ra trong lúc chữ phía sau vẫn đang gõ", JSON.stringify(after));
  check(after.steps >= 20 && after.rebuilds <= 3, "6. chữ sau bảng gõ mượt từng chữ, bảng không bị dựng lại liên tục", JSON.stringify(after));
  send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  await page.waitForTimeout(800);
  const end = await page.evaluate(() => ({ rows: document.querySelectorAll("#chat-history .sd-table:not(.sd-table--skeleton) tbody tr").length, skeleton: !!document.querySelector("#chat-history .sd-table--skeleton"), rebuilds: window.__rebuilds }));
  check(end.rows === 12 && !end.skeleton, "4. đủ dữ liệu: hiện bảng thật đủ 12 dòng, hết skeleton", JSON.stringify(end));

  // a wide table scrolls sideways inside its own frame, and that frame stays inside the bubble (user 2026-10-16: squeezing
  // the table into the bubble split words and still spilled on the phone)
  const fit = await page.evaluate(() => {
    const w = document.querySelector("#chat-history .sd-table-wrap"), b = w.closest(".chat-bubble");
    return { overflowX: getComputedStyle(w).overflowX, wrapRight: Math.round(w.getBoundingClientRect().right), bubbleRight: Math.round(b.getBoundingClientRect().right) };
  });
  check(fit.overflowX === "auto" && fit.wrapRight <= fit.bubbleRight, "7. bảng rộng cuộn ngang trong khung riêng, khung nằm trong bong bóng", JSON.stringify(fit));

  // the tool's market tables centre every column and carry long prices (user screenshot 2026-10-16: pushed past the bubble)
  send({ type: "stream_start" });
  send({ type: "text_chunk", text: "Giá xăng dầu:\n\n| Sản phẩm | Vùng 1 | Vùng 2 | Ghi chú |\n| :---: | :---: | :---: | :---: |\n"
    + "| Xăng E10 RON 95 Mức 3 | 26.720 VNĐ. | 27.250 VNĐ. | 140.900.000 VNĐ/lượng. |\n| DO 0,001S Mức 5 | 30.200 VNĐ. | 30.800 VNĐ. | Petrolimex |\n\nXong ạ." });
  send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  await page.waitForTimeout(3000);
  const wide = await page.evaluate(() => {
    const w = [...document.querySelectorAll("#chat-history .sd-table-wrap")].pop(), t = w.querySelector("table"), b = w.closest(".chat-bubble");
    return { wrapRight: Math.round(w.getBoundingClientRect().right), bubbleRight: Math.round(b.getBoundingClientRect().right), scrolls: t.getBoundingClientRect().width > w.clientWidth + 1 ? getComputedStyle(w).overflowX : "fits" };
  });
  check(wide.wrapRight <= wide.bubbleRight && ["auto", "fits"].includes(wide.scrolls), "8. bảng 4 cột căn giữa, giá dài: khung nằm trong bong bóng, phần rộng thì cuộn ngang", JSON.stringify(wide));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
