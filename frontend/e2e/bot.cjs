// E2E: bot linh vật (thay mascot, nằm trên nút gửi) theo từng trạng thái hệ thống (idle, listening, thinking, working, speaking).
//  idle      → tỉnh, nhìn quanh trái/phải/lên/xuống 30s rồi ngủ
//  listening → tỉnh, nhìn thẳng ra người nói (gật đầu khi nghe thấy tiếng, xem bot-gaze.cjs) 30s rồi ngủ
//  thinking  → tỉnh, nhìn về khung chat, 3 chấm suy nghĩ trên đầu, không nhảy, không bao giờ ngủ
//  working   → trạng thái working của thư viện (bận rộn)
//  speaking  → tỉnh, có miệng, nhìn về khung chat, không lật/nhảy ngẫu nhiên
//  chuột     → nhìn theo, KHÔNG nhảy khi lại gần; chỉ bấm vào bot mới nhảy mừng
// Đồng hồ giả của Playwright (page.clock) để không phải chờ 30s thật; WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/bot.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

async function open(browser, opts = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, ...opts });
  await page.clock.install();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(300);
  await page.waitForTimeout(300);
  const emit = async (s) => { await page.evaluate((st) => window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: st })), s); await page.waitForTimeout(80); };
  const st = () => page.$eval("#jarvis-bot", (e) => ({ state: e.dataset.state, face: e.dataset.face, look: e.dataset.look || "", grace: e.dataset.grace, hops: Number(e.dataset.hops || 0), jumps: e.dataset.idlejumps, dots: e.dataset.dots || "" })).catch(() => null);
  const ff = async (ms) => { await page.clock.fastForward(ms); await page.waitForTimeout(60); };
  return { page, emit, st, ff, sock };
}

(async () => {
  const browser = await chromium.launch();
  const { page, emit, st, ff, sock } = await open(browser);

  // vị trí: ngay trên nút gửi, trong khối thanh lệnh; nút gửi nằm TRÊN bot (bot có thể lấn xuống nhưng không che nút)
  const geo = await page.evaluate(() => {
    const bot = document.getElementById("jarvis-bot"), b = bot?.getBoundingClientRect(), sw = document.getElementById("cmd-send-wrap"), s = sw?.getBoundingClientRect();
    const pts = s ? [[0.5, 0.5], [0.5, 0.1], [0.5, 0.9], [0.15, 0.5], [0.85, 0.5]] : [];
    return {
      has: !!b, dx: b && s ? Math.abs((b.x + b.width / 2) - (s.x + s.width / 2)) : 999, near: b && s ? b.top < s.top && s.top - b.top < 60 : false,
      inBar: !!bot?.closest("#command-bar-inner"), z: bot && sw ? [Number(getComputedStyle(bot).zIndex), Number(getComputedStyle(sw).zIndex)] : null,
      hit: pts.map(([fx, fy]) => document.elementFromPoint(s.left + s.width * fx, s.top + s.height * fy)?.closest("#cmd-send-wrap, #jarvis-bot")?.id).join(","),
      canvases: document.querySelectorAll("#jarvis-bot canvas").length, mascot: !!document.getElementById("jarvis-mascot"), w: b && Math.round(b.width), shape: bot?.dataset.shape, shading: bot?.dataset.shading,
    };
  });
  check(geo.has && geo.dx < 40 && geo.near && geo.inBar && geo.canvases === 1, "0a. bot nằm trên nút gửi, trong khối thanh lệnh, đúng 1 canvas", JSON.stringify(geo));
  check(geo.z && geo.z[1] > geo.z[0] && geo.hit.split(",").every((h) => h === "cmd-send-wrap"), "0a2. nút gửi nằm TRÊN bot: mọi điểm trên nút vẫn bấm trúng nút", `z=${geo.z} hit=${geo.hit}`);
  check(geo.w === 32 && geo.shape === "square" && geo.shading === "plastic", "0a3. bot square 32px, shading plastic", `${geo.w}px ${geo.shape} ${geo.shading}`);
  check(!geo.mascot, "0b. mascot cáo đã gỡ", String(geo.mascot));
  for (let n = 0; n < 2; n++) { sock.send(JSON.stringify({ type: "stream_start" })); await page.waitForTimeout(120); sock.send(JSON.stringify({ type: "text_chunk", text: "Câu " + n })); await page.waitForTimeout(200); sock.send(JSON.stringify({ type: "stream_end" })); await page.waitForTimeout(150); }
  const old = await page.evaluate(() => ({ head: document.querySelectorAll("#chat-history .has-head, #chat-history .bubble-avatar, #chat-history .bubble-shell, #chat-history canvas").length, spring: document.querySelectorAll(".spring").length }));
  check(old.head === 0 && old.spring === 0, "0c. bong bóng chat trở lại khung cũ: không avatar, không lớp nền lò xo", JSON.stringify(old));

  // speaking: tỉnh + có miệng
  await emit("speaking");
  let s = await st();
  check(s.state === "default" && s.face === "mouth" && s.look === "chat" && s.jumps === "off" && s.dots === "", "1. speaking → tỉnh, có miệng, nhìn về khung chat, tắt lật/nhảy ngẫu nhiên", JSON.stringify(s));

  // working: trạng thái bận của thư viện, mặt thường
  await emit("working");
  s = await st();
  check(s.state === "working" && s.face === "eyes", "2. working → state working, mặt thường", JSON.stringify(s));

  // thinking: tỉnh, ngước lên các hướng phía trên, không nhảy, không ngủ
  await emit("thinking");
  s = await st();
  check(s.state === "default" && s.look === "chat" && s.face === "eyes" && s.dots === "1" && s.jumps === "off", "3a. thinking → tỉnh, nhìn về khung chat, 3 chấm suy nghĩ trên đầu", JSON.stringify(s));
  for (let i = 0; i < 4; i++) await ff(1900);
  s = await st();
  check(s.look === "chat" && s.dots === "1", "3b. thinking kéo dài: vẫn nhìn chat, vẫn 3 chấm", JSON.stringify(s));
  await ff(60000);
  s = await st();
  check(s.state === "default" && s.grace !== "1" && s.hops === 0, "3c. đang nghĩ thì không bao giờ ngủ, không nhảy", JSON.stringify(s));

  // listening: chăm chú nhìn xuống thanh lệnh, 30s rồi ngủ
  await emit("listening");
  s = await st();
  check(s.state === "default" && /^front/.test(s.look) && s.grace === "1" && s.dots === "", "4a. listening → tỉnh, nhìn thẳng ra người nói, bắt đầu 30s chờ", JSON.stringify(s));
  await ff(29000);
  s = await st();
  check(s.state === "default" && /^front/.test(s.look), "4b. 29s vẫn tỉnh, vẫn chăm chú nhìn thẳng", JSON.stringify(s));
  await ff(2500);
  s = await st();
  check(s.state === "sleeping" && s.grace !== "1" && s.look === "", "4c. đủ 30s không ai nói → ngủ", JSON.stringify(s));

  // idle: nhìn quanh đủ 4 hướng trong 30s, rồi ngủ
  await emit("working"); await emit("idle");
  s = await st();
  check(s.state === "default" && s.grace === "1" && s.jumps === "off", "5a. idle → tỉnh, bắt đầu 30s chờ, tắt nhảy lật ngẫu nhiên", JSON.stringify(s));
  const seen = new Set([s.look]);
  for (let i = 0; i < 6; i++) { await ff(1400); seen.add((await st()).look); }
  check(["left", "right", "up", "down"].every((d) => seen.has(d)), "5b. idle: nhìn đủ trái, phải, lên, xuống", [...seen].join(","));
  await ff(18000); // ~26.4s
  s = await st();
  check(s.state === "default" && s.jumps === "off", "5c. gần 30s vẫn tỉnh, không nhảy lật ngẫu nhiên của thư viện (các trò khi chờ: xem bot-tricks.cjs)", JSON.stringify(s));
  await ff(4500);
  s = await st();
  check(s.state === "sleeping" && s.look === "" && s.jumps === "on", "5d. đủ 30s → ngủ, thôi nhìn quanh, bật lại nhảy lật", JSON.stringify(s));

  // đang ngủ: idle → listening không đánh thức; có việc thì tỉnh
  await emit("listening");
  check((await st()).state === "sleeping", "6a. ngủ rồi, về nghe → vẫn ngủ");
  await emit("thinking");
  check((await st()).state === "default", "6b. có việc → tỉnh dậy");

  // idle → listening giữa chừng không đếm lại: tổng vẫn 30s
  await emit("idle"); await ff(20000);
  await emit("listening");
  s = await st();
  check(s.state === "default" && /^front/.test(s.look), "7a. idle 20s rồi sang nghe → vẫn tỉnh, đổi sang nhìn thẳng", JSON.stringify(s));
  await ff(11000);
  check((await st()).state === "sleeping", "7b. đồng hồ 30s không bị đếm lại khi idle ↔ listening");

  // có việc xen vào: huỷ đếm, rảnh lại thì đếm lại đủ 30s
  await emit("idle"); await ff(10000);
  await emit("working"); await ff(60000);
  check((await st()).state === "working", "8a. đang bận không ngủ");
  await emit("idle"); await ff(29000);
  check((await st()).state === "default", "8b. rảnh lại → đếm lại đủ 30s (29s vẫn tỉnh)");
  await ff(2500);
  check((await st()).state === "sleeping", "8c. đủ 30s mới ngủ");
  await page.close();

  // tương tác như libraries.dev/bots: nhìn theo chuột, lại gần thì nhảy tưng tưng, bấm thì nhảy vui hơn
  const pl = await open(browser);
  await pl.emit("speaking"); await pl.page.waitForTimeout(300); // bot tỉnh, không đang ân hạn nên không tự nhảy
  const c = await pl.page.$eval("#jarvis-bot", (e) => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  const ds = () => pl.page.$eval("#jarvis-bot", (e) => ({ follow: e.dataset.follow, hops: Number(e.dataset.hops || 0), awake: e.dataset.awake }));
  await pl.page.mouse.move(c.x - 700, c.y - 300); await pl.page.waitForTimeout(150);
  const far1 = await ds();
  check(far1.follow === "0" && far1.hops === 0, "11a. chuột ở xa: bot không nhìn theo, không nhảy", JSON.stringify(far1));
  await pl.page.mouse.move(c.x - 110, c.y - 40); await pl.page.waitForTimeout(150);
  const mid1 = await ds();
  check(mid1.follow === "1" && mid1.hops === 0, "11b. chuột lại vài bề ngang đầu: bot nhìn theo chuột (chưa nhảy)", JSON.stringify(mid1));
  await pl.page.mouse.move(c.x - 40, c.y - 10); await pl.page.waitForTimeout(250);
  const near1 = await ds();
  check(near1.follow === "1" && near1.hops === 0, "11c. chuột lại sát: bot vẫn nhìn theo, KHÔNG nhảy", JSON.stringify(near1));
  await pl.page.mouse.move(c.x - 12, c.y - 4); await pl.page.waitForTimeout(2000);
  const near2 = await ds();
  check(near2.hops === 0, "11d. chuột đứng sát bot nhiều giây: vẫn không nhảy", `${near2.hops}`);
  await pl.page.mouse.move(c.x - 700, c.y - 300); await pl.page.waitForTimeout(150);
  const h0 = (await ds()).hops;
  await pl.page.mouse.click(c.x, c.y); await pl.page.waitForTimeout(700);
  check((await ds()).hops >= h0 + 2, "11e. bấm vào bot: nhảy hai lần (vui hơn)", `${h0} → ${(await ds()).hops}`);
  await pl.page.close();

  // bot đang ngủ: chuột lại gần thì tỉnh về idle (nhìn quanh), 30s không hoạt động thì ngủ lại; chạm/gõ phím cũng đánh thức
  const w = await open(browser);
  await w.emit("idle"); await w.ff(31000);
  const wst = () => w.page.$eval("#jarvis-bot", (e) => ({ state: e.dataset.state, look: e.dataset.look || "", grace: e.dataset.grace || "", follow: e.dataset.follow }));
  const c0 = await w.page.$eval("#jarvis-bot", (e) => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  check((await wst()).state === "sleeping", "9-0. rảnh 30s → bot ngủ");
  await w.page.mouse.move(c0.x - 700, c0.y - 300); await w.page.waitForTimeout(150);
  check((await wst()).state === "sleeping", "9a. bot ngủ, chuột ở xa → vẫn ngủ", JSON.stringify(await wst()));
  await w.page.mouse.move(c0.x - 90, c0.y - 20); await w.page.waitForTimeout(250);
  const mid = await wst();
  check(mid.state === "default" && mid.follow === "1" && mid.grace === "1", "9b. chuột lại gần → bot tỉnh về idle, nhìn theo chuột, bắt đầu đếm lại 30s", JSON.stringify(mid));
  await w.page.mouse.move(c0.x - 700, c0.y - 300); await w.page.waitForTimeout(250);
  const away = await wst();
  check(away.state === "default" && away.look !== "", "9c. chuột đi xa → vẫn tỉnh, nhìn quanh chờ (idle)", JSON.stringify(away));
  await w.ff(20000);
  check((await wst()).state === "default", "9d. 20s sau lần hoạt động cuối vẫn tỉnh");
  await w.ff(12000);
  check((await wst()).state === "sleeping", "9e. đủ 30s không hoạt động → ngủ lại", JSON.stringify(await wst()));
  await w.page.keyboard.press("Shift"); await w.page.waitForTimeout(250);
  const typed = await wst();
  check(typed.state === "default" && typed.look !== "" && typed.grace === "1", "9f. đang ngủ, gõ phím (hoặc chạm màn hình) ở bất kỳ đâu → bot tỉnh về idle nhìn quanh", JSON.stringify(typed));
  await w.ff(31000);
  check((await wst()).state === "sleeping", "9g. rồi 30s sau lại ngủ");
  await w.page.close();

  // iPhone (dpr 3): canvas vẽ theo dpr 3 để bớt răng cưa
  const hi = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  await hi.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await hi.routeWebSocket(/\/ws/, () => {});
  await hi.goto(BASE); await hi.waitForTimeout(1500);
  const cw = await hi.$eval("#jarvis-bot canvas", (c) => c.width);
  check(cw === Math.round(32 * 1.5 * 3), "9h. màn dpr 3: canvas bot vẽ ở dpr 3 (144px) thay vì 2", String(cw));
  await hi.close();

  // giảm chuyển động: không nhìn quanh, ngủ ngay khi rảnh
  const rm = await open(browser, { reducedMotion: "reduce" });
  await rm.emit("speaking"); await rm.emit("idle");
  const r = await rm.st();
  check(r?.state === "sleeping" && r?.hops === 0 && r?.look === "", "10. giảm chuyển động: rảnh là ngủ ngay, không nhìn quanh", JSON.stringify(r));
  const painted = await rm.page.$eval("#jarvis-bot canvas", (c) => { const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) return true; return false; });
  const rmc = await rm.page.$eval("#jarvis-bot", (e) => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  await rm.page.mouse.move(rmc.x - 20, rmc.y); await rm.page.mouse.click(rmc.x, rmc.y); await rm.page.waitForTimeout(500);
  check(painted && !(await rm.page.$eval("#jarvis-bot", (e) => Number(e.dataset.hops || 0))), "10b. giảm chuyển động: bot vẫn hiện (khung tĩnh), không nhảy khi lại gần/bấm");
  await rm.page.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
