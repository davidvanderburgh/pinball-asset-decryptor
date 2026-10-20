// Modes: the Light shows view of a blocks mode (PAD-646). David: "a way to create light-shows from scratch in a
// beautiful and elegant way ... pre-programmed presets with timing options and a way to preview it in the App ...
// multiple light shows throughout a mode".
//
// A mode keeps its own named shows (blocks.json `shows`: [{name, steps, repeat}], block_modes._norm_shows), and a
// Run the light show block runs one by name from any rule. This tab makes them: the mode's shows down the left
// (new from a ready-made one or blank, duplicate, rename, delete), the game's own playfield picture in the middle
// PLAYING the show picked - every placed insert painted by the same arithmetic the C runs on the machine
// (block_modes._SHOW_C fx_colour, mirrored below integer for integer, tests/test_pad646_light_shows.py proves the
// two agree) - and on the right the show's steps as a timeline (a bar per step, as wide as it is long, its two
// colors), the step picked with its pattern, time, colors, centre, pace, GI and blend-in, and the rules that run
// the show, with a way to add it to another.
//
// It is a tab over the one program (modes_blocks.js useModeProgram): an edit here is a step of the mode's one
// history and is saved to the same blocks.json; the Blocks tab's Run the light show block lists the shows made here.

import { html, useEffect, useRef, useState, Button, Field, Select, Note, tip, cx, openMenu } from "../core/ui.js";
import { loadPlayfield } from "./modes_playfield.js";
import { hatWords } from "./modes_views.js";

const TIP = {
  list: "The mode's own light shows: a Run the light show block runs one by name, from any rule.",
  newShow: "A new show for the mode: blank, or starting from one of the ready-made ones.",
  dup: "A copy of this show, to change.",
  del: "Take this show out of the mode. A rule that runs it is told so under Blocks.",
  name: "The show's name: what a Run the light show block picks. Renaming it renames it in every rule.",
  repeat: "How many times the show runs when a block runs it. Over and over: until the mode ends (the pass it is in finishes), or until another show runs.",
  play: "Play the show on the picture, as the machine will play it over the inserts.",
  stop: "Stop, back to the start.",
  loop: "Play it again when it ends.",
  scrub: "Where in the show the picture is: drag to any moment.",
  timeline: "The show's steps, one bar each, as wide as the step is long: press one to change it.",
  addStep: "A new step at the end of the show (a copy of the last).",
  fx: "The pattern this step paints over the inserts.",
  ms: "How long this step lasts, ms.",
  blend: "The step blends in from the one before over its first ms (0: it starts at once). The first step blends up from dark.",
  a: "Its first color: the ring, the band, the beam, the lit inserts.",
  b: "Its second color: the wake, the ground, the inserts the pattern is not on.",
  at: "Where the pattern centers: a place on the playfield, or a point of its own picked on the picture.",
  pick: "Press the picture where this step should center.",
  rate: "The pattern's pace, ms: how fast a strobe, a spin, a chase, ripples or a pulse move (0: its usual).",
  gi: "What the lights between the inserts (the GI strings) do during this step.",
  stepUp: "Move this step earlier", stepDown: "Move this step later", stepDup: "A copy of this step after it", stepDel: "Take this step out",
  runs: "The rules that run this show. Add it to another with Run it when…",
  runWhen: "Put a Run the light show block for this show at the end of a rule, or in a new one.",
  noArt: "The game's own playfield picture could not be read from the card, so the inserts are drawn on an outline.",
  legacy: "A Run the light show block with steps of its own, made in the Blocks tab before this page: bring it in here as one of the mode's shows, to preview and change.",
};
const WORDS = { xy: "a point of its own" };
const SWATCHES = ["#ffffff", "#ffd000", "#ffb000", "#ff7800", "#ff3000", "#ff0000", "#ff40a0", "#a040ff", "#4000a0",
  "#0050ff", "#00a0ff", "#00e0ff", "#00c040", "#00ff60", "#000000"];
const TRACK_PX = 520;

// ------------------------------------------------------------------ the engine, as the C runs it (block_modes._SHOW_C)
// Every function here is the C's line for line, in C's integer arithmetic (|0 truncates toward zero as C's int
// division does; the unsigned divisions are of non-negative numbers, so floor is the same).
const i32 = (v) => v | 0;
export function fxMix(a, b, f) {
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
const fxScale = (c, f) => fxMix(0, c, f);
const rgb = (r, g, b) => (((r & 255) << 16) | ((g & 255) << 8) | (b & 255)) >>> 0;
function fxHue(h) {
  const s = ((h % 1536) + 1536) % 1536, i = i32(s / 256), f = s % 256;
  switch (i) {
    case 0: return rgb(255, f, 0);
    case 1: return rgb(255 - f, 255, 0);
    case 2: return rgb(0, 255, f);
    case 3: return rgb(0, 255 - f, 255);
    case 4: return rgb(f, 0, 255);
    default: return rgb(255, 0, 255 - f);
  }
}
function fxRand(S) {
  S.seed = (Math.imul(S.seed, 1103515245) + 12345) >>> 0;
  return (S.seed >>> 16) & 0x7fff;
}
function fxIsqrt(v) {
  let r = 0, b = 1 << 14;
  if (v <= 0) return 0;
  while (b > v) b >>= 2;
  while (b) {
    if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1;
    b >>= 2;
  }
  return r;
}
function fxAngle(dx, dy) {
  const ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy;
  if (!ax && !ay) return 0;
  let a = ax >= ay ? i32((ay * 192) / (ax ? ax : 1)) : 384 - i32((ax * 192) / (ay ? ay : 1));
  if (dx < 0) a = 768 - a;
  if (dy < 0) a = 1536 - a;
  return a % 1536;
}
// the color of the insert at (x, y) for step st at `t` ms into it; S holds the show's random seed
export function fxColour(st, x, y, idx, t, S) {
  const f = st.ms ? i32(t * 256 / st.ms) : 256;
  const dx = x - st.x, dy = y - st.y;
  const rate = st.rate ? st.rate : 100;
  const a = st.a, b = st.b;
  let d, r, w, v;
  switch (st.fx) {
    case "burst": case "implode":
      d = fxIsqrt(dx * dx + dy * dy);
      r = st.fx === "burst" ? i32(f * 700 / 256) : i32((256 - f) * 700 / 256);
      w = d - r;
      if (w > 0 && w < 60) return fxScale(a, 256 - w * 4);
      if (w <= 0 && w > -140) return fxMix(a, b, i32(-w * 256 / 140));
      return w <= 0 ? b : 0;
    case "sweep_up": case "sweep_down":
      r = st.fx === "sweep_up" ? 640 - i32(f * 720 / 256) : i32(f * 720 / 256) - 40;
      w = st.fx === "sweep_up" ? y - r : r - y;
      if (w >= 0 && w < 50) return a;
      if (w >= 50) return fxMix(a, b, (w - 50) * 3);
      return 0;
    case "sweep_lr": case "sweep_rl":
      r = st.fx === "sweep_lr" ? i32(f * 380 / 256) - 40 : 340 - i32(f * 380 / 256);
      w = st.fx === "sweep_lr" ? r - x : x - r;
      if (w >= 0 && w < 30) return a;
      if (w >= 30) return fxMix(a, b, (w - 30) * 4);
      return 0;
    case "spin":
      v = (fxAngle(dx, dy) - i32(t * 1536 / (rate * 8))) % 1536;
      if (v < 0) v += 1536;
      return v < 160 ? a : v < 400 ? fxMix(a, b, i32((v - 160) * 256 / 240)) : b;
    case "rainbow":
      return fxHue(fxAngle(dx, dy) + i32(t * 1536 / (rate * 10)) + fxIsqrt(dx * dx + dy * dy) * 2);
    case "strobe":
      return i32(t / rate) % 2 ? b : a;
    case "sparkle":
      return ((fxRand(S) + idx * 7) % 100) < 18 ? a : b;
    case "fire":
      v = fxRand(S) % 90;
      w = i32((600 - y) * 256 / 600);
      return fxScale(fxMix(b, a, w + v - 45), 150 + v);
    case "pulse":
      v = i32((t % (rate * 2)) * 512 / (rate * 2));
      v = v < 256 ? v : 512 - v;
      return fxMix(b, a, v);
    case "chase":
      v = (i32(fxAngle(dx, dy) * 12 / 1536) + 12 - (i32(t / rate) % 12)) % 12;
      return v === 0 ? a : v === 1 ? fxScale(a, 110) : b;
    case "fade":
      return fxScale(a, 256 - f);
    case "bolts":
      v = i32(t / rate) % 5;
      r = 40 + v * 55 + ((y * 13 + v * 71) % 40) - 20;
      w = x - r;
      if (w < 0) w = -w;
      return w < 18 && (t % rate) < i32(rate * 2 / 3) ? a : b;
    case "spiral_out": case "spiral_in":
      d = fxIsqrt(dx * dx + dy * dy) + i32(fxAngle(dx, dy) * 140 / 1536);
      r = st.fx === "spiral_out" ? i32(f * 840 / 256) : i32((256 - f) * 840 / 256);
      w = d - r;
      if (w > 0 && w < 60) return fxScale(a, 256 - w * 4);
      if (w <= 0 && w > -140) return fxMix(a, b, i32(-w * 256 / 140));
      return w <= 0 ? b : 0;
    case "ripple":
      d = fxIsqrt(dx * dx + dy * dy);
      v = ((i32(d * 256 / 140) - i32(t * 256 / rate)) % 256 + 256) % 256;
      return fxMix(a, b, v < 128 ? v * 2 : (256 - v) * 2);
    case "bounce":
      v = f < 128 ? f * 2 : (256 - f) * 2;
      r = i32(v * 380 / 256) - 40;
      w = x - r;
      if (w < 0) w = -w;
      if (w < 30) return a;
      return fxMix(a, b, (w - 30) * 4);
    case "fade_in":
      return fxScale(a, f);
    case "solid":
      return a;
    default:
      return 0;
  }
}
// the step's color blending in from the step before (fx_blend): from dark when there is none
export function fxBlend(st, prev, x, y, idx, t, S) {
  let c = fxColour(st, x, y, idx, t, S);
  if (st.blend && t < st.blend) c = fxMix(prev ? fxColour(prev, x, y, idx, prev.ms, S) : 0, c, i32(t * 256 / st.blend));
  return c;
}

// A step as the C's table row holds it: colors as numbers, its centre as a point (block_modes.step_c)
const hex = (s) => (/^#[0-9a-fA-F]{6}$/.test(s || "") ? parseInt(s.slice(1), 16) : 0);
export function compileStep(st, placeXY) {
  const [px, py] = st.at === "xy" ? [st.x, st.y] : (placeXY[st.at] || placeXY.center || [150, 330]);
  const ms = Math.max(50, Math.min(10000, Number(st.ms) || 500));
  return { fx: st.fx, ms, a: hex(st.a), b: hex(st.b), x: Number(px) || 0, y: Number(py) || 0,
    rate: Math.max(0, Math.min(2000, Number(st.rate) || 0)), gi: st.gi || "keep",
    blend: Math.max(0, Math.min(10000, Number(st.blend) || 0)) };
}
// where a show is at `t` ms in: its step, the ms into it, the step before (a blend's), and whether it is over
export function showAt(steps, repeat, t) {
  const pass = steps.reduce((s, x) => s + x.ms, 0);
  if (!steps.length || pass <= 0) return { over: true };
  const passes = repeat > 0 ? repeat : Infinity;
  if (t >= pass * passes) return { over: true, pass, passes };
  const n = Math.floor(t / pass);
  let u = t - n * pass, i = 0;
  while (i < steps.length - 1 && u >= steps[i].ms) { u -= steps[i].ms; i += 1; }
  const prev = i > 0 ? steps[i - 1] : n > 0 ? steps[steps.length - 1] : null;
  return { step: i, t: u, prev, pass, passes, n };
}
const css = (c) => "#" + (c >>> 0).toString(16).padStart(6, "0");

// ------------------------------------------------------------------ the program's shows
function walkBlocks(list, fn) {
  (list || []).forEach((b) => {
    if (!b) return;
    fn(b);
    if (b.op === "if") { walkBlocks(b.then, fn); walkBlocks(b.else, fn); }
  });
}
// the rules that run show `name`: [{si, words}]
function runsOf(prog, name, ch) {
  const out = [];
  (prog.scripts || []).forEach((sc, si) => walkBlocks(sc.do, (b) => {
    if (b.op === "show" && b.show === "mine" && b.name === name && !out.some((r) => r.si === si)) out.push({ si, words: hatWords(sc.hat, ch) });
  }));
  return out;
}
// the Run the light show blocks with steps of their own (the Blocks tab's way before this page): [{si, b}]
function legacyBlocks(prog) {
  const out = [];
  (prog.scripts || []).forEach((sc, si) => walkBlocks(sc.do, (b) => { if (b.op === "show" && b.show === "own") out.push({ si, b }); }));
  return out;
}
const secs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(ms % 1000 ? 1 : 0) + " s" : ms + " ms");
const lengthOf = (s) => (s.steps || []).reduce((a, x) => a + (Number(x.ms) || 0), 0);
// a name no other show has, of the letters a name may hold (block_modes.SHOW_NAME_RE)
const freeName = (shows, base) => {
  const taken = new Set(shows.map((s) => String(s.name || "").toLowerCase()));
  base = String(base || "").replace(/[^A-Za-z0-9 _'!-]/g, "").replace(/\s+/g, " ").trim().slice(0, 20) || "New show";
  let name = base, n = 2;
  while (taken.has(name.toLowerCase())) name = `${base} ${n++}`;
  return name.slice(0, 24);
};
const blankStep = () => ({ fx: "burst", ms: 800, a: "#ffffff", b: "#ffb000", at: "center", rate: 0, gi: "dark" });
const clone = (x) => JSON.parse(JSON.stringify(x));

// ------------------------------------------------------------------ the picture, playing the show
const fieldCache = {};
function usePlayfield(slug) {
  const [pf, setPf] = useState(fieldCache[slug] || null);
  useEffect(() => {
    let live = true;
    loadPlayfield(slug).then((r) => { fieldCache[slug] = r; if (live) setPf(r); });
    return () => { live = false; };
  }, [slug]);
  return pf;
}

function Preview({ pf, show, light, t, onPick, picking, centre }) {
  const ins = pf.inserts || [];
  const w = pf.w || Math.max(300, ...ins.map((i) => i.x + 24));
  const h = pf.h || Math.max(600, ...ins.map((i) => i.y + 40));
  const steps = (show.steps || []).map((s) => compileStep(s, light.place_xy || {}));
  const at = showAt(steps, show.repeat, t);
  const S = { seed: ((t * 7919) | 1) >>> 0 };
  const st = at.over ? null : steps[at.step];
  let gi = "keep";
  if (st) gi = st.gi === "flash" ? (i32(at.t / (st.rate || 100)) % 2 ? "dark" : "flash") : st.gi;
  const svgRef = useRef(null);
  const click = (e) => {
    if (!picking || !svgRef.current) return;
    const r = svgRef.current.getBoundingClientRect();
    onPick(Math.round((e.clientX - r.left) * w / r.width), Math.round((e.clientY - r.top) * h / r.height));
  };
  return html`<svg ref=${svgRef} class=${cx("pf-svg ls-svg", !pf.art && "pf-none", "ls-gi-" + gi, picking && "picking")}
      viewBox=${`0 0 ${w} ${h}`} style=${{ aspectRatio: `${w} / ${h}` }} role="img" aria-label="The playfield, playing the show"
      onClick=${click}>
    ${pf.art ? html`<image class="pf-art" href=${pf.art} x="0" y="0" width=${w} height=${h} />`
      : html`<rect class="pf-outline" x="3" y="3" width=${w - 6} height=${h - 6} rx="48" />`}
    ${ins.map((i, k) => {
      const c = st ? fxBlend(st, at.prev, i.x, i.y, k, at.t, S) : 0;
      return html`<circle key=${i.name + i.x} class=${cx("ls-ins", c && "lit")} cx=${i.x} cy=${i.y} r="6"
        style=${c ? { fill: css(c), color: css(c) } : null} ...${tip({ head: i.name, lines: [i.shots.length ? "Shot: " + i.shots.join(", ") : "Not a shot's light"] })} />`;
    })}
    ${centre ? html`<g class="ls-centre" transform=${`translate(${centre[0]} ${centre[1]})`}>
      <circle r="11" /><line x1="-16" x2="16" y1="0" y2="0" /><line x1="0" x2="0" y1="-16" y2="16" /></g>` : null}
  </svg>`;
}

// Play / pause, stop, the loop tick and the scrubber: the show's clock in ms, run by the frames
function usePlayer(total, loop) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  const ref = useRef({ t: 0, last: 0, raf: 0 });
  useEffect(() => {
    if (!playing || total <= 0) return undefined;
    ref.current.last = performance.now();
    const frame = (now) => {
      const st = ref.current;
      st.t += Math.min(100, now - st.last);
      st.last = now;
      if (st.t >= total) {
        if (loop) st.t = st.t % total; else { st.t = total; setT(total); setPlaying(false); return; }
      }
      setT(st.t);
      st.raf = requestAnimationFrame(frame);
    };
    ref.current.raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(ref.current.raf);
  }, [playing, total, loop]);
  const seek = (ms) => { ref.current.t = Math.max(0, Math.min(total, ms)); setT(ref.current.t); };
  const play = () => { if (ref.current.t >= total) seek(0); setPlaying(true); };
  return { t, playing, seek, play, pause: () => setPlaying(false), stop: () => { setPlaying(false); seek(0); } };
}

// ------------------------------------------------------------------ the timeline and a step's card
function Timeline({ show, sel, onSel, t, total }) {
  const steps = show.steps || [];
  const pass = lengthOf(show);
  const pos = pass ? ((t % pass) / pass) * 100 : 0;
  return html`<div class="ls-track" ...${tip(TIP.timeline)}>
    ${steps.map((st, i) => html`<button type="button" key=${i} class=${cx("ls-bar", sel === i && "sel")}
      style=${{ flexGrow: Math.max(150, Number(st.ms) || 0), background: `linear-gradient(90deg, ${st.a || "#fff"}, ${st.b || "#000"})` }}
      aria-pressed=${sel === i} onClick=${() => onSel(i)} ...${tip({ head: `${i + 1}. ${st.fx}`, lines: [secs(Number(st.ms) || 0) + (st.blend ? `, blends in over ${st.blend} ms` : "")] })}>
      <span class="ls-bar-n">${i + 1}</span><span class="ls-bar-t">${secs(Number(st.ms) || 0)}</span>
      ${st.blend ? html`<span class="ls-bar-blend" style=${{ width: `${Math.min(100, (st.blend / (Number(st.ms) || 1)) * 100)}%` }}></span>` : null}
    </button>`)}
    ${pass ? html`<div class="ls-head" style=${{ left: `${pos}%` }}></div>` : null}
  </div>`;
}

function NumBox({ value, onChange, width = 64, title, min, max }) {
  return html`<${Field} sm mono width=${width} value=${value == null ? "" : String(value)} title=${title}
    onChange=${(v) => { const n = Number(String(v).replace(/,/g, "")); if (String(v).trim() !== "" && Number.isInteger(n)) onChange(min != null ? Math.max(min, Math.min(max, n)) : n); }} />`;
}

function ColorBox({ value, onChange, title }) {
  return html`<span class="ls-color">
    <input type="color" class="bk-color" value=${value || "#ffffff"} onInput=${(e) => onChange(e.target.value)} ...${tip(title)} />
    <span class="ls-swatches">${SWATCHES.map((c) => html`<button type="button" key=${c} class=${cx("ls-swatch", value === c && "on")}
      style=${{ background: c }} aria-label=${c} ...${tip(c)} onClick=${() => onChange(c)}></button>`)}</span>
  </span>`;
}

function StepCard({ show, si, i, light, set, edit, picking, setPicking }) {
  const st = (show.steps || [])[i];
  if (!st) return null;
  const groups = light.fx_groups || [];
  const words = Object.fromEntries(light.fx || []);
  const fxOpts = groups.length ? groups.flatMap(([g, keys]) => keys.map((k) => ({ value: k, label: words[k] || k, group: g })))
    : (light.fx || []).map(([k, l]) => ({ value: k, label: l }));
  const n = show.steps.length;
  const p = ["shows", si, "steps", i];
  const setK = (k, v) => set([...p, k], v);
  const move = (dir) => edit((d) => { const l = d.shows[si].steps; const [x] = l.splice(i, 1); l.splice(i + dir, 0, x); });
  const paced = ["strobe", "spin", "rainbow", "pulse", "chase", "bolts", "ripple", "sparkle", "fire"].includes(st.fx);
  return html`<div class="ls-step">
    <div class="row ls-step-hd">
      <span class="h3">Step ${i + 1} of ${n}</span><span class="sp"></span>
      <button type="button" class="bk-x" disabled=${i === 0} aria-label=${TIP.stepUp} ...${tip(TIP.stepUp)} onClick=${() => move(-1)}>↑</button>
      <button type="button" class="bk-x" disabled=${i === n - 1} aria-label=${TIP.stepDown} ...${tip(TIP.stepDown)} onClick=${() => move(1)}>↓</button>
      <button type="button" class="bk-x" disabled=${n >= (light.limits || {}).steps} aria-label=${TIP.stepDup} ...${tip(TIP.stepDup)}
        onClick=${() => edit((d) => { d.shows[si].steps.splice(i + 1, 0, clone(st)); })}>⧉</button>
      <button type="button" class="bk-x" disabled=${n <= 1} aria-label=${TIP.stepDel} ...${tip(TIP.stepDel)}
        onClick=${() => edit((d) => { d.shows[si].steps.splice(i, 1); })}>×</button>
    </div>
    <div class="ls-grid">
      <span class="lbl" ...${tip(TIP.fx)}>Pattern</span>
      <${Select} sm value=${st.fx} options=${fxOpts} width=${190} onChange=${(v) => setK("fx", v)} />
      <span class="lbl" ...${tip(TIP.ms)}>Lasts</span>
      <span class="row ls-inl"><${NumBox} value=${st.ms} min=${50} max=${10000} title=${TIP.ms} onChange=${(v) => setK("ms", v)} /><span class="small muted">ms</span>
        <span class="small muted" ...${tip(TIP.blend)}>· blends in over</span><${NumBox} value=${st.blend || 0} min=${0} max=${10000} title=${TIP.blend} onChange=${(v) => setK("blend", v)} /><span class="small muted">ms</span></span>
      <span class="lbl" ...${tip(TIP.a)}>Color</span>
      <${ColorBox} value=${st.a} title=${TIP.a} onChange=${(v) => setK("a", v)} />
      <span class="lbl" ...${tip(TIP.b)}>Second color</span>
      <${ColorBox} value=${st.b} title=${TIP.b} onChange=${(v) => setK("b", v)} />
      <span class="lbl" ...${tip(TIP.at)}>Center</span>
      <span class="row ls-inl">
        <${Select} sm value=${st.at || "center"} options=${(light.places || []).map(([k, l]) => ({ value: k, label: l }))} width=${150}
          onChange=${(v) => edit((d) => { const s = d.shows[si].steps[i]; s.at = v; if (v === "xy" && !(s.x >= 0)) { const c = (light.place_xy || {}).center || [150, 330]; s.x = c[0]; s.y = c[1]; } })} />
        ${st.at === "xy" ? html`<span class="small mono muted">${st.x ?? "?"}, ${st.y ?? "?"}</span>
          <${Button} size="xs" kind=${picking ? "" : "ghost"} icon="fit" title=${TIP.pick} onClick=${() => setPicking(!picking)}>${picking ? "Press the picture…" : "Pick on the picture"}<//>` : null}
      </span>
      <span class="lbl" ...${tip(TIP.gi)}>GI</span>
      <${Select} sm value=${st.gi || "keep"} options=${(light.gi || []).map(([k, l]) => ({ value: k, label: l }))} width=${150} onChange=${(v) => setK("gi", v)} />
      <span class="lbl" ...${tip(TIP.rate)}>Pace</span>
      <span class="row ls-inl"><${NumBox} value=${st.rate ?? 0} min=${0} max=${2000} title=${TIP.rate} onChange=${(v) => setK("rate", v)} /><span class="small muted">ms${paced ? "" : " (not used by this pattern)"}</span></span>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ the view
export function LightShowsView({ c, pg }) {
  const ch = (c.blocks || {}).choices || {};
  const light = ch.light || {};
  const limits = light.limits || { steps: 32, shows: 24, repeat: 10 };
  const { prog, edit } = pg;
  const shows = prog.shows || [];
  const [selName, setSelName] = useState(() => (shows[0] || {}).name || "");
  let si = shows.findIndex((s) => s.name === selName);
  if (si < 0) si = shows.length ? 0 : -1;
  const show = si >= 0 ? shows[si] : null;
  const [stepSel, setStepSel] = useState(0);
  const [loop, setLoop] = useState(true);
  const [picking, setPicking] = useState(false);
  const pf = usePlayfield(c.slug);
  const pass = show ? lengthOf(show) : 0;
  const total = show ? pass * (show.repeat > 0 ? show.repeat : 1) : 0;
  const player = usePlayer(total, loop || (show && !show.repeat));
  const set = (path, v) => edit((d) => { path.slice(0, -1).reduce((o, k) => o[k], d)[path[path.length - 1]] = v; }, path.join("/"));
  const stepI = show ? Math.min(stepSel, show.steps.length - 1) : -1;
  const curStep = show && stepI >= 0 ? show.steps[stepI] : null;
  const centre = curStep ? (curStep.at === "xy" ? [curStep.x, curStep.y] : (light.place_xy || {})[curStep.at || "center"]) : null;
  const runs = show ? runsOf(prog, show.name, ch) : [];
  const allLegacy = legacyBlocks(prog);

  const addShow = (from) => edit((d) => {
    d.shows = d.shows || [];
    const name = freeName(d.shows, from ? from.label : "New show");
    d.shows.push({ name, steps: from ? clone(from.steps) : [blankStep()], repeat: 1 });
    setSelName(name);
    setStepSel(0);
    player.seek(0);
  });
  const newMenu = (e) => openMenu(e.currentTarget, [
    { label: "A blank show", onClick: () => addShow(null) },
    { sep: true }, { header: "From a ready-made show" },
    ...(light.shows || []).map((s) => ({ label: s.label, onClick: () => addShow(s) })),
  ]);
  const rename = (name) => edit((d) => {
    const old = d.shows[si].name;
    d.shows[si].name = name;
    (d.scripts || []).forEach((sc) => walkBlocks(sc.do, (b) => { if (b.op === "show" && b.show === "mine" && b.name === old) b.name = name; }));
    setSelName(name);
  }, "shows/" + si + "/name");
  const dup = () => edit((d) => {
    const name = freeName(d.shows, show.name.replace(/ \d+$/, "") + " copy");
    d.shows.splice(si + 1, 0, { ...clone(show), name });
    setSelName(name);
  });
  const del = () => edit((d) => { d.shows.splice(si, 1); setSelName((d.shows[Math.max(0, si - 1)] || {}).name || ""); });
  const runWhen = (e) => {
    const blk = () => ({ op: "show", show: "mine", name: show.name });
    const items = (prog.scripts || []).map((sc, i) => ({ label: hatWords(sc.hat, ch), disabled: runs.some((r) => r.si === i),
      onClick: () => edit((d) => { d.scripts[i].do.push(blk()); }) }));
    const fresh = [["mode_start", "When the mode starts"], ["mode_end", "When the mode ends"], ["seconds_left", "When 10 seconds are left"],
      ["any_shot", "When any shot is made while it runs"]];
    openMenu(e.currentTarget, [
      { header: "At the end of a rule" }, ...items,
      { sep: true }, { header: "In a new rule" },
      ...fresh.map(([kind, label]) => ({ label, onClick: () => edit((d) => {
        const hat = kind === "seconds_left" ? { kind, seconds: 10 } : kind === "any_shot" ? { kind, when: "running" } : { kind };
        d.scripts = [...(d.scripts || []), { hat, do: [blk()] }];
      }) })),
    ]);
  };
  // PAD-646: a block with its own steps (the Blocks tab's way before this page) becomes one of the mode's shows
  const bringIn = (si2, b) => edit((d) => {
    const name = freeName(d.shows || [], "Show " + ((d.shows || []).length + 1));
    d.shows = [...(d.shows || []), { name, steps: clone(b.steps || []), repeat: 1 }];
    walkBlocks(d.scripts[si2].do, (x) => { if (x === b || (x.op === "show" && x.show === "own" && JSON.stringify(x.steps) === JSON.stringify(b.steps))) { x.show = "mine"; x.name = name; delete x.steps; } });
    setSelName(name);
  });
  const repeatOpts = [{ value: "1", label: "once" }, ...[2, 3, 4, 5, 6, 8, 10].filter((n) => n <= limits.repeat).map((n) => ({ value: String(n), label: `${n} times` })),
    { value: "0", label: "over and over until the mode ends" }];

  return html`<div class="ls-view">
    <div class="ls-list" ...${tip(TIP.list)}>
      <div class="row ls-list-hd"><span class="h3">The mode's shows</span><span class="sp"></span>
        <${Button} size="sm" icon="plus" disabled=${shows.length >= limits.shows} title=${TIP.newShow} onClick=${newMenu}>New<//></div>
      ${shows.length ? shows.map((s, i) => {
        const n = runsOf(prog, s.name, ch).length;
        return html`<button type="button" key=${s.name + i} class=${cx("ls-row", i === si && "on")} aria-pressed=${i === si}
          onClick=${() => { setSelName(s.name); setStepSel(0); player.seek(0); player.play(); }}>
          <span class="ls-row-strip">${(s.steps || []).map((st, k) => html`<span key=${k} style=${{ flexGrow: Math.max(150, Number(st.ms) || 0), background: `linear-gradient(90deg, ${st.a || "#fff"}, ${st.b || "#000"})` }}></span>`)}</span>
          <span class="ls-row-name ellip">${s.name || "(no name)"}</span>
          <span class="small muted">${secs(lengthOf(s))}${s.repeat === 0 ? " · loops" : s.repeat > 1 ? ` · ×${s.repeat}` : ""} · ${n ? `${n} rule${n > 1 ? "s" : ""}` : "not run yet"}</span>
        </button>`;
      }) : html`<div class="small muted ls-none">No show of the mode's own yet. Press New: a blank one, or one of the ready-made shows to start from. A Run the light show block then runs it by name.</div>`}
      ${allLegacy.length ? html`<div class="ls-legacy"><${Note} kind="info">${allLegacy.length === 1 ? "A rule runs a light show of its own steps" : `${allLegacy.length} rules run light shows of their own steps`}, made under Blocks.</${Note}>
        ${allLegacy.map(({ si: s2, b }, k) => html`<div class="row small" key=${k}><span class="grow ellip">${hatWords((prog.scripts[s2] || {}).hat, ch)}: ${(b.steps || []).length} steps</span>
          <${Button} size="xs" kind="ghost" title=${TIP.legacy} onClick=${() => bringIn(s2, b)}>Bring it in<//></div>`)}</div>` : null}
    </div>
    <div class="ls-field">
      ${pf ? html`<${Preview} pf=${pf} show=${show || { steps: [], repeat: 1 }} light=${light} t=${player.t} picking=${picking} centre=${centre}
          onPick=${(x, y) => { edit((d) => { const s = d.shows[si].steps[stepI]; s.at = "xy"; s.x = x; s.y = y; }); setPicking(false); }} />`
        : html`<div class="small muted">Reading the playfield…</div>`}
      ${pf && !pf.art ? html`<div class="small muted pf-why">${pf.why || TIP.noArt}</div>` : null}
      <div class="row ls-transport">
        <${Button} size="sm" icon=${player.playing ? "pause" : "play"} disabled=${!total} title=${TIP.play}
          onClick=${() => (player.playing ? player.pause() : player.play())}>${player.playing ? "Pause" : "Play"}<//>
        <${Button} size="sm" kind="ghost" icon="stop" disabled=${!total} title=${TIP.stop} onClick=${player.stop}>Stop<//>
        <label class="chk" ...${tip(TIP.loop)}><input type="checkbox" checked=${loop} onChange=${(e) => setLoop(e.target.checked)} /><span>Loop</span></label>
        <span class="small mono muted ls-clock">${secs(Math.round(player.t))} / ${secs(total)}</span>
      </div>
      <input type="range" class="ls-scrub" min="0" max=${total || 1} value=${Math.round(player.t)} disabled=${!total} ...${tip(TIP.scrub)}
        onInput=${(e) => { player.pause(); player.seek(Number(e.target.value)); }} />
    </div>
    <div class="ls-side">
      ${show ? html`
        <div class="row ls-name">
          <span class="row ls-inl"><span class="lbl" ...${tip(TIP.name)}>Name</span><${Field} sm width=${190} value=${show.name} maxLength=${24} title=${TIP.name} onChange=${rename} /></span>
          <span class="row ls-inl"><span class="lbl" ...${tip(TIP.repeat)}>Runs</span><${Select} sm value=${String(show.repeat ?? 1)} options=${repeatOpts} width=${230} title=${TIP.repeat}
            onChange=${(v) => set(["shows", si, "repeat"], Number(v))} /></span>
          <span class="sp"></span>
          <${Button} size="sm" kind="ghost" icon="copy" disabled=${shows.length >= limits.shows} title=${TIP.dup} onClick=${dup}>Duplicate<//>
          <${Button} size="sm" kind="ghost" icon="trash" title=${TIP.del} onClick=${del}>Delete<//>
        </div>
        <div class="row ls-tl-hd"><span class="h3">Steps</span><span class="small muted">${secs(pass)} a pass</span><span class="sp"></span>
          <${Button} size="xs" kind="ghost" icon="plus" disabled=${show.steps.length >= limits.steps} title=${TIP.addStep}
            onClick=${() => edit((d) => { const l = d.shows[si].steps; l.push(l.length ? clone(l[l.length - 1]) : blankStep()); setStepSel(l.length - 1); })}>Add a step<//></div>
        <${Timeline} show=${show} sel=${stepI} t=${player.t} total=${total}
          onSel=${(i) => { setStepSel(i); const before = show.steps.slice(0, i).reduce((a, x) => a + (Number(x.ms) || 0), 0); player.seek(before); }} />
        <${StepCard} show=${show} si=${si} i=${stepI} light=${light} set=${set} edit=${edit} picking=${picking} setPicking=${setPicking} />
        <div class="ls-runs">
          <div class="row"><span class="h3" ...${tip(TIP.runs)}>Runs</span><span class="sp"></span>
            <${Button} size="xs" kind="ghost" icon="plus" title=${TIP.runWhen} onClick=${runWhen}>Run it when…<//></div>
          ${runs.length ? html`<ul class="ls-runlist">${runs.map((r) => html`<li key=${r.si}>${r.words}</li>`)}</ul>`
            : html`<div class="small muted">No rule runs this show yet: press Run it when… to put it in one.</div>`}
        </div>`
        : html`<div class="small muted">Pick a show, or press New.</div>`}
    </div>
  </div>`;
}
