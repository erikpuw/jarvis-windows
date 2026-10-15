// E2E: miệng của bot lúc JARVIS nói.
//  - Miệng thư viện bot-avatars không mở/đóng được và không đi theo hướng nhìn của mắt, nên lúc nói bot tự vẽ miệng:
//    mở ra khép lại theo nhịp từng âm tiết (tượng trưng, không khớp môi thật), mắt liếc đâu miệng đi theo đó (cả trái/phải lẫn lên/xuống),
//    quay đầu thì miệng quay cùng.
//  - Không nói thì không có miệng mở.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/bot-mouth.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  const emit = (s) => page.evaluate((st) => window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: st })), s);

  // vị trí miệng theo hướng nhìn (hàm thuần)
  const spot = await page.evaluate(async () => {
    const { mouthSpot } = await import("/src/bot-mouth.ts");
    const at = (p) => mouthSpot({ yaw: 0, pitch: 0, lookX: 0, lookY: 0, ...p });
    return { base: at({}), left: at({ lookX: -3 }), right: at({ lookX: 3 }), up: at({ lookY: -3 }), down: at({ lookY: 3 }), turned: at({ yaw: 0.4 }), away: at({ yaw: 2.2 }) };
  }).catch((e) => ({ err: String(e) }));
  check(!spot.err, "0. có module bot-mouth.ts với mouthSpot()", spot.err || "");
  if (!spot.err) {
    check(spot.right.x - spot.left.x > 5 && spot.right.x - spot.left.x < 6.2, "1a. mắt liếc phải 3 / trái 3 → miệng lệch gần đủ 6 đơn vị như mắt (mặt cầu: miệng thấp hơn nên co nhẹ)", `${spot.left.x.toFixed(2)} → ${spot.right.x.toFixed(2)}`);
    check(Math.abs(spot.down.y - spot.up.y - 6) < 0.5 && spot.down.y > spot.base.y && spot.up.y < spot.base.y, "1b. nhìn lên/xuống → miệng đi lên/xuống theo mắt (thư viện không làm)", `${spot.up.y.toFixed(2)} / ${spot.base.y.toFixed(2)} / ${spot.down.y.toFixed(2)}`);
    check(spot.turned.x > spot.base.x + 5 && spot.turned.sx < spot.base.sx, "1c. quay đầu sang phải → miệng dịch sang phải và co hẹp theo phối cảnh", `${spot.base.x.toFixed(1)} → ${spot.turned.x.toFixed(1)} sx ${spot.base.sx.toFixed(2)} → ${spot.turned.sx.toFixed(2)}`);
    check(spot.away.z <= 0.02, "1d. quay hẳn ra sau → miệng khuất (không vẽ)", `z=${spot.away.z.toFixed(2)}`);
  }

  // độ mở miệng (data-mouth, 0 khép … 1 há rộng) lấy mẫu mỗi 40ms
  const sample = (ms) => page.evaluate(async (ms) => {
    const el = document.getElementById("jarvis-bot"), out = [], end = performance.now() + ms;
    while (performance.now() < end) { out.push(el.dataset.mouth === undefined ? null : Number(el.dataset.mouth)); await new Promise((r) => setTimeout(r, 40)); }
    return out;
  }, ms);

  await emit("idle"); await page.waitForTimeout(300);
  const quiet = await sample(800);
  check(quiet.every((v) => v === null), "2a. không nói: không có miệng mở/đóng", JSON.stringify([...new Set(quiet)]));

  await emit("speaking"); await page.waitForTimeout(300);
  const talk = (await sample(2500)).filter((v) => v !== null);
  const lo = Math.min(...talk), hi = Math.max(...talk);
  check(talk.length > 20 && hi >= 0.7 && lo <= 0.3, "2b. đang nói: miệng há rộng rồi khép gần kín", `${lo}..${hi} (${talk.length} mẫu)`);
  const flips = talk.filter((v, i) => i && (v > 0.4) !== (talk[i - 1] > 0.4)).length;
  check(flips >= 4, "2c. nhịp mở–khép đều đặn như nói (≥ 4 lần đổi trong 2,5s)", `${flips} lần`);

  await emit("idle"); await page.waitForTimeout(500);
  const after = await sample(500);
  check(after.every((v) => v === null), "2d. nói xong: miệng hết nhép", JSON.stringify([...new Set(after)]));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
