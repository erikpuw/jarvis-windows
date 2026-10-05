/**
 * JARVIS — Hệ thống mô phỏng hạt đa trạng thái (Multi-mode particle visualization).
 * 
 * KIẾN TRÚC CỐT LÕI:
 * - Sử dụng Three.js với BufferGeometry để tối ưu hiệu suất xử lý (N=1000 hạt).
 * - Vật lý: Hệ thống dựa trên vận tốc (Velocity-based) với lực hướng tâm và chuyển động Brownian.
 * - Logic kết nối: Tạo các đoạn thẳng (lines) động giữa các hạt lân cận.
 * 
 * CÁC CÔNG THỨC TOÁN HỌC SỬ DỤNG:
 * 1. Lực hướng tâm: F = -r * k (Kéo các hạt về bán kính currentRadius)
 * 2. Ma trận xoay 3D (3D Rotation Matrix): 
 *    - rx = x*cos(θ) - z*sin(θ)
 *    - rz = x*sin(θ) + z*cos(θ)
 * 3. Nhiễu Brownian (Brownian Noise): vel += sin(t * freq + phase) * amplitude
 */

import * as THREE from "three";

export type OrbState = "idle" | "listening" | "thinking" | "speaking" | "working";

export interface Orb {
  setState(s: OrbState): void;
  setAnalyser(a: AnalyserNode | null): void;
  pause(): void;
  resume(): void;
  /** Off: stops drawing, hands the WebGL context back to the GPU and swaps the canvas for a flat 1x1 backdrop. On: builds it again on a fresh canvas. */
  setEnabled(on: boolean): void;
  destroy(): void;
}

/** The scene itself (one WebGL context). `Orb.setEnabled` builds and destroys it. */
function buildOrb(canvas: HTMLCanvasElement): Omit<Orb, "setEnabled"> {
  let destroyed = false;
  let paused = false;
  const N = 1000;
  const MAX_RENDER_HEIGHT = 1080;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, stencil: false, powerPreference: "high-performance", });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_RENDER_HEIGHT / window.innerHeight));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x050508, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 1, 1000);
  camera.position.z = 80;

  // ── Particles ──
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(N * 3);
  const vel = new Float32Array(N * 3);
  const phase = new Float32Array(N);

  for (let i = 0; i < N; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = Math.pow(Math.random(), 0.5) * 25;
    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    pos[i * 3 + 2] = r * Math.cos(phi);
    phase[i] = Math.random() * 1000;
  }

  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));

  const mat = new THREE.PointsMaterial({
    color: 0x4ca8e8, size: 0.4, transparent: true, opacity: 0.6,
    sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });

  const points = new THREE.Points(geo, mat);
  scene.add(points);

  // ── Connection lines ──
  const MAX_LINES = 500;
  const linePos = new Float32Array(MAX_LINES * 6);
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
  lineGeo.setDrawRange(0, 0);

  const lineMat = new THREE.LineBasicMaterial({
    color: 0x4ca8e8, transparent: true, opacity: 0.0,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });

  const lines = new THREE.LineSegments(lineGeo, lineMat);
  scene.add(lines);

  // ── Plexus Mesh (Triangles between 3 nearby points) ──
  const MAX_TRIANGLES = 200;
  const triPos = new Float32Array(MAX_TRIANGLES * 9); // 3 points * 3 coords
  const triGeo = new THREE.BufferGeometry();
  triGeo.setAttribute("position", new THREE.BufferAttribute(triPos, 3));
  triGeo.setDrawRange(0, 0);
  const triMat = new THREE.MeshBasicMaterial({
    color: 0x4ca8e8, transparent: true, opacity: 0.0,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const plexus = new THREE.Mesh(triGeo, triMat);
  scene.add(plexus);

  // ── Electrons — bright dots that travel along connections ──
  const MAX_ELECTRONS = 200;
  const electronGeo = new THREE.BufferGeometry();
  const electronPos = new Float32Array(MAX_ELECTRONS * 3);
  electronGeo.setAttribute("position", new THREE.BufferAttribute(electronPos, 3));
  electronGeo.setDrawRange(0, 0);

  // 0.8 từng gấp ~2.7 lần hạt thường → chấm trắng lẻ trông như vỡ hình.
  const ELECTRON_SIZE = 0.45;
  const electronMat = new THREE.PointsMaterial({
    color: 0xffffff, size: ELECTRON_SIZE, transparent: true, opacity: 1.0,
    sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });

  const electrons = new THREE.Points(electronGeo, electronMat);
  scene.add(electrons);

  // Each electron: start point, end point, progress (0-1), speed
  interface Electron { sx: number; sy: number; sz: number; ex: number; ey: number; ez: number; t: number; speed: number; }
  const activeElectrons: Electron[] = [];
  let electronSpawnRate = 0;
  let targetElectronRate = 0;
  let lastElectronSpawn = 0; // timestamp of last spawn

  // Store active connections for electron spawning
  let activeConnections: { x1: number; y1: number; z1: number; x2: number; y2: number; z2: number }[] = [];

  // ── State ──
  let state: OrbState = "idle";
  let targetRadius = 25, currentRadius = 25;
  let targetSpeed = 0.3, currentSpeed = 0.3;
  let targetBright = 0.6, currentBright = 0.6;
  let targetSize = 0.4, currentSize = 0.4;
  let lineAmount = 0, targetLineAmount = 0;
  let lineDistance = 8, targetLineDist = 8;

  // Transition tumble
  let spinX = 0, spinY = 0, spinZ = 0;
  let transitionEnergy = 0;
  let lastState: OrbState = "idle";

  // Depth Z
  let cloudZ = 0, cloudZVel = 0;

  // Triangles tracking
  let lastTriUpdate = 0;
  let activeTriangles: [number, number, number][] = [];

  // ── Audio ──
  let analyser: AnalyserNode | null = null;
  let freqData = new Uint8Array(64);
  let bass = 0, mid = 0;

  const startedAt = performance.now(); // THREE.Clock is deprecated; only the elapsed seconds were used
  const idleColor = new THREE.Color();

  const C_WORKING = new THREE.Color(0x818cf8), C_WORKING_LINE = new THREE.Color(0xffaa00);
  const C_THINKING = new THREE.Color(0x6ec4ff), C_SPEAKING = new THREE.Color(0x7ee8a8), C_LISTENING = new THREE.Color(0x4ca8e8);

  // One loop only: pause() cancels the pending frame, otherwise pause()+resume() within a frame left
  // two loops alive and every overlay open/close added another (the orb then drew 5x per frame).
  let raf = 0;
  let lastFrame = 0;
  const FRAME_MS = 1000 / 60; // a 120 Hz screen no longer draws (and runs the physics) twice as often

  function animate(now = performance.now()) {
    raf = 0;
    if (destroyed || paused) return;
    raf = requestAnimationFrame(animate);
    if (now - lastFrame < FRAME_MS - 2) return;
    lastFrame = now;
    const t = (performance.now() - startedAt) / 1000;

    switch (state) {
      case "idle":
        targetRadius = 24; targetSpeed = 0.22; targetBright = 0.5; targetSize = 0.3;
        targetLineAmount = 0.15; targetElectronRate = 0; break;
      case "listening":
        targetRadius = 22; targetSpeed = 0.35; targetBright = 0.65; targetSize = 0.3;
        targetLineAmount = 0.5; targetElectronRate = 0; break;
      case "thinking":
        targetRadius = 18; targetSpeed = 0.45; targetBright = 0.7; targetSize = 0.3;
        targetLineAmount = 0.8; targetElectronRate = 0.015; break;
      case "speaking":
        targetRadius = 16; targetSpeed = 0.4; targetBright = 0.7; targetSize = 0.3;
        targetLineAmount = 0.4; targetLineDist = 12; targetElectronRate = 0; break;
      case "working":
        targetRadius = 14; targetSpeed = 0.38; targetBright = 0.8; targetSize = 0.3;
        targetLineAmount = 1; lineDistance = 8; targetLineDist = 12; targetElectronRate = 0.015; break;
    }

    currentRadius += (targetRadius - currentRadius) * 0.02;
    currentSpeed += (targetSpeed - currentSpeed) * 0.02;
    currentBright += (targetBright - currentBright) * 0.02;
    currentSize += (targetSize - currentSize) * 0.02;
    lineAmount += (targetLineAmount - lineAmount) * 0.02;
    lineDistance += (targetLineDist - lineDistance) * 0.02;
    electronSpawnRate += (targetElectronRate - electronSpawnRate) * 0.02;

    // Transition energy
    if (state !== lastState) { transitionEnergy = 1.0; lastState = state; }
    transitionEnergy *= 0.985;
    spinY += 0.0012; // xoay ngang chậm liên tục (~0.07 rad/s, ~90s một vòng)
    if (transitionEnergy > 0.05) {
      spinX += transitionEnergy * 0.012 * Math.sin(t * 1.7);
      spinY += transitionEnergy * 0.015;
      spinZ += transitionEnergy * 0.008 * Math.cos(t * 1.3);
    }

    // Audio
    bass = 0; mid = 0;
    if (analyser) {
      analyser.getByteFrequencyData(freqData);
      let bSum = 0, mSum = 0;
      for (let i = 0; i < 8; i++) bSum += freqData[i];
      for (let i = 8; i < 24; i++) mSum += freqData[i];
      bass = bSum / (8 * 255); mid = mSum / (16 * 255);
    }

    // --- ĐIỀU KHIỂN THU PHÓNG & NHỊP THỞ (Zoom & Breathing Control) ---
    // zTarget xác định vị trí của khối cầu trên trục Z (độ sâu)
    let zTarget = Math.sin(t * 0.12) * 8; // Mặc định là nhịp thở nhẹ
    if (state === "thinking") zTarget = Math.sin(t * 0.3) * 15 + Math.sin(t * 0.9) * 6;
    else if (state === "working") zTarget = Math.sin(t * 0.4) * 18 + Math.sin(t * 0.9) * 8;
    else if (state === "speaking") zTarget = Math.sin(t * 0.10) * 6 - bass * 0.02;

    // Tạo chuyển động mượt mà khi thay đổi độ sâu
    cloudZVel += (zTarget - cloudZ) * 0.008;
    cloudZVel *= 0.94;
    cloudZ += cloudZVel;

    points.rotation.x = spinX; points.rotation.y = spinY; points.rotation.z = spinZ;
    points.position.z = cloudZ;
    lines.rotation.x = spinX; lines.rotation.y = spinY; lines.rotation.z = spinZ;
    lines.position.z = cloudZ;
    plexus.rotation.x = spinX; plexus.rotation.y = spinY; plexus.rotation.z = spinZ;
    plexus.position.z = cloudZ;

    // ── Update particles ──
    const p = geo.getAttribute("position") as THREE.BufferAttribute;
    const a = p.array as Float32Array;

    for (let i = 0; i < N; i++) {
      const i3 = i * 3;
      let x = a[i3], y = a[i3 + 1], z = a[i3 + 2];
      const px = phase[i];

      // ── LOGIC VẬT LÝ GỐC (Original Physics) ──
      // Ghi chú: Phần tạo chuyển động nhiễu động tự do (Brownian Noise) trôi nổi tự nhiên của các hạt
      vel[i3] += Math.sin(t * 0.05 + px) * 0.001 * currentSpeed;
      vel[i3 + 1] += Math.cos(t * 0.06 + px * 1.3) * 0.001 * currentSpeed;
      vel[i3 + 2] += Math.sin(t * 0.055 + px * 0.7) * 0.001 * currentSpeed;
      vel[i3] += Math.sin(t * 0.02 + px * 2.1 + y * 0.1) * 0.0008 * currentSpeed;
      vel[i3 + 1] += Math.cos(t * 0.025 + px * 1.7 + z * 0.1) * 0.0008 * currentSpeed;
      vel[i3 + 2] += Math.sin(t * 0.022 + px * 0.9 + x * 0.1) * 0.0008 * currentSpeed;

      const dist = Math.sqrt(x * x + y * y + z * z) || 0.01;

      // ── PHẦN VỎ & ĐỊNH HÌNH QUẢ CẦU (Shell Definition) ──
      const pull = Math.max(0, dist - currentRadius) * 0.002 + 0.0003;
      vel[i3] -= (x / dist) * pull;
      vel[i3 + 1] -= (y / dist) * pull;
      vel[i3 + 2] -= (z / dist) * pull;

      // ── PHẦN ĐI TỪ LÕI RA TỚI VỎ & LỰC ĐẨY ÂM THANH (Core to Shell Audio Impulse) ──
      if (bass > 0.05) {
        vel[i3] += (x / dist) * bass * 0.005;
        vel[i3 + 1] += (y / dist) * bass * 0.005;
        vel[i3 + 2] += (z / dist) * bass * 0.005;
      }
      if (state === "speaking" && mid > 0.1) {
        const pulse = Math.sin(t * 8 + px);
        vel[i3] += (x / dist) * mid * 0.012 * pulse;
        vel[i3 + 1] += (y / dist) * mid * 0.012 * pulse;
        vel[i3 + 2] += (z / dist) * mid * 0.012 * pulse;
      }

      // ── PHẦN LÕI & TIÊU TÁN NĂNG LƯỢNG (Core Damping & Final Position) ──
      // Ghi chú: Ma sát vel *= 0.992 hãm các hạt lại để chúng tự do trôi nổi êm ái
      // và tích tụ lại khu vực trung tâm (lõi) khi không có lực đẩy âm thanh tác động.
      vel[i3] *= 0.992; vel[i3 + 1] *= 0.992; vel[i3 + 2] *= 0.992;
      a[i3] += vel[i3]; a[i3 + 1] += vel[i3 + 1]; a[i3 + 2] += vel[i3 + 2];
    }
    p.needsUpdate = true;

    // --- CẬP NHẬT CÁC ĐƯỜNG KẾT NỐI & HÌNH TAM GIÁC (Update Lines & Plexus) ---
    if (lineAmount > 0.01) {
      const lp = lineGeo.getAttribute("position") as THREE.BufferAttribute;
      const la = lp.array as Float32Array;
      const tp = triGeo.getAttribute("position") as THREE.BufferAttribute;
      const ta = tp.array as Float32Array;

      let lineCount = 0;
      let triCount = 0;

      const maxDistSq = (lineDistance * (1 + bass * 0.5)) ** 2;
      const step = Math.max(2, Math.floor(N / 300));

      if (state === "idle") {
        // --- LOGIC KẾT NỐI CHO IDLE (Giữ nguyên gốc để ổn định cấu trúc plexus) ---
        for (let i = 0; i < N && lineCount < MAX_LINES; i += step) {
          const i3 = i * 3;
          const x1 = a[i3], y1 = a[i3 + 1], z1 = a[i3 + 2];
          let pConnections = 0;

          for (let j = i + step; j < N && lineCount < MAX_LINES; j += step) {
            const j3 = j * 3;
            const dx = a[j3] - x1, dy = a[j3 + 1] - y1, dz = a[j3 + 2] - z1;
            const d2 = dx * dx + dy * dy + dz * dz;
            if (d2 < maxDistSq && pConnections < 3) {
              const idx = lineCount * 6;
              la[idx] = x1; la[idx + 1] = y1; la[idx + 2] = z1;
              la[idx + 3] = a[j3]; la[idx + 4] = a[j3 + 1]; la[idx + 5] = a[j3 + 2];
              lineCount++; pConnections++;
            }
          }
        }
      } else if (state === "listening") {
        // --- LOGIC KẾT NỐI CHO LISTENING: Nối line từ trung tâm ra rìa ngoài, ít tam giác ngẫu nhiên ---
        // 1. Phân loại các hạt ở vùng trung tâm (gần gốc tọa độ) và rìa ngoài
        for (let i = 0; i < N && lineCount < MAX_LINES; i += step) {
          const i3 = i * 3;
          const x1 = a[i3], y1 = a[i3 + 1], z1 = a[i3 + 2];
          let nb = 0, n1 = 0, n2 = 0; // first two neighbours (was an array allocated per particle per frame)
          let pConnections = 0;

          for (let j = i + step; j < N && lineCount < MAX_LINES; j += step) {
            const j3 = j * 3;
            const dx = a[j3] - x1, dy = a[j3 + 1] - y1, dz = a[j3 + 2] - z1;
            const d2 = dx * dx + dy * dy + dz * dz;
            if (d2 < maxDistSq && pConnections < 3) {
              const idx = lineCount * 6;
              la[idx] = x1; la[idx + 1] = y1; la[idx + 2] = z1;
              la[idx + 3] = a[j3]; la[idx + 4] = a[j3 + 1]; la[idx + 5] = a[j3 + 2];
              lineCount++; pConnections++;
              if (nb === 0) n1 = j3; else if (nb === 1) n2 = j3;
              nb++;
            }
          }

          if (nb >= 2 && triCount < 3) {
            const tidx = triCount * 9;
            ta[tidx] = x1; ta[tidx + 1] = y1; ta[tidx + 2] = z1;
            ta[tidx + 3] = a[n1]; ta[tidx + 4] = a[n1 + 1]; ta[tidx + 5] = a[n1 + 2];
            ta[tidx + 6] = a[n2]; ta[tidx + 7] = a[n2 + 1]; ta[tidx + 8] = a[n2 + 2];
            triCount++;
            if (lineCount < MAX_LINES) {
              const lidx = lineCount * 6;
              la[lidx] = a[n1]; la[lidx + 1] = a[n1 + 1]; la[lidx + 2] = a[n1 + 2];
              la[lidx + 3] = a[n2]; la[lidx + 4] = a[n2 + 1]; la[lidx + 5] = a[n2 + 2];
              lineCount++;
            }
          }
        }
      } else {
        // --- LOGIC KẾT NỐI CHO CÁC TRẠNG THÁI KHÁC (Vẫn giữ kết nối các đường line) ---
        for (let i = 0; i < N && lineCount < MAX_LINES; i += step) {
          const i3 = i * 3;
          const x1 = a[i3], y1 = a[i3 + 1], z1 = a[i3 + 2];
          let pConnections = 0;

          for (let j = i + step; j < N && lineCount < MAX_LINES; j += step) {
            const j3 = j * 3;
            const dx = a[j3] - x1, dy = a[j3 + 1] - y1, dz = a[j3 + 2] - z1;
            const d2 = dx * dx + dy * dy + dz * dz;
            if (d2 < maxDistSq && pConnections < 3) {
              const idx = lineCount * 6;
              la[idx] = x1; la[idx + 1] = y1; la[idx + 2] = z1;
              la[idx + 3] = a[j3]; la[idx + 4] = a[j3 + 1]; la[idx + 5] = a[j3 + 2];
              lineCount++; pConnections++;
            }
          }
        }

        // Tạo các tam giác ngẫu nhiên (không phải cứ 3 hạt là 1 tam giác) với nhịp chậm cho thinking/working, nhanh cho speaking/listening
        const triInterval = (state === "thinking" || state === "working") ? 0.5 : 0.08;
        if (t - lastTriUpdate > triInterval) {
          lastTriUpdate = t;
          activeTriangles = [];
          let attempts = 0;
          const targetPoolCount = 40;

          while (activeTriangles.length < targetPoolCount && attempts < 150) {
            attempts++;
            const i = Math.floor(Math.random() * N);
            const i3 = i * 3;
            const x1 = a[i3], y1 = a[i3 + 1], z1 = a[i3 + 2];
            const neighbors: number[] = [];

            // Duyệt nhanh một vùng ngẫu nhiên xung quanh mảng hạt để tìm lân cận
            const windowSize = 80;
            const startScan = Math.floor(Math.random() * (N - windowSize));
            for (let j = startScan; j < startScan + windowSize; j++) {
              if (j === i) continue;
              const j3 = j * 3;
              const dx = a[j3] - x1, dy = a[j3 + 1] - y1, dz = a[j3 + 2] - z1;
              if (dx * dx + dy * dy + dz * dz < maxDistSq) {
                neighbors.push(j3);
                if (neighbors.length >= 2) break;
              }
            }

            if (neighbors.length >= 2) {
              activeTriangles.push([i3, neighbors[0], neighbors[1]]);
            }
          }
        }

        // Xác định số lượng tam giác hiển thị tùy theo trạng thái
        let displayCount = activeTriangles.length;
        if (state === "thinking" || state === "working") {
          // Nhịp nhanh: thay đổi ngẫu nhiên số lượng tam giác hiển thị
          displayCount = Math.floor(12 + Math.random() * 20); // 12 đến 32 tam giác
          displayCount = Math.min(displayCount, activeTriangles.length);
        } else if (state === "speaking") {
          // Theo nhịp âm thanh (từ microphone hoặc phát âm thanh)
          const audioFactor = Math.min(1.0, (bass + mid) * 1.5);
          displayCount = Math.floor(audioFactor * activeTriangles.length);
        }

        // Đổ dữ liệu tam giác vào buffer
        for (let k = 0; k < displayCount && triCount < MAX_TRIANGLES; k++) {
          const tri = activeTriangles[k];
          if (!tri) continue;
          const [p1, p2, p3] = tri;
          const tidx = triCount * 9;
          ta[tidx] = a[p1]; ta[tidx + 1] = a[p1 + 1]; ta[tidx + 2] = a[p1 + 2];
          ta[tidx + 3] = a[p2]; ta[tidx + 4] = a[p2 + 1]; ta[tidx + 5] = a[p2 + 2];
          ta[tidx + 6] = a[p3]; ta[tidx + 7] = a[p3 + 1]; ta[tidx + 8] = a[p3 + 2];
          triCount++;
        }
      }

      lineGeo.setDrawRange(0, lineCount * 2);
      lp.needsUpdate = true;
      // Tăng độ sáng nhẹ cho lines trong idle nếu là tam giác
      lineMat.opacity = (state === "idle" || state === "listening") ? 0.12 : lineAmount * 0.08;

      triGeo.setDrawRange(0, triCount * 3);
      tp.needsUpdate = true;
      triMat.opacity = (state === "listening") ? 0.14 : (state === "speaking") ? 0.05 : lineAmount * 0.08;
      triMat.color.copy(lineMat.color);

      // Store connections for electron spawning. Only the electron spawner
      // below reads these, and it is gated on the same rate — rebuilding up to
      // 500 object literals every frame regardless meant ~30k allocations a
      // second of pure GC pressure in the states that never spawn any.
      if (electronSpawnRate > 0.005) {
        activeConnections = [];
        for (let c = 0; c < Math.min(lineCount, 500); c++) {
          const ci = c * 6;
          activeConnections.push({
            x1: la[ci], y1: la[ci + 1], z1: la[ci + 2],
            x2: la[ci + 3], y2: la[ci + 4], z2: la[ci + 5],
          });
        }
      } else if (activeConnections.length) {
        activeConnections = [];
      }
    } else {
      lineGeo.setDrawRange(0, 0);
      activeConnections = [];
    }

    // ── Update electrons — only during thinking ──
    // One fires off every ~1 second, max 3 alive, takes 2-4s to travel
    if (activeConnections.length > 0 && electronSpawnRate > 0.005) {
      if (activeElectrons.length < 3 && (t - lastElectronSpawn) > 1.0) {
        const conn = activeConnections[Math.floor(Math.random() * activeConnections.length)];
        // speed: 1/fps * speed = progress per frame. At 60fps, speed 0.005 = 200 frames = 3.3s
        activeElectrons.push({
          sx: conn.x1, sy: conn.y1, sz: conn.z1,
          ex: conn.x2, ey: conn.y2, ez: conn.z2,
          t: 0,
          speed: 0.003 + Math.random() * 0.003, // 2-4 seconds to travel
        });
        lastElectronSpawn = t;
      }
    }

    // Update electron positions
    const ep = electronGeo.getAttribute("position") as THREE.BufferAttribute;
    const ea = ep.array as Float32Array;
    let aliveCount = 0;

    for (let e = activeElectrons.length - 1; e >= 0; e--) {
      const el = activeElectrons[e];
      el.t += el.speed;
      if (el.t >= 1) {
        activeElectrons.splice(e, 1);
        continue;
      }
      const ei = aliveCount * 3;
      ea[ei] = el.sx + (el.ex - el.sx) * el.t;
      ea[ei + 1] = el.sy + (el.ey - el.sy) * el.t;
      ea[ei + 2] = el.sz + (el.ez - el.sz) * el.t;
      aliveCount++;
    }

    electronGeo.setDrawRange(0, aliveCount);
    ep.needsUpdate = true;

    // Electrons follow the same rotation/position as the main group
    electrons.rotation.x = spinX; electrons.rotation.y = spinY; electrons.rotation.z = spinZ;
    electrons.position.z = cloudZ;

    mat.opacity = currentBright + bass * 0.008;
    // Khối cầu tiến/lùi theo cloudZ; bù lại để hạt giữ đúng cỡ trên màn hình như idle,
    // không phình to (vỡ hạt) khi thinking/working kéo khối cầu sát camera (z=80).
    const depthScale = (camera.position.z - cloudZ) / camera.position.z;
    mat.size = (currentSize + bass * 0.008) * depthScale;
    electronMat.size = ELECTRON_SIZE * depthScale;

    if (state === "working") { mat.color.lerp(C_WORKING, 0.015); lineMat.color.lerp(C_WORKING_LINE, 0.015); }
    else if (state === "thinking") { mat.color.lerp(C_THINKING, 0.015); lineMat.color.lerp(C_THINKING, 0.015); }
    else if (state === "speaking") { mat.color.lerp(C_SPEAKING, 0.015); lineMat.color.lerp(C_SPEAKING, 0.015); }
    else if (state === "idle") {
      // Mic tắt: xoay nhẹ qua vòng màu, 60s một vòng (listening giữ xanh cố định).
      idleColor.setHSL((t / 60) % 1, 0.55, 0.6);
      mat.color.lerp(idleColor, 0.015); lineMat.color.lerp(idleColor, 0.015);
    }
    else { mat.color.lerp(C_LISTENING, 0.015); lineMat.color.lerp(C_LISTENING, 0.015); }

    camera.position.x = Math.sin(t * 0.02) * 5;
    camera.position.y = Math.cos(t * 0.03) * 3;
    camera.lookAt(0, 0, cloudZ * 0.2);

    renderer.render(scene, camera);
  }

  function onResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_RENDER_HEIGHT / window.innerHeight));
    renderer.setSize(window.innerWidth, window.innerHeight);
  }

  window.addEventListener("resize", onResize);
  animate();

  return {
    setState(s: OrbState) { state = s; },
    setAnalyser(a: AnalyserNode | null) {
      analyser = a;
      if (a) freqData = new Uint8Array(a.frequencyBinCount);
    },
    pause() {
      paused = true;
      cancelAnimationFrame(raf);
      raf = 0;
    },
    resume() {
      if (paused) {
        paused = false;
        lastFrame = 0;
        animate();
      }
    },
    destroy() {
      destroyed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      renderer.forceContextLoss(); // a disposed renderer still holds its GL context until the canvas is collected
    },
  };
}

export function createOrb(canvas: HTMLCanvasElement): Orb {
  let current: HTMLCanvasElement = canvas;
  let scene: Omit<Orb, "setEnabled"> | null = buildOrb(canvas);
  let state: OrbState = "idle";
  let analyser: AnalyserNode | null = null;
  let paused = false; // pause()/resume() come from overlays; they must not wake an orb the user turned off
  return {
    setState(s) { state = s; scene?.setState(s); },
    setAnalyser(a) { analyser = a; scene?.setAnalyser(a); },
    pause() { paused = true; scene?.pause(); },
    resume() { paused = false; scene?.resume(); },
    setEnabled(on) {
      if (on === (scene !== null)) return;
      if (!on) {
        scene!.destroy();
        scene = null;
        current.width = 0; // drop the drawing buffer first: no stale last frame left composited
        current.height = 0;
        // The canvas of a lost context can never get a new one, so it is replaced. Not removed: a fixed full-screen canvas always sat behind
        // the page, and without it iOS Safari in standalone mode (added to the home screen) blurs the top edge. A 1x1 flat canvas stretched by
        // CSS keeps that layer at no cost (nothing is drawn again).
        const backdrop = current.cloneNode(false) as HTMLCanvasElement;
        backdrop.width = 1;
        backdrop.height = 1;
        const g = backdrop.getContext("2d");
        if (g) { g.fillStyle = "#050508"; g.fillRect(0, 0, 1, 1); }
        current.replaceWith(backdrop);
        current = backdrop;
        return;
      }
      const fresh = current.cloneNode(false) as HTMLCanvasElement; // same id, class and style; the flat backdrop has a 2d context, so WebGL needs a new canvas
      current.replaceWith(fresh);
      current = fresh;
      scene = buildOrb(fresh);
      scene.setState(state);
      scene.setAnalyser(analyser);
      if (paused) scene.pause();
    },
    destroy() { scene?.destroy(); scene = null; },
  };
}
