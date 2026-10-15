// E2E: mọi vòng lặp hoạt ảnh (orb, orb trạng thái, viền edge-aura, bot linh vật, shader nút gửi)
//  - dừng hẳn khi Settings / map / media phủ toàn màn hình, chạy lại khi đóng
//  - orb không vẽ quá 60 khung/s kể cả màn 120Hz; pause()+resume() liền nhau không sinh vòng lặp thứ hai
// Giả lập: điện thoại 390x844, rAF bị ép 120Hz. WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/anim-gate.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await ctx.addInitScript(() => {
    // màn 120Hz: rAF bắn mỗi ~8ms
    window.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 8);
    window.cancelAnimationFrame = (id) => clearTimeout(id);
    window.__raf = new Map(); window.__gl = 0;
    const o = window.requestAnimationFrame;
    window.requestAnimationFrame = (cb) => {
      const k = (new Error().stack.split("\n")[2] || "").match(/\/([\w.-]+\.(?:ts|js))/)?.[1] || "other";
      window.__raf.set(k, (window.__raf.get(k) || 0) + 1);
      return o(cb);
    };
    window.__bot = 0; // số lần vẽ lại canvas của bot (chỉ lệnh xóa toàn canvas của bubble-avatar.ts, mỗi khung đúng một lần)
    const cr = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (...a) { if (this.canvas.parentElement?.id === "jarvis-bot" && a[2] === this.canvas.width) window.__bot++; return cr.apply(this, a); };
    for (const C of [WebGL2RenderingContext, WebGLRenderingContext]) {
      const c = C.prototype.clear;
      C.prototype.clear = function (m) { if (this.canvas.id === "orb-canvas") window.__gl++; return c.call(this, m); };
    }
  });
  const page = await ctx.newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(2500);
  const rate = async (ms = 1500) => {
    await page.evaluate(() => { window.__raf.clear(); window.__gl = 0; });
    await page.waitForTimeout(ms);
    return page.evaluate((ms) => ({ gl: window.__gl / (ms / 1000), raf: Object.fromEntries([...window.__raf].map(([k, v]) => [k, v / (ms / 1000)])) }), ms);
  };
  const sum = (r, keys) => keys.reduce((a, k) => a + (r.raf[k] || 0), 0);
  const LOOPS = ["orb.ts", "status-orb.ts", "edge-aura.ts", "bot.ts", "anim-gate.ts", "other"]; // "other" gồm shader nút gửi

  const run = await rate();
  check(run.gl <= 62, "1. orb không vẽ quá 60 khung/s trên màn 120Hz", `${run.gl.toFixed(0)}/s`);
  check((run.raf["anim-gate.ts"] || 0) > 5, "2. bot linh vật có vòng lặp chung (anim-gate) khi bình thường", `${(run.raf["anim-gate.ts"] || 0).toFixed(0)}/s`);
  check((run.raf["anim-gate.ts"] || 0) > 5 && run.gl > 20, "3. orb trạng thái và viền (vòng lặp chung) vẫn chạy khi bình thường", JSON.stringify(run.raf));

  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(600);
  const open = await rate();
  check(open.gl === 0 && sum(open, LOOPS) <= 2, "4. mở Settings → mọi vòng lặp dừng hẳn", `gl=${open.gl} ${JSON.stringify(open.raf)}`);
  const cssRunning = () => page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running" && !a.effect?.target?.closest?.("#settings-container")).map((a) => a.animationName || a.transitionProperty));
  const behind = await cssRunning();
  check(behind.length === 0, "4b. mở Settings → animation CSS trên màn hình chính (đồng hồ, chữ trạng thái, quầng sáng…) cũng dừng hết", behind.join(","));

  await page.evaluate(() => window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: false } })));
  await page.waitForTimeout(400);
  const back = await rate();
  check(back.gl > 20 && (back.raf["anim-gate.ts"] || 0) > 5, "5. đóng Settings → orb và các vòng lặp chạy lại", `gl=${back.gl.toFixed(0)} ${JSON.stringify(back.raf)}`);

  // pause()+resume() liền nhau nhiều lần (đóng/mở lớp phủ nhanh) không được nhân đôi vòng lặp
  await page.evaluate(() => { for (let i = 0; i < 6; i++) { window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: true } })); window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: false } })); } });
  await page.waitForTimeout(400);
  const dbl = await rate();
  check(dbl.gl <= 62 && (dbl.raf["anim-gate.ts"] || 0) <= 400, "6. đóng/mở lớp phủ liên tục không sinh vòng lặp thứ hai", `gl=${dbl.gl.toFixed(0)} ${JSON.stringify(dbl.raf)}`);

  // bot linh vật: 60 khung/s cả trên màn cảm ứng (đã bỏ giới hạn 30; xem bot-fps.cjs). Máy test với rAF giả 120Hz chỉ đo được 35–60 kể cả
  // code cũ (2026-10-15), nên ngưỡng 32 chỉ để bắt lại giới hạn 30
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(800);
  await page.evaluate(() => (window.__bot = 0)); await page.waitForTimeout(1500);
  const bot = await page.evaluate(() => window.__bot / 1.5);
  check(bot >= 32 && bot <= 65, "7. bot linh vật vẽ ~60 khung/s trên màn cảm ứng (không còn bị giới hạn 30)", `${bot.toFixed(0)}/s`);

  // 8. ẩn thanh lệnh (nút #btn-cmd-bar): bot, shader vòng kim loại nút gửi và quầng sáng dừng hẳn; quả cầu trạng thái (#status-row) vẫn chạy
  const shader = (r) => r.raf.other || 0; // the send-button shader (@paper-design) shows up as "other"
  const shown = await rate();
  await page.evaluate(() => document.getElementById("btn-cmd-bar").click());
  await page.waitForTimeout(600);
  await page.evaluate(() => (window.__bot = 0));
  const hid = await rate();
  const hidState = await page.evaluate(() => ({ bot: window.__bot, halo: !!document.querySelector("#cmd-send-wrap .paused"), vis: getComputedStyle(document.getElementById("command-bar")).visibility }));
  check(hidState.bot === 0 && shader(hid) === 0 && hidState.halo, "8a. ẩn thanh lệnh: bot, shader nút gửi, quầng sáng dừng hẳn", JSON.stringify({ ...hidState, shader: shader(hid), shaderShown: shader(shown) }));
  const statusLoop = hid.raf["anim-gate.ts"] || 0;
  check(statusLoop >= 50 && statusLoop <= 70, "8b. ẩn thanh lệnh: quả cầu trạng thái vẫn chạy (chỉ còn một vòng chung ~60/s)", `${statusLoop.toFixed(0)}/s · lúc hiện ${(shown.raf["anim-gate.ts"] || 0).toFixed(0)}/s`);
  check(hidState.vis === "hidden", "8c. ẩn thanh lệnh: phần đã mờ hẳn được ẩn (visibility), trình duyệt thôi vẽ lớp trong suốt", hidState.vis);
  await page.evaluate(() => document.getElementById("btn-cmd-bar").click());
  await page.waitForTimeout(600);
  await page.evaluate(() => (window.__bot = 0)); await page.waitForTimeout(1000);
  const again = await rate();
  check((await page.evaluate(() => window.__bot)) > 30 && shader(again) > 30 && !(await page.$("#cmd-send-wrap .paused")), "8d. hiện lại thanh lệnh: bot, shader, quầng sáng chạy lại", JSON.stringify({ shader: shader(again) }));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
