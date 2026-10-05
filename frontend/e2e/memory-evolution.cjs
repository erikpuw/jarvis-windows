// E2E: Settings → Bộ nhớ → Evolution — đọc và sửa luật tiến hóa (STYLE.md đang áp dụng, Evolution.md nhật ký) ngay trong giao diện, một chỗ duy nhất.
//  Nhóm "Evolution" nằm cùng hàng với Learnings/Memories/...; hai bản ghi là hai file; sửa nội dung rồi lưu gọi POST /api/evolution/update {id, content};
//  không có nút xoá và ô tích chọn nhiều (đây là file, không phải bản ghi để xoá).
// Mọi /api và /ws bị mock. Chạy: PW=<module playwright> node frontend/e2e/memory-evolution.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const files = {
    style: "# Self Evolution Style Rules\n- **[MỚI]** Xưng hô thân mật.\n",
    log: "# Jarvis Evolution Log\n\n## Giao tiếp\n- Gọn, thẳng.\n",
  };
  const saves = [];
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  // Memory Control is password-locked: the fake backend accepts any password
  await page.route("**/api/memory-lock/status", (r) => r.fulfill({ json: { configured: true } }));
  await page.route("**/api/memory-lock/unlock", (r) => r.fulfill({ json: { success: true, token: "t" } }));
  await page.route("**/api/memory-lock/lock", (r) => r.fulfill({ json: { success: true } }));
  await page.route("**/api/memory-control/summary", (r) => r.fulfill({ json: { success: true, counts: {} } }));
  await page.route("**/api/learnings/list**", (r) => r.fulfill({ json: { success: true, learnings: [], total: 0 } }));
  await page.route("**/api/evolution/list**", (r) => r.fulfill({ json: { success: true, total: 2, items: [
    { id: "style", title: "STYLE.md — luật giọng điệu đang áp dụng", path: "skills/self_evolution/STYLE.md", exists: true, editable: true, content: files.style, updated_at: 1790000000 },
    { id: "log", title: "Evolution.md — nhật ký luật tiến hóa (Routing chỉ là đề xuất chờ duyệt)", path: "data/wiki/System/Evolution.md", exists: true, editable: true, content: files.log, updated_at: 1790000000 },
  ] } }));
  await page.route("**/api/evolution/update", async (r) => {
    const body = r.request().postDataJSON();
    saves.push(body); files[body.id] = body.content;
    await r.fulfill({ json: { success: true } });
  });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="memory"]').click());
  await page.waitForTimeout(400);
  await page.fill("#memory-lock-input", "x"); await page.click("#memory-lock-btn"); // Memory Control đòi mật khẩu
  await page.waitForTimeout(1000);

  const nav = await page.$$eval("#memory-category-nav .sd-mem-cat-btn", (b) => b.map((x) => `${x.dataset.memoryKind}:${x.textContent.trim().replace(/\d+$/, "")}`));
  check(nav.includes("evolution:Evolution"), "1. nhóm Evolution có trong thanh nhóm bộ nhớ", nav.join(", "));
  await page.click('[data-memory-kind="evolution"]'); await page.waitForTimeout(800);
  const cards = await page.$$eval("#memory-list-container .sd-mem-record-card", (c) => c.map((x) => x.querySelector(".sd-mem-card-title").textContent));
  check(cards.length === 2 && /STYLE\.md/.test(cards[0]) && /Evolution\.md/.test(cards[1]), "2. hai bản ghi là hai file STYLE.md và Evolution.md", cards.join(" | "));
  const ta = () => page.$eval('#memory-detail-container [data-memory-field="content"]', (t) => t.value).catch(() => null);
  check((await ta()) === files.style, "3. chọn STYLE.md → đọc được nội dung luật đang áp dụng ngay trong ô chỉnh sửa");
  const ctl = await page.evaluate(() => ({ del: !!document.getElementById("memory-delete-btn"), checks: document.querySelectorAll("#memory-list-container .sd-mem-card-check").length, save: !!document.getElementById("memory-save-btn") }));
  check(!ctl.del && ctl.checks === 0 && ctl.save, "4. file thì không có nút Xoá và ô tích chọn nhiều, có nút Lưu", JSON.stringify(ctl));

  const edited = "# Self Evolution Style Rules\n- **[MỚI]** Xưng hô thân mật.\n- Trả lời gọn.\n";
  await page.fill('#memory-detail-container [data-memory-field="content"]', edited);
  await page.click("#memory-save-btn"); await page.waitForTimeout(800);
  check(saves.length === 1 && saves[0].id === "style" && saves[0].content === edited, "5. Lưu → POST /api/evolution/update {id: style, content}", JSON.stringify(saves).slice(0, 120));
  check((await ta()) === edited, "6. sau khi lưu danh sách tải lại và ô chỉnh sửa hiện đúng nội dung mới");

  await page.click('[data-memory-record-id="log"]'); await page.waitForTimeout(500);
  check((await ta()) === files.log, "7. chọn Evolution.md → đọc được nhật ký tiến hóa");
  await page.fill('#memory-detail-container [data-memory-field="content"]', files.log + "- Thêm một luật.\n");
  await page.click("#memory-save-btn"); await page.waitForTimeout(800);
  check(saves.length === 2 && saves[1].id === "log", "8. lưu Evolution.md → id log", JSON.stringify(saves.map((s) => s.id)));

  await page.click('[data-memory-kind="learning"]'); await page.waitForTimeout(800);
  const back = await page.evaluate(() => ({ checks: document.querySelectorAll("#memory-select-all").length, evolutionBtnActive: document.querySelector('[data-memory-kind="evolution"]').classList.contains("active") }));
  check(!back.evolutionBtnActive, "9. quay lại nhóm khác thì rời khỏi Evolution bình thường", JSON.stringify(back));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
