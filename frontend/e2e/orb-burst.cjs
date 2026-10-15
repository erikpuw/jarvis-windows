// E2E: orb bật bởi tin nhắn đầu (lớp chào spec 2026-10-16): cả đám hạt là một chấm nhỏ ở tâm (giữ 1.2 s từ khung vẽ đầu, canvas hiện dần),
//  rồi bung nhanh ra chỗ cũ trong 0.6 s theo đường ease-out (ngài 2026-10-16). Đo độ sáng một dải phía ngoài lõi (cách tâm ~140-260px): lúc 0.9 s tối (chỉ có
//  chấm ở tâm), lúc 2.9 s đã bung xong (~1.6-2.4, dao động theo đường nối; bản đẩy bằng lực hãm chậm tới 4 s mới ~0.8).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/orb-burst.cjs   (cần `npm run dev` ở :5173)
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
  // lớp chào giữ orb tắt tới tin đầu (spec 2026-10-16): gửi tin, rồi orb dựng và giữ chấm 1.2 s (không phải 0.6) trước khi bung
  await dismissWelcome(page);
  await page.evaluate(() => document.querySelectorAll("#chat-history .chat-bubble").forEach((b) => b.remove()));
  await page.waitForSelector("#orb-canvas[data-first]", { state: "attached", timeout: 20000 });
  // mốc đo tính từ khung vẽ đầu (data-first): chấm giữ 1.2 s từ khung vẽ đầu rồi mới bung, nên đo lúc 0.9 s vẫn là chấm (canvas hiện dần trong 0.6 s).
  const atFirst = async (ms) => page.waitForTimeout(Math.max(0, ms - (await page.evaluate(() => performance.now() - Number(document.getElementById("orb-canvas").dataset.first)))));
  await atFirst(900);
  const early = await outer(page), dot = await screenMean(page, 634, 394, 12, 12); // chấm ở giữa (640,400) nhỏ ~2-6px: vùng 12x12 để không bị pha loãng
  await atFirst(2900);
  const late = await outer(page);
  check(late > 1.2, "1. 2.9 giây sau khi orb vẽ khung đầu: hạt đã bung ra tới dải ngoài (nhanh, đám mây như cũ)", late.toFixed(2));
  check(early < late * 0.4, "2. lúc mới nạp: dải ngoài còn tối, hạt gom ở tâm", JSON.stringify({ early: early.toFixed(2), late: late.toFixed(2) }));
  check(dot > early * 3 && dot > 3, "3. lúc mới nạp: có một chấm sáng nhỏ ở tâm", JSON.stringify({ dot: dot.toFixed(2), early: early.toFixed(2) }));
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
