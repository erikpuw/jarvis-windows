// The bot's mouth while JARVIS talks, and the three thinking dots over its head. The library's own mouth can neither open and shut nor follow a glance (it only shifts a third
// of the way with the eyes' sideways glance and never with an up/down one), so while talking the bot draws its own on top of the
// frame, placed with the library's own face maths: it moves with the eyes (same offsets) and turns with the head.
import { BOT_AVATAR_OVERSCAN, BOT_AVATAR_RISE, type BotAvatarPose } from "bot-avatars";

const REACH = 30; // radius of the face's sphere, in face units (the library's)
const MOUTH_Y = 14; // face units below the face centre; the eyes sit at about 1

export type Gaze = Pick<BotAvatarPose, "yaw" | "pitch" | "lookX" | "lookY">;
const clamp1 = (v: number) => Math.max(-1, Math.min(1, v));

/** Where a spot of the face is (dx, dy face units from its centre; the mouth by default), with the head's perspective: x, y,
 *  squash sx/sy, depth z (<= 0.02 = turned away). */
export function mouthSpot(g: Gaze, dx = 0, dy = MOUTH_Y): { x: number; y: number; sx: number; sy: number; z: number } {
  const i = Math.asin(clamp1((g.lookX + dx) / REACH)) + g.yaw;
  const o = Math.asin(clamp1(-(dy + g.lookY) / REACH)) + g.pitch;
  const r = Math.cos(o);
  return { x: REACH * Math.sin(i) * r, y: -REACH * Math.sin(o), sx: Math.cos(i), sy: r, z: Math.cos(i) * r };
}

interface FaceCfg { faceX: number; faceY: number; faceScale: number; ink: string }

/** Saves the context and sets the library's body transform: origin at the body's centre, 100 units = the body's height. */
function onBody(ctx: CanvasRenderingContext2D, pose: BotAvatarPose, box: number, dpr: number): void {
  const o = box / 100, c = Math.cos(pose.roll), s = Math.sin(pose.roll), sx = pose.sx * o, sy = pose.sy * o, v = 50 * (1 - pose.sy) * o;
  const mid = (box * BOT_AVATAR_OVERSCAN) / 2;
  ctx.save();
  ctx.setTransform(dpr * c * sx, dpr * s * sx, -dpr * s * sy, dpr * c * sy, dpr * (mid + pose.x * o - s * v), dpr * (mid + BOT_AVATAR_RISE * box + pose.y * o + c * v));
}

/** Saves the context and moves it onto a spot of the face (face units, turning with the head, with the library's body
 *  transform); false (nothing to draw, context restored) when that spot is turned away. */
function onFace(ctx: CanvasRenderingContext2D, pose: BotAvatarPose, box: number, dpr: number, cfg: FaceCfg, dx = 0, dy = MOUTH_Y): boolean {
  const spot = mouthSpot(pose, dx, dy);
  if (spot.z <= 0.02) return false;
  onBody(ctx, pose, box, dpr);
  ctx.translate(cfg.faceX - 50, cfg.faceY - 50);
  ctx.scale(cfg.faceScale, cfg.faceScale);
  ctx.translate(spot.x, spot.y);
  ctx.scale(Math.max(0.02, spot.sx), Math.max(0.02, spot.sy));
  ctx.globalAlpha = 0.93 * Math.min(1, spot.z * 5);
  return true;
}

/** Draws the mouth on a canvas already holding the bot (`open` 0 shut … 1 wide). */
export function drawMouth(ctx: CanvasRenderingContext2D, pose: BotAvatarPose, box: number, dpr: number, cfg: FaceCfg, open: number): void {
  if (!onFace(ctx, pose, box, dpr, cfg)) return;
  ctx.fillStyle = cfg.ink;
  ctx.beginPath();
  ctx.ellipse(0, 0, 7 - 2 * open, 1.5 + 6.5 * open, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

/** The sulking face: a "^" mouth on the face, and the 💢 emoji stuck on the top right corner of the head. */
export function drawSulkFace(ctx: CanvasRenderingContext2D, pose: BotAvatarPose, box: number, dpr: number, cfg: FaceCfg, now: number): void {
  if (onFace(ctx, pose, box, dpr, cfg)) {
    ctx.strokeStyle = cfg.ink;
    ctx.lineWidth = 2.2;
    ctx.lineCap = ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(-5, 2);
    ctx.lineTo(0, -2.5);
    ctx.lineTo(5, 2);
    ctx.stroke();
    ctx.restore();
  }
  // the anger mark is the 💢 emoji itself, stuck on the top right corner of the head (a hand-drawn one looked like a scar);
  // on the body, so it squashes and stretches with it
  onBody(ctx, pose, box, dpr);
  ctx.translate(29, -35); // body units from its centre (a bit in and down from the rim)
  ctx.scale(1 + Math.sin(now / 140) * 0.05, 1 + Math.sin(now / 140) * 0.05); // a slight throb
  ctx.font = '30px "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("💢", 0, 0);
  ctx.restore();
}

/** Symbolic talking, not lip-sync: a syllable opens the mouth, the gap between syllables nearly shuts it. Returns the openness. */
export function createTalk(): (now: number, dtMs: number) => number {
  let next = 0, target = 0, v = 0, opening = true;
  return (now, dtMs) => {
    if (now >= next) {
      target = opening ? 0.55 + Math.random() * 0.45 : 0.04 + Math.random() * 0.12;
      opening = !opening;
      next = now + 90 + Math.random() * 90;
    }
    v += (target - v) * Math.min(1, dtMs / 40);
    return v;
  };
}

/** Three dots above the head that appear one after another (1 -> 2 -> 3, then again) while JARVIS thinks; the first is always there. */
export function drawThinkDots(ctx: CanvasRenderingContext2D, box: number, dpr: number, now: number): void {
  const mid = (box * BOT_AVATAR_OVERSCAN) / 2, t = now % 1600;
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#d8f3ff";
  for (let i = 0; i < 3; i++) {
    ctx.globalAlpha = i ? Math.max(0, Math.min(1, (t - i * 500) / 160)) : 1;
    if (ctx.globalAlpha === 0) continue;
    ctx.beginPath();
    ctx.arc(mid + (i - 1) * 6.5, 4.2, 1.7, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

