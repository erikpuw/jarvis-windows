// E2E: xuống dòng trong lúc stream chữ.
//  Lỗi cũ: tin `\n\n` tới thì bong bóng nở thêm hai dòng trắng ở đáy NGAY, trong khi chữ vẫn còn nằm ở dòng cũ; chữ đoạn sau lại được nối vào dòng cũ
//  (trước hai dấu xuống dòng) rồi vài trăm mili giây sau mới "nhảy" xuống đúng chỗ. Nhìn như bấm Enter hai lần rồi chữ nhảy về dòng của Enter thứ hai.
//  Đúng: dấu xuống dòng ở CUỐI chữ đang gõ không hiện trước; nó hiện cùng chữ đầu tiên của đoạn sau, chữ luôn nằm đúng dòng, không nhảy ngược lên,
//  không có khoảng trắng thừa ở đáy bong bóng; kết quả cuối vẫn có dòng trống giữa các đoạn như cũ.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/stream-newline.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const P1 = "Thôi được rồi, ngài muốn tôi 'bắn' nhiều hơn nữa hả? Được thôi, tôi sẽ mở rộng 'kho dữ liệu' và 'chiều sâu' câu chữ lên mức tối đa cho ngài thưởng thức đây!";
const P2 = "Vì ngài đang nói về việc 'nói nhiều hơn', tôi xin phép được đào sâu vào cái 'bản chất' của việc giao tiếp giữa một trợ lý AI và một người dùng thông minh như ngài. Ngài biết không, việc tôi cố gắng mô phỏng giọng điệu Sài Gòn.";
const P3 = "Ví dụ, khi tôi dùng từ 'trời đất' hay thêm một cái 'nè' vào cuối câu, đó không phải là ngẫu nhiên đâu.";

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

  send({ type: "stream_start" }); await page.waitForTimeout(500);
  await page.evaluate(() => {
    window.__f = [];
    const h = document.getElementById("chat-history");
    const tick = () => {
      const bub = [...h.querySelectorAll(".chat-bubble.assistant")].pop(), t = bub?.querySelector(".bubble-text");
      if (t && t.textContent) {
        const w = document.createTreeWalker(t, NodeFilter.SHOW_TEXT); let last = null; for (let n = w.nextNode(); n; n = w.nextNode()) last = n;
        const r = document.createRange(); r.setStart(last, Math.max(0, last.length - 1)); r.setEnd(last, last.length);
        const rr = r.getBoundingClientRect(), br = bub.getBoundingClientRect();
        window.__f.push({ n: t.textContent.length, lastTop: rr.top, gap: br.bottom - rr.bottom - 7, endsBr: /<br>\s*$/.test(t.innerHTML) });
      }
      window.__raf = requestAnimationFrame(tick);
    };
    window.__raf = requestAnimationFrame(tick);
  });

  // đoạn 1 + hai dấu xuống dòng, rồi dừng một lúc (chưa có đoạn sau)
  send({ type: "text_chunk", text: P1 + "\n\n" }); await page.waitForTimeout(4200);
  const held = await page.evaluate(() => { const t = [...document.querySelectorAll(".chat-bubble.assistant")].pop().querySelector(".bubble-text"); const f = window.__f.at(-1); return { endsBr: /<br>\s*$/.test(t.innerHTML), gap: f.gap, text: t.textContent.length }; });
  check(held.text > 100, `${tag} 1a. đoạn 1 đã gõ xong`, JSON.stringify(held));
  check(!held.endsBr && held.gap <= 4, `${tag} 1b. dấu xuống dòng ở CUỐI chưa hiện trước: không có dòng trắng thừa ở đáy bong bóng`, JSON.stringify(held));

  // đoạn 2: chữ đầu tiên phải nằm đúng dòng mới (có dòng trống ở trên), không được nối vào dòng cũ
  const mark = await page.evaluate(() => window.__f.length);
  send({ type: "text_chunk", text: P2 + "\n\n" }); await page.waitForTimeout(250);
  const first = await page.evaluate(() => { const t = [...document.querySelectorAll(".chat-bubble.assistant")].pop().querySelector(".bubble-text"); const w = document.createTreeWalker(t, NodeFilter.SHOW_TEXT); const nodes = []; for (let n = w.nextNode(); n; n = w.nextNode()) nodes.push(n); const full = nodes.map((n) => n.data).join(""); const i1 = full.indexOf("tối đa cho ngài thưởng thức đây!"), i2 = full.indexOf("Vì ngài"); const rect = (idx) => { let o = 0; for (const n of nodes) { if (idx < o + n.length) { const r = document.createRange(); r.setStart(n, idx - o); r.setEnd(n, idx - o + 1); return r.getBoundingClientRect(); } o += n.length; } return null; }; const a = i1 >= 0 ? rect(i1 + 20) : null, b = i2 >= 0 ? rect(i2) : null; return { have2: i2 >= 0, y1: a && Math.round(a.top), y2: b && Math.round(b.top) }; });
  check(first.have2 && first.y2 - first.y1 >= 25, `${tag} 2a. chữ đầu của đoạn 2 nằm ĐÚNG dòng mới (cách dòng cuối đoạn 1 một dòng trống), không bị nối vào dòng cũ`, JSON.stringify(first));
  await page.waitForTimeout(4200);
  send({ type: "text_chunk", text: P3 }); await page.waitForTimeout(3000);
  send({ type: "stream_end" }); await page.waitForTimeout(600);
  await page.evaluate(() => cancelAnimationFrame(window.__raf));

  const f = await page.evaluate(() => window.__f);
  let up = 0, upAt = null, maxGap = 0, gapBr = 0;
  for (let i = 1; i < f.length; i++) {
    const d = f[i - 1].lastTop - f[i].lastTop; if (d > up) { up = d; upAt = [f[i - 1], f[i]]; }
    if (!f[i].endsBr && f[i].gap > maxGap) maxGap = f[i].gap;
    if (f[i].endsBr) gapBr++;
  }
  check(up <= 3, `${tag} 3a. chữ không bao giờ nhảy ngược lên trong suốt lúc gõ`, `nhảy lên lớn nhất ${up.toFixed(0)}px ${upAt ? JSON.stringify(upAt) : ""}`);
  check(maxGap <= 6, `${tag} 3b. suốt lúc gõ đáy bong bóng không có khoảng trắng thừa dưới dòng chữ cuối`, `${maxGap.toFixed(0)}px`);
  check(gapBr === 0, `${tag} 3c. không có khung hình nào chữ đang kết thúc bằng dấu xuống dòng treo`, `${gapBr} khung`);

  const end = await page.evaluate(() => { const b = [...document.querySelectorAll(".chat-bubble.assistant")].pop(), t = b.querySelector(".bubble-text"); return { html: t.innerHTML, gap: window.__f.at(-1).gap, text: t.textContent }; });
  check(/đây!<br><br>Vì ngài/.test(end.html) && /Gòn\.<br><br>Ví dụ/.test(end.html), `${tag} 4a. kết quả cuối vẫn có dòng trống giữa các đoạn như cũ`, JSON.stringify(end.html.slice(end.html.indexOf("đây!") , end.html.indexOf("đây!") + 40)));
  check(end.text.includes("ngẫu nhiên đâu.") && end.gap <= 6, `${tag} 4b. kết quả cuối ôm vừa chữ, đủ chữ`, `gap ${end.gap}`);
  await browser.close();
}

(async () => {
  await run("máy tính", { viewport: { width: 760, height: 700 } });
  await run("điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
