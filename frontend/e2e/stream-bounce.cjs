// E2E: hiệu ứng 4 quả cầu của stream_start khi chữ đầu tiên tới (mẫu C do người dùng chọn: KHÔNG zoom, chỉ thu về).
//  Khi chưa có chữ, 4 quả cầu nhỏ bay vòng quanh (loader). Khi chữ sắp gõ, 4 quả vẫn đang bay và THU NHỎ LẠI VỀ TÂM (không phồng lên), tan đi nhanh (< 0,4 giây).
//  Chữ chỉ bắt đầu hiện khi 4 quả đã thu nhỏ gần hết, nên THẤY RÕ CHỮ ĐẦU TIÊN (không bị quả cầu che), và gõ ra bình thường.
//  Trong lúc thu: vẫn là 4 quả riêng, vẫn bay vòng, tâm cụm cố định, kích thước/hình ảnh quả cầu giữ nguyên, không tràn khung mặc định của hiệu ứng ban đầu.
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
    const blobs = [...bub.querySelectorAll(".blob-c")].map((x) => { const cs = getComputedStyle(x); return { w: cs.width, h: cs.height, bg: cs.backgroundImage }; });
    const host = bub.querySelector(".stream-bubble-host").getBoundingClientRect();
    return { ...f, pillW: pill.width, pillH: pill.height, blobs, hostCx: host.left + host.width / 2 - pill.left, hostCy: host.top + host.height / 2 - pill.top };
  });
  await page.evaluate(() => {
    window.__c = []; window.__firstChar = null;
    const tick = () => {
      const bub = [...document.querySelectorAll(".chat-bubble.assistant")].pop(), host = bub?.querySelector(".stream-bubble-host"), t = bub?.querySelector(".bubble-text");
      const now = performance.now();
      let hw = null, balls = null;
      if (host && host.classList.contains("collapsing")) {
        const h = host.getBoundingClientRect(), bl = [...host.querySelectorAll(".blob-c")].map((x) => x.getBoundingClientRect()), bb = bub.getBoundingClientRect();
        hw = h.width; balls = bl;
        window.__c.push({ t: now, w: h.width, ax: h.left + h.width / 2, ay: h.top + h.height / 2, cx: h.left + h.width / 2 - bb.left, cy: h.top + h.height / 2 - bb.top, op: parseFloat(getComputedStyle(host).opacity), n: bl.length,
          balls: bl.map((r) => [r.left + r.width / 2, r.top + r.height / 2]), l: Math.min(...bl.map((r) => r.left)), r: Math.max(...bl.map((r) => r.right)), tp: Math.min(...bl.map((r) => r.top)), bt: Math.max(...bl.map((r) => r.bottom)) });
      }
      if (t && t.textContent.length >= 1 && !window.__firstChar) {
        const w = document.createTreeWalker(t, NodeFilter.SHOW_TEXT); const n = w.nextNode();
        const r = document.createRange(); r.setStart(n, 0); r.setEnd(n, 1); const cr = r.getBoundingClientRect();
        let cover = 0;
        if (balls) { const ov = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)); cover = balls.reduce((s, b) => s + ov(cr, b), 0) / Math.max(1, cr.width * cr.height); }
        window.__firstChar = { t: now, hostW: hw, cover, hostStillThere: !!host };
      }
      window.__raf = requestAnimationFrame(tick);
    };
    window.__raf = requestAnimationFrame(tick);
  });
  const sentAt = await page.evaluate(() => performance.now());
  send({ type: "text_chunk", text: "Xin chào, tôi nghe đây." });
  await page.waitForTimeout(1300);
  await page.evaluate(() => cancelAnimationFrame(window.__raf));
  const c = await page.evaluate(() => window.__c);
  const first = await page.evaluate(() => window.__firstChar);
  const gone = await page.evaluate(() => !document.querySelector(".stream-bubble-host"));
  const fullText = await page.evaluate(() => [...document.querySelectorAll(".chat-bubble.assistant")].pop().querySelector(".bubble-text").textContent);

  check(c.length >= 5, `${tag} 1. có animation thu lại đủ dài để thấy`, `${c.length} khung`);
  const w0 = c[0].w;
  check(Math.max(...c.map((f) => f.w)) <= w0 * 1.02, `${tag} 2a. KHÔNG zoom/phồng lên: chỉ thu lại`, `đỉnh x${(Math.max(...c.map((f) => f.w)) / w0).toFixed(2)}`);
  let rise = 0; for (let i = 1; i < c.length; i++) rise = Math.max(rise, c[i].w - c[i - 1].w);
  check(rise <= 0.4, `${tag} 2b. thu nhỏ liên tục, không nảy lên giữa chừng`, `tăng lớn nhất ${rise.toFixed(2)}px/khung`);
  const drift = Math.max(...c.map((f) => Math.hypot(f.cx - base.hostCx, f.cy - base.hostCy)));
  check(drift <= 3, `${tag} 2c. vị trí cố định: tâm cụm 4 quả không dịch đi đâu`, `lệch lớn nhất ${drift.toFixed(2)}px`);
  check(c.every((f) => f.n === 4), `${tag} 2d. luôn là 4 quả cầu (không gộp thành một)`);
  const spread = (f) => { const mx = f.balls.reduce((s, b) => s + b[0], 0) / 4, my = f.balls.reduce((s, b) => s + b[1], 0) / 4; return f.balls.reduce((s, b) => s + Math.hypot(b[0] - mx, b[1] - my), 0) / 4 / f.w; };
  const mid = c.findIndex((f) => f.w < w0 * 0.6), upto = c[Math.max(1, mid)];
  check(spread(upto) >= spread(c[0]) * 0.6, `${tag} 2e. lúc thu 4 quả vẫn xoè ra như đang bay (thu đều cả cụm, không bị kéo dồn thành cục)`, `độ xoè/cỡ: đầu ${spread(c[0]).toFixed(2)} → giữa ${spread(upto).toFixed(2)}`);
  const rel = (f) => f.balls.map(([x, y]) => Math.atan2(y - f.ay, x - f.ax));
  const turned = rel(c[0]).map((a0, i) => { let d = Math.abs(rel(upto)[i] - a0) % (2 * Math.PI); if (d > Math.PI) d = 2 * Math.PI - d; return (d * 180) / Math.PI; });
  check(turned.filter((d) => d > 8).length >= 3, `${tag} 2f. 4 quả vẫn đang BAY VÒNG trong lúc thu`, `góc đã quay: ${turned.map((d) => d.toFixed(0)).join("°, ")}°`);
  check(c.at(-1).w <= w0 * 0.35 || c.at(-1).op <= 0.2, `${tag} 2g. cuối cùng thu về tâm rồi tan`, `w ${c.at(-1).w.toFixed(1)}px op ${c.at(-1).op.toFixed(2)}`);
  check(base.blobs.length === 4 && base.blobs.every((b) => parseFloat(b.w) >= 10 && parseFloat(b.w) <= 17), `${tag} 2h. kích thước và hình ảnh quả cầu đang dùng giữ nguyên (11–16px, gradient)`, JSON.stringify(base.blobs.map((b) => b.w)));
  const TOL = 2.5;
  const out = c.filter((f) => f.l < base.l - TOL || f.r > base.r + TOL || f.tp < base.t - TOL || f.bt > base.b + TOL);
  check(out.length === 0, `${tag} 3. không tràn ra ngoài khung mặc định của hiệu ứng ban đầu (sai số ${TOL}px)`, `${out.length} khung vượt; khung mặc định ${Math.round(base.r - base.l)}×${Math.round(base.b - base.t)}`);
  const dur = c.at(-1).t - c[0].t;
  check(dur <= 420 && gone, `${tag} 4. thu xong trong < 0,42 giây (gọn, không chậm) và khối bong bóng được gỡ hẳn`, `${dur.toFixed(0)}ms, gỡ=${gone}`);
  check(first && first.hostW !== null ? first.hostW <= w0 * 0.4 : first && !first.hostStillThere, `${tag} 5a. chữ đầu tiên chỉ hiện khi 4 quả đã thu nhỏ gần hết`, first ? `bề ngang cụm lúc hiện chữ đầu: ${first.hostW === null ? "đã gỡ" : first.hostW.toFixed(1) + "px"} (gốc ${w0.toFixed(1)}px)` : "không thấy chữ");
  check(first && first.cover <= 0.2, `${tag} 5b. THẤY RÕ chữ đầu tiên: quả cầu che dưới 20% ô chữ đầu`, first ? `che ${(first.cover * 100).toFixed(0)}%` : "không thấy chữ");
  check(first && first.t - sentAt <= 330, `${tag} 5c. chữ bắt đầu hiện trong < 0,33 giây kể từ khi tin chữ tới`, first ? `${(first.t - sentAt).toFixed(0)}ms` : "—");
  check(fullText === "Xin chào, tôi nghe đây.", `${tag} 5d. chữ vẫn gõ ra đủ, đúng`, JSON.stringify(fullText));
  await browser.close();
}

(async () => {
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  await run("điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
