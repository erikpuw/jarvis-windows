// E2E: trang Thông tin (README) — chữ trong dấu ` ` (code nội tuyến) ngắn như `vi-VN`, `.env`, `@rag` KHÔNG được bị ngắt xuống dòng giữa chừng
//  (trước đây overflow-wrap:anywhere + dấu gạch làm "vi-" ở cuối dòng, "VN" nhảy xuống dòng sau). Code nội tuyến rất dài (đường dẫn, chuỗi liền không dấu cách)
//  vẫn phải tự ngắt để trang không bị kéo ngang. Bảng cuộn trong khối của nó.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/info-wrap.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const LONG = "engine/router/" + "rat_dai_khong_co_dau_cach_".repeat(8) + ".py";
const README = fs.readFileSync(path.join(__dirname, "..", "..", "README.md"), "utf8")
  + `\n\n## Thử ngắt dòng\n\nMã ngắn \`vi-VN\` và \`.env\` và \`@rag\` giữa câu dài dài dài dài dài dài dài dài dài dài dài dài. Mã dài \`${LONG}\` nằm trong đoạn.\n\n- mục: \`${LONG}\`\n`;

async function run(label, opts) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/system/readme", (r) => r.fulfill({ json: { success: true, content: README } }));
  await page.goto(BASE);
  await page.waitForTimeout(1200);
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(400);
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="info"]').click());
  await page.waitForTimeout(1500);
  const r = await page.evaluate((LONG) => {
    const v = document.getElementById("readme-viewer"), vr = v.getBoundingClientRect(), c = document.getElementById("settings-content");
    const codes = [...v.querySelectorAll(".sd-inline-code")].map((el) => ({ t: el.textContent, lines: el.getClientRects().length, right: el.getBoundingClientRect().right, inTable: !!el.closest(".sd-table-wrap") }));
    const short = codes.filter((x) => x.t.length <= 24 && !/\s/.test(x.t));
    const long = codes.filter((x) => x.t === LONG);
    return { n: codes.length, short: short.length, brokenShort: short.filter((x) => x.lines > 1).map((x) => x.t), long: long.length, longOut: long.filter((x) => !x.inTable && x.right > vr.right + 1.5).length, sw: c.scrollWidth, cw: c.clientWidth, doc: document.documentElement.scrollWidth, vw: innerWidth };
  }, LONG);
  const tag = `[${label}]`;
  check(r.short >= 5, `${tag} 0. có code nội tuyến ngắn để kiểm tra`, `${r.short}/${r.n}`);
  check(r.brokenShort.length === 0, `${tag} 1. code nội tuyến ngắn không bị ngắt xuống dòng giữa chừng`, JSON.stringify(r.brokenShort));
  check(r.long === 2 && r.longOut === 0, `${tag} 2. code nội tuyến rất dài vẫn tự ngắt, không tràn ra ngoài khung`, `${r.long} đoạn, ${r.longOut} tràn`);
  check(r.sw <= r.cw + 1 && r.doc <= r.vw + 1, `${tag} 3. trang không bị kéo ngang`, `nội dung ${r.sw}/${r.cw}, trang ${r.doc}/${r.vw}`);
  await browser.close();
}

(async () => {
  await run("điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await run("máy tính", { viewport: { width: 1280, height: 800 } });
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
