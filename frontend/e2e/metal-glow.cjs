// E2E: quầng sáng của nút gửi (vòng kim loại, src/metal-ring.ts) — chép thuật toán "halo" của metal-fx (Libraries.dev, MIT):
//  canvas quầng sáng tràn ~40px quanh nút (metal-fx: 126px cho nút 40px), vẽ bằng 4 nét chồng nhau có làm mờ + một chấm sáng nhỏ,
//  sáng đậm trên mép vòng, mờ một nửa ở ngoài, không lấn vào trong nút; lớp bọc canvas mờ đi / hiện lên bằng opacity.
//  KHÔNG xoay vòng: mỗi lượt 3 giây = 1 giây sáng dần lên, 1 giây giữ sáng, 1 giây tắt dần; tắt hẳn rồi mới hiện ở một chỗ NGẪU NHIÊN
//  khác trên vòng. Mờ nhẹ như bản gốc (glowOpacity thấp của metal-fx): thấy rõ quầng nhưng không chói ra ngoài khung thanh lệnh.
//  MÀU: quầng sáng lấy màu từ chính vòng kim loại (metal-ring) NGAY CHỖ nó phát sáng (vòng kim loại đổi màu liên tục), không cố định một màu.
//  Dừng khi màn hình bị che (Settings/bản đồ/media, anim-gate); đứng yên khi bật "giảm chuyển động".
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/metal-glow.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"];

async function open(opts) {
  const browser = await chromium.launch({ args: ARGS });
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(400);
  return { browser, page };
}

// ghi từng khung hình: độ mờ của lớp quầng sáng, hướng (độ) của tâm sáng quanh nút, độ đậm lớn nhất trên canvas, độ sáng ở tâm nút
const film = (page, ms) => page.evaluate((ms) => new Promise((res) => {
  const env = document.querySelector("#cmd-send-wrap .metal-glow"), c = env.querySelector("canvas"), g = c.getContext("2d");
  const out = [], t0 = performance.now();
  const tick = () => {
    const d = g.getImageData(0, 0, c.width, c.height).data, w = c.width, h = c.height;
    let sx = 0, sy = 0, sum = 0, max = 0, centre = 0;
    for (let y = 0; y < h; y += 2) for (let x = 0; x < w; x += 2) {
      const a = d[(y * w + x) * 4 + 3]; if (!a) continue;
      sx += (x - w / 2) * a; sy += (y - h / 2) * a; sum += a; max = Math.max(max, a);
      if (Math.hypot(x - w / 2, y - h / 2) < w * 0.08) centre = Math.max(centre, a);
    }
    const ang = sum ? Math.round(((Math.atan2(sy, sx) * 180) / Math.PI + 360) % 360) : -1;
    out.push({ t: performance.now() - t0, op: parseFloat(getComputedStyle(env).opacity), ang, max, centre });
    performance.now() - t0 < ms ? requestAnimationFrame(tick) : res(out);
  };
  requestAnimationFrame(tick);
}), ms);
const angDiff = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };

(async () => {
  const { browser, page } = await open({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  const info = await page.evaluate(() => {
    const w = document.getElementById("cmd-send-wrap"), env = w.querySelector(".metal-glow"), c = env && env.querySelector("canvas");
    if (!c) return { metal: w.dataset.metal, glow: false };
    const wr = w.getBoundingClientRect(), cr = c.getBoundingClientRect();
    return { metal: w.dataset.metal, glow: true, pe: getComputedStyle(env).pointerEvents, spill: Math.round((cr.width - wr.width) / 2), cw: c.width, css: cr.width };
  });
  check(info.metal === "on", "0. vòng kim loại đang bật (WebGL2)", JSON.stringify(info));
  check(info.glow && info.pe === "none", "1. có canvas quầng sáng, không chặn bấm", JSON.stringify(info));
  if (!info.glow) { await browser.close(); console.log(`\n${failed} FAIL`); process.exit(1); }
  check(info.spill >= 30 && info.spill <= 50, "2. quầng sáng tràn ~40px quanh nút như metal-fx (mềm, rộng, không phải nét mảnh)", `${info.spill}px mỗi phía`);

  const f = await film(page, 9600);
  // các lần đổi chỗ (góc tâm sáng nhảy > 10°)
  const changes = []; for (let i = 1; i < f.length; i++) if (f[i].ang >= 0 && f[i - 1].ang >= 0 && angDiff(f[i].ang, f[i - 1].ang) > 10) changes.push(i);
  let moveLit = 0; for (const i of changes) if (Math.max(f[i].op, f[i - 1].op) > 0.03) moveLit++;
  check(moveLit === 0, "3. KHÔNG xoay: chỉ đổi chỗ khi đã tắt hẳn", `${moveLit}/${changes.length} lần đổi chỗ khi còn sáng`);
  // 3b. luồng chính bận (như lúc iPhone đang nạp trang): đổi chỗ vẫn chỉ khi đã tắt hẳn. Trước đây độ sáng do CSS chạy tiếp ở
  // luồng vẽ trong khi sự kiện animationiteration (đổi chỗ) đến trễ, nên quầng sáng đã sáng lên rồi mới nhảy sang chỗ khác
  await page.evaluate(() => { window.__busy = setInterval(() => { const end = performance.now() + 450; while (performance.now() < end) { /* busy */ } }, 700); });
  const fb = await film(page, 9600);
  await page.evaluate(() => clearInterval(window.__busy));
  const cb = []; for (let i = 1; i < fb.length; i++) if (fb[i].ang >= 0 && fb[i - 1].ang >= 0 && angDiff(fb[i].ang, fb[i - 1].ang) > 10) cb.push(i);
  let litB = 0; for (const i of cb) if (Math.max(fb[i].op, fb[i - 1].op) > 0.03) litB++;
  check(cb.length >= 2 && litB === 0, "3b. luồng chính bận: vẫn chỉ đổi chỗ khi đã tắt hẳn (không nhảy giữa lúc đang sáng)", `${litB}/${cb.length} lần đổi chỗ khi còn sáng`);
  const gaps = changes.slice(1).map((i, k) => f[i].t - f[changes[k]].t);
  check(changes.length >= 2 && gaps.every((g) => g > 2850 && g < 3200), "4. mỗi lượt 3 giây", JSON.stringify(gaps.map(Math.round)));
  const spots = changes.map((i) => f[i].ang);
  check(spots.length >= 2 && spots.slice(1).every((a, k) => angDiff(a, spots[k]) >= 45) && !spots.slice(2).every((a, k) => angDiff(angDiff(a, spots[k + 1]), angDiff(spots[k + 1], spots[k])) < 5),
    "5. hiện ở chỗ NGẪU NHIÊN (không lặp một bước xoay đều), cách chỗ trước đủ xa", JSON.stringify(spots));
  // nhịp trong một lượt: 1 giây sáng lên, 1 giây giữ, 1 giây tắt
  const c0 = changes[0], at = (ms) => f.reduce((best, x) => (Math.abs(x.t - (f[c0].t + ms)) < Math.abs(best.t - (f[c0].t + ms)) ? x : best));
  const rhythm = [500, 1500, 2500, 2980].map((ms) => +at(ms).op.toFixed(2));
  check(rhythm[0] > 0.2 && rhythm[0] < 0.8 && rhythm[1] >= 0.97 && rhythm[2] > 0.2 && rhythm[2] < 0.8 && rhythm[3] <= 0.05, "6. nhịp 1-2-3: đang sáng dần (0,5s), giữ sáng (1,5s), đang tắt dần (2,5s), tắt hẳn (3s)", JSON.stringify(rhythm));
  const peakA = Math.max(...f.map((x) => x.max));
  check(peakA <= 175, "7. mờ nhẹ như bản gốc: chỗ đậm nhất ≤ 70%", `${Math.round(peakA / 2.55)}%`);
  check(f.every((x) => x.centre === 0), "8. không lấn vào trong nút (icon không bị phủ)", `${Math.max(...f.map((x) => x.centre))}`);

  // màu: mỗi lần quầng sáng chuyển chỗ (sự kiện metal-glow-beat), màu của nó phải bằng màu vòng kim loại tại góc đó
  // (trung bình mảnh nhỏ trên dải vòng, chuẩn hoá kênh lớn nhất = 255 như metal-fx), đo độc lập ngay trong sự kiện đó
  const col = await page.evaluate(() => new Promise((res) => {
    const wrap = document.getElementById("cmd-send-wrap"), env = wrap.querySelector(".metal-glow"), src = wrap.querySelector(".metal-ring canvas");
    const size = wrap.getBoundingClientRect().width, R = size / 2, got = [];
    const cv = document.createElement("canvas"); cv.width = cv.height = 3;
    const g = cv.getContext("2d", { willReadFrequently: true });
    setTimeout(() => res(got), 14000); // chưa có dataset.angle/tint thì không treo: để các check bên dưới báo đỏ
    env.addEventListener("metal-glow-beat", () => {
      if (!env.dataset.angle || !env.dataset.tint) return;
      const ang = (parseFloat(env.dataset.angle) * Math.PI) / 180, k = src.width / size, r = (R - 1) * k;
      g.clearRect(0, 0, 3, 3);
      g.drawImage(src, src.width / 2 + r * Math.cos(ang) - 1.5 * k, src.height / 2 + r * Math.sin(ang) - 1.5 * k, 3 * k, 3 * k, 0, 0, 3, 3);
      const d = g.getImageData(0, 0, 3, 3).data; let sr = 0, sg = 0, sb = 0;
      for (let i = 0; i < d.length; i += 4) { sr += d[i]; sg += d[i + 1]; sb += d[i + 2]; }
      const m = Math.max(sr, sg, sb) || 1, want = [sr, sg, sb].map((v) => Math.round((255 * v) / m));
      // màu thật vẽ ra: điểm trên quầng cách tâm sáng ~6px về phía ngoài (ngoài chấm lõi trắng, vẫn trong quầng)
      const cvs = env.querySelector("canvas"), c2 = cvs.getContext("2d", { willReadFrequently: true }), dpr = cvs.width / cvs.getBoundingClientRect().width, mid = cvs.width / 2;
      const px = c2.getImageData(Math.round(mid + (R + 6) * Math.cos(ang) * dpr), Math.round(mid + (R + 6) * Math.sin(ang) * dpr), 1, 1).data;
      got.push({ want, tint: env.dataset.tint.split(",").map(Number), drawn: [px[0], px[1], px[2]], a: px[3] });
      if (got.length >= 4) res(got);
    });
  }));
  const near = (a, b, t) => a.every((v, i) => Math.abs(v - b[i]) <= t);
  check(col.length === 4 && col.every((c) => c.a > 0 && near(c.drawn, c.tint, 6)), "12. màu thật vẽ trên canvas quầng sáng đúng bằng màu đã lấy", JSON.stringify(col.map((c) => [c.drawn, c.tint, c.a])));

  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(1200);
  const p = await film(page, 1300);
  check(new Set(p.map((x) => `${x.op.toFixed(2)}|${x.ang}`)).size === 1, "9. mở Settings (màn hình bị che) thì quầng sáng dừng", JSON.stringify([p[0], p.at(-1)]));
  await browser.close();

  const r = await open({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
  const s = await film(r.page, 1500);
  check(s.every((x) => x.op === s[0].op && x.ang === s[0].ang) && s[0].ang >= 0, "10. giảm chuyển động: quầng sáng đứng yên ở một góc", JSON.stringify(s[0]));
  await r.browser.close();

  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
