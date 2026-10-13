// E2E: bảng Markdown trong bong bóng chat trên điện thoại (iPhone 390px) — như GitHub: chữ chỉ xuống dòng ở dấu cách,
//  KHÔNG bẻ giữa một từ ("Đá|nh giá", "Đ|ã|b|án") hay giữa một con số ("61.90|0đ"). Bảng rộng hơn bong bóng thì cuộn ngang
//  trong khung của nó; trang và bong bóng không bị kéo ngang.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/chat-table-wrap.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const TABLE = [
  "Kết quả tra giá cho **thịt bò**:",
  "",
  "| Sản phẩm | Giá niêm yết | Đánh giá | Đã bán | Nguồn |",
  "| :--- | ---: | :---: | ---: | :--- |",
  "| Thịt bò xay PTV 200g (Khay) | 61.900₫ | — | — | [Bách Hóa Xanh](https://www.bachhoaxanh.com/a) |",
  "| Nạm bò (200 g) | 49.000₫ | — | — | [Bách Hóa Xanh](https://www.bachhoaxanh.com/b) |",
  "| Đùi bò (200 g) | 58.929₫ | 5★ (3) | 1.204 | [Bách Hóa Xanh](https://www.bachhoaxanh.com/c) |",
  "",
  "#### 🔥 Giá Gas Petrolimex",
  "",
  "| Sản phẩm | Giá niêm yết | Giá ưu đãi |",
  "| :---: | :---: | :---: |",
  "| Gas Petrolimex (bình 12kg) | 644.112 VNĐ. | 580.000 VNĐ. |",
].join("\n");

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
  send({ type: "stream_start" }); await page.waitForTimeout(300);
  send({ type: "text_chunk", text: TABLE }); await page.waitForTimeout(400);
  send({ type: "stream_end" }); await page.waitForTimeout(4000);
  const r = await page.evaluate(() => {
    const bub = [...document.querySelectorAll(".chat-bubble.assistant")].pop();
    const broken = [];
    for (const cell of bub.querySelectorAll("th, td")) {
      const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const re = /\S+/g; let m;
        while ((m = re.exec(n.data))) {
          const rg = document.createRange(); rg.setStart(n, m.index); rg.setEnd(n, m.index + m[0].length);
          const tops = new Set([...rg.getClientRects()].filter((x) => x.width > 0).map((x) => Math.round(x.top)));
          if (tops.size > 1) broken.push(m[0]);
        }
      }
    }
    const wraps = [...bub.querySelectorAll(".sd-table-wrap")].map((w) => ({ sw: w.scrollWidth, cw: w.clientWidth, right: w.getBoundingClientRect().right }));
    const br = bub.getBoundingClientRect();
    return { cells: bub.querySelectorAll("td").length, broken, wraps, bubbleRight: br.right, doc: document.documentElement.scrollWidth, vw: innerWidth };
  });
  const tag = `[${label}]`;
  check(r.cells >= 18, `${tag} 0. bảng đã hiện trong bong bóng`, `${r.cells} ô`);
  check(r.broken.length === 0, `${tag} 1. không từ/số nào bị bẻ giữa chừng trong ô bảng`, JSON.stringify(r.broken.slice(0, 12)));
  check(r.wraps.every((w) => w.right <= r.bubbleRight + 1) && r.doc <= r.vw + 1, `${tag} 2. bảng nằm trong bong bóng (rộng thì cuộn ngang trong khung), trang không bị kéo ngang`, JSON.stringify({ wraps: r.wraps, bubbleRight: r.bubbleRight, doc: r.doc, vw: r.vw }));
  await browser.close();
}

(async () => {
  await run("iPhone 390", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
