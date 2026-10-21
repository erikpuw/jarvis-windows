// E2E: trang không gọi CDN bên thứ ba lúc nạp (trước đây index.html nạp hls.js từ cdn.jsdelivr.net ở MỌI lần mở trang,
// dù chỉ dùng cho IPTV .m3u8; Edge báo "Tracking Prevention blocked access to storage"). Tính năng IPTV đã bỏ nên hls.js
// bị gỡ hẳn khỏi mã nguồn và package.json. WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/no-cdn.cjs
const { chromium } = require(process.env.PW || "playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  check(!/<script[^>]+src=["']https?:/i.test(html) && !/<link[^>]+href=["']https?:\/\/(?!localhost)/i.test(html), "1. index.html không còn script/link tới máy chủ bên ngoài");

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const reqs = [];
  page.on("request", (r) => reqs.push(r.url()));
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/fake/**", (r) => r.fulfill({ status: 200, contentType: "application/vnd.apple.mpegurl", body: "#EXTM3U\n" }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  const external = reqs.filter((u) => /^https?:/.test(u) && !/^https?:\/\/(localhost|127\.0\.0\.1)[:/]/.test(u));
  check(external.length === 0, "2. nạp trang không gọi máy chủ bên ngoài nào", external.slice(0, 3).join(" "));
  check(!reqs.some((u) => /hls/i.test(u)), "3. không tải hls.js");

  // trình phát media: chỉ còn iframe/HTML5 thường (IPTV .m3u8 đã bỏ), không tải hls.js
  sock.send(JSON.stringify({ type: "media_open", query: "clip", title: "Clip thử", embed_url: BASE + "fake/embed" }));
  await page.waitForTimeout(1500);
  const media = await page.evaluate(() => ({ iframe: !!document.querySelector("#media-player-inner iframe"), iptv: !!document.getElementById("iptv-video"), open: !document.getElementById("media-player").classList.contains("hidden") }));
  check(media.open && media.iframe && !media.iptv, "4. media_open → trình phát iframe hiện bình thường, không còn khối IPTV", JSON.stringify(media));
  sock.send(JSON.stringify({ type: "media_open", query: "iptv", title: "Kênh", embed_url: BASE + "fake/stream.m3u8" }));
  await page.waitForTimeout(1500);
  check(!(await page.evaluate(() => !!document.getElementById("iptv-video"))) && !reqs.some((u) => /hls/i.test(u)), "5. URL .m3u8 không còn nhánh phát riêng, không tải hls.js");
  const src = fs.readFileSync(path.join(__dirname, "..", "src", "main.ts"), "utf8"), pkg = fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8");
  check(!/hls|m3u8|iptv/i.test(src) && !/hls/i.test(pkg), "6. mã nguồn không còn HLS/IPTV (main.ts, package.json)");
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
