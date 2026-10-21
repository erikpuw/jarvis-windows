// Liquid-metal ring around the send button. Paper Shaders' liquidMetal (Apache-2.0,
// https://github.com/paper-design/shaders — same shader the metal-fx package uses)
// paints a metal disc on a WebGL2 canvas; CSS masks it down to a thin ring, so the
// button (icon + morphicons) inside stays untouched. No WebGL2 → data-metal="off",
// the button simply has no ring.
import { onBarGate } from "./anim-gate";
import { mountMetalHalo } from "./metal-halo";
import {
  ShaderMount, liquidMetalFragmentShader, LiquidMetalShapes, ShaderFitOptions,
  getShaderColorFromString,
} from "@paper-design/shaders";

function webgl2Supported(): boolean {
  try { return !!document.createElement("canvas").getContext("webgl2"); } catch { return false; }
}

export function mountMetalRing(wrap: HTMLElement): void {
  if (!webgl2Supported()) { wrap.dataset.metal = "off"; return; }
  const face = document.createElement("span");
  face.className = "metal-ring";
  face.setAttribute("aria-hidden", "true");
  wrap.prepend(face);
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  try {
    const mount = new ShaderMount(face, liquidMetalFragmentShader, {
      u_fit: ShaderFitOptions.contain,
      u_scale: 1,
      u_rotation: 0,
      u_originX: 0.5,
      u_originY: 0.5,
      u_offsetX: 0,
      u_offsetY: 0,
      u_worldWidth: 0,
      u_worldHeight: 0,
      u_colorBack: getShaderColorFromString("#0b1220"),
      u_colorTint: getShaderColorFromString("#9be7ff"),
      u_image: undefined,
      u_isImage: false,
      u_repetition: 2,
      u_shiftRed: 0.35,
      u_shiftBlue: 0.35,
      u_contour: 0.5,
      u_softness: 0.15,
      u_distortion: 0.08,
      u_angle: 70,
      u_shape: LiquidMetalShapes.circle,
    }, { preserveDrawingBuffer: true }, still ? 0 : 0.5); // kept so the halo can sample the ring's colour at any time
    wrap.dataset.metal = "on";
    mountMetalHalo(wrap, face); // metal-fx's halo round the ring, coloured from the ring (metal-halo.ts)
    if (!still) onBarGate((p) => mount.setSpeed(p ? 0 : 0.5)); // speed 0 stops the shader's own rAF loop (also while the bar is hidden)
  } catch {
    face.remove();
    wrap.dataset.metal = "off";
  }
}
