// E2E: Settings → Nhật ký, tab Lịch sử chat chỉ dành cho admin. Không còn "Toàn bộ"; danh sách phiên ghi tên phiên và chủ phiên,
//  có bộ lọc theo người dùng; khung đọc chỉ xem, không có ô gửi/tiếp tục. Thành viên không thấy mục Nhật ký trong Bảng điều khiển.
//  7a. admin: không có nút "Toàn bộ"; mỗi dòng có tên phiên (title) và chủ phiên (user_name)
//  7b. admin: bộ lọc người dùng liệt kê "Tất cả" và từng người; chọn u1 gọi lại với user=u1 và chỉ hiện phiên của u1
//  7c. admin: bấm một phiên mở khung đọc (tin nhắn), không có nút gửi/tiếp tục
//  7d. thành viên: menu Bảng điều khiển không có mục Nhật ký
//  7e. danh sách (ul/ol) trong tin đọc lại nằm trong bong bóng: dấu chấm không lòi ra ngoài mép (reset * { padding: 0 }, 2026-10-23)
// Backend giả. Chạy: PW=<module playwright> BASE_URL=http://localhost:5174/ node frontend/e2e/logs-sessions.cjs
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5174/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const USERS = [{ id: "u1", name: "Minh" }, { id: "u2", name: "Lan" }];
const ROWS = [
  { session_id: "web-aaaa0001", source: "web", device: "desktop", msg_count: 2, started_at: 1790000000, last_msg: 1790000500, user_id: "u1", user_name: "Minh", title: "Giá vàng SJC hôm nay" },
  { session_id: "web-bbbb0002", source: "web", device: "ios", msg_count: 4, started_at: 1790000100, last_msg: 1790000400, user_id: "u2", user_name: "Lan", title: "Công thức phở bò" },
  { session_id: "web-cccc0003", source: "web", msg_count: 6, started_at: 1790000200, last_msg: 1790000300, user_id: "admin", user_name: "Admin", title: "Lịch chiếu phim cuối tuần" },
];
const MESSAGES = [
  { id: 1, role: "user", content: "Giá vàng SJC hôm nay?", created_at: 1790000000 },
  { id: 2, role: "assistant", content: "Vàng SJC hôm nay:\n\n- **Mua vào:** 84,5 triệu\n- **Bán ra:** 86,5 triệu\n\nTóm lại giá tăng.", created_at: 1790000010 },
];

async function open(browser, user) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await ctx.addInitScript((u) => {
    localStorage.setItem("jarvis_token", "tok-logs-sessions");
    localStorage.setItem("jarvis_user", JSON.stringify(u));
  }, user);
  const listRequests = [];
  const detailRequests = [];
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: { success: true, user: { ...user, username: user.id } } }));
  await page.route("**/api/settings/status**", (r) => r.fulfill({ json: { success: true, server_engine_ok: true, system: {}, env_keys_set: { llama: true } } }));
  await page.route("**/api/memory-control/summary", (r) => r.fulfill({ json: { success: true, counts: {} } }));
  await page.route(/\/api\/conversations\/sessions(\?.*)?$/, (r) => {
    const user = new URL(r.request().url()).searchParams.get("user") || "";
    listRequests.push(user);
    const rows = user ? ROWS.filter((s) => s.user_id === user) : ROWS;
    r.fulfill({ json: { success: true, sessions: rows, users: USERS } });
  });
  await page.route(/\/api\/conversations\/session\/[^?]+(\?.*)?$/, (r) => {
    detailRequests.push(decodeURIComponent(r.request().url().split("/session/")[1].split("?")[0]));
    r.fulfill({ json: { success: true, messages: MESSAGES } });
  });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  const go = async (p) => {
    await page.evaluate((x) => document.querySelector(`.sd-nav-item[data-page="${x}"]`)?.click(), p);
    await page.waitForTimeout(600);
  };
  return { ctx, page, go, listRequests, detailRequests };
}

(async () => {
  const browser = await chromium.launch();

  // admin
  {
    const { ctx, page, go, listRequests, detailRequests } = await open(browser, { id: "admin", name: "Admin", role: "admin" });
    await go("overview");
    await go("logs");
    await page.waitForTimeout(800);

    const toanBo = await page.evaluate(() => [...document.querySelectorAll("#page-logs button")].some((b) => b.textContent.trim() === "Toàn bộ") || !!document.querySelector("#page-logs [data-hist-view]"));
    check(!toanBo, "7a. Lịch sử chat không có nút \"Toàn bộ\"");

    await page.waitForSelector(".sd-session-row", { timeout: 4000 }).catch(() => {});
    const rows = await page.$$eval("#history-sessions-list .sd-session-row", (els) => els.map((el) => ({
      id: el.dataset.session,
      title: el.querySelector(".sd-session-title")?.textContent.trim() || "",
      owner: el.querySelector(".sd-session-owner")?.textContent.trim() || "",
    })));
    const first = rows.find((r) => r.id === "web-aaaa0001");
    check(rows.length === 3 && first && first.title === "Giá vàng SJC hôm nay" && first.owner.includes("Minh"),
      "7a. mỗi dòng hiện tên phiên (title) và chủ phiên (user_name)", JSON.stringify(rows));

    const options = await page.$$eval("#history-owner-filter option", (os) => os.map((o) => [o.value, o.textContent.trim()]));
    check(JSON.stringify(options) === JSON.stringify([["", "Tất cả"], ["u1", "Minh"], ["u2", "Lan"]]),
      "7b. bộ lọc người dùng: Tất cả + từng người", JSON.stringify(options));

    const before = listRequests.length;
    await page.selectOption("#history-owner-filter", "u1");
    await page.waitForTimeout(800);
    const reqs = listRequests.slice(before);
    const filtered = await page.$$eval("#history-sessions-list .sd-session-row", (els) => els.map((el) => el.dataset.session));
    check(reqs.includes("u1") && JSON.stringify(filtered) === JSON.stringify(["web-aaaa0001"]),
      "7b. chọn Minh gọi lại với user=u1 và chỉ hiện phiên của u1", JSON.stringify({ reqs, filtered }));

    await page.click('#history-sessions-list .sd-session-row[data-session="web-aaaa0001"]');
    await page.waitForTimeout(800);
    const items = await page.$$eval("#history-settings-list .history-item", (els) => els.length);
    check(items === 2 && detailRequests.includes("web-aaaa0001"), "7c. bấm phiên mở khung đọc tin nhắn", `tin=${items}`);
    const controls = await page.evaluate(() => [...document.querySelectorAll("#page-logs button")].map((b) => b.textContent.trim()).filter((t) => /gửi|tiếp tục|send|continue/i.test(t)));
    check(controls.length === 0, "7c. khung đọc chỉ xem: không có nút gửi/tiếp tục", JSON.stringify(controls));
    const list = await page.evaluate(() => {
      const item = document.querySelector("#history-settings-list .history-item.assistant");
      const ul = item?.querySelector("ul");
      if (!item || !ul) return null;
      const ir = item.getBoundingClientRect(), ur = ul.getBoundingClientRect(), li = ul.querySelector("li").getBoundingClientRect();
      // a disc marker is drawn left of the li box: about 1em must stay inside the bubble's padding box
      return { padLeft: parseFloat(getComputedStyle(ul).paddingLeft), markerRoom: Math.round(li.left - ir.left), ulLeft: Math.round(ur.left - ir.left) };
    });
    check(!!list && list.padLeft > 0 && list.markerRoom >= 20, "7e. danh sách trong tin đọc lại thụt vào trong bong bóng, dấu chấm không lòi ra", JSON.stringify(list));
    await ctx.close();
  }

  // member
  {
    const { ctx, page } = await open(browser, { id: "u1", name: "Minh", role: "member" });
    await page.waitForTimeout(300);
    const menu = await page.evaluate(() => ({
      memory: !!document.querySelector('.sd-nav-item[data-page="memory"]'),
      logs: !!document.querySelector('.sd-nav-item[data-page="logs"]'),
    }));
    check(menu.memory && !menu.logs, "7d. thành viên: Bảng điều khiển không có mục Nhật ký", JSON.stringify(menu));
    await ctx.close();
  }

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
