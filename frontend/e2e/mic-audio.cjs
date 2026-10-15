// E2E: AudioContext của trình phát KHÔNG bao giờ bị suspend (như bản gốc docs/frontend-original), trên điện thoại lẫn máy tính.
//  Bản có suspend sau 2,5s im lặng làm iPhone mất chấm vàng và tiếng "ting" của nhận dạng giọng nói (iOS tắt nó khi âm thanh bị tạm dừng dưới chân,
//  rồi mic bật lại trên context vừa suspend nên phải chờ vài phiên mới nghe lại). Quy trình đúng như bản gốc:
//    bật mic: start() → nhận xong: pause() (tạm dừng nhận dạng cho TTS đọc) → đọc xong: resume() ngay → lặp lại; tắt mic: stop() hẳn.
//  AudioContext luôn chạy suốt, mic bật lại tức thì khi JARVIS đọc xong.
// SpeechRecognition là bản giả, WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/mic-audio.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const tone = (sec) => { const n = 24000 * sec, a = new Int16Array(n); for (let i = 0; i < n; i++) a[i] = Math.sin((2 * Math.PI * 330 * i) / 24000) * 9000; return Buffer.from(a.buffer).toString("base64"); };

async function run(browser, label, opts) {
  const ctx = await browser.newContext(opts);
  await ctx.addInitScript(() => {
    window.__ctxs = [];
    const AC = window.AudioContext;
    window.AudioContext = class extends AC { constructor(...a) { super(...a); window.__ctxs.push(this); } };
    window.__suspends = 0;
    const sp = AC.prototype.suspend; AC.prototype.suspend = function (...a) { window.__suspends++; return sp.apply(this, a); };
    window.SpeechRecognition = class {
      constructor() { window.__sr = this; }
      start() { setTimeout(() => this.onstart && this.onstart(), 0); }
      stop() { setTimeout(() => this.onend && this.onend(), 0); }
      abort() {}
    };
  });
  const page = await ctx.newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE + "?debug=1");
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  // the control buttons sit behind the round menu button (#controls): open it first, then a real tap/click
  const press = async (sel) => {
    if (!(await page.$eval("#controls", (e) => e.classList.contains("open")))) { await page.click("#btn-controls"); await page.waitForTimeout(350); }
    return opts.hasTouch ? page.tap(sel) : page.click(sel);
  };
  const send = (m) => sock.send(JSON.stringify(m));
  const state = () => page.evaluate(() => window.__ctxs[0]?.state);
  const suspends = () => page.evaluate(() => window.__suspends);
  const micOn = async () => { await page.waitForTimeout(1200); return page.evaluate(() => /mic SR on/.test(document.getElementById("perf-debug").textContent)); }; // bảng debug cập nhật mỗi giây

  await press("#btn-mute"); await page.waitForTimeout(1500);
  check(await micOn(), `${label} 1. bấm nút mic → start(), nhận dạng giọng nói chạy`);
  await page.waitForTimeout(6000);
  check((await state()) === "running" && (await suspends()) === 0, `${label} 2. mic nghe 6s: AudioContext chạy, không bị suspend lần nào`, `${await state()} suspend=${await suspends()}`);

  send({ type: "status", state: "thinking" });
  check(!(await micOn()), `${label} 3. JARVIS nhận câu → pause(): nhận dạng giọng nói tạm dừng`);
  send({ type: "stream_start" });
  send({ type: "pcm_chunk", data: tone(1), sample_rate: 24000, gap_ms: 0 });
  send({ type: "status", state: "idle" }); // như server thật: báo xong lượt trong lúc tiếng còn đang phát
  await page.waitForTimeout(6000); // đọc xong (đệm 0,45s + 1s tiếng) rồi chờ thêm quá 2,5s
  check((await state()) === "running" && (await suspends()) === 0, `${label} 4. đọc xong 6s sau: AudioContext vẫn chạy, không suspend`, `${await state()} suspend=${await suspends()}`);
  check(await micOn(), `${label} 5. đọc xong → resume(): mic bật lại, nghe tiếp`);

  await press("#btn-mute"); await page.waitForTimeout(500);
  check(!(await micOn()), `${label} 6. bấm tắt mic → stop(): mic tắt hẳn`);
  await page.waitForTimeout(5000);
  check((await state()) === "running" && (await suspends()) === 0 && !(await micOn()), `${label} 7. tắt mic rồi: không có hoạt động mic nào, AudioContext vẫn không suspend (như bản gốc)`, `${await state()} suspend=${await suspends()}`);
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  await run(browser, "[điện thoại]", { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await run(browser, "[máy tính]", { viewport: { width: 1280, height: 800 } });
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
