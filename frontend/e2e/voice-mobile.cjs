// E2E: tiếng JARVIS trên điện thoại không bị nhỏ khi mic bật.
//  Nguyên nhân (iOS/Safari): lúc JARVIS nói, bộ phát hiện ngắt lời mở getUserMedia (echoCancellation) → iOS chuyển phiên âm thanh
//  sang "play-and-record" qua bộ xử lý thoại: tiếng ra loa thoại/ốp tai ở mức gọi điện, rất nhỏ. Sửa: máy cảm ứng không mở mic để bắt
//  ngắt lời trong lúc phát. KHÔNG đụng vào navigator.audioSession: bản có đặt "playback" khi phát làm iOS nói được một lần là mic tắt luôn
//  (tiếng "ting" bật/tiếp tục mic của nhận dạng giọng nói biến mất), nên phiên âm thanh được để mặc định như bản gốc.
// WebSocket và /api bị mock, mic là thiết bị giả của Chromium. Chạy: PW=<module playwright> node frontend/e2e/voice-mobile.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const tone = (sec) => { const n = 24000 * sec, a = new Int16Array(n); for (let i = 0; i < n; i++) a[i] = Math.sin((2 * Math.PI * 330 * i) / 24000) * 9000; return Buffer.from(a.buffer).toString("base64"); };

async function open(browser, opts) {
  const ctx = await browser.newContext(opts);
  await ctx.addInitScript(() => {
    window.__gum = 0; window.__gumArgs = []; window.__streams = [];
    const md = navigator.mediaDevices;
    if (md) { const g = md.getUserMedia.bind(md); md.getUserMedia = (c) => { window.__gum++; window.__gumArgs.push(c); return g(c).then((st) => { window.__streams.push(st); return st; }); }; }
    // Safari 16.4+: navigator.audioSession; Chromium chưa có nên dựng bản giả ghi lại các lần đặt
    window.__sessionLog = [];
    let type = "auto";
    Object.defineProperty(navigator, "audioSession", { value: { get type() { return type; }, set type(v) { type = v; window.__sessionLog.push(v); } } });
  });
  const page = await ctx.newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  await page.mouse.click(300, 300); // mở khoá âm thanh bằng một lần chạm
  await page.evaluate(() => document.getElementById("btn-mute").click()); // mic bật (mặc định đang tắt)
  await page.waitForTimeout(300);
  return { page, send: (m) => sock.send(JSON.stringify(m)) };
}

(async () => {
  const browser = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"] });

  const phone = await open(browser, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  check(await phone.page.evaluate(() => matchMedia("(pointer: coarse)").matches), "0. giả lập điện thoại: pointer coarse");
  phone.send({ type: "stream_start" });
  phone.send({ type: "pcm_chunk", data: tone(2), sample_rate: 24000, gap_ms: 0 });
  await phone.page.waitForTimeout(1200);
  const mid = await phone.page.evaluate(() => ({ gum: window.__gum, type: navigator.audioSession.type, log: window.__sessionLog }));
  check(mid.gum === 0, "1a. điện thoại: đang nói không mở mic bắt ngắt lời (getUserMedia 0 lần)", JSON.stringify(mid));
  check(mid.type === "auto" && mid.log.length === 0, "1b. điện thoại: đang nói không đụng vào audioSession (vẫn mặc định auto, chưa từng bị đặt)", JSON.stringify(mid));
  await phone.page.waitForTimeout(3500);
  const end = await phone.page.evaluate(() => ({ type: navigator.audioSession.type, log: window.__sessionLog }));
  check(end.type === "auto" && end.log.length === 0, "1c. nói xong: audioSession vẫn chưa từng bị đặt lần nào", JSON.stringify(end));
  await phone.page.context().close();

  const pc = await open(browser, { viewport: { width: 1280, height: 800 } });
  pc.send({ type: "stream_start" });
  pc.send({ type: "pcm_chunk", data: tone(2), sample_rate: 24000, gap_ms: 0 });
  await pc.page.waitForTimeout(1200);
  const gum = await pc.page.evaluate(() => window.__gum);
  check(gum >= 1, "2a. máy tính: vẫn mở mic để bắt ngắt lời khi JARVIS nói (không đổi hành vi PC)", String(gum));
  const audio = await pc.page.evaluate(() => window.__gumArgs[0]?.audio);
  check(audio && audio.autoGainControl === false && audio.echoCancellation === true, "2b. mic bắt ngắt lời tắt autoGainControl (AGC của Chrome kéo hạ âm lượng mic của HỆ ĐIỀU HÀNH → nhận dạng giọng nói sau đó bị yếu), vẫn khử vọng", JSON.stringify(audio));
  await pc.page.waitForTimeout(4500);
  const live = await pc.page.evaluate(() => window.__streams.flatMap((s) => s.getTracks()).filter((t) => t.readyState === "live").length);
  check(live === 0, "2c. JARVIS nói xong → mic của bộ bắt ngắt lời được nhả hẳn (nhận dạng giọng nói giữ mic một mình)", `${live} track còn mở`);
  await pc.page.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
