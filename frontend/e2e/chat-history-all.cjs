// E2E: khung chat giữ TOÀN BỘ lịch sử của phiên hiện tại, không cắt bớt bong bóng cũ.
//  Lỗi cũ: addBubble xóa bong bóng đầu tiên mỗi khi quá 36 phần tử, nên cuộc trò chuyện dài mất phần đầu (chữ đã nhận biến mất khỏi màn hình).
//  Đúng: mỗi phiên chat là một cuộc riêng (tải lại trang = phiên mới, khung chat trống), trong phiên đó không giới hạn số tin; bong bóng đầu
//  vẫn còn, kéo lên trên vẫn thấy, và khung vẫn cuộn xuống đúng bong bóng mới nhất.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/chat-history-all.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const TURNS = 45; // 90 bong bóng (+ khối hoạt động), gấp hơn 2 lần mức cắt cũ

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
  for (let i = 1; i <= TURNS; i++) {
    await page.fill("#command-input", `Câu hỏi số ${i}`);
    await page.evaluate(() => document.getElementById("cmd-send").click()); // bong bóng của người dùng
    send({ type: "stream_start" }); await page.waitForTimeout(25);
    send({ type: "text_chunk", text: `Trả lời số ${i}.` }); await page.waitForTimeout(45);
    send({ type: "stream_end" }); await page.waitForTimeout(25);
  }
  await page.waitForTimeout(1500);
  const r = await page.evaluate(() => {
    const h = document.getElementById("chat-history"), bubbles = [...h.querySelectorAll(".chat-bubble")];
    const texts = bubbles.map((b) => (b.querySelector(".bubble-text") || b).textContent.trim());
    const last = bubbles.at(-1).getBoundingClientRect(), hr = h.getBoundingClientRect();
    return { n: bubbles.length, kids: h.children.length, first: texts.find((t) => /số 1\b/.test(t)) || null, last: texts.at(-1), scrollable: h.scrollHeight > h.clientHeight, lastVisible: last.bottom <= hr.bottom + 2 };
  });
  check(r.n >= TURNS, `${tag} 1. không có bong bóng nào bị cắt: còn ${r.n} bong bóng (≥ ${TURNS}), cũ chỉ giữ tối đa 36`, `${r.n} bong bóng, ${r.kids} phần tử`);
  check(!!r.first, `${tag} 2. bong bóng đầu tiên của phiên vẫn còn`, JSON.stringify(r.first));
  check(/Trả lời số 45/.test(r.last || ""), `${tag} 3. bong bóng mới nhất đúng và đang nằm trong tầm nhìn`, JSON.stringify({ last: r.last, visible: r.lastVisible }));
  check(r.scrollable && r.lastVisible, `${tag} 4. khung chat vẫn cuộn được và đang ở đáy`, JSON.stringify({ scrollable: r.scrollable, visible: r.lastVisible }));
  await page.reload();
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1200);
  const fresh = await page.evaluate(() => document.querySelectorAll("#chat-history .chat-bubble").length);
  check(fresh <= 1, `${tag} 5. tải lại trang là phiên chat mới, khung chat trống (mỗi phiên một cuộc riêng)`, `${fresh} bong bóng`);
  await browser.close();
}

(async () => {
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  await run("iPhone 390", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
