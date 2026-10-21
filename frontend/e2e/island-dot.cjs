// E2E: the Dynamic Island's progress dots sit dead centre (user 2026-10-18: "icon tiến trình bị lệch"). The running step's
// ring (15px, 1.5px border, spinning) held a 4px dot whose edges fell on half pixels (5.5px in): the browser rounded them
// differently as the ring turned, so the blue dot wobbled off the ring's centre. Its edges must sit on whole pixels and
// its centre on the ring's; the done/failed glyphs too.
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/island-dot.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const socks = [];
  await page.routeWebSocket(/\/ws/, (ws) => { socks.push(ws); });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !socks.length; i++) await page.waitForTimeout(100);
  const send = (o) => socks[socks.length - 1].send(JSON.stringify(o));
  await page.waitForTimeout(600);
  send({ type: "stream_start" });
  send({ type: "flow_step", step: { id: 1, label: "Nhận: xin chào", status: "completed" } });
  send({ type: "flow_step", step: { id: 2, label: "Lỗi công cụ", status: "failed" } });
  send({ type: "flow_step", step: { id: 3, label: "Đang gọi LLM...", status: "active" } });
  await page.waitForTimeout(1000);
  await page.click("#error-text .island-pill");
  await page.waitForTimeout(900);

  // measured unrotated: offsets inside the dot's border box, from layout (offsetLeft/Top are not touched by the spin)
  const m = await page.evaluate(() => [...document.querySelectorAll(".island-step")].map((st) => {
    const d = st.querySelector(".timeline-dot");
    d.style.animation = "none";
    const dr = d.getBoundingClientRect();
    const g = st.dataset.status === "active" ? st.querySelector(".timeline-dot-inner") : st.querySelector(".timeline-dot svg");
    const gr = g.getBoundingClientRect();
    const left = gr.left - dr.left, top = gr.top - dr.top;
    d.style.animation = "";
    return { s: st.dataset.status, left: +left.toFixed(2), top: +top.toFixed(2), w: +gr.width.toFixed(2), dx: +((left + gr.width / 2) - dr.width / 2).toFixed(2), dy: +((top + gr.height / 2) - dr.height / 2).toFixed(2) };
  }));
  const whole = (v) => Math.abs(v - Math.round(v)) < 0.01;
  check(m.length === 3 && m.every((g) => Math.abs(g.dx) < 0.01 && Math.abs(g.dy) < 0.01 && whole(g.left) && whole(g.top)),
    "1. chấm/icon tiến trình đúng tâm vòng, mép rơi đúng điểm ảnh nguyên (không lệch khi vòng quay)", JSON.stringify(m));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
