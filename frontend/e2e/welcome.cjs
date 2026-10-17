// E2E: lớp chào phiên mới (spec docs/superpowers/specs/2026-10-16-welcome-layer-design.md). WS và /api bị mock.
// Chạy: PW=<module playwright> node frontend/e2e/welcome.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const TOOLS = ["Trạng thái máy", "Bách khoa toàn thư", "Tra cứu pháp luật", "Đơn vị hành chính"]; // nhãn thật, dài nhất

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const socks = [];
  await page.routeWebSocket(/\/ws/, (ws) => { socks.push(ws); });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !socks.length; i++) await page.waitForTimeout(100);
  const send = (o) => socks[socks.length - 1].send(JSON.stringify(o));
  await page.waitForTimeout(600);

  // 1. hiện ngay khi tải trang, chữ chào theo giờ máy, không tên
  const s1 = await page.evaluate(() => {
    const el = document.getElementById("welcome"), h = new Date().getHours();
    // 8 khung giờ của greeting cũ (ngài viết): welcome-rotate.cjs kiểm đủ cả 8
    const want = h < 5 ? "Đêm khuya rồi" : h < 7 ? "Chào buổi sáng sớm" : h < 11 ? "Chào buổi sáng" : h < 13 ? "Chào buổi trưa"
      : h < 17 ? "Chào buổi chiều" : h < 19 ? "Chào buổi xế chiều" : h < 22 ? "Chào buổi tối" : "Khuya rồi";
    const hello = el?.querySelector(".welcome-hello");
    return { has: !!el, text: hello?.textContent, want, font: hello && getComputedStyle(hello).fontFamily,
      sub: el?.querySelector(".welcome-sub")?.textContent, bg: el && getComputedStyle(el).backgroundColor };
  });
  check(s1.has && s1.text === s1.want, "1. lớp chào hiện khi tải trang, chào theo khung giờ, không kèm tên", JSON.stringify(s1));
  check(/Lexend/.test(s1.font || ""), "2. chữ chào dùng Lexend", s1.font);
  check(s1.sub === "Tôi có thể giúp gì cho ngài hôm nay?" && s1.bg === "rgba(0, 0, 0, 0)", "3. câu hỏi đúng; lớp chào trong suốt (không nền tô thanh Safari)", JSON.stringify(s1));

  // 4. chữ xoay: nhận danh sách công cụ, đổi chữ sau ~2.2 s, khe không cắt chữ
  send({ type: "welcome", tools: TOOLS });
  await page.waitForTimeout(800);
  const w1 = await page.$eval(".welcome-slot", (s) => s.lastElementChild?.textContent);
  // 4a. chữ ĐẦU TIÊN cũng đủ khe: nó từng được đo khi Lexend 400 chưa tải (font dự phòng hẹp hơn) → cắt mất cuối chữ
  const f = await page.evaluate(() => { const s = document.querySelector(".welcome-slot"), sp = s.lastElementChild; return { w: sp.textContent, slot: s.getBoundingClientRect().width, word: sp.getBoundingClientRect().width }; });
  check(f.slot + 0.5 >= f.word, "4a. chữ đầu tiên không bị cắt (khe theo bề rộng chữ thật sau khi font tải)", JSON.stringify(f));
  await page.waitForTimeout(2300);
  const r = await page.evaluate(() => { const s = document.querySelector(".welcome-slot"), sp = s.lastElementChild; return { w2: sp.textContent, slot: s.getBoundingClientRect().width, word: sp.getBoundingClientRect().width }; });
  check(TOOLS.includes(w1) && TOOLS.includes(r.w2) && r.w2 !== w1 && r.slot >= r.word, "4. 'Thử hỏi về' xoay tên công cụ, khe đủ rộng", JSON.stringify({ w1, ...r }));

  // 5. thời tiết: thiếu nhiệt độ + kind lạ vẫn hiện mô tả + biểu tượng
  send({ type: "welcome", weather: { desc: "trời âm u", temp: null, kind: "weird", place: "Hồ Chí Minh" } });
  await page.waitForTimeout(500);
  const wx = await page.evaluate(() => { const el = document.querySelector(".welcome-weather"); return { text: el.textContent, svg: !!el.querySelector("svg"), op: getComputedStyle(el).opacity }; });
  check(/Trời âm u/.test(wx.text) && /Hồ Chí Minh/.test(wx.text) && !/°C/.test(wx.text) && wx.svg && wx.op === "1", "5. dòng thời tiết: thiếu nhiệt độ/kind lạ vẫn hiện mô tả + biểu tượng", JSON.stringify(wx));

  // 6. orb chưa dựng, nút orb khoá; bấm không có gì xảy ra
  const o1 = await page.evaluate(() => { const c = document.getElementById("orb-canvas"), b = document.getElementById("btn-orb-toggle"); b.click(); return { backend: c.dataset.backend, disabled: b.disabled }; });
  await page.waitForTimeout(500);
  const backendAfterClick = await page.$eval("#orb-canvas", (c) => c.dataset.backend);
  check(o1.backend === "off" && o1.disabled && backendAfterClick === "off", "6. lớp chào còn hiện: orb chưa dựng, nút orb khoá", JSON.stringify({ ...o1, backendAfterClick }));

  // 7. mép trái khối chữ = mép chữ trong ô nhập
  const al = await page.evaluate(() => ({ sub: document.querySelector(".welcome-sub").getBoundingClientRect().left, input: (() => { const i = document.getElementById("command-input"); return i.getBoundingClientRect().left + parseFloat(getComputedStyle(i).paddingLeft); })() }));
  check(Math.abs(al.sub - al.input) <= 3, "7. lề trái khối chữ thẳng mép chữ ô nhập (±3px)", JSON.stringify(al));
  // 7b. khối chào căn giữa dọc, nhích lên (ngài 2026-10-16; neo sát nút menu nhìn lạ nên trả về giữa): tâm khối 30–38% màn hình
  const mid = await page.evaluate(() => { const t = document.querySelector(".welcome-hello").getBoundingClientRect().top, b = document.querySelector(".welcome-try").getBoundingClientRect().bottom; return ((t + b) / 2) / innerHeight; });
  check(mid >= 0.30 && mid <= 0.38, "7b. khối chào căn giữa dọc, hơi cao (tâm 30–38% màn hình)", mid.toFixed(3));

  // 8. Settings mở: chữ xoay dừng; đóng: chạy lại
  await page.evaluate(() => document.querySelector('.sd-nav-item[data-page="overview"]').click()); await page.waitForTimeout(600);
  const a = await page.$eval(".welcome-slot", (s) => s.lastElementChild.textContent); await page.waitForTimeout(2600);
  const b = await page.$eval(".welcome-slot", (s) => s.lastElementChild.textContent);
  await page.evaluate(() => document.getElementById("settings-close").click()); await page.waitForTimeout(2800);
  const c = await page.$eval(".welcome-slot", (s) => s.lastElementChild.textContent);
  check(a === b && c !== b, "8. Settings mở: chữ xoay dừng; đóng lại chạy tiếp", JSON.stringify({ a, b, c }));

  // gửi tin đầu tiên
  await page.fill("#command-input", "xin chào"); await page.press("#command-input", "Enter");
  const t0 = Date.now();
  await page.waitForSelector("#welcome", { state: "detached", timeout: 3000 });
  await page.waitForSelector("#orb-canvas[data-first]", { state: "attached", timeout: 15000 });
  const sinceSend = Date.now() - t0;
  const o2 = await page.evaluate(() => ({ disabled: document.getElementById("btn-orb-toggle").disabled, backend: document.getElementById("orb-canvas").dataset.backend }));
  check(!o2.disabled && o2.backend !== "off", "9a. tin đầu: lớp chào biến mất, orb dựng, nút orb mở khoá", JSON.stringify({ ...o2, sinceSend }));
  // no opening any more (user 2026-10-17): the orb shows its cloud at once. 0.8 s after its first frame (page clock: the test sees
  // data-first late) the area left of the centre already has dots. PNG 80x80 measured 2026-10-16: empty/dot = 181 bytes,
  // cloud = 1575..3745 bytes; the bar of 1000 sits between.
  const firstDraw = await page.$eval("#orb-canvas", (c) => Number(c.dataset.first));
  await page.waitForFunction((t) => performance.now() - t >= 800, firstDraw, { polling: 20, timeout: 5000 });
  const midLeft = await page.screenshot({ clip: { x: 60, y: 380, width: 80, height: 80 } });
  check(midLeft.length > 1000, "9b. orb sau tin đầu hiện đám hạt ngay, không còn màn chấm-bung", String(midLeft.length));

  // 9c. thời tiết về muộn sau khi đã biến mất: bỏ qua, không hiện lại
  send({ type: "welcome", weather: { desc: "nắng", temp: 30, kind: "clear", place: "Hồ Chí Minh" } });
  await page.waitForTimeout(300);
  check(!(await page.$("#welcome")), "9c. thời tiết về muộn: lớp chào không hiện lại");

  // 10. nối lại socket: welcome gửi lại, không hiện lại lớp chào
  socks[socks.length - 1].close();
  for (let i = 0; i < 80 && socks.length < 2; i++) await page.waitForTimeout(100);
  if (socks.length > 1) send({ type: "welcome", tools: TOOLS });
  await page.waitForTimeout(400);
  check(socks.length > 1 && !(await page.$("#welcome")) && (await page.$eval("#orb-canvas", (c) => c.dataset.backend)) !== "off", "10. nối lại socket: lớp chào không hiện lại, orb vẫn bật", String(socks.length));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
