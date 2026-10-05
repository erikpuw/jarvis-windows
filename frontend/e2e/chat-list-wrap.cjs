// E2E: danh sách đánh số / gạch đầu dòng trong câu trả lời của JARVIS không bị bẻ chữ số ("1" xuống dòng rồi "0." như "10.").
//  Trước đây ô số là một <span> trong hàng flex nên bị bóp hẹp khi nội dung dài: "10." gãy thành "1" / "0.", dấu chấm bị đẩy xuống dòng dưới.
//  Giờ ô số/dấu đầu dòng giữ nguyên bề rộng (không co, không gãy), nội dung bên phải xuống dòng bình thường và thụt lề đều.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/chat-list-wrap.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const LONG = "Cung cấp lượng chất xơ và giúp cải thiện tiêu hóa, thường có giá rất phải chăng và rất dễ tìm ở chợ gần nhà.";
const TEXT = [
  "Nhóm Dinh Dưỡng Tốt và Đa Dạng:",
  `6. Cải Bó Xôi: ${LONG}`,
  `9. Mồng Tơi: ${LONG}`,
  `10. Rau Lang: ${LONG}`,
  `12. Hành Lá: ${LONG}`,
  `- Gạch đầu dòng: ${LONG}`,
  "* Sao đầu dòng ngắn",
].join("\n");

async function run(label, opts) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  sock.send(JSON.stringify({ type: "stream_start" })); await page.waitForTimeout(150);
  sock.send(JSON.stringify({ type: "text_chunk", text: TEXT })); await page.waitForTimeout(250);
  sock.send(JSON.stringify({ type: "stream_end" })); await page.waitForTimeout(600);
  const rows = await page.evaluate(() => [...document.querySelectorAll(".chat-bubble.assistant div[style*='display:flex']")].map((row) => {
    const [mark, body] = row.children;
    const m = mark.getBoundingClientRect(), b = body.getBoundingClientRect();
    const range = document.createRange(); range.selectNodeContents(mark);
    return { mark: mark.textContent, markLines: range.getClientRects().length, markH: Math.round(m.height), bodyLines: Math.round(b.height / parseFloat(getComputedStyle(body).lineHeight || "18") || 0), bodyLeft: Math.round(b.left), markW: Math.round(m.width), right: Math.round(b.right), vw: window.innerWidth };
  }));
  const tag = `[${label}]`;
  check(rows.length === 6, `${tag} 1. có đủ 6 dòng danh sách`, JSON.stringify(rows.map((r) => r.mark)));
  const broken = rows.filter((r) => r.markLines > 1);
  check(broken.length === 0, `${tag} 2. ô số / dấu đầu dòng không bị gãy sang dòng dưới (kể cả "10." và "12.")`, JSON.stringify(broken.map((r) => ({ mark: r.mark, lines: r.markLines }))));
  const wide = rows.filter((r) => /^\d+\.$/.test(r.mark));
  const w10 = wide.find((r) => r.mark === "10.");
  const w6 = wide.find((r) => r.mark === "6.");
  check(w10 && w6 && w10.markW > w6.markW, `${tag} 3. "10." rộng hơn "6." (giữ đủ hai chữ số), không bị bóp hẹp`, JSON.stringify({ w6: w6?.markW, w10: w10?.markW }));
  check(rows.every((r) => r.right <= r.vw), `${tag} 4. nội dung không tràn khỏi màn hình`, JSON.stringify(rows.map((r) => r.right)));
  await browser.close();
}

(async () => {
  await run("điện thoại 390px", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
