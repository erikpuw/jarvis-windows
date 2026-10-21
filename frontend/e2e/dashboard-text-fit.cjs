// E2E: Dashboard text fits its page on a phone (user 2026-10-18 screenshots):
//  Tổng quan: a long model name squeezed the label column until the labels broke one letter per line.
//  Thông tin: the README's list bullets hung outside the page's left edge.
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/dashboard-text-fit.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const STATUS = { success: true, env_keys_set: { llama: true }, skill_count: 2, command_count: 33,
  runtime: { llm_model: "Qwen3.5-9B-DeepSeek-V4-Flash-Q4_K_M.gguf", embed_model: "embeddinggemma-2-Q8_0", tts_engine: "vieneu", vieneu_voice: "Adam bựa" } };
const README = "# JARVIS\n\nMở đầu.\n\n## Mục lục\n\n- Tính năng\n- Định tuyến tool phẳng\n- Kiến trúc\n\n1. Bước một\n2. Bước hai\n";

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => {
    const u = r.request().url();
    if (u.includes("/api/system/readme")) return r.fulfill({ json: { success: true, content: README } });
    return r.fulfill({ json: STATUS });
  });
  await page.goto(BASE);
  await page.waitForTimeout(1500);

  // 1. Tổng quan: every label stays on one line
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click());
  await page.waitForTimeout(1200);
  const kv = await page.evaluate(() => [...document.querySelectorAll('#page-overview .sd-kv dt')].filter((d) => d.offsetParent)
    .map((d) => { const r = document.createRange(); r.selectNodeContents(d); // the text's own lines (the cell stretches to its row)
      return { t: d.textContent, lines: new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size }; }));
  const bad = kv.filter((d) => d.lines > 1);
  const model = await page.evaluate(() => { const e = document.getElementById("ov-llm-model"), p = e.closest(".sd-page-body") || document.body;
    return { right: Math.round(e.getBoundingClientRect().right), frame: Math.round(p.getBoundingClientRect().right), text: e.textContent }; });
  check(kv.length > 0 && !bad.length && model.right <= model.frame, "1. Tổng quan: nhãn không vỡ từng chữ, tên mô hình dài xuống dòng trong khung",
    JSON.stringify({ bad, model }));

  // 2. Thông tin: list bullets/numbers sit inside the text column
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="info"]').click());
  await page.waitForTimeout(1200);
  const li = await page.evaluate(() => {
    const v = document.getElementById("readme-viewer"), vl = v.getBoundingClientRect().left;
    return [...v.querySelectorAll("ul, ol")].map((l) => ({ tag: l.tagName, pad: parseFloat(getComputedStyle(l).paddingLeft), pos: getComputedStyle(l).listStylePosition,
      textLeft: Math.round(l.querySelector("li").getBoundingClientRect().left - vl) }));
  });
  check(li.length >= 2 && li.every((l) => l.pos === "inside" || l.textLeft >= 16), "2. Thông tin: dấu đầu dòng nằm trong lề chữ, không thò ra ngoài", JSON.stringify(li));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
