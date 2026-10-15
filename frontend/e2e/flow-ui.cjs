// E2E cho khung các bước (flow_tracker nằm trong đảo thông báo #error-text).
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
  await page.waitForSelector("#error-text .island-step", { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(700);

  const f = await page.evaluate(() => {
    const b = document.getElementById("error-text");
    const rows = [...b.querySelectorAll(".island-step")];
    return {
      font: getComputedStyle(b).fontFamily,
      rowFont: getComputedStyle(rows[0]).fontFamily,
      ids: b.querySelectorAll(".flow-step-id").length,
      statuses: rows.map((r) => r.dataset.status).join(","),
      text: rows.map((r) => r.querySelector(".island-step-text").textContent).join("|"),
      detail: rows[1].querySelector(".island-step-detail")?.textContent || "",
      pill: b.querySelector(".island-count").textContent,
      hasBar: !!b.querySelector(".flow-progress"),
      inChat: document.querySelectorAll(".chat-bubble.system-flow").length,
    };
  });
  check(!/mono|consolas|cascadia/i.test(f.font + f.rowFont), "1. khung bước dùng font giao diện, không monospace", f.font);
  check(f.ids === 0, "2. bỏ số thứ tự '1. 2. 3.'");
  check(f.statuses === "completed,completed,active", "3. mỗi bước có trạng thái (chấm dòng thời gian)", f.statuses);
  check(f.text === "Nhận: xin chào jarvis|Định tuyến|Đang gọi LLM" && f.detail === "general", "4. tách '→ chi tiết' thành chữ phụ, bỏ '...'", `${f.text} / ${f.detail}`);
  check(f.pill === "" && !f.hasBar && f.inChat === 0, "5. không số đếm, không thanh tiến độ (8786c87), không còn bong bóng flow trong chat", `${f.pill} · trong chat ${f.inChat}`);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
