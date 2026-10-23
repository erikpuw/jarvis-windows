// E2E: thanh bên phiên (máy tính) và ngăn kéo phiên (iPhone): nạp, đổi, tạo phiên; khóa khi LLM hoặc TTS đang chạy (spec §7).
//  6a. 1280×800: thanh bên hiện "＋ Phiên mới", 3 phiên dưới Hôm nay/Hôm qua/Cũ hơn, "⚙ Bảng điều khiển" ở đáy
//  6b. mở app: lớp chào hiện, không có thêm dòng phiên
//  6c. bấm phiên web-bbbb0002: WS mang session=, khung chat có 2 tin, dòng đó được tô sáng
//  6d. bấm "＋ Phiên mới": khung chat trống, lớp chào hiện, WS kế tiếp không có session=
//  6e. đang có lượt chạy: bấm phiên khác / Phiên mới không làm gì (không nối lại, không gửi cancel, dòng không đổi kiểu);
//      LLM idle rồi TTS speaking vẫn khóa; TTS idle thì bấm phiên là đổi được
//  6f. 390×844: thanh bên ẩn; nút ngôi nhà mở ngăn kéo; chọn phiên thì đóng
//  6g. "⚙ Bảng điều khiển" mở menu Bảng điều khiển (.sd-nav); trước đó menu không đứng ở cột trái
//  6j. socket rớt giữa lượt chạy: nối lại cùng phiên thì mở khóa và tải lại lịch sử
// WebSocket và /api bị mock. Chạy: PW=<module playwright> BASE_URL=http://localhost:5174/ node frontend/e2e/sessions-sidebar.cjs
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5174/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const nowSec = Date.now() / 1000;
const yesterdaySec = (() => { const d = new Date(); d.setDate(d.getDate() - 1); d.setHours(12, 0, 0, 0); return d.getTime() / 1000; })();
const olderSec = (() => { const d = new Date(); d.setDate(d.getDate() - 10); d.setHours(12, 0, 0, 0); return d.getTime() / 1000; })();
const ROWS = [
  { session_id: "web-bbbb0002", title: "Giá vàng SJC hôm nay", started_at: olderSec, last_msg: nowSec, msg_count: 2 },
  { session_id: "web-cccc0003", title: "Lịch chiếu phim cuối tuần", started_at: yesterdaySec, last_msg: yesterdaySec, msg_count: 4 },
  { session_id: "web-dddd0004", title: "Công thức phở bò", started_at: olderSec, last_msg: olderSec, msg_count: 6 },
];
const HISTORY = [
  { id: 1, role: "user", content: "Giá vàng SJC hôm nay?", created_at: nowSec },
  { id: 2, role: "assistant", content: "Vàng SJC hôm nay mua vào 84,5 triệu, bán ra 86,5 triệu.", created_at: nowSec },
];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  // đã đăng nhập (cổng auth-gate không chặn việc mở WebSocket)
  await page.addInitScript(() => localStorage.setItem("jarvis_token", "tok-sessions-sidebar"));

  const urls = [];
  const socks = [];
  const frames = [];
  await page.routeWebSocket(/\/ws/, (ws) => {
    const n = urls.length;
    urls.push(ws.url());
    socks.push(ws);
    ws.onMessage((m) => frames.push({ n, text: String(m) }));
    // mock: server cấp đúng ID đang xin, hoặc web-aaaa0001 cho phiên mới. Trì hoãn 300 ms vì gửi ngay lúc tạo có thể bị mất.
    const asked = new URL(ws.url()).searchParams.get("session") || "web-aaaa0001";
    setTimeout(() => ws.send(JSON.stringify({ type: "session", id: asked })), 300);
  });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: { success: true, user: { id: "admin", username: "admin", display_name: "Admin", role: "admin" } } }));
  await page.route(/\/api\/sessions\/mine(\?.*)?$/, (r) => r.fulfill({ json: { success: true, sessions: ROWS } }));
  let histFetches = 0; // GETs of the web-bbbb0002 history (checked in 6c and 6i)
  await page.route(/\/api\/sessions\/mine\/web-bbbb0002(\?.*)?$/, (r) => { histFetches++; r.fulfill({ json: { success: true, messages: HISTORY } }); });

  const until = async (cond, ms = 6000) => {
    for (let t = 0; t < ms; t += 100) { if (await cond()) return true; await page.waitForTimeout(100); }
    return cond();
  };
  const sid = (u) => new URL(u).searchParams.get("session");
  const bubbles = () => page.$$eval("#chat-history .chat-bubble", (els) => els.map((e) => e.textContent));
  const rowStyle = (id) => page.$eval(`.sess-row[data-id="${id}"]`, (el) => {
    const s = getComputedStyle(el);
    return { opacity: s.opacity, color: s.color, visibility: s.visibility, cursor: s.cursor };
  });

  await page.goto(BASE);
  await until(() => urls.length >= 1);
  await until(() => page.$(".sess-row[data-id='web-bbbb0002']").then((el) => !!el));

  // 6a
  const side = await page.evaluate(() => {
    const el = document.getElementById("sessions");
    if (!el) return null;
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    const groups = [...el.querySelectorAll(".sess-group")].map((g) => g.textContent.trim());
    const rows = [...el.querySelectorAll(".sess-row")].map((b) => b.textContent.trim());
    const dash = document.getElementById("sessions-dash");
    const dashBottom = dash ? dash.getBoundingClientRect().bottom : 0;
    const lowest = Math.max(...[...el.querySelectorAll("button, .sess-group")].map((b) => b.getBoundingClientRect().bottom));
    return {
      visible: cs.display !== "none" && cs.visibility !== "hidden" && r.width > 0 && r.right > 0,
      newText: (document.getElementById("sessions-new")?.textContent || "").trim(),
      groups, rows,
      dashText: (dash?.textContent || "").trim(),
      dashAtBottom: dashBottom >= lowest - 1,
    };
  });
  check(side && side.visible, "6a. thanh bên hiện trên máy tính 1280×800", JSON.stringify(side && { visible: side.visible }));
  check(side && side.newText.includes("Phiên mới"), "6a. nút ＋ Phiên mới ở trên", side && side.newText);
  check(side && JSON.stringify(side.groups) === JSON.stringify(["Hôm nay", "Hôm qua", "Cũ hơn"]), "6a. nhóm Hôm nay / Hôm qua / Cũ hơn", side && JSON.stringify(side.groups));
  check(side && side.rows.length === 3 && side.rows[0].includes("Giá vàng SJC") && side.rows[1].includes("Lịch chiếu phim") && side.rows[2].includes("Công thức phở"), "6a. ba tên phiên dưới đúng nhóm", side && JSON.stringify(side.rows));
  check(side && side.dashText.includes("Bảng điều khiển") && side.dashAtBottom, "6a. ⚙ Bảng điều khiển ở đáy thanh bên", side && side.dashText);

  // 6b
  const welcomeOpen = await page.evaluate(() => { const w = document.getElementById("welcome"); return !!w && !w.classList.contains("gone"); });
  const rowCount = await page.$$eval(".sess-row", (els) => els.length);
  check(welcomeOpen && rowCount === 3, "6b. lớp chào hiện khi mở, không có thêm dòng phiên", `welcome=${welcomeOpen} rows=${rowCount}`);

  // 6c
  await page.click(".sess-row[data-id='web-bbbb0002']");
  await until(() => urls.length >= 2);
  await until(async () => (await bubbles()).length === 2);
  const shown = await bubbles();
  const activeId = await page.evaluate(() => document.querySelector(".sess-row.on")?.getAttribute("data-id") || "");
  check(urls.length >= 2 && sid(urls[urls.length - 1]) === "web-bbbb0002", "6c. WS mang session=web-bbbb0002", urls[urls.length - 1]);
  check(shown.length === 2 && shown[0].includes("Giá vàng SJC") && shown[1].includes("84,5"), "6c. khung chat hiện 2 tin của phiên", JSON.stringify(shown));
  check(activeId === "web-bbbb0002", "6c. dòng phiên đang mở được tô sáng", activeId);
  check(histFetches === 1, "6c. chọn phiên: lịch sử tải đúng một lần", `fetches=${histFetches}`);

  // 6d
  await page.click("#sessions-new");
  await until(() => urls.length >= 3);
  await until(async () => (await bubbles()).length === 0);
  // the dismissed layer fades for 450 ms before it leaves the DOM: wait for the new one, not the old one
  const welcomeAgain = await until(() => page.evaluate(() => !!document.querySelector("#welcome:not(.gone)")));
  check(urls.length >= 3 && !sid(urls[urls.length - 1]), "6d. WS kế tiếp không có session=", urls[urls.length - 1]);
  check((await bubbles()).length === 0 && welcomeAgain, "6d. khung chat trống, lớp chào hiện");
  // a new session starts like the boot: the orb is off (the button locked) until its first message
  const orbOff = await page.evaluate(() => document.getElementById("orb-canvas")?.dataset.backend === "off" && document.getElementById("btn-orb-toggle").disabled);
  check(orbOff, "6d. Phiên mới: orb tắt và nút orb khóa như lúc mở app", String(orbOff));

  // 6e: có lượt đang chạy (LLM nghĩ, bong bóng đang gõ)
  await until(() => socks.length >= 3);
  await page.waitForTimeout(400);
  const cur = socks[socks.length - 1];
  const before = await rowStyle("web-cccc0003");
  const urlsBefore = urls.length;
  const cancelsBefore = frames.filter((f) => f.text.includes('"cancel"')).length;
  cur.send(JSON.stringify({ type: "status", state: "thinking", message: "Đang nghĩ…" }));
  cur.send(JSON.stringify({ type: "stream_start" }));
  cur.send(JSON.stringify({ type: "text_chunk", text: "Đang tra cứu giá vàng" }));
  await page.waitForTimeout(400);
  await page.click(".sess-row[data-id='web-cccc0003']", { force: true });
  await page.click("#sessions-new", { force: true });
  await page.waitForTimeout(500);
  await page.mouse.move(1000, 700);
  await page.waitForTimeout(100);
  const during = await rowStyle("web-cccc0003");
  const cancelsAfter = frames.filter((f) => f.text.includes('"cancel"')).length;
  const streaming = (await bubbles()).some((t) => t.includes("Đang tra cứu"));
  const locked = await page.evaluate(() => document.getElementById("sessions")?.classList.contains("locked") === true);
  check(urls.length === urlsBefore, "6e. đang chạy: bấm phiên và Phiên mới không nối lại WS", `${urlsBefore} → ${urls.length}`);
  check(cancelsAfter === cancelsBefore, "6e. đang chạy: không gửi cancel");
  check(streaming, "6e. đang chạy: khung chat giữ bong bóng đang gõ");
  check(JSON.stringify({ o: before.opacity, c: before.color, v: before.visibility }) === JSON.stringify({ o: during.opacity, c: during.color, v: during.visibility }) && during.cursor === "not-allowed",
    "6e. dòng phiên không đổi opacity/màu/hiện, con trỏ not-allowed", `${JSON.stringify(before)} → ${JSON.stringify(during)}`);
  check(locked, "6e. thanh bên có class locked khi đang chạy");

  cur.send(JSON.stringify({ type: "status", state: "idle" }));
  await page.waitForTimeout(300);
  cur.send(JSON.stringify({ type: "status", state: "speaking", source: "tts", message: "Đang đọc…" }));
  await page.waitForTimeout(300);
  const urlsTts = urls.length;
  await page.click(".sess-row[data-id='web-cccc0003']", { force: true });
  await page.waitForTimeout(400);
  check(urls.length === urlsTts && await page.evaluate(() => document.getElementById("sessions")?.classList.contains("locked") === true),
    "6e. LLM đã idle nhưng TTS đang đọc: vẫn khóa", `${urlsTts} → ${urls.length}`);

  cur.send(JSON.stringify({ type: "status", state: "idle", source: "tts" }));
  await page.waitForTimeout(400);
  await page.click(".sess-row[data-id='web-cccc0003']");
  await until(() => urls.length > urlsTts);
  check(urls.length > urlsTts && sid(urls[urls.length - 1]) === "web-cccc0003", "6e. TTS idle: bấm phiên đổi được, WS mang session=web-cccc0003",
    urls[urls.length - 1]);

  // 6h: the sentence audio ends AFTER the TTS idle packet: the rows stay locked while it plays and unlock once it has finished
  const wav = (() => { // 2 s of silence, mono 16-bit 8 kHz WAV (decodeAudioData reads it)
    const n = 8000 * 2 * 2, b = Buffer.alloc(44 + n);
    b.write("RIFF", 0); b.writeUInt32LE(36 + n, 4); b.write("WAVE", 8); b.write("fmt ", 12); b.writeUInt32LE(16, 16);
    b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(8000, 24); b.writeUInt32LE(16000, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34);
    b.write("data", 36); b.writeUInt32LE(n, 40);
    return b.toString("base64");
  })();
  const sock6h = socks[socks.length - 1];
  const lockedNow = () => page.evaluate(() => document.getElementById("sessions")?.classList.contains("locked") === true);
  sock6h.send(JSON.stringify({ type: "status", state: "thinking", message: "Đang nghĩ…" }));
  await page.waitForTimeout(300);
  sock6h.send(JSON.stringify({ type: "status", state: "idle" }));
  sock6h.send(JSON.stringify({ type: "status", state: "speaking", source: "tts", message: "Đang đọc…" }));
  sock6h.send(JSON.stringify({ type: "audio", data: wav }));
  await page.waitForTimeout(400);
  sock6h.send(JSON.stringify({ type: "status", state: "idle", source: "tts" }));
  await page.waitForTimeout(500);
  const lockedWhilePlaying = await lockedNow();
  await page.waitForTimeout(3000);
  const lockedAfterAudio = await lockedNow();
  check(lockedWhilePlaying && !lockedAfterAudio, "6h. TTS idle đến trước, audio còn phát: vẫn khóa; audio hết thì mở khóa",
    `playing=${lockedWhilePlaying} afterAudio=${lockedAfterAudio}`);

  // 6i: a reconnect of the same session (the socket drops, the page comes back with the same id) draws the history again, so a
  // reply made while it was down shows up; the pick itself drew it once (6c)
  const f0 = histFetches, urls0 = urls.length;
  await page.click(".sess-row[data-id='web-bbbb0002']");
  await until(() => histFetches === f0 + 1);
  await page.waitForTimeout(600);
  const pickFetches = histFetches - f0;
  HISTORY.push({ id: 3, role: "assistant", content: "Tin trả lời đến lúc đang rớt mạng" });
  socks[socks.length - 1].close();
  await until(() => histFetches === f0 + 2 && urls.length > urls0 + 1);
  await until(async () => (await bubbles()).some((t) => t.includes("rớt mạng")));
  const reconnect = urls[urls.length - 1] || "";
  const shownNew = (await bubbles()).some((t) => t.includes("rớt mạng"));
  check(pickFetches === 1 && histFetches === f0 + 2 && shownNew && sid(reconnect) === "web-bbbb0002",
    "6i. chọn phiên tải lịch sử một lần; rớt mạng rồi nối lại cùng phiên thì tải lại và hiện tin mới",
    `pick=${pickFetches} total=${histFetches - f0} url=${sid(reconnect)}`);

  // 6j: the socket drops in the middle of a turn: the new socket never gets that turn's idle, so the rows must unlock anyway and the
  // history is drawn again (the reply that was cut off shows up with the rest of the session)
  const sock6j = socks[socks.length - 1];
  sock6j.send(JSON.stringify({ type: "status", state: "thinking", message: "Đang nghĩ…" }));
  sock6j.send(JSON.stringify({ type: "stream_start" }));
  sock6j.send(JSON.stringify({ type: "text_chunk", text: "Đang trả lời dở" }));
  const lockedMidTurn = await until(() => lockedNow());
  const f6j = histFetches, urls6j = urls.length;
  HISTORY.push({ id: 4, role: "assistant", content: "Tin sau khi nối lại sau khi rớt mạng" });
  sock6j.close();
  await until(() => urls.length > urls6j && histFetches === f6j + 1);
  await until(async () => (await bubbles()).some((t) => t.includes("sau khi nối lại")));
  const unlockedAfterDrop = !(await lockedNow());
  const cursorAfterDrop = (await rowStyle("web-cccc0003")).cursor;
  check(lockedMidTurn && unlockedAfterDrop && cursorAfterDrop !== "not-allowed" && sid(urls[urls.length - 1]) === "web-bbbb0002",
    "6j. rớt mạng giữa lượt chạy: nối lại thì mở khóa phiên, lịch sử tải lại",
    `locked=${lockedMidTurn} unlocked=${unlockedAfterDrop} cursor=${cursorAfterDrop} fetches=${histFetches - f6j}`);

  // 6g: menu Dashboard không đứng ở cột trái nữa; bấm ⚙ Bảng điều khiển mới mở nó
  const navBefore = await page.evaluate(() => { const n = document.querySelector(".sd-nav"); const cs = getComputedStyle(n); return cs.display !== "none" && n.getBoundingClientRect().width > 0; });
  check(!navBefore, "6g. menu Dashboard không hiện sẵn trên màn chính");
  // 6k: khung phiên cùng chỗ, cùng cỡ, cùng kiểu khung với menu Bảng điều khiển (user 2026-10-23)
  const frame = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s), r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return { left: Math.round(r.left), top: Math.round(r.top), bottom: Math.round(r.bottom), width: Math.round(r.width),
      radius: cs.borderTopLeftRadius, bg: cs.backgroundColor, border: cs.borderTopColor };
  }, sel);
  const sessFrame = await frame("#sessions");
  // 6n: PC collapse folds the panel to a 60px icon rail like the Dashboard menu (user 2026-10-23), it does not vanish
  const rail = () => page.evaluate(() => {
    const s = document.getElementById("sessions"), r = s.getBoundingClientRect(), vis = (el) => !!el && getComputedStyle(el).display !== "none" && el.getBoundingClientRect().width > 0;
    return { shown: getComputedStyle(s).visibility !== "hidden" && r.right > 0, width: Math.round(r.width), left: Math.round(r.left),
      toggle: vis(document.getElementById("sessions-collapse")), newBtn: vis(document.getElementById("sessions-new")),
      dash: vis(document.getElementById("sessions-dash")), rows: vis(document.querySelector(".sess-row")) };
  });
  await page.click("#sessions-collapse");
  await page.waitForTimeout(400);
  const folded = await rail();
  check(folded.shown && folded.width === 60 && folded.left === 16 && folded.toggle && folded.newBtn && folded.dash,
    "6n. thu gọn trên PC: còn cột icon 60px (mở rộng, Phiên mới, Bảng điều khiển)", JSON.stringify(folded));
  // each chat stays in the rail as a bare chat icon (user 2026-10-23): no frame, no group label, no title text; the open one is lit
  const railRows = await page.evaluate(() => [...document.querySelectorAll(".sess-row")].map((b) => {
    const cs = getComputedStyle(b), label = b.querySelector(".sess-label"), icon = b.querySelector("svg");
    return { id: b.dataset.id, icon: !!icon && icon.getBoundingClientRect().width > 0, text: !!label && label.getBoundingClientRect().width > 0,
      bg: cs.backgroundColor, border: cs.borderTopWidth, color: cs.color, title: b.title };
  }));
  const groupsShown = await page.evaluate(() => [...document.querySelectorAll(".sess-group")].some((g) => g.getBoundingClientRect().width > 0));
  const lit = railRows.find((r) => r.id === "web-bbbb0002"), dim = railRows.find((r) => r.id !== "web-bbbb0002");
  check(railRows.length === 3 && railRows.every((r) => r.icon && !r.text && r.bg === "rgba(0, 0, 0, 0)" && r.border === "0px" && r.title) && !groupsShown
    && lit && dim && lit.color !== dim.color,
    "6n. thu gọn: mỗi phiên là icon chat trần (không khung, không chữ, có tên khi rê chuột), phiên đang mở sáng hơn", JSON.stringify({ railRows, groupsShown }));
  await page.click("#sessions-collapse");
  await page.waitForTimeout(400);
  const unfolded = await rail();
  check(unfolded.width === 200 && unfolded.rows, "6n. bấm lại: thanh phiên mở rộng 200px", JSON.stringify(unfolded));
  // 6l: the panel lies over the screen like the Dashboard menu did: the command bar stays centred (user 2026-10-23)
  const barCentre = await page.evaluate(() => { const r = document.getElementById("command-container").getBoundingClientRect(); return Math.round(r.left + r.width / 2); });
  check(Math.abs(barCentre - 640) <= 1, "6l. thanh phiên không đẩy màn chính: thanh lệnh vẫn giữa màn", `centre=${barCentre}`);
  await page.click("#sessions-dash");
  await page.waitForTimeout(400);
  const navAfter = await page.evaluate(() => { const n = document.querySelector(".sd-nav"); const cs = getComputedStyle(n); return cs.display !== "none" && cs.visibility !== "hidden" && n.getBoundingClientRect().width > 0; });
  check(navAfter, "6g. ⚙ Bảng điều khiển mở menu (.sd-nav) hiện");
  const navFrame = await frame(".sd-nav");
  check(JSON.stringify(sessFrame) === JSON.stringify(navFrame), "6k. khung phiên trùng menu Bảng điều khiển (vị trí, cỡ, bo góc, nền, viền)",
    `sessions=${JSON.stringify(sessFrame)} nav=${JSON.stringify(navFrame)}`);

  // 6f: iPhone 390×844
  const phoneCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await phoneCtx.addInitScript(() => localStorage.setItem("jarvis_token", "tok-sessions-sidebar"));
  const phone = await phoneCtx.newPage();
  const phoneUrls = [];
  await phone.routeWebSocket(/\/ws/, (ws) => {
    phoneUrls.push(ws.url());
    const asked = new URL(ws.url()).searchParams.get("session") || "web-aaaa0001";
    setTimeout(() => ws.send(JSON.stringify({ type: "session", id: asked })), 300);
  });
  await phone.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await phone.route("**/api/auth/me", (r) => r.fulfill({ json: { success: true, user: { id: "admin", username: "admin", display_name: "Admin", role: "admin" } } }));
  await phone.route(/\/api\/sessions\/mine(\?.*)?$/, (r) => r.fulfill({ json: { success: true, sessions: ROWS } }));
  await phone.goto(BASE);
  await phone.waitForTimeout(1500);
  const hidden = await phone.evaluate(() => { const el = document.getElementById("sessions"); if (!el) return false; const r = el.getBoundingClientRect(); return getComputedStyle(el).visibility === "hidden" || r.right <= 0; });
  check(hidden, "6f. 390×844: thanh bên ẩn");
  await phone.click("#settings-menu-toggle");
  await phone.waitForTimeout(500);
  const drawer = await phone.evaluate(() => {
    const el = document.getElementById("sessions");
    const r = el.getBoundingClientRect();
    return { open: getComputedStyle(el).visibility !== "hidden" && r.right > 0, width: Math.round(r.width), left: Math.round(r.left),
      top: Math.round(r.top), radius: getComputedStyle(el).borderTopLeftRadius };
  });
  // the same frame as the Dashboard menu drawer at its full (named) width: 200px, 12px from the left, under the island
  check(drawer.open && drawer.width === 200 && drawer.left === 12 && drawer.radius === "12px",
    "6f. nút ngôi nhà mở ngăn kéo (khung như menu Bảng điều khiển, 200px)", JSON.stringify(drawer));
  await phone.click(".sess-row[data-id='web-cccc0003']");
  await phone.waitForTimeout(500);
  const closed = await phone.evaluate(() => { const el = document.getElementById("sessions"); const r = el.getBoundingClientRect(); return getComputedStyle(el).visibility === "hidden" || r.right <= 0; });
  check(closed, "6f. chọn một phiên thì ngăn kéo đóng");

  // 6m: on a phone the Dashboard keeps a way back to its menu (user 2026-10-23): while it is open the home button's place holds a
  // gear that opens the menu drawer; closed again, the button is the house (sessions); reopening lands on the page left last
  const btn = () => phone.evaluate(() => {
    const b = document.getElementById("settings-menu-toggle"), r = b.getBoundingClientRect();
    return { shown: getComputedStyle(b).display !== "none" && r.width > 0, title: b.title, left: Math.round(r.left), top: Math.round(r.top),
      nav: document.getElementById("settings-panel-inner").classList.contains("nav-open"),
      page: document.querySelector('.sd-nav-item[aria-current="page"]')?.dataset.page || "" };
  });
  await phone.click("#settings-menu-toggle");
  await phone.waitForTimeout(400);
  await phone.click("#sessions-dash");
  await phone.waitForTimeout(600);
  await phone.evaluate(() => document.querySelector('.sd-nav-item[data-page="voice"]').click());
  await phone.waitForTimeout(600);
  const onPage = await btn();
  check(onPage.shown && !onPage.nav && onPage.title === "Bảng điều khiển" && onPage.left === 12,
    "6m. đang xem trang: nút bánh răng ở chỗ nút nhà, menu đã đóng", JSON.stringify(onPage));
  await phone.click("#settings-menu-toggle");
  await phone.waitForTimeout(500);
  const menuBack = await btn();
  check(menuBack.nav && menuBack.page === "voice", "6m. bấm bánh răng: menu Bảng điều khiển hiện lại, trang đang xem được tô", JSON.stringify(menuBack));
  await phone.click("#settings-menu-toggle"); // ✕ closes the menu
  await phone.waitForTimeout(400);
  await phone.evaluate(() => document.getElementById("settings-close").click());
  await phone.waitForTimeout(500);
  const home = await btn();
  check(home.shown && home.title === "Phiên chat", "6m. đóng Bảng điều khiển: nút trở lại là nhà (phiên chat)", JSON.stringify(home));
  await phone.click("#settings-menu-toggle");
  await phone.waitForTimeout(400);
  await phone.click("#sessions-dash");
  await phone.waitForTimeout(600);
  const again = await btn();
  check(again.page === "voice", "6m. mở lại Bảng điều khiển: về đúng trang đã xem, không nhảy về Tổng quan", JSON.stringify(again));
  await phoneCtx.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
