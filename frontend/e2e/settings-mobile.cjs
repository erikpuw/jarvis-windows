// E2E: Settings và nhật ký trên điện thoại (390px) phải khoá theo chiều ngang như PC.
//  - Trang "Thông tin" (README): không tràn ngang, bảng/khối mã cuộn TRONG khối của nó, trang không viền (PC = mobile).
//  - Graphfy: vuốt bằng tay kéo xem được bản đồ rộng (không chặn cuộn của trình duyệt), nút kéo thả chỉ dành cho chuột.
//  - Jarvis.log (tab Jarvis log của trang Nhật ký trong Settings, sau mật khẩu): một dòng dài không tạo thanh cuộn ngang, vuốt ngang không làm lệch khung.
// Mọi /api và /ws bị mock; README thật lấy từ README.md. Chạy: PW=<module playwright> node frontend/e2e/settings-mobile.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const README = fs.readFileSync(path.join(__dirname, "..", "..", "README.md"), "utf8");
const MAP = {
  success: true,
  nodes: [
    { id: "server", label: "server", lane: "input" }, { id: "router", label: "router", lane: "turn" },
    { id: "orchestrator", label: "orchestrator", lane: "turn" }, { id: "server/llm_server", label: "llm_server", lane: "llm" },
    { id: "server/voice_streamer", label: "voice_streamer", lane: "output" }, { id: "core/learning", label: "learning", lane: "memory" },
    { id: "core/dream", label: "dream", lane: "background" },
  ],
  edges: [
    { from: "server", to: "router", kind: "import" }, { from: "router", to: "server/llm_server", kind: "llm" },
    { from: "orchestrator", to: "server/voice_streamer", kind: "import" }, { from: "server", to: "core/learning", kind: "import" },
  ],
};
const LOGS = [
  "2026-10-02 10:00:00,1 [jarvis] INFO server started",
  "2026-10-02 10:00:01,2 [jarvis] ERROR " + "x".repeat(420),
  "2026-10-02 10:00:02,3 [jarvis] WARNING https://example.com/" + "a/b/c/".repeat(60),
  "2026-10-02 10:00:03,4 [jarvis] INFO ok",
].join("\n");

async function open(browser, opts) {
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/system/readme", (r) => r.fulfill({ json: { success: true, content: README } }));
  await page.route("**/api/graphfy", (r) => r.fulfill({ json: MAP }));
  await page.route("**/api/logs**", (r) => r.fulfill({ json: { success: true, logs: LOGS } }));
  await page.route("**/api/memory-lock/status", (r) => r.fulfill({ json: { configured: true } }));
  await page.route("**/api/memory-lock/unlock", (r) => r.fulfill({ json: { success: true, token: "t" } }));
  await page.route("**/api/memory-lock/lock", (r) => r.fulfill({ json: { success: true } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  return { page, cdp: await ctx.newCDPSession(page) };
}
const openPage = async (page, id) => {
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(500);
  await page.evaluate((id) => document.querySelector(`.sd-nav-item[data-page="${id}"]`).click(), id);
  await page.waitForTimeout(900);
};
// vuốt bằng sự kiện chạm thật (Input.dispatchTouchEvent): đi qua bộ nhận dạng cử chỉ của trình duyệt như ngón tay thật
const swipe = async (cdp, x, y, dx, dy, steps = 12) => {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  for (let i = 1; i <= steps; i++) { await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + (dx * i) / steps, y: y + (dy * i) / steps }] }); await new Promise((r) => setTimeout(r, 16)); }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
};

(async () => {
  const browser = await chromium.launch();
  const MOBILE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };

  // ── Thông tin ──
  const m = await open(browser, MOBILE);
  await openPage(m.page, "info");
  const info = await m.page.evaluate(() => {
    const v = document.getElementById("readme-viewer"), vw = innerWidth;
    const inScroller = (el) => { for (let p = el.parentElement; p && p !== v; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === "auto" || o === "scroll") return true; } return false; };
    const bad = [...v.querySelectorAll("*")].filter((e) => e.getBoundingClientRect().right > vw + 1 && !inScroller(e)).map((e) => e.tagName.toLowerCase() + (e.className ? "." + String(e.className).split(" ")[0] : ""));
    const wide = [];
    for (let p = v; p; p = p.parentElement) if (p !== document.documentElement && p.scrollWidth > p.clientWidth + 1 && !["auto", "scroll"].includes(getComputedStyle(p).overflowX)) wide.push((p.id || p.className || p.tagName).toString().split(" ")[0]);
    const card = getComputedStyle(document.querySelector(".sd-readme-card"));
    return { doc: document.documentElement.scrollWidth, vw, bad: [...new Set(bad)].slice(0, 5), wide: wide.slice(0, 4), tables: v.querySelectorAll("table").length, card: { bw: card.borderTopWidth, bg: card.backgroundColor, br: card.borderTopLeftRadius } };
  });
  check(info.doc <= info.vw && info.bad.length === 0 && info.wide.length === 0, "1a. mobile: trang Thông tin không tràn ngang (không phần tử nào vượt mép, không khối nào bị đẩy rộng)", JSON.stringify({ doc: info.doc, bad: info.bad, wide: info.wide }));
  const wrapped = await m.page.evaluate(() => [...document.querySelectorAll("#readme-viewer table")].every((t) => { for (let p = t.parentElement; p; p = p.parentElement) { if (p.id === "readme-viewer") return false; const o = getComputedStyle(p).overflowX; if (o === "auto" || o === "scroll") return true; } return false; }));
  check(info.tables > 0 && wrapped, "1b. mobile: mọi bảng markdown cuộn ngang TRONG khối của nó", `${info.tables} bảng`);
  await m.page.context().close();

  const d = await open(browser, { viewport: { width: 1440, height: 900 } });
  await openPage(d.page, "info");
  const card2 = await d.page.evaluate(() => { const c = getComputedStyle(document.querySelector(".sd-readme-card")); return { bw: c.borderTopWidth, bg: c.backgroundColor, br: c.borderTopLeftRadius }; });
  check(info.card.bw === "0px" && card2.bw === "0px" && info.card.bg === "rgba(0, 0, 0, 0)" && card2.bg === "rgba(0, 0, 0, 0)" && info.card.br === "0px" && card2.br === "0px", "1c. trang Thông tin không viền, không nền thẻ — PC và mobile giống nhau", JSON.stringify({ mobile: info.card, pc: card2 }));
  await d.page.context().close();

  // ── Graphfy ──
  const g = await open(browser, MOBILE);
  await openPage(g.page, "graphfy");
  await g.page.waitForSelector(".gf-svg", { timeout: 5000 }).catch(() => {});
  const gf = await g.page.evaluate(() => { const card = document.querySelector(".gf-card"), svg = document.querySelector(".gf-svg"); const r = card.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + 60, scrollW: card.scrollWidth, clientW: card.clientWidth, ta: getComputedStyle(svg).touchAction }; });
  check(gf.scrollW > gf.clientW && gf.ta !== "none", "2a. mobile: bản đồ rộng hơn màn hình và không còn chặn cử chỉ cuộn (touch-action != none)", JSON.stringify(gf));
  await swipe(g.cdp, gf.x + 100, gf.y, -220, 0); await g.page.waitForTimeout(500);
  const moved = await g.page.$eval(".gf-card", (c) => Math.round(c.scrollLeft));
  check(moved > 50, "2b. mobile: vuốt ngang kéo xem được phần bên phải của bản đồ", `scrollLeft=${moved}`);
  const nodePos = () => g.page.$eval(".gf-node", (n) => n.getAttribute("transform"));
  const before = await nodePos();
  const nb = await g.page.$eval(".gf-node", (n) => { const r = n.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  await swipe(g.cdp, nb.x, nb.y, 60, 0).catch(() => {}); await g.page.waitForTimeout(400);
  check((await nodePos()) === before, "2c. mobile: vuốt bắt đầu trên một nút thì cuộn bản đồ, không kéo lệch nút", `${before} → ${await nodePos()}`);
  await g.page.context().close();

  // ── Jarvis.log (trang Nhật ký trong Settings, khóa mật khẩu) ──
  const l = await open(browser, MOBILE);
  await openPage(l.page, "logs");
  await l.page.fill("#logs-lock-input", "x"); await l.page.click("#logs-lock-btn");
  await l.page.waitForTimeout(400); await l.page.click('#logs-category-nav [data-log-tab="jarvis"]');
  await l.page.waitForSelector(".log-line", { timeout: 4000 }).catch(() => {});
  await l.page.waitForTimeout(500);
  const lg = await l.page.evaluate(() => { const c = document.getElementById("logs-content"); return { sw: c.scrollWidth, cw: c.clientWidth, ox: getComputedStyle(c).overflowX }; });
  check(lg.sw <= lg.cw + 1 && lg.ox === "hidden", "3a. mobile: nhật ký — dòng dài tự xuống dòng, không có cuộn ngang", JSON.stringify(lg));
  const px = await l.page.$eval("#card-logs", (p) => Math.round(p.getBoundingClientRect().x));
  await swipe(l.cdp, 200, 500, -240, 0); await l.page.waitForTimeout(400);
  const after = await l.page.evaluate(() => ({ cardX: Math.round(document.getElementById("card-logs").getBoundingClientRect().x), cl: document.getElementById("logs-content").scrollLeft, doc: document.scrollingElement.scrollLeft }));
  check(after.cardX === px && after.cl === 0 && after.doc === 0, "3b. mobile: vuốt ngang trên nhật ký không làm lệch khung hay nhảy khung hình", JSON.stringify({ before: px, after }));
  await l.page.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
