// Lớp chào (src/welcome.ts) giữ orb tắt tới tin nhắn đầu tiên. Test cần orb như trước thì gửi một tin trước.
// Gửi bằng nút #cmd-send (không dùng Enter): trên điện thoại (pointer coarse) Enter chỉ xuống dòng, không gửi (main.ts enterMakesNewLine).
exports.dismissWelcome = async (page) => {
  if (!(await page.$("#welcome"))) return;
  await page.fill("#command-input", "chào");
  await page.$eval("#cmd-send", (b) => b.click());
  await page.waitForSelector("#welcome", { state: "detached", timeout: 3000 });
};
