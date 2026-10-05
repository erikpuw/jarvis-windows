// E2E: khi xem video (YouTube/phim: tin `media_open`) chỉ orb lớn của Three.js dừng vẽ; orb trạng thái nhỏ và avatar (bot) vẫn chạy hoạt ảnh.
//  Trước đây mở trình phát media gọi pauseScene() nên cổng hoạt ảnh dừng MỌI vòng lặp trang trí, kể cả orb nhỏ và bot vẫn đang hiện cạnh video.
//  Lớp phủ toàn màn hình (Settings, bản đồ toàn màn hình) vẫn dừng tất cả như cũ. Đóng Settings khi video còn mở: vòng nhỏ chạy lại, orb lớn vẫn dừng.
// Đếm lệnh vẽ của orb lớn (WebGL, #orb-canvas), orb trạng thái (#status-orb) và bot (#jarvis-bot) qua init script. WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/anim-media.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript(() => {
    window.__c = { orb: 0, bot: 0, status: 0 };
    for (const C of [window.WebGL2RenderingContext, window.WebGLRenderingContext]) {
      for (const fn of ["drawArrays", "drawElements"]) {
        const d = C.prototype[fn];
        C.prototype[fn] = function (...a) { if (this.canvas && this.canvas.id === "orb-canvas") window.__c.orb++; return d.apply(this, a); };
      }
    }
    const clear = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (...a) {
      const c = this.canvas;
      const k = c.closest && c.closest("#jarvis-bot") ? "bot" : c.closest && c.closest("#status-orb") ? "status" : null;
      if (k) window.__c[k]++;
      return clear.apply(this, a);
    };
  });
  const page = await ctx.newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/blank-video.html**", (r) => r.fulfill({ contentType: "text/html", body: "<html><body style='background:#000'></body></html>" }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(1500);
  // số lệnh vẽ của từng vòng lặp trong ms mili-giây
  const rate = async (ms) => {
    const a = await page.evaluate(() => ({ ...window.__c }));
    await page.waitForTimeout(ms);
    const z = await page.evaluate(() => ({ ...window.__c }));
    return { orb: z.orb - a.orb, bot: z.bot - a.bot, status: z.status - a.status };
  };
  const running = (r) => r.orb > 5 && r.bot > 5 && r.status > 5;

  let r = await rate(700);
  check(running(r), "1. bình thường: orb lớn, orb trạng thái nhỏ và avatar đều đang chạy", JSON.stringify(r));

  // 2. mở video
  sock.send(JSON.stringify({ type: "media_open", query: "thử", title: "Video thử", embed_url: "http://localhost:5173/blank-video.html?x=1" }));
  await page.waitForTimeout(600);
  check(await page.evaluate(() => document.body.classList.contains("media-playing") && !document.getElementById("media-player").classList.contains("hidden")), "2a. trình phát video đã mở");
  r = await rate(700);
  check(r.orb === 0, "2b. đang xem video: orb lớn (WebGL) dừng vẽ", JSON.stringify(r));
  check(r.status > 5 && r.bot > 5, "2c. đang xem video: orb trạng thái nhỏ và avatar VẪN chạy hoạt ảnh", JSON.stringify(r));

  // 3. mở Settings khi video còn mở: dừng tất cả; đóng Settings: vòng nhỏ chạy lại, orb lớn vẫn dừng
  await page.evaluate(() => document.getElementById("btn-settings").click()); await page.waitForTimeout(700);
  r = await rate(600);
  check(r.orb === 0 && r.status === 0 && r.bot === 0, "3a. Settings phủ toàn màn hình: dừng tất cả như cũ", JSON.stringify(r));
  await page.evaluate(() => document.getElementById("settings-close").click()); await page.waitForTimeout(700);
  r = await rate(700);
  check(r.orb === 0 && r.status > 5 && r.bot > 5, "3b. đóng Settings khi video còn mở: vòng nhỏ chạy lại, orb lớn vẫn dừng", JSON.stringify(r));

  // 4. đóng video: orb lớn chạy lại
  await page.keyboard.press("Escape"); await page.waitForTimeout(700);
  r = await rate(700);
  check(running(r) && (await page.evaluate(() => document.getElementById("media-player").classList.contains("hidden"))), "4. đóng video: orb lớn chạy lại cùng các vòng nhỏ", JSON.stringify(r));

  // 5. Settings không có video: dừng tất cả rồi chạy lại
  await page.evaluate(() => document.getElementById("btn-settings").click()); await page.waitForTimeout(700);
  r = await rate(600);
  check(r.orb === 0 && r.status === 0 && r.bot === 0, "5a. Settings (không video): dừng tất cả", JSON.stringify(r));
  await page.evaluate(() => document.getElementById("settings-close").click()); await page.waitForTimeout(700);
  r = await rate(700);
  check(running(r), "5b. đóng Settings: chạy lại tất cả", JSON.stringify(r));

  // 6. orb lớn đã tắt bằng nút: mở/đóng video không làm nó sống lại, vòng nhỏ vẫn chạy
  await page.click("#btn-orb-toggle"); await page.waitForTimeout(500);
  sock.send(JSON.stringify({ type: "media_open", query: "thử", title: "Video thử", embed_url: "http://localhost:5173/blank-video.html?x=2" })); await page.waitForTimeout(600);
  await page.keyboard.press("Escape"); await page.waitForTimeout(700);
  r = await rate(700);
  check(r.orb === 0 && r.status > 5 && r.bot > 5, "6. orb lớn đã tắt bằng nút: mở/đóng video không làm nó sống lại, vòng nhỏ vẫn chạy", JSON.stringify(r));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
