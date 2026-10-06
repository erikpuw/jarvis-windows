// E2E cho khung các bước (flow_tracker) và thẻ agent (flow_agents) sau khi thiết kế lại.
// WebSocket bị mock và tự phát một lượt chạy; không chạm JARVIS thật.
// Chạy: PW=<module playwright> node frontend/e2e/flow-ui.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForFunction(() => true);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  const send = (m) => sock.send(JSON.stringify(m));
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));

  send({ type: "stream_start" });
  send({ type: "flow_step", step: { id: 1, label: "Nhận: xin chào jarvis", status: "completed" } });
  send({ type: "flow_step", step: { id: 2, label: "Định tuyến → general", status: "completed" } });
  send({ type: "flow_step", step: { id: 3, label: "Đang gọi LLM...", status: "active" } });
  send({ type: "interactive", card: { id: "t1", type: "tracker", title: "💻 Agent Desktop", status: "active", label: "Thực thi: mở Task Manager" } });
  send({ type: "interactive", card: { id: "t2", type: "tracker", title: "🧪 Agent Newbie", status: "completed", label: "chạy thử" } });
  await page.waitForSelector(".chat-bubble.system-flow .flow-step-row", { timeout: 5000 }).catch(() => {});
  await page.evaluate(() => document.querySelector(".chat-bubble.system-flow")?.classList.add("flow-expanded"));
  await page.waitForTimeout(400);

  const f = await page.evaluate(() => {
    const b = document.querySelector(".chat-bubble.system-flow");
    const rows = [...b.querySelectorAll(".flow-step-row")];
    return {
      font: getComputedStyle(b).fontFamily,
      rowFont: getComputedStyle(rows[0]).fontFamily,
      ids: b.querySelectorAll(".flow-step-id").length,
      statuses: rows.map((r) => r.dataset.status).join(","),
      text: rows.map((r) => r.querySelector(".flow-step-text").textContent).join("|"),
      detail: rows[1].querySelector(".flow-step-detail")?.textContent || "",
      pill: b.querySelector(".flow-step-count").textContent,
      hasBar: !!b.querySelector(".flow-progress"),
    };
  });
  check(!/mono|consolas|cascadia/i.test(f.font + f.rowFont), "1. khung bước dùng font giao diện, không monospace", f.font);
  check(f.ids === 0, "2. bỏ số thứ tự '1. 2. 3.'");
  check(f.statuses === "completed,completed,active", "3. mỗi bước có trạng thái (chấm dòng thời gian)", f.statuses);
  check(f.text === "Nhận: xin chào jarvis|Định tuyến|Đang gọi LLM" && f.detail === "general", "4. tách '→ chi tiết' thành chữ phụ, bỏ '...'", `${f.text} / ${f.detail}`);
  check(f.pill === "2/3" && !f.hasBar, "5. số đếm bước (đã bỏ thanh tiến độ)", f.pill);

  const t = await page.evaluate(() => [...document.querySelectorAll(".tracker-card")].map((c) => ({
    name: c.querySelector(".tracker-name")?.textContent,
    label: c.querySelector(".tracker-label")?.textContent,
    icon: !!c.querySelector(".tracker-agent-icon morph-icon"),
    glyph: c.querySelector(".tracker-icon-container morph-icon")?.getAttribute("size"),
    oldTitle: !!c.querySelector(".interactive-card-title"),
    font: getComputedStyle(c.querySelector(".tracker-name") || c).fontFamily,
  })));
  check(t[0]?.name === "Agent Desktop" && t[0]?.icon && !t[0]?.oldTitle, "6. thẻ agent: icon lucide + tên, bỏ emoji", JSON.stringify(t[0]));
  check(t[0]?.label === "mở Task Manager", "7. bỏ tiền tố 'Thực thi:'", t[0]?.label);
  check(t[0]?.glyph === "14", "8. dấu trạng thái 14px, cùng cỡ khung bước", t[0]?.glyph);
  check(t[1]?.name === "Agent Newbie" && t[1]?.icon, "9. agent mới chưa có trong bảng vẫn có icon mặc định", JSON.stringify(t[1]));
  check(t[0]?.font === f.font, "10. cùng font với khung bước", `${t[0]?.font} vs ${f.font}`);
  const h = await page.$eval('[data-card-id="t1"]', (e) => Math.round(e.closest(".chat-bubble").getBoundingClientRect().height));
  check(h <= 44, "10b. khung thẻ agent mỏng, ôm sát nội dung", `${h}px`);
  const gap = await page.evaluate(() => {
    const f = document.querySelector(".chat-bubble.system-flow").getBoundingClientRect();
    const c = document.querySelector('[data-card-id="t1"]').closest(".chat-bubble").getBoundingClientRect();
    return Math.round(c.top - f.bottom);
  });
  check(gap <= 8, "10c. khung bước và thẻ agent sát nhau", `${gap}px`);
  const w = await page.evaluate(() => {
    const b = document.querySelector(".chat-bubble.system-flow");
    const r = b.getBoundingClientRect(), pill = b.querySelector(".flow-step-count").getBoundingClientRect();
    const chev = b.querySelector(".flow-chevron").getBoundingClientRect();
    const card = document.querySelector('[data-card-id="t1"]').closest(".chat-bubble").getBoundingClientRect();
    return { right: Math.round(r.right - chev.right), pillGap: Math.round(chev.left - pill.right), width: Math.round(r.width), card: Math.round(card.width) };
  });
  check(w.right <= 14 && w.pillGap <= 10, "10d. số đếm + mũi tên nằm sát mép phải khung", JSON.stringify(w));
  check(w.width >= w.card, "10e. khung bước không hẹp hơn thẻ agent", JSON.stringify(w));

  send({ type: "interactive", card: { id: "t1", type: "tracker", title: "💻 Agent Desktop", status: "completed", label: "Thực thi: mở Task Manager" } });
  await page.waitForTimeout(200);
  const done = await page.evaluate(() => { const c = document.querySelector('[data-card-id="t1"] .tracker-card'); return [c.className, c.querySelector(".tracker-name").textContent]; });
  check(done[0].includes("completed") && done[1] === "Agent Desktop", "11. đổi trạng thái vá tại chỗ", done.join(" | "));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
