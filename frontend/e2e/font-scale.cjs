// E2E: cỡ chữ đủ đọc và tự tăng theo màn hình. Lỗi cũ: chữ cố định rất nhỏ (bong bóng chat 13px, bảng 12px, nhãn 9–11px) trên điện thoại
//  lẫn màn hình lớn. Đúng: thang chữ chung (--ui-scale) tăng theo loại và cỡ màn hình: điện thoại ≥ 15px cho chữ chat, điện thoại to/dài
//  (Galaxy S21 Ultra, iPhone Pro Max) lớn hơn điện thoại nhỏ, máy tính ≥ 14px và lớn dần ở màn hình rộng (Full HD, 2K/4K);
//  ô nhập ≥ 16px trên điện thoại (dưới 16px iOS tự phóng to trang khi chạm vào); chữ nhỏ nhất trong giao diện chính ≥ 11px;
//  tăng chữ không làm tràn ngang, không làm cắt chữ trong bong bóng, và bong bóng "đang tải" vẫn cao đúng bằng bong bóng một dòng chữ (không nẩy).
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/font-scale.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const mobile = (width, height, dpr) => ({ viewport: { width, height }, deviceScaleFactor: dpr, isMobile: true, hasTouch: true });
const DEVICES = [
  { key: "se", label: "iPhone SE · 375×667", opts: mobile(375, 667, 2), phone: true },
  { key: "ip", label: "iPhone 14 · 390×844", opts: mobile(390, 844, 3), phone: true },
  { key: "pm", label: "iPhone 14 Pro Max · 430×932", opts: mobile(430, 932, 3), phone: true },
  { key: "s23", label: "Galaxy S23 · 360×780", opts: mobile(360, 780, 3), phone: true },
  { key: "s21", label: "Galaxy S21 Ultra · 412×915", opts: mobile(412, 915, 2.625), phone: true },
  { key: "fold", label: "Galaxy Fold gập · 280×653", opts: mobile(280, 653, 3), phone: true, tiny: true },
  { key: "pc", label: "máy tính 1280×800", opts: { viewport: { width: 1280, height: 800 } }, phone: false },
  { key: "fhd", label: "máy tính Full HD 1920×1080", opts: { viewport: { width: 1920, height: 1080 } }, phone: false },
  { key: "qhd", label: "máy tính 2K 2560×1440", opts: { viewport: { width: 2560, height: 1440 } }, phone: false },
];
const got = {};

async function run(d) {
  const browser = await chromium.launch();
  const page = await (await browser.newContext(d.opts)).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.addInitScript(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError")); });
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  const send = (m) => sock.send(JSON.stringify(m));
  // bong bóng đang tải rồi một dòng chữ: chiều cao không được nhảy
  send({ type: "stream_start" });
  await page.waitForTimeout(700);
  const loaderH = await page.evaluate(() => [...document.querySelectorAll(".chat-bubble.assistant")].pop().getBoundingClientRect().height);
  send({ type: "text_chunk", text: "Xin chào." });
  await page.waitForTimeout(1300);
  send({ type: "stream_end" });
  await page.waitForTimeout(400);
  await page.evaluate(() => document.getElementById("btn-webcam-toggle").click()); // hiện #error-text
  await page.waitForTimeout(700);
  const r = await page.evaluate(() => {
    const fs = (el) => parseFloat(getComputedStyle(el).fontSize);
    const bub = [...document.querySelectorAll(".chat-bubble.assistant")].pop(), txt = bub.querySelector(".bubble-text") || bub;
    const small = []; let min = 99, minEl = "";
    for (const root of document.querySelectorAll("#command-container, #controls, #error-text, #status-row")) {
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        if (!n.data.trim()) continue;
        const el = n.parentElement, cs = getComputedStyle(el), r = el.getBoundingClientRect();
        if (cs.display === "none" || cs.visibility === "hidden" || !r.width || !r.height) continue;
        if (el.closest("#jarvis-clock, option, script, style")) continue;
        const f = parseFloat(cs.fontSize); if (f < min) { min = f; minEl = el.tagName + "." + (el.className || el.id || "").toString().split(" ")[0] + " «" + n.data.trim().slice(0, 14) + "»"; }
        if (f < 11) small.push(el.id || el.className || el.tagName);
      }
    }
    return {
      bubble: fs(txt), input: fs(document.getElementById("command-input")), status: fs(document.getElementById("status-text")), error: fs(document.getElementById("error-text")), min, minEl,
      bubbleH: bub.getBoundingClientRect().height, clipped: bub.scrollHeight > bub.clientHeight + 1,
      sw: document.documentElement.scrollWidth, vw: innerWidth, ccRight: document.getElementById("command-container").getBoundingClientRect().right, ccLeft: document.getElementById("command-container").getBoundingClientRect().left,
    };
  });
  got[d.key] = r;
  const tag = `[${d.label}]`;
  check(r.sw <= r.vw + 1 && r.ccLeft >= -1 && r.ccRight <= r.vw + 1, `${tag} 1. không tràn ngang, thanh lệnh nằm trong màn hình`, `trang ${r.sw}/${r.vw}`);
  check(!r.clipped, `${tag} 2. chữ trong bong bóng không bị cắt`, "");
  check(Math.abs(loaderH - r.bubbleH) <= 1, `${tag} 3. bong bóng "đang tải" cao đúng bằng bong bóng một dòng chữ (không nẩy)`, `${loaderH.toFixed(1)}px → ${r.bubbleH.toFixed(1)}px`);
  if (d.phone) {
    check(r.bubble >= (d.tiny ? 13.5 : 15), `${tag} 4. chữ chat đủ lớn: ${r.bubble.toFixed(1)}px (cần ≥ ${d.tiny ? 13.5 : 15}px)`, "");
    check(r.input >= 16, `${tag} 5. ô nhập ≥ 16px (iOS không tự phóng to trang)`, `${r.input.toFixed(1)}px`);
  } else {
    const need = d.key === "pc" ? 14 : d.key === "fhd" ? 15.5 : 17;
    check(r.bubble >= need, `${tag} 4. chữ chat đủ lớn: ${r.bubble.toFixed(1)}px (cần ≥ ${need}px)`, "");
    check(r.input >= need - 0.5, `${tag} 5. ô nhập đủ lớn`, `${r.input.toFixed(1)}px`);
  }
  check(r.min >= 11, `${tag} 6. chữ nhỏ nhất trong giao diện chính ≥ 11px`, `${r.min.toFixed(1)}px ở ${r.minEl}`);
  check(r.error >= (d.phone ? 14 : 13.5) && r.status >= (d.phone ? (d.tiny ? 13 : 14) : 13), `${tag} 7. dòng trạng thái và thông báo lỗi đủ lớn`, `trạng thái ${r.status.toFixed(1)}px · lỗi ${r.error.toFixed(1)}px`);
  await browser.close();
}

(async () => {
  for (const d of DEVICES) await run(d);
  const g = got;
  check(g.s21.bubble >= g.s23.bubble + 0.4 && g.pm.bubble >= g.se.bubble + 0.4, "8. điện thoại to/dài chữ lớn hơn điện thoại nhỏ (S21 Ultra > S23, Pro Max > SE)", `S23 ${g.s23.bubble.toFixed(1)} · S21U ${g.s21.bubble.toFixed(1)} · SE ${g.se.bubble.toFixed(1)} · ProMax ${g.pm.bubble.toFixed(1)}`);
  check(g.pc.bubble < g.fhd.bubble && g.fhd.bubble < g.qhd.bubble, "9. máy tính: 1280 < Full HD < 2K (chữ lớn dần theo màn hình)", `${g.pc.bubble.toFixed(1)} < ${g.fhd.bubble.toFixed(1)} < ${g.qhd.bubble.toFixed(1)}`);
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
