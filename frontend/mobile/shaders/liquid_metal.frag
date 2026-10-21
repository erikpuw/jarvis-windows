// Paper Shaders "liquid metal" (Apache-2.0, https://github.com/paper-design/shaders), the fragment shader the web send button uses
// (frontend/src/metal-ring.ts), adapted for Flutter's FragmentProgram:
//  - only the non-image, circle-shape path is kept (u_isImage = false, u_shape = circle), with metal-ring.ts's fixed fit
//    (contain, scale 1, no rotation/offset) folded in: on a square box v_objectUV + .5 is just fragCoord / size;
//  - Flutter's GLSL subset has no derivatives (fwidth), so each one is a finite difference of the same function one pixel
//    to the right / down (the raw circle edge is analytic);
//  - the CSS mask radial-gradient(circle closest-side, transparent 80%, #000 84%) that cuts the disc to a thin ring is
//    applied at the end;
//  - the output is premultiplied alpha, as Flutter expects.
#version 460 core
#include <flutter/runtime_effect.glsl>

precision highp float;

uniform vec2 u_size;
uniform float u_time;
uniform vec4 u_colorBack;
uniform vec4 u_colorTint;
uniform float u_softness;
uniform float u_repetition;
uniform float u_shiftRed;
uniform float u_shiftBlue;
uniform float u_distortion;
uniform float u_contour;
uniform float u_angle;

out vec4 fragColor;

#define PI 3.14159265358979323846

vec2 rotate(vec2 uv, float th) {
  return mat2(cos(th), sin(th), -sin(th), cos(th)) * uv;
}

vec3 permute(vec3 x) { return mod(((x * 34.0) + 1.0) * x, 289.0); }
float snoise(vec2 v) {
  const vec4 C = vec4(0.211324865405187, 0.366025403784439,
    -0.577350269189626, 0.024390243902439);
  vec2 i = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1;
  i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
    + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy),
      dot(x12.zw, x12.zw)), 0.0);
  m = m * m;
  m = m * m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x = a0.x * x0.x + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

float getColorChanges(float c1, float c2, float stripe_p, vec3 w, float blur, float bump, float tint) {
  float ch = mix(c2, c1, smoothstep(.0, 2. * blur, stripe_p));

  float border = w[0];
  ch = mix(ch, c2, smoothstep(border, border + 2. * blur, stripe_p));

  border = w[0] + .4 * (1. - bump) * w[1];
  ch = mix(ch, c1, smoothstep(border, border + 2. * blur, stripe_p));

  border = w[0] + .5 * (1. - bump) * w[1];
  ch = mix(ch, c2, smoothstep(border, border + 2. * blur, stripe_p));

  border = w[0] + w[1];
  ch = mix(ch, c1, smoothstep(border, border + 2. * blur, stripe_p));

  float gradient_t = (stripe_p - w[0] - w[1]) / w[2];
  float gradient = mix(c1, c2, smoothstep(0., 1., gradient_t));
  ch = mix(ch, gradient, smoothstep(border, border + .5 * blur, stripe_p));

  // Tint color is applied with color burn blending
  ch = mix(ch, 1. - min(1., (1. - ch) / max(tint, 0.0001)), u_colorTint.a);
  return ch;
}

// the circle's raw edge value, analytic in the pixel position (the web shader takes fwidth of it)
float rawEdge(vec2 fc) {
  vec2 uv = fc / u_size;
  vec2 shapeUV = (uv - .5) * .67;
  return pow(clamp(3. * length(shapeUV), 0., 1.), 18.);
}

// Everything of the web main() up to the three stripe phases; fc is the pixel position.
void field(vec2 fc, float t, out vec3 stripe, out float edgeOut, out float bumpOut) {
  vec2 uv = fc / u_size;
  float cycleWidth = u_repetition;

  vec2 rotatedUV = uv - vec2(.5);
  float angle = (-u_angle + 70.) * PI / 180.;
  float cosA = cos(angle);
  float sinA = sin(angle);
  rotatedUV = vec2(
    rotatedUV.x * cosA - rotatedUV.y * sinA,
    rotatedUV.x * sinA + rotatedUV.y * cosA
  ) + vec2(.5);

  float edge = rawEdge(fc);
  float fwE = abs(rawEdge(fc + vec2(1., 0.)) - edge) + abs(rawEdge(fc + vec2(0., 1.)) - edge);
  edge = mix(smoothstep(.9 - 2. * fwE, .9, edge), edge, smoothstep(0.0, 0.4, u_contour));
  edge = 1.2 * edge; // u_shape < 2 (circle)

  float diagBLtoTR = rotatedUV.x - rotatedUV.y;

  vec2 grad_uv = uv - .5;

  float dist = length(grad_uv + vec2(0., .2 * diagBLtoTR));
  grad_uv = rotate(grad_uv, (.25 - .2 * diagBLtoTR) * PI);
  float direction = grad_uv.x;

  float bump = pow(1.8 * dist, 1.2);
  bump = 1. - bump;
  bump *= pow(uv.y, .3);

  float noise = snoise(uv - t);

  edge += (1. - edge) * u_distortion * noise;

  direction += diagBLtoTR;
  direction -= 2. * noise * diagBLtoTR * (smoothstep(0., 1., edge) * (1.0 - smoothstep(0., 1., edge)));
  direction *= mix(1., 1. - edge, smoothstep(.5, 1., u_contour));
  direction -= 1.7 * edge * smoothstep(.5, 1., u_contour);
  direction += .2 * pow(u_contour, 4.) * (1.0 - smoothstep(0., 1., edge));

  bump *= clamp(pow(uv.y, .1), .3, 1.);
  direction *= (.1 + (1.1 - edge) * bump);

  direction *= (.4 + .6 * (1.0 - smoothstep(.5, 1., edge)));
  direction += .18 * (smoothstep(.1, .2, uv.y) * (1.0 - smoothstep(.2, .4, uv.y)));
  direction += .03 * (smoothstep(.1, .2, 1. - uv.y) * (1.0 - smoothstep(.2, .4, 1. - uv.y)));

  direction *= (.5 + .5 * pow(uv.y, 2.));
  direction *= cycleWidth;
  direction -= t;

  float colorDispersion = (1. - bump);
  colorDispersion = clamp(colorDispersion, 0., 1.);
  float dispersionRed = colorDispersion;
  dispersionRed += .03 * bump * noise;
  dispersionRed += 5. * (smoothstep(-.1, .2, uv.y) * (1.0 - smoothstep(.1, .5, uv.y))) * (smoothstep(.4, .6, bump) * (1.0 - smoothstep(.4, 1., bump)));
  dispersionRed -= diagBLtoTR;

  float dispersionBlue = colorDispersion;
  dispersionBlue *= 1.3;
  dispersionBlue += (smoothstep(0., .4, uv.y) * (1.0 - smoothstep(.1, .8, uv.y))) * (smoothstep(.4, .6, bump) * (1.0 - smoothstep(.4, .8, bump)));
  dispersionBlue -= .2 * edge;

  dispersionRed *= (u_shiftRed / 20.);
  dispersionBlue *= (u_shiftBlue / 20.);

  stripe = vec3(
    fract(direction + dispersionRed),
    fract(direction),
    fract(direction - dispersionBlue)
  );
  edgeOut = edge;
  bumpOut = bump;
}

void main() {
  vec2 fc = FlutterFragCoord().xy;

  const float firstFrameOffset = 2.8;
  float t = .3 * (u_time + firstFrameOffset);

  vec3 s0;
  vec3 sx;
  vec3 sy;
  float edge;
  float bump;
  float edgeX;
  float bumpX;
  float edgeY;
  float bumpY;
  field(fc, t, s0, edge, bump);
  field(fc + vec2(1., 0.), t, sx, edgeX, bumpX);
  field(fc + vec2(0., 1.), t, sy, edgeY, bumpY);
  vec3 fw = abs(sx - s0) + abs(sy - s0);

  float rawE = rawEdge(fc);
  float fwE = abs(rawEdge(fc + vec2(1., 0.)) - rawE) + abs(rawEdge(fc + vec2(0., 1.)) - rawE);
  float opacity = 1. - smoothstep(.9 - 2. * fwE, .9, rawE);

  vec2 uv = fc / u_size;
  float angle = (-u_angle + 70.) * PI / 180.;
  vec2 rotatedUV = uv - vec2(.5);
  rotatedUV = vec2(
    rotatedUV.x * cos(angle) - rotatedUV.y * sin(angle),
    rotatedUV.x * sin(angle) + rotatedUV.y * cos(angle)
  ) + vec2(.5);
  float diagTLtoBR = rotatedUV.x + rotatedUV.y;

  vec3 color1 = vec3(.98, 0.98, 1.);
  vec3 color2 = vec3(.1, .1, .1 + .1 * smoothstep(.7, 1.3, diagTLtoBR));

  float cycleWidth = u_repetition;
  float thin_strip_1_ratio = .12 / cycleWidth * (1. - .4 * bump);
  float thin_strip_2_ratio = .07 / cycleWidth * (1. + .4 * bump);
  float wide_strip_ratio = (1. - thin_strip_1_ratio - thin_strip_2_ratio);
  float thin_strip_1_width = cycleWidth * thin_strip_1_ratio;
  float thin_strip_2_width = cycleWidth * thin_strip_2_ratio;

  float blur = u_softness / 15.; // the web adds .3 * contour, and contour is 0 on this path

  vec3 w = vec3(thin_strip_1_width, thin_strip_2_width, wide_strip_ratio);
  w[1] -= .02 * smoothstep(.0, 1., edge + bump);
  float r = getColorChanges(color1.r, color2.r, s0.r, w, blur + fw.r, bump, u_colorTint.r);
  float g = getColorChanges(color1.g, color2.g, s0.g, w, blur + fw.g, bump, u_colorTint.g);
  float b = getColorChanges(color1.b, color2.b, s0.b, w, blur + fw.b, bump, u_colorTint.b);

  vec3 color = vec3(r, g, b);
  color *= opacity;

  vec3 bgColor = u_colorBack.rgb * u_colorBack.a;
  color = color + bgColor * (1. - opacity);
  opacity = opacity + u_colorBack.a * (1. - opacity);

  color += 1. / 256. * (fract(sin(dot(.014 * fc, vec2(12.9898, 78.233))) * 43758.5453123) - .5);

  // metal-ring.ts masks the disc with CSS: radial-gradient(circle closest-side, transparent 80%, #000 84%)
  float rr = length(uv - .5) * 2.;
  // and the box is round (border-radius: 50%; overflow: hidden): the outer edge is only anti-aliased, about one
  // device pixel (0.35 pt at dpr 3; rr is in radii, so w pt = 2w / u_size), as the browser clips it. A wider fade
  // (it was 0.75 pt) thinned the ring next to the web's.
  float ring = smoothstep(.80, .84, rr) * (1. - smoothstep(1. - .7 / u_size.x, 1., rr));
  color *= ring;
  opacity *= ring;

  fragColor = vec4(color, opacity);
}
