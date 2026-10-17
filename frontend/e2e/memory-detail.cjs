// E2E: Settings → Bộ nhớ, khung chi tiết một bản ghi (user 2026-10-17).
//  - Ô nội dung dài giãn ra lấp khung (không còn 4 dòng bé xíu với khoảng trống dư dưới nút Lưu); nút Lưu nằm ở đáy khung.
//  - Workflows: "Công cụ" (tools, đã có trong Tool Chain) và "Đường dẫn Wiki" (máy tự sinh) không còn là ô sửa, chỉ hiện ở
//    Thông tin hệ thống; không còn nhãn "Chuỗi ký tự / Văn bản lớn / Số" trên từng ô.
//  - Conversations: phiên ghi rõ thiết bị (iPhone/iPad · iOS, Android, máy tính), không chỉ web-xxxxxxxx.
//  - Trang báo đúng thiết bị khi kết nối: ?device=ios / android / desktop.
// Mọi /api và /ws bị mock. Chạy: PW=<module playwright> node frontend/e2e/memory-detail.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const T = 1792200000;
const data = {
  conversations: [{ id: 412, role: "assistant", content: "Dạ, giá vàng SJC hôm nay là 140.900.000 VNĐ/lượng mua vào.", session_id: "web-3fa9c21b", created_at: T, device: "ios" }],
  outcomes: [{ id: 88, tools: "market_price", query: "giá vàng hôm nay", status: "success", result: "SJC mua 140.900.000", traces: [{ tool: "market_price", ok: true }], created_at: T }],
  workflows: [{ id: 7, tools: "market_price", intent: "tra giá thị trường", tool_chain: [{ tool: "market_price", args: { item: "vàng" } }], sample_queries: ["giá vàng hôm nay"], success_evidence: "SJC 140.9 triệu", validation_count: 12, wiki_path: "E:\\jarvis\\data\\wiki\\System\\Workflows\\market_price.md", created_at: T, updated_at: T }],
};

async function openMemory(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/memory-lock/status", (r) => r.fulfill({ json: { configured: true } }));
  await page.route("**/api/memory-lock/unlock", (r) => r.fulfill({ json: { success: true, token: "t" } }));
  await page.route("**/api/memory-control/summary", (r) => r.fulfill({ json: { success: true, counts: { conversations: 1, outcomes: 1, workflows: 1 } } }));
  await page.route("**/api/learnings/list**", (r) => r.fulfill({ json: { success: true, learnings: [], total: 0 } }));
  await page.route("**/api/conversations?**", (r) => r.fulfill({ json: { success: true, conversations: data.conversations, total: 1 } }));
  await page.route("**/api/outcomes/list**", (r) => r.fulfill({ json: { success: true, outcomes: data.outcomes, total: 1 } }));
  await page.route("**/api/workflows/list**", (r) => r.fulfill({ json: { success: true, workflows: data.workflows, total: 1 } }));
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click());
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="memory"]').click());
  await page.waitForTimeout(400);
  await page.fill("#memory-lock-input", "x"); await page.click("#memory-lock-btn");
  await page.waitForTimeout(1000);
  return page;
}
const pick = (page, kind) => page.evaluate((k) => document.querySelector(`[data-memory-kind="${k}"]`).click(), kind).then(() => page.waitForTimeout(700));
const layout = (page, field) => page.evaluate((f) => {
  const d = document.getElementById("memory-detail-container"), ta = d.querySelector(`[data-memory-field="${f}"]`), save = document.getElementById("memory-save-btn");
  const dr = d.getBoundingClientRect();
  return { panel: Math.round(dr.height), ta: Math.round(ta.getBoundingClientRect().height), gapUnderSave: Math.round(dr.bottom - save.getBoundingClientRect().bottom) };
}, field);

(async () => {
  const browser = await chromium.launch();
  const page = await openMemory(browser);

  await pick(page, "conversation");
  const c = await layout(page, "content");
  check(c.ta >= 240, "1. Conversations: ô Nội dung giãn ra lấp khung (trước: 88px, 4 dòng)", JSON.stringify(c));
  check(c.gapUnderSave <= 40, "2. nút Lưu nằm ở đáy khung (không dư khoảng trống bên dưới)", JSON.stringify(c));
  const dev = await page.evaluate(() => [...document.querySelectorAll("#memory-detail-container .sd-mem-meta-row")].map((r) => r.textContent.replace(/\s+/g, " ").trim()).find((t) => t.startsWith("Thiết bị")));
  check(dev === "Thiết bị: iPhone/iPad · iOS", "3. phiên ghi rõ thiết bị", String(dev));

  await pick(page, "outcome");
  const o = await layout(page, "result");
  check(o.ta >= 120 && o.gapUnderSave <= 40, "4. Outcomes: ô Kết quả cao ít nhất 120px (chia chỗ với Traces), nút Lưu ở đáy", JSON.stringify(o));

  await pick(page, "workflow");
  const w = await page.evaluate(() => {
    const d = document.getElementById("memory-detail-container");
    return { fields: [...d.querySelectorAll("[data-memory-field]")].map((e) => e.dataset.memoryField), meta: d.querySelector(".sd-mem-meta-card")?.textContent || "", tags: d.querySelectorAll(".sd-mem-field-type").length };
  });
  check(!w.fields.includes("tools") && !w.fields.includes("wiki_path") && w.fields.includes("tool_chain"), "5. Workflows: Công cụ và Đường dẫn Wiki không còn là ô sửa", JSON.stringify(w.fields));
  check(/market_price\.md/.test(w.meta) && /Công cụ/.test(w.meta), "6. hai trường đó vẫn xem được trong Thông tin hệ thống", w.meta.slice(0, 160));
  check(w.tags === 0, "7. không còn nhãn kiểu dữ liệu trên từng ô", String(w.tags));
  await page.close();

  // the page tells the server which device opened the session
  for (const [want, ua] of [
    ["ios", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"],
    ["android", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"],
    ["desktop", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"],
  ]) {
    const ctx = await browser.newContext({ userAgent: ua, viewport: want === "desktop" ? { width: 1280, height: 800 } : { width: 390, height: 844 }, hasTouch: want !== "desktop", isMobile: want !== "desktop" });
    const p = await ctx.newPage();
    let url = "";
    await p.routeWebSocket(/\/ws/, (ws) => { url = ws.url(); });
    await p.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
    await p.goto(BASE);
    for (let i = 0; i < 50 && !url; i++) await p.waitForTimeout(100);
    check(new URL(url).searchParams.get("device") === want, `8. ${want}: trang báo ?device=${want}`, url.replace(/^.*\?/, "?"));
    await ctx.close();
  }

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
