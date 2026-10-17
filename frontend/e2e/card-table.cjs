// E2E: bảng "thẻ" (mỗi cột là một món có ảnh: lịch phim CGV, game Epic) hiện thành lưới thẻ tự xuống dòng (ngài 2026-10-16:
//  lịch phim 4+ cột bị đẩy ngang, cắt mất bên phải trên điện thoại). PC: thẻ nằm ngang một hàng; điện thoại: 2 thẻ một hàng như
//  bảng game. Thẻ không cuộn ngang; bảng số liệu thường vẫn là bảng, cuộn ngang trong khung riêng (ngài 2026-10-16).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/card-table.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const { dismissWelcome } = require("./_welcome.cjs");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

// same shape as engine/tools/search_engine.py _format_cgv_table (one column per movie)
const IMG = "data:image/svg+xml;utf8," + encodeURIComponent("<svg xmlns='http://www.w3.org/2000/svg' width='200' height='300'><rect width='200' height='300' fill='%23446'/></svg>");
const M = ["TRẠI BUÔN NGƯỜI", "QUỶ ĂN TẠNG 4: HỔ TINH", "PHIM STREET FIGHTER", "THE SHEEP: “QUÁI LẠ” GHÉ NHÀ"];
const CGV = [
  "| " + M.map((t) => `**${t}**`).join(" | ") + " |",
  "|" + M.map(() => ":---:").join("|") + "|",
  "| " + M.map((t) => `![${t}](${IMG})`).join(" | ") + " |",
  "| " + M.map(() => "*Hài, Hành Động, Kinh Dị*").join(" | ") + " |",
  "| " + M.map(() => "⏱️ 111 phút").join(" | ") + " |",
  "| " + M.map(() => "📅 16-10-2026").join(" | ") + " |",
  "| " + M.map(() => "[Xem chi tiết](https://www.cgv.vn/)").join(" | ") + " |",
].join("\n");
const PRICES = "| Sản phẩm | Giá | Nguồn |\n| :--- | ---: | :--- |\n| Galaxy S24 | 19.990.000₫ | cellphones |\n| Galaxy S25 | 22.990.000₫ | https://www.thegioididong.com/dtdd/samsung-galaxy-s25-ultra-5g-256gb-titan-xam |";

async function render(browser, viewport, mobile) {
  const page = await (await browser.newContext({ viewport, isMobile: mobile, hasTouch: mobile })).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await dismissWelcome(page);
  const send = (o) => sock.send(JSON.stringify(o));
  send({ type: "stream_start" });
  send({ type: "text_chunk", text: "=== PHIM ĐANG CHIẾU TẠI CGV ===\n" + CGV + "\n\nGiá máy:\n\n" + PRICES + "\n\nXong.\n" });
  send({ type: "stream_end" });
  await page.waitForTimeout(2500);
  const r = await page.evaluate(() => {
    const b = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop(), br = b.getBoundingClientRect();
    const grid = b.querySelector(".sd-card-grid"), cards = grid ? [...grid.querySelectorAll(".sd-card")] : [];
    const rects = cards.map((c) => c.getBoundingClientRect());
    return {
      cards: cards.length,
      rows: new Set(rects.map((x) => Math.round(x.top))).size,
      inside: rects.every((x) => x.left >= br.left - 1 && x.right <= br.right + 1),
      firstCard: cards[0] ? [...cards[0].children].map((e) => e.textContent.trim() || (e.querySelector("img") ? "<img>" : "")) : [],
      tables: b.querySelectorAll("table.sd-table").length,
      tableInside: [...b.querySelectorAll(".sd-table-wrap")].every((w) => w.getBoundingClientRect().right <= br.right + 1),
      // only a data table's own frame may scroll sideways (user 2026-10-16), never the cards
      scrollers: [...b.querySelectorAll("*")].filter((e) => ["auto", "scroll"].includes(getComputedStyle(e).overflowX)).map((e) => e.className),
      // chat history never pans sideways, even if something inside is too wide (user 2026-10-16)
      historyPan: (() => {
        const h = document.getElementById("chat-history"), cs = getComputedStyle(h);
        return { overflowX: cs.overflowX, touchAction: cs.touchAction, wider: h.scrollWidth - h.clientWidth };
      })(),
    };
  });
  await page.context().close();
  return r;
}

(async () => {
  const browser = await chromium.launch();
  const phone = await render(browser, { width: 390, height: 844 }, true);
  check(phone.cards === 4 && phone.inside, "1. điện thoại: bảng phim thành 4 thẻ, không thẻ nào tràn khỏi bong bóng", JSON.stringify(phone));
  check(phone.rows === 2, "2. điện thoại: 2 thẻ một hàng (2 hàng), như bảng game", String(phone.rows));
  check(phone.firstCard[0] === "TRẠI BUÔN NGƯỜI" && phone.firstCard[1] === "<img>" && phone.firstCard.includes("⏱️ 111 phút"), "3. mỗi thẻ: tên, ảnh, thể loại, thời lượng, ngày, link xếp dọc theo đúng cột", JSON.stringify(phone.firstCard));
  check(phone.tables === 1 && phone.scrollers.every((c) => c.includes("sd-table-wrap")), "4. bảng số liệu (không ảnh) vẫn là bảng, cuộn ngang trong khung riêng; thẻ không cuộn", JSON.stringify({ tables: phone.tables, scrollers: phone.scrollers }));
  check(phone.tableInside, "7. khung bảng giá (cuộn ngang bên trong) không tràn khỏi bong bóng", String(phone.tableInside));
  check(["hidden", "clip"].includes(phone.historyPan.overflowX) && phone.historyPan.touchAction === "pan-y" && phone.historyPan.wider <= 0, "6. lịch sử chat khoá kéo ngang (nội dung quá rộng cũng không kéo được)", JSON.stringify(phone.historyPan));
  const pc = await render(browser, { width: 1280, height: 800 }, false);
  check(pc.cards === 4 && pc.rows === 1 && pc.inside, "5. PC: 4 thẻ nằm ngang một hàng", JSON.stringify({ cards: pc.cards, rows: pc.rows, inside: pc.inside }));
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
