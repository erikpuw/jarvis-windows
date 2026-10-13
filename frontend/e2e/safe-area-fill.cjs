// E2E: vùng an toàn phía trên (dưới thanh trạng thái) trên iPhone (viewport-fit=cover, manifest standalone).
//  Lỗi: lúc mới nạp trang vùng đó đen liền với trang; vào Cài đặt rồi thoát thì một dải cao bằng vùng an toàn ở trên cùng đổi sang màu xám xanh
//  (Safari mới lấy màu thanh trên từ phần tử fixed ở mép trên màn hình, và giữ lại màu của lớp phủ vừa mở), cả trang trông như bị đẩy xuống.
//  Đúng: luôn có một phần tử fixed phủ đúng vùng an toàn phía trên, màu nền trang (#050508), nằm trên mọi lớp phủ (Cài đặt, media, ảnh phóng to) nên Safari chỉ
//  thấy một màu duy nhất ở mép trên; và đóng Cài đặt thì trang không bị cuộn lệch (scroll về 0).
// WebSocket và /api bị mock; vùng an toàn giả lập qua CDP (Emulation.setSafeAreaInsetsOverride). Chạy: PW=<module playwright> node frontend/e2e/safe-area-fill.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
const TOP = 47;

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  await page.routeWebSocket(/\/ws/, () => {});
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  const cdp = await ctx.newCDPSession(page);
  let emulated = true;
  await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: TOP, left: 0, bottom: 0, right: 0 } }).catch(() => { emulated = false; });
  await page.goto(BASE);
  await page.waitForTimeout(1800);
  const info = () => page.evaluate(() => {
    const f = document.getElementById("safe-top-fill");
    if (!f) return null;
    const cs = getComputedStyle(f), r = f.getBoundingClientRect(), top = document.elementFromPoint(195, 1);
    const z = (id) => { const e = document.getElementById(id); return e ? parseInt(getComputedStyle(e).zIndex) || 0 : 0; };
    return { pos: cs.position, bg: cs.backgroundColor, pe: cs.pointerEvents, z: parseInt(cs.zIndex), h: r.height, top0: r.top, w: r.width, vw: innerWidth, topEl: top && (top.id || top.className || top.tagName), maxOther: Math.max(z("settings-container"), z("image-lightbox"), z("media-player")), scroll: [scrollY, document.documentElement.scrollTop, document.body.scrollTop] };
  });

  let s = await info();
  check(!!s, "1. có phần tử phủ vùng an toàn phía trên (#safe-top-fill)", JSON.stringify(s));
  if (!s) { await browser.close(); console.log("\n" + failed + " FAIL"); process.exit(1); }
  check(s.pos === "fixed" && s.top0 === 0 && Math.abs(s.w - s.vw) < 1 && s.bg === "rgb(5, 5, 8)" && s.pe === "auto", "2. cố định ở mép trên, rộng đủ màn hình, màu nền trang #050508, nhận chạm (iOS chỉ lấy màu từ phần tử chạm trúng ở mép trên)", JSON.stringify({ pos: s.pos, bg: s.bg, pe: s.pe, w: s.w }));
  const orbZ = await page.evaluate(() => parseInt(getComputedStyle(document.getElementById("orb-canvas")).zIndex) || 0);
  const beforeOrb = await page.evaluate(() => !!(document.getElementById("safe-top-fill").compareDocumentPosition(document.getElementById("orb-canvas")) & Node.DOCUMENT_POSITION_FOLLOWING));
  check(s.topEl === "safe-top-fill", "3b. điểm ở mép trên (ngoài nút menu/đảo) chạm trúng lớp màu nền tối", String(s.topEl));
  check(s.z <= orbZ && beforeOrb && s.z < s.maxOther, "3. nằm dưới quả cầu và mọi lớp phủ (không hiện thành vạch đen trên Cài đặt)", `z ${s.z} · quả cầu ${orbZ} · đứng trước quả cầu ${beforeOrb}`);
  if (emulated) {
    check(Math.abs(s.h - TOP) < 1, `4. cao đúng bằng vùng an toàn (${TOP}px)`, `${s.h}px`);
  } else console.log("skip 4: trình duyệt không hỗ trợ giả lập vùng an toàn");
  if (emulated) {
    // status bar "black" (home-screen app) and a Safari tab report a top safe area of 0: the layer must still be there for iOS to
    // take the top colour from (else it takes Settings' slate top bar and keeps it after Settings closes)
    await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: 0, left: 0, bottom: 0, right: 0 } });
    await page.waitForTimeout(200);
    const h0 = await page.evaluate(() => document.getElementById("safe-top-fill").getBoundingClientRect().height);
    check(h0 >= 4, "4b. vùng an toàn trên = 0 (thanh trạng thái black, tab Safari): lớp phủ vẫn cao ≥ 4px để iOS lấy màu nền tối", `${h0}px`);
    await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: TOP, left: 0, bottom: 0, right: 0 } });
    await page.waitForTimeout(200);
  }

  // vào Cài đặt rồi thoát
  await page.evaluate(() => document.getElementById("btn-settings").click());
  await page.waitForTimeout(500);
  s = await info();
  // device test 2026-10-12: any background colour on Settings' top bar (or its fixed box) kills the notch gradient, in the Safari
  // tab and in the home-screen app alike, and it stays lost after Settings closes: both stay transparent
  const bgs = await page.evaluate(() => ["#settings-container", "#settings-container .sd-root", "#settings-container .sd-topbar"]
    .map((q) => getComputedStyle(document.querySelector(q)).backgroundColor));
  check(bgs.every((c) => c === "rgba(0, 0, 0, 0)"), "6b. Cài đặt mở: khung cố định, sd-root và thanh tiêu đề đều không có màu nền (có màu là iOS mất gradient tai thỏ)", JSON.stringify(bgs));
  await page.evaluate(() => { window.scrollTo(0, 40); document.body.scrollTop = 40; }); // iOS để lại trang bị cuộn khi bàn phím/Cài đặt
  await page.evaluate(() => document.getElementById("settings-close").click());
  await page.waitForTimeout(500);
  const edge = await page.evaluate(() => { const e = document.elementFromPoint(195, 1); return e && (e.id || e.className); });
  check(edge === "safe-top-fill", "7c. thoát Cài đặt: điểm ở mép trên chạm trúng lớp màu nền tối (iOS tô lại thanh trạng thái màu tối, không giữ màu Cài đặt)", String(edge));
  s = await info();
  check(s.scroll.every((v) => v === 0), "7. thoát Cài đặt: trang về đầu, không bị cuộn lệch", JSON.stringify(s.scroll));

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
