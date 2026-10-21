// E2E: phím Enter trong ô nhập lệnh (#command-input).
//  Máy tính: Enter gửi, Shift+Enter xuống dòng (như cũ).
//  Điện thoại (màn cảm ứng): bàn phím không có Shift+Enter nên Enter chỉ XUỐNG DÒNG, gửi bằng nút gửi.
//  Khi danh sách gợi ý (/ hoặc @) đang mở thì Enter vẫn chọn gợi ý, không xuống dòng.
//  Sau khi gửi: máy tính giữ con trỏ trong ô nhập để gõ tiếp; điện thoại BỎ focus để bàn phím ảo tụt xuống, trả về màn hình chính.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/cmd-enter.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, opts) {
  const page = await (await browser.newContext(opts)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.route("**/api/command-bar/skills", (r) => r.fulfill({ json: { success: true, commands: [{ name: "check_mail", description: "kiem tra thu" }] } }));
  await page.route("**/api/command-bar/context", (r) => r.fulfill({ json: { success: true, agents: [], files: [] } }));
  await page.goto(BASE); await page.waitForTimeout(1500);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  await page.waitForTimeout(300);
  return page;
}
const val = (page) => page.$eval("#command-input", (e) => e.value);
const userBubbles = (page) => page.$$eval(".chat-bubble.user", (b) => b.map((x) => x.textContent.trim()));

(async () => {
  const browser = await chromium.launch();

  // máy tính
  let page = await open(browser, { viewport: { width: 1280, height: 800 } });
  await page.click("#command-input"); await page.keyboard.type("dong mot"); await page.keyboard.press("Shift+Enter"); await page.keyboard.type("dong hai");
  check((await val(page)) === "dong mot\ndong hai", "1a. máy tính: Shift+Enter xuống dòng", JSON.stringify(await val(page)));
  await page.keyboard.press("Enter"); await page.waitForTimeout(500);
  const sent = await userBubbles(page);
  check((await val(page)) === "" && sent.length === 1 && /dong mot/.test(sent[0]) && /dong hai/.test(sent[0]), "1b. máy tính: Enter gửi cả hai dòng", JSON.stringify(sent));
  check((await page.$eval("#command-input", (e) => e.enterKeyHint)) === "send", "1c. máy tính: phím Enter của bàn phím gợi ý là \"gửi\"");
  check(await page.evaluate(() => document.activeElement?.id === "command-input"), "1d. máy tính: sau khi gửi, con trỏ vẫn ở ô nhập để gõ tiếp");
  await page.context().close();

  // điện thoại
  page = await open(browser, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  check(await page.evaluate(() => matchMedia("(pointer: coarse)").matches), "2a. giả lập điện thoại là màn cảm ứng (pointer: coarse)");
  await page.click("#command-input"); await page.keyboard.type("dong 1"); await page.keyboard.press("Enter"); await page.keyboard.type("dong 2");
  check((await val(page)) === "dong 1\ndong 2", "2b. điện thoại: Enter chỉ xuống dòng, không gửi", JSON.stringify(await val(page)));
  await page.waitForTimeout(300);
  check((await userBubbles(page)).length === 0, "2c. điện thoại: bấm Enter không tạo tin nhắn nào");
  await page.keyboard.press("Enter"); await page.keyboard.type("dong 3");
  check((await val(page)) === "dong 1\ndong 2\ndong 3", "2d. điện thoại: Enter nhiều lần vẫn chỉ xuống dòng", JSON.stringify(await val(page)));
  const h = await page.$eval("#command-input", (e) => e.getBoundingClientRect().height);
  check(h > 30, "2e. điện thoại: ô nhập cao lên theo số dòng", String(Math.round(h)));
  check((await page.$eval("#command-input", (e) => e.enterKeyHint)) === "enter", "2f. điện thoại: phím Enter của bàn phím gợi ý là xuống dòng");
  await page.click("#cmd-send"); await page.waitForTimeout(500);
  const sent2 = await userBubbles(page);
  check((await val(page)) === "" && sent2.length === 1 && /dong 1/.test(sent2[0]) && /dong 3/.test(sent2[0]), "2g. điện thoại: nút gửi gửi cả ba dòng", JSON.stringify(sent2));

  check(await page.evaluate(() => document.activeElement?.id !== "command-input" && document.activeElement === document.body), "2i. điện thoại: bấm nút gửi xong ô nhập mất focus → bàn phím ảo tụt xuống, không còn treo", await page.evaluate(() => document.activeElement?.tagName + "#" + document.activeElement?.id));
  await page.click("#command-input"); await page.keyboard.type("tam"); await page.keyboard.press("Enter");
  check(await page.evaluate(() => document.activeElement?.id === "command-input"), "2j. điện thoại: Enter chỉ xuống dòng nên bàn phím vẫn mở để gõ tiếp");
  await page.fill("#command-input", "");

  // gợi ý đang mở: Enter chọn gợi ý, không xuống dòng
  await page.click("#command-input"); await page.keyboard.type("/check"); await page.waitForTimeout(500);
  const shown = await page.evaluate(() => !document.getElementById("command-suggest").classList.contains("hidden") && document.querySelectorAll("#command-suggest .suggest-item, #command-suggest [data-suggest]").length >= 0);
  await page.keyboard.press("Enter"); await page.waitForTimeout(400);
  const v = await val(page);
  check(shown && !v.includes("\n") && /check_mail/.test(v), "2h. điện thoại: gợi ý đang mở thì Enter chọn gợi ý (/check_mail), không xuống dòng", JSON.stringify(v));
  await page.context().close();

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
