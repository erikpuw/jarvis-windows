// E2E: Tổng quan is a flat page that answers "is JARVIS OK?" first (impeccable critique 2026-10-18, user picked
// "Tổng quan + trang phẳng"): one status line on top naming the failed services, the hardware numbers in one compact row,
// then flat sections — no card boxes, no boxes inside boxes. Phone and PC.
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/dashboard-overview.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const STATUS = (ok) => ({ success: true, env_keys_set: { llama: true }, intelligence_core_ok: true, server_engine_ok: true, llm_server_ok: ok,
  tts_server_ok: true, uptime_seconds: 5400, server_port: 8340, memory_count: 3, conversation_turn_count: 40, task_count: 0, skill_count: 2,
  command_count: 33, mcp_connected: 1, mcp_total: 2, mentions_count: 4, session_tokens: { total: 36076, input: 33849, output: 2227 },
  system: { cpu_percent: 37, ram_percent: 61, ram_used_gb: 19.5, ram_total_gb: 32, gpus: [] }, open_apps: ["cua-driver", "WindowsTerminal"],
  runtime: { llm_model: "Qwen3.5-9B-DeepSeek-V4-Flash-Q4_K_M.gguf", embed_model: "embeddinggemma-2-Q8_0", tts_engine: "vieneu", vieneu_voice: "Adam" } });
const HEALTH = (ok) => ({ status: "online", llm: { status: ok ? "online" : "offline" }, database: { ok: true, size_kb: 900 }, rag: { enabled: true, total_chunks: 10 } });

async function open(browser, viewport, ok) {
  const page = await (await browser.newContext({ viewport })).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => {
    const u = r.request().url();
    if (u.includes("/api/health/detailed")) return r.fulfill({ json: HEALTH(ok) });
    return r.fulfill({ json: STATUS(ok) });
  });
  await page.goto(BASE);
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click());
  await page.waitForTimeout(1500);
  return page;
}
const summary = (page) => page.evaluate(() => {
  const s = document.getElementById("ov-summary"), body = document.querySelector("#page-overview .sd-page-body") || document.getElementById("page-overview");
  if (!s) return null;
  const first = [...body.querySelectorAll("*")].find((e) => !e.contains(s) && e.offsetParent && e.getBoundingClientRect().height > 0); // wrappers of the line do not count
  return { text: s.textContent.replace(/\s+/g, " ").trim(), top: Math.round(s.getBoundingClientRect().top), isFirst: !!first && s.contains(first) };
});

(async () => {
  const browser = await chromium.launch();

  // 1-2. status line first: names what failed; all good says so
  const bad = await open(browser, { width: 1440, height: 900 }, false);
  const sb = await summary(bad);
  check(sb && sb.isFirst && /2 dịch vụ lỗi/.test(sb.text) && /Máy chủ LLM/.test(sb.text) && /Dịch vụ LLM/.test(sb.text),
    "1. dòng trạng thái đứng đầu trang, nêu số và tên dịch vụ lỗi", JSON.stringify(sb));
  // 3. flat: no card boxes on the page, nothing boxed inside a box
  const flat = await bad.evaluate(() => {
    const page = document.getElementById("page-overview");
    const boxed = [...page.querySelectorAll("*")].filter((e) => e.offsetParent && parseFloat(getComputedStyle(e).borderTopWidth) > 0
      && parseFloat(getComputedStyle(e).borderLeftWidth) > 0 && e.getBoundingClientRect().height > 30);
    return { cards: page.querySelectorAll(".sd-card").length, boxed: boxed.map((e) => e.className || e.tagName).slice(0, 6) };
  });
  check(flat.cards === 0 && flat.boxed.length === 0, "3. trang phẳng: không thẻ, không hộp lồng hộp", JSON.stringify(flat));
  await bad.context().close();

  const good = await open(browser, { width: 1440, height: 900 }, true);
  const sg = await summary(good);
  check(sg && /Tất cả dịch vụ hoạt động/.test(sg.text), "2. mọi dịch vụ chạy: dòng trạng thái báo ổn", JSON.stringify(sg));
  await good.context().close();

  // 4. phone: the status line, the hardware (2 x 2, was four cards ~520px tall) and the services start in the first screen
  const ph = await open(browser, { width: 390, height: 844 }, false);
  const p = await ph.evaluate(() => {
    const s = document.getElementById("ov-summary").getBoundingClientRect(), m = document.getElementById("ov-metrics")?.getBoundingClientRect();
    const svc = document.getElementById("section-status")?.getBoundingClientRect();
    return { summaryTop: Math.round(s.top), metricsH: m ? Math.round(m.height) : -1, servicesTop: svc ? Math.round(svc.top) : -1, vh: innerHeight };
  });
  check(p.summaryTop < 260 && p.metricsH > 0 && p.metricsH <= 200 && p.servicesTop > 0 && p.servicesTop < p.vh,
    "4. điện thoại: trạng thái + hàng số liệu gọn + danh sách dịch vụ đều trong màn đầu", JSON.stringify(p));
  const cpu = await ph.textContent("#ov-cpu-val");
  check(/37/.test(cpu), "5. số CPU vẫn lấy từ status", cpu);
  await ph.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
