// E2E: Settings → Nhật ký — MỘT trang gồm bốn tab (Lịch sử chat, Jarvis log, Log bảo mật, Log TTS), khóa bằng cùng mật khẩu với Memory Control.
//  Phiên chat KHÔNG phải tab riêng: nằm trong tab Lịch sử chat (nút phụ "Toàn bộ" / "Phiên chat"). Máy tính: hai khung riêng cạnh nhau (danh sách phiên | nội dung phiên) như Memory Control.
//  Điện thoại: một khung một lúc (danh sách → bấm phiên → khung đọc), nút "← Danh sách phiên chat" cố định trên khung đọc, ẩn bớt tiêu đề để khung đọc rộng.
//  - Nút lịch sử / nhật ký không còn ở màn hình chính; Settings không còn trang "Lịch sử chat" riêng.
//  - Vào Nhật ký: nền mờ + ô mật khẩu; chưa nhập đúng thì không request nào và không có chữ nào của dữ liệu trong trang. Nhập một lần xem được cả bốn tab.
//  - Rời trang là khóa lại và thu hồi token (kể cả đi sang Bộ nhớ: phải nhập lại).
//  - Trang Nhật ký KHÔNG kiểm tra kết nối (/api/settings/status mỗi 5 giây chỉ ở Tổng quan/Hệ thống; mỗi lần kiểm tra ghi thêm một dòng httpx vào jarvis.log). Tab ẩn thì không kiểm tra.
//  - Điện thoại: màn hình khóa không che ngăn kéo điều hướng (mở menu ra vẫn bấm được để rời trang khóa).
//  - Bố cục: thẻ kéo xuống hết khung (đáy bằng đáy sidebar như Bộ nhớ); lịch sử chat là một cột giữa; điện thoại: thanh tab cuộn ngang, nội dung xếp dọc, không tràn ngang.
// Backend giả: các /api/history, /api/logs* trả 401 locked nếu thiếu token đúng. Chạy: PW=<module playwright> node frontend/e2e/settings-protected.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
const PASSWORD = "mat-khau-thu-nghiem", TOKEN = "tok-xyz-789";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const LOGS = ["10:00:00 INFO khoi dong", "10:00:01 ERROR loi <b>nguy hiem</b>", "10:00:02 WARNING " + "y".repeat(400)].join("\n");
const SECURITY = "01:00:00 [INFO] canh bao bao mat so 1\n01:00:05 [WARNING] chan ket noi la";
const TTS = "tts dong 1\ntts dong 2";
const HISTORY = [
  { role: "user", content: "Câu hỏi bí mật", created_at: 1790000000 },
  { role: "assistant", content: "Trả lời bí mật", created_at: 1790000010 },
];
const TABS = ["history", "jarvis", "security", "tts"];

async function open(browser, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ...opts });
  const page = await ctx.newPage();
  await page.clock.install();
  const log = { history: [], logs: [], security: [], tts: [], sessions: [], detail: [], status: 0, lock: [] };
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/settings/status**", (r) => { log.status++; r.fulfill({ json: { success: true, server_engine_ok: true, system: {}, env_keys_set: { llama: true } } }); });
  const gated = (list, body) => (r) => {
    const tok = r.request().headers()["x-memory-token"];
    list.push({ tok, url: r.request().url().replace(/^.*\/api/, "/api") });
    if (tok !== TOKEN) return r.fulfill({ status: 401, json: { detail: "locked" } });
    r.fulfill({ json: body });
  };
  await page.route("**/api/history**", gated(log.history, { success: true, history: HISTORY }));
  await page.route("**/api/logs**", gated(log.logs, { success: true, logs: LOGS }));
  await page.route("**/api/logs/security**", gated(log.security, { success: true, logs: SECURITY }));
  await page.route("**/api/logs/tts**", gated(log.tts, { success: true, logs: TTS }));
  const sessions = { sessions: [
    { session_id: "web-ab12", source: "web", msg_count: 40, started_at: 1790000000, last_msg: 1790000500 },
    { session_id: "tg-77", source: "telegram", msg_count: 2, started_at: 1789000000, last_msg: 1789000100 },
    { session_id: "legacy", source: "legacy", msg_count: 9, started_at: 1780000000, last_msg: 1780000900 } ] };
  const detail = (id) => ({ messages: Array.from({ length: id === "web-ab12" ? 40 : 2 }, (_, i) => ({ id: i, role: i % 2 ? "assistant" : "user", content: `tin ${i} của phiên ${id} dai dai dai dai dai dai dai dai dai dai`, created_at: 1790000000 + i * 10 })) });
  await page.route("**/api/conversations/sessions**", gated(log.sessions, { success: true, ...sessions }));
  await page.route("**/api/conversations/session/**", (r) => {
    const tok = r.request().headers()["x-memory-token"], id = decodeURIComponent(r.request().url().split("/session/")[1].split("?")[0]);
    log.detail.push({ tok, id });
    if (tok !== TOKEN) return r.fulfill({ status: 401, json: { detail: "locked" } });
    r.fulfill({ json: { success: true, ...detail(id) } });
  });
  await page.route("**/api/memory-control/summary", (r) => r.fulfill({ json: { success: true, counts: {} } }));
  await page.route("**/api/memory-lock/status", (r) => r.fulfill({ json: { configured: true } }));
  await page.route("**/api/memory-lock/unlock", (r) => {
    const pw = r.request().postDataJSON().password;
    if (pw !== PASSWORD) return r.fulfill({ status: 401, json: { success: false, code: "wrong_password" } });
    r.fulfill({ json: { success: true, token: TOKEN } });
  });
  await page.route("**/api/memory-lock/lock", (r) => { log.lock.push(r.request().headers()["x-memory-token"]); r.fulfill({ json: { success: true } }); });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(400);
  const go = async (p) => { await page.evaluate((x) => document.querySelector(`.sd-nav-item[data-page="${x}"]`).click(), p); await page.waitForTimeout(600); };
  const enter = async (id, pw) => { await page.fill(`#${id}-lock-input`, pw); await page.click(`#${id}-lock-btn`); await page.waitForTimeout(600); };
  const locked = (id, root) => page.evaluate(([i, r]) => { const o = document.getElementById(`${i}-lock`), p = document.querySelector(r); return !!o && getComputedStyle(o).display !== "none" && p.classList.contains("locked"); }, [id, root]);
  const tab = async (name) => { await page.click(`#logs-category-nav [data-log-tab="${name}"]`); await page.waitForTimeout(500); };
  const shown = () => page.evaluate(() => ({ list: !document.getElementById("history-view").hidden, log: !document.getElementById("logs-content").hidden, active: document.querySelector("#logs-category-nav .active")?.dataset.logTab }));
  return { ctx, page, log, go, enter, locked, tab, shown };
}

// mép dưới thẻ nội dung phải bằng mép dưới khung sidebar (Bộ nhớ và Nhật ký cùng kiểu), ở mọi cỡ màn hình
const edge = (page, root) => page.evaluate((r) => { const c = document.querySelector(r + " .sd-card"), n = document.querySelector("nav.sd-nav"); return { dy: Math.round(Math.abs(c.getBoundingClientRect().bottom - n.getBoundingClientRect().bottom)), card: Math.round(c.getBoundingClientRect().bottom), nav: Math.round(n.getBoundingClientRect().bottom) }; }, root);
const leaked = (page, text) => page.evaluate((t) => document.getElementById("page-logs").innerText.includes(t) || document.getElementById("page-logs").innerHTML.includes(t), text);

(async () => {
  const browser = await chromium.launch();
  const { page, log, go, enter, locked, tab, shown } = await open(browser);

  // 1. màn hình chính không còn nút lịch sử / nhật ký; Settings chỉ có MỘT trang Nhật ký
  const gone = await page.evaluate(() => ({ h: !!document.getElementById("btn-history"), hp: !!document.getElementById("history-panel"), l: !!document.getElementById("btn-logs"), lv: !!document.querySelector(".log-viewer-overlay") }));
  check(!gone.h && !gone.hp && !gone.l && !gone.lv, "1a. màn hình chính không còn nút/panel lịch sử và nút nhật ký", JSON.stringify(gone));
  const navs = await page.$$eval(".sd-nav-item", (n) => n.map((x) => x.dataset.page + ":" + x.textContent.trim()));
  check(navs.some((n) => n === "logs:Nhật ký") && !navs.some((n) => n.startsWith("history")), "1b. Settings có đúng một trang Nhật ký, không còn trang Lịch sử chat riêng", navs.join(", "));

  // 2. khóa
  await go("logs");
  check(await locked("logs", "#page-logs"), "2a. vào Nhật ký → màn hình khóa");
  check(log.history.length + log.logs.length + log.security.length + log.tts.length === 0 && !(await leaked(page, "bí mật")), "2b. chưa nhập mật khẩu: không request nào, không lộ chữ");
  await enter("logs", "sai");
  check((await locked("logs", "#page-logs")) && /Sai mật khẩu/.test(await page.$eval("#logs-lock-msg", (e) => e.textContent)), "2c. sai mật khẩu → vẫn khóa, báo Sai mật khẩu");

  // 3. mở: bốn tab, mặc định Lịch sử chat
  await enter("logs", PASSWORD);
  check(!(await locked("logs", "#page-logs")), "3a. đúng mật khẩu → mở");
  const tabs = await page.$$eval("#logs-category-nav [data-log-tab]", (b) => b.map((x) => x.dataset.logTab + ":" + x.textContent.trim()));
  check(tabs.length === 4 && TABS.every((t) => tabs.some((x) => x.startsWith(t + ":"))) && /Lịch sử chat/.test(tabs[0]) && /Jarvis/i.test(tabs[1]) && /bảo mật/i.test(tabs[2]) && /TTS/.test(tabs[3]), "3b. bốn tab: Lịch sử chat, Jarvis log, Log bảo mật, Log TTS", tabs.join(" | "));
  check((await shown()).active === "history" && (await shown()).list && !(await shown()).log, "3c. mặc định tab Lịch sử chat");
  const items = await page.$$eval("#history-settings-list .history-item", (c) => c.map((x) => x.className + "|" + x.textContent.trim().slice(0, 30)));
  check(items.length === 2 && /user/.test(items[0]) && /assistant/.test(items[1]), "3d. tab Lịch sử: hội thoại người dùng + JARVIS", items.join(" ; "));
  check(log.history.length >= 1 && log.history.every((t) => t.tok === TOKEN), "3e. request lịch sử gửi kèm token", JSON.stringify(log.history));
  check(log.logs.length + log.security.length + log.tts.length === 0, "3f. chỉ tải tab đang xem (chưa gọi các log khác)");

  // 4. chuyển tab: mỗi tab tải đúng nguồn, một lần mở khóa xem được cả bốn
  await tab("jarvis");
  let lines = await page.$$eval("#logs-content .log-line", (c) => c.map((x) => x.className + "|" + x.textContent.slice(0, 40)));
  check((await shown()).log && !(await shown()).list && lines.length === 3 && /error/.test(lines[1]) && /<b>nguy hiem<\/b>/.test(lines[1]) && /warning/.test(lines[2]), "4a. tab Jarvis log: dòng log màu theo mức, dấu < không thành markup", lines.join(" ; "));
  check(log.logs.length >= 1 && log.logs.every((t) => t.tok === TOKEN) && /\/api\/logs\?lines=300/.test(log.logs[0].url), "4b. gọi /api/logs?lines=300 kèm token", JSON.stringify(log.logs[0]));
  await tab("security");
  lines = await page.$$eval("#logs-content .log-line", (c) => c.map((x) => x.textContent));
  check(lines.length === 2 && /canh bao bao mat so 1/.test(lines[0]) && log.security.length >= 1 && log.security[0].tok === TOKEN && /\/api\/logs\/security/.test(log.security[0].url), "4c. tab Log bảo mật: gọi /api/logs/security kèm token", JSON.stringify({ lines, req: log.security[0] }));
  await tab("tts");
  lines = await page.$$eval("#logs-content .log-line", (c) => c.map((x) => x.textContent));
  check(lines.length === 2 && lines[0] === "tts dong 1" && log.tts.length >= 1 && log.tts[0].tok === TOKEN && /\/api\/logs\/tts/.test(log.tts[0].url), "4d. tab Log TTS: gọi /api/logs/tts kèm token", JSON.stringify({ lines, req: log.tts[0] }));
  check(!(await page.evaluate(() => document.getElementById("logs-content").innerText.includes("canh bao bao mat"))), "4e. đổi tab thì nội dung tab trước không còn lẫn vào");
  const before = log.tts.length;
  await page.click("#logs-refresh"); await page.waitForTimeout(500);
  check(log.tts.length === before + 1, "4f. nút Làm mới tải lại đúng tab đang xem", `${before} → ${log.tts.length}`);
  await tab("history");
  check((await shown()).list && (await page.$$("#history-settings-list .history-item")).length === 2, "4g. quay lại tab Lịch sử vẫn đọc được");

  // 4b. Phiên chat nằm TRONG tab Lịch sử chat: khung danh sách phiên riêng + khung đọc nội dung riêng (như Memory Control)
  check(!(await page.$('#logs-category-nav [data-log-tab="sessions"]')), "4h. không có tab \"Phiên chat\" riêng ở thanh tab chính");
  const subs = await page.$$eval("#history-subbar [data-hist-view]", (b) => b.map((x) => x.dataset.histView + ":" + x.textContent.trim() + ":" + x.classList.contains("active")));
  check(subs.length === 2 && /^all:Toàn bộ:true/.test(subs[0]) && /^sessions:Phiên chat:false/.test(subs[1]), "4i. trong tab Lịch sử có nút phụ: Toàn bộ (đang chọn) và Phiên chat", subs.join(" | "));
  check(await page.$eval("#history-sessions-list", (e) => e.hidden), "4j. ở \"Toàn bộ\" chưa có khung danh sách phiên");
  await page.click('#history-subbar [data-hist-view="sessions"]'); await page.waitForTimeout(700);
  const frames = await page.evaluate(() => { const l = document.getElementById("history-sessions-list"), r = document.getElementById("history-settings-list"); const a = l.getBoundingClientRect(), c = r.getBoundingClientRect(); return { listShown: !l.hidden && a.width > 0, readerShown: !r.hidden && c.width > 0, listRight: Math.round(a.right), readerLeft: Math.round(c.left), listW: Math.round(a.width), readerW: Math.round(c.width), listBorder: getComputedStyle(l).borderTopWidth, readerBorder: getComputedStyle(r).borderTopWidth, sameTop: Math.round(a.top) === Math.round(c.top) }; });
  check(frames.listShown && frames.readerShown && frames.listRight <= frames.readerLeft && frames.sameTop && frames.listW <= 420 && frames.readerW >= 500 && frames.listBorder === "1px" && frames.readerBorder === "1px", "4k. nút Phiên chat → hai khung riêng cạnh nhau: danh sách phiên (hẹp, bên trái) và khung đọc nội dung (rộng hơn, bên phải), mỗi khung có viền", JSON.stringify(frames));
  const rows = await page.$$eval("#history-sessions-list .sd-session-row", (b) => b.map((x) => x.textContent.replace(/\s+/g, " ").trim()));
  check(rows.length === 3 && /Web/.test(rows[0]) && /web-ab12/.test(rows[0]) && /40 tin/.test(rows[0]) && /Telegram/.test(rows[1]) && /Cũ/.test(rows[2]), "4l. danh sách phiên có nhãn nguồn (Web / Telegram / Cũ) và số tin", rows.join(" | "));
  check(log.sessions.length >= 1 && log.sessions.every((t) => t.tok === TOKEN), "4m. danh sách phiên gọi kèm token", JSON.stringify(log.sessions));
  const first = await page.evaluate(() => ({ selected: document.querySelector("#history-sessions-list .sd-session-row.selected")?.textContent.includes("web-ab12"), msgs: document.querySelectorAll("#history-settings-list .history-item").length }));
  check(first.selected && first.msgs === 40 && log.detail[0]?.id === "web-ab12" && log.detail[0]?.tok === TOKEN, "4n. máy tính: tự mở phiên mới nhất, dòng được tô chọn, khung đọc hiện đủ 40 tin kèm token", JSON.stringify({ first, d: log.detail[0] }));
  const keep = await page.evaluate(async () => { const l = document.getElementById("history-sessions-list"), r = document.getElementById("history-settings-list"); const t0 = Math.round(l.getBoundingClientRect().top); r.scrollTop = 0; await new Promise((x) => setTimeout(x, 50)); r.scrollTop = r.scrollHeight; await new Promise((x) => setTimeout(x, 50)); return { t0, t1: Math.round(l.getBoundingClientRect().top), scrollable: r.scrollHeight > r.clientHeight + 20, backShown: getComputedStyle(document.getElementById("history-back-btn")).display !== "none" }; });
  check(keep.scrollable && keep.t0 === keep.t1 && !keep.backShown, "4o. máy tính: cuộn khung đọc thì danh sách phiên đứng yên; không cần nút quay lại vì hai khung đều đang hiện", JSON.stringify(keep));
  await page.click('#history-sessions-list .sd-session-row:nth-child(2)'); await page.waitForTimeout(500);
  const second = await page.evaluate(() => ({ selected: document.querySelector("#history-sessions-list .sd-session-row.selected")?.textContent.includes("tg-77"), msgs: document.querySelectorAll("#history-settings-list .history-item").length, rows: document.querySelectorAll("#history-sessions-list .sd-session-row").length }));
  check(second.selected && second.msgs === 2 && second.rows === 3 && log.detail.at(-1)?.id === "tg-77", "4p. chọn phiên Telegram → khung đọc đổi sang 2 tin của tg-77, danh sách phiên giữ nguyên", JSON.stringify({ second, d: log.detail.at(-1) }));
  await page.click('#history-subbar [data-hist-view="all"]'); await page.waitForTimeout(500);
  const all = await page.evaluate(() => ({ list: document.getElementById("history-sessions-list").hidden, msgs: document.querySelectorAll("#history-settings-list .history-item").length, w: Math.round(document.getElementById("history-settings-list").getBoundingClientRect().width) }));
  check(all.list && all.msgs === 2 && all.w <= 900, "4q. bấm Toàn bộ → khung danh sách phiên ẩn, về lịch sử chung (2 tin, cột giữa)", JSON.stringify(all));

  // 5. bố cục: đáy bằng sidebar, lịch sử là một cột giữa
  await page.setViewportSize({ width: 1920, height: 1000 }); await page.waitForTimeout(300);
  const wide = await page.evaluate(() => { const l = document.getElementById("history-settings-list"), c = l.closest(".sd-card"); const r = l.getBoundingClientRect(), b = c.getBoundingClientRect(); const items = [...l.querySelectorAll(".history-item")].map((x) => x.getBoundingClientRect()); return { w: Math.round(r.width), dx: Math.round(Math.abs((r.left + r.right) / 2 - (b.left + b.right) / 2)), maxItem: Math.round(Math.max(...items.map((x) => x.width))) }; });
  check(wide.w <= 900 && wide.dx <= 2 && wide.maxItem <= 760, "5a. màn 1920px: hội thoại là một cột giữa, bong bóng không bè ra", JSON.stringify(wide));
  const e1 = await edge(page, "#page-logs");
  check(e1.dy <= 2, "5b. màn 1920px: đáy thẻ Nhật ký bằng đáy sidebar", JSON.stringify(e1));
  await page.setViewportSize({ width: 1440, height: 900 }); await page.waitForTimeout(300);
  const wideTab = await page.evaluate(() => { const l = document.querySelector("#page-logs .sd-logs-layout").getBoundingClientRect(), p = document.getElementById("card-logs").getBoundingClientRect(); return { pane: Math.round(p.width), layout: Math.round(l.width), ratio: +(p.width / l.width).toFixed(2) }; });
  check(wideTab.ratio >= 0.7, "5d. bảng nội dung rộng ra khi chọn tab (chiếm phần lớn bề ngang, không bị bó như cột danh sách)", JSON.stringify(wideTab));
  const e2 = await edge(page, "#page-logs");
  check(e2.dy <= 2, "5c. màn 1440px: đáy thẻ Nhật ký bằng đáy sidebar", JSON.stringify(e2));

  // 6. rời trang → khóa, thu hồi token; sang Bộ nhớ phải nhập lại; vào lại Nhật ký phải nhập lại, dữ liệu cũ đã xóa
  await go("memory");
  check(log.lock.length >= 1 && log.lock[0] === TOKEN, "6a. rời Nhật ký → thu hồi token", JSON.stringify(log.lock));
  check(await locked("memory", "#page-memory"), "6b. sang Bộ nhớ → phải nhập mật khẩu lại");
  await go("logs");
  check((await locked("logs", "#page-logs")) && !(await leaked(page, "bí mật")) && !(await leaked(page, "canh bao")) && !(await leaked(page, "tts dong")) && !(await leaked(page, "phiên tg-77")) && !(await leaked(page, "web-ab12")), "6c. vào lại Nhật ký → khóa lại, dữ liệu mọi tab đã xóa");
  await enter("logs", PASSWORD);
  check((await shown()).active === "history", "6d. mở lại thì về tab Lịch sử chat");

  // 7. trang Nhật ký không kiểm tra kết nối; Hệ thống vẫn kiểm tra; tab ẩn thì không
  const s0 = log.status;
  await page.clock.fastForward(16000); await page.waitForTimeout(300);
  check(log.status === s0, "7a. trang Nhật ký KHÔNG kiểm tra kết nối (không tự sinh thêm dòng httpx vào log)", `${log.status - s0} request`);
  await go("system");
  const s1 = log.status;
  await page.clock.fastForward(11000); await page.waitForTimeout(300);
  check(log.status - s1 >= 1, "7b. trang Hệ thống vẫn kiểm tra kết nối mỗi 5 giây", String(log.status - s1));
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, get: () => true }); });
  const s2 = log.status;
  await page.clock.fastForward(16000); await page.waitForTimeout(300);
  check(log.status === s2, "7c. tab đang ẩn → không kiểm tra kết nối", `${log.status - s2} request`);
  await page.context().close();

  // 8. điện thoại: thanh tab cuộn ngang, đủ bốn tab, nội dung không tràn ngang
  const m = await open(browser, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await m.go("logs");
  await m.enter("logs", PASSWORD);
  await m.tab("jarvis");
  const mob = await m.page.evaluate(() => {
    const nav = document.getElementById("logs-category-nav"), c = document.getElementById("logs-content"), card = document.getElementById("card-logs");
    return { dir: getComputedStyle(nav).flexDirection, navScroll: nav.scrollWidth, navClient: nav.clientWidth, tabs: nav.querySelectorAll("[data-log-tab]").length, sw: c.scrollWidth, cw: c.clientWidth, ox: getComputedStyle(c).overflowX, card: Math.round(card.getBoundingClientRect().width), doc: document.documentElement.scrollWidth, vw: window.innerWidth };
  });
  check(mob.dir === "row" && mob.tabs === 4 && mob.navScroll >= mob.navClient, "8a. điện thoại: thanh tab nằm ngang (cuộn ngang được), đủ bốn tab", JSON.stringify(mob));
  check(mob.sw <= mob.cw + 1 && mob.ox === "hidden" && mob.card <= mob.vw && mob.doc <= mob.vw, "8b. điện thoại: dòng log dài tự xuống dòng, không tràn ngang", JSON.stringify(mob));
  await m.tab("history");
  await m.page.click('#history-subbar [data-hist-view="sessions"]'); await m.page.waitForTimeout(600);
  const ml = await m.page.evaluate(() => {
    const l = document.getElementById("history-sessions-list"), r = document.getElementById("history-settings-list");
    const row = [...l.querySelectorAll(".sd-session-row")];
    const legacy = row.find((x) => x.textContent.includes("legacy"));
    const id = legacy.querySelector(".sd-session-id"), meta = legacy.querySelector(".sd-session-meta");
    return { listW: Math.round(l.getBoundingClientRect().width), vw: window.innerWidth, readerShown: r.getBoundingClientRect().width > 0 && getComputedStyle(r).display !== "none", rows: row.length, idCut: id.scrollWidth > id.clientWidth + 1, metaBelow: meta.getBoundingClientRect().top >= id.getBoundingClientRect().bottom - 2, head: getComputedStyle(document.querySelector("#page-logs .sd-page-head p")).display, selected: !!l.querySelector(".selected") };
  });
  check(ml.rows === 3 && ml.listW <= ml.vw && !ml.readerShown && !ml.selected, "8d. điện thoại: vào Phiên chat chỉ thấy danh sách phiên (chưa tự mở phiên nào, khung đọc ẩn)", JSON.stringify(ml));
  check(!ml.idCut && ml.metaBelow, "8e. điện thoại: mỗi phiên hai dòng gọn (tên phiên đầy đủ không bị cắt, số tin và giờ ở dòng dưới)", JSON.stringify({ idCut: ml.idCut, metaBelow: ml.metaBelow }));
  check(ml.head === "none", "8f. điện thoại: bỏ đoạn mô tả dài của trang để dành chỗ cho nội dung", ml.head);
  await m.page.click('#history-sessions-list .sd-session-row'); await m.page.waitForTimeout(500);
  const mr = await m.page.evaluate(() => {
    const l = document.getElementById("history-sessions-list"), r = document.getElementById("history-settings-list"), back = document.getElementById("history-back"), btn = document.getElementById("history-back-btn");
    const rr = r.getBoundingClientRect(), bb = back.getBoundingClientRect();
    return { listHidden: getComputedStyle(l).display === "none", readerH: Math.round(rr.height), vh: window.innerHeight, backShown: !back.hidden && getComputedStyle(btn).display !== "none", backTop: Math.round(bb.top), backL: Math.round(bb.left), backR: Math.round(bb.right), vw: window.innerWidth, readerTop: Math.round(rr.top), head: getComputedStyle(document.querySelector("#card-logs .sd-logs-head")).display, tabs: getComputedStyle(document.querySelector("#history-subbar .sd-subtabs")).display, msgs: r.querySelectorAll(".history-item").length };
  });
  check(mr.listHidden && mr.msgs === 40 && mr.backShown && mr.backL >= 0 && mr.backR <= mr.vw && mr.backTop < mr.readerTop, "8g. điện thoại: bấm phiên → khung đọc thay danh sách, nút \"← Danh sách phiên chat\" ngay trên khung đọc", JSON.stringify(mr));
  check(mr.head === "none" && mr.tabs === "none" && mr.readerH >= mr.vh * 0.55, "8h. điện thoại: đang đọc thì ẩn tiêu đề và nút phụ để khung đọc rộng (chiếm trên 55% chiều cao màn hình)", JSON.stringify({ head: mr.head, tabs: mr.tabs, readerH: mr.readerH, vh: mr.vh }));
  const mk = await m.page.evaluate(async () => { const b = document.getElementById("history-back"), r = document.getElementById("history-settings-list"); const t0 = Math.round(b.getBoundingClientRect().top); r.scrollTop = 0; await new Promise((x) => setTimeout(x, 50)); r.scrollTop = r.scrollHeight; await new Promise((x) => setTimeout(x, 50)); return { t0, t1: Math.round(b.getBoundingClientRect().top), scrollable: r.scrollHeight > r.clientHeight + 20 }; });
  check(mk.scrollable && mk.t0 === mk.t1, "8i. điện thoại: cuộn nội dung phiên thì nút quay lại đứng yên", JSON.stringify(mk));
  await m.page.click("#history-back-btn"); await m.page.waitForTimeout(500);
  const mb2 = await m.page.evaluate(() => ({ listShown: getComputedStyle(document.getElementById("history-sessions-list")).display !== "none", readerHidden: getComputedStyle(document.getElementById("history-settings-list")).display === "none", back: document.getElementById("history-back").hidden, head: getComputedStyle(document.querySelector("#card-logs .sd-logs-head")).display }));
  check(mb2.listShown && mb2.readerHidden && mb2.back && mb2.head !== "none", "8j. điện thoại: bấm quay lại → về danh sách phiên, tiêu đề hiện lại", JSON.stringify(mb2));
  await m.tab("tts");
  check((await m.shown()).active === "tts" && (await m.page.$$("#logs-content .log-line")).length === 2, "8c. điện thoại: bấm qua tab Log TTS xem được");
  await m.page.context().close();

  // 9. điện thoại: màn hình khóa KHÔNG được che ngăn kéo điều hướng (trước đây nằm trên sidebar nên mở menu ra không bấm được gì, kẹt ở trang khóa)
  for (const name of ["memory", "logs"]) {
    const d = await open(browser, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    await d.go(name);
    check(await d.locked(name, `#page-${name}`), `9a. [${name}] điện thoại: trang đang khóa`);
    await d.page.click("#settings-menu-toggle"); await d.page.waitForTimeout(500);
    const hit = await d.page.evaluate(() => {
      const item = document.querySelector('.sd-nav-item[data-page="overview"]'), r = item.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { onNav: !!top && !!top.closest("nav.sd-nav"), tag: top ? (top.className || top.tagName).toString().slice(0, 40) : null, inView: r.right > 0 && r.left < window.innerWidth };
    });
    check(hit.inView && hit.onNav, `9b. [${name}] mở ngăn kéo: mục menu nằm trên cùng, không bị màn hình khóa che`, JSON.stringify(hit));
    let clicked = true;
    try { await d.page.click('.sd-nav-item[data-page="overview"]', { timeout: 3000 }); } catch { clicked = false; }
    await d.page.waitForTimeout(500);
    const now = await d.page.evaluate(() => [...document.querySelectorAll(".sd-page")].find((p) => !p.hidden)?.dataset.page);
    check(clicked && now === "overview", `9c. [${name}] bấm được mục Tổng quan trong ngăn kéo và rời khỏi trang khóa`, JSON.stringify({ clicked, now }));
    await d.page.context().close();
  }

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
