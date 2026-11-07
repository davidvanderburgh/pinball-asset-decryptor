// The cabinet's expression light patterns (PAD-1040): the mode runtime's "CAB FX" slice (pad_mode_runtime.c), line for
// line in C's integer arithmetic, so the Expression lights page shows what the machine's blades and speaker lights
// will. tests/test_pad1040_cab_shows.py compiles the C slice and runs this file over every pattern, colour for colour.
//
// `| 0` truncates toward zero as C's int division does; the C's unsigned products wrap at 32 bits, so they are
// Math.imul(...) >>> 0 here; its unsigned divisions are of non-negative numbers, so Math.floor is the same.

export const CX_NAMES = ["solid", "fade_in", "fade_out", "crossfade", "pulse", "strobe", "sweep_up", "sweep_down",
  "fill_up", "fill_down", "chase_up", "chase_down", "bounce", "center_out", "center_in", "alternate", "rainbow",
  "sparkle", "fire", "meter"];

const i32 = (v) => v | 0;
const u32 = (v) => v >>> 0;
const udiv = (a, b) => Math.floor(a / b);

export function cxMix(a, b, f) {
  if (f < 0) f = 0;
  if (f > 256) f = 256;
  let out = 0;
  for (let k = 0; k < 3; k++) {
    const sh = 16 - 8 * k;
    const ca = (a >>> sh) & 255, cb = (b >>> sh) & 255;
    out |= ((ca + i32((cb - ca) * f / 256)) & 255) << sh;
  }
  return out >>> 0;
}
const cxScale = (c, f) => cxMix(0, c, f);

function cxHue(h) {
  const s = ((h % 1536) + 1536) % 1536, i = i32(s / 256), f = s % 256;
  switch (i) {
    case 0: return u32((255 << 16) | (f << 8));
    case 1: return u32(((255 - f) << 16) | (255 << 8));
    case 2: return u32((255 << 8) | f);
    case 3: return u32(((255 - f) << 8) | 255);
    case 4: return u32((f << 16) | 255);
    default: return u32((255 << 16) | (255 - f));
  }
}

export function cxHash(v) {
  v = u32(v);
  v = u32(v ^ (v >>> 16));
  v = u32(Math.imul(v, 0x7feb352d));
  v = u32(v ^ (v >>> 15));
  v = u32(Math.imul(v, 0x846ca68b));
  v = u32(v ^ (v >>> 16));
  return v;
}

function cxBand(a, b, w, head, trail) {
  if (w < 0) return b;
  if (w < head) return a;
  if (w < head + trail) return cxMix(a, b, i32((w - head) * 256 / trail));
  return b;
}

// the colour of a light (its side, its place u along its strip, its number k) for step st at `t` ms into it
export function cxColour(st, side, u, k, t) {
  const fx = typeof st.fx === "number" ? st.fx : CX_NAMES.indexOf(st.fx);
  const rate = st.rate ? st.rate : 100;
  const f = st.ms ? (t >= st.ms ? 256 : udiv(t * 256, st.ms)) : 256;
  const up = u, down = 999 - u;
  let p, d, v;
  switch (CX_NAMES[fx]) {
    case "solid": return st.a >>> 0;
    case "fade_in": return cxScale(st.a, f);
    case "fade_out": return cxScale(st.a, 256 - f);
    case "crossfade": return cxMix(st.a, st.b, f);
    case "pulse":
      v = udiv((t % (rate * 2)) * 512, rate * 2);
      return cxMix(st.b, st.a, v < 256 ? v : 512 - v);
    case "strobe": return (udiv(t, rate) % 2 ? st.b : st.a) >>> 0;
    case "sweep_up":
    case "sweep_down":
      p = i32(f * 1500 / 256) - 100;
      return cxBand(st.a, st.b, p - (fx === 6 ? up : down), 120, 300) >>> 0;
    case "fill_up":
    case "fill_down":
      return ((fx === 8 ? up : down) < i32(f * 1000 / 256) ? st.a : st.b) >>> 0;
    case "chase_up":
    case "chase_down":
      v = udiv(t * 125, rate) % 125;
      d = fx === 10 ? (up - v + 125) % 125 : (up + v) % 125;
      return (d < 40 ? st.a : st.b) >>> 0;
    case "bounce":
      p = i32((f < 128 ? f * 2 : (256 - f) * 2) * 1000 / 256);
      d = up - p;
      if (d < 0) d = -d;
      if (d < 100) return st.a >>> 0;
      if (d < 300) return cxMix(st.a, st.b, i32((d - 100) * 256 / 200));
      return st.b >>> 0;
    case "center_out":
    case "center_in":
      d = up - 500;
      if (d < 0) d = -d;
      if (fx === 13) return cxBand(st.a, st.b, i32(f * 800 / 256) - 60 - d, 60, 200) >>> 0;
      return cxBand(st.a, st.b, d - (i32((256 - f) * 800 / 256) - 60), 60, 200) >>> 0;
    case "alternate":
      v = udiv(t, rate) % 2;
      d = side ? (side < 0 ? 1 : 0) : k % 2;
      return (d === v ? st.a : st.b) >>> 0;
    case "rainbow":
      return cxHue(udiv(u * 1536, 1000) + udiv(t * 1536, rate * 10));
    case "sparkle":
      return (cxHash(u32(Math.imul(k, 7919) + Math.imul(udiv(t, 60), 104729))) % 100 < 18 ? st.a : st.b) >>> 0;
    case "fire":
      v = cxHash(u32(Math.imul(k, 7919) + Math.imul(udiv(t, 50), 104729))) % 90;
      return cxScale(cxMix(st.b, st.a, i32(down * 256 / 1000) + v - 45), 150 + v);
    case "meter":
      p = 250 + cxHash(u32(Math.imul(udiv(t, rate), 2654435761 | 0) + (side + 1))) % 750;
      if (up >= p) return 0;
      return (up > p - 90 ? st.b : st.a) >>> 0;
  }
  return 0;
}

// the colour for the step on, blending in from the step before (`prev`, null = from dark) over its first `blend` ms
export function cxBlend(st, prev, side, u, k, t) {
  let c = cxColour(st, side, u, k, t);
  if (st.blend && t < st.blend) c = cxMix(prev ? cxColour(prev, side, u, k, prev.ms) : 0, c, udiv(t * 256, st.blend));
  return c;
}

// ------------------------------------------------------------------ a show, as the runtime plays it (cab_step_at)
// A step as the runtime holds it: colours as numbers (the sidecar keeps "#rrggbb").
export function compileStep(st) {
  const hex = (c) => parseInt(String(c || "#000000").slice(1), 16) >>> 0;
  return { fx: CX_NAMES.indexOf(st.fx), ms: Math.max(1, st.ms | 0), a: hex(st.a), b: hex(st.b), rate: st.rate | 0,
           blend: Math.min(st.blend | 0, Math.max(1, st.ms | 0)) };
}

// One lane `el` ms into the show: { i: the step (-1: the lane has none), t: the ms into it, over: its steps ran out }
export function laneAt(steps, loop, el) {
  const n = steps.length;
  if (!n) return { i: -1, t: 0, over: false };
  let total = 0;
  for (const s of steps) total += s.ms ? s.ms : 1;
  if (el >= total) {
    if (!loop) return { i: n, t: 0, over: true };
    el %= total;
  }
  let at = 0;
  for (let i = 0; i < n; i++) {
    const ms = steps[i].ms ? steps[i].ms : 1;
    if (el < at + ms) return { i, t: el - at, over: false };
    at += ms;
  }
  return { i: n, t: 0, over: true };
}

// Every light's colour `el` ms into the show (`lanes`: [blade steps, speaker steps], compiled); null = the game's
// (a lane with no steps), 0 = held dark (its steps ran out)
export function showColours(lights, lanes, loop, el) {
  const at = [laneAt(lanes[0], loop, el), laneAt(lanes[1], loop, el)];
  return lights.map((L, k) => {
    const a = at[L.lane];
    if (a.i < 0) return null;
    if (a.over) return 0;
    const steps = lanes[L.lane];
    return cxBlend(steps[a.i], a.i ? steps[a.i - 1] : null, L.side, L.u, k, a.t);
  });
}
