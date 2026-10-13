// E2E: trang giữ MỘT ID phiên chat khi WebSocket nối lại.
//  Lỗi cũ (iPhone): thoát app thì socket bị ngắt nhưng trang vẫn giữ bong bóng chat; vào lại thì socket nối lại và server cấp ID phiên mới,
//  nên lịch sử trong DB bị tách thành nhiều ID dù trên màn hình là một cuộc trò chuyện.
//  Đúng: mỗi lần mở trang có một ID dạng web-xxxxxxxx gửi kèm URL WebSocket (?session=...); nối lại thì gửi đúng ID đó;
//  mở trang mới / tải lại trang thì ID mới (bong bóng cũ cũng không còn).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/ws-session.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  const urls = [];
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { urls.push(ws.url()); sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  const sid = (u) => new URL(u).searchParams.get("session");
  check(urls.length === 1 && /^web-[0-9a-f]{8}$/.test(sid(urls[0]) || ""), "1. kết nối đầu có ID phiên dạng web-xxxxxxxx", urls[0]);

  // như iPhone thoát app: server thấy socket bị đóng, trang vẫn còn
  await sock.close();
  for (let i = 0; i < 60 && urls.length < 2; i++) await page.waitForTimeout(100);
  check(urls.length >= 2, "2. socket tự nối lại", `${urls.length} lần kết nối`);
  check(urls.length >= 2 && !!sid(urls[0]) && sid(urls[1]) === sid(urls[0]), "3. nối lại gửi ĐÚNG ID phiên cũ (lịch sử không bị tách)", `${sid(urls[0])} → ${urls[1] && sid(urls[1])}`);

  await page.reload();
  for (let i = 0; i < 50 && urls.length < 3; i++) await page.waitForTimeout(100);
  check(urls.length >= 3 && /^web-[0-9a-f]{8}$/.test(sid(urls.at(-1)) || "") && sid(urls.at(-1)) !== sid(urls[0]), "4. tải lại trang thì ID phiên mới", `${sid(urls[0])} → ${sid(urls.at(-1))}`);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
