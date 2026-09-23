// The Fonts window ("Fonts — Preview & Import"): a floating tool window.
// Python: webui/text_fonts.py (ns "text_fonts").  The shell renders it (and
// the Scenes window) over every tab; it shows itself while text_fonts.open is
// true.  ToolWindow and ToolDock below are shared with the Scenes window.

import { html, useState, useEffect, useLayoutEffect, useRef, Button, Field, Select, Check, Radio, Table,
         openMenu, menuOpen, InfoBadge, tip, call, mediaUrl, cx, Spinner } from "../core/ui.js";
import { useNs, state } from "../core/store.js";

const CSS_HREF = "/static/css/tabs/text_fonts.css";
if (typeof document !== "undefined" && !document.querySelector(`link[href="${CSS_HREF}"]`)) {
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = CSS_HREF;
  document.head.appendChild(l);
}

// Tk's Treeview: Font 230 px (stretches), Size 104, Chars 52, Scenes 56.
// The name column takes most of the room so rows of one typeface stay
// tellable apart; the counts keep their width (minmax(n,n) is a fixed track
// the Table keeps even as the last column).
const FONT_COLS = [
  { key: "label", label: "Font", width: "minmax(0,1.45fr)", titleOf: (r) => r.label + "\n" + r.key },
  { key: "size", label: "Size", width: "minmax(96px,1fr)", cls: "small",
    render: (r) => (r.pending ? html`<span class="warn-ink">${r.size}</span>` : r.size), titleOf: (r) => r.size },
  { key: "chars", label: "Chars", width: "50px", num: true },
  { key: "scenes", label: "Scenes", width: "minmax(56px,56px)", num: true },
];
let fontWidths = null;          // dragged column widths, kept for the session

// ------------------------------------------------------------ tool windows
// The Fonts and Scenes windows float over the app the way Tk's Toplevels did:
// nothing is dimmed, the rail and the tab under them stay usable, both can be
// open at once (the one used last is in front, and closing it shows the
// other), the title bar drags, the corner sizes.  Escape closes the window
// that has the keyboard (Tk bound it on the Toplevel), never while a menu or
// a question is open over it.
const Z_BASE = 44;              // under a question's scrim (50) and menus (60)
const zOrder = ["text_scenes", "text_fonts"];
const zSubs = new Set();
export function raiseTool(ns) {
  const i = zOrder.indexOf(ns);
  if (i === zOrder.length - 1) return;
  if (i >= 0) zOrder.splice(i, 1);
  zOrder.push(ns);
  zSubs.forEach((f) => f());
}
function useZ(ns) {
  const [, force] = useState(0);
  useEffect(() => {
    const f = () => force((n) => n + 1);
    zSubs.add(f);
    return () => zSubs.delete(f);
  }, []);
  return Z_BASE + Math.max(0, zOrder.indexOf(ns));
}
const zoomOf = () => parseFloat(document.documentElement.style.zoom) || 1;
// a Python question (messagebox / prompt / file picker) is up
export function questionOpen() { return !!((state.modals || {}).open || []).length; }
const places = {};              // ns -> {x, y, w, h}: where the user left it

const ASIDE_TIP = "Step aside: move this window out of the way (nothing is closed). Its button in the "
  + "status bar brings it back.";

export function ToolWindow({ ns, title, raiseN, onClose, onAside, holdEsc, footer, children, cls = "" }) {
  const layer = useRef(null);
  const win = useRef(null);
  const z = useZ(ns);
  const [pos, setPos] = useState(() => (places[ns] && places[ns].x != null ? places[ns] : null));
  const clamp = (p) => {
    const L = layer.current, W = win.current;
    if (!L || !W) return p;
    return {
      x: Math.round(Math.min(Math.max(p.x, 96 - W.offsetWidth), L.clientWidth - 96)),
      y: Math.round(Math.min(Math.max(p.y, 0), L.clientHeight - 48)),
    };
  };
  const keep = (p) => { places[ns] = { ...(places[ns] || {}), ...p }; setPos(p); };
  useLayoutEffect(() => {
    const L = layer.current, W = win.current;
    if (!L || !W) return;
    const room = { w: L.clientWidth - W.offsetWidth, h: L.clientHeight - W.offsetHeight };
    if (pos) {                  // opened again: where it was left, but all of it in view
      keep({ x: Math.max(0, Math.min(pos.x, room.w)), y: Math.max(0, Math.min(pos.y, room.h)) });
      return;
    }
    // first time: centred over the app, stepped down and right from the
    // other tool window when that one sits in the same place
    let p = { x: Math.max(0, Math.round(room.w / 2)), y: Math.max(0, Math.round(room.h / 2)) };
    const other = Object.entries(places).find(([k, v]) => k !== ns && v && v.x === p.x && v.y === p.y);
    if (other) p = { x: Math.max(0, Math.min(p.x + 32, room.w)), y: Math.max(0, Math.min(p.y + 32, room.h)) };
    keep(p);
  }, []);
  useEffect(() => {             // opened / brought back: in front, with the keyboard
    raiseTool(ns);
    const W = win.current;
    if (W && !W.contains(document.activeElement)) W.focus({ preventScroll: true });
  }, [raiseN]);
  useEffect(() => {             // a smaller app window keeps the title bar reachable
    const onResize = () => setPos((p) => {
      if (!p) return p;
      const c = clamp(p);
      places[ns] = { ...(places[ns] || {}), ...c };
      return c;
    });
    window.addEventListener("resize", onResize);
    const W = win.current;      // remember a size the user dragged
    const ro = W && typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => {
      if (W.style.width || W.style.height) places[ns] = { ...(places[ns] || {}), w: W.style.width, h: W.style.height };
    }) : null;
    if (ro) ro.observe(W);
    return () => { window.removeEventListener("resize", onResize); if (ro) ro.disconnect(); };
  }, []);
  const startDrag = (e) => {
    if (e.button !== 0 || e.target.closest("button")) return;
    e.preventDefault();
    const zf = zoomOf(), x0 = e.clientX, y0 = e.clientY, p0 = pos || { x: 0, y: 0 };
    const move = (ev) => keep(clamp({ x: p0.x + (ev.clientX - x0) / zf, y: p0.y + (ev.clientY - y0) / zf }));
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  const onKey = (e) => {
    if (e.key !== "Escape" || !onClose || e.defaultPrevented) return;
    if (holdEsc || menuOpen() || questionOpen()) return;
    e.preventDefault();
    e.stopPropagation();
    onClose();
  };
  const pl = places[ns] || {};
  return html`<div class="toolwin-layer" ref=${layer} style=${{ zIndex: z }}>
    <section class=${cx("toolwin", cls)} ref=${win} role="dialog" aria-label=${title} tabindex="-1"
        style=${{ left: (pos ? pos.x : 0) + "px", top: (pos ? pos.y : 0) + "px", visibility: pos ? "visible" : "hidden",
                  width: pl.w || undefined, height: pl.h || undefined }}
        onMouseDownCapture=${() => raiseTool(ns)} onKeyDown=${onKey}>
      <header class="hd" onMouseDown=${startDrag}>
        <span class="h2">${title}</span>
        ${onAside ? html`<${Button} kind="ghost" size="sm" icon="minus" title=${ASIDE_TIP} label="Step aside" onClick=${onAside} />` : null}
        <${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${onClose} />
      </header>
      <div class="bd">${children}</div>
      ${footer ? html`<div class="ft">${footer}</div>` : null}
    </section>
  </div>`;
}

// The status bar's buttons for a window that stepped aside (a jump to a tab,
// or its own Step aside button): Tk lowered it behind the main window, where
// the taskbar still showed it.
const DOCK = [
  { ns: "text_scenes", label: "Scenes", icon: "images", tip: "Bring the Scenes window back." },
  { ns: "text_fonts", label: "Fonts", icon: "text", tip: "Bring the Fonts window back." },
];
export function ToolDock() {
  const sc = useNs("text_scenes");
  const fo = useNs("text_fonts");
  const by = { text_scenes: sc, text_fonts: fo };
  const items = DOCK.filter((d) => by[d.ns].alive && !by[d.ns].open);
  const [at, setAt] = useState(null);
  useEffect(() => {
    if (!items.length) return undefined;
    const place = () => {
      const zf = zoomOf();
      const bar = document.querySelector(".statusbar");
      let next;
      if (bar) {
        const r = bar.getBoundingClientRect();
        const last = bar.lastElementChild;
        const lr = last ? last.getBoundingClientRect() : { left: r.right };
        next = { top: Math.round((r.top + r.height / 2) / zf - 14), right: Math.round((window.innerWidth - lr.left) / zf + 8) };
      } else {
        next = { top: Math.round(window.innerHeight / zf - 46), right: 18 };
      }
      setAt((p) => (p && p.top === next.top && p.right === next.right ? p : next));
    };
    place();
    const t = setInterval(place, 400);
    window.addEventListener("resize", place);
    return () => { clearInterval(t); window.removeEventListener("resize", place); };
  }, [items.length]);
  if (!items.length) return null;
  return html`<div class="tool-dock" role="toolbar" aria-label="Windows stepped aside"
      style=${at ? { top: at.top + "px", right: at.right + "px" } : { visibility: "hidden" }}>
    ${items.map((d) => html`<${Button} key=${d.ns} size="sm" icon=${d.icon} title=${d.tip}
      onClick=${() => call(d.ns + ".show")}>${d.label}<//>`)}
  </div>`;
}

function Num({ value, min, max, step = 1, onCommit, label, width = 64 }) {
  const [v, setV] = useState(String(value ?? ""));
  useEffect(() => setV(String(value ?? "")), [value]);
  return html`<div class="field sm" style=${`width:${width}px;flex:0 0 ${width}px`}>
    <input type="number" min=${min} max=${max} step=${step} value=${v} aria-label=${label}
      onInput=${(e) => setV(e.target.value)}
      onChange=${(e) => onCommit(e.target.value)} /></div>`;
}

export function FontsWindow() {
  const s = useNs("text_fonts");
  const last = useRef(null);            // last clicked scene row (shift ranges)
  const dock = html`<${ToolDock} />`;
  if (!s.open) return dock;
  const tips = s.tips || {};
  const o = s.opts || {};
  const some = s.scope === "some";
  const sel = new Set(s.scope_sel || []);
  const setOpt = (k, v) => call("text_fonts.set_opt", k, v);
  const clickScene = (i, e) => {
    if (!some) return;
    let next;
    if (e.shiftKey && last.current != null) {
      const [a, b] = [Math.min(last.current, i), Math.max(last.current, i)];
      next = new Set(sel);
      for (let k = a; k <= b; k++) next.add(k);
    } else if (e.ctrlKey || e.metaKey) {
      next = new Set(sel);
      if (next.has(i)) next.delete(i); else next.add(i);
    } else {
      next = new Set([i]);
    }
    last.current = i;
    call("text_fonts.set_scope_sel", [...next]);
  };
  const sceneMenu = (i, sc, e) => {
    e.preventDefault();
    const short = (sc.label || "").trim().split(" — ")[0];
    openMenu({ x: e.clientX, y: e.clientY }, [
      { label: `Show "${short}" in Scenes…`, onClick: () => call("text_fonts.show_scene", i) },
    ]);
  };
  const busy = !!s.busy;
  const close = () => call("text_fonts.close");
  return html`${dock}<${ToolWindow} ns="text_fonts" title="Fonts — Preview & Import" cls="fonts-win" raiseN=${s.raise_n}
      onClose=${close} onAside=${() => call("text_fonts.hide")}
      footer=${html`${busy ? html`<${Spinner} />` : null}<span class="grow"></span>
        <${Button} onClick=${close}>Close<//>`}>
    <p class="small muted" style="margin:0">${s.hint}</p>
    <div class="fonts-body">
      <div class="fonts-left">
        <${Field} sm value=${s.search} placeholder="Search" onChange=${(v) => call("text_fonts.set_search", v)}
          delay=${200} />
        <${Table} cls="fonts-list" columns=${FONT_COLS} rows=${s.fonts || []} rowKey=${(r) => r.key}
          selected=${s.sel} onSelect=${(r) => call("text_fonts.select", r.key)} rowHeight=${30}
          resizable widths=${fontWidths} onResize=${(w) => { fontWidths = w; }} />
        <span class="lbl">Used in scenes:</span>
        <div class="stack" style="gap:0">
          <${Radio} name="fscope" value="all" checked=${!some} label="Change in all of them"
            onChange=${() => call("text_fonts.set_scope_mode", "all")} />
          <${Radio} name="fscope" value="some" checked=${some} label="Change only the scenes I select"
            onChange=${() => call("text_fonts.set_scope_mode", "some")} />
        </div>
        <div class="fonts-scenes" role="listbox" aria-multiselectable=${some} ...${tip(tips.scenes)}>
          ${(s.scenes || []).map((sc, i) => html`<div key=${sc.card} role="option" aria-selected=${some && sel.has(i)}
              class=${cx("fs-item mono", some && sel.has(i) && "sel", !some && "dim")}
              onClick=${(e) => clickScene(i, e)} onContextMenu=${(e) => sceneMenu(i, sc, e)}>${sc.label}</div>`)}
        </div>
        <span class="small muted">${s.scope_lbl}</span>
      </div>
      <div class="fonts-right">
        <div class="row wrap fonts-prow">
          <label class="lbl nw" for="fs-text">Preview text:</label>
          <div class="grow" style="min-width:180px" ...${tip(tips.text)}>
            <${Field} id="fs-text" sm value=${o.text} onChange=${(v) => setOpt("text", v)} delay=${150} />
          </div>
          <span class="row nw" style="gap:6px"><span class="lbl">Zoom:</span>
          <${Select} sm width=${70} value=${o.zoom} options=${["1x", "2x", "3x", "4x"]} onChange=${(v) => setOpt("zoom", v)} /></span>
          <span class="row nw" style="gap:6px"><span class="lbl">Show:</span>
          <${Select} sm width=${160} value=${o.show} options=${s.show_options || []} onChange=${(v) => setOpt("show", v)} /></span>
          <span class="row nw" style="gap:6px"><span class="lbl">Behind:</span>
          <${Select} sm width=${130} value=${o.bg} options=${s.bgs || []} onChange=${(v) => setOpt("bg", v)} title=${tips.behind} /></span>
        </div>
        <div class="fonts-canvas" style=${`background:${s.preview_bg || "#101014"}`}>
          ${s.preview ? html`<img src=${mediaUrl(s.preview)} alt="" width=${s.preview_w} height=${s.preview_h} />` : null}
        </div>
        <div class="small muted fonts-status">${s.status}</div>
        <section class="fonts-import">
          <div class="eyebrow">Import a desktop font</div>
          <div class="row wrap">
            <${Button} size="sm" onClick=${() => call("text_fonts.pick_ttf")} disabled=${!s.sel}>Import font file…<//>
            <span class="small muted">${s.ttf_label}</span>
          </div>
          <div class="row wrap">
            <span class="lbl">Color:</span>
            <input type="color" class="fonts-swatch" value=${s.color} aria-label="Ink color" ...${tip(tips.color)}
              onChange=${(e) => call("text_fonts.set_color", e.target.value)} />
            <${Check} checked=${o.auto_color} label="match original" onChange=${(v) => setOpt("auto_color", v)} />
            <span class="lbl" style="margin-left:8px">Outline:</span>
            <span ...${tip(tips.stroke)}><${Num} value=${o.stroke} min=${0} max=${6} label="Outline px"
              onCommit=${(v) => setOpt("stroke", v)} width=${58} /></span>
            <input type="color" class="fonts-swatch" value=${s.stroke_color} aria-label="Outline color" ...${tip(tips.stroke)}
              onChange=${(e) => call("text_fonts.set_stroke_color", e.target.value)} />
            <span class="small muted">px (0 = none)</span>
          </div>
          ${s.tint ? html`<div class=${cx("small", s.tint_warn ? "warn-ink" : "muted")}>${s.tint}</div>` : null}
          <div class="row wrap">
            <span class="lbl">Size:</span>
            <span ...${tip(tips.scale)}><${Num} value=${o.scale} min=${50} max=${100} step=${5} label="Size percent"
              onCommit=${(v) => setOpt("scale", v)} /></span>
            <span class="small muted">% of the auto-fitted size</span>
            <span class="lbl" style="margin-left:8px">Letter width:</span>
            <span ...${tip(tips.width)}><${Num} value=${o.width} min=${60} max=${100} step=${5} label="Letter width percent"
              onCommit=${(v) => setOpt("width", v)} /></span>
            <span class="small muted">% (lower = more space between letters)</span>
          </div>
          ${s.comp_text ? html`<div class="stack" style="gap:4px">
            <div class=${cx("small", s.comp_warn ? "warn-ink" : "muted")}>${s.comp_text}</div>
            ${s.comp_ctrl ? html`<div class="row"><span class="lbl">Its outline:</span>
              <${Select} sm width=${280} value=${o.comp} options=${s.comp_options || []} title=${tips.comp}
                onChange=${(v) => setOpt("comp", v)} /></div>` : null}
          </div>` : null}
        </section>
        ${s.all_sizes_label ? html`<${Check} checked=${o.all_sizes} label=${s.all_sizes_label} title=${tips.all_sizes}
          onChange=${(v) => setOpt("all_sizes", v)} wrap />` : null}
        <div class="row wrap fonts-actions">
          <${Button} kind="primary" disabled=${!s.can_apply || busy} title=${tips.apply}
            onClick=${() => call("text_fonts.apply")}>Apply to this font<//>
          <${Button} disabled=${!s.can_undo || busy} title=${tips.undo} onClick=${() => call("text_fonts.undo")}>${s.undo_label || "Undo"}<//>
          <${Button} disabled=${!s.sel || busy} title=${tips.blank} onClick=${() => call("text_fonts.blank")}>Blank font<//>
          <${Button} disabled=${!s.sel || busy} title=${tips.revert} onClick=${() => call("text_fonts.revert")}>Revert font<//>
          <${Button} kind="ghost" disabled=${!(s.fonts || []).length || busy} title=${tips.revert_all}
            onClick=${() => call("text_fonts.revert_all")}>Revert all fonts…<//>
        </div>
      </div>
    </div>
  <//>`;
}
