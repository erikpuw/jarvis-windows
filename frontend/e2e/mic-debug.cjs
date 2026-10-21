// E2E: bảng ?debug=1 hiện tình trạng mic/nhận dạng giọng nói (STT) để đọc ngay trên điện thoại, không cần console:
//  số lần bật/tắt, số kết quả (tạm/cuối), lỗi theo mã, kết quả gần nhất (chữ + độ tin cậy + cách đây bao lâu), audioSession.
// SpeechRecognition là bản giả, WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/mic-debug.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript(() => {
    window.SpeechRecognition = class { constructor() { window.__sr = this; } start() { setTimeout(() => this.onstart && this.onstart(), 0); } stop() { setTimeout(() => this.onend && this.onend(), 0); } abort() {} };
  });
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE + "?debug=1");
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("btn-mute").click()); // bật mic
  await page.waitForTimeout(1500);
  const panel = () => page.$eval("#perf-debug", (e) => e.textContent);
  const line = async () => (await panel()).split("\n").find((l) => l.startsWith("mic")) || "";

  let l = await line();
  check(/^mic /.test(l) && /SR on/.test(l), "1. bảng có dòng mic, SR đang bật sau khi bấm nút mic", l);
  const res = (text, isFinal, confidence) => page.evaluate(([t, f, c]) => window.__sr.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: t, confidence: c }], { isFinal: f })] }), [text, isFinal, confidence]);
  await res("xin", false, 0); await res("xin chào", true, 0.42);
  await page.waitForTimeout(1200);
  l = await line();
  check(/results 2/.test(l) && /final 1/.test(l) && /"xin chào"/.test(l) && /0\.42/.test(l), "2. kết quả: đếm tạm/cuối, hiện chữ nghe được và độ tin cậy", l);
  await page.evaluate(() => { window.__sr.onerror({ error: "no-speech" }); window.__sr.onerror({ error: "no-speech" }); window.__sr.onerror({ error: "audio-capture" }); });
  await page.waitForTimeout(1200);
  l = await line();
  check(/no-speech×2/.test(l) && /audio-capture×1/.test(l), "3. lỗi đếm theo mã (no-speech, audio-capture…) thay vì nuốt im lặng", l);
  check(/audioSession/.test(await panel()), "4. vẫn có dòng AudioContext/audioSession");

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
