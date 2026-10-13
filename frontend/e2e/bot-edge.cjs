// E2E: mép của bot (mascot trên thanh lệnh) phải MƯỢT, không răng cưa, kể cả trên màn hình PC 100% (mật độ điểm ảnh 1x).
//  Lỗi cũ: PC dùng sides:"vector" (thân bot là chồng nhiều lát, mỗi lát khử răng cưa riêng nên viền cộng dồn thành cứng, lởm chởm);
//  iPhone dùng "sprite" (ảnh lát dựng sẵn, dán lại có làm mịn) nên đẹp.
//  (Không đo iPhone: ở mật độ 3x răng cưa không nhìn thấy, và Chromium của test không phải WebKit.)
//  Đo: lấy canvas của bot, thu về đúng cỡ hiển thị như trình duyệt làm ở 1x, đếm điểm ở MÉP (có màu, cạnh nó là trong suốt):
//  mép mượt thì phần lớn các điểm đó chỉ mờ một phần; mép răng cưa thì phần lớn là đặc 100%.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/bot-edge.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function run(label, opts, maxHard) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(600);
  const frames = [];
  for (let i = 0; i < 8; i++) {
    frames.push(await page.evaluate(() => {
      const c = document.querySelector("#jarvis-bot canvas"), css = c.getBoundingClientRect().width, dpr = window.devicePixelRatio;
      const w = Math.round(css * dpr), o = document.createElement("canvas"); o.width = o.height = w;
      const g = o.getContext("2d"); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "medium"; g.drawImage(c, 0, 0, w, w); // as the browser shrinks a 2x canvas to 1x
      const d = g.getImageData(0, 0, w, w).data, A = (x, y) => (x < 0 || y < 0 || x >= w || y >= w ? 0 : d[(y * w + x) * 4 + 3]);
      let edge = 0, hard = 0;
      for (let y = 0; y < w; y++) for (let x = 0; x < w; x++) { const a = A(x, y); if (a > 0 && (A(x - 1, y) <= 2 || A(x + 1, y) <= 2 || A(x, y - 1) <= 2 || A(x, y + 1) <= 2)) { edge++; if (a >= 250) hard++; } }
      return { edge, hard, w, canvasPx: c.width, dpr, sides: document.getElementById("jarvis-bot").dataset.sides || "" };
    }));
    await page.waitForTimeout(260);
  }
  const edge = frames.reduce((s, f) => s + f.edge, 0), hard = frames.reduce((s, f) => s + f.hard, 0), frac = edge ? hard / edge : 1;
  check(edge > 40, `[${label}] 0. thấy được mép của bot để đo`, `${edge} điểm mép, hiển thị ${frames[0].w}px, canvas ${frames[0].canvasPx}px, dpr ${frames[0].dpr}`);
  check(frac <= maxHard, `[${label}] 1. mép mượt: điểm mép đặc 100% chiếm ≤ ${(maxHard * 100).toFixed(0)}%`, `${(frac * 100).toFixed(1)}% (${hard}/${edge})`);
  await browser.close();
}

(async () => {
  await run("PC 100%", { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 }, 0.25);
  await run("PC 125%", { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.25 }, 0.25);
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
