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
// Scenes preview's "As on the machine" draws through it; nothing is written.

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

function tables(p) {
  const out = [];
  for (let c = 0; c < 3; c++) {
    const g = p.gamma[c], k = p.gain[c], lo = p.lift;
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

function correct(src, dst, p) {
  const [tr, tg, tb] = tables(p);
  const m = matrix(p.saturation);
  const mix = p.saturation !== 1;
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
    o[i] = tr[r]; o[i + 1] = tg[g]; o[i + 2] = tb[b]; o[i + 3] = a[i + 3];
  }
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
  const same = sat === 1 && lift === 0
    && [0, 1, 2].every((i) => Number(p.gamma[i]) === 1 && Number(p.gain[i]) === 1);
  if (same) return "No change: the card gets your picture exactly as it is.";
  return "The right side is meant to look off here: it is corrected for the machine's screen, which shifts it back to what you made.";
}

// PAD-324: the right side is the screen's version of the left, not a fix.
function screenWords(p) {
  const sat = Number(p.saturation), lift = Number(p.lift || 0);
  if (sat === 0) return "The right side is how this screen shows the left: in black and white.";
  const same = sat === 1 && lift === 0
    && [0, 1, 2].every((i) => Number(p.gamma[i]) === 1 && Number(p.gain[i]) === 1);
  if (same) return "No change: this screen shows colors exactly as your PC does.";
  return "The right side is how this screen shows the left.";
}

// -------------------------------------------------------------- the curves
function Curves({ p, screen }) {
  const t = tables(p);
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
function Slider({ label, value, min, max, step, show, onInput, hint, cls, left, right }) {
  return html`<div class=${cx("cp-slider", cls)}>
    <div class="cp-sl-hd">
      <span class="cp-sl-name" ...${tip(hint)}>${label}</span>
      <span class="cp-sl-val mono">${show(value)}</span>
    </div>
    <input type="range" min=${min} max=${max} step=${step} value=${value} aria-label=${label}
      onInput=${(e) => onInput(Number(e.target.value))} />
    ${left || right ? html`<div class="cp-sl-ends small muted"><span>${left}</span><span>${right}</span></div>` : null}
  </div>`;
}

const darker = (g) => (Math.abs(g - 1) < 0.005 ? "unchanged"
  : g > 1 ? `${Math.round((g - 1) * 100)}% darker` : `${Math.round((1 - g) * 100)}% brighter`);
const pct = (v) => `${Math.round(v * 100)}%`;

function Controls({ s, p, update }) {
  const screen = s.per_file && s.mode === "screen";
  const lim = s.limits || {};
  const [glo, ghi] = lim.gamma || [0.5, 2.5];
  const [klo, khi] = lim.gain || [0.5, 1.5];
  const [llo, lhi] = lim.lift || [0, 0.3];
  const [slo, shi] = lim.saturation || [0, 2];
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
      ${CH.map((c) => html`<${Slider} cls=${c.cls} label=${c.name} value=${p.gamma[c.key]} min=${glo} max=${ghi} step="0.01"
          show=${darker} onInput=${(v) => setCh("gamma", c.key, v)} left="brighter" right="darker"
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

const MODES = [
  { value: "display", label: "Adjust whole screen overlay", title: "One correction drawn over everything the game shows: its own art, videos, mode screens, text and your replacements. No file is changed." },
  { value: "assets", label: "Adjust individual files", title: "A correction baked into the replaced pictures and videos you switch on (and pictures added in Scenes). The game's own art is left as Stern made it." },
  { value: "screen", label: "Machine screen (preview only)", title: "Not a correction: how the machine's screen changes what it is given. Only the Scenes preview uses it, when As on the machine is ticked. Nothing is written to the card." },
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
    ${screen ? html`<p>This profile is that screen. With As on the machine ticked, Scenes draws everything through it, after the whole screen overlay: the game's own art, your replaced files and the pictures you add. It is not a correction, and nothing is written to the card.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />Until you set one, it is the individual files profile, undone: what Scenes has shown so far. Same as individual files puts that back.</li>
      <li><${Icon} name="check" />Scenes looks bluer than your PC, but not blue enough for your machine? Turn the middle shades brighter here, most of all blue.</li>
      <li><${Icon} name="check" />Saved with this project, so each machine has its own. Save a copy and Load move it between projects.</li>
      <li><${Icon} name="check" />Revert all and the Write tab leave it alone: it describes your machine, not a change to the card.</li>
    </ul>`
    : assets ? html`<p>This profile corrects the files you choose, and only those. When you build, PAD shifts the colors of each switched-on picture or video the opposite way as it is staged, so the machine's screen shifts them back to what you made. The game's own art is left as Stern made it for this screen.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />Your own files are never changed. The correction is made fresh from them every time you build, so it can never be applied twice.</li>
      <li><${Icon} name="check" />The whole screen overlay still applies on top, if you set one: the game draws these files through it like everything else.</li>
      <li><${Icon} name="check" />The Scenes preview shows a switched-on picture the way it will be written, so you can judge it in place.</li>
      <li><${Icon} name="check" />Different machines need different profiles. Save a copy for each one and load the one you're building for.</li>
    </ul>`
    : s.on_display ? html`<p>A color profile corrects for that. When you build, PAD teaches the game to shift every color it draws the opposite way, so the machine's screen shifts them back to what you made. It covers everything on the screen: the game's own art, videos, mode screens, text, and your replacements.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />No picture or video file is changed, yours or the game's. The correction lives in the game program itself, so it can never be applied twice.</li>
      <li><${Icon} name="check" />Pick No change and build again for the game's own colors.</li>
      <li><${Icon} name="check" />Different machines need different profiles. Save a copy for each one and load the one you're building for.</li>
      <li><${Icon} name="check" />See it in the emulator to check it in the game. The colors are set when the game starts, so each change restarts it.</li>
      <li><${Icon} name="check" />Only your own new pictures and videos need it? Adjust individual files above: that profile is baked into the files you pick, and the game's own art is left alone.</li>
    </ul>` : html`<p>A color profile corrects for that. When you build, PAD shifts the colors of your replacement pictures and videos the opposite way, so the machine's screen shifts them back to what you made.</p>
    <ul class="cp-facts">
      <li><${Icon} name="check" />Your own files are never changed. The correction is made fresh from them every time you build, so it can never be applied twice.</li>
      <li><${Icon} name="check" />The game's own art is left alone on this machine: PAD can only correct what you replace.</li>
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
      ? (s.screen_stored ? html`<${Note} kind="ok">${"Scenes draws every picture through “" + (s.name || "My screen") + "” when As on the machine is ticked. Nothing is written to the card."}<//>`
        : html`<${Note} kind="info">${"Scenes uses the individual files profile, undone (“" + (s.name || "") + "”). Move a slider or pick a starting point to set this machine's own screen."}<//>`)
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
        <${Explainer} s=${s} />
      </div>
      <div class="cp-side">
        ${assets ? html`<${WhichFiles} s=${s} />` : null}
        <${Controls} s=${s} p=${p} update=${update} />
      </div>
    </div>
  </div>`;
}
