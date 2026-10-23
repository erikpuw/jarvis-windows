// E2E: ID phiên chat do SERVER cấp và giữ trong bộ nhớ trang (không còn localStorage).
//  5a. kết nối đầu không có session=
//  5b. server gửi {"type":"session","id":"web-11112222"}; socket nối lại mang session=web-11112222
//  5c. server cấp web-33334444 thay vì ID cũ; socket nối lại kế tiếp mang session=web-33334444
//  5d. tải lại trang thì URL đầu không có session=
//  5e. server đóng với 1008 (token sai) thì không nối lại trong 3 s
// WebSocket và /api bị mock. Chạy: PW=<module playwright> BASE_URL=http://localhost:5174/ node frontend/e2e/ws-session.cjs
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5174/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

// ID mock server cấp cho từng lần kết nối (theo thứ tự kết nối); lần sau đó không gửi gói session
const ASSIGN = ["web-11112222", "web-33334444"];

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
  // đã đăng nhập (cổng auth-gate không chặn việc mở WebSocket). Chỉ gieo token một lần: sau 1008 trang xóa token và tải lại,
  // và lần tải đó phải hiện cổng đăng nhập chứ không tự đăng nhập lại
  await page.addInitScript(() => {
    if (sessionStorage.getItem("seeded")) return;
    sessionStorage.setItem("seeded", "1");
    localStorage.setItem("jarvis_token", "tok-ws-session");
  });
  const urls = [];
  const socks = [];
  await page.routeWebSocket(/\/ws/, (ws) => {
    const n = urls.length;
    urls.push(ws.url());
    socks.push(ws);
    // giới hạn của mock routeWebSocket trong Playwright: gửi ngay lúc tạo có thể bị mất, nên trì hoãn 300 ms (không phải hành vi client)
    if (n < ASSIGN.length) setTimeout(() => ws.send(JSON.stringify({ type: "session", id: ASSIGN[n] })), 300);
  });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: { success: true, user: { id: "u1", username: "erik", display_name: "Erik", role: "member" } } }));
  const until = async (cond, ms = 6000) => {
    for (let t = 0; t < ms; t += 100) { if (cond()) return true; await page.waitForTimeout(100); }
    return cond();
  };
  const sid = (u) => new URL(u).searchParams.get("session");

  await page.goto(BASE);
  await until(() => urls.length >= 1);
  check(urls.length >= 1 && !sid(urls[0]), "5a. kết nối đầu không có session=", urls[0] || "chưa kết nối");

  // 5b: server cấp ID; socket đóng → nối lại mang đúng ID server cấp
  await until(() => socks.length >= 1);
  await page.waitForTimeout(500); // để gói session tới trang
  socks[0].close();
  await until(() => urls.length >= 2);
  check(urls.length >= 2 && sid(urls[1]) === "web-11112222", "5b. nối lại mang session= ID server cấp", `${urls[1] && sid(urls[1])}`);

  // 5c: server cấp ID khác (từ chối ID cũ) → lần nối lại kế tiếp mang ID mới
  await until(() => socks.length >= 2);
  await page.waitForTimeout(500);
  socks[1].close();
  await until(() => urls.length >= 3);
  check(urls.length >= 3 && sid(urls[2]) === "web-33334444", "5c. ID server cấp lần sau thay thế ID cũ", `${urls[2] && sid(urls[2])}`);

  // 5d: tải lại trang → ID trong bộ nhớ mất, URL đầu không có session=
  await page.reload();
  await until(() => urls.length >= 4);
  check(urls.length >= 4 && !sid(urls[3]), "5d. tải lại trang: URL đầu không có session=", urls[3] || "chưa kết nối");

  // 5e: server đóng với 1008 → không có lần nối lại nào trong 3 s
  await until(() => socks.length >= 4);
  await page.waitForTimeout(500);
  const before = urls.length;
  socks[3].close({ code: 1008, reason: "bad token" });
  await page.waitForTimeout(3000);
  check(urls.length === before, "5e. đóng 1008 → không nối lại trong 3 s", `${before} → ${urls.length} lần kết nối`);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
