// E2E: thẻ ảnh và thẻ tệp trong chat theo kiểu claude.ai (user 2026-10-17).
//  Ảnh: nằm ngay trong câu trả lời, bo góc, viền mảnh, không phát sáng; bấm phóng to; nút tải về nhỏ nằm trên góc ảnh.
//  Tệp: thẻ gọn (icon loại tệp + tên + "PDF · 240 KB", dung lượng do backend gửi trong output_file.size) với nút tải về là icon không màu; PDF bấm thẻ là xem trước ở tab mới.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/output-cards.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };
// a 120x200 portrait SVG stands in for the upscaled picture (narrower than the column: the corner button must follow the picture)
const PNG = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="200"><rect width="120" height="200" fill="#345"/></svg>');

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/outputs/**", (r) => r.request().url().includes("img")
    ? r.fulfill({ body: PNG, headers: { "content-type": "image/svg+xml" } })
    : r.fulfill({ body: Buffer.alloc(0), headers: { "content-type": "application/pdf" } }));
  await page.route("**/api/**", (r) => r.request().url().includes("/api/outputs/") ? r.fallback() : r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.waitForTimeout(1500);
  const send = (o) => sock.send(JSON.stringify(o));

  // a document
  send({ type: "stream_start" });
  send({ type: "output_file", kind: "document", name: "bao-cao-quy-3.pdf", ext: "pdf", label: "PDF", caption: "", url: "/api/outputs/doc1", download_url: "/api/outputs/doc1?download=1", size: 245760 });
  send({ type: "text_chunk", text: "Dạ, báo cáo đây ạ." }); send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  await page.waitForTimeout(1500);
  const f = await page.evaluate(() => {
    const c = document.querySelector("#chat-history .file-card");
    if (!c) return null;
    const dl = c.querySelector(".file-download"), open = c.querySelector("a.file-open"), cs = getComputedStyle(dl);
    return { name: c.querySelector(".file-name")?.textContent, meta: c.querySelector(".file-meta-line")?.textContent, w: Math.round(c.getBoundingClientRect().width),
      dlHref: dl.getAttribute("href"), dlAttr: dl.hasAttribute("download"), dlBg: cs.backgroundImage + " " + cs.backgroundColor, dlText: dl.textContent.trim(),
      openHref: open?.getAttribute("href"), openTarget: open?.getAttribute("target") };
  });
  check(!!f && f.name === "bao-cao-quy-3.pdf" && f.meta === "PDF · 240 KB", "1. thẻ tệp: tên + loại + dung lượng", JSON.stringify(f));
  check(!!f && f.dlHref === "/api/outputs/doc1?download=1" && f.dlAttr && f.dlBg.startsWith("none") && f.dlText === "", "2. nút tải về là icon không màu, trỏ link tải", JSON.stringify(f));
  check(!!f && f.openHref === "/api/outputs/doc1" && f.openTarget === "_blank", "3. PDF: bấm thẻ là xem trước ở tab mới", JSON.stringify(f));
  check(!!f && f.w <= 420, "4. thẻ tệp gọn (≤ 420px), không giãn hết cột", String(f && f.w));

  // an image (upscale)
  send({ type: "stream_start" });
  send({ type: "output_file", kind: "image", name: "anh-upscale.png", ext: "png", label: "Ảnh", url: "/api/outputs/img1", download_url: "/api/outputs/img1?download=1" });
  send({ type: "text_chunk", text: "Ảnh đã nét hơn rồi ạ." }); send({ type: "stream_end" }); send({ type: "status", state: "idle" });
  await page.waitForTimeout(1500);
  const im = await page.evaluate(() => {
    const img = document.querySelector("#chat-history .image-result-preview");
    if (!img) return null;
    const cs = getComputedStyle(img), dl = img.closest(".image-result")?.querySelector("a.image-download");
    const last = [...document.querySelectorAll("#chat-history .chat-bubble.assistant")].pop();
    const ir = img.getBoundingClientRect(), dr = dl?.getBoundingClientRect();
    return { radius: cs.borderTopLeftRadius, shadow: cs.boxShadow, dlHref: dl?.getAttribute("href"), dlAttr: dl?.hasAttribute("download"),
      dlInside: !!dr && dr.right <= ir.right + 1 && dr.left >= ir.left && dr.top >= ir.top - 1 && dr.bottom <= ir.bottom + 1,
      strayArrow: [...last.querySelectorAll("a")].some((a) => a.textContent.includes("⬇")) };
  });
  check(!!im && im.radius === "12px" && im.shadow === "none", "5. ảnh nằm trong câu trả lời: bo góc 12px, không bóng/phát sáng", JSON.stringify(im));
  check(!!im && im.dlHref === "/api/outputs/img1?download=1" && im.dlAttr && im.dlInside, "6. nút tải ảnh nằm trên góc ảnh (trong khung ảnh)", JSON.stringify(im));
  check(!!im && !im.strayArrow, "7. không còn mũi tên ⬇ rời ở cuối câu trả lời", JSON.stringify(im));
  await page.click("#chat-history .image-result-preview");
  await page.waitForTimeout(400);
  check(await page.evaluate(() => document.getElementById("image-lightbox")?.classList.contains("active")), "8. bấm ảnh là phóng to");

  await browser.close();
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
