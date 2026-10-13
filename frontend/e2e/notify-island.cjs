// E2E: "đảo động" thông báo (Dynamic Island, kiểu Sileo) ở chính giữa mép trên, thay cho dòng #error-text và khung flow-tracker trong chat.
//  - Khung các bước xử lý (flow-tracker: flow_step) và lỗi hệ thống nằm trong đảo: viên thuốc rộng đúng bằng chữ (trạng thái + bước hiện tại + số đếm) có viền sáng mỏng;
//    bấm vào thì thẻ rũ xuống dưới liệt kê các bước. Thẻ agent (flow_agents) vẫn nằm trong khu bong bóng chat.
//  - MẶC ĐỊNH KHÔNG BAO GIỜ tự popup: thông báo mới chỉ hiện viên thuốc, bấm vào mới bung thẻ (kể cả khi có media/webcam: thẻ nằm trên cả hai lớp đó).
//  - Thẻ mở ra mà 5 giây không chạm thì tự thu về viên thuốc; trên máy tính chuột còn nằm trong thẻ thì không thu, rời chuột đi trong 5 giây thì thu.
//  - Chữ trong thẻ hiện cùng lúc với khung thẻ (không hiện trước khung).
//  - Chữ đổi dài/ngắn: viên thuốc co giãn cùng lúc với chữ (chữ không tràn ra ngoài nền trước).
//  - Biến mất: viên thuốc thu ngang vào giữa trong ~0,3 giây, icon + chữ + số đếm bị xoá mờ dần và bám theo nhanh hơn (~0,25 giây), thu về là biến mất luôn (không còn vệt hẹp); KHÔNG trượt lên.
//  - PC và điện thoại cùng một kiểu: một đường viền SVG (cổ nối cong, nền đen trong suốt 80%, viền cực mỏng nhưng liền nét), không bộ lọc.
//  - Thẻ bung ra không rộng sát hai mép màn hình và không che nút menu điều khiển; bung/thu mượt (không đo lại bố cục ở mỗi khung hình).
//  - Cài đặt hoặc bản đồ toàn màn hình che được đảo. Lỗi hệ thống (showError) vào cùng khu vực thông báo này.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/notify-island.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const mobile = (width, height, dpr) => ({ viewport: { width, height }, deviceScaleFactor: dpr, isMobile: true, hasTouch: true });

async function open(opts) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(opts)).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.addInitScript(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError")); });
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  const send = (m) => sock.send(JSON.stringify(m));
  const st = () => page.evaluate(() => {
    const r = document.getElementById("error-text"), pill = r.querySelector(".island-pill"), rect = r.getBoundingClientRect(), cs = getComputedStyle(r);
    const pr = pill.getBoundingClientRect(), pRect = r.querySelector(".island-pill-rect"), bRect = r.querySelector(".island-body-rect"), fp = pRect.getBoundingClientRect(), fc = bRect.getBoundingClientRect(), canvas = getComputedStyle(r.querySelector(".island-canvas"));
    return {
      state: r.dataset.state, kind: r.dataset.kind, vis: cs.visibility, op: parseFloat(cs.opacity), z: parseInt(cs.zIndex) || 0,
      cx: rect.left + rect.width / 2, top: rect.top, vw: innerWidth,
      pillCx: (pr.left + pr.right) / 2, pillL: pr.left, pillR: pr.right,
      fillPillW: fp.width, fillPillH: fp.height, pillBottom: fp.bottom, canvasOp: canvas.opacity, canvasFilter: canvas.filter, fillColor: getComputedStyle(pRect).fill,
      cardW: fc.width, cardH: fc.height, cardL: fc.left, cardR: fc.right, cardTop: fc.top,
      label: pill.querySelector(".island-label").textContent, count: pill.querySelector(".island-count").textContent, expanded: pill.getAttribute("aria-expanded"),
      labelOp: parseFloat(getComputedStyle(pill.querySelector(".island-label")).opacity),
      rows: [...r.querySelectorAll(".island-step")].map((x) => x.dataset.status + ":" + x.querySelector(".island-step-text").textContent).join("|"),
      err: r.querySelector(".island-error").textContent, flowBubbles: document.querySelectorAll(".chat-bubble.system-flow").length,
    };
  });
  return { browser, page, send, st };
}
const flow = (send, activeLast = true) => {
  send({ type: "stream_start" });
  send({ type: "flow_step", step: { id: 1, label: "Nhận: xin chào jarvis", status: "completed" } });
  send({ type: "flow_step", step: { id: 2, label: "Định tuyến → general", status: "completed" } });
  send({ type: "flow_step", step: { id: 3, label: "Đang gọi LLM...", status: activeLast ? "active" : "completed" } });
};
const finish = (send) => send({ type: "flow_step", step: { id: 3, label: "Đang gọi LLM...", status: "completed" } });
// viên thuốc (và thẻ bung ra) có nằm trên cùng không (z-index: đảo phải nằm trên chat, đồng hồ, media, webcam)
const islandOnTop = (page) => page.evaluate(() => {
  const root = document.getElementById("error-text"), pill = root.querySelector(".island-pill").getBoundingClientRect();
  const hit = (x, y) => { const el = document.elementFromPoint(x, y); return !!el && !!el.closest("#error-text"); };
  let ok = hit(pill.left + pill.width / 2, pill.top + pill.height / 2);
  if (root.dataset.state === "open") { const p = root.querySelector(".island-panel").getBoundingClientRect(); ok = ok && hit(p.left + p.width / 2, p.top + Math.min(p.height / 2, 40)); }
  return ok;
});
const tapPill = async (page, hasHover) => {
  if (hasHover) { await page.click("#error-text .island-pill"); return; }
  const r = await page.evaluate(() => { const b = document.querySelector("#error-text .island-pill").getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; });
  await page.touchscreen.tap(r[0], r[1]);
};

async function run(label, opts, hasHover) {
  const tag = `[${label}]`;
  const { browser, page, send, st } = await open(opts);
  await page.waitForTimeout(1200); // CSS của chế độ dev được nạp cùng JS: đợi hiệu ứng ẩn ban đầu xong
  let s = await st();
  check(s.state === "hidden" && (s.vis === "hidden" || s.op === 0), `${tag} 1. chưa có thông báo: đảo ẩn`, JSON.stringify([s.state, s.vis, s.op]));

  // --- thông báo mới: chỉ hiện viên thuốc, KHÔNG tự popup ---
  flow(send);
  await page.waitForTimeout(900);
  s = await st();
  check(s.state === "pill" && s.vis === "visible" && s.cardH < 4, `${tag} 2. có thông báo mới: chỉ hiện viên thuốc, KHÔNG tự bung popup`, JSON.stringify([s.state, s.vis, Math.round(s.cardH)]));
  check(s.flowBubbles === 0, `${tag} 3. không còn bong bóng flow trong chat`, `flow ${s.flowBubbles}`);
  check(s.rows === "completed:Nhận: xin chào jarvis|completed:Định tuyến|active:Đang gọi LLM" && s.label === "Đang gọi LLM" && s.count === "2/3", `${tag} 4. viên thuốc: bước hiện tại và số đếm; đủ các bước theo trạng thái`, `${s.label} · ${s.count} · ${s.rows}`);
  check(Math.abs(s.pillCx - s.vw / 2) <= 2 && Math.abs(s.cx - s.vw / 2) <= 2 && s.top >= 0 && s.top <= 24, `${tag} 5. top-center mặc định: viên thuốc nằm giữa mép trên màn hình`, `giữa ${Math.round(s.pillCx)}/${s.vw / 2} · cách mép ${Math.round(s.top)}px`);
  { // nền đảo sáng hơn nền trang (tối) một chút để tách ra, nhưng chữ trắng vẫn đọc rõ (tương phản ≥ 7:1)
    const rgb = (s.fillColor.match(/\d+/g) || []).map(Number), lum = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    const L = 0.2126 * lum(rgb[0]) + 0.7152 * lum(rgb[1]) + 0.0722 * lum(rgb[2]), contrast = 1.05 / (L + 0.05);
    check(L >= 0.02 && contrast >= 7 && parseFloat(s.canvasOp) >= 0.85 && s.canvasFilter.includes("island-goo"), `${tag} 6. nền đảo sáng hơn nền trang (không chìm vào nền tối) mà chữ trắng vẫn rõ, dựng như Sileo (hai rect dưới bộ lọc goo)`, `${s.fillColor} · độ sáng ${L.toFixed(3)} · tương phản chữ trắng ${contrast.toFixed(1)}:1 · độ đậm ${s.canvasOp}`);
  }
  const zl = await page.evaluate(() => Object.fromEntries(["jarvis-clock", "command-container", "controls", "webcam-hud", "media-player", "settings-container"].map((id) => [id, +getComputedStyle(document.getElementById(id) || document.body).zIndex || 0])));
  check(s.z > Math.max(zl["jarvis-clock"], zl["command-container"], zl["controls"], zl["webcam-hud"], zl["media-player"]) && (!zl["settings-container"] || s.z < zl["settings-container"]) && await islandOnTop(page), `${tag} 7. z-index che được đồng hồ/chat/hàng nút/webcam/media nhưng dưới Cài đặt`, `z ${s.z} · ${JSON.stringify(zl)}`);
  await page.waitForTimeout(3300);
  s = await st();
  check(s.state === "pill", `${tag} 8. sau vài giây vẫn không tự bung`, s.state);

  // --- chữ đổi dài/ngắn: viên thuốc co giãn bám theo chữ (chữ không tràn ra ngoài nền rồi nền mới giãn theo) ---
  for (const [txt, what] of [["Đang tìm kiếm tài liệu và tổng hợp...", "dài ra"], ["Đang gọi LLM...", "ngắn lại"]]) {
    await page.evaluate(() => {
      window.__w = [];
      const r = document.getElementById("error-text"), pillEl = r.querySelector(".island-pill"), bg = r.querySelector(".island-pill-rect"), t0 = performance.now();
      // sampled after the frame's callbacks (the outline is redrawn in its own rAF), i.e. what was painted in that frame
      const sample = () => window.__w.push({ t: performance.now() - t0, vis: pillEl.getBoundingClientRect().width, bg: bg.getBoundingClientRect().width });
      const tick = () => { setTimeout(sample, 0); if (performance.now() - t0 < 900) requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
    });
    send({ type: "flow_step", step: { id: 3, label: txt, status: "active" } });
    await page.waitForTimeout(1000);
    const w = await page.evaluate(() => window.__w), last = w[w.length - 1];
    const off = Math.max(...w.map((f) => Math.abs(f.vis - f.bg))), settled = (w.find((f) => Math.abs(f.bg - last.bg) <= 2) || { t: Infinity }).t;
    check(off <= 4 && settled <= 450, `${tag} 8b. chữ ${what}: viên thuốc co giãn cùng lúc với chữ (phần chữ hiện ra không vượt nền), xong trong ≤ 450ms`, `lệch lớn nhất ${off.toFixed(1)}px · xong sau ${Math.round(settled)}ms`);
  }

  // --- bấm vào: thẻ rũ xuống; chữ hiện cùng thẻ, không hiện trước khung ---
  await page.evaluate(() => {
    window.__f = [];
    const r = document.getElementById("error-text"), card = r.querySelector(".island-body-rect"), inner = r.querySelector(".island-panel");
    const t0 = performance.now();
    const tick = () => { window.__f.push({ t: performance.now() - t0, h: card.getBoundingClientRect().height, w: card.getBoundingClientRect().width, o: parseFloat(card.getAttribute("opacity")), op: parseFloat(getComputedStyle(inner).opacity) }); if (performance.now() - t0 < 1400) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
  await page.evaluate(() => { // đếm số lần đảo đo lại bố cục (offsetWidth của nội dung viên thuốc) trong lúc bung: phải là vài lần, không phải mỗi khung hình
    const pill = document.querySelector("#error-text .island-pill-content"), get = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth").get;
    window.__rect = 0; Object.defineProperty(pill, "offsetWidth", { get() { window.__rect++; return get.call(this); } });
  });
  await tapPill(page, hasHover);
  await page.waitForTimeout(1500);
  s = await st();
  const rectCalls = await page.evaluate(() => window.__rect);
  check(rectCalls <= 8, `${tag} 9b. bung mượt: đảo không đo lại bố cục ở mỗi khung hình (${rectCalls} lần đo trong lúc bung, cũ ~30+)`, `${rectCalls} lần`);
  const fr = await page.evaluate(() => window.__f), finalH = s.cardH;
  check(s.state === "open" && s.expanded === "true" && finalH > 40 && s.cardW > s.pillR - s.pillL + 40, `${tag} 9. bấm viên thuốc: thẻ rũ xuống dưới, rộng hơn viên thuốc (kiểu Sileo)`, `${s.state} · thẻ ${Math.round(s.cardW)}×${Math.round(s.cardH)}`);
  check(s.pillBottom - s.cardTop >= 16 && s.cardW > s.pillR - s.pillL + 40,
    `${tag} 9c. như Sileo: nửa dưới viên thuốc kéo xuống chồng vào thân thẻ (goo tạo cổ nối), thân rộng hơn viên thuốc`, `viên thuốc chồng vào thân ${Math.round(s.pillBottom - s.cardTop)}px`);
  check(await page.evaluate(() => getComputedStyle(document.querySelector("#error-text .island-panel")).position === "absolute" && !getComputedStyle(document.querySelector("#error-text .island-panel")).transitionProperty.includes("grid")),
    `${tag} 9d. nội dung thẻ chỉ đổi độ mờ, không tính lại bố cục mỗi khung hình (không animate grid/width)`, "");
  const early = fr.filter((f) => f.op > 0.15 && f.h < finalH * 0.45);
  check(early.length === 0 && Math.max(...fr.map((f) => f.op)) >= 0.99, `${tag} 10. chữ hiện cùng thẻ: khi chữ đã rõ (>15%) khung đã rũ xuống ≥ 45%`, `${early.length} khung chữ hiện sớm; chữ cuối ${Math.max(...fr.map((f) => f.op)).toFixed(2)}`);
  check(await islandOnTop(page), `${tag} 11. thẻ nằm trên cùng (che đồng hồ/chat)`, "");
  { // PC và điện thoại giống hệt nhau, dựng như Sileo: hai rect dưới một bộ lọc goo nhẹ
    const look = await page.evaluate(() => {
      const r = document.getElementById("error-text");
      const f = document.getElementById("island-goo");
      return { filtered: [r, ...r.querySelectorAll("*")].filter((e) => getComputedStyle(e).filter.includes("url(")).map((e) => e.className.baseVal ?? e.className), steps: f ? f.children.length : 0, rects: r.querySelectorAll(".island-canvas rect").length };
    });
    check(look.filtered.length === 1 && look.filtered[0] === "island-canvas" && look.steps <= 3 && look.rects === 2,
      `${tag} 11b. cùng một kiểu trên PC và điện thoại, dựng như Sileo: một khối lọc goo nhẹ (≤ 3 bước) chứa đúng hai rect`, JSON.stringify(look));
  }
  // thu về nhanh: Escape → thẻ co lên trong ≤ 230ms
  await page.evaluate(() => {
    window.__c = [];
    const card = document.querySelector("#error-text .island-body-rect"), t0 = performance.now();
    const tick = () => { window.__c.push({ t: performance.now() - t0, h: card.getBoundingClientRect().height, w: card.getBoundingClientRect().width, o: parseFloat(card.getAttribute("opacity")) }); if (performance.now() - t0 < 800) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(900);
  const tFold = (await page.evaluate(() => window.__c)).find((f) => f.h < 4)?.t ?? Infinity;
  check(tFold <= 230, `${tag} 11c. thu thẻ về nhanh (≤ 230ms)`, `${Math.round(tFold)}ms`);
  { // sau khi thu thẻ, viên thuốc vẫn ôm trọn chữ + số đếm (lúc mở chữ thu nhỏ 0,9: không được lấy bề rộng đã thu nhỏ làm bề rộng viên thuốc)
    const fit = await page.evaluate(() => { const p = document.querySelector("#error-text .island-pill"), c = document.querySelector("#error-text .island-pill-content"), r = document.querySelector("#error-text .island-pill-rect"); return { pill: p.getBoundingClientRect().width, rect: r.getBoundingClientRect().width, content: c.offsetWidth }; });
    check(fit.pill >= fit.content - 1 && fit.rect >= fit.content - 1, `${tag} 11f. mở xem rồi thu về: viên thuốc vẫn ôm trọn chữ và số đếm (không tràn ra ngoài)`, `viên thuốc ${Math.round(fit.rect)}px · chữ ${fit.content}px`);
  }
  { // như Sileo: lúc bung và lúc thu thân thẻ luôn đủ bề rộng, cao dần và hiện dần
    const both = [...fr, ...(await page.evaluate(() => window.__c))].filter((f) => f.h > 0.5), cardW = s.cardW;
    // as in Sileo the body is always full width and fades in with its height: while it is low it is (nearly) transparent, so it
    // never shows as a line across the screen
    const pillW = s.pillR - s.pillL, bad = both.filter((f) => Math.abs(f.w - cardW) > 1.5), lowSeen = both.filter((f) => f.h < 6 && f.o > 0.15);
    check(both.length > 4 && bad.length === 0 && lowSeen.length === 0, `${tag} 11d. bung/thu như Sileo: thân thẻ đủ bề rộng, cao dần và hiện dần (khi còn thấp thì gần như trong suốt → không thành vạch kẻ ngang)`,
      `lệch bề rộng: ${bad.length} · thấp mà rõ: ${lowSeen.length} / ${both.length} khung`);
  }
  await tapPill(page, hasHover);
  await page.waitForTimeout(1000);

  // --- 5 giây không chạm thì thu lại ---
  if (hasHover) {
    await page.mouse.move(2, 600);
    await page.waitForTimeout(5500);
    s = await st();
    check(s.state === "pill" && s.cardH < 4 && Math.abs(s.pillCx - s.vw / 2) <= 2, `${tag} 12. mở xong 5 giây không tương tác: thẻ co lên mất hẳn, chỉ còn viên thuốc ở giữa`, `${s.state} · thẻ ${Math.round(s.cardW)}×${Math.round(s.cardH)} · thuốc ${Math.round(s.pillR - s.pillL)}px`);
    await tapPill(page, true);
    await page.waitForTimeout(700);
    const p = await page.evaluate(() => { const b = document.querySelector("#error-text .island-panel").getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; });
    await page.mouse.move(p[0], p[1]);
    await page.waitForTimeout(7000);
    s = await st();
    check(s.state === "open", `${tag} 13. chuột còn nằm trong thẻ: không tự thu lại (quá 5 giây)`, s.state);
    await page.mouse.move(2, 600);
    await page.waitForTimeout(5600);
    s = await st();
    check(s.state === "pill", `${tag} 14. chuột rời đi: trong 5 giây thẻ tự thu lại`, s.state);
  } else {
    await page.waitForTimeout(3200);
    const p = await page.evaluate(() => { const b = document.querySelector("#error-text .island-panel").getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; });
    await page.touchscreen.tap(p[0], p[1]); // chạm vào thẻ: đếm lại 5 giây
    await page.waitForTimeout(3600);
    s = await st();
    check(s.state === "open", `${tag} 12. chạm vào thẻ thì đếm lại 5 giây (6,8 giây từ lúc mở mà vẫn mở)`, s.state);
    await page.waitForTimeout(2600);
    s = await st();
    check(s.state === "pill" && s.cardH < 4 && Math.abs(s.pillCx - s.vw / 2) <= 2, `${tag} 13. 5 giây không chạm nữa: thẻ co lên mất hẳn, chỉ còn viên thuốc ở giữa`, `${s.state} · thẻ ${Math.round(s.cardW)}×${Math.round(s.cardH)}`);
  }

  // --- xong việc: thu ngang theo chữ, mờ dần, biến mất — không trượt lên ---
  await page.evaluate(() => {
    window.__g = [];
    const r = document.getElementById("error-text"), pillBg = r.querySelector(".island-pill-rect"), label = r.querySelector(".island-label"), pillEl = r.querySelector(".island-pill"), icon = r.querySelector(".island-icon");
    const t0 = performance.now();
    const tick = () => {
      const tf = getComputedStyle(r).transform, m = new DOMMatrixReadOnly(tf === "none" ? undefined : tf);
      window.__g.push({ t: performance.now() - t0, state: r.dataset.state, w: pillBg.getBoundingClientRect().width, top: r.getBoundingClientRect().top, lop: parseFloat(getComputedStyle(label).opacity), pop: parseFloat(getComputedStyle(pillEl).opacity), iconVisW: icon.getBoundingClientRect().width, clip: getComputedStyle(pillEl).clipPath, op: parseFloat(getComputedStyle(r).opacity), ty: m.m42 });
      if (performance.now() - t0 < 10500) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  finish(send);
  await page.waitForTimeout(1300);
  s = await st();
  check(s.state !== "hidden" && s.count === "3/3", `${tag} 15. xong 3/3: viên thuốc báo hoàn thành (chưa biến mất ngay)`, `${s.state} · ${s.count}`);
  await page.waitForTimeout(8200);
  s = await st();
  const g = await page.evaluate(() => window.__g), leaving = g.filter((f) => f.state === "leaving"), natural = Math.max(...g.map((f) => f.w));
  check(s.state === "hidden", `${tag} 16. không ai xem: báo xong rồi biến mất`, s.state);
  const minW = Math.min(...leaving.map((f) => f.w));
  check(leaving.length >= 3 && minW <= 14 && natural >= 80, `${tag} 17. biến mất: viên thuốc thu ngang vào giữa tới hết`, `rộng nhất ${Math.round(natural)}px → nhỏ nhất ${Math.round(minW)}px, ${leaving.length} khung`);
  const stillFull = leaving.filter((f) => f.w <= natural * 0.5 && f.pop > 0.6);
  const sliverLeft = leaving.filter((f) => f.w <= 16 && f.pop > 0.15);
  check(stillFull.length === 0 && sliverLeft.length === 0 && leaving.some((f) => f.pop < 0.15), `${tag} 18. icon + chữ + số đếm bị xoá mờ dần theo độ thu ngang: khi viên thuốc đã hẹp thì không còn sót icon hay chữ`, `khung hẹp mà còn rõ: ${stillFull.length} (≤50% rộng, >60% đậm) · ${sliverLeft.length} (vệt ≤16px, >15% đậm)`);
  const tPill = (leaving.find((f) => f.w <= 12) || { t: Infinity }).t, tContent = (leaving.find((f) => f.pop <= 0.05) || { t: Infinity }).t, t0 = leaving[0].t;
  check(tPill - t0 >= 150 && tPill - t0 <= 450 && tContent <= tPill, `${tag} 18b. thu ngang viên thuốc nhanh (~0,3 giây), chữ + icon bám theo nhanh hơn (~0,25 giây)`, `viên thuốc hẹp sau ${Math.round(tPill - t0)}ms · chữ hết sau ${Math.round(tContent - t0)}ms`);
  const sliver = leaving.filter((f) => f.w <= 12 && f.op > 0.3);
  check(sliver.length === 0, `${tag} 18c. thu về là biến mất luôn: không còn vệt hẹp đứng lại rồi mới mờ`, `${sliver.length} khung còn vệt hẹp rõ`);
  check(g.every((f) => Math.abs(f.ty) < 0.5 && Math.abs(f.top - g[0].top) < 0.5), `${tag} 19. không trượt lên: vị trí đứng yên suốt lúc biến mất`, `lệch dọc lớn nhất ${Math.max(...g.map((f) => Math.abs(f.top - g[0].top))).toFixed(1)}px`);

  // --- có media: vẫn chỉ viên thuốc, bấm mới bung, nằm trên media ---
  await page.evaluate(() => { document.body.classList.add("media-playing"); document.getElementById("media-player").classList.remove("hidden"); });
  flow(send);
  await page.waitForTimeout(900);
  s = await st();
  check(s.state === "pill" && s.vis === "visible", `${tag} 20. media đang phát: chỉ viên thuốc`, s.state);
  await tapPill(page, hasHover);
  await page.waitForTimeout(800);
  s = await st();
  check(s.state === "open" && await islandOnTop(page), `${tag} 21. bấm viên thuốc: thẻ hiện ra, nằm trên cả media`, `${s.state} · z ${s.z}`);
  await page.mouse.move(2, 600);
  await tapPill(page, hasHover);
  await page.waitForTimeout(700);
  await page.evaluate(() => { document.body.classList.remove("media-playing"); document.getElementById("media-player").classList.add("hidden"); });

  // --- webcam đang mở: cũng chỉ viên thuốc ---
  finish(send);
  await page.waitForTimeout(6400);
  await page.evaluate(() => document.getElementById("webcam-hud").classList.add("visible"));
  flow(send);
  await page.waitForTimeout(900);
  s = await st();
  check(s.state === "pill" && s.cardH < 4, `${tag} 22. webcam đang mở: chỉ viên thuốc`, s.state);
  await tapPill(page, hasHover);
  await page.waitForTimeout(800);
  check(await islandOnTop(page), `${tag} 23. bấm viên thuốc: thẻ nằm trên cả webcam`, "");
  await tapPill(page, hasHover);
  await page.waitForTimeout(500);
  await page.evaluate(() => document.getElementById("webcam-hud").classList.remove("visible"));

  // --- lỗi hệ thống: viên thuốc đỏ, bấm mới xem đầy đủ ---
  finish(send);
  await page.waitForTimeout(6400);
  await page.mouse.move(2, 600);
  await page.evaluate(() => document.getElementById("btn-webcam-toggle").click()); // mở webcam thất bại → showError
  await page.waitForTimeout(900);
  s = await st();
  check(s.kind === "error" && s.state === "pill" && s.vis === "visible" && /Webcam/.test(s.label), `${tag} 24. lỗi hệ thống (showError) vào khu thông báo: viên thuốc đỏ, không tự bung`, JSON.stringify([s.kind, s.state, s.label]));
  await tapPill(page, hasHover);
  await page.waitForTimeout(800);
  s = await st();
  check(s.state === "open" && /Webcam/.test(s.err), `${tag} 25. bấm: thẻ hiện lỗi đầy đủ`, JSON.stringify([s.state, s.err]));
  await page.mouse.move(2, 600);
  await page.waitForTimeout(5600);
  s = await st();
  check(s.state === "pill", `${tag} 26. không tương tác 5 giây: thẻ lỗi thu lại`, s.state);
  await page.waitForTimeout(3000);
  s = await st();
  check(s.state === "leaving" || s.state === "hidden", `${tag} 27. lỗi hết hạn thì viên thuốc tự biến mất`, s.state);

  // --- Cài đặt che đảo ---
  await page.waitForTimeout(800);
  flow(send);
  await page.waitForTimeout(500);
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(500);
  s = await st();
  check(s.vis === "hidden" || s.op === 0, `${tag} 28. Cài đặt đang mở: đảo bị che`, JSON.stringify([s.vis, s.op]));
  await page.evaluate(() => document.getElementById("settings-close").click());
  await page.waitForTimeout(600);
  s = await st();
  check(s.vis === "visible", `${tag} 29. thoát Cài đặt: đảo hiện lại (flow còn chạy)`, s.vis);
  await browser.close();
}

async function layout(label, opts) {
  const tag = `[${label}]`;
  const { browser, page, send, st } = await open(opts);
  flow(send);
  await page.waitForTimeout(900);
  const c = await page.evaluate(() => {
    const r = document.querySelector("#error-text .island-pill").getBoundingClientRect(), b = document.getElementById("btn-controls").getBoundingClientRect();
    return { right: r.right, ctlLeft: b.left };
  });
  check(c.right <= c.ctlLeft - 2, `${tag} 30. viên thuốc không đè lên nút menu điều khiển`, `viên thuốc tới ${Math.round(c.right)} · nút menu từ ${Math.round(c.ctlLeft)}`);
  const r = await page.evaluate(() => { const b = document.querySelector("#error-text .island-pill").getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; });
  await page.touchscreen.tap(r[0], r[1]);
  await page.waitForTimeout(800);
  const s = await st();
  check(s.cardL >= 0 && s.cardR <= s.vw, `${tag} 31. thẻ bung nằm gọn trong màn hình`, `${Math.round(s.cardL)}…${Math.round(s.cardR)} / ${s.vw}`);
  const ctl = await page.evaluate(() => document.getElementById("btn-controls").getBoundingClientRect().left);
  check(s.cardW <= 340 && s.cardW >= 200 && (s.vw < 360 || s.cardR <= ctl - 2), `${tag} 32. thẻ không rộng sát hai mép và không che nút menu điều khiển (máy ≥ 360px)`, `thẻ ${Math.round(s.cardW)}px · tới ${Math.round(s.cardR)} · nút menu từ ${Math.round(ctl)}`);
  await browser.close();
}

(async () => {
  await run("máy tính 1280", { viewport: { width: 1280, height: 800 } }, true);
  await run("iPhone 390", mobile(390, 844, 3), false);
  await layout("điện thoại nhỏ 320", mobile(320, 640, 2));
  await layout("Galaxy Fold gập 280", mobile(280, 653, 3));
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
