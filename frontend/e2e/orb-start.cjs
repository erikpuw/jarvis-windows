// E2E: orb mở ra là hiện đám hạt ngay, không có màn mở đầu chấm-bung (ngài 2026-10-17 bỏ intro). Cả hai đường: tin nhắn đầu
//  (lớp chào giữ orb tắt tới lúc đó) và tắt/bật orb. Đo độ sáng một dải phía ngoài lõi (cách tâm ~140-260px) 0.4 s sau khung
//  vẽ đầu: có hạt ngay (~0.9-1.2); bản có chấm giữ thì đúng 0.00 (đo 2026-10-16).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/orb-start.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { dismissWelcome } = require("./_welcome.cjs");
const zlib = require("zlib");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

// mean brightness (0-255) of a screen area: PNG screenshot decoded here (all five row filters)
const screenMean = async (page, x, y, w, h) => {
  const png = await page.screenshot({ clip: { x, y, width: w, height: h } });
  const bpp = png[25] === 6 ? 4 : 3, idat = [];
  for (let o = 8; o < png.length;) { const n = png.readUInt32BE(o), t = png.toString("ascii", o + 4, o + 8); if (t === "IDAT") idat.push(png.subarray(o + 8, o + 8 + n)); o += 12 + n; }
  const raw = zlib.inflateSync(Buffer.concat(idat)), W = png.readUInt32BE(16), H = png.readUInt32BE(20), row = W * bpp;
  let prev = Buffer.alloc(row), sum = 0;
  for (let r = 0; r < H; r++) {
    const f = raw[r * (row + 1)], line = Buffer.from(raw.subarray(r * (row + 1) + 1, (r + 1) * (row + 1)));
    for (let i = 0; i < row; i++) {
      const a = i >= bpp ? line[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
      const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c);
      line[i] = (line[i] + [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][f]) & 255;
    }
    for (let i = 0; i < row; i += bpp) sum += (line[i] + line[i + 1] + line[i + 2]) / 3;
    prev = line;
  }
  return sum / (W * H);
};
// the band left and right of the core (centre 640,400 at 1280x800)
const outer = async (page) => ((await screenMean(page, 380, 300, 120, 200)) + (await screenMean(page, 780, 300, 120, 200))) / 2;

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  // 0.4 s after the canvas's first frame: it has faded in ~2/3 (0.6 s fade); a held dot would still read 0.00 here
  const atFirst = async (ms) => page.waitForTimeout(Math.max(0, ms - (await page.evaluate(() => performance.now() - Number(document.getElementById("orb-canvas").dataset.first)))));
  const firstFrame = () => page.waitForFunction(() => { const c = document.getElementById("orb-canvas"); return c.dataset.first && c.dataset.backend !== "off"; }, null, { polling: 10, timeout: 20000 });
  const sinceFirst = () => page.evaluate(() => Math.round(performance.now() - Number(document.getElementById("orb-canvas").dataset.first)));

  await dismissWelcome(page);
  await page.evaluate(() => document.querySelectorAll("#chat-history .chat-bubble").forEach((b) => b.remove()));
  await firstFrame(); await atFirst(400);
  const at1 = await sinceFirst(), first = await outer(page);
  // the old opening held the dot 1200 ms on this path: a sample before that still tells the two apart
  check(first > 0.3 && at1 < 1200, "1. tin nhắn đầu: orb hiện đám hạt ngay, không chấm-bung", JSON.stringify({ outer: first.toFixed(2), msAfterFirstFrame: at1 }));

  await page.evaluate(() => document.getElementById("btn-orb-toggle").click()); // tắt
  await page.waitForTimeout(500);
  await page.evaluate(() => document.getElementById("btn-orb-toggle").click()); // bật
  await firstFrame(); await atFirst(400);
  const at2 = await sinceFirst(), again = await outer(page);
  check(again > 0.3 && at2 < 600, "2. tắt/bật orb: hạt đã ở chỗ ngay khung đầu", JSON.stringify({ outer: again.toFixed(2), msAfterFirstFrame: at2 }));
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
