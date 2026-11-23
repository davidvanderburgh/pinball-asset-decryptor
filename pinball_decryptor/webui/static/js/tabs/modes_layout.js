// The JJP screen layout editor (PAD-1515). JJP games draw their screens in code, so there is no scene
// file to open; but what the mode runtime draws over the game is ours, placed by .mode / title.cfg keys.
// This lays those places out by dragging: a mode's screen (its panel, title, total, timer, picture and
// video), a wizard mode's progress board, and the attract game type menu.
//
// Python (plugins/jjp/screen_layout.py) gives each screen's elements with their boxes ([x, y, w, h], %
// of the parent: the screen, or the panel / menu they sit in) and owns what a drag writes:
// modes.jjp_place(scope, key, box) and modes.jjp_panel_word(scope, word). Every move writes at once
// through the same save as the form, so the check runs after it.

import { html, useEffect, useRef, useState, Button, Select, call, cx, mediaUrl } from "../core/ui.js";

const SNAP_PX = 6;        // screen pixels: a box edge or centre this close to a guide snaps to it
const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
const r2 = (n) => Math.round(n * 100) / 100;

// a parent-relative box -> screen percent, and back
function toScreen(b, p) { return p ? [p[0] + b[0] * p[2] / 100, p[1] + b[1] * p[3] / 100, b[2] * p[2] / 100, b[3] * p[3] / 100] : b; }
function toParent(b, p) { return p ? [(b[0] - p[0]) * 100 / p[2], (b[1] - p[1]) * 100 / p[3], b[2] * 100 / p[2], b[3] * 100 / p[3]] : b; }

let measureCtx = null;
function textWidth(text, font) {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  measureCtx.font = font;
  return measureCtx.measureText(text).width;
}

// Text as the runtime fits it into a box: as tall as the box, narrower when it would overflow, centred.
// No game font: the built-in font's look (8 px cells, each glyph as wide as it is tall). A game font:
// a stand-in face at the same fit (the browser cannot read the game's font objects; "Show it in the
// game" is the true look).
function BoxText({ text, color, font, wpx, hpx }) {
  if (!text) return null;
  let size = hpx, sx = 1;
  if (!font) {                            // the built-in font: len * h wide at h tall
    const want = Math.min(text.length * hpx, wpx);
    size = Math.min(hpx, wpx / Math.max(1, text.length));
    const w = textWidth(text, `bold ${size}px "Courier New", monospace`);
    sx = w > 0 ? Math.min(want, text.length * size) / w : 1;
  } else {
    const w = textWidth(text, `800 ${hpx}px "Arial Black", Arial, sans-serif`);
    if (w > wpx) size = hpx * wpx / w;
  }
  const fam = font ? `"Arial Black", Arial, sans-serif` : `"Courier New", monospace`;
  return html`<div class="jjpl-text" style=${{ color, fontFamily: fam, fontWeight: font ? 800 : 700, fontSize: size + "px",
      lineHeight: hpx + "px", transform: `scaleX(${sx})` }}>${text}</div>`;
}

function Media({ el, lit }) {
  const src = el.kind === "pane" && !lit ? el.unlit : el.file;
  if (!src) return html`<div class="jjpl-empty">${el.kind === "pane" ? "no unlit picture" : ""}</div>`;
  return /\.(webm|mp4|mkv|mov|ogv|avi|m4v)$/i.test(src)
    ? html`<video class="jjpl-media" src=${mediaUrl(src)} muted preload="auto" playsinline />`
    : html`<img class="jjpl-media" src=${mediaUrl(src)} draggable=${false} />`;
}

// what an element looks like inside its box (px: the box's size on the page)
function Look({ el, wpx, hpx, lit, scale }) {
  if (el.kind === "picture" || el.kind === "video" || el.kind === "pane") return html`<${Media} el=${el} lit=${lit} />`;
  if (el.kind === "panel") {
    if (el.off) return null;
    const bar = el.bar ? Math.max(1, (el.bar_h || 0.6) / 100 * 768 * scale) : 0;   // scaled as the runtime scales it
    return html`<div class="jjpl-fill" style=${{ background: el.color }}>
      ${bar ? html`<div class="jjpl-bar" style=${{ top: 0, height: bar + "px", background: el.bar }}></div>
                   <div class="jjpl-bar" style=${{ bottom: 0, height: bar + "px", background: el.bar }}></div>` : null}</div>`;
  }
  if (el.kind === "text") return el.off ? null : html`<${BoxText} text=${el.text} color=${el.color} font=${el.font} wpx=${wpx} hpx=${hpx} />`;
  if (el.kind === "lines") {
    const rows = el.rows || [], rh = hpx / Math.max(1, rows.length);
    return html`<div class="jjpl-rows">${rows.map((t, i) => html`<div class="jjpl-row" key=${i} style=${{ height: rh + "px" }}>
      ${i === el.pick ? html`<div class="jjpl-pickbar" style=${{ height: rh * 0.867 + "px", background: el.pick_bar }}></div>` : null}
      <div class="jjpl-rowtext" style=${{ height: rh * 0.867 + "px" }}>
        <${BoxText} text=${t} color=${i === el.pick ? el.pick_color : el.color} font=${el.font} wpx=${wpx * 0.96} hpx=${rh * 0.555} /></div>
    </div>`)}</div>`;
  }
  return null;                            // the shared progress box: its outline alone
}

// The editor. `lay`: {screen, scope, elements, words?}; `size`: [W, H] of the screen.
export function LayoutEditor({ lay, size, backdrops = [], title, hint, onBrowse }) {
  const [W, H] = size || [1360, 768];
  const els = (lay && lay.elements) || [];
  const scope = lay ? lay.scope : "mode";
  const wrap = useRef(null);
  const [cw, setCw] = useState(800);
  const [sel, setSel] = useState("");
  const [drag, setDrag] = useState(null);          // {key, box (screen %), guides}
  const [nudged, setNudged] = useState(null);      // {key, box} written after a pause
  const [lit, setLit] = useState(true);
  const bkKey = `pad.jjplayout.backdrop.${lay ? lay.screen : ""}`;
  const [bk, setBkState] = useState(() => { try { return localStorage.getItem(bkKey) || ""; } catch (e) { return ""; } });
  const setBk = (v) => { setBkState(v); try { localStorage.setItem(bkKey, v); } catch (e) { /* private window */ } };
  useEffect(() => {
    const ro = new ResizeObserver(() => { if (wrap.current) setCw(wrap.current.clientWidth); });
    if (wrap.current) { ro.observe(wrap.current); setCw(wrap.current.clientWidth); }
    return () => ro.disconnect();
  }, []);
  const k = cw / W;                                 // page px per screen px
  const ch = H * k;
  const byKey = {};
  els.forEach((e) => { byKey[e.key] = e; });
  // each element's box on the screen (%), a drag or nudge in flight taking the place of its saved box
  const live = (key) => (drag && drag.key === key ? drag.box : nudged && nudged.key === key ? nudged.box : null);
  const scr = {};
  const screenBox = (e) => {
    if (scr[e.key]) return scr[e.key];
    const own = live(e.key);
    if (own) return (scr[e.key] = own);
    const p = e.parent && byKey[e.parent] ? screenBox(byKey[e.parent]) : null;
    return (scr[e.key] = toScreen(e.box, p));
  };
  const parentBox = (e) => (e.parent && byKey[e.parent] ? screenBox(byKey[e.parent]) : null);
  const place = (e, sbox) => call("modes.jjp_place", scope, e.key, toParent(sbox, parentBox(e)).map(r2));

  // snapping: the screen's edges and centre, the parent's, and every other element's
  const guides = (key) => {
    const xs = [0, 50, 100], ys = [0, 50, 100];
    els.forEach((o) => {
      if (o.key === key || o.off) return;
      const b = screenBox(o);
      xs.push(b[0], b[0] + b[2] / 2, b[0] + b[2]); ys.push(b[1], b[1] + b[3] / 2, b[1] + b[3]);
    });
    return { xs, ys };
  };
  const snap1 = (vals, lines, tolPct) => {
    let best = null;
    vals.forEach((v, i) => lines.forEach((l) => {
      const d = l - v;
      if (Math.abs(d) <= tolPct && (!best || Math.abs(d) < Math.abs(best.d))) best = { d, l, i };
    }));
    return best;
  };

  const start = (e, ev, handle) => {
    ev.preventDefault(); ev.stopPropagation();
    setSel(e.key);
    if (wrap.current) wrap.current.focus();
    const b0 = screenBox(e).slice();
    const x0 = ev.clientX, y0 = ev.clientY, g = guides(e.key);
    const tx = SNAP_PX * 100 / W, ty = SNAP_PX * 100 / H;
    let last = null;
    const move = (m) => {
      const dx = (m.clientX - x0) / k * 100 / W, dy = (m.clientY - y0) / k * 100 / H;
      let [x, y, w, h] = b0;
      const shown = [];
      if (!handle) {
        x += dx; y += dy;
        if (!m.altKey) {
          const sx = snap1([x, x + w / 2, x + w], g.xs, tx), sy = snap1([y, y + h / 2, y + h], g.ys, ty);
          if (sx) { x += sx.d; shown.push({ x: sx.l }); }
          if (sy) { y += sy.d; shown.push({ y: sy.l }); }
        }
      } else {
        let l = x, t = y, rr = x + w, bb = y + h;
        if (handle.includes("w")) l += dx;
        if (handle.includes("e")) rr += dx;
        if (handle.includes("n")) t += dy;
        if (handle.includes("s")) bb += dy;
        if (!m.altKey) {
          const fix = (v, lines, tol, axis) => { const s = snap1([v], lines, tol); if (s) { shown.push({ [axis]: s.l }); return s.l; } return v; };
          if (handle.includes("w")) l = fix(l, g.xs, tx, "x");
          if (handle.includes("e")) rr = fix(rr, g.xs, tx, "x");
          if (handle.includes("n")) t = fix(t, g.ys, ty, "y");
          if (handle.includes("s")) bb = fix(bb, g.ys, ty, "y");
        }
        const minW = 4 * 100 / W, minH = 4 * 100 / H;
        if (rr - l < minW) { if (handle.includes("w")) l = rr - minW; else rr = l + minW; }
        if (bb - t < minH) { if (handle.includes("n")) t = bb - minH; else bb = t + minH; }
        x = l; y = t; w = rr - l; h = bb - t;
      }
      last = [x, y, w, h];
      setDrag({ key: e.key, box: last, shown });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (last) {
        setNudged({ key: e.key, box: last });      // held until the saved box comes back
        place(e, last);
      }
      setDrag(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  // the saved boxes came back: drop the held one
  useEffect(() => { setNudged(null); }, [lay]);

  const nudgeT = useRef(null);
  const onKey = (ev) => {
    const e = byKey[sel];
    if (!e) return;
    const step = ev.shiftKey ? 10 : 1;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
    if (!d) return;
    ev.preventDefault();
    const b = screenBox(e).slice();
    b[0] += d[0] * 100 / W; b[1] += d[1] * 100 / H;
    setNudged({ key: e.key, box: b });
    clearTimeout(nudgeT.current);
    nudgeT.current = setTimeout(() => place(e, b), 350);
  };

  const cur = byKey[sel];
  const bkOpts = [{ value: "", label: "Black" }].concat(backdrops.map((b) => ({ value: b.path, label: b.label })))
    .concat(bk && !backdrops.some((b) => b.path === bk) ? [{ value: bk, label: bk.split(/[\\/]/).pop() }] : [])
    .concat(onBrowse ? [{ value: "::browse", label: "Choose a picture or video…" }] : []);
  const pickBk = async (v) => {
    if (v !== "::browse") return setBk(v);
    const p = await onBrowse();
    if (p) setBk(typeof p === "string" ? p : (p && p.result) || "");
  };
  const bkIsVideo = /\.(webm|mp4|mkv|mov|ogv|avi|m4v)$/i.test(bk);
  const panel = els.find((e) => e.kind === "panel" && e.word);
  return html`<div class="jjpl" data-screen=${lay ? lay.screen : ""}>
    <div class="jjpl-hd row wrap">
      <span class="jjpl-title">${title}</span>
      ${panel ? html`<span class="small muted">Panel place</span>
        <div class="pages jjpl-words" role="tablist">${lay.words.map((w) => html`<button type="button" key=${w}
          class=${panel.word === w && !panel.set ? "on" : ""} title=${w === "none" ? "No panel, title, total or timer" : `The panel at the ${w} of the screen (its own box taken away)`}
          onClick=${() => call("modes.jjp_panel_word", scope, w)}>${w}</button>`)}</div>` : null}
      ${lay && lay.screen === "progress" ? html`<div class="pages" role="tablist">
        <button type="button" class=${lit ? "on" : ""} onClick=${() => setLit(true)} title="Each pane as a played mode lights it">Lit</button>
        <button type="button" class=${!lit ? "on" : ""} onClick=${() => setLit(false)} title="Each pane before its mode is played">Unlit</button></div>` : null}
      <span class="sp"></span>
      <span class="small muted">Backdrop</span>
      <${Select} sm value=${bk} options=${bkOpts} onChange=${pickBk} width=${230} title="What to see under the layout: nothing, or a picture or video (its first frame)" />
    </div>
    ${hint ? html`<div class="small muted jjpl-hint">${hint}</div>` : null}
    <div class="jjpl-canvas" ref=${wrap} tabindex="0" style=${{ height: ch + "px" }} onKeyDown=${onKey}
      onPointerDown=${() => setSel("")}>
      ${bk ? (bkIsVideo ? html`<video class="jjpl-bk" src=${mediaUrl(bk)} muted preload="auto" />`
                       : html`<img class="jjpl-bk" src=${mediaUrl(bk)} draggable=${false} />`) : null}
      ${els.map((e) => {
        const b = screenBox(e);
        const wpx = b[2] / 100 * cw, hpx = b[3] / 100 * ch;
        const st = { left: b[0] / 100 * cw + "px", top: b[1] / 100 * ch + "px", width: wpx + "px", height: hpx + "px" };
        return html`<div key=${e.key} class=${cx("jjpl-el", "k-" + e.kind, sel === e.key && "sel", !e.set && "dflt", e.off && "off")}
          style=${st} title=${`${e.label}${e.set ? "" : " (default place)"}${e.where === "title" ? " - from Every mode of this game" : ""}`}
          onPointerDown=${(ev) => start(e, ev, null)}>
          <${Look} el=${e} wpx=${wpx} hpx=${hpx} lit=${lit} scale=${k} />
          <span class="jjpl-tag">${e.label}</span>
          ${sel === e.key ? HANDLES.map((hd) => html`<span key=${hd} class=${"jjpl-h h-" + hd} onPointerDown=${(ev) => start(e, ev, hd)}></span>`) : null}
        </div>`;
      })}
      ${drag ? (drag.shown || []).map((g, i) => html`<div key=${i} class="jjpl-guide" style=${g.x != null
        ? { left: g.x / 100 * cw + "px", top: 0, bottom: 0, width: "1px" } : { top: g.y / 100 * ch + "px", left: 0, right: 0, height: "1px" }}></div>`) : null}
    </div>
    <${Inspector} e=${cur} sbox=${cur ? screenBox(cur) : null} pbox=${cur ? parentBox(cur) : null} W=${W} H=${H}
      onSet=${(b) => cur && call("modes.jjp_place", scope, cur.key, b.map(r2))}
      onReset=${() => cur && call("modes.jjp_place", scope, cur.key, null)} />
  </div>`;
}

// the picked element's numbers: x y w h in % of its parent, and its pixels on the screen
function Inspector({ e, sbox, pbox, W, H, onSet, onReset }) {
  if (!e) return html`<div class="jjpl-insp small muted">Click a box to pick it: drag it to move it, its handles to size it,
    the arrow keys to nudge it a pixel (Shift: ten). Edges and centres snap to the screen, the panel and each other; hold Alt not to snap.</div>`;
  const b = toParent(sbox, pbox).map(r2);
  const px = [sbox[0] * W / 100, sbox[1] * H / 100, sbox[2] * W / 100, sbox[3] * H / 100].map(Math.round);
  const of = e.parent ? (e.parent === "game_type_at" ? "% of the menu" : "% of the panel") : "% of the screen";
  return html`<div class="jjpl-insp row wrap">
    <b>${e.label}</b>
    ${["x", "y", "w", "h"].map((n, i) => html`<label key=${n} class="jjpl-num"><span>${n}</span>
      <input class="num" type="number" step="0.1" value=${b[i]} onChange=${(ev) => {
        const v = Number(ev.target.value);
        if (Number.isFinite(v)) { const nb = b.slice(); nb[i] = v; onSet(nb); }
      }} /></label>`)}
    <span class="small muted">${of} · ${px[0]}, ${px[1]} · ${px[2]} x ${px[3]} px</span>
    ${e.font ? html`<span class="small muted" title="The browser cannot draw the game's font objects: the text is fitted the way the game fits it, in a stand-in face">${e.font} (stand-in)</span>` : null}
    <span class="sp"></span>
    ${e.where === "title" ? html`<span class="small muted">from Every mode of this game</span>` : null}
    <${Button} size="xs" kind="ghost" disabled=${!e.set || e.where === "title"} onClick=${onReset}
      title="Take its box away: the runtime draws it at its default place">Default place<//>
  </div>`;
}
