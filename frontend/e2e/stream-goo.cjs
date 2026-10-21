// E2E: the stream_start loader's four blobs melt together (the goo filter is applied), not four separate balls
// (user 2026-10-19: no liquid effect anywhere). 5402d0e wrote `filter: url(data:…), url(#sl-goo)`: a comma list is not valid
// CSS, the browser dropped the whole declaration and the blob layer had no filter at all. Then (still 2026-10-19) the phone
// showed no goo with the CSS fixed: on iOS WebKit the spinning HTML blobs become their own GPU layers and a CSS url() filter on
// their parent does not reach them. The blobs are SVG shapes inside the SVG whose <g> holds the filter: one layer, always goo.
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/stream-goo.cjs   (needs `npm run dev` on :5173)
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
  await page.waitForTimeout(500);
  await page.fill("#command-input", "xin chào"); await page.press("#command-input", "Enter");
  await page.waitForTimeout(200);
  socks[socks.length - 1].send(JSON.stringify({ type: "stream_start" }));
  await page.waitForTimeout(500);
  const f = await page.evaluate(() => {
    const g = document.querySelector('.typing-loader svg g[filter="url(#sl-goo)"]');
    const blobs = g ? [...g.querySelectorAll(".blob-c")] : [];
    return { group: !!g, filterInSameSvg: !!(g && g.ownerSVGElement.querySelector("#sl-goo")), blobs: blobs.length,
      svgBlobs: blobs.every((b) => b instanceof SVGElement), spinning: blobs.every((b) => getComputedStyle(b).animationName === "stream-spin"),
      htmlDivs: document.querySelectorAll(".typing-loader div.blob-c").length };
  });
  check(f.group && f.filterInSameSvg && f.blobs === 4 && f.svgBlobs && f.spinning && f.htmlDivs === 0,
    "1. 4 giọt là hình SVG trong nhóm <g> mang bộ lọc chất lỏng (iOS cũng dính), vẫn xoay", JSON.stringify(f));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
