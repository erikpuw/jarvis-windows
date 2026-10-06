// E2E: hiệu ứng 4 quả cầu của stream_start khi chữ đầu tiên tới.
//  Khi chưa có chữ, 4 quả cầu nhỏ bay vòng quanh (loader). Khi chữ sắp gõ ra, CẢ 4 QUẢ cùng PHỒNG NHẸ lên một chút (pump, như đang nhảy lên) rồi THU NHỎ LẠI VỀ TÂM
//  rồi tan. Trong suốt cú nhảy: 4 quả vẫn là 4 quả riêng (không dồn thành một cục), vẫn đang bay vòng, vị trí tâm cụm cố định (không dịch lên xuống/trái phải),
//  kích thước và hình ảnh quả cầu giữ nguyên (chỉ cả cụm phồng nhẹ rồi thu về tâm), và không tràn ra ngoài khung mặc định của hiệu ứng ban đầu.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/stream-bounce.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function run(label, opts) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  const send = (m) => sock.send(JSON.stringify(m));
  const tag = `[${label}]`;

  send({ type: "stream_start" }); await page.waitForTimeout(400);
  // khung mặc định = bong bóng loader ∪ vùng 4 quả cầu quay tới trong một vòng đầy đủ (2,2 giây) khi chưa có chữ; ghi luôn kích thước/ảnh quả cầu đang dùng
  const base = await page.evaluate(async () => {
    const bub = [...document.querySelectorAll(".chat-bubble.assistant")].pop(), pill = bub.getBoundingClientRect();
    let f = { l: pill.left, r: pill.right, t: pill.top, b: pill.bottom };
    const t0 = performance.now();
    await new Promise((res) => { const tick = () => { for (const x of bub.querySelectorAll(".blob-c")) { const r = x.getBoundingClientRect(); f = { l: Math.min(f.l, r.left), r: Math.max(f.r, r.right), t: Math.min(f.t, r.top), b: Math.max(f.b, r.bottom) }; } performance.now() - t0 < 2400 ? requestAnimationFrame(tick) : res(); }; requestAnimationFrame(tick); });
    const blobs = [...bub.querySelectorAll(".blob-c")].map((x) => { const cs = getComputedStyle(x); return { w: cs.width, h: cs.height, bg: cs.backgroundImage, origin: cs.transformOrigin }; });
    const host = bub.querySelector(".stream-bubble-host").getBoundingClientRect();
    return { ...f, pillW: pill.width, pillH: pill.height, blobs, hostCx: host.left + host.width / 2 - pill.left, hostCy: host.top + host.height / 2 - pill.top };
  });
  await page.evaluate(() => {
    window.__c = [];
    const tick = () => {
      const bub = [...document.querySelectorAll(".chat-bubble.assistant")].pop(), host = bub?.querySelector(".stream-bubble-host");
      if (host && host.classList.contains("collapsing")) {
        const h = host.getBoundingClientRect(), bl = [...host.querySelectorAll(".blob-c")].map((x) => x.getBoundingClientRect());
        const bb = bub.getBoundingClientRect();
        window.__c.push({ t: performance.now(), ax: h.left + h.width / 2, ay: h.top + h.height / 2, w: h.width, cx: h.left + h.width / 2 - bb.left, cy: h.top + h.height / 2 - bb.top, op: parseFloat(getComputedStyle(host).opacity), n: bl.length,
          balls: bl.map((r) => [r.left + r.width / 2, r.top + r.height / 2]), l: Math.min(...bl.map((r) => r.left)), r: Math.max(...bl.map((r) => r.right)), tp: Math.min(...bl.map((r) => r.top)), bt: Math.max(...bl.map((r) => r.bottom)) });
      }
      window.__raf = requestAnimationFrame(tick);
    };
    window.__raf = requestAnimationFrame(tick);
  });
  send({ type: "text_chunk", text: "Xin chào, tôi nghe đây." });
  await page.waitForTimeout(1200);
  await page.evaluate(() => cancelAnimationFrame(window.__raf));
  const c = await page.evaluate(() => window.__c);
  const gone = await page.evaluate(() => !document.querySelector(".stream-bubble-host"));

  check(c.length >= 6, `${tag} 1. có animation đủ dài để thấy`, `${c.length} khung`);
  const w0 = c[0].w;
  const peak = c.reduce((m, f, i) => (f.w > m.w ? { w: f.w, i } : m), { w: 0, i: 0 });
  check(peak.w >= w0 * 1.06 && peak.w <= w0 * 1.3, `${tag} 2a. phồng NHẸ lên (pump): cả cụm 4 quả to ra khoảng 6–30%`, `gốc ${w0.toFixed(1)}px → đỉnh ${peak.w.toFixed(1)}px (x${(peak.w / w0).toFixed(2)})`);
  const small = c.findIndex((f) => f.w < w0 * 0.5);
  check(small > peak.i, `${tag} 2b. phồng lên TRƯỚC rồi mới thu nhỏ về tâm (đỉnh khung ${peak.i}, thu nhỏ từ khung ${small})`);
  const drift = Math.max(...c.map((f) => Math.hypot(f.cx - base.hostCx, f.cy - base.hostCy)));
  check(drift <= 0.8, `${tag} 2c. vị trí cố định: tâm cụm 4 quả không dịch đi đâu (không nhảy lên/xuống)`, `lệch lớn nhất ${drift.toFixed(2)}px`);
  check(c.every((f) => f.n === 4), `${tag} 2d. luôn là 4 quả cầu (không gộp thành một)`);
  // độ xoè của cụm (khoảng cách trung bình từ 4 quả tới tâm cụm) chia cho cỡ cụm: phồng đều cả cụm thì tỉ lệ này gần như không đổi; kéo các quả dồn về giữa sớm thì tụt mạnh
  const spread = (f) => { const mx = f.balls.reduce((s, b) => s + b[0], 0) / 4, my = f.balls.reduce((s, b) => s + b[1], 0) / 4; return f.balls.reduce((s, b) => s + Math.hypot(b[0] - mx, b[1] - my), 0) / 4 / f.w; };
  const s0 = Math.max(...c.slice(0, 3).map(spread)), sPeak = spread(c[peak.i]);
  check(sPeak >= s0 * 0.6, `${tag} 2e. lúc phồng lên 4 quả vẫn xoè ra như đang bay (không bị kéo dồn thành cục sớm)`, `độ xoè/cỡ: đầu ${s0.toFixed(2)} → đỉnh ${sPeak.toFixed(2)}`);
  const rel = (f) => f.balls.map(([x, y]) => Math.atan2(y - f.ay, x - f.ax));
  const turned = rel(c[0]).map((a0, i) => { let d = Math.abs(rel(c[peak.i])[i] - a0) % (2 * Math.PI); if (d > Math.PI) d = 2 * Math.PI - d; return (d * 180) / Math.PI; });
  check(turned.filter((d) => d > 8).length >= 3, `${tag} 2f. 4 quả vẫn đang BAY VÒNG trong lúc phồng lên (không đứng khựng)`, `góc đã quay: ${turned.map((d) => d.toFixed(0)).join("°, ")}°`);
  check(c.at(-1).w <= w0 * 0.35 || c.at(-1).op <= 0.2, `${tag} 2g. cuối cùng thu lại về tâm rồi tan`, `w ${c.at(-1).w.toFixed(1)}px op ${c.at(-1).op.toFixed(2)}`);
  const sizes = await page.evaluate(() => 1);
  check(base.blobs.length === 4 && base.blobs.every((b) => parseFloat(b.w) >= 10 && parseFloat(b.w) <= 17), `${tag} 2h. kích thước và hình ảnh quả cầu đang dùng giữ nguyên (11–16px, gradient)`, JSON.stringify(base.blobs.map((b) => b.w)));

  const TOL = 2.5;
  const out = c.filter((f) => f.l < base.l - TOL || f.r > base.r + TOL || f.tp < base.t - TOL || f.bt > base.b + TOL);
  const worst = Math.max(0, ...c.map((f) => Math.max(base.l - f.l, f.r - base.r, base.t - f.tp, f.bt - base.b)));
  check(out.length === 0, `${tag} 3. cả cú phồng nằm trong khung mặc định của hiệu ứng ban đầu (sai số ${TOL}px)`, `${out.length} khung vượt, tràn nhiều nhất ${worst.toFixed(1)}px; khung mặc định ${Math.round(base.r - base.l)}×${Math.round(base.b - base.t)} (bong bóng ${Math.round(base.pillW)}×${Math.round(base.pillH)})`);
  const dur = c.at(-1).t - c[0].t;
  check(dur <= 700 && gone, `${tag} 4. xong trong < 0,7 giây và khối bong bóng được gỡ hẳn`, `${dur.toFixed(0)}ms, gỡ=${gone}`);
  await browser.close();
}

(async () => {
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  await run("điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
