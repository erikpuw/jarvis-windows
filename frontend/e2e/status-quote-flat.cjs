// E2E (impeccable polish 2026-10-18):
//  1. the status label shimmers like Claude's "thinking" text (user 2026-10-18: keep the shimmer, Claude's looks nicer): the
//     state's colour with one narrow soft white sheen passing, only while JARVIS is busy (thinking / working / listening);
//     idle is plain text, no animation (the old shimmer also ran while idle);
//  3. a quote in an answer is a thin grey rule on the left, no blue bar on a blue tint (answers have no bubble any more).
// WebSocket and /api are mocked. Run: PW=<playwright module> node frontend/e2e/status-quote-flat.cjs   (needs `npm run dev` on :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1200);

  // 1. busy states shimmer (text-clipped gradient with a white sheen, running); idle is plain; each state keeps its own colour
  const st = await page.evaluate(() => {
    const el = document.getElementById("status-text");
    const out = {};
    for (const c of ["", "status-thinking", "status-working", "status-listening"]) {
      el.className = c; el.textContent = "Đang nghĩ…";
      const cs = getComputedStyle(el);
      out[c || "idle"] = { anim: cs.animationName, clip: cs.webkitBackgroundClip || cs.backgroundClip, img: cs.backgroundImage, color: cs.color };
    }
    return out;
  });
  const busy = ["status-thinking", "status-working", "status-listening"].map((k) => st[k]);
  const sheen = (img) => /255, 255, 255/.test(img); // a white band in the gradient
  const base = (img) => (img.match(/rgba?\([^)]*\)/) || [""])[0]; // the gradient's first stop = the state colour
  check(st.idle.anim === "none" && st.idle.img === "none" && !/rgba\(0, 0, 0, 0\)/.test(st.idle.color)
    && busy.every((v) => v.anim !== "none" && v.clip === "text" && sheen(v.img)) && new Set(busy.map((v) => base(v.img))).size === 3,
    "1. dòng trạng thái: lấp lánh kiểu Claude khi đang bận (màu trạng thái + vệt sáng trắng), lúc nghỉ đứng yên", JSON.stringify(st));

  // 3. a quote in an answer
  const q = await page.evaluate(() => {
    const b = document.createElement("div"); b.className = "chat-bubble assistant";
    b.innerHTML = '<div class="bubble-prose"><blockquote>Trích dẫn</blockquote></div>';
    document.getElementById("chat-history").appendChild(b);
    const cs = getComputedStyle(b.querySelector("blockquote"));
    return { w: cs.borderLeftWidth, c: cs.borderLeftColor, bg: cs.backgroundColor };
  });
  const [r, g, bl] = (q.c.match(/\d+/g) || []).map(Number);
  const grey = Math.max(r, g, bl) - Math.min(r, g, bl) <= 40;
  check(parseFloat(q.w) <= 2 && grey && q.bg === "rgba(0, 0, 0, 0)", "3. trích dẫn: vạch xám mảnh ≤2px, không nền xanh", JSON.stringify(q));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
