// The Color profile tab (PAD-305): the colour correction a build applies to
// the user's replacement pictures and videos, so the machine's screen shows
// them the way the PC does.  Python: webui/tabs/color.py; the maths and the
// file: core/colour_profile.py.
//
// The preview is drawn here, with the SAME maths as the build (a saturation
// mix toward Rec.601 grey, then per channel lift + (1 - lift) * (in * gain)
// ^ gamma), so a slider moves the picture while it is dragged.  Python is
// told the numbers a moment after the last move and saves them to the file.
//
// PAD-312: on Spike 2 the tab has two modes.  "Whole screen" is the profile
// the game draws everything through; "Chosen files" is a second profile
// baked into the replaced pictures and videos (and pictures added in
// Scenes) that are switched on: the two boxes here for every file of a
// kind, and each file's own box on the Images and Video tabs and in the
// Scenes layers.  The same sliders and preview serve whichever is showing.
//
// PAD-324: a third mode, "Machine screen", is not a correction but the
// screen itself: what the machine does to what it is given.  Only the
// preview (Scenes, the Video tab's players) draws through it; nothing is written.
//
// PAD-339: being preview only, the machine screen also has colour ranges
// (hue, saturation and brightness of one band of hues, greys protected) and
// curves (master, then red, green, blue, through points placed by hand),
// applied after the other steps.  The maths mirrors core/colour_profile.py
// (apply_ranges, curve_table); its comment there spells out every step.
// PAD-343: every mode has them now; the files bake them and the Spike 2
// overlay's shaders draw them (plugins/stern/shader_profile.py extras_glsl).

import { html, useState, useEffect, useRef, useCallback, PageHead, Card, Button, Field, Select, Seg, Note, Check,
         Icon, tip, call, cx, mediaUrl } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const INTRO = "Make your pictures and videos look on the machine the way they look on your PC.";

const LUMA = [0.299, 0.587, 0.114];
const CH = [
  { key: 0, name: "Red", cls: "r" },
  { key: 1, name: "Green", cls: "g" },
  { key: 2, name: "Blue", cls: "b" },
];

// the shader slots' ceiling (core/colour_profile.py CURVE_MAX)
const CURVE_MAX = 9.999999;

// PAD-333: brightness and contrast folded into each channel's gain and gamma,
// as core/colour_profile.py Profile.curve does.
function curve(p) {
  const b = Number(p.brightness ?? 1), c = Math.max(Number(p.contrast ?? 1), 0.01);
  if (b === 1 && c === 1) return { gamma: p.gamma, gain: p.gain };
  const k = Math.max(b, 0) * 2 * Math.pow(0.5, 1 / c);
  return { gamma: p.gamma.map((g) => Math.min(g * c, CURVE_MAX)),
           gain: p.gain.map((g) => Math.min(k * Math.pow(Math.max(g, 0), 1 / c), CURVE_MAX)) };
}

function tables(p) {
  const out = [];
  const cv = curve(p);
  for (let c = 0; c < 3; c++) {
    const g = cv.gamma[c], k = cv.gain[c], lo = p.lift;
    const t = new Uint8ClampedArray(256);
    for (let v = 0; v < 256; v++) {
      const x = Math.min(Math.max((v / 255) * k, 0), 1);
      t[v] = Math.floor((lo + (1 - lo) * Math.pow(x, g)) * 255 + 0.5);
    }
    out.push(t);
  }
  return out;
}

function matrix(s) {
  const m = [];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) m.push((1 - s) * LUMA[j] + (i === j ? s : 0));
  return m;
}

export function correct(src, dst, p) {
  const [tr, tg, tb] = tables(p);
  const m = matrix(p.saturation);
  const mix = p.saturation !== 1;
  const live = (p.ranges || []).filter((r) => !rangeNeutral(r));
  const ct = curveTables(p);
  const a = src.data, o = dst.data;
  for (let i = 0; i < a.length; i += 4) {
    let r = a[i], g = a[i + 1], b = a[i + 2];
    if (mix) {
      const r2 = m[0] * r + m[1] * g + m[2] * b;
      const g2 = m[3] * r + m[4] * g + m[5] * b;
      const b2 = m[6] * r + m[7] * g + m[8] * b;
      r = Math.min(255, Math.max(0, Math.round(r2)));
      g = Math.min(255, Math.max(0, Math.round(g2)));
      b = Math.min(255, Math.max(0, Math.round(b2)));
    }
    r = tr[r]; g = tg[g]; b = tb[b];
    if (live.length) {
      const px = rangePixel(r, g, b, live);
      r = Math.min(255, Math.max(0, Math.floor(px[0] + 0.5)));
      g = Math.min(255, Math.max(0, Math.floor(px[1] + 0.5)));
      b = Math.min(255, Math.max(0, Math.floor(px[2] + 0.5)));
    }
    if (ct) { r = ct[0][r]; g = ct[1][g]; b = ct[2][b]; }
    o[i] = r; o[i + 1] = g; o[i + 2] = b; o[i + 3] = a[i + 3];
  }
}

// ------------------------------------------- PAD-339: colour ranges, curves
const IDENT = [[0, 0], [255, 255]];
const RF = ["hue", "width", "soft", "shift", "saturation", "brightness", "protect"];
const mod = (a, n) => ((a % n) + n) % n;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const smooth = (t) => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
const rangeNeutral = (r) => r[3] === 0 && r[4] === 1 && r[5] === 1;
const sameCurve = (pts) => pts.length === 2 && pts[0][0] === 0 && pts[0][1] === 0 && pts[1][0] === 255 && pts[1][1] === 255;

function hasExtras(p) {
  return (p.ranges || []).some((r) => !rangeNeutral(r))
    || Object.values(p.curves || {}).some((pts) => !sameCurve(pts));
}

// core/colour_profile.py curve_table: Fritsch-Carlson monotone cubic
export function curveTable(points) {
  const xs = points.map((q) => Number(q[0])), ys = points.map((q) => Number(q[1]));
  const n = xs.length, out = new Uint8Array(256);
  if (n < 2) { for (let v = 0; v < 256; v++) out[v] = v; return out; }
  const d = [];
  for (let k = 0; k < n - 1; k++) d.push((ys[k + 1] - ys[k]) / (xs[k + 1] - xs[k]));
  const m = new Array(n).fill(0);
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let k = 1; k < n - 1; k++) m[k] = d[k - 1] * d[k] > 0 ? (d[k - 1] + d[k]) / 2 : 0;
  for (let k = 0; k < n - 1; k++) {
    if (d[k] === 0) { m[k] = 0; m[k + 1] = 0; continue; }
    const a = m[k] / d[k], b = m[k + 1] / d[k], r = a * a + b * b;
    if (r > 9) { const t = 3 / Math.sqrt(r); m[k] = t * a * d[k]; m[k + 1] = t * b * d[k]; }
  }
  let k = 0;
  for (let v = 0; v < 256; v++) {
    let y;
    if (v <= xs[0]) y = ys[0];
    else if (v >= xs[n - 1]) y = ys[n - 1];
    else {
      while (xs[k + 1] < v) k++;
      const h = xs[k + 1] - xs[k], t = (v - xs[k]) / h, t2 = t * t, t3 = t2 * t;
      y = (2 * t3 - 3 * t2 + 1) * ys[k] + (t3 - 2 * t2 + t) * h * m[k]
        + (-2 * t3 + 3 * t2) * ys[k + 1] + (t3 - t2) * h * m[k + 1];
    }
    out[v] = Math.floor(clamp(y + 0.5, 0, 255));
  }
  return out;
}

// the master curve, then each channel's own: [r, g, b] tables, or null
function curveTables(p) {
  const cv = p.curves || {};
  const live = (ch) => cv[ch] && !sameCurve(cv[ch]);
  if (!["rgb", "r", "g", "b"].some(live)) return null;
  const master = live("rgb") ? curveTable(cv.rgb) : null;
  return ["r", "g", "b"].map((ch) => {
    const own = live(ch) ? curveTable(cv[ch]) : null;
    const t = new Uint8Array(256);
    for (let v = 0; v < 256; v++) { const x = master ? master[v] : v; t[v] = own ? own[x] : x; }
    return t;
  });
}

// how much of a range reaches the hue *h* (degrees), greys aside
function hueWeight(range, h) {
  const [hue, width, soft] = range;
  const dist = Math.abs(mod(h - hue + 180, 360) - 180), half = width / 2;
  if (width >= 360) return 1;
  if (soft > 0) return smooth(1 - (dist - half) / soft);
  return dist <= half ? 1 : 0;
}

// core/colour_profile.py apply_ranges, one pixel (floats 0..255)
function rangePixel(r, g, b, ranges) {
  for (const rg of ranges) {
    const [, , , shift, sat, bright, protect] = rg;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), c = mx - mn;
    if (c <= 0) continue;
    const h = (mx === r ? mod((g - b) / c, 6) : mx === g ? (b - r) / c + 2 : (r - g) / c + 4) * 60;
    const gw = protect > 0 ? smooth(c / 255 / protect) : 1;
    const w = hueWeight(rg, h) * gw;
    if (w <= 0) continue;
    const h2 = mod(h + shift * w, 360), s2 = clamp((c / mx) * (1 + (sat - 1) * w), 0, 1);
    const v2 = clamp(mx * (1 + (bright - 1) * w), 0, 255);
    const f = (n) => { const k = mod(n + h2 / 60, 6); return v2 - v2 * s2 * clamp(Math.min(k, 4 - k), 0, 1); };
    r = f(5); g = f(3); b = f(1);
  }
  return [r, g, b];
}

// ------------------------------------------------------------- the preview
function Preview({ s, p, screen }) {
  const beforeRef = useRef(null);
  const afterRef = useRef(null);
  const wrapRef = useRef(null);
  const srcData = useRef(null);
  const frame = useRef(0);
  const [split, setSplit] = useState(50);
  const [failed, setFailed] = useState(false);
  const url = s.sample_url || (s.sample_path ? mediaUrl(s.sample_path) : "");

  const draw = useCallback(() => {
    const data = srcData.current, cv = afterRef.current;
    if (!data || !cv) return;
    const ctx = cv.getContext("2d");
    const out = ctx.createImageData(data.width, data.height);
    correct(data, out, p);
    ctx.putImageData(out, 0, 0);
  }, [p]);

  useEffect(() => {
    if (!url) return undefined;
    let live = true;
    const img = new Image();
    img.onload = () => {
      if (!live) return;
      const scale = Math.min(1, 1100 / img.naturalWidth, 760 / img.naturalHeight);
      const w = Math.max(1, Math.round(img.naturalWidth * scale));
      const h = Math.max(1, Math.round(img.naturalHeight * scale));
      for (const cv of [beforeRef.current, afterRef.current]) { if (cv) { cv.width = w; cv.height = h; } }
      const bctx = beforeRef.current.getContext("2d");
      bctx.clearRect(0, 0, w, h);
      bctx.drawImage(img, 0, 0, w, h);
      try {
        srcData.current = bctx.getImageData(0, 0, w, h);
        setFailed(false);
      } catch (e) {
        srcData.current = null;
        setFailed(true);
      }
      draw();
    };
    img.onerror = () => { if (live) setFailed(true); };
    img.src = url;
    return () => { live = false; };
  }, [url]);

  useEffect(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame.current);
  }, [draw]);

  const drag = (e) => {
    const box = wrapRef.current && wrapRef.current.getBoundingClientRect();
    if (!box || !box.width) return;
    setSplit(Math.min(100, Math.max(0, ((e.clientX - box.left) / box.width) * 100)));
  };
  const down = (e) => { e.currentTarget.setPointerCapture(e.pointerId); drag(e); };
  const move = (e) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) drag(e); };
  const key = (e) => {
    if (e.key === "ArrowLeft") setSplit((v) => Math.max(0, v - 5));
    else if (e.key === "ArrowRight") setSplit((v) => Math.min(100, v + 5));
  };

  return html`<div class="cp-stage">
    <div class="cp-wipe" ref=${wrapRef} onPointerDown=${down} onPointerMove=${move} onKeyDown=${key}
        tabIndex="0" role="slider" aria-label="Compare your picture with the corrected one"
        aria-valuemin="0" aria-valuemax="100" aria-valuenow=${Math.round(split)}>
      <canvas class="cp-after" ref=${afterRef}></canvas>
      <canvas class="cp-before" ref=${beforeRef} style=${`clip-path: inset(0 ${100 - split}% 0 0)`}></canvas>
      <div class="cp-handle" style=${`left:${split}%`}><span class="cp-knob"><${Icon} name="left" /><${Icon} name="right" /></span></div>
      <span class="cp-tag cp-tag-l">Your picture</span>
      <span class="cp-tag cp-tag-r">${screen ? "On the machine's screen" : "Written to the card"}</span>
    </div>
    ${failed ? html`<${Note} kind="warn">That picture could not be shown here. Pick another one, or the test card.<//>` : null}
    <p class="small muted cp-why">${screen ? screenWords(p) : previewWords(p)} Drag the line to compare.</p>
  </div>`;
}

// What the right side is: a correction the machine's screen undoes, or (black
// and white) the look the machine will really show - never "warmer" for a grey.
function previewWords(p) {
  const sat = Number(p.saturation), lift = Number(p.lift || 0);
  if (sat === 0) return "The right side is how the machine will show it: in black and white.";
  const same = sat === 1 && lift === 0 && Number(p.brightness ?? 1) === 1 && Number(p.contrast ?? 1) === 1
    && [0, 1, 2].every((i) => Number(p.gamma[i]) === 1 && Number(p.gain[i]) === 1);
  if (same) return "No change: the card gets your picture exactly as it is.";
  return "The right side is meant to look off here: it is corrected for the machine's screen, which shifts it back to what you made.";
}

// PAD-324: the right side is the screen's version of the left, not a fix.
function screenWords(p) {
  const sat = Number(p.saturation), lift = Number(p.lift || 0);
  if (sat === 0) return "The right side is how this screen shows the left: in black and white.";
  const same = sat === 1 && lift === 0 && Number(p.brightness ?? 1) === 1 && Number(p.contrast ?? 1) === 1
    && [0, 1, 2].every((i) => Number(p.gamma[i]) === 1 && Number(p.gain[i]) === 1) && !hasExtras(p);
  if (same) return "No change: this screen shows colors exactly as your PC does.";
  return "The right side is how this screen shows the left.";
}

// -------------------------------------------------------------- the curves
function Curves({ p, screen }) {
  const t = tables(p);
  const ct = screen ? curveTables(p) : null;
  if (ct) for (let c = 0; c < 3; c++) t[c] = t[c].map((v) => ct[c][v]);
  const W = 120;
  const path = (tab) => {
    let d = "";
    for (let v = 0; v < 256; v += 5) {
      const x = (v / 255) * W, y = W - (tab[v] / 255) * W;
      d += (d ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }
    return d + "L" + W + " " + (W - (tab[255] / 255) * W).toFixed(1);
  };
  return html`<figure class="cp-curves">
    <svg viewBox=${`-2 -2 ${W + 4} ${W + 4}`} role="img" aria-label="How each color's shades are remapped">
      <rect x="0" y="0" width=${W} height=${W} class="cp-grid" />
      <path d=${`M0 ${W / 2}H${W}M${W / 2} 0V${W}`} class="cp-grid-line" />
      <path d=${`M0 ${W}L${W} 0`} class="cp-diag" />
      ${CH.map((c) => html`<path d=${path(t[c.key])} class=${"cp-curve " + c.cls} />`)}
    </svg>
    <figcaption class="small muted">${screen
      ? "Each line is one color: the shade given to the screen along the bottom, what it shows up the side. Above the dashed line means the screen shows it brighter."
      : "Each line is one color: your shade along the bottom, what is written up the side. Below the dashed line means darker on the card."}</figcaption>
  </figure>`;
}

// ---------------------------------------------------------------- controls
// PAD-333: the slider's own number, typed.  It is the number a saved copy
// of the profile holds; the words beside it say what it does.  A number in
// range moves the slider as it is typed; leaving the box (or Enter) puts an
// out-of-range one at the nearest end, Escape puts back the number it had.
// PAD-338: Middle shades show the file's gamma upside down (1 / gamma), so
// on every slider a bigger number and the right end mean more.
function NumBox({ value, min, max, step, onInput, label }) {
  const places = String(step).includes(".") ? String(step).split(".")[1].length : 0;
  const fmt = (v) => Number(v).toFixed(places);
  const [draft, setDraft] = useState(null);
  const undo = useRef(false), start = useRef(value);
  const commit = (txt) => {
    const v = Number(txt);
    if (undo.current) { undo.current = false; setDraft(null); if (start.current !== value) onInput(start.current); return; }
    if (txt !== "" && Number.isFinite(v)) {
      const got = Math.min(Math.max(v, Number(min)), Number(max));
      if (got !== value) onInput(got);
    }
    setDraft(null);
  };
  return html`<span class="field sm cp-sl-num"><input type="number" min=${min} max=${max} step=${step}
    value=${draft ?? fmt(value)} aria-label=${label + " value"}
    onFocus=${(e) => { start.current = value; setDraft(fmt(value)); e.target.select(); }}
    onInput=${(e) => {
      const txt = e.target.value, v = Number(txt);
      setDraft(txt);
      if (txt !== "" && Number.isFinite(v) && v >= Number(min) && v <= Number(max)) onInput(v);
    }}
    onBlur=${(e) => commit(e.target.value)}
    onKeyDown=${(e) => {
      if (e.key === "Enter") e.target.blur();
      else if (e.key === "Escape") { undo.current = true; e.target.blur(); }
    }} /></span>`;
}

// PAD-338: `scale` puts the track on another footing than the number (pos /
// val: number to track position and back, with the track's own min, max, step).
function Slider({ label, value, min, max, step, show, onInput, hint, cls, left, right, scale }) {
  const sc = scale || { pos: (v) => v, val: (x) => x, min, max, step };
  return html`<div class=${cx("cp-slider", cls)}>
    <div class="cp-sl-hd">
      <span class="cp-sl-name" ...${tip(hint)}>${label}</span>
      <span class="cp-sl-val mono">${show(value)}</span>
      <${NumBox} value=${value} min=${min} max=${max} step=${step} onInput=${onInput} label=${label} />
    </div>
    <input type="range" min=${sc.min} max=${sc.max} step=${sc.step} value=${sc.pos(value)} aria-label=${label}
      onInput=${(e) => onInput(sc.val(Number(e.target.value)))} />
    ${left || right ? html`<div class="cp-sl-ends small muted"><span>${left}</span><span>${right}</span></div>` : null}
  </div>`;
}

const darker = (g) => (Math.abs(g - 1) < 0.005 ? "unchanged"
  : g > 1 ? `${Math.round((g - 1) * 100)}% darker` : `${Math.round((1 - g) * 100)}% brighter`);
const pct = (v) => `${Math.round(v * 100)}%`;

function Controls({ s, p, update }) {
  const screen = s.per_file && s.mode === "screen";
  const lim = s.limits || {};
  const [glo, ghi] = lim.gamma || [0.1, 5];
  const [klo, khi] = lim.gain || [0, 4];
  const [llo, lhi] = lim.lift || [0, 0.9];
  const [slo, shi] = lim.saturation || [0, 4];
  const [blo, bhi] = lim.brightness || [0, 4];
  const [clo, chi] = lim.contrast || [0.1, 4];
  // PAD-338: middle shades as 1 / gamma (bigger = brighter) on a log track,
  // so 1 sits mid-way and each end is as far from it as the file allows
  const mids = { pos: (v) => Math.log(v), val: (x) => Math.round(Math.exp(x) * 100) / 100,
                 min: Math.log(1 / ghi), max: Math.log(1 / glo), step: 0.001 };
  const inv = (g) => Math.round((1 / g) * 100) / 100;
  const setCh = (key, c, v) => { const arr = p[key].slice(); arr[c] = v; update({ [key]: arr }); };
  const presets = s.presets || [];
  const extra = html`<div class="row cp-file">
    <${Button} size="sm" icon="save" onClick=${() => call("color.save_copy")}
      title="Save this profile as a file of its own, e.g. one per machine">Save a copy...<//>
    <${Button} size="sm" icon="upload" onClick=${() => call("color.load_file")}
      title="Use a profile saved earlier">Load...<//>
  </div>`;
  const footer = html`<span class="small muted">Saved with this project as you go, like your other changes. Save a copy keeps it for another table.</span>`;
  return html`<${Card} title="Adjust" cls="cp-controls" extra=${extra} footer=${footer}>
    <div class="cp-row">
      <span class="lbl">Start from</span>
      <div class="row wrap">
        ${presets.map((pr) => html`<${Button} size="sm" title=${pr.tip} onClick=${() => call("color.preset", pr.key)}>${pr.label}<//>`)}
      </div>
    </div>
    <div class="cp-row">
      <label class="lbl" for="cp-name">Profile name</label>
      <${Field} id="cp-name" value=${p.name} onChange=${(v) => update({ name: v })} placeholder="e.g. Godzilla, my machine" />
    </div>
    <${Curves} p=${p} screen=${s.per_file && s.mode === "screen"} />

    <div class="cp-group">
      <div class="cp-group-hd"><span class="h3">Middle shades</span>
        <span class="small muted">${screen
          ? "How bright this screen shows each color's middle shades. Scenes not blue enough? Turn blue brighter."
          : "The machine shows a color's middle shades too bright? Darken them here."}</span></div>
      ${CH.map((c) => html`<${Slider} cls=${c.cls} label=${c.name} value=${inv(p.gamma[c.key])} min=${inv(ghi)} max=${inv(glo)} step="0.01"
          scale=${mids} show=${(v) => darker(1 / v)} onInput=${(v) => setCh("gamma", c.key, 1 / v)} left="darker" right="brighter"
          hint=${"How bright the middle shades of " + c.name.toLowerCase() + " come out. Black and full " + c.name.toLowerCase() + " stay where they are."} />`)}
    </div>

    <div class="cp-group">
      <div class="cp-group-hd"><span class="h3">Color level</span>
        <span class="small muted">${screen
          ? "A tint this screen puts on everything, even white."
          : "A tint everywhere, even in white? Turn that color down."}</span></div>
      ${CH.map((c) => html`<${Slider} cls=${c.cls} label=${c.name} value=${p.gain[c.key]} min=${klo} max=${khi} step="0.01"
          show=${pct} onInput=${(v) => setCh("gain", c.key, v)} left="less" right="more"
          hint=${"Turns " + c.name.toLowerCase() + " down or up in every shade, white included."} />`)}
    </div>

    <div class="cp-group">
      <div class="cp-group-hd"><span class="h3">Whole picture</span></div>
      <${Slider} label="Brightness" value=${p.brightness} min=${blo} max=${bhi} step="0.01" show=${pct}
        onInput=${(v) => update({ brightness: v })} left="darker" right="brighter"
        hint=${screen ? "How bright this screen shows everything." : "Every shade darker or brighter. Above 100% the brightest shades turn white."} />
      <${Slider} label="Contrast" value=${p.contrast} min=${clo} max=${chi} step="0.01" show=${pct}
        onInput=${(v) => update({ contrast: v })} left="flatter" right="punchier"
        hint=${screen ? "How far apart this screen pulls dark and bright shades." : "Above 100% pulls dark shades darker and bright shades brighter; below 100% brings them closer. A middle grey stays where it is."} />
      <${Check} checked=${p.saturation === 0} label="Black and white"
        title=${screen ? "A screen that shows everything in greys, the game's own art too. Untick for full color."
          : "Every replaced picture and video in greys, for a black-and-white playfield. Your other settings still apply on top. Untick for full color."}
        onChange=${(v) => update({ saturation: v ? 0 : 1 })} />
      <${Slider} label="Color strength" value=${p.saturation} min=${slo} max=${shi} step="0.01" show=${pct}
        onInput=${(v) => update({ saturation: v })} left="grey" right="vivid"
        hint="Below 100% calms colors that glow too much on the machine; above makes them stronger." />
      <${Slider} label="Lift the darkest shades" value=${p.lift} min=${llo} max=${lhi} step="0.005"
        show=${(v) => (v < 0.002 ? "off" : `black becomes ${Math.round(v * 255)} of 255`)}
        onInput=${(v) => update({ lift: v })} left="off" right="more"
        hint="Raises the darkest shades so detail doesn't vanish into the machine's black. Black itself turns dark grey." />
    </div>
    ${(s.problems || []).length ? html`<${Note} kind="warn">Some lines of the profile file were skipped: ${(s.problems || []).join("; ")}<//>` : null}
  <//>`;
}

// ---------------------------------------------- PAD-339: the colour ranges
const RANGE_STARTS = [
  { hue: 0, label: "Reds" }, { hue: 60, label: "Yellows" }, { hue: 120, label: "Greens" },
  { hue: 180, label: "Cyans" }, { hue: 240, label: "Blues" }, { hue: 300, label: "Magentas" },
];
const hueLabel = (h) => {
  const near = RANGE_STARTS.reduce((a, b) => (Math.abs(mod(h - b.hue + 180, 360) - 180)
    < Math.abs(mod(h - a.hue + 180, 360) - 180) ? b : a));
  return near.label;
};
const deg = (v) => `${Math.round(v)}°`;
const signedDeg = (v) => (Math.abs(v) < 0.5 ? "unchanged" : `${v > 0 ? "+" : ""}${Math.round(v)}°`);

// the hues a range reaches: the colour wheel, dimmed where it does not
function RangeBand({ r }) {
  const stops = [];
  for (let h = 0; h <= 360; h += 6) stops.push(`rgba(20,22,26,${(0.7 * (1 - hueWeight(r, h))).toFixed(3)}) ${(h / 3.6).toFixed(2)}%`);
  const hues = [0, 60, 120, 180, 240, 300, 360].map((h) => `hsl(${h} 90% 50%) ${(h / 3.6).toFixed(2)}%`);
  return html`<div class="cp-band" aria-hidden="true"
    style=${`background: linear-gradient(to right, ${stops.join(", ")}), linear-gradient(to right, ${hues.join(", ")})`}></div>`;
}

function Ranges({ s, p, update }) {
  const lim = s.range_limits || {};
  const nw = s.range_new || { width: 60, soft: 30, shift: 0, saturation: 1, brightness: 1, protect: 0.15 };
  const ranges = p.ranges || [];
  const full = ranges.length >= (s.max_ranges || 6);
  const setR = (i, field, v) => {
    const next = ranges.map((r) => r.slice());
    next[i][RF.indexOf(field)] = v;
    update({ ranges: next });
  };
  const add = (hue) => update({ ranges: [...ranges.map((r) => r.slice()),
    [hue, nw.width, nw.soft, nw.shift, nw.saturation, nw.brightness, nw.protect]] });
  const neutral = (i) => update({ ranges: ranges.map((r, j) => (j === i ? [r[0], r[1], r[2], 0, 1, 1, r[6]] : r.slice())) });
  const drop = (i) => update({ ranges: ranges.filter((_r, j) => j !== i).map((r) => r.slice()) });
  const L = (k, d) => lim[k] || d;
  const extra = html`<${Button} size="sm" icon="undo" disabled=${!ranges.length} onClick=${() => update({ ranges: [] })}
    title="Remove every color range">Reset all<//>`;
  return html`<${Card} title="Color ranges" cls="cp-ranges" extra=${extra}>
    <p class="small muted cp-note">Change one band of colors and leave the rest alone, e.g. a sea that comes out too teal. Greys and near-greys are protected, so portraits and metal keep their grey. Applied after the sliders under Adjust.</p>
    <div class="row wrap cp-range-add">
      <span class="small muted">Add a range:</span>
      ${RANGE_STARTS.map((st) => html`<${Button} size="sm" icon="plus" disabled=${full} onClick=${() => add(st.hue)}
        title=${`A range around ${st.label.toLowerCase()} (${st.hue}°). Move Hue to center it on the color you want.`}>${st.label}<//>`)}
    </div>
    ${ranges.map((r, i) => html`<div class="cp-group cp-range" key=${i}>
      <div class="row cp-range-hd">
        <span class="h3">${`Range ${i + 1}: ${hueLabel(r[0])}`}</span>
        <span class="sp"></span>
        <${Button} size="sm" icon="undo" disabled=${rangeNeutral(r)} onClick=${() => neutral(i)}
          title="Hue shift, saturation and brightness back to unchanged; the range keeps its place">Reset<//>
        <${Button} size="sm" icon="trash" onClick=${() => drop(i)} title="Remove this range">Remove<//>
      </div>
      <${RangeBand} r=${r} />
      <${Slider} label="Hue" value=${r[0]} min=${L("hue", [0, 360])[0]} max=${L("hue", [0, 360])[1]} step="1" show=${deg}
        onInput=${(v) => setR(i, "hue", v)} hint="The center of the range on the color wheel: 0 red, 60 yellow, 120 green, 180 cyan, 240 blue, 300 magenta." />
      <${Slider} label="Width" value=${r[1]} min=${L("width", [0, 360])[0]} max=${L("width", [0, 360])[1]} step="1" show=${deg}
        onInput=${(v) => setR(i, "width", v)} hint="How many degrees of hue are fully in the range." />
      <${Slider} label="Soft edge" value=${r[2]} min=${L("soft", [0, 180])[0]} max=${L("soft", [0, 180])[1]} step="1" show=${deg}
        onInput=${(v) => setR(i, "soft", v)} hint="How gently the range fades out on each side, so there is no hard edge between colors." />
      <${Slider} label="Hue shift" value=${r[3]} min=${L("shift", [-180, 180])[0]} max=${L("shift", [-180, 180])[1]} step="1" show=${signedDeg}
        onInput=${(v) => setR(i, "shift", v)} left="−180°" right="+180°"
        hint="Turns the colors in the range around the color wheel. A teal sea moves toward blue with a positive shift." />
      <${Slider} label="Saturation" value=${r[4]} min=${L("saturation", [0, 4])[0]} max=${L("saturation", [0, 4])[1]} step="0.01" show=${pct}
        onInput=${(v) => setR(i, "saturation", v)} left="grey" right="vivid" hint="How strong the colors in the range are." />
      <${Slider} label="Brightness" value=${r[5]} min=${L("brightness", [0, 4])[0]} max=${L("brightness", [0, 4])[1]} step="0.01" show=${pct}
        onInput=${(v) => setR(i, "brightness", v)} left="darker" right="brighter" hint="How bright the colors in the range are." />
      <${Slider} label="Protect greys" value=${r[6]} min=${L("protect", [0, 1])[0]} max=${L("protect", [0, 1])[1]} step="0.01" show=${pct}
        onInput=${(v) => setR(i, "protect", v)} left="off" right="more"
        hint="How much color a pixel needs before the range touches it fully. Greys and pixels with less color than this are left alone or only partly changed." />
    </div>`)}
    ${!ranges.length ? html`<p class="small muted cp-note">No range yet: everything is as the sliders under Adjust leave it.</p>` : null}
  <//>`;
}

// ---------------------------------------------------- PAD-339: the curves
const CURVE_CH = [
  { value: "rgb", label: "RGB" }, { value: "r", label: "Red" }, { value: "g", label: "Green" }, { value: "b", label: "Blue" },
];
const CURVE_CLS = { rgb: "w", r: "r", g: "g", b: "b" };

function CurveEditor({ s, p, update }) {
  const [ch, setCh] = useState("rgb");
  const svgRef = useRef(null);
  const drag = useRef(-1);
  const curves = p.curves || {};
  const pts = (curves[ch] || IDENT).map((q) => q.slice());
  const maxPts = s.max_points || 16;
  const name = CURVE_CH.find((c) => c.value === ch).label;
  const put = (next) => {
    const c = {};
    for (const k of Object.keys(curves)) c[k] = curves[k].map((q) => q.slice());
    next = next.slice().sort((a, b) => a[0] - b[0]);
    if (sameCurve(next)) delete c[ch]; else c[ch] = next;
    update({ curves: c });
  };
  const setPt = (i, x, y) => {
    const lo = i > 0 ? pts[i - 1][0] + 1 : 0, hi = i < pts.length - 1 ? pts[i + 1][0] - 1 : 255;
    const next = pts.map((q) => q.slice());
    next[i] = [Math.round(clamp(x, lo, hi)), Math.round(clamp(y, 0, 255))];
    put(next);
  };
  const at = (e) => {
    // the viewBox is -4 -4 263 263: a 4-unit margin keeps the end points' circles whole
    const box = svgRef.current.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * 263 - 4;
    const y = ((e.clientY - box.top) / box.height) * 263 - 4;
    return [clamp(x, 0, 255), clamp(255 - y, 0, 255)];
  };
  const down = (e) => {
    const [x, y] = at(e);
    let i = pts.findIndex((q) => Math.abs(q[0] - x) < 8 && Math.abs(q[1] - y) < 8);
    if (i < 0) {
      if (pts.length >= maxPts || pts.some((q) => Math.round(q[0]) === Math.round(x))) return;
      const next = [...pts, [Math.round(x), Math.round(y)]].sort((a, b) => a[0] - b[0]);
      i = next.findIndex((q) => q[0] === Math.round(x));
      put(next);
    }
    drag.current = i;
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e) => { if (drag.current >= 0 && e.currentTarget.hasPointerCapture(e.pointerId)) { const [x, y] = at(e); setPt(drag.current, x, y); } };
  const up = () => { drag.current = -1; };
  const removeAt = (i) => { if (pts.length > 2) put(pts.filter((_q, j) => j !== i)); };
  // on the svg, not the circle: the pointer capture a click takes retargets
  // the double-click to the svg, so a circle never sees it
  const dbl = (e) => {
    const [x, y] = at(e);
    const i = pts.findIndex((q) => Math.abs(q[0] - x) < 8 && Math.abs(q[1] - y) < 8);
    if (i >= 0) removeAt(i);
  };
  const addPoint = () => {
    if (pts.length >= maxPts) return;
    let best = 0;
    for (let i = 1; i < pts.length - 1; i++) if (pts[i + 1][0] - pts[i][0] > pts[best + 1][0] - pts[best][0]) best = i;
    const x = Math.round((pts[best][0] + pts[best + 1][0]) / 2);
    if (x <= pts[best][0] || x >= pts[best + 1][0]) return;
    put([...pts, [x, curveTable(pts)[x]]]);
  };
  const path = (tab) => {
    let d = "";
    for (let v = 0; v < 256; v += 3) d += (d ? "L" : "M") + v + " " + (255 - tab[v]);
    return d + "L255 " + (255 - tab[255]);
  };
  const others = CURVE_CH.filter((c) => c.value !== ch && curves[c.value] && !sameCurve(curves[c.value]));
  const anyCurve = Object.values(curves).some((q) => !sameCurve(q));
  const extra = html`<${Button} size="sm" icon="undo" disabled=${!anyCurve} onClick=${() => update({ curves: {} })}
    title="Every curve back to a straight line">Reset all<//>`;
  return html`<${Card} title="Curves" cls="cp-curve-ed" extra=${extra}>
    <p class="small muted cp-note">Bend the shades with points of your own: RGB moves all three colors, then Red, Green and Blue each move their own. Lower a point to darken those shades. Applied last, after the color ranges.</p>
    <div class="row cp-curve-top">
      <${Seg} value=${ch} options=${CURVE_CH} onChange=${setCh} />
      <span class="sp"></span>
      <${Button} size="sm" icon="plus" disabled=${pts.length >= maxPts} onClick=${addPoint}
        title="A new point in the widest gap, on the curve as it is">Add point<//>
      <${Button} size="sm" icon="undo" disabled=${sameCurve(pts)} onClick=${() => put(IDENT)}
        title=${`The ${name} curve back to a straight line`}>${"Reset " + name}<//>
    </div>
    <div class="cp-curve-body">
      <svg ref=${svgRef} class="cp-curve-box" viewBox="-4 -4 263 263" role="img"
          aria-label=${`${name} curve: click to add a point, drag to move it, double-click to remove it`}
          onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onDblClick=${dbl}>
        <rect x="0" y="0" width="255" height="255" class="cp-grid" />
        <path d="M64 0V255M128 0V255M191 0V255M0 64H255M0 128H255M0 191H255" class="cp-grid-line" />
        <path d="M0 255L255 0" class="cp-diag" />
        ${others.map((c) => html`<path d=${path(curveTable(curves[c.value]))} class=${"cp-curve faint " + CURVE_CLS[c.value]} />`)}
        <path d=${path(curveTable(pts))} class=${"cp-curve " + CURVE_CLS[ch]} />
        ${pts.map((q) => html`<circle cx=${q[0]} cy=${255 - q[1]} r="5" class=${"cp-pt " + CURVE_CLS[ch]} />`)}
      </svg>
      <div class="cp-pts">
        <div class="cp-pts-hd small muted"><span></span><span>Input</span><span>Output</span><span></span></div>
        ${pts.map((q, i) => html`<div class="cp-pts-row" key=${ch + i}>
          <span class="small muted">${"Point " + (i + 1)}</span>
          <${NumBox} value=${q[0]} min=${i > 0 ? pts[i - 1][0] + 1 : 0} max=${i < pts.length - 1 ? pts[i + 1][0] - 1 : 255} step="1"
            onInput=${(v) => setPt(i, v, q[1])} label=${`Point ${i + 1} input`} />
          <${NumBox} value=${q[1]} min="0" max="255" step="1" onInput=${(v) => setPt(i, q[0], v)} label=${`Point ${i + 1} output`} />
          <${Button} size="sm" icon="x" disabled=${pts.length <= 2} onClick=${() => removeAt(i)} title="Remove this point" />
        </div>`)}
      </div>
    </div>
  <//>`;
}

const MODES = [
  { value: "display", label: "Adjust whole screen overlay", title: "One correction drawn over everything the game shows: its own art, videos, mode screens, text and your replacements. No file is changed." },
  { value: "assets", label: "Adjust individual files", title: "A correction baked into the replaced pictures and videos you switch on (and pictures added in Scenes). The game's own art is left as Stern made it." },
  { value: "screen", label: "Machine screen (preview only)", title: "Not a correction: how the machine's screen changes what it is given. Only the preview uses it (Scenes and the Video tab's players), when its Machine screen switch is on. Nothing is written to the card." },
];

const MODE_WORDS = {
  display: "Drawn over everything the game shows, its own art included; no file is changed.",
  assets: "Baked into the replaced files you switch on; the game's own art is left alone.",
  screen: "How the machine's screen changes what it is given. Only the Scenes preview uses it; nothing is written to the card.",
};

function countWords(n) {
  const parts = [];
  if (n.images) parts.push(`${n.images} replaced picture${n.images === 1 ? "" : "s"}`);
  if (n.videos) parts.push(`${n.videos} replaced video${n.videos === 1 ? "" : "s"}`);
  if (n.added) parts.push(`${n.added} picture${n.added === 1 ? "" : "s"} added in Scenes`);
  return parts.join(", ");
}

// PAD-312: which files the chosen-files profile reaches
function WhichFiles({ s }) {
  const n = s.asset_counts || {};
  const words = countWords(n);
  return html`<${Card} title="Which files" cls="cp-which">
    <${Check} checked=${!!s.all_images} label="Every replaced picture"
      title="Every picture picked on the Images tab gets this profile baked in when you build, unless its own box there says otherwise."
      onChange=${(v) => call("color.set_all", "images", v)} />
    <${Check} checked=${!!s.all_videos} label="Every replaced video"
      title="Every clip picked on the Video tab gets this profile baked in when you build (each is re-encoded for it), unless its own box there says otherwise."
      onChange=${(v) => call("color.set_all", "videos", v)} />
    <p class="small muted cp-which-now">${words ? `Now: ${words}.` : "No file is switched on yet."} One file at a time: its box in the Color column of the Images or Video tab, or its palette in the Scenes layers. The game's own pictures and clips have no box: Stern made them for this screen.</p>
  <//>`;
}

function Explainer({ s }) {
  const assets = s.per_file && s.mode === "assets";
  const screen = s.per_file && s.mode === "screen";
  return html`<${Card} title="What this does" cls="cp-explain">
    <p>A pinball machine's screen doesn't show colors the way your PC monitor does. On a Stern Godzilla, for example, middle greys come out too bright and too blue, and the darkest shades all sink into the same black.</p>
    ${screen ? html`<p>This profile is that screen. With the Machine screen switched on under Preview colors, Scenes and the Video tab's players draw everything through it, after the whole screen overlay: the game's own art, your replaced files and the pictures you add. It is not a correction, and nothing is written to the card.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />Until you set one, it is the Recommended screen, tuned on a real Spike 2. Same as individual files uses that profile, undone, instead.</li>
      <li><${Icon} name="check" />Scenes looks bluer than your PC, but not blue enough for your machine? Turn the middle shades brighter here, most of all blue.</li>
      <li><${Icon} name="check" />One band of colors off, like a sea that comes out teal? Color ranges below the preview changes just that band and leaves greys alone. Curves bends the shades with points of your own, all three colors together or one at a time.</li>
      <li><${Icon} name="check" />Saved with this project, so each machine has its own. Save a copy and Load move it between projects.</li>
      <li><${Icon} name="check" />Revert all and the Write tab leave it alone: it describes your machine, not a change to the card.</li>
    </ul>`
    : assets ? html`<p>This profile corrects the files you choose, and only those. When you build, PAD shifts the colors of each switched-on picture or video the opposite way as it is staged, so the machine's screen shifts them back to what you made. The game's own art is left as Stern made it for this screen.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />Your own files are never changed. The correction is made fresh from them every time you build, so it can never be applied twice.</li>
      <li><${Icon} name="check" />Recommended undoes the Machine screen, so what you made shows on the machine as it does on your PC. It follows that screen: tune the Machine screen and this changes with it. Move a slider to take it from there.</li>
      <li><${Icon} name="check" />The whole screen overlay still applies on top, if you set one: the game draws these files through it like everything else. While it is on Recommended, it already undoes the screen for these files, so Recommended here changes nothing.</li>
      <li><${Icon} name="check" />Color ranges and Curves below the preview are baked in too, after the sliders: fix one band of colors, or bend the shades point by point.</li>
      <li><${Icon} name="check" />The Scenes preview shows a switched-on picture the way it will be written, so you can judge it in place.</li>
      <li><${Icon} name="check" />Different machines need different profiles. Save a copy for each one and load the one you're building for.</li>
    </ul>`
    : s.on_display ? html`<p>A color profile corrects for that. When you build, PAD teaches the game to shift every color it draws the opposite way, so the machine's screen shifts them back to what you made. It covers everything on the screen: the game's own art, videos, mode screens, text, and your replacements.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />No picture or video file is changed, yours or the game's. The correction lives in the game program itself, so it can never be applied twice.</li>
      <li><${Icon} name="check" />Recommended undoes the Machine screen, so what you made shows on the machine as it does on your PC. It follows that screen: tune the Machine screen and this changes with it. Move a slider to take it from there.</li>
      <li><${Icon} name="check" />Pick No change and build again for the game's own colors.</li>
      <li><${Icon} name="check" />Color ranges and Curves below the preview are drawn by the game too, after the sliders. The multi-boot menu's Color correction changes the sliders only; ranges and curves stay as you built them.</li>
      <li><${Icon} name="check" />Different machines need different profiles. Save a copy for each one and load the one you're building for.</li>
      <li><${Icon} name="check" />See it in the emulator to check it in the game. The colors are set when the game starts, so each change restarts it.</li>
      <li><${Icon} name="check" />Only your own new pictures and videos need it? Adjust individual files above: that profile is baked into the files you pick, and the game's own art is left alone.</li>
    </ul>` : html`<p>A color profile corrects for that. When you build, PAD shifts the colors of your replacement pictures and videos the opposite way, so the machine's screen shifts them back to what you made.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />Your own files are never changed. The correction is made fresh from them every time you build, so it can never be applied twice.</li>
      <li><${Icon} name="check" />The game's own art is left alone on this machine: PAD can only correct what you replace.</li>
      <li><${Icon} name="check" />Color ranges and Curves below the preview are baked in too, after the sliders.</li>
      <li><${Icon} name="check" />Different machines need different profiles. Save a copy for each one and load the one you're building for.</li>
    </ul>`}
    <p class="small muted">${screen
      ? "Best way to tune it: put the test card on the machine, photograph the screen, and nudge the sliders until the right side here matches the photo."
      : "Best way to tune it: put the test card on the machine, photograph the screen, and nudge the sliders until the photo matches what you see here on the left."}</p>
  <//>`;
}

export default function ColorTab() {
  const s = useNs("color");
  const fromStore = () => ({
    name: s.name || "", gamma: (s.gamma || [1, 1, 1]).slice(), gain: (s.gain || [1, 1, 1]).slice(),
    lift: Number(s.lift || 0), saturation: s.saturation == null ? 1 : Number(s.saturation),
    brightness: s.brightness == null ? 1 : Number(s.brightness), contrast: s.contrast == null ? 1 : Number(s.contrast),
    ranges: (s.ranges || []).map((r) => r.slice()),
    curves: Object.fromEntries(Object.entries(s.curves || {}).map(([k, v]) => [k, v.map((q) => q.slice())])),
  });
  const [p, setP] = useState(fromStore);
  const pending = useRef({});
  const timer = useRef(0);
  // a preset, a Load or a re-read file bumps rev: the sliders take its numbers
  useEffect(() => { setP(fromStore()); }, [s.rev]);

  const update = (change) => {
    setP((cur) => ({ ...cur, ...change }));
    Object.assign(pending.current, change);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const send = pending.current;
      pending.current = {};
      call("color.set_params", send);
    }, 250);
  };

  const samples = [...(s.samples || []), { value: "browse", label: "Another picture..." }];
  const assets = s.per_file && s.mode === "assets";
  const screen = s.per_file && s.mode === "screen";
  const nFiles = Object.values(s.asset_counts || {}).reduce((a, b) => a + (b || 0), 0);
  const note = !s.has_project
    ? html`<${Note} kind="warn">There is no project folder yet: choose or extract one on the Extract tab, and the profile you set here is saved with it.<//>`
    : screen
      ? (s.screen_stored ? html`<${Note} kind="ok">${"The preview draws every picture through “" + (s.name || "My screen") + "” when its Machine screen switch is on. Nothing is written to the card."}<//>`
        : s.screen_follow
          ? html`<${Note} kind="info">${"Scenes uses the individual files profile, undone (“" + (s.name || "") + "”). Move a slider or pick a starting point to set this machine's own screen."}<//>`
          : html`<${Note} kind="info">${"Scenes uses the Recommended screen, tuned on a real Spike 2. Move a slider or pick a starting point to set this machine's own screen."}<//>`)
    : assets
      ? (s.active ? html`<${Note} kind="ok">${"“" + (s.name || "My profile") + "” is baked into " + countWords(s.asset_counts || {})
            + " when you build; the game's own art is not touched. Pick No change to send the files as they are."}<//>`
        : !s.asset_active ? html`<${Note} kind="info">No change on the individual files: they go onto the card as you made them. Pick a starting point or move a slider to correct them.<//>`
        : html`<${Note} kind="info">${"“" + (s.name || "My profile") + "” is ready, but no file is switched on yet: tick a box under Which files, or switch on pictures on the Images tab, videos on the Video tab, or layers in Scenes."}<//>`)
      : s.active ? html`<${Note} kind="ok">${"“" + (s.name || "My profile") + "” is staged for this project: the next build "
          + (s.on_display ? "corrects everything the game draws." : "corrects your replaced pictures and videos.")
          + " Pick No change to take it off."}<//>`
      : html`<${Note} kind="info">${s.on_display
          ? "No whole screen overlay on this project: the game draws in its own colors. Pick a starting point or move a slider to stage one."
          : "No color profile on this project: your pictures and videos go onto the card as they are. Pick a starting point or move a slider to stage one."}<//>`;
  return html`<div class="page cp-page">
    <${PageHead} title="Color profile" sub=${INTRO}>
      <${Button} kind="primary" icon="emulate" onClick=${() => call("color.try_emulator")}
        disabled=${!s.has_project}
        title="Run this project in the emulator with this profile (a running game restarts, since the colors are set when the game starts)">See it in the emulator<//>
    <//>
    ${s.per_file ? html`<div class="row cp-modes">
      <${Seg} value=${s.mode || "display"} options=${MODES} onChange=${(v) => call("color.set_mode", v)} />
      <span class="small muted">${MODE_WORDS[s.mode] || MODE_WORDS.display}</span>
    </div>
    ${screen ? html`<${Note} kind="info" cls="cp-both"><b>Preview only.</b> Scenes draws the game's own art and your files through this, after the whole screen overlay. The two corrections are not changed by it.<//>`
    : html`<${Note} kind="info" cls="cp-both"><b>Both can be on at once.</b> ${assets
      ? (s.display_active ? `The whole screen overlay “${s.display_name}” is on too: the game draws these files through it like everything else.`
        : "No whole screen overlay is set: only the files you switch on here are corrected.")
      : (nFiles ? `The individual files profile “${s.asset_name}” is on too, baked into ${countWords(s.asset_counts || {})}; the overlay is drawn over those as well.`
        : "No individual file is switched on; switch files on under Adjust individual files to correct only your own art.")}<//>`}` : null}
    ${note}
    ${s.try_note ? html`<div class="small muted">${s.try_note}</div>` : null}
    <div class="cp-grid">
      <div class="cp-main">
        <${Card} title="Preview" cls="cp-preview" extra=${html`<div class="row">
            <${Select} sm value=${s.sample || "card"} options=${samples} width=${260}
              onChange=${(v) => call("color.pick_sample", v)} title="The picture to try the profile on" />
          </div>`}>
          <${Preview} s=${s} p=${p} screen=${screen} />
        <//>
        <${Ranges} s=${s} p=${p} update=${update} />
        <${CurveEditor} s=${s} p=${p} update=${update} />
        <${Explainer} s=${s} />
      </div>
      <div class="cp-side">
        ${assets ? html`<${WhichFiles} s=${s} />` : null}
        <${Controls} s=${s} p=${p} update=${update} />
      </div>
    </div>
  </div>`;
}
