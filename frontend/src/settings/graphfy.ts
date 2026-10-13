/**
 * Graphfy — JARVIS structure map generated from the code (/api/graphfy, backend
 * engine/UIUX/graphfy.py scans imports). Nothing here is hand-drawn: a new module
 * shows up by itself. Layout is lanes: top band follows a turn left → right with the
 * LLM as the central column; bottom band holds memory, ingestion, background jobs.
 * Import edges are faint and only LLM calls carry a pulse; edges to the shared hubs
 * (server, tools, UIUX: nearly everything imports them) are hidden until "Hiện tất cả"
 * or until one of their nodes is hovered. Hover a node to isolate its edges;
 * drag to rearrange (positions in localStorage only).
 */
import { apiGet, escapeHtml } from "./api";

type Lane = "input" | "turn" | "llm" | "output" | "memory" | "ingestion" | "background" | "support" | "other";
interface ApiNode { id: string; label: string; lane: Lane; }
interface ApiEdge { from: string; to: string; kind: "import" | "llm"; }
interface GNode extends ApiNode { x: number; y: number; w: number; h: number; }

const W = 150;
const H = 30;
const ROW = 40;
const HEAD = 34; // lane title height
const VIEW_W = 1160;
const BAND_GAP = 40;
// the LLM hub is drawn as a circuit brain (90% width), not a box
const BRAIN_W = 114;
const BRAIN_H = 120;
// the outline sits inside the box: side edges attach where the lobes are widest
const BRAIN_INSET = 16;
const BRAIN_SIDE_Y = 0.45;
// bump when the layout model changes, so positions saved for an old map are dropped
const POS_KEY = "jarvis.graphfy.positions.v4";

const LANES: { id: Lane; title: string; color: string }[] = [
  { id: "input", title: "Đầu vào", color: "#38bdf8" },
  { id: "turn", title: "Xử lý lượt", color: "#f59e0b" },
  { id: "llm", title: "LLM", color: "#c084fc" },
  { id: "output", title: "Phản hồi", color: "#4ade80" },
  { id: "memory", title: "Bộ nhớ · học", color: "#f472b6" },
  { id: "ingestion", title: "Nạp tài liệu", color: "#22d3ee" },
  { id: "background", title: "Chạy nền", color: "#94a3b8" },
  { id: "support", title: "Hỗ trợ", color: "#64748b" },
  { id: "other", title: "Khác (chưa gán làn)", color: "#eab308" },
];
const TOP: Lane[] = ["input", "turn", "llm", "output"];
const BOTTOM: Lane[] = ["memory", "ingestion", "background", "support", "other"];
// imported by nearly every module: their edges only show on hover or with "Hiện tất cả"
const HUBS = new Set(["server", "tools", "UIUX"]);
const COLOR = Object.fromEntries(LANES.map((l) => [l.id, l.color])) as Record<Lane, string>;

const fileOf = (id: string) =>
  id === "server" ? "server.py" : id.includes("/") ? `engine/${id}.py` : `engine/${id}/`;

function layout(nodes: ApiNode[]): { nodes: GNode[]; height: number; titles: string } {
  const byLane = (l: Lane) => nodes.filter((n) => n.lane === l);
  const topRows = Math.max(1, ...TOP.map((l) => byLane(l).length));
  const topH = HEAD + Math.max(topRows * ROW, BRAIN_H + 10);
  const bottomLanes = BOTTOM.filter((l) => byLane(l).length);
  const bottomRows = Math.max(0, ...bottomLanes.map((l) => byLane(l).length));
  const out: GNode[] = [];
  let titles = "";
  const place = (lanes: Lane[], y0: number, bandH: number) => {
    const step = VIEW_W / lanes.length;
    lanes.forEach((l, i) => {
      const x = Math.round(i * step + (step - W) / 2);
      const col = byLane(l);
      const meta = LANES.find((m) => m.id === l)!;
      titles += `<text class="gf-lane-title" x="${x}" y="${y0 + 16}" fill="${meta.color}">${meta.title}</text>`;
      // the LLM column holds one node: centre it so every caller's edge converges on it
      if (l === "llm") {
        const bx = x + Math.round((W - BRAIN_W) / 2);
        const by = y0 + HEAD + Math.round((bandH - HEAD - col.length * BRAIN_H) / 2);
        col.forEach((n, r) => out.push({ ...n, x: bx, y: by + r * BRAIN_H, w: BRAIN_W, h: BRAIN_H }));
        return;
      }
      col.forEach((n, r) => out.push({ ...n, x, y: y0 + HEAD + r * ROW, w: W, h: H }));
    });
  };
  place(TOP, 0, topH);
  if (bottomLanes.length) place(bottomLanes, topH + BAND_GAP, HEAD + bottomRows * ROW);
  const height = topH + (bottomLanes.length ? BAND_GAP + HEAD + bottomRows * ROW : 0);
  return { nodes: out, height, titles };
}

function edgePath(a: GNode, b: GNode): string {
  if (b.lane === "llm" && a.y > b.y + b.h) {
    // callers below the brain plug into its signal pins
    const x1 = a.x + a.w / 2, y1 = a.y, x2 = b.x + b.w / 2, y2 = b.y + b.h * 0.92; // middle pin (y 184/200)
    const dy = Math.max(40, (y1 - y2) * 0.5);
    return `M${x1},${y1} C${x1},${y1 - dy} ${x2},${y2 + dy} ${x2},${y2}`;
  }
  const ac = a.x + a.w / 2, bc = b.x + b.w / 2;
  if (Math.abs(ac - bc) < W) {
    // same column: bow out to the right
    const x1 = a.x + a.w, x2 = b.x + b.w, y1 = a.y + a.h / 2, y2 = b.y + b.h / 2;
    const bow = 30 + Math.min(60, Math.abs(y2 - y1) / 4);
    return `M${x1},${y1} C${x1 + bow},${y1} ${x2 + bow},${y2} ${x2},${y2}`;
  }
  const forward = bc > ac;
  const inA = a.lane === "llm" ? BRAIN_INSET : 0, inB = b.lane === "llm" ? BRAIN_INSET : 0;
  const x1 = forward ? a.x + a.w - inA : a.x + inA, x2 = forward ? b.x + inB : b.x + b.w - inB;
  const y1 = a.y + a.h * (inA ? BRAIN_SIDE_Y : 0.5), y2 = b.y + b.h * (inB ? BRAIN_SIDE_Y : 0.5);
  const dx = Math.max(40, Math.abs(x2 - x1) * 0.5) * (forward ? 1 : -1);
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}

// Circuit brain, drawn for this app (left: gyri, right: traces ending in pads,
// bottom: signal pins). 190x200 artwork, squeezed to 90% width, scaled to BRAIN_W.
function brainSvg(): string {
  const traces = ["M104 34 H122 V28", "M104 56 H132", "M104 76 H116 V68 H140", "M104 96 H150", "M104 116 H124 V126 H142"];
  const pads: [number, number][] = [[122, 24], [136, 56], [144, 68], [154, 96], [146, 126], [122, 136]];
  const sx = (x: number) => (100 + (x - 100) * 0.9).toFixed(1);
  return `<g class="gf-brain" transform="scale(${(BRAIN_H / 200).toFixed(3)}) translate(${-(100 - (BRAIN_W / (BRAIN_H / 200)) / 2).toFixed(1)} 0)">
    <ellipse class="gf-brain-aura" cx="100" cy="86" rx="66" ry="80"></ellipse>
    <rect class="gf-brain-hit" x="20" y="4" width="160" height="186"></rect>
    <g class="gf-brain-lines" transform="translate(100 0) scale(0.9 1) translate(-100 0)">
      <path vector-effect="non-scaling-stroke" d="M96 18 C82 10 66 14 60 26 C44 24 34 40 38 54 C24 60 22 80 32 90 C22 100 26 122 40 126 C40 142 56 152 70 146 C76 158 92 158 96 150 Z"/>
      <path vector-effect="non-scaling-stroke" d="M52 42 C60 46 62 58 56 64 M40 76 C52 74 62 80 62 92 M44 108 C54 104 66 108 68 120 M76 28 C80 40 74 48 80 58 M82 72 C74 80 78 92 88 94 M78 114 C86 120 84 132 76 136"/>
      <path vector-effect="non-scaling-stroke" d="M104 18 C118 10 134 14 140 26 C156 24 166 40 162 54 C176 60 178 80 168 90 C178 100 174 122 160 126 C160 142 144 152 130 146 C124 158 108 158 104 150 Z"/>
      <path vector-effect="non-scaling-stroke" d="${traces.join(" ")} M104 136 H118"/>
      ${traces.map((d, i) => `<path class="gf-brain-trace" vector-effect="non-scaling-stroke" d="${d}" style="animation-delay:${(i * 0.3).toFixed(1)}s"></path>`).join("")}
    </g>
    <path class="gf-brain-lines" d="M90 152 V170 M100 152 V180 M110 152 V170"></path>
    <path class="gf-brain-trace" d="M100 180 V152"></path>
    ${pads.map(([x, y], i) => `<circle class="gf-brain-pad" cx="${sx(x)}" cy="${y}" r="5" style="animation-delay:${(i * 0.4).toFixed(1)}s"></circle>`).join("")}
    <circle class="gf-brain-pin" cx="90" cy="174" r="4"></circle><circle class="gf-brain-pin" cx="100" cy="184" r="4"></circle><circle class="gf-brain-pin" cx="110" cy="174" r="4"></circle>
  </g>`;
}

function nodeSvg(n: GNode): string {
  const c = COLOR[n.lane];
  if (n.lane === "llm") {
    return `<g class="gf-node gf-lane-llm" data-id="${escapeHtml(n.id)}" transform="translate(${n.x},${n.y})" style="--gf-c:${c}">
    <title>${escapeHtml(fileOf(n.id))}</title>${brainSvg()}
  </g>`;
  }
  return `<g class="gf-node gf-lane-${n.lane}" data-id="${escapeHtml(n.id)}" transform="translate(${n.x},${n.y})" style="--gf-c:${c}">
    <title>${escapeHtml(fileOf(n.id))}</title>
    <rect width="${W}" height="${H}" rx="7" class="gf-node-box"></rect>
    <rect width="3" height="${H - 12}" x="0" y="6" rx="1.5" fill="${c}"></rect>
    <text x="12" y="${H / 2 + 4.5}" class="gf-node-label">${escapeHtml(n.label.length > 19 ? n.label.slice(0, 18) + "…" : n.label)}</text>
  </g>`;
}

function edgeSvg(e: ApiEdge, byId: Map<string, GNode>, i: number): string {
  const a = byId.get(e.from), b = byId.get(e.to);
  if (!a || !b) return "";
  const d = edgePath(a, b);
  const support = a.lane === "support" || b.lane === "support";
  const color = e.kind === "llm" ? COLOR.llm : COLOR[a.lane];
  const hub = e.kind === "import" && (HUBS.has(e.from) || HUBS.has(e.to));
  const dur = 2.8 + (i % 7) * 0.4;
  // simulated flow on the LLM calls only; negative begin puts each pulse mid-flight on first paint
  const pulse = e.kind !== "llm" ? "" : `<circle class="gf-pulse" r="2.4"><animateMotion dur="${dur}s" begin="-${((i * 0.37) % dur).toFixed(2)}s" repeatCount="indefinite" path="${d}"></animateMotion></circle>`;
  return `<g class="gf-link${support ? " gf-support" : ""}${hub ? " gf-hub" : ""}" data-from="${escapeHtml(e.from)}" data-to="${escapeHtml(e.to)}" data-kind="${e.kind}" style="--gf-e:${color}">
    <path class="gf-edge gf-edge-${e.kind}" d="${d}"></path>${pulse}
  </g>`;
}

function loadPositions(): Record<string, [number, number]> {
  try { return JSON.parse(localStorage.getItem(POS_KEY) || "{}"); } catch { return {}; }
}
function savePositions(nodes: Iterable<GNode>): void {
  try { localStorage.setItem(POS_KEY, JSON.stringify(Object.fromEntries([...nodes].map((n) => [n.id, [n.x, n.y]])))); } catch { /* storage blocked */ }
}

function enableInteraction(svg: SVGSVGElement, byId: Map<string, GNode>, viewH: number): void {
  const links = () => svg.querySelectorAll<SVGGElement>(".gf-link");
  const clear = () => svg.querySelectorAll(".gf-dim").forEach((e) => e.classList.remove("gf-dim"));
  svg.addEventListener("pointerover", (ev) => {
    const el = (ev.target as Element).closest<SVGGElement>(".gf-node");
    // off any node (empty canvas, an edge, a lane title) → show every flow again
    if (!el) { clear(); return; }
    const id = el.dataset.id!;
    const near = new Set([id]);
    links().forEach((l) => {
      const on = l.dataset.from === id || l.dataset.to === id;
      l.classList.toggle("gf-dim", !on);
      if (on) { near.add(l.dataset.from!); near.add(l.dataset.to!); }
    });
    svg.querySelectorAll<SVGGElement>(".gf-node").forEach((n) => n.classList.toggle("gf-dim", !near.has(n.dataset.id!)));
  });
  svg.addEventListener("pointerleave", clear);

  let drag: { node: GNode; el: SVGGElement; dx: number; dy: number } | null = null;
  const toSvg = (ev: PointerEvent) => {
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    return pt.matrixTransform(svg.getScreenCTM()!.inverse());
  };
  svg.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "touch") return; // a finger pans the (wider than the screen) map; dragging nodes is for mouse/pen
    const el = (ev.target as Element).closest<SVGGElement>(".gf-node");
    if (!el) return;
    const node = byId.get(el.dataset.id!)!;
    const p = toSvg(ev);
    drag = { node, el, dx: p.x - node.x, dy: p.y - node.y };
    el.classList.add("dragging");
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const p = toSvg(ev);
    drag.node.x = Math.max(0, Math.min(VIEW_W - drag.node.w, p.x - drag.dx));
    drag.node.y = Math.max(0, Math.min(viewH - drag.node.h, p.y - drag.dy));
    drag.el.setAttribute("transform", `translate(${drag.node.x},${drag.node.y})`);
    links().forEach((link) => {
      if (link.dataset.from !== drag!.node.id && link.dataset.to !== drag!.node.id) return;
      const d = edgePath(byId.get(link.dataset.from!)!, byId.get(link.dataset.to!)!);
      link.querySelector("path")!.setAttribute("d", d);
      link.querySelector("animateMotion")?.setAttribute("path", d);
    });
  });
  const end = () => {
    if (!drag) return;
    drag.el.classList.remove("dragging");
    drag = null;
    savePositions(byId.values());
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
}

let renderToken = 0;

/** Renders the generated map into #graphfy-map. */
export async function renderGraphfy(_loadCatalog?: unknown): Promise<void> {
  const host = document.getElementById("graphfy-map");
  if (!host) return;
  const token = ++renderToken;
  let data: { nodes: ApiNode[]; edges: ApiEdge[] };
  try {
    data = await apiGet("/api/graphfy");
  } catch (err) {
    if (token === renderToken) host.innerHTML = `<div class="sd-empty">Không dựng được sơ đồ: ${escapeHtml(String((err as Error)?.message || err))}</div>`;
    return;
  }
  // a newer render (reopen, reset) started while we awaited: drop this one
  if (token !== renderToken) return;
  const { nodes, height, titles } = layout(data.nodes || []);
  const saved = loadPositions();
  for (const n of nodes) {
    const pos = saved[n.id];
    if (pos) [n.x, n.y] = [Math.max(0, Math.min(VIEW_W - n.w, pos[0])), Math.max(0, Math.min(height - n.h, pos[1]))];
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  host.innerHTML = `<svg class="gf-svg" viewBox="-10 -6 ${VIEW_W + 20} ${height + 12}" preserveAspectRatio="xMidYMin meet" role="img" aria-label="Sơ đồ cấu trúc JARVIS tự sinh từ code">
    <defs><pattern id="gf-dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" class="gf-grid-dot"></circle></pattern></defs>
    <rect x="-10" y="-6" width="${VIEW_W + 20}" height="${height + 12}" fill="url(#gf-dots)"></rect>
    ${titles}
    <g class="gf-edges">${(data.edges || []).map((e, i) => edgeSvg(e, byId, i)).join("")}</g>
    <g class="gf-nodes">${nodes.map(nodeSvg).join("")}</g>
  </svg>`;
  enableInteraction(host.querySelector<SVGSVGElement>("svg")!, byId, height);
}

/** Shows or hides the edges to the shared hubs; the choice survives a re-render (it sits on #graphfy-map). */
export function toggleGraphfyAll(btn: HTMLButtonElement): void {
  const all = document.getElementById("graphfy-map")?.classList.toggle("gf-all") ?? false;
  btn.textContent = all ? "Ẩn bớt" : "Hiện tất cả";
  btn.setAttribute("aria-pressed", String(all));
}

/** Restores the default layout. */
export function resetGraphfyLayout(_loadCatalog?: unknown): void {
  try { localStorage.removeItem(POS_KEY); } catch { /* ignore */ }
  void renderGraphfy();
}
