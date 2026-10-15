// E2E: orb tự dựng lại khi mất GPU. iOS thu hồi GPU của trang khi app chạy nền / khoá máy; quay lại thì ngữ cảnh WebGPU/WebGL
//  của orb đã mất (device lost) và orb đen cho tới khi bấm tắt/bật orb. Giờ renderer.onDeviceLost dựng lại orb trên canvas mới
//  (đợi trang hiện lại nếu đang ẩn). Chromium headless chạy three ở nền WebGL 2: mất ngữ cảnh giả lập bằng WEBGL_lose_context.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/orb-lost.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.addInitScript(() => {
    window.__draws = 0; window.__ctxs = [];
    const c = WebGL2RenderingContext.prototype.clear;
    WebGL2RenderingContext.prototype.clear = function (m) { if (this.canvas.id === "orb-canvas" && this.canvas.isConnected) window.__draws++; return c.call(this, m); };
    const gc = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (t, ...r) { const x = gc.call(this, t, ...r); if (x && this.id === "orb-canvas" && /webgl/.test(t) && !window.__ctxs.includes(x)) window.__ctxs.push(x); return x; };
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(2500);
  const drawsOver = async (ms) => { const a = await page.evaluate(() => window.__draws); await page.waitForTimeout(ms); return (await page.evaluate(() => window.__draws)) - a; };
  const live = () => page.evaluate(() => { const c = document.getElementById("orb-canvas"); return window.__ctxs.some((x) => x.canvas === c && !x.isContextLost()); });

  check((await drawsOver(500)) > 10 && (await live()), "1. orb đang vẽ");

  // 2. the GPU is taken away (as iOS does in the background)
  await page.evaluate(() => { const c = document.getElementById("orb-canvas"); window.__ctxs.find((x) => x.canvas === c).getExtension("WEBGL_lose_context").loseContext(); });
  await page.waitForTimeout(1500);
  const n = await drawsOver(600);
  check(n > 10 && (await live()), "2. mất GPU: orb tự dựng lại trên canvas mới, vẽ tiếp (không cần bấm tắt/bật)", `${n} lần vẽ / 0,6s`);
  const one = await page.evaluate(() => document.querySelectorAll("#orb-canvas").length);
  check(one === 1, "3. chỉ còn đúng một canvas orb", String(one));

  // 4. lost while the page is hidden: rebuilt once it is visible again
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, get: () => true }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.evaluate(() => { const c = document.getElementById("orb-canvas"); window.__ctxs.find((x) => x.canvas === c && !x.isContextLost()).getExtension("WEBGL_lose_context").loseContext(); });
  await page.waitForTimeout(800);
  const hiddenLive = await live();
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, get: () => false }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.waitForTimeout(1500);
  const n2 = await drawsOver(600);
  check(!hiddenLive && n2 > 10 && (await live()), "4. mất GPU lúc trang ẩn: đợi hiện lại mới dựng, rồi vẽ tiếp", JSON.stringify({ hiddenLive, n2 }));

  // 5. turning the orb off still wins: a loss while off does not bring it back
  await page.evaluate(() => document.getElementById("btn-orb-toggle").click()); await page.waitForTimeout(500);
  check((await drawsOver(800)) === 0, "5. tắt orb bằng nút: không vẽ");

  check(errors.length === 0, "6. không có lỗi trang", errors.slice(0, 2).join(" | "));
  await ctx.close();

  // 7. the GPU request hangs at page load (no error, no answer): the build is dropped after a few seconds and tried again
  //    (here the second try finds no WebGPU and uses WebGL 2), without anyone toggling the orb
  const hang = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await hang.addInitScript(() => {
    let asked = false;
    Object.defineProperty(navigator, "gpu", { configurable: true, get: () => (asked ? undefined : { requestAdapter: () => { asked = true; return new Promise(() => {}); }, getPreferredCanvasFormat: () => "bgra8unorm" }) });
  });
  const hp = await hang.newPage();
  await hp.routeWebSocket(/\/ws/, () => {});
  await hp.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await hp.goto(BASE);
  await hp.waitForTimeout(8000);
  const hb = await hp.evaluate(() => document.getElementById("orb-canvas").dataset.backend || "loading");
  check(hb === "webgl2", "7. GPU treo lúc mở trang: tự bỏ lượt treo và dựng lại, orb hiện (không cần bấm tắt/bật)", hb);
  await hang.close();

  // 8. a resource that never finishes keeps window "load" back: the orb and the effects still start after a few seconds
  const slow = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await slow.addInitScript(() => document.addEventListener("DOMContentLoaded", () => { const i = new Image(); i.src = "/__never.png"; document.body.appendChild(i); }));
  const sp = await slow.newPage();
  await sp.routeWebSocket(/\/ws/, () => {});
  await sp.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await sp.route("**/__never.png", () => { /* never answered */ });
  await sp.goto(BASE, { waitUntil: "domcontentloaded" });
  await sp.waitForTimeout(7000);
  const sb = await sp.evaluate(() => ({ ready: document.readyState, orb: document.getElementById("orb-canvas").dataset.backend || "loading", paused: document.documentElement.classList.contains("anim-paused") }));
  check(sb.ready !== "complete" && sb.orb !== "loading" && !sb.paused, "8. load không bao giờ tới: orb và hiệu ứng vẫn bắt đầu sau vài giây", JSON.stringify(sb));
  await slow.close();
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
