// E2E cho Graphfy tự sinh từ code (/api/graphfy). Mọi /api và /ws đều bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/graphfy.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

const MAP = {
  success: true,
  nodes: [
    { id: "server", label: "server", lane: "input" },
    { id: "router", label: "router", lane: "turn" },
    { id: "orchestrator", label: "orchestrator", lane: "turn" },
    { id: "server/llm_server", label: "llm_server", lane: "llm" },
    { id: "server/voice_streamer", label: "voice_streamer", lane: "output" },
    { id: "core/learning", label: "learning", lane: "memory" },
    { id: "core/dream", label: "dream", lane: "background" },
    { id: "core/json_parser", label: "json_parser", lane: "support" },
    { id: "newpkg", label: "newpkg", lane: "other" },
  ],
  edges: [
    { from: "server", to: "router", kind: "import" },
    { from: "router", to: "orchestrator", kind: "import" },
    { from: "router", to: "server/llm_server", kind: "llm" },
    { from: "orchestrator", to: "server/llm_server", kind: "llm" },
    { from: "core/dream", to: "server/llm_server", kind: "llm" },
    { from: "orchestrator", to: "server/voice_streamer", kind: "import" },
    { from: "server", to: "core/learning", kind: "import" },
    { from: "router", to: "core/json_parser", kind: "import" },
    { from: "newpkg", to: "router", kind: "import" },
  ],
};

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.routeWebSocket(/\/ws/, () => {});
  let graphCalls = 0;
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true } }));
  await page.route("**/api/settings/status**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/graphfy", (r) => { graphCalls++; return r.fulfill({ json: MAP }); });
  await page.goto(BASE);
  await page.evaluate(() => localStorage.setItem("jarvis.graphfy.positions.v3", '{"router":[5000,5000]}'));
  await page.click("#btn-menu");
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForSelector("#settings-container.open");
  await page.click('.sd-nav-item[data-page="graphfy"]');
  await page.waitForSelector("#graphfy-map .gf-node", { timeout: 5000 }).catch(() => {});

  const ids = await page.$$eval("#graphfy-map .gf-node", (els) => els.map((e) => e.dataset.id));
  check(graphCalls >= 1 && ids.length === MAP.nodes.length, "1. khối lấy từ /api/graphfy", ids.join(","));
  check(ids.includes("newpkg"), "2. module mới tự hiện (làn Khác)");
  const lanes = await page.$$eval("#graphfy-map .gf-lane-title", (els) => els.map((e) => e.textContent));
  check(lanes.length >= 7, "3. có tiêu đề làn", lanes.join(" | "));

  const box = (id) => page.$eval(`#graphfy-map .gf-node[data-id="${id}"]`, (e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
  const llm = await box("server/llm_server"), router = await box("router"), voice = await box("server/voice_streamer");
  check(llm.x > router.x && llm.x < voice.x, "4. LLM ở trục giữa (giữa luồng xử lý và phản hồi)", JSON.stringify({ llm, router, voice }));
  check(router.h <= 40, "5. khối thường nhỏ", String(router.h));
  const brain = await page.evaluate(() => {
    const n = document.querySelector('#graphfy-map .gf-node[data-id="server/llm_server"]');
    return { brain: !!n.querySelector(".gf-brain"), traces: n.querySelectorAll(".gf-brain-trace").length, box: !!n.querySelector(".gf-node-box") };
  });
  check(brain.brain && brain.traces >= 5 && !brain.box, "5b. LLM là khối bộ não, có mạch chạy xung", JSON.stringify(brain));
  check(llm.h >= 100 && llm.w < llm.h * 1.1, "5c. khối não to, dáng gọn ngang", JSON.stringify(llm));
  const ends = await page.$$eval('#graphfy-map .gf-link[data-to="server/llm_server"] path', (ps) => ps.map((p) => { const t = p.getTotalLength(); const e = p.getPointAtLength(t); return [Math.round(e.x), Math.round(e.y)]; }));
  const nb = await page.$eval('#graphfy-map .gf-node[data-id="server/llm_server"]', (n) => { const m = n.transform.baseVal.consolidate().matrix; const b = n.getBBox(); return { x: m.e, y: m.f, w: b.width, h: b.height }; });
  check(ends.every(([x, y]) => x >= nb.x - 2 && x <= nb.x + nb.w + 2 && y >= nb.y - 2 && y <= nb.y + nb.h + 2), "5d. đường gọi LLM cắm vào khối não", JSON.stringify({ ends, nb }));
  // side edges must touch the drawn outline, not stop at the empty box edge
  const outline = await page.$eval('#graphfy-map .gf-node[data-id="server/llm_server"] .gf-brain-lines', (g) => {
    const svg = g.ownerSVGElement, r = g.getBoundingClientRect(), m = svg.getScreenCTM().inverse();
    const a = new DOMPoint(r.left, r.top).matrixTransform(m), b = new DOMPoint(r.right, r.bottom).matrixTransform(m);
    return { l: Math.round(a.x), r: Math.round(b.x) };
  });
  const sideGaps = ends.filter(([, y]) => y < nb.y + nb.h * 0.8).map(([x]) => Math.min(Math.abs(x - outline.l), Math.abs(x - outline.r)));
  check(sideGaps.every((g) => g <= 3), "5e. đường hai bên chạm viền não, không hở", JSON.stringify({ sideGaps, outline }));
  check((await box("router")).x < 1440, "6. vị trí lưu từ bản vẽ tay cũ (v3) bị bỏ qua");

  const llmEdges = await page.$$eval('#graphfy-map .gf-link[data-kind="llm"]', (els) => els.length);
  check(llmEdges === 3, "7. đường gọi LLM được đánh dấu", String(llmEdges));
  const dim = await page.$eval('#graphfy-map .gf-link[data-to="core/json_parser"]', (e) => parseFloat(getComputedStyle(e).opacity));
  check(dim < 0.5, "8. module hỗ trợ bị làm mờ", String(dim));
  const pulses = await page.$$eval("#graphfy-map .gf-link", (els) => els.map((e) => [e.dataset.to, !!e.querySelector("animateMotion")]));
  const kinds = await page.$$eval("#graphfy-map .gf-link", (els) => els.map((e) => e.dataset.kind));
  check(pulses.every(([, p], i) => p === (kinds[i] === "llm")), "9. xung sáng chỉ chạy trên đường gọi LLM (đỡ rối)", JSON.stringify(pulses));
  // edges to the shared hubs (server, tools, UIUX) are hidden until "Hiện tất cả"
  const hubShown = () => page.$eval('#graphfy-map .gf-link[data-from="server"][data-to="router"]', (e) => getComputedStyle(e).display !== "none");
  check(!(await hubShown()), "9b. đường import tới khối dùng chung (server) ẩn mặc định");
  await page.click("#btn-graphfy-all");
  check(await hubShown(), "9c. bấm Hiện tất cả: đường tới server hiện lại");
  await page.click("#btn-graphfy-all");

  await page.hover('#graphfy-map .gf-node[data-id="core/dream"]');
  const hl = await page.$$eval("#graphfy-map .gf-link", (els) => els.map((e) => [e.dataset.from + ">" + e.dataset.to, e.classList.contains("gf-dim")]));
  const lit = hl.filter(([, d]) => !d).map(([k]) => k);
  check(lit.length === 1 && lit[0] === "core/dream>server/llm_server", "10. rê chuột: chỉ sáng đường của khối", JSON.stringify(lit));
  const empty = await page.$eval("#graphfy-map svg", (svg) => { const r = svg.getBoundingClientRect(); return { x: r.x + r.width * 0.5, y: r.y + 8 }; });
  await page.mouse.move(empty.x, empty.y);
  await page.waitForTimeout(100);
  check((await page.$$eval("#graphfy-map .gf-dim", (e) => e.length)) === 0, "10b. chuột ra chỗ trống trong sơ đồ → hiện lại mọi luồng");
  const tip = await page.$eval('#graphfy-map .gf-node[data-id="core/dream"] title', (e) => e.textContent);
  check(tip.includes("engine/core/dream.py"), "11. rê chuột thấy file nguồn", tip);

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
