// E2E: Settings → Bộ nhớ (Memory Control) khóa bằng mật khẩu.
//  Vào trang Bộ nhớ là hiện nền mờ + ô nhập mật khẩu, KHÔNG có dữ liệu nào được tải hay nằm trong trang cho đến khi nhập đúng.
//  Sai bao nhiêu lần cũng được thử lại (không giới hạn). Đúng thì tải danh sách, mọi request dữ liệu gửi kèm token (X-Memory-Token).
//  Rời trang Bộ nhớ hoặc tải lại trang là khóa lại; token không lưu vào localStorage/sessionStorage. Backend trả 401 giữa chừng thì quay về khóa.
//  Chưa đặt MEMORY_PASSWORD trong .env thì báo rõ và không cho nhập.
// Backend giả (/api và /ws bị mock): data endpoint trả 401 locked nếu thiếu token đúng, giống backend thật.
// Chạy: PW=<module playwright> node frontend/e2e/memory-lock.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
const PASSWORD = "mat-khau-thu-nghiem", TOKEN = "tok-123-abc";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, { configured = true } = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const log = { data: [], unlock: [], lock: [], saves: [] };
  const state = { revoked: false };
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  const gated = (body) => async (r) => {
    const tok = r.request().headers()["x-memory-token"];
    log.data.push({ url: r.request().url().replace(/^.*\/api/, "/api"), tok });
    if (tok !== TOKEN || state.revoked) return r.fulfill({ status: 401, json: { detail: "locked" } });
    await r.fulfill({ json: body });
  };
  await page.route("**/api/memory-control/summary", gated({ success: true, counts: {} }));
  await page.route("**/api/learnings/list**", gated({ success: true, total: 1, learnings: [{ id: 7, type: "fact", content: "Bí mật không được lộ khi khóa", importance: 5, created_at: 1790000000 }] }));
  await page.route("**/api/evolution/list**", gated({ success: true, total: 1, items: [{ id: "style", title: "STYLE.md", path: "x", exists: true, editable: true, content: "luật", updated_at: 1790000000 }] }));
  await page.route("**/api/evolution/update", async (r) => { log.saves.push(r.request().headers()["x-memory-token"]); await gated({ success: true })(r); });
  await page.route("**/api/memory-lock/status", (r) => r.fulfill({ json: { configured } }));
  await page.route("**/api/memory-lock/unlock", (r) => {
    const pw = r.request().postDataJSON().password;
    log.unlock.push(pw);
    if (!configured) return r.fulfill({ status: 403, json: { success: false, code: "not_configured" } });
    if (pw !== PASSWORD) return r.fulfill({ status: 401, json: { success: false, code: "wrong_password" } });
    r.fulfill({ json: { success: true, token: TOKEN } });
  });
  await page.route("**/api/memory-lock/lock", (r) => { log.lock.push(r.request().headers()["x-memory-token"]); r.fulfill({ json: { success: true } }); });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(400);
  const go = async (p) => { await page.evaluate((x) => document.querySelector(`.sd-nav-item[data-page="${x}"]`).click(), p); await page.waitForTimeout(600); };
  const enter = async (pw) => { await page.fill("#memory-lock-input", pw); await page.click("#memory-lock-btn"); await page.waitForTimeout(700); };
  const locked = () => page.evaluate(() => { const o = document.getElementById("memory-lock"), p = document.getElementById("page-memory"); return !!o && getComputedStyle(o).display !== "none" && p.classList.contains("locked"); });
  return { page, log, state, go, enter, locked };
}

(async () => {
  const browser = await chromium.launch();
  const { page, log, state, go, enter, locked } = await open(browser);

  // 1. vào Bộ nhớ → khóa, không có dữ liệu
  await go("memory");
  check(await locked(), "1a. vào trang Bộ nhớ là hiện màn hình khóa");
  check(log.data.length === 0, "1b. chưa nhập mật khẩu thì KHÔNG request dữ liệu nào tới backend", JSON.stringify(log.data));
  const hidden = await page.evaluate(() => ({ cards: document.querySelectorAll("#memory-list-container .sd-mem-record-card").length, leaks: document.getElementById("page-memory").innerText.includes("Bí mật"), blur: getComputedStyle(document.querySelector("#page-memory .memory-control-layout")).filter, input: !!document.getElementById("memory-lock-input") }));
  check(hidden.cards === 0 && !hidden.leaks && /blur/.test(hidden.blur) && hidden.input, "1c. trang trống, nền mờ, có ô nhập mật khẩu, không lộ dữ liệu", JSON.stringify(hidden));

  const mid = await page.evaluate(() => { const h = document.querySelector("#memory-lock-form h4"), c = document.getElementById("memory-lock-form"); const r = document.createRange(); r.selectNodeContents(h); const t = r.getBoundingClientRect(), b = c.getBoundingClientRect(); return { dx: Math.abs((t.left + t.right) / 2 - (b.left + b.right) / 2) }; });
  check(mid.dx < 2, "1d. tiêu đề \"đang khóa\" nằm giữa thẻ mật khẩu", JSON.stringify(mid));

  // 2. sai không giới hạn
  for (let i = 0; i < 6; i++) await enter("sai-" + i);
  const msg = await page.$eval("#memory-lock-msg", (e) => e.textContent);
  check((await locked()) && /Sai mật khẩu/.test(msg) && log.unlock.length === 6 && log.data.length === 0, "2a. nhập sai 6 lần vẫn thử lại được, vẫn khóa, báo Sai mật khẩu", msg);
  check(await page.$eval("#memory-lock-input", (e) => !e.disabled && e.value === ""), "2b. ô nhập được xóa sau mỗi lần sai và vẫn bật");

  // 3. đúng → mở, mọi request mang token
  await enter(PASSWORD);
  check(!(await locked()), "3a. nhập đúng → mở khóa");
  const cards = await page.$$eval("#memory-list-container .sd-mem-record-card .sd-mem-card-title", (c) => c.map((x) => x.textContent));
  check(cards.length === 1 && /Bí mật/.test(cards[0]), "3b. danh sách bản ghi hiện ra", cards.join("|"));
  check(log.data.length >= 2 && log.data.every((d) => d.tok === TOKEN), "3c. mọi request dữ liệu gửi kèm token", JSON.stringify(log.data.map((d) => d.tok)));
  await page.click('[data-memory-kind="evolution"]'); await page.waitForTimeout(600);
  await page.click("#memory-save-btn"); await page.waitForTimeout(500);
  check(log.saves.length === 1 && log.saves[0] === TOKEN, "3d. Lưu cũng gửi token", JSON.stringify(log.saves));
  const stored = await page.evaluate((t) => JSON.stringify([localStorage, sessionStorage]).includes(t) || document.cookie.includes(t), TOKEN);
  check(!stored, "3e. token không lưu vào localStorage/sessionStorage/cookie");

  // 4. rời trang → khóa lại, vào lại phải nhập
  await go("overview");
  check(log.lock.length === 1 && log.lock[0] === TOKEN, "4a. rời trang Bộ nhớ → báo backend thu hồi token", JSON.stringify(log.lock));
  const before = log.data.length;
  await go("memory");
  const again = await page.evaluate(() => ({ cards: document.querySelectorAll("#memory-list-container .sd-mem-record-card").length, leaks: document.getElementById("page-memory").innerText.includes("Bí mật") }));
  check((await locked()) && again.cards === 0 && !again.leaks && log.data.length === before, "4b. vào lại Bộ nhớ → khóa lại, dữ liệu cũ đã xóa khỏi trang, không request nào", JSON.stringify(again));

  // 5. 401 giữa chừng → về màn hình khóa
  await enter(PASSWORD);
  check(!(await locked()), "5a. mở khóa lại được");
  state.revoked = true;
  await page.click('[data-memory-kind="learning"]'); await page.waitForTimeout(700);
  const dead = await page.evaluate(() => ({ cards: document.querySelectorAll("#memory-list-container .sd-mem-record-card").length, leaks: document.getElementById("page-memory").innerText.includes("Bí mật") }));
  check((await locked()) && dead.cards === 0 && !dead.leaks, "5b. backend trả 401 locked giữa chừng → quay về màn hình khóa, xóa dữ liệu", JSON.stringify(dead));

  // 6. tải lại trang → khóa
  state.revoked = false;
  await page.reload(); await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("btn-settings").click()); await page.waitForTimeout(400);
  await go("memory");
  check(await locked(), "6. tải lại trang rồi vào Bộ nhớ → phải nhập lại mật khẩu");
  await page.close();

  // 7. chưa cấu hình MEMORY_PASSWORD
  const nc = await open(browser, { configured: false });
  await nc.go("memory");
  const m = await nc.page.evaluate(() => ({ msg: document.getElementById("memory-lock-msg").textContent, dis: document.getElementById("memory-lock-input").disabled }));
  check((await nc.locked()) && /MEMORY_PASSWORD/.test(m.msg) && m.dis && nc.log.data.length === 0, "7. chưa đặt MEMORY_PASSWORD → báo rõ, không cho nhập, không tải dữ liệu", JSON.stringify(m));
  await nc.page.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
