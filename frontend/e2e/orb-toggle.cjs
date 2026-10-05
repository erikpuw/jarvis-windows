// E2E: nút bật/tắt orb ở hàng nút điều khiển (góc trên phải), không có trong Settings.
//  Mặc định mỗi lần mở WebUI orb luôn bật. Bấm tắt: orb hết vẽ (không còn lệnh vẽ WebGL nào), canvas bị gỡ và ngữ cảnh WebGL được trả về GPU;
//  mở/đóng Settings khi đang tắt không làm nó sống lại. Bấm bật: canvas mới, vẽ lại bình thường, đầy khung hình như cũ. Không lưu trạng thái: tải lại trang là bật.
// Đếm lệnh vẽ và ngữ cảnh WebGL của canvas #orb-canvas qua init script. WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/orb-toggle.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...opts });
  await ctx.addInitScript(() => {
    window.__draws = 0; window.__ctxs = [];
    for (const C of [window.WebGL2RenderingContext, window.WebGLRenderingContext]) {
      for (const fn of ["drawArrays", "drawElements"]) {
        const d = C.prototype[fn];
        C.prototype[fn] = function (...a) { if (this.canvas && this.canvas.id === "orb-canvas") window.__draws++; return d.apply(this, a); };
      }
    }
    const gc = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (t, ...r) { const c = gc.call(this, t, ...r); if (c && this.id === "orb-canvas" && /webgl/.test(t) && !window.__ctxs.includes(c)) window.__ctxs.push(c); return c; };
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1200);
  return { ctx, page, errors, sock: () => sock };
}
const drawsOver = async (page, ms) => { const a = await page.evaluate(() => window.__draws); await page.waitForTimeout(ms); return (await page.evaluate(() => window.__draws)) - a; };
const orbState = (page) => page.evaluate(() => {
  const c = document.getElementById("orb-canvas"), b = document.getElementById("btn-orb-toggle");
  const rect = c ? c.getBoundingClientRect() : null;
  const gl = !!c && window.__ctxs.some((x) => !x.isContextLost() && x.canvas === c); // đang có ngữ cảnh WebGL sống trên canvas hiện tại
  let px = null;
  if (c && !gl) { try { px = [...c.getContext("2d").getImageData(0, 0, 1, 1).data]; } catch { /* not a 2d canvas */ } }
  return { canvas: gl && getComputedStyle(c).display !== "none", backdrop: !!c && !gl && !!px, px, w: rect ? Math.round(rect.width) : 0, h: rect ? Math.round(rect.height) : 0, lost: window.__ctxs.map((x) => x.isContextLost()), btn: !!b, pressed: b?.getAttribute("aria-pressed"), cls: b?.classList.contains("orb-off"), title: b?.title };
});

(async () => {
  const browser = await chromium.launch();
  const { ctx, page, errors, sock } = await open(browser);

  // 1. mặc định bật
  let st = await orbState(page);
  check(st.btn && st.canvas && st.w === 1280 && st.h === 800 && st.lost.length >= 1 && st.lost.every((l) => !l) && st.pressed === "true" && !st.cls, "1a. mặc định: có nút, orb hiện đầy khung, ngữ cảnh WebGL còn sống", JSON.stringify(st));
  check((await drawsOver(page, 600)) > 5, "1b. mặc định: orb đang vẽ liên tục");
  check(!(await page.$("#settings-container #btn-orb-toggle")) && !(await page.$("#settings-container [data-orb-toggle]")), "1c. nút nằm ở hàng nút điều khiển, không thêm vào Settings");
  const inRow = await page.evaluate(() => document.getElementById("btn-orb-toggle")?.parentElement?.id);
  check(inRow === "controls", "1d. nút nằm trong hàng nút điều khiển (#controls)", String(inRow));

  // 2. tắt
  await page.click("#btn-orb-toggle"); await page.waitForTimeout(500);
  st = await orbState(page);
  check(!st.canvas && st.lost.length >= 1 && st.lost.every((l) => l) && st.pressed === "false" && st.cls, "2a. bấm tắt: ngữ cảnh WebGL đã trả về GPU, nút đổi trạng thái", JSON.stringify(st));
  check(st.backdrop && st.w === 1280 && st.h === 800 && st.px[0] === 5 && st.px[1] === 5 && st.px[2] === 8 && st.px[3] === 255, "2a2. tắt: thay bằng một canvas phẳng 1×1 màu nền (#050508) phủ kín khung hình, không vẽ lại — giữ lớp nền cố định toàn màn hình như lúc orb bật (PWA iOS không bị mờ phía trên)", JSON.stringify({ backdrop: st.backdrop, px: st.px, w: st.w, h: st.h }));
  check((await drawsOver(page, 1200)) === 0, "2b. tắt: không còn lệnh vẽ nào (kể cả 1 giây liền)");
  const freed = await page.evaluate(() => window.__ctxs.filter((x) => x.isContextLost()).every((x) => x.canvas.width === 0 && x.canvas.height === 0));
  check(freed, "2b2. tắt: bộ đệm vẽ của canvas cũ được xả về 0×0 trước khi gỡ (không để lại khung hình cuối làm lớp mờ trên iOS Safari)");
  sock().send(JSON.stringify({ type: "status", state: "thinking" })); await page.waitForTimeout(300);
  check((await drawsOver(page, 600)) === 0, "2c. tắt: đổi trạng thái JARVIS (đang nghĩ) cũng không làm orb vẽ lại");
  await page.evaluate(() => document.getElementById("btn-settings").click()); await page.waitForTimeout(600);
  await page.evaluate(() => document.getElementById("settings-close").click()); await page.waitForTimeout(600);
  check((await drawsOver(page, 800)) === 0 && !(await orbState(page)).canvas && (await orbState(page)).backdrop, "2d. tắt: mở rồi đóng Settings không làm orb sống lại");

  // 3. bật lại
  await page.click("#btn-orb-toggle"); await page.waitForTimeout(700);
  st = await orbState(page);
  const live = st.lost[st.lost.length - 1] === false;
  check(st.canvas && !st.backdrop && st.w === 1280 && st.h === 800 && live && st.pressed === "true" && !st.cls, "3a. bấm bật: canvas mới đầy khung, ngữ cảnh WebGL mới còn sống", JSON.stringify(st));
  check((await drawsOver(page, 600)) > 5, "3b. bật lại: orb vẽ lại bình thường");
  const z = await page.evaluate(() => { const c = document.getElementById("orb-canvas"), s = getComputedStyle(c); return { pos: s.position, pe: s.pointerEvents, count: document.querySelectorAll("#orb-canvas").length }; });
  check(z.pos === "fixed" && z.pe === "none" && z.count === 1, "3c. canvas mới giữ đúng kiểu cũ (nền cố định, không chặn chuột), chỉ có một canvas orb", JSON.stringify(z));

  // 4. bật tắt liên tục không rò rỉ ngữ cảnh WebGL
  for (let i = 0; i < 6; i++) { await page.click("#btn-orb-toggle"); await page.waitForTimeout(150); await page.click("#btn-orb-toggle"); await page.waitForTimeout(150); }
  await page.waitForTimeout(400);
  const alive = await page.evaluate(() => window.__ctxs.filter((x) => !x.isContextLost()).length);
  check(alive === 1, "4. bật tắt nhiều lần: chỉ còn đúng một ngữ cảnh WebGL sống (không rò rỉ GPU)", String(alive));

  // 5. không lưu trạng thái: tắt rồi tải lại trang → bật
  await page.click("#btn-orb-toggle"); await page.waitForTimeout(400);
  await page.reload(); await page.waitForTimeout(1500);
  st = await orbState(page);
  check(st.canvas && st.pressed === "true" && (await drawsOver(page, 500)) > 3, "5. tắt rồi tải lại trang → orb bật lại (mặc định luôn bật, không lưu)", JSON.stringify(st));

  check(errors.length === 0, "6. không có lỗi console/trang trong cả quá trình", errors.slice(0, 2).join(" | "));
  await ctx.close();
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
