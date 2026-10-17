// E2E: quả cầu orb nằm giữa phần trang (body, 100dvh) kể cả khi canvas cao hơn trang. Canvas cao 100lvh (fc0706a, để nền kéo
//  xuống dưới thanh địa chỉ Safari); trong app màn hình chính iPhone 100lvh > 100dvh nên tâm canvas thấp hơn tâm trang và quả cầu
//  bị lệch xuống (ngài 2026-10-16). Chromium không có thanh địa chỉ nổi: test ép canvas cao hơn trang 200px như trên iPhone,
//  rồi đo trọng tâm độ sáng của quả cầu (sau khi bung xong) phải ở giữa trang.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/orb-center.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { dismissWelcome } = require("./_welcome.cjs");
const zlib = require("zlib");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

// brightness centroid (x, y) of a screen area: PNG screenshot decoded here (all five row filters)
const centroid = async (page, clip) => {
  const png = await page.screenshot({ clip });
  const bpp = png[25] === 6 ? 4 : 3, idat = [];
  for (let o = 8; o < png.length;) { const n = png.readUInt32BE(o), t = png.toString("ascii", o + 4, o + 8); if (t === "IDAT") idat.push(png.subarray(o + 8, o + 8 + n)); o += 12 + n; }
  const raw = zlib.inflateSync(Buffer.concat(idat)), W = png.readUInt32BE(16), H = png.readUInt32BE(20), row = W * bpp;
  let prev = Buffer.alloc(row), sum = 0, sx = 0, sy = 0;
  for (let r = 0; r < H; r++) {
    const f = raw[r * (row + 1)], line = Buffer.from(raw.subarray(r * (row + 1) + 1, (r + 1) * (row + 1)));
    for (let i = 0; i < row; i++) {
      const a = i >= bpp ? line[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
      const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c);
      line[i] = (line[i] + [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][f]) & 255;
    }
    for (let i = 0, x = 0; i < row; i += bpp, x++) { const v = (line[i] + line[i + 1] + line[i + 2]) / 3; sum += v; sx += v * x; sy += v * r; }
    prev = line;
  }
  return { x: clip.x + sx / sum, y: clip.y + sy / sum };
};

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  // canvas cao hơn trang 200px (như 100lvh > 100dvh trong app màn hình chính iPhone); áp cho mọi canvas orb mới dựng
  await page.addStyleTag({ content: "#orb-canvas { height: calc(100dvh + 200px) !important; }" });
  await dismissWelcome(page);
  await page.evaluate(() => document.querySelectorAll("#chat-history .chat-bubble").forEach((b) => b.remove()));
  await page.waitForSelector("#orb-canvas[data-first]", { state: "attached", timeout: 20000 });
  await page.waitForTimeout(4000); // bung xong, đường nối đã hình thành
  // đo trong vùng giữa (bỏ thanh lệnh ở đáy, hàng nút ở trên): trang 1280x800, tâm trang (640, 400)
  let cx = 0, cy = 0;
  for (let i = 0; i < 4; i++) { const c = await centroid(page, { x: 240, y: 60, width: 800, height: 620 }); cx += c.x / 4; cy += c.y / 4; await page.waitForTimeout(400); }
  check(Math.abs(cy - 400) <= 30 && Math.abs(cx - 640) <= 40, "1. canvas cao hơn trang: quả cầu vẫn nằm giữa trang (±30px dọc)", JSON.stringify({ cx: Math.round(cx), cy: Math.round(cy) }));
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
