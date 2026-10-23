// E2E: cổng đăng nhập chỉ đăng xuất khi server trả 401/403.
//  Lỗi cũ: backend restart (503/mất mạng) lúc mở trang làm token bị xóa và hiện màn đăng nhập.
//  Đúng: 401/403 → xóa token, hiện cổng đăng nhập; 5xx/mất mạng → giữ token, thử lại /api/auth/me mỗi 2s, không hiện gì thêm.
// /api và /ws bị mock. Chạy: PW=<module playwright> BASE_URL=http://localhost:5174/ node frontend/e2e/auth-retry.cjs   (cần `npx vite --port 5174` trong frontend/)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
const TOKEN = "tok-retry-123";
const USER = { id: "u1", username: "erik", display_name: "Erik", role: "member" };
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, meStatuses) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await page.addInitScript((tok) => { localStorage.setItem("jarvis_token", tok); }, TOKEN);
  const ws = { opened: 0 };
  await page.routeWebSocket(/\/ws/, () => { ws.opened++; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  const me = { calls: 0 };
  await page.route("**/api/auth/me", (r) => {
    me.calls++;
    const s = meStatuses[Math.min(me.calls - 1, meStatuses.length - 1)];
    if (s === 200) return r.fulfill({ json: { success: true, user: USER } });
    return r.fulfill({ status: s, json: { success: false, error: "x" } });
  });
  await page.goto(BASE);
  return { page, me, ws };
}

(async () => {
  const browser = await chromium.launch();

  // 1. 503 hai lần rồi 200: không hiện cổng, giữ token, app mount.
  {
    const { page, me, ws } = await open(browser, [503, 503, 200]);
    for (let i = 0; i < 100 && ws.opened < 1; i++) await page.waitForTimeout(150);
    const gate = await page.$("#auth-gate-overlay");
    const token = await page.evaluate(() => localStorage.getItem("jarvis_token"));
    check(me.calls >= 3, "1a. thử lại /api/auth/me sau 503", `${me.calls} lần gọi`);
    check(!gate, "1b. không hiện cổng đăng nhập khi server 503");
    check(token === TOKEN, "1c. token còn trong localStorage", String(token));
    check(ws.opened >= 1, "1d. app chạy tiếp sau xác thực (WebSocket mở)", `${ws.opened} kết nối`);
    await page.context().close();
  }

  // 2. 401: hiện cổng đăng nhập và xóa token.
  {
    const { page, me } = await open(browser, [401]);
    await page.waitForSelector("#auth-gate-overlay", { timeout: 15000 }).catch(() => {});
    const gate = await page.$("#auth-gate-overlay");
    const token = await page.evaluate(() => localStorage.getItem("jarvis_token"));
    check(!!gate, "2a. 401 hiện cổng đăng nhập");
    check(token === null, "2b. 401 xóa token", String(token));
    check(me.calls === 1, "2c. 401 không thử lại", `${me.calls} lần gọi`);
    await page.context().close();
  }

  // 3. 404 (server trả rõ, không phải lỗi tạm): hiện cổng đăng nhập và xóa token, không thử lại.
  {
    const { page, me } = await open(browser, [404]);
    await page.waitForSelector("#auth-gate-overlay", { timeout: 15000 }).catch(() => {});
    const gate = await page.$("#auth-gate-overlay");
    const token = await page.evaluate(() => localStorage.getItem("jarvis_token"));
    check(!!gate, "3a. 404 hiện cổng đăng nhập");
    check(token === null, "3b. 404 xóa token", String(token));
    check(me.calls === 1, "3c. 404 không thử lại", `${me.calls} lần gọi`);
    await page.context().close();
  }

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
