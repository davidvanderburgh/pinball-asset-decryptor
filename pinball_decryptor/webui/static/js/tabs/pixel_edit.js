// PAD-1547 (Captain Gordon): Edit pixels, the Images tab's pixel editor for small pictures,
// asked for as "a sprite editor for the Sonic Pinball micro LED ring displays".  Every rule
// (what opens, the byte budget, where a save goes) lives in webui/tabs/pixel_edit.py; this is
// the drawing surface.  A picture opens as it is now (its replacement, else the game's own),
// is painted here, and a save makes it the slot's replacement, as a picked file would be.

import { html, useEffect, useMemo, useRef, useState, Button, Seg, Modal, Note, call, mediaUrl, cx, tip }
  from "../core/ui.js";

const TOOLS = ["Pencil", "Eraser", "Fill", "Pick"];
const TOOL_KEYS = { p: "Pencil", b: "Pencil", e: "Eraser", f: "Fill", g: null, i: "Pick" };
const TOOL_TIP = "Pencil (P) paints the color, Eraser (E) makes pixels see-through, Fill (F) paints every touching pixel of the same color, Pick (I) takes a pixel's color. Right-click a pixel to pick its color with any tool.";
const RING_NOTE = "Sonic's ring displays: each ring is a grid of 14 × 14 full-color LEDs, and each frame is a 14 × 14 picture like this one with red, green, blue and see-through levels of 0-255 each, so any color can be used. A bigger picture is a sheet of 14 × 14 frames; the yellow lines mark them. The game holds every file at its original size in bytes, so a saved picture has to fit in it (the line at the bottom). Frames can be changed, not added: the game plays the frames it has.";
const LED_TIP = "How the picture looks as lit LEDs: one dot per pixel, see-through parts dark.";
const PLAY_FPS = 12;
const MAP_TIP = "Where Sonic's five ring displays sit on the playfield, marked on the game's own playfield picture (taken before the rings were fitted, so they are not in it). Which ring shows which picture is up to the game.";

// PAD-1549: where the ring displays are.  Sonic's game program, which places them, is locked
// to its own key, so the positions were measured from Jersey Jack's playfield photo
// (webui/tabs/pixel_edit.py, SONIC_RINGS) and are drawn on the project's own picture.
function RingMap({ map }) {
  const [hot, setHot] = useState(0);
  return html`<div class="pxe-map">
    <div class="eyebrow" ...${tip(MAP_TIP)}>Where the rings are</div>
    <div class="pxe-map-pf">
      <img src=${mediaUrl(map.photo)} alt="" draggable="false" />
      ${map.rings.map((r) => html`<span class=${cx("pxe-map-ring", hot === r.n && "on")}
        style=${{ left: (r.x * 100) + "%", top: (r.y * 100) + "%" }}
        onMouseEnter=${() => setHot(r.n)} onMouseLeave=${() => setHot(0)}
        ...${tip({ head: `Ring ${r.n}: ${r.name}`, lines: [r.where] })}>${r.n}</span>`)}
    </div>
    <ol class="pxe-map-list small">
      ${map.rings.map((r) => html`<li class=${cx(hot === r.n && "on")}
        onMouseEnter=${() => setHot(r.n)} onMouseLeave=${() => setHot(0)}>${r.name}</li>`)}
    </ol>
  </div>`;
}

const fromB64 = (s) => { const b = atob(s || ""); const a = new Uint8ClampedArray(b.length); for (let i = 0; i < b.length; i++) a[i] = b.charCodeAt(i); return a; };
const toB64 = (a) => { let s = ""; for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode.apply(null, a.subarray(i, i + 0x8000)); return btoa(s); };
const hex = (c) => "#" + c.slice(0, 3).map((v) => v.toString(16).padStart(2, "0")).join("");
const rgba = (c) => `rgba(${c[0]},${c[1]},${c[2]},${(c[3] / 255).toFixed(3)})`;
const num = (n) => (n == null ? "…" : n.toLocaleString("en-US"));

function drawLeds(cv, w, h, px) {
  if (!cv || !px) return;
  const pitch = Math.max(3, Math.floor(196 / Math.max(w, h)));
  cv.width = w * pitch; cv.height = h * pitch;
  const g = cv.getContext("2d");
  g.fillStyle = "#050505"; g.fillRect(0, 0, cv.width, cv.height);
  const r = pitch * 0.42;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4, a = px[i + 3] / 255;
    g.fillStyle = a ? `rgb(${Math.round(px[i] * a)},${Math.round(px[i + 1] * a)},${Math.round(px[i + 2] * a)})` : "#111";
    g.beginPath(); g.arc(x * pitch + pitch / 2, y * pitch + pitch / 2, r, 0, Math.PI * 2); g.fill();
  }
}

export function PixelEditor({ rel, onClose }) {
  const [spec, setSpec] = useState(null);
  const [ver, setVer] = useState(0);
  const [tool, setTool] = useState("Pencil");
  const [color, setColor] = useState([255, 255, 255, 255]);
  const [grid, setGrid] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [bytes, setBytes] = useState(null);
  const [msg, setMsg] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [askClose, setAskClose] = useState(false);
  const [showMap, setShowMap] = useState(true);
  const px = useRef(null);
  const hist = useRef({ undo: [], redo: [] });
  const cvRef = useRef(null);
  const ledRef = useRef(null);
  const stroke = useRef(null);
  const frameImgs = useRef([]);

  const load = async (r) => {
    const sp = await call("images.pixel_open", r);
    if (!sp) { onClose(); return; }
    px.current = fromB64(sp.data);
    hist.current = { undo: [], redo: [] };
    setSpec(sp); setDirty(false); setMsg(null); setAskClose(false); setBytes(null); setVer((v) => v + 1);
  };
  useEffect(() => { load(rel); }, [rel]);

  const w = spec ? spec.w : 0, h = spec ? spec.h : 0;
  const scale = spec ? Math.max(2, Math.floor(Math.min(480 / w, 400 / h))) : 1;

  // the canvas: a checkerboard under the pixels, then the pixel grid and the frame cells
  useEffect(() => {
    const cv = cvRef.current, p = px.current;
    if (!cv || !p || !spec) return;
    cv.width = w * scale; cv.height = h * scale;
    const g = cv.getContext("2d");
    const ck = Math.max(4, Math.floor(scale / 2));
    for (let y = 0; y < cv.height; y += ck) for (let x = 0; x < cv.width; x += ck) {
      g.fillStyle = ((x / ck + y / ck) & 1) ? "#2a2a2e" : "#3a3a40"; g.fillRect(x, y, ck, ck);
    }
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (!p[i + 3]) continue;
      g.fillStyle = rgba([p[i], p[i + 1], p[i + 2], p[i + 3]]); g.fillRect(x * scale, y * scale, scale, scale);
    }
    const line = (x0, y0, x1, y1) => { g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke(); };
    if (grid && scale >= 6) {
      g.strokeStyle = "rgba(0,0,0,0.30)"; g.lineWidth = 1;
      for (let x = 1; x < w; x++) line(x * scale + 0.5, 0, x * scale + 0.5, h * scale);
      for (let y = 1; y < h; y++) line(0, y * scale + 0.5, w * scale, y * scale + 0.5);
    }
    if (spec.cell) {
      g.strokeStyle = "rgba(255,200,40,0.75)"; g.lineWidth = 1;
      for (let x = spec.cell[0]; x < w; x += spec.cell[0]) line(x * scale + 0.5, 0, x * scale + 0.5, h * scale);
      for (let y = spec.cell[1]; y < h; y += spec.cell[1]) line(0, y * scale + 0.5, w * scale, y * scale + 0.5);
    }
    if (!playing) drawLeds(ledRef.current, w, h, p);
  }, [ver, spec, grid, scale, playing]);

  // the size it saves at, a moment after the last change
  useEffect(() => {
    if (!spec || !px.current) return undefined;
    const t = setTimeout(() => {
      call("images.pixel_bytes", w, h, toB64(px.current), spec.budget).then(setBytes);
    }, 350);
    return () => clearTimeout(t);
  }, [ver, spec]);

  // the frames of the folder, played as LEDs; the frame open here plays as it is now
  useEffect(() => {
    if (!playing || !spec) return undefined;
    const frames = spec.frames || [];
    frameImgs.current = frames.map((f, i) => {
      if (i === spec.index) return null;
      const im = new Image(); im.src = mediaUrl(f.path) + "&v=" + ver; return im;
    });
    const off = document.createElement("canvas"); off.width = w; off.height = h;
    const og = off.getContext("2d", { willReadFrequently: true });
    let i = spec.index;
    const tick = () => {
      i = (i + 1) % Math.max(1, frames.length);
      const im = frameImgs.current[i];
      if (!im) { drawLeds(ledRef.current, w, h, px.current); return; }
      if (!im.complete || !im.naturalWidth) return;
      og.clearRect(0, 0, w, h); og.drawImage(im, 0, 0);
      drawLeds(ledRef.current, w, h, og.getImageData(0, 0, w, h).data);
    };
    const t = setInterval(tick, 1000 / PLAY_FPS);
    return () => clearInterval(t);
  }, [playing, spec]);

  const palette = useMemo(() => {
    const p = px.current;
    if (!p) return [];
    const seen = new Map();
    for (let i = 0; i < p.length; i += 4) {
      if (!p[i + 3]) continue;
      const k = (p[i] << 24 >>> 0) + (p[i + 1] << 16) + (p[i + 2] << 8) + p[i + 3];
      seen.set(k, (seen.get(k) || 0) + 1);
    }
    return [...seen.entries()].sort((a, b) => b[1] - a[1]).slice(0, 48)
      .map(([k]) => [(k >>> 24) & 255, (k >>> 16) & 255, (k >>> 8) & 255, k & 255]);
  }, [ver, spec]);

  const snapshot = () => { hist.current.undo.push(px.current.slice()); if (hist.current.undo.length > 200) hist.current.undo.shift(); hist.current.redo = []; };
  const changed = () => { setDirty(true); setMsg(null); setAskClose(false); setVer((v) => v + 1); };
  const at = (x, y) => { const i = (y * w + x) * 4, p = px.current; return [p[i], p[i + 1], p[i + 2], p[i + 3]]; };
  const put = (x, y, c) => { if (x < 0 || y < 0 || x >= w || y >= h) return; const i = (y * w + x) * 4; px.current.set(c, i); };
  const ink = () => (tool === "Eraser" ? [0, 0, 0, 0] : color);
  const fill = (x0, y0, c) => {
    const from = at(x0, y0).join();
    if (from === c.join()) return;
    const st = [[x0, y0]];
    while (st.length) {
      const [x, y] = st.pop();
      if (x < 0 || y < 0 || x >= w || y >= h || at(x, y).join() !== from) continue;
      put(x, y, c); st.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
    }
  };
  const cellOf = (ev) => {
    const r = cvRef.current.getBoundingClientRect();
    return [Math.floor((ev.clientX - r.left) / r.width * w), Math.floor((ev.clientY - r.top) / r.height * h)];
  };
  const pick = (x, y) => { const c = at(x, y); if (c[3]) { setColor(c); setTool((t) => (t === "Pick" ? "Pencil" : t)); } };
  const onDown = (ev) => {
    if (!px.current || playing) return;
    ev.preventDefault();
    const [x, y] = cellOf(ev);
    if (ev.button === 2 || ev.altKey || tool === "Pick") { pick(x, y); return; }
    if (ev.button !== 0) return;
    snapshot();
    if (tool === "Fill") { fill(x, y, ink()); changed(); return; }
    put(x, y, ink()); stroke.current = [x, y]; changed();
    ev.currentTarget.setPointerCapture(ev.pointerId);
  };
  const onMove = (ev) => {
    if (!stroke.current) return;
    let [x0, y0] = stroke.current;
    const [x1, y1] = cellOf(ev);
    if (x0 === x1 && y0 === y1) return;
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (;;) {                                           // the pixels between two moves, so a quick stroke has no gaps
      put(x0, y0, ink());
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
    }
    stroke.current = [x1, y1]; changed();
  };
  const onUp = () => { stroke.current = null; };

  const undo = () => { const u = hist.current.undo.pop(); if (!u) return; hist.current.redo.push(px.current); px.current = u; changed(); };
  const redo = () => { const r = hist.current.redo.pop(); if (!r) return; hist.current.undo.push(px.current); px.current = r; changed(); };
  const toOriginal = () => { snapshot(); px.current = fromB64(spec.orig); changed(); };

  const save = async () => {
    setBusy(true);
    try {
      const r = await call("images.pixel_save", spec.rel, w, h, toB64(px.current));
      if (!r || !r.ok) { setMsg({ kind: "err", text: (r && r.msg) || "Not saved." }); return false; }
      setDirty(false);
      setSpec((s) => ({ ...s, edited: !r.same,
        frames: (s.frames || []).map((f, i) => (i === s.index ? { ...f, path: r.same ? f.path : r.path } : f)) }));
      setMsg({ kind: "ok", text: r.same ? r.msg : "Saved as this picture's replacement. Build it on the Write tab." });
      return true;
    } finally { setBusy(false); }
  };
  const go = async (step) => {
    const frames = spec.frames || [];
    const n = spec.index + step;
    if (n < 0 || n >= frames.length) return;
    if (dirty && !(await save())) return;               // moving on saves this frame first
    setPlaying(false);
    load(frames[n].rel);
  };
  const close = () => { if (dirty && !askClose) { setAskClose(true); return; } onClose(); };

  const onKey = (ev) => {
    if (ev.target && ev.target.tagName === "INPUT") return;
    const k = ev.key.toLowerCase();
    if ((ev.ctrlKey || ev.metaKey) && k === "z") { ev.preventDefault(); ev.shiftKey ? redo() : undo(); return; }
    if ((ev.ctrlKey || ev.metaKey) && k === "y") { ev.preventDefault(); redo(); return; }
    if ((ev.ctrlKey || ev.metaKey) && k === "s") { ev.preventDefault(); save(); return; }
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (k === "g") { setGrid((v) => !v); return; }
    if (TOOL_KEYS[k]) setTool(TOOL_KEYS[k]);
    else if (k === "arrowleft" || k === ",") go(-1);
    else if (k === "arrowright" || k === ".") go(1);
  };

  if (!spec) return null;
  const frames = spec.frames || [];
  const over = spec.budget != null && bytes != null && bytes > spec.budget;
  const sizeText = spec.budget != null
    ? `Saves at ${num(bytes)} bytes · this game holds the file at ${num(spec.budget)}`
    : `Saves at ${num(bytes)} bytes`;
  const footer = html`
    <span class=${cx("small pxe-size", over ? "err" : spec.budget != null && bytes != null ? "ok" : "muted")}
      ...${tip(spec.budget != null ? "Sonic-era Jersey Jack games keep every file at the byte size it shipped at. A smaller picture is padded up to it when you build; a bigger one can't go in." : "The size of the picture as it is saved.")}>
      ${sizeText}${over ? ` (${num(bytes - spec.budget)} too many)` : ""}</span>
    <span class="grow"></span>
    ${askClose ? html`<span class="small err">Not saved. Close again to drop the changes.</span>` : null}
    <${Button} onClick=${close}>${dirty ? "Close" : "Done"}<//>
    <${Button} kind="primary" icon="save" onClick=${save} disabled=${!dirty || busy || over}
      title="Save the picture as this slot's replacement (Ctrl+S). The game's own file is untouched until you build.">Save<//>`;
  return html`<${Modal} title=${"Edit pixels — " + spec.name} icon="brush" onClose=${close} xwide footer=${footer} cls="pxe-modal">
    <div class="pxe" tabindex="-1" onKeyDown=${onKey}>
      <div class="pxe-tools">
        <span ...${tip(TOOL_TIP)}><${Seg} value=${tool} options=${TOOLS} onChange=${setTool} /></span>
        <label class="row pxe-color" ...${tip("The color the Pencil and Fill paint. Opacity 100% is solid; lower lets what is under it show through.")}>
          <span class="pxe-swatch" style=${{ background: rgba(color) }}></span>
          <input type="color" value=${hex(color)} onInput=${(e) => {
            const v = e.target.value; setColor([parseInt(v.slice(1, 3), 16), parseInt(v.slice(3, 5), 16), parseInt(v.slice(5, 7), 16), color[3]]);
            if (tool === "Eraser" || tool === "Pick") setTool("Pencil"); }} />
          <span class="small muted">Opacity</span>
          <input type="range" min="1" max="255" value=${color[3]} onInput=${(e) => setColor([color[0], color[1], color[2], +e.target.value])} />
          <span class="small mono">${Math.round(color[3] / 2.55)}%</span>
        </label>
        <span class="grow"></span>
        <${Button} size="sm" kind="ghost" icon="undo" onClick=${undo} disabled=${!hist.current.undo.length} title="Undo (Ctrl+Z)" />
        <${Button} size="sm" kind="ghost" icon="redo" onClick=${redo} disabled=${!hist.current.redo.length} title="Redo (Ctrl+Y)" />
        <${Button} size="sm" kind=${grid ? "" : "ghost"} onClick=${() => setGrid(!grid)} title="Show the line between pixels (G)">Grid<//>
        ${spec.ringmap ? html`<${Button} size="sm" kind=${showMap ? "" : "ghost"} icon="map" onClick=${() => setShowMap(!showMap)}
          title="Show or hide where Sonic's ring displays sit on the playfield">Ring map<//>` : null}
        <${Button} size="sm" kind="ghost" onClick=${toOriginal} title="Put the game's own picture back in the editor (Undo takes it back). Saving it drops this slot's replacement.">Game's own<//>
      </div>
      <div class="pxe-body">
        <div class="pxe-stage">
          <canvas ref=${cvRef} class="pxe-canvas" style=${{ width: w * scale + "px", height: h * scale + "px" }}
            onPointerDown=${onDown} onPointerMove=${onMove} onPointerUp=${onUp} onPointerCancel=${onUp}
            onContextMenu=${(e) => e.preventDefault()} />
        </div>
        <div class="pxe-side">
          <div class="eyebrow">${spec.ring ? "On the ring" : "As LEDs"}</div>
          <canvas ref=${ledRef} class="pxe-led" ...${tip(LED_TIP)} />
          <div class="small muted">${w} × ${h} pixels${spec.cell ? ` · frames of ${spec.cell[0]} × ${spec.cell[1]}` : ""}${spec.edited ? " · has a replacement" : ""}</div>
          ${frames.length > 1 ? html`<div class="pxe-frames">
            <div class="row">
              <${Button} size="sm" kind="ghost" icon="prev" onClick=${() => go(-1)} disabled=${spec.index <= 0 || busy} title="The frame before (←). Saves this one first." />
              <span class="small mono pxe-fno">Frame ${spec.index + 1} of ${frames.length}</span>
              <${Button} size="sm" kind="ghost" icon="next" onClick=${() => go(1)} disabled=${spec.index >= frames.length - 1 || busy} title="The next frame (→). Saves this one first." />
              <${Button} size="sm" kind="ghost" icon=${playing ? "stop" : "play"} onClick=${() => setPlaying(!playing)}
                title=${`Play the ${frames.length} pictures of this folder in turn on the LEDs, at ${PLAY_FPS} a second (the game sets its own speed).`}>${playing ? "Stop" : "Play"}<//>
            </div>
            <div class="small muted ellip" title=${frames.map((f) => f.name).join("\n")}>${frames[0].name} … ${frames[frames.length - 1].name}</div>
          </div>` : null}
          <div class="eyebrow">Colors in this picture</div>
          <div class="pxe-pal">
            ${palette.map((c) => html`<button class=${cx("pxe-chip", c.join() === color.join() && "on")} style=${{ background: rgba(c) }}
              onClick=${() => { setColor(c); if (tool === "Eraser" || tool === "Pick") setTool("Pencil"); }}
              ...${tip(`${hex(c).toUpperCase()}${c[3] < 255 ? ` at ${Math.round(c[3] / 2.55)}%` : ""}`)}></button>`)}
          </div>
        </div>
        ${spec.ringmap && showMap ? html`<${RingMap} map=${spec.ringmap} />` : null}
      </div>
      ${spec.ring ? html`<p class="small muted pxe-note">${RING_NOTE}</p>` : null}
      ${msg ? html`<${Note} kind=${msg.kind === "err" ? "err" : "ok"}>${msg.text}<//>` : null}
    </div>
  <//>`;
}
