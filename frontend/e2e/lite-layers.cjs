// E2E: giao diện nhẹ cho GPU (đã đo: lớp ẩn bằng opacity:0 vẫn tốn ~9% công vẽ, backdrop-filter là phần nặng nhất).
//  - Không còn backdrop-filter nào (CSS, template trong main.ts, và lúc chạy sau khi chat + mở các panel).
//  - Panel bản đồ khi ẩn là display:none (không còn lớp ghép tranh nhau vẽ); mở ra thì hiện, đóng thì ẩn lại.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/lite-layers.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const SRC = path.join(__dirname, "..", "src");
const files = [["style.css"], ["main.ts"], ["settings", "styles.css"]].map((p) => path.join(SRC, ...p));
const hits = files.flatMap((f) => fs.readFileSync(f, "utf8").split("\n").map((l, i) => [path.basename(f), i + 1, l]).filter(([, , l]) => /backdrop-filter\s*:\s*(?=\S)(?!none)/i.test(l)));
check(hits.length === 0, "1. không còn khai báo backdrop-filter nào trong CSS/main.ts", hits.slice(0, 3).map((h) => h[0] + ":" + h[1]).join(" "));

async function session(browser, opts) {
  const page = await (await browser.newContext(opts)).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true }, history: [] } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  return { page, sock };
}
const disp = (page, id) => page.$eval("#" + id, (e) => getComputedStyle(e).display);

(async () => {
  const browser = await chromium.launch();
  for (const [label, opts] of [["điện thoại", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }], ["máy tính", { viewport: { width: 1280, height: 800 } }]]) {
    const { page, sock } = await session(browser, opts);
    check((await disp(page, "map-panel")) === "none", `2. ${label}: panel bản đồ khi ẩn là display:none`, await disp(page, "map-panel"));
    await page.evaluate(() => document.getElementById("btn-map").click());
    await page.waitForTimeout(900);
    check((await disp(page, "map-panel")) !== "none", `5. ${label}: mở bản đồ → hiện`, await disp(page, "map-panel"));
    await page.evaluate(() => document.getElementById("btn-close-map").click());
    await page.waitForTimeout(900);
    check((await disp(page, "map-panel")) === "none", `6. ${label}: đóng bản đồ → display:none lại`, await disp(page, "map-panel"));
    for (let n = 0; n < 3; n++) {
      sock.send(JSON.stringify({ type: "stream_start" })); await page.waitForTimeout(150);
      sock.send(JSON.stringify({ type: "text_chunk", text: "Câu trả lời " + n })); await page.waitForTimeout(200);
      sock.send(JSON.stringify({ type: "stream_end" })); await page.waitForTimeout(200);
    }
    await page.evaluate(() => document.getElementById("btn-menu").click()); await page.waitForTimeout(300);
    const blur = await page.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => { const s = getComputedStyle(e); return (s.backdropFilter || s.webkitBackdropFilter || "none") !== "none"; }).map((e) => e.id || e.className.toString().split(" ")[0]).slice(0, 5));
    check(blur.length === 0, `7. ${label}: chạy thật (chat + menu): không phần tử nào còn backdrop-filter`, blur.join(","));
    await page.context().close();
  }
  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
