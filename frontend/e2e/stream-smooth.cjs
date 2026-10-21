// E2E: chữ stream hiện đều đặn theo khung hình (không có khung đứng hình xen kẽ khung nhảy 2-4 ký tự)
// và chữ thường chỉ được NỐI vào text node (không dựng lại toàn bộ markdown mỗi khung). WebSocket và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/stream-smooth.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

const WORDS = "Tôi đã mở Task Manager thành công thưa Ngài, đồng thời kiểm tra mức dùng CPU và bộ nhớ của các tiến trình đang chạy để báo cáo lại cho Ngài một cách đầy đủ nhất có thể".split(" ");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  const send = (m) => sock.send(JSON.stringify(m));
  send({ type: "stream_start" });
  await page.waitForTimeout(800);

  await page.evaluate(() => {
    window.__f = []; window.__mut = { child: 0, data: 0 }; let last = performance.now();
    const tick = (t) => {
      const tx = document.querySelector(".chat-bubble.assistant:last-of-type .bubble-text");
      window.__f.push({ t, dt: t - last, chars: tx ? tx.textContent.length : 0 });
      if (tx && !window.__mo) { window.__mo = new MutationObserver((ms) => { for (const m of ms) window.__mut[m.type === "childList" ? "child" : "data"]++; }); window.__mo.observe(tx, { childList: true, characterData: true, subtree: true }); }
      last = t; window.__raf = requestAnimationFrame(tick);
    };
    window.__raf = requestAnimationFrame(tick);
  });
  let sent = "";
  for (let i = 0; i < WORDS.length; i += 3) { const c = WORDS.slice(i, i + 3).join(" ") + " "; sent += c; send({ type: "text_chunk", text: c }); await page.waitForTimeout(140); }
  await page.waitForTimeout(1500);
  send({ type: "stream_end" });
  await page.waitForTimeout(400);

  const r = await page.evaluate(() => {
    cancelAnimationFrame(window.__raf);
    const f = window.__f, first = f.findIndex((x) => x.chars > 0), last = f.length - 1 - [...f].reverse().findIndex((x, i, a) => x.chars !== a[0].chars);
    const win = f.slice(first, last + 1), d = [];
    for (let i = 1; i < win.length; i++) d.push(win[i].chars - win[i - 1].chars);
    const mean = d.reduce((a, b) => a + b, 0) / d.length;
    const sd = Math.sqrt(d.reduce((a, b) => a + (b - mean) ** 2, 0) / d.length);
    const b = document.querySelector(".chat-bubble.assistant:last-of-type");
    return { frames: win.length, zerosFrac: d.filter((v) => v === 0).length / d.length, sd, max: Math.max(...d), child: window.__mut.child, data: window.__mut.data, text: b.querySelector(".bubble-text").textContent.trim() };
  });
  check(r.zerosFrac <= 0.06, "1. không có khung đứng hình xen kẽ (<=6% khung không thêm ký tự)", `${(r.zerosFrac * 100).toFixed(0)}% / ${r.frames} khung`);
  check(r.sd <= 0.95 && r.max <= 5, "2. số ký tự mỗi khung đều (độ lệch <=0.95, không quá 5/khung)", `sd=${r.sd.toFixed(2)} max=${r.max}`);
  check(r.data >= r.frames * 0.5 && r.child <= 6, "3. chữ thường chỉ nối vào text node: ít lần dựng lại markdown, nhiều lần nối chữ", `nối=${r.data} dựng lại=${r.child} / ${r.frames} khung`);
  check(r.text === sent.trim(), "5. chữ đủ, đúng thứ tự, không mất hay lặp ký tự", r.text === sent.trim() ? "" : `${r.text.length} vs ${sent.trim().length}`);

  // markdown vẫn đúng khi stream: **đậm** và danh sách thành thẻ thật, không còn dấu ** thô
  send({ type: "stream_start" }); await page.waitForTimeout(300);
  for (const c of ["Kết quả: **Task Manager** đã mở.\n", "- mục một\n", "- mục hai\n", "Xong thưa Ngài."]) { send({ type: "text_chunk", text: c }); await page.waitForTimeout(250); }
  await page.waitForTimeout(1200); send({ type: "stream_end" }); await page.waitForTimeout(500);
  const md = await page.evaluate(() => { const t = document.querySelector(".chat-bubble.assistant:last-of-type .bubble-text"); return { strong: t.querySelectorAll("strong,b").length, raw: t.textContent.includes("**"), text: t.textContent }; });
  check(md.strong >= 1 && !md.raw && md.text.includes("mục một") && md.text.includes("mục hai") && md.text.includes("Xong thưa Ngài."), "5b. markdown stream ra đúng (đậm, các mục, chữ cuối)", JSON.stringify(md).slice(0, 160));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
