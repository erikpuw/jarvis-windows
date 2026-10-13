// E2E cho bong bóng chat ở khung cũ (không avatar, không lớp nền lò xo): loader stream_start, thẻ agent, chữ stream, mobile.
// WebSocket giả phát các lượt chat.
// Chạy: PW=<module playwright> node frontend/e2e/bubbles.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) failed++;
};

async function open(browser, opts = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, ...opts });
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(400);
  return { page, send: (m) => sock.send(JSON.stringify(m)) };
}

(async () => {
  const browser = await chromium.launch();
  const { page, send } = await open(browser);

  send({ type: "stream_start" });
  await page.waitForSelector(".chat-bubble.assistant.typing-loader", { timeout: 4000 }).catch(() => {});
  const frame = await page.evaluate(() => ({ head: document.querySelectorAll(".bubble-head, .bubble-avatar, .bubble-shell, .has-head, .spring").length }));
  check(frame.head === 0, "1a. bong bóng stream là khung cũ: không avatar, không lớp nền lò xo", JSON.stringify(frame));
  // 1e. hiệu ứng gooey của stream_start giữ nguyên, nhưng phần tràn của nó không đẩy khung chat lên
  const loader = await page.evaluate(() => {
    const l = document.querySelector(".chat-bubble.typing-loader");
    const blobs = [...l.querySelectorAll(".blob-c")].map((b) => getComputedStyle(b).animationName);
    return { oneLine: 13 * parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ui-scale")) * 1.5 + 14, blobs: blobs.join(","), goo: getComputedStyle(l.querySelector(".loader-inner-c")).filter.includes("sl-goo"), own: !!l.querySelector("svg filter#sl-goo"), global: !!document.querySelector("body > svg"), w: Math.round(l.getBoundingClientRect().width), h: Math.round(l.getBoundingClientRect().height) };
  });
  check(loader.blobs === "stream-spin,stream-spin,stream-spin,stream-spin" && loader.goo && loader.own && !loader.global && loader.w >= 44 && loader.w <= 52 && Math.abs(loader.h - loader.oneLine) <= 0.6, "1e. loader 4 khối quay + bộ lọc goo (chất lỏng) nằm trong chính loader, không SVG toàn trang, bong bóng rộng ~50px, cao bằng một dòng chữ (13px × thang chữ × 1,5 + 14)", JSON.stringify(loader));
  for (let i = 1; i <= 5; i++) send({ type: "flow_step", step: { id: i, label: "Bước " + i, status: i < 5 ? "completed" : "active" } });
  send({ type: "status", state: "thinking" });
  await page.waitForTimeout(900);
  const gap = await page.evaluate(() => {
    const h = document.getElementById("chat-history"), last = h.lastElementChild.getBoundingClientRect(), hb = h.getBoundingClientRect();
    return { scrollTop: Math.round(h.scrollTop), gapBelow: Math.round(hb.bottom - last.bottom) };
  });
  check(gap.scrollTop === 0 && gap.gapBelow <= 12, "1f. stream_start: bong bóng nằm sát đáy như cũ (không cuộn lên, không đệm thêm)", JSON.stringify(gap));

  const clipped = await page.evaluate(async () => {
    const h = document.getElementById("chat-history"), l = h.querySelector(".chat-bubble.typing-loader");
    let worst = 0;
    for (let i = 0; i < 60; i++) { // một vòng quay đầy đủ của các khối
      const hb = h.getBoundingClientRect();
      for (const e of l.querySelectorAll(".blob-c")) worst = Math.max(worst, e.getBoundingClientRect().bottom - hb.bottom);
      await new Promise((r) => setTimeout(r, 40));
    }
    return Math.round(worst);
  });
  check(clipped <= 0, "1g. khối gooey không bị cắt ở mép dưới khung chat", `${clipped}px quá mép`);
  const spill = await page.evaluate(async () => {
    const l = document.querySelector(".chat-bubble.typing-loader");
    let up = 0, down = 0;
    for (let i = 0; i < 60; i++) {
      const bb = l.getBoundingClientRect();
      for (const e of l.querySelectorAll(".blob-c")) { const r = e.getBoundingClientRect(); up = Math.max(up, bb.top - r.top); down = Math.max(down, r.bottom - bb.bottom); }
      await new Promise((r) => setTimeout(r, 40));
    }
    return { up: Math.round(up), down: Math.round(down) };
  });
  check(spill.up >= 1 && spill.down >= 1 && spill.down <= 8, "1h. hiệu ứng vẫn tràn ra ngoài bong bóng (>=1px; bong bóng cao hơn khi chữ lớn hơn nên tràn ít đi) nhưng vừa trong chỗ chừa sẵn (<=8px)", JSON.stringify(spill));
  send({ type: "text_chunk", text: "Xin chào, thưa Ngài. " }); await page.waitForTimeout(700);
  const after = await page.evaluate(() => { const h = document.getElementById("chat-history"), last = h.lastElementChild.getBoundingClientRect(); return Math.round(h.getBoundingClientRect().bottom - last.bottom); });
  check(Math.abs(after - gap.gapBelow) <= 2, "1i. chữ chạy ra thì bong bóng vẫn nằm đúng chỗ đó (không nhảy lên xuống)", `${gap.gapBelow}px → ${after}px`);
  send({ type: "status", state: "idle" }); await page.waitForTimeout(200);


  // 2. chữ stream ra đúng, thẻ agent đứng riêng, stream_end giữ nguyên nội dung
  send({ type: "interactive", card: { id: "t1", type: "tracker", title: "💻 Agent Desktop", status: "active", label: "Thực thi: mở Task Manager" } });
  await page.waitForTimeout(300);
  check(await page.$eval('[data-card-id="t1"]', (e) => !e.closest(".chat-bubble").querySelector("canvas, .bubble-avatar")), "2a. thẻ agent không có avatar");
  send({ type: "text_chunk", text: "Tôi đã mở Task Manager thành công, thưa Ngài." });
  send({ type: "stream_end" });
  await page.waitForTimeout(900);
  const kept = await page.evaluate(() => { const b = [...document.querySelectorAll(".chat-bubble.assistant")].pop(); return { text: b.querySelector(".bubble-text")?.textContent || "", cs: getComputedStyle(b).backgroundColor, canvases: b.querySelectorAll("canvas").length }; });
  check(kept.text.includes("Task Manager") && kept.canvases === 0, "2b. sau stream_end nội dung còn đủ, bong bóng không có canvas", JSON.stringify(kept));
  check(kept.cs !== "rgba(0, 0, 0, 0)", "2c. bong bóng tự có nền (khung cũ, không phải lớp nền riêng)", kept.cs);

  // 3. đường text (không stream, phiên mới) cũng ra bong bóng thường
  const t = await open(browser);
  t.send({ type: "text", text: "Tôi ở đây, thưa Ngài." });
  await t.page.waitForTimeout(1500);
  const textBubble = await t.page.evaluate(() => { const b = [...document.querySelectorAll(".chat-bubble.assistant")].find((x) => x.textContent.includes("Tôi ở đây")); return { has: !!b, extra: b ? b.querySelectorAll("canvas, .bubble-head").length : -1 }; });
  check(textBubble.has && textBubble.extra === 0, "3. tin nhắn dạng text ra bong bóng thường", JSON.stringify(textBubble));
  await t.page.close();

  // 4. bong bóng người dùng
  await page.evaluate(() => { const i = document.getElementById("command-input"); i.value = "mở task manager"; i.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await page.waitForTimeout(400);
  const user = await page.evaluate(() => { const b = document.querySelector(".chat-bubble.user"); if (!b) return null; const cs = getComputedStyle(b); return { self: cs.alignSelf }; });
  check(user && user.self === "flex-end", "4. bong bóng người dùng căn phải", JSON.stringify(user));

  // 5. mobile: bong bóng nằm gọn trong khung chat
  const m = await open(browser, { viewport: { width: 375, height: 812 } });
  m.send({ type: "stream_start" });
  m.send({ type: "text_chunk", text: "Một câu trả lời đủ dài để xuống dòng trên màn hình điện thoại nhỏ, thưa Ngài." });
  m.send({ type: "stream_end" });
  await m.page.waitForTimeout(900);
  const mob = await m.page.evaluate(() => {
    const h = document.getElementById("chat-history").getBoundingClientRect();
    const b = [...document.querySelectorAll(".chat-bubble.assistant")].pop(), br = b.getBoundingClientRect();
    return { l: br.left >= h.left - 1, r: br.right <= h.right + 1 };
  });
  check(mob.l && mob.r, "5. mobile: không tràn khung chat", JSON.stringify(mob));
  await m.page.close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
