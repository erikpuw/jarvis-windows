// E2E: khung chat kiểu các trang chat lớn (user 2026-10-17 "thiết kế lại mà không ảnh hưởng nhiều").
//  Câu trả lời của Jarvis không có bong bóng: không nền, không viền, rộng hết cột chat, chữ sáng dễ đọc;
//  tin của người dùng vẫn là bong bóng nhỏ bên phải. Bảng rộng hết cột, cuộn ngang trong khung riêng khi quá rộng.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/chat-layout.cjs   (cần `npm run dev` ở :5173)
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

  await page.fill("#command-input", "Giá tổng hợp");
  await page.click("#cmd-send");
  await page.waitForTimeout(500);
  send({ type: "stream_start" });
  send({ type: "text_chunk", text: "Dạ, **giá xăng** hôm nay:\n\n| Sản phẩm | Vùng 1 | Vùng 2 | Ghi chú |\n| :---: | :---: | :---: | :---: |\n"
    + "| Xăng E10 RON 95 Mức 3 | 26.720 VNĐ. | 27.250 VNĐ. | Petrolimex niêm yết |\n| DO 0,001S Mức 5 | 30.200 VNĐ. | 30.800 VNĐ. | Petrolimex |\n\nNgài cần gì thêm ạ?" });
  send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  await page.waitForTimeout(3000);

  const r = await page.evaluate(() => {
    const h = document.getElementById("chat-history"), hs = getComputedStyle(h);
    const inner = h.clientWidth - parseFloat(hs.paddingLeft) - parseFloat(hs.paddingRight);
    const a = [...h.querySelectorAll(".chat-bubble.assistant")].pop(), u = [...h.querySelectorAll(".chat-bubble.user")].pop();
    const as = getComputedStyle(a), us = getComputedStyle(u);
    const p = a.querySelector(".bubble-prose p"), w = a.querySelector(".sd-table-wrap");
    return {
      inner: Math.round(inner), aWidth: Math.round(a.getBoundingClientRect().width), aBg: as.backgroundColor, aBorder: as.borderTopWidth,
      text: getComputedStyle(p).color, uBg: us.backgroundColor, uWidth: Math.round(u.getBoundingClientRect().width), uRight: Math.round(u.getBoundingClientRect().right),
      wrapWidth: w && Math.round(w.getBoundingClientRect().width), wrapOverflow: w && getComputedStyle(w).overflowX,
    };
  });
  const rgb = (c) => (c.match(/[\d.]+/g) || []).map(Number);
  const [tr, tg, tb] = rgb(r.text);
  check(rgb(r.aBg)[3] === 0 && r.aBorder === "0px", "1. câu trả lời không có bong bóng (không nền, không viền)", JSON.stringify(r));
  check(r.aWidth >= r.inner - 2, "2. câu trả lời rộng hết cột chat", `${r.aWidth} / ${r.inner}`);
  check(tr > 200 && tg > 200 && tb > 200, "3. chữ câu trả lời sáng (gần trắng), dễ đọc trên nền đen", r.text);
  check(rgb(r.uBg).length < 4 || rgb(r.uBg)[3] > 0, "4. tin người dùng vẫn là bong bóng có nền", r.uBg);
  check(r.uWidth < r.inner * 0.9, "5. bong bóng người dùng nhỏ, nằm bên phải", `${r.uWidth} / ${r.inner}`);
  check(r.wrapWidth >= r.inner - 2 && r.wrapOverflow === "auto", "6. bảng rộng hết cột, cuộn ngang trong khung riêng", `${r.wrapWidth} ${r.wrapOverflow}`);

  // the only cards left in the chat are previews: a screenshot comes as an image_result (the flow tracker lives in the island)
  send({ type: "screenshot_processed", url: "/favicon.ico" });
  await page.waitForTimeout(400);
  const shot = await page.evaluate(() => !!document.querySelector("#chat-history .chat-bubble.assistant .image-result-preview"));
  check(shot, "7. ảnh chụp màn hình hiện thành khung xem trước trong chat");

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
