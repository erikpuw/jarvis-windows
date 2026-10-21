// E2E: mọi vòng lặp hoạt ảnh (orb, orb trạng thái, viền edge-aura, shader nút gửi; bot linh vật đã gỡ 2026-10-17)
//  - dừng hẳn khi Settings / map / media phủ toàn màn hình, chạy lại khi đóng
//  - orb không vẽ quá 60 khung/s kể cả màn 120Hz; pause()+resume() liền nhau không sinh vòng lặp thứ hai
// Giả lập: điện thoại 390x844, rAF bị ép 120Hz. WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/anim-gate.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { dismissWelcome } = require("./_welcome.cjs");
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
  // lớp chào giữ orb tắt tới tin đầu (spec 2026-10-16): gửi một tin, rồi chờ orb dựng xong (chấm giữ 1200 ms) trước khi đo
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await dismissWelcome(page);
  await page.waitForTimeout(1800);
  const rate = async (ms = 1500) => {
    await page.evaluate(() => { window.__raf.clear(); window.__gl = 0; });
    await page.waitForTimeout(ms);
    return page.evaluate((ms) => ({ gl: window.__gl / (ms / 1000), raf: Object.fromEntries([...window.__raf].map(([k, v]) => [k, v / (ms / 1000)])) }), ms);
  };
  const sum = (r, keys) => keys.reduce((a, k) => a + (r.raf[k] || 0), 0);
  const LOOPS = ["orb.ts", "status-orb.ts", "edge-aura.ts", "anim-gate.ts", "other"]; // "other" gồm shader nút gửi

  const run = await rate();
  check(run.gl <= 62, "1. orb không vẽ quá 60 khung/s trên màn 120Hz", `${run.gl.toFixed(0)}/s`);
  check((run.raf["anim-gate.ts"] || 0) > 5, "2. vòng lặp chung (anim-gate) chạy khi bình thường", `${(run.raf["anim-gate.ts"] || 0).toFixed(0)}/s`);
  check((run.raf["anim-gate.ts"] || 0) > 5 && run.gl > 20, "3. orb trạng thái và viền (vòng lặp chung) vẫn chạy khi bình thường", JSON.stringify(run.raf));

  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click());
  await page.waitForTimeout(600);
  const open = await rate();
  check(open.gl === 0 && sum(open, LOOPS) <= 2, "4. mở Settings → mọi vòng lặp dừng hẳn", `gl=${open.gl} ${JSON.stringify(open.raf)}`);
  const cssRunning = () => page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running" && !a.effect?.target?.closest?.("#settings-container")).map((a) => a.animationName || a.transitionProperty));
  const behind = await cssRunning();
  check(behind.length === 0, "4b. mở Settings → animation CSS trên màn hình chính (chữ trạng thái, quầng sáng…) cũng dừng hết", behind.join(","));

  await page.evaluate(() => window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: false } })));
  await page.waitForTimeout(400);
  const back = await rate();
  check(back.gl > 20 && (back.raf["anim-gate.ts"] || 0) > 5, "5. đóng Settings → orb và các vòng lặp chạy lại", `gl=${back.gl.toFixed(0)} ${JSON.stringify(back.raf)}`);

  // pause()+resume() liền nhau nhiều lần (đóng/mở lớp phủ nhanh) không được nhân đôi vòng lặp
  await page.evaluate(() => { for (let i = 0; i < 6; i++) { window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: true } })); window.dispatchEvent(new CustomEvent("jarvis:overlay", { detail: { open: false } })); } });
  await page.waitForTimeout(400);
  const dbl = await rate();
  check(dbl.gl <= 62 && (dbl.raf["anim-gate.ts"] || 0) <= 400, "6. đóng/mở lớp phủ liên tục không sinh vòng lặp thứ hai", `gl=${dbl.gl.toFixed(0)} ${JSON.stringify(dbl.raf)}`);

  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  // orb đang vẽ (GL phần mềm trong headless) chiếm CPU làm các vòng nhỏ rớt khung; test 8 đo quả cầu/shader nên tắt orb trước
  await page.evaluate(() => { if (document.getElementById("orb-canvas")?.dataset.backend !== "off") document.getElementById("btn-orb-toggle").click(); });
  await page.waitForTimeout(800);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(800);
  // 8. ẩn thanh lệnh (nút #btn-cmd-bar): shader vòng kim loại nút gửi và quầng sáng dừng hẳn; quả cầu trạng thái (#status-row) vẫn chạy
  const shader = (r) => r.raf.other || 0; // the send-button shader (@paper-design) shows up as "other"
  const shown = await rate();
  await page.evaluate(() => document.getElementById("btn-cmd-bar").click());
  await page.waitForTimeout(600);
  const hid = await rate();
  const hidState = await page.evaluate(() => ({ halo: !!document.querySelector("#cmd-send-wrap .paused"), vis: getComputedStyle(document.getElementById("command-bar")).visibility }));
  check(shader(hid) === 0 && hidState.halo, "8a. ẩn thanh lệnh: shader nút gửi, quầng sáng dừng hẳn", JSON.stringify({ ...hidState, shader: shader(hid), shaderShown: shader(shown) }));
  const statusLoop = hid.raf["anim-gate.ts"] || 0;
  // one chain only: the 120 Hz stub (setTimeout 8 ms) lets a light loop tick ~110-125/s; a second chain would read ~240/s. (≤ 70 held
  // only while the heavy bot slowed every tick; the bot was removed 2026-10-17)
  check(statusLoop >= 50 && statusLoop <= 130, "8b. ẩn thanh lệnh: quả cầu trạng thái vẫn chạy (chỉ một vòng lặp chung)", `${statusLoop.toFixed(0)}/s · lúc hiện ${(shown.raf["anim-gate.ts"] || 0).toFixed(0)}/s`);
  check(hidState.vis === "hidden", "8c. ẩn thanh lệnh: phần đã mờ hẳn được ẩn (visibility), trình duyệt thôi vẽ lớp trong suốt", hidState.vis);
  await page.evaluate(() => document.getElementById("btn-cmd-bar").click());
  // fade with a 10 px slide (user 2026-10-16; 15 px still tinted the address bar on the iPhone). 20 px pushed the bar (bottom 18 px) past the screen's bottom edge on hide, and
  // iOS Safari then tinted its address bar from it: the slide must stay short of the edge
  const dy = () => page.evaluate(() => { const m = getComputedStyle(document.getElementById("command-bar")).transform; return m === "none" ? 0 : new DOMMatrix(m).m42; });
  await page.waitForTimeout(100);
  const yIn = await dy();
  await page.waitForTimeout(500);
  await page.evaluate(() => document.getElementById("btn-cmd-bar").click());
  await page.waitForTimeout(100);
  const yOut = await dy();
  await page.waitForTimeout(500);
  const yHidden = await dy();
  check(yIn > 0 && yIn < 10 && yOut > 0 && yOut < 10 && Math.abs(yHidden - 10) < 0.01, "8e. hiện/ẩn thanh lệnh: mờ dần kèm trượt 10px (không chạm mép dưới)", JSON.stringify({ yIn, yOut, yHidden }));
  await page.evaluate(() => document.getElementById("btn-cmd-bar").click());
  await page.waitForTimeout(600);
  await page.waitForTimeout(1000);
  const again = await rate();
  check(shader(again) > 30 && !(await page.$("#cmd-send-wrap .paused")), "8d. hiện lại thanh lệnh: shader, quầng sáng chạy lại", JSON.stringify({ shader: shader(again) }));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
