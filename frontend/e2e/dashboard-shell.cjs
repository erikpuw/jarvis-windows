// E2E: Dashboard thay cho Settings lớp phủ (user 2026-10-17, mẫu đã duyệt).
//  PC: menu "Dashboard" bo viền luôn nằm bên trái màn chính: mép trên dưới Dynamic Island, mép dưới thẳng mép dưới thanh lệnh.
//  Bấm một mục: khung nội dung phủ từ cạnh menu tới sát mép phải, cả vùng chat lẫn thanh lệnh; màn chính dừng (anim-paused).
//  Bấm lại mục đang mở / nút đóng / Esc: đóng khung, màn chính chạy lại. Nút ở đầu menu thu menu thành dải icon.
//  Không còn nút Settings trong cụm nút góc phải. Điện thoại: nút ngôi nhà góc trên trái mở menu (ngăn kéo cùng mép trên/dưới),
//  chọn mục thì ngăn kéo đóng, khung nội dung phủ gần hết màn hình.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/dashboard-shell.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

async function open(browser, ctx) {
  const page = await (await browser.newContext(ctx)).newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  await page.waitForTimeout(1800);
  return page;
}
const rect = (page, sel) => page.evaluate((s) => {
  const e = document.querySelector(s);
  if (!e) return null;
  const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
  return { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom), w: Math.round(r.width), visible: cs.display !== "none" && cs.visibility !== "hidden" && r.width > 0 };
}, sel);
const paused = (page) => page.evaluate(() => document.documentElement.classList.contains("anim-paused"));

(async () => {
  const browser = await chromium.launch();

  // ---------- PC ----------
  const pc = await open(browser, { viewport: { width: 1440, height: 900 } });
  const W = 1440;
  const nav = await rect(pc, "#settings-nav"), bar = await rect(pc, "#command-bar-inner");
  check(nav?.visible && nav.l >= 12 && nav.l <= 20, "1. PC: menu Dashboard luôn nằm bên trái khi vừa mở trang", JSON.stringify(nav));
  check(nav && nav.t >= 50 && nav.t <= 62, "2. mép trên menu nằm dưới Dynamic Island (≈54px)", String(nav?.t));
  check(nav && bar && Math.abs(nav.b - bar.b) <= 2, "3. mép dưới menu thẳng mép dưới thanh lệnh", `${nav?.b} / ${bar?.b}`);
  check(await pc.evaluate(() => /^Dashboard/.test(document.querySelector("#settings-nav .sd-title")?.textContent.trim() || "")), "4. đầu menu ghi Dashboard");
  check(!(await pc.$("#btn-settings")), "5. cụm nút góc phải không còn nút Settings");
  check((await rect(pc, "#settings-content"))?.visible === false && !(await paused(pc)), "6. chưa chọn mục: chưa có khung nội dung, màn chính chạy");

  await pc.click('.sd-nav-item[data-page="memory"]'); await pc.waitForTimeout(500);
  const c = await rect(pc, "#settings-content");
  check(c?.visible && c.l > nav.r && c.l - nav.r <= 16 && Math.abs(c.r - (W - nav.l)) <= 2, "7. khung nội dung chạy từ cạnh menu tới sát mép phải (lề bằng lề trái menu)", JSON.stringify(c));
  check(c && c.t === nav.t && c.b === nav.b, "8. khung cùng mép trên/dưới với menu, phủ cả thanh lệnh", `${c?.t}-${c?.b} / ${nav.t}-${nav.b}`);
  const covered = await pc.evaluate(() => { const r = document.getElementById("command-bar-inner").getBoundingClientRect(); return !!document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)?.closest("#settings-content"); });
  check(covered, "9. thanh lệnh nằm dưới khung (bấm vào chỗ thanh lệnh là trúng khung)");
  check(await paused(pc), "10. khung mở: mọi hiệu ứng ở màn chính dừng (anim-paused)");
  check(await pc.evaluate(() => !document.querySelector('.sd-page[data-page="memory"]').hidden), "11. nội dung đúng trang Bộ nhớ");

  await pc.click('.sd-nav-item[data-page="memory"]'); await pc.waitForTimeout(500);
  check((await rect(pc, "#settings-content"))?.visible === false && !(await paused(pc)), "12. bấm lại mục đang mở: đóng khung, màn chính chạy lại");
  await pc.click('.sd-nav-item[data-page="voice"]'); await pc.waitForTimeout(400);
  await pc.keyboard.press("Escape"); await pc.waitForTimeout(400);
  check((await rect(pc, "#settings-content"))?.visible === false, "13. Esc đóng khung");
  await pc.click('.sd-nav-item[data-page="voice"]'); await pc.waitForTimeout(400);
  await pc.click("#settings-close"); await pc.waitForTimeout(400);
  check((await rect(pc, "#settings-content"))?.visible === false && (await rect(pc, "#settings-nav"))?.visible, "14. nút đóng: khung đóng, menu vẫn còn");

  await pc.click("#settings-sidebar-toggle"); await pc.waitForTimeout(500);
  const mini = await rect(pc, "#settings-nav");
  check(mini && mini.w <= 64, "15. nút ở đầu menu thu menu thành dải icon", String(mini?.w));
  await pc.click('.sd-nav-item[data-page="voice"]'); await pc.waitForTimeout(500);
  const c2 = await rect(pc, "#settings-content");
  check(c2 && c2.l > mini.r && c2.l - mini.r <= 16, "16. khung nội dung giãn theo dải icon", `${c2?.l} / ${mini.r}`);
  await pc.click("#settings-close"); await pc.click("#settings-sidebar-toggle"); await pc.waitForTimeout(300);

  // the menu is grouped like the approved mockup (the old flat list was too general)
  const groups = await pc.evaluate(() => [...document.querySelectorAll("#settings-nav .sd-nav-group")].map((g) => {
    const items = []; let n = g.nextElementSibling;
    while (n && !n.classList.contains("sd-nav-group")) { if (n.dataset.page) items.push(n.dataset.page); n = n.nextElementSibling; }
    return g.textContent.trim() + ":" + items.join(",");
  }));
  check(JSON.stringify(groups) === JSON.stringify(["Chung:overview,user,voice,connect", "Dữ liệu:memory,logs", "Công cụ:agents,commands,skills,prompts,hooks,plugins,mcp", "Hệ thống:system,graphfy,info"]),
    "23. menu chia 4 nhóm: Chung, Dữ liệu, Công cụ, Hệ thống", JSON.stringify(groups));

  // inside a page: the head (title + search) stays put, only the body scrolls, vertically
  await pc.click('.sd-nav-item[data-page="skills"]'); await pc.waitForTimeout(500);
  await pc.evaluate(() => { const p = document.querySelector('.sd-page[data-page="skills"] .sd-page-body'); const s = p.querySelector(".sd-agents-grid") || p; for (let i = 0; i < 40; i++) s.insertAdjacentHTML("beforeend", "<div style='height:40px'>dòng thử</div>"); });
  const before = await pc.evaluate(() => ({ head: Math.round(document.querySelector('.sd-page[data-page="skills"] .sd-page-head').getBoundingClientRect().top), search: Math.round(document.getElementById("skills-search-input").getBoundingClientRect().top) }));
  await pc.evaluate(() => { document.querySelector('.sd-page[data-page="skills"] .sd-page-body').scrollTop = 600; document.getElementById("settings-content").scrollTop = 600; });
  await pc.waitForTimeout(200);
  const after = await pc.evaluate(() => ({ head: Math.round(document.querySelector('.sd-page[data-page="skills"] .sd-page-head').getBoundingClientRect().top), search: Math.round(document.getElementById("skills-search-input").getBoundingClientRect().top), body: document.querySelector('.sd-page[data-page="skills"] .sd-page-body').scrollTop, frame: document.getElementById("settings-content").scrollTop }));
  check(after.head === before.head && after.search === before.search && after.body > 0 && after.frame === 0, "24. cuộn trang: tiêu đề và ô tìm kiếm đứng yên, chỉ thân trang cuộn", JSON.stringify({ before, after }));
  await pc.click("#settings-close");
  await pc.context().close();

  // ---------- phone ----------
  const ph = await open(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  check((await rect(ph, "#settings-nav"))?.visible === false, "17. điện thoại: menu ẩn khi vừa mở trang");
  const home = await rect(ph, "#settings-menu-toggle"), ctl = await rect(ph, "#btn-controls");
  check(home?.visible && home.l <= 20 && home.t <= 24 && ctl && Math.abs(home.w - ctl.w) <= 2, "18. nút ngôi nhà góc trên trái, cùng cỡ nút điều khiển", JSON.stringify({ home, ctl }));
  await ph.click("#settings-menu-toggle"); await ph.waitForTimeout(450);
  const dn = await rect(ph, "#settings-nav"), pbar = await rect(ph, "#command-bar-inner");
  check(dn?.visible && dn.t >= 50 && dn.t <= 62 && pbar && Math.abs(dn.b - pbar.b) <= 2, "19. bấm ngôi nhà: menu trượt ra, cùng mép trên/dưới", JSON.stringify(dn));
  await ph.click('.sd-nav-item[data-page="memory"]'); await ph.waitForTimeout(500);
  const pc2 = await rect(ph, "#settings-content");
  check((await rect(ph, "#settings-nav"))?.visible === false && pc2?.visible && pc2.l <= 16 && pc2.r >= 390 - 16, "20. chọn mục: menu đóng, khung nội dung phủ gần hết màn hình", JSON.stringify(pc2));
  check(await paused(ph), "21. điện thoại: khung mở thì màn chính dừng");
  await ph.click("#settings-close"); await ph.waitForTimeout(400);
  check((await rect(ph, "#settings-content"))?.visible === false && !(await paused(ph)), "22. đóng khung: về chat, màn chính chạy lại");

  // phone menu: "Dashboard" on top and the version at the bottom stay put, only the list between them scrolls
  await ph.click("#settings-menu-toggle"); await ph.waitForTimeout(450);
  const navBefore = await ph.evaluate(() => ({ head: Math.round(document.querySelector("#settings-nav .sd-nav-head").getBoundingClientRect().top), foot: Math.round(document.querySelector("#settings-nav .sd-nav-footer").getBoundingClientRect().bottom) }));
  await ph.evaluate(() => { document.querySelector("#settings-nav .sd-nav-list").scrollTop = 400; document.getElementById("settings-nav").scrollTop = 400; });
  await ph.waitForTimeout(200);
  const navAfter = await ph.evaluate(() => { const n = document.getElementById("settings-nav"); return { head: Math.round(n.querySelector(".sd-nav-head").getBoundingClientRect().top), foot: Math.round(n.querySelector(".sd-nav-footer").getBoundingClientRect().bottom), navScroll: n.scrollTop, navBottom: Math.round(n.getBoundingClientRect().bottom) }; });
  check(navAfter.head === navBefore.head && navAfter.foot === navBefore.foot && navAfter.navScroll === 0 && Math.abs(navAfter.foot - navAfter.navBottom) <= 14, "25. menu điện thoại: tên Dashboard và phiên bản đứng yên, chỉ danh sách cuộn", JSON.stringify({ navBefore, navAfter }));
  await ph.click("#settings-menu-toggle"); await ph.waitForTimeout(300);

  // phone: no page scrolls sideways; only its body scrolls (vertically)
  const sideways = [];
  for (const id of ["overview", "connect", "voice", "user", "system", "memory", "logs", "agents", "hooks", "skills", "prompts", "commands", "plugins", "mcp", "graphfy", "info"]) {
    await ph.evaluate((i) => document.querySelector(`.sd-nav-item[data-page="${i}"]`).click(), id); await ph.waitForTimeout(350);
    const r = await ph.evaluate((i) => { const f = document.getElementById("settings-content"), b = document.querySelector(`.sd-page[data-page="${i}"] .sd-page-body`); return { frame: f.scrollWidth - f.clientWidth, body: b ? b.scrollWidth - b.clientWidth : 999 }; }, id);
    if (r.frame > 1 || r.body > 1) sideways.push(`${id}:${r.frame}/${r.body}`);
    await ph.evaluate(() => document.getElementById("settings-close").click()); await ph.waitForTimeout(150);
  }
  check(sideways.length === 0, "26. điện thoại: không trang nào cuộn ngang được", sideways.join(" "));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
