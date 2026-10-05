// E2E: thẻ agent (flow_agents) gọn và cố định chiều rộng.
//  Việc agent đang làm có thể rất dài (nhiều dòng như cả đề bài tìm máy giặt): thẻ chỉ hiện MỘT dòng rút gọn bằng "…", mọi thẻ cùng một chiều rộng,
//  hàng đầu = icon agent · tên agent · dấu trạng thái sát mép phải; chữ đầy đủ xem bằng cách rê chuột (thuộc tính title).
//  Thẻ KHÔNG xổ ra khi bấm (đã thử, nhìn kỳ cục): chỉ rút gọn một dòng. Rộng bằng khung các bước (flow_tracker): 240px như cũ, không nới ra.
// WebSocket và /api bị mock. Chạy: PW=<module playwright> node frontend/e2e/agent-card.cjs   (cần `npm run dev` ở :5173)
const { chromium } = require(process.env.PW || "playwright");
const BASE = process.env.BASE_URL || "http://localhost:5173/";
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!ok) failed++; };

const LONG = ["Tôi đang tìm mua máy giặt", "Tôi chỉ mua ở Điện máy xanh", "Nhu cầu sử dụng cho 7 người lớn, Ưu tiên loại từ 11kg trở lên", "Có động cơ truyền động trực tiếp (quan trọng)",
  "Máy giặt cửa trên", "Ưu tiên độ bền và giá dưới 10tr", "Hãy chọn và lọc giúp tôi top 5 máy giặt thực tế hợp với nhu cầu của tôi nhất"].join("\n");
const SHORT = "thông tin Máy giặt Panasonic Inverter 11.5 kg NA-FJ115X1BV";

async function run(width) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width, height: 800 } });
  let sock = null;
  await page.routeWebSocket(/\/ws/, (ws) => { sock = ws; });
  await page.route("**/api/**", (r) => r.fulfill({ json: { success: true, env_keys_set: { llama: true } } }));
  await page.goto(BASE);
  for (let i = 0; i < 50 && !sock; i++) await page.waitForTimeout(100);
  await page.evaluate(() => document.getElementById("command-container")?.classList.add("visible"));
  const send = (m) => sock.send(JSON.stringify(m));
  send({ type: "stream_start" });
  send({ type: "flow_step", step: { id: 1, label: "Nhận: tìm máy giặt", status: "completed" } });
  send({ type: "interactive", card: { id: "a1", type: "tracker", title: "🔎 Agent Search", status: "active", label: "Thực thi: " + LONG } });
  send({ type: "interactive", card: { id: "a2", type: "tracker", title: "🔎 Agent Search", status: "completed", label: SHORT } });
  await page.waitForSelector(".tracker-card .tracker-label", { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(600);
  const cards = await page.evaluate(() => [...document.querySelectorAll(".tracker-card")].map((c) => {
    const r = (e) => e.getBoundingClientRect(), label = c.querySelector(".tracker-label"), cs = getComputedStyle(label);
    return {
      w: Math.round(r(c).width), right: r(c).right, labelH: Math.round(r(label).height), ws: cs.whiteSpace, to: cs.textOverflow, ov: cs.overflow, clipped: label.scrollWidth > label.clientWidth,
      title: label.title, iconX: r(c.querySelector(".tracker-agent-icon")).left, nameX: r(c.querySelector(".tracker-name")).left, statusX: r(c.querySelector(".tracker-icon-container")).right,
    };
  }));
  const [a, b] = cards;
  const tag = `[${width}px]`;
  check(cards.length === 2, `${tag} 1. có hai thẻ agent`, String(cards.length));
  check(a && a.ws === "nowrap" && a.to === "ellipsis" && a.ov === "hidden" && a.labelH <= 20, `${tag} 2. việc dài nhiều dòng chỉ hiện MỘT dòng rút gọn bằng …`, JSON.stringify({ ws: a?.ws, to: a?.to, h: a?.labelH }));
  check(a && a.clipped, `${tag} 3. chữ dài thật sự bị cắt (có …), chữ ngắn thì không`, `${a?.clipped}/${b?.clipped}`);
  const widths = await page.evaluate(() => ({ flow: Math.round(document.querySelector(".chat-bubble.system-flow")?.getBoundingClientRect().width ?? 0), bubble: Math.round(document.querySelector('[data-card-id="a1"]')?.getBoundingClientRect().width ?? 0), bubble2: Math.round(document.querySelector('[data-card-id="a2"]')?.getBoundingClientRect().width ?? 0) }));
  check(a && b && a.w === b.w && widths.bubble === widths.bubble2, `${tag} 4. mọi thẻ cùng chiều rộng cố định, không co giãn theo nội dung`, `${a?.w} / ${b?.w}`);
  check(widths.flow > 0 && widths.bubble === widths.flow && widths.flow <= 240, `${tag} 4b. thẻ agent rộng bằng khung các bước (flow_tracker) như cũ, tối đa 240px`, JSON.stringify(widths));
  const click = await page.evaluate(async () => { const c = document.querySelector('[data-card-id="a1"] .tracker-card'); const h = c.getBoundingClientRect().height; c.click(); await new Promise((r) => setTimeout(r, 400)); return { before: Math.round(h), after: Math.round(c.getBoundingClientRect().height), cls: c.classList.contains("expanded"), aria: c.getAttribute("aria-expanded"), cursor: getComputedStyle(c).cursor }; });
  check(click.before === click.after && !click.cls && click.aria === null && click.cursor !== "pointer", `${tag} 4c. bấm vào thẻ KHÔNG xổ ra (cao như cũ, không con trỏ bàn tay)`, JSON.stringify(click));
  check(a && a.iconX < a.nameX && a.nameX < a.statusX && a.right - a.statusX <= 12, `${tag} 5. hàng đầu: icon agent → tên agent → dấu trạng thái sát mép phải`, JSON.stringify({ i: a?.iconX, n: a?.nameX, s: a?.statusX, r: a?.right }));
  check(a && a.title.includes("Máy giặt cửa trên") && !a.title.startsWith("Thực thi"), `${tag} 6. rê chuột hiện đầy đủ nội dung (title)`, (a?.title || "").slice(0, 60));
  await browser.close();
}

(async () => {
  await run(1280);
  await run(390);
  console.log(failed ? `\n${failed} FAIL` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
