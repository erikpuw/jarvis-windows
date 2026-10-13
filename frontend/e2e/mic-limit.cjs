// E2E: mic bật mà không có đầu vào, và nhịp dừng/bật lại.
//  A. Phiên nhận dạng tự kết thúc mà chưa nghe được gì → tự bật lại sau 3 giây; quá 5 lần liên tiếp → stop() hẳn và tắt nút mic.
//  B. Có nghe được tiếng nói thì bộ đếm về 0 và lần bật lại kế tiếp là tức thì (nhận liên tục như bản gốc).
//  C. start() mà không bao giờ lên (iOS lặng lẽ không làm gì, không chấm vàng): sau 3s tự abort và thử lại; quá 5 lần → stop() và tắt nút mic.
//     (lần start đầu tiên được chờ lâu hơn vì có thể đang hiện hộp thoại xin quyền mic)
//  D. pause() rồi resume() ngay (JARVIS vừa nhận câu rồi xong): start() ném lỗi vì phiên cũ chưa kết thúc → bật lại NGAY khi nó kết thúc,
//     không bị tính là "tự tắt không có đầu vào" (không chờ 3s).
//  E. Bấm nút mic: start() và resume() liền nhau chỉ gọi nhận dạng giọng nói đúng 1 lần.
// Đồng hồ giả của Playwright để không phải chờ 3s thật; SpeechRecognition là bản giả như thật (start() ném lỗi khi đang chạy, stop() kết thúc sau một lúc);
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/mic-limit.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, { dead = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.addInitScript((dead) => {
    window.__starts = 0; window.__running = false; window.__dead = false; window.__stopMs = 0; window.__wantDead = dead;
    window.SpeechRecognition = class {
      constructor() { window.__sr = this; }
      start() {
        if (window.__running) throw new Error("InvalidStateError");
        window.__starts++; window.__running = true;
        if (!(window.__dead)) setTimeout(() => this.onstart && this.onstart(), 0);
      }
      stop() { if (!window.__running) return; setTimeout(() => { window.__running = false; this.onend && this.onend(); }, window.__stopMs); }
      abort() { this.stop(); }
    };
  }, dead);
  await page.clock.install();
  await page.routeWebSocket(/\/ws/, (ws) => { page.__ws = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1200);
  await page.clock.fastForward(1500); // bộ hẹn giờ khởi động 1s của app
  await page.click("#btn-controls"); await page.waitForTimeout(400); await page.click("#btn-mute"); await page.waitForTimeout(300); // mở menu nút rồi bấm nút mic: bật mic, start()
  const starts = () => page.evaluate(() => window.__starts);
  const muted = () => page.$eval("#btn-mute", (b) => b.classList.contains("muted"));
  // nhận dạng giọng nói tự kết thúc khi im lặng: no-speech rồi onend
  const emptyEnd = async () => { await page.evaluate(() => { window.__running = false; window.__sr.onerror({ error: "no-speech" }); window.__sr.onend(); }); await page.waitForTimeout(60); };
  const ff = async (ms) => { await page.clock.fastForward(ms); await page.waitForTimeout(60); };
  const send = (m) => page.__ws.send(JSON.stringify(m));
  return { page, starts, muted, emptyEnd, ff, send };
}

(async () => {
  const browser = await chromium.launch();

  // ── A ──
  const a = await open(browser);
  check((await a.starts()) === 1 && !(await a.muted()), "E. bấm nút mic → start() và resume() liền nhau chỉ gọi nhận dạng giọng nói đúng 1 lần", `starts=${await a.starts()}`);
  const s0 = await a.starts();
  await a.emptyEnd();
  check((await a.starts()) === s0, "A1. tự kết thúc không có đầu vào → KHÔNG bật lại ngay", `${s0} → ${await a.starts()}`);
  await a.ff(2800);
  check((await a.starts()) === s0, "A2. 2,8s sau vẫn chưa bật lại", `${await a.starts()}`);
  await a.ff(400);
  check((await a.starts()) === s0 + 1, "A3. đủ 3s → tự bật lại (reset)", `${s0} → ${await a.starts()}`);
  for (let i = 2; i <= 5; i++) { await a.emptyEnd(); await a.ff(3100); }
  check((await a.starts()) === s0 + 5 && !(await a.muted()), "A4. 5 lần tự tắt liên tiếp: vẫn tự bật lại, nút mic còn bật", `starts=${await a.starts()} muted=${await a.muted()}`);
  await a.emptyEnd(); await a.ff(10000);
  check((await a.starts()) === s0 + 5 && (await a.muted()), "A5. lần thứ 6 tự tắt → stop() hẳn, không bật lại nữa, nút mic tự tắt", `starts=${await a.starts()} muted=${await a.muted()}`);
  await a.page.close();

  // ── B ──
  const b = await open(browser);
  for (let i = 0; i < 4; i++) { await b.emptyEnd(); await b.ff(3100); }
  await b.page.evaluate(() => window.__sr.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: "xin", confidence: 0.5 }], { isFinal: false })] }));
  const before = await b.starts();
  await b.page.evaluate(() => { window.__running = false; window.__sr.onend(); }); await b.page.waitForTimeout(60);
  check((await b.starts()) === before + 1, "B1. phiên có nghe được tiếng nói kết thúc → bật lại NGAY (nhận liên tục, không chờ 3s)", `${before} → ${await b.starts()}`);
  for (let i = 0; i < 5; i++) { await b.emptyEnd(); await b.ff(3100); }
  check(!(await b.muted()), "B2. đã có tiếng nói nên bộ đếm về 0: thêm 5 lần tự tắt vẫn chưa bỏ cuộc", `muted=${await b.muted()}`);
  await b.page.close();

  // ── D ──
  const d = await open(browser);
  await d.page.evaluate(() => { window.__stopMs = 200; });
  const d0 = await d.starts();
  d.send({ type: "status", state: "thinking" }); await d.page.waitForTimeout(80); // pause(): stop() đang chờ kết thúc
  d.send({ type: "status", state: "idle" }); await d.page.waitForTimeout(80); // resume() ngay: phiên cũ chưa kết thúc nên start() ném lỗi
  check((await d.starts()) === d0, "D1. resume() khi phiên cũ chưa kết thúc: chưa bật được (start() ném lỗi như thật)", `${d0} → ${await d.starts()}`);
  await d.ff(300);
  check((await d.starts()) === d0 + 1, "D2. phiên cũ vừa kết thúc → bật lại ngay (không chờ 3s, không bị tính là tự tắt)", `${d0} → ${await d.starts()}`);
  await d.page.close();

  // ── C ──
  const c = await open(browser, { dead: true });
  check((await c.starts()) === 1, "C0. start() đầu tiên", `starts=${await c.starts()}`);
  await c.page.evaluate(() => { window.__dead = true; }); // từ đây start() lặng lẽ không lên (đã từng lên một lần: hết chờ hộp thoại quyền)
  await c.emptyEnd(); await c.ff(3100); // phiên đầu hết, 3s sau bật lại → start() không lên
  check((await c.starts()) === 2, "C1. start() không lên", `starts=${await c.starts()}`);
  await c.ff(2900);
  check((await c.starts()) === 2, "C2. 2,9s sau chưa lên → chưa thử lại", `${await c.starts()}`);
  await c.ff(700);
  check((await c.starts()) === 3, "C3. đủ 3s không lên → abort rồi thử lại", `${await c.starts()}`);
  let ticks = 0;
  while (!(await c.muted()) && ticks < 10) { await c.ff(3600); ticks++; }
  const stuck = await c.starts();
  await c.ff(10000);
  check((await c.muted()) && (await c.starts()) === stuck && stuck <= 7, "C4. quá 5 lần không lên → stop() hẳn, tắt nút mic, không thử nữa", `starts=${stuck}→${await c.starts()} muted=${await c.muted()}`);
  await c.page.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
