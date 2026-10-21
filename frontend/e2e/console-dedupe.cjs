// E2E: bật/tắt nút mic không in trùng log trạng thái.
//  Trước đây một cú bấm in [UI] updateStatus 2-3 lần giống hệt nhau (transition() cập nhật, rồi nút mic cập nhật lại, rồi sự kiện mic đổi trạng thái lại cập nhật):
//  nay updateStatus bỏ qua lần gọi không đổi gì (cùng trạng thái, nội dung, đang nghe hay không, bận hay không).
// SpeechRecognition là bản giả, WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/console-dedupe.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript(() => {
    window.SpeechRecognition = class {
      constructor() { window.__sr = this; this.on = false; }
      start() { if (this.on) throw new Error("InvalidStateError"); this.on = true; setTimeout(() => this.onstart && this.onstart(), 0); }
      stop() { if (!this.on) return; setTimeout(() => { this.on = false; this.onend && this.onend(); }, 0); }
      abort() { this.stop(); }
    };
  });
  const page = await ctx.newPage();
  const logs = [];
  page.on("console", (m) => logs.push(m.text()));
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(2000);
  const since = async (fn) => { logs.length = 0; await fn(); await page.waitForTimeout(700); return logs.filter((l) => /\[UI\] updateStatus|\[voice\] microphone state/.test(l)); };
  const dup = (ls) => ls.filter((l, i) => ls.indexOf(l) !== i);

  const on = await since(() => page.evaluate(() => document.getElementById("btn-mute").click()));
  check(dup(on).length === 0, "1. bật mic: không dòng trạng thái nào in trùng", on.map((l) => l.replace("[UI] updateStatus: ", "")).join(" | "));
  check(on.filter((l) => /microphone state changed: true/.test(l)).length === 1, "2. bật mic: báo mic đổi trạng thái đúng 1 lần");
  const off = await since(() => page.evaluate(() => document.getElementById("btn-mute").click()));
  check(dup(off).length === 0, "3. tắt mic: không dòng trạng thái nào in trùng", off.map((l) => l.replace("[UI] updateStatus: ", "")).join(" | "));
  check(off.filter((l) => /microphone state changed: false/.test(l)).length === 1, "4. tắt mic: báo mic đổi trạng thái đúng 1 lần");

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
