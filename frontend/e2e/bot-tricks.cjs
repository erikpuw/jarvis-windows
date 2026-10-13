// E2E: bot linh vật làm trò trong 30 giây chờ (idle) trước khi ngủ, thay vì chỉ nhìn quanh trông cứng.
//  0–15s: cứ vài giây làm một trò nhẹ: nhảy nhẹ lên (hop) hoặc nảy co giãn (bounce: dẹt xuống rồi giãn lên, hai nhịp ngắn)
//  sau 15s: giận dỗi vì đợi lâu (sulk): quay mặt đi, dấu 💢 trên đầu, miệng mím, ~2,5s
//  hết 30s: ngủ, không làm trò nữa
//  KHÔNG làm trò khi người dùng đang gõ, khi JARVIS đang nghĩ/nói; trò không tính là "có hoạt động" (đồng hồ 30s vẫn chạy).
// Đồng hồ giả (page.clock); WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/bot-tricks.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.clock.install();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(300);
  const emit = (s) => page.evaluate((st) => window.dispatchEvent(new CustomEvent("jarvis:mascot", { detail: st })), s);
  const bot = () => page.$eval("#jarvis-bot", (e) => ({ now: performance.now() - (window.__t0 || 0), state: e.dataset.state, trick: e.dataset.trick || "", tricks: Number(e.dataset.tricks || 0), sulk: e.dataset.sulk || "", sulkFace: e.dataset.sulkFace || "", look: e.dataset.look || "" }));
  // run the fake clock in 250 ms steps, noting every trick as it starts (with the time since idle began)
  const watch = async (ms, t0 = 0) => {
    const seen = []; let last = (await bot()).tricks;
    for (let t = 250; t <= ms; t += 250) {
      await page.clock.fastForward(250);
      await page.waitForTimeout(5);
      const b = await bot();
      if (b.tricks !== last) { seen.push({ at: Math.round(b.now), trick: b.trick, sulk: b.sulk, sulkFace: b.sulkFace, look: b.look }); last = b.tricks; } // page's own clock since the key press
    }
    return seen;
  };

  // a fresh idle: wake it (a key anywhere counts as activity) so the 30 s starts now
  await emit("idle");
  await page.keyboard.press("Shift");
  await page.evaluate(() => { window.__t0 = performance.now(); });
  const seen = await watch(29500);
  // times on the page's clock since the key press (the fake clock also runs in real time between steps)
  const early = seen.filter((s) => s.at < 15000), late = seen.filter((s) => s.at >= 15000);
  check(seen.length >= 4, "1. trong 30s chờ bot làm nhiều trò (không chỉ nhìn quanh)", JSON.stringify(seen.map((s) => `${s.trick}@${(s.at / 1000).toFixed(1)}s`)));
  check(early.length >= 2 && early.every((s) => s.trick === "hop" || s.trick === "bounce"), "2. 15s đầu: nhảy nhẹ hoặc nảy co giãn, chưa giận", JSON.stringify(early.map((s) => s.trick)));
  const sulk = late.find((s) => s.trick === "sulk");
  check(!!sulk && sulk.sulk === "1" && sulk.look.startsWith("sulk") && sulk.sulkFace === "frown+emoji", "3. sau 15s: giận dỗi vì đợi lâu (quay mặt đi, miệng ^, dán emoji 💢 ở góc trên đầu thay cho dấu tự vẽ)", JSON.stringify(sulk || late));
  await page.clock.fastForward(1500); await page.waitForTimeout(20);
  let b = await bot();
  check(b.state === "sleeping", "4. hết 30s: bot ngủ", b.state);
  const asleep = await watch(10000);
  check(asleep.length === 0, "5. đang ngủ thì không làm trò", JSON.stringify(asleep));

  // typing wakes it but it watches the box: no tricks while the user types
  await page.click("#command-input");
  let typed = [];
  for (let i = 0; i < 8; i++) {
    await page.keyboard.type("a");
    typed = typed.concat(await watch(1000));
  }
  check(typed.length === 0, "6. đang gõ trong ô lệnh: không làm trò", JSON.stringify(typed));
  await page.keyboard.press("Escape");

  // JARVIS thinking / speaking: no tricks
  await emit("thinking");
  const thinking = await watch(8000);
  check(thinking.length === 0, "7. JARVIS đang nghĩ: không làm trò", JSON.stringify(thinking));
  await emit("speaking");
  const speaking = await watch(8000);
  check(speaking.length === 0, "8. JARVIS đang nói: không làm trò", JSON.stringify(speaking));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
