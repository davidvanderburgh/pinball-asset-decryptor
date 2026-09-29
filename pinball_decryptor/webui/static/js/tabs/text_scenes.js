// The scenes ("what each scene is made of") and the scene editor (PAD-251).  A page of its
// own now, the Scenes tab (tabs/scenes.js hosts ScenesPage); it was a floating window.
// Python: webui/text_scenes.py (ns "text_scenes").

import { html, useState, useEffect, useRef, Button, Field, Select, Seg, Table, Modal, openMenu, InfoBadge,
         Icon, Progress, Spinner, tip, call, mediaUrl, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

// Load its own sheet once.
const CSS_HREF = "/static/css/tabs/text_scenes.css";
if (typeof document !== "undefined" && !document.querySelector(`link[href="${CSS_HREF}"]`)) {
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = CSS_HREF;
  document.head.appendChild(l);
}

// Tk: Scene 220 px (stretches), then 56 / 48 / 44 / 46 px counts that do
// not stretch.  The last one is a minmax(n,n) track so the Table keeps its
// width (a plain px width on the last column is turned into "the rest").
const SCENE_COLS = [
  { key: "label", label: "Scene", width: "minmax(0,1fr)", sort: "#0",
    titleOf: (r) => r.label + "\n" + r.d + (r.state ? "\n" + STATE_TIP[r.state] : ""),
    render: (r) => html`<span class="sc-name"><span class=${"sc-dot " + (r.state || "same")}></span><span class="ellip">${r.label}</span></span>` },
  { key: "imgs", label: "Images", width: "60px", sort: "imgs", num: true },
  { key: "fonts", label: "Fonts", width: "50px", sort: "fonts", num: true },
  { key: "texts", label: "Text", width: "44px", sort: "texts", num: true },
  { key: "vids", label: "Video", width: "minmax(50px,50px)", sort: "vids", num: true },
];
let sceneWidths = null;         // dragged column widths, kept for the session
// DragonRR: a scene's colour says where its edits stand - orange: changed and not written to
// a card yet (the next Write puts them on); green: exactly what the last Write put on the card
const STATE_TIP = {
  same: "Not changed: the scene as the game ships it.",
  edited: "Changed since the last Write: the next Write puts it on the card.",
  written: "Written: the last Write put exactly these edits on the card.",
};
// The count columns the scene list has room for: a narrow list keeps the scene NAMES
// readable and drops the counts, least useful first (Video, Fonts, then Text and Images).
const COLS_BY_WIDTH = [[470, ["imgs", "fonts", "texts", "vids"]], [330, ["imgs", "texts"]],
  [250, ["imgs"]], [0, []]];
function sceneCols(width) {
  const keep = (COLS_BY_WIDTH.find(([w]) => width >= w) || [0, []])[1];
  const cols = SCENE_COLS.filter((c) => c.key === "label" || keep.includes(c.key));
  // the last column is a fixed track so the Table keeps its width (see SCENE_COLS)
  return cols.map((c, i) => (i === cols.length - 1 && c.key !== "label" && !c.width.startsWith("minmax")
    ? { ...c, width: `minmax(${parseInt(c.width, 10)}px,${parseInt(c.width, 10)}px)` } : c));
}

// The dividers between the scene list, the preview and the inspector (and between the
// inspector's selection and its Layers): where the user left them, kept across sessions.
// Unset = the layout's own proportions; a double-click on a divider puts it back.
const SPLIT_KEY = "pad.scenes.split";
function loadSplit() {
  try { return JSON.parse(localStorage.getItem(SPLIT_KEY) || "{}") || {}; } catch (e) { return {}; }
}
const SPLIT_LIMITS = { left: [180, 720], right: [240, 760], top: [90, 2000] };
const clampSplit = (k, v) => Math.round(Math.max(SPLIT_LIMITS[k][0], Math.min(SPLIT_LIMITS[k][1], v)));

// One divider.  *measure(event)* turns the pointer into the size it sets (unzoomed px);
// *dir* is the sign an arrow key moves it by.
function Divider({ k, horizontal, measure, split, setSplit, save, dir = 1, label }) {
  const drag = useRef(false);
  const down = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    drag.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e) => {
    if (!drag.current) return;
    const v = measure(e);
    if (v != null) setSplit((q) => ({ ...q, [k]: clampSplit(k, v) }));
  };
  const up = () => { if (drag.current) { drag.current = false; save(); } };
  const key = (e) => {
    const step = (e.shiftKey ? 64 : 16) * dir;
    const back = horizontal ? "ArrowUp" : "ArrowLeft", fwd = horizontal ? "ArrowDown" : "ArrowRight";
    if (e.key !== back && e.key !== fwd) return;
    e.preventDefault();
    const cur = split[k] != null ? split[k] : measure(null);
    if (cur == null) return;
    setSplit((q) => ({ ...q, [k]: clampSplit(k, cur + (e.key === fwd ? step : -step)) }));
    setTimeout(save, 0);
  };
  const reset = () => { setSplit((q) => { const n = { ...q }; delete n[k]; return n; }); setTimeout(save, 0); };
  return html`<div class=${cx("sc-split", horizontal ? "h" : "v", "sc-split-" + k)} role="separator" tabIndex="0"
    aria-orientation=${horizontal ? "horizontal" : "vertical"} aria-label=${label}
    title=${label + ": drag to resize, double-click to put it back"}
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}
    onDblClick=${reset} onKeyDown=${key}><span></span></div>`;
}

// The page head's buttons (Export picture…, Export all pictures…, Re-read from card…): none of
// them is needed to keep an edit (edits are kept as they are made; Write puts them on the card).
export function ScenesActions() {
  const s = useNs("text_scenes");
  if (!s.alive) return null;
  const tips = s.tips || {};
  return html`
    ${s.rebuild_msg ? html`<span class="small muted scenes-msg-head">${s.rebuild_msg}</span>` : null}
    <${Button} kind="ghost" icon="download" disabled=${!s.can_save && !s.exporting} title=${tips.save}
      onClick=${() => call("text_scenes.save_preview")}>${s.exporting ? "Cancel" : "Export picture…"}<//>
    <${Button} kind="ghost" title=${tips.save_all} disabled=${!(s.scenes || []).length && !s.bulk}
      onClick=${() => call("text_scenes.save_all")}>${s.bulk ? "Cancel" : "Export all pictures…"}<//>
    <${Button} kind="ghost" icon=${s.rebuilding ? "x" : "refresh"} title=${tips.rebuild}
      onClick=${() => call("text_scenes.rebuild")}>${s.rebuilding ? "Cancel" : "Re-read from card…"}<//>`;
}

export function ScenesPage() {
  const s = useNs("text_scenes");
  const [color, setColor] = useState(null);     // {text, start, stock, title}
  const [wide, setWide] = useState(false);      // the scene editor without the scene list
  const [playFrame, setPlayFrame] = useState(0); // the frame a playback is on
  useEffect(() => { if (!s.tree_play) setPlayFrame(0); }, [s.tree_play]);
  const [split, setSplit] = useState(loadSplit);
  const splitRef = useRef(split);
  splitRef.current = split;
  const saveSplit = () => { try { localStorage.setItem(SPLIT_KEY, JSON.stringify(splitRef.current)); } catch (e) {} };
  const bodyRef = useRef(null);
  const inspRef = useRef(null);
  const listRef = useRef(null);
  const [listW, setListW] = useState(340);
  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => setListW(el.offsetWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const topRef = useRef(null);
  // pointer -> unzoomed px against the element (the app can be zoomed: rect px / offset px)
  const scaleOf = (el, r) => (r.width ? el.offsetWidth / r.width : 1) || 1;
  const measureLeft = (e) => {
    const el = bodyRef.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!e) { const l = el.querySelector(".scenes-left"); return l ? l.offsetWidth : null; }
    return (e.clientX - r.left) * scaleOf(el, r);
  };
  const measureRight = (e) => {
    const el = bodyRef.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!e) { const i = inspRef.current; return i ? i.offsetWidth : null; }
    return (r.right - e.clientX) * scaleOf(el, r);
  };
  const measureTop = (e) => {
    const el = inspRef.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!e) return topRef.current ? topRef.current.offsetHeight : null;
    return (e.clientY - r.top) * scaleOf(el, r);
  };
  const splitProps = { split, setSplit, save: saveSplit };
  const bodyStyle = [split.left != null ? `--sc-left:${split.left}px` : "",
    split.right != null ? `--sc-right:${split.right}px` : ""].filter(Boolean).join(";");
  useEffect(() => { if (!s.alive) setColor(null); }, [s.alive]);
  const tips = s.tips || {};
  const layout = s.layout_dialog;               // Move… / Font size…, shown in the side column
  const startColor = async (text) => {
    const c = await call("text_scenes.color_start", text);
    if (c) setColor(c);
  };
  const startLayout = (text, kind) => call("text_scenes.layout_start", text, kind);
  const itemMenu = (it, e) => {
    if (!it.id) return;
    call("text_scenes.select_item", it.id);
    let items = [];
    if (it.id.startsWith("txt::")) {
      items = [
        { label: "Text colour…", onClick: () => startColor(it.text) },
        it.picked ? { label: "Back to the original colour", onClick: () => call("text_scenes.reset_color", it.text) } : null,
        { sep: true },
        { label: "Move…", onClick: () => startLayout(it.text, "move") },
        { label: "Alignment", submenu: [["left", "Left"], ["center", "Centre"], ["right", "Right"]].map(([n, l]) => ({
          label: l, checked: it.align === n, onClick: () => call("text_scenes.align_text", it.text, n) })) },
        { label: "Font size…", onClick: () => startLayout(it.text, "size") },
        it.has_layout ? { label: "Back to the original layout", onClick: () => call("text_scenes.reset_layout", it.text) } : null,
        { sep: true },
        { label: "Find on the Replace Text tab", onClick: () => call("text_scenes.activate", it.id) },
      ];
    } else if (it.id.startsWith("font::")) {
      const key = it.id.slice(6);
      items = [
        { label: "Blank this font in this scene", onClick: () => call("text_scenes.blank_font", key, true) },
        { label: "Blank this font everywhere it is used", onClick: () => call("text_scenes.blank_font", key, false) },
        { sep: true },
        { label: "Open in the Fonts window", onClick: () => call("text_scenes.activate", it.id) },
      ];
    } else if (it.id.startsWith("img::")) {
      items = [{ label: "Show on the Images tab", onClick: () => call("text_scenes.activate", it.id) }];
    } else if (it.id.startsWith("vid::")) {
      items = [{ label: "Show on the Video tab", onClick: () => call("text_scenes.activate", it.id) }];
    }
    openMenu({ x: e.clientX, y: e.clientY }, items);
  };
  const editor = !!(s.tree && s.tree_view);
  const stage = editor ? s.tree_view.stage : [1360, 768];
  // The page is one screen tall: the scene list, the preview (as big as the room lets it be,
  // width AND height) and the inspector side by side, each scrolling on its own.
  return html`<section class="card scenes-card">
    <div class=${cx("scenes-body", wide && "wide")} ref=${bodyRef} style=${bodyStyle}>
      <div class="scenes-left">
        <div class="row scenes-search">
          <${Field} sm value=${s.search} placeholder="Search" onChange=${(v) => call("text_scenes.set_search", v)}
            delay=${200} prefix=${html`<${Icon} name="search" />`} />
          <${InfoBadge} text=${s.hint} />
        </div>
        ${(s.scenes || []).length ? null : html`<p class="small muted" style="margin:0">${s.hint}</p>`}
        ${(s.scenes || []).length ? html`<div class="row small muted sc-legend">
          <span class="sc-dot same"></span><span title=${STATE_TIP.same}>not changed</span>
          <span class="sc-dot edited"></span><span title=${STATE_TIP.edited}>not written yet</span>
          <span class="sc-dot written"></span><span title=${STATE_TIP.written}>written to a card</span>
        </div>` : null}
        <div class="scenes-list-wrap" ref=${listRef} ...${tip(tips.list)}>
          <${Table} key=${sceneCols(listW).length} cls="scenes-list" columns=${sceneCols(listW)}
            rowClass=${(r) => (r.state ? "sc-" + r.state : "")} rows=${s.scenes || []} rowKey=${(r) => r.d}
            selected=${s.sel} onSelect=${(r) => call("text_scenes.select", r.d)} rowHeight=${30}
            sort=${{ key: (s.sort || {}).col, desc: (s.sort || {}).rev }}
            onSort=${(k) => call("text_scenes.sort_by", k)}
            resizable widths=${sceneWidths} onResize=${(w) => { sceneWidths = w; }} />
        </div>
      </div>
      <${Divider} k="left" measure=${measureLeft} label="Scene list width" ...${splitProps} />
      <div class="scenes-center">
        ${[s.card_note, editor && s.pic_note].filter(Boolean).map((t, i) => html`<div key=${"w" + i}
          class="note warn scenes-warn" role="status"><${Icon} name="warn" /><div class="body-text small">${t}</div></div>`)}
        <div class="scenes-stage" style=${`--ar:${stage[0] / stage[1]}`}>
          ${s.preparing ? html`<${Preparing} p=${s.preparing} />`
            : editor && s.tree_play ? html`<${TreePlayer} s=${s} onFrame=${setPlayFrame} />`
            : editor ? html`<${TreeCanvas} s=${s} />` : html`<${Preview} s=${s} tip=${tips.preview} />`}
        </div>
        <div class="scenes-stagebar">
          <${Button} size="sm" kind="ghost" icon=${wide ? "right" : "left"} label=${wide ? "Show the scene list" : "Hide the scene list"}
            title=${wide ? "Show the scene list" : "Hide the scene list: more room for the preview"} onClick=${() => setWide(!wide)} />
          ${s.preparing ? html`<span class="grow"></span>`
            : editor ? html`<${TreeActions} t=${s.tree_view} /><span class="grow"></span>
              ${s.tree_live ? html`<span class=${cx("chip sm tree-live-chip", s.tree_live.kind === "live" ? "ok" : "warn")}
                title=${s.tree_live.text}><span class="dot"></span>${s.tree_live.kind === "live" ? "Live in the emulator"
                  : s.tree_live.kind === "failed" ? "Emulator not reached" : "Restart the game to see it"}</span>` : null}
              <${InfoBadge} text=${s.caption_full || s.caption} />`
            : html`<span class="small muted ellip grow">${s.caption}</span>
              ${s.caption_full ? html`<${InfoBadge} text=${s.caption_full} />` : null}`}
          ${(s.screens || []).length ? html`<div class="scenes-ctl">
            <span class="lbl">Screen</span>
            <${Select} sm value=${s.screen} options=${s.screens} onChange=${(v) => call("text_scenes.set_screen", v)} />
            <${Button} size="xs" kind="ghost" icon="left" label="Previous screen" onClick=${() => call("text_scenes.step_screen", -1)} />
            <${Button} size="xs" kind="ghost" icon="right" label="Next screen" onClick=${() => call("text_scenes.step_screen", 1)} />
            <${InfoBadge} text=${tips.screen} />
          </div>` : null}
          ${s.animated ? html`<div class="scenes-ctl">
            <span class="lbl">Speed</span>
            <${Select} sm value=${s.fps_choice} options=${s.fps_choices || []} onChange=${(v) => call("text_scenes.set_fps", v)} />
            <${InfoBadge} text=${tips.speed} />
          </div>` : null}
          <div class="scenes-ctl">
            <span class="lbl">Behind</span>
            <${Select} sm value=${s.bg} options=${s.bgs || []} onChange=${(v) => call("text_scenes.set_bg", v)} />
            <${InfoBadge} text=${tips.behind} />
          </div>
        </div>
        ${layout ? html`<${LayoutEditor} key=${layout.kind + "\u0000" + layout.text} d=${layout} />` : null}
        ${editor || s.preparing ? null : html`<div class="row scenes-bottom">
          <div class="thumb scenes-thumb">${s.thumb ? html`<img src=${mediaUrl(s.thumb)} alt="" />` : null}</div>
          <span class="small muted mono scenes-detail">${s.detail}</span>
        </div>`}
      </div>
      <${Divider} k="right" measure=${measureRight} dir=${-1} label="Inspector width" ...${splitProps} />
      <div class="scenes-inspector" ref=${inspRef}>
        ${editor ? html`<div class="insp-top" ref=${topRef} data-play=${s.tree_play ? 1 : 0}
            style=${split.top != null ? `flex:0 0 auto;height:${split.top}px;max-height:calc(100% - 120px)` : ""}>
            <${TreeSide} t=${s.tree_view} play=${s.tree_play} playFrame=${playFrame} /></div>
          <${Divider} k="top" horizontal measure=${measureTop} label="Selection and Layers" ...${splitProps} />
          <${TreeTop} s=${s} onMenu=${itemMenu} />`
          : s.preparing ? null : html`<${Contents} s=${s} onMenu=${itemMenu} />`}
      </div>
    </div>
  </section>
  ${color ? html`<${ColorDialog} c=${color} onClose=${() => setColor(null)} />` : null}`;
}

// The project was extracted before the scene editor: its scenes are read off the card once
// (text_scenes.py _auto_trees).  This stands where the preview goes until the editor is ready.
function Preparing({ p }) {
  const pct = p.total ? Math.round((100 * p.cur) / p.total) : 0;
  return html`<div class="scenes-preparing" role="status" aria-live="polite">
    <div class="scenes-shimmer"></div>
    <div class="scenes-prep-body">
      <div class="row" style="gap:10px"><${Spinner} /><span class="h2">Getting the scene editor ready</span></div>
      <p class="small muted">This project was extracted before the scene editor existed, so its scenes are being read off the card once (about ten seconds). The list on the left already works.</p>
      <div class="scenes-prep-bar"><${Progress} pct=${pct} busy=${!p.total} /></div>
      <span class="small muted">${p.total ? `Scene ${p.cur} of ${p.total}` : "Opening the card…"}</span>
    </div>
  </div>`;
}

// While a picture is being drawn: the canvas keeps its shape and says so.
function Drawing({ label }) {
  return html`<div class="scenes-drawing" role="status"><div class="scenes-shimmer"></div>
    <span class="row small" style="gap:8px"><${Spinner} />${label || "Drawing the scene…"}</span></div>`;
}

function Contents({ s, onMenu }) {
  const c = s.contents;
  const [open, setOpen] = useState({});
  const listRef = useRef(null);
  useEffect(() => { setOpen({}); }, [c && c.path]);
  useEffect(() => {
    // land on a focused line (Show in Scenes…)
    if (!s.item || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-id="${CSS.escape(s.item)}"]`);
    // centred: the list can still shrink a little once the preview lands
    if (el) el.scrollIntoView({ block: "center" });
  }, [s.item, c && c.path]);
  if (!c) return html`<div class="scenes-contents"><div class="sc-head"><span class="eyebrow">Contents</span></div></div>`;
  return html`<div class="scenes-contents" ref=${listRef} role="tree" aria-label="Contents">
    <div class="sc-head"><span class="eyebrow">Contents</span></div>
    ${c.groups.map((g) => {
      const isOpen = open[g.key] ?? (g.open || (s.item && g.items.some((it) => it.id === s.item)));
      return html`<div class="sc-group" key=${g.key}>
        <button type="button" class="sc-gh" onClick=${() => setOpen({ ...open, [g.key]: !isOpen })}>
          <${Icon} name=${isOpen ? "down" : "right"} />${g.title}</button>
        ${isOpen ? g.items.map((it, n) => html`<div key=${it.id || g.key + n} data-id=${it.id || ""}
            class=${cx("sc-item", it.id && s.item === it.id && "sel", !it.id && "note")}
            onClick=${() => it.id && call("text_scenes.select_item", it.id)}
            onDblClick=${() => it.id && call("text_scenes.activate", it.id)}
            onContextMenu=${(e) => { e.preventDefault(); onMenu(it, e); }}>
          ${it.swatch ? html`<span class="swatch sc-sw" style=${`background:${it.swatch}`}></span>` : html`<span></span>`}
          <span class="sc-t ellip" title=${it.text}>${it.text}</span>
          <span class="sc-i small muted ellip" title=${it.info}>${it.info}</span>
        </div>`) : null}
      </div>`;
    })}
  </div>`;
}

function Preview({ s, tip: help }) {
  const frames = s.frames || [];
  const [i, setI] = useState(0);
  useEffect(() => {
    setI(0);
    if (frames.length < 2) return undefined;
    const ms = Math.max(10, Math.round(1000 / Math.max(1, Number(s.fps) || 12)));
    const t = setInterval(() => setI((n) => (n + 1) % frames.length), ms);
    return () => clearInterval(t);
  }, [frames, s.fps]);
  return html`<div class="scenes-canvas" style=${`background:${s.bg_rgb || "#101014"}`} ...${tip(help)}>
    ${frames.length ? frames.map((p, n) => html`<img key=${p} src=${mediaUrl(p)} alt="" style=${n === i ? "" : "display:none"} />`)
      : s.canvas_msg === "drawing…" ? html`<${Drawing} />` : html`<span class="scenes-msg">${s.canvas_msg}</span>`}
  </div>`;
}

function ColorDialog({ c, onClose }) {
  const [v, setV] = useState(c.start || "#ffffff");
  const ok = () => { onClose(); call("text_scenes.set_color", c.text, v); };
  return html`<${Modal} title=${c.title} onClose=${onClose}
      footer=${html`<${Button} onClick=${onClose}>Cancel<//><${Button} kind="primary" onClick=${ok}>OK<//>`}>
    <div class="row" style="gap:14px">
      <input type="color" class="scenes-color" value=${v} onInput=${(e) => setV(e.target.value)} aria-label="Colour" />
      <span class="mono">${v}</span>
    </div>
  <//>`;
}

// Move… / Font size… (Tk's small _LayoutDialog): the fields sit in a strip
// right under the preview while the edit is live, so the preview they drive
// is never covered.  Every change redraws the preview; Apply (or Enter)
// records it, Cancel (or Escape) puts the preview back.
function LayoutEditor({ d }) {
  const move = d.kind === "move";
  const [vals, setVals] = useState(move ? { dx: d.dx, dy: d.dy } : { size: String(d.size) });
  const [px, setPx] = useState("");
  const first = useRef(null);
  useEffect(() => {
    call("text_scenes.layout_px", vals).then((t) => setPx(t || ""));
    if (first.current) { first.current.focus(); first.current.select(); }
  }, []);
  const change = (k, v) => {
    const next = { ...vals, [k]: v };
    setVals(next);
    call("text_scenes.layout_preview", next).then((t) => { if (typeof t === "string") setPx(t); });
  };
  const apply = () => call("text_scenes.layout_done", vals);
  const cancel = () => call("text_scenes.layout_done", null);
  const onKey = (e) => {
    if (e.key === "Enter") { e.preventDefault(); apply(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
  };
  const num = (k, label, min, max, step, n) => html`
    <label class="lbl nw" for=${"ly-" + k}>${label}</label>
    <div class="field sm scenes-ly-f"><input id=${"ly-" + k} ref=${n === 0 ? first : undefined} type="number"
      min=${min} max=${max} step=${step} value=${vals[k]} onInput=${(e) => change(k, e.target.value)} /></div>`;
  return html`<section class="scenes-edit" role="group" aria-label=${d.title} onKeyDown=${onKey}>
    <span class="scenes-edit-t ellip" title=${d.title}>${d.title}</span>
    ${move ? [num("dx", "Right (px):", -4096, 4096, 1, 0), num("dy", "Down (px):", -4096, 4096, 1, 1)]
      : [num("size", "Size (%):", 25, 400, 5, 0), html`<span class="small nw">${px}</span>`]}
    <span class="grow"></span>
    <${Button} size="sm" kind="primary" onClick=${apply}>Apply<//>
    <${Button} size="sm" onClick=${cancel}>Cancel<//>
    <span class="small muted scenes-edit-n">${move ? "Negative moves the line left / up."
      : "Every line this scene draws with the same font at this size changes with it."}</span>
  </section>`;
}


// ---------------------------------------------------------------------------------------------
// PAD-251: the scene EDITOR (webui/text_scenes_tree.py).  The scene is drawn from its tree, as
// the machine draws it; every picture and line of text on the canvas can be picked, dragged,
// resized from a corner, nudged with the arrow keys, tinted, hidden, re-layered or removed.
// ---------------------------------------------------------------------------------------------
function inPoly(pts, x, y) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function TreeTop({ s, onMenu }) {
  const [view, setView] = useState("layers");
  return html`<div class="scenes-top">
    <${Seg} value=${view} onChange=${setView}
      options=${[{ value: "layers", label: "Layers" }, { value: "contents", label: "Contents" }]} />
    ${view === "layers" ? html`<${TreeLayers} t=${s.tree_view} />` : html`<${Contents} s=${s} onMenu=${onMenu} />`}
  </div>`;
}

// Ctrl (Cmd on a Mac) adds a layer to the selection or takes it out; Shift selects a run of
// them in the Layers list (PAD-279).
const pickHow = (e, range) => (range && e.shiftKey ? "range" : e.ctrlKey || e.metaKey || e.shiftKey ? "add" : "");

function TreeLayers({ t }) {
  const listRef = useRef(null);
  const sels = t.sels || [];
  useEffect(() => {
    if (t.sel == null || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-node="${t.sel}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [t.sel]);
  return html`<div class="scenes-contents tree-layers" ref=${listRef} role="tree" aria-label="Layers">
    <div class="sc-head"><span class="eyebrow">Layers — last drawn on top</span></div>
    ${(t.layers || []).map((l) => html`<div key=${l.id} data-node=${l.id}
        class=${cx("sc-item", "ly-item", (t.sel === l.id || sels.includes(l.id)) && "sel", !l.drawn && "ly-off")}
        style=${`padding-left:${10 + l.depth * 14}px`}
        title=${!l.drawn && !l.hidden ? "Not on the screen at this moment: click to see it on top while it is selected, and edit it" : null}
        onMouseDown=${(e) => { if (e.shiftKey) e.preventDefault(); }}
        onClick=${(e) => call("text_scenes.tree_select", l.id, pickHow(e, true))}>
      <button type="button" class="ly-eye"
        title=${l.hidden ? "Hidden — show it again" : l.drawn ? "Hide it"
          : "Not on the screen at this moment: see it on top while it is selected"}
        onClick=${(e) => {
          e.stopPropagation();
          if (!l.hidden && !l.drawn) call("text_scenes.tree_select", l.id);
          else call("text_scenes.tree_visible", l.id, l.hidden);
        }}>
        <${Icon} name=${l.hidden ? "eye-off" : "eye"} /></button>
      <span class="sc-t ellip" title=${l.name}>${l.name}${l.added ? " (added)" : ""}</span>
      <span class="sc-i small muted ellip" title=${l.edits || l.kind}>${l.edits || l.kind}</span>
    </div>`)}
  </div>`;
}

// A set of pictures, handed over only once the browser has every one of them: the canvas
// swaps to a redraw when it is ready, so an edit never flashes an empty frame.
function useLoaded(srcs, key) {
  const [got, setGot] = useState(null);
  const want = (srcs || []).join("|");
  useEffect(() => {
    if (!want) { setGot(null); return undefined; }
    let dead = false;
    let left = srcs.length;
    const done = () => { if (!dead && --left === 0) setGot({ srcs, key }); };
    srcs.forEach((p) => {
      const im = new Image();
      im.onload = done;
      im.onerror = done;
      im.src = mediaUrl(p);
    });
    return () => { dead = true; };
  }, [want]);
  return got;
}

// A drag or a nudge as SVG (stage units) and CSS (a picture as big as the canvas) transforms.
// Lists are newest first: a transform list applies its LAST entry first.
function svgTf(ops) {
  return ops.map((o) => (o.m === "move" ? `translate(${o.dx} ${o.dy})`
    : `translate(${o.cx} ${o.cy}) scale(${o.f}) translate(${-o.cx} ${-o.cy})`)).join(" ");
}
function cssTf(ops, W, H) {
  const px = (x) => (100 * x) / W + "%", py = (y) => (100 * y) / H + "%";
  return ops.map((o) => (o.m === "move" ? `translate(${px(o.dx)}, ${py(o.dy)})`
    : `translate(${px(o.cx)}, ${py(o.cy)}) scale(${o.f}) translate(${px(-o.cx)}, ${py(-o.cy)})`)).join(" ");
}

// The scene's animation playing (tree_play): its frames drawn on the server one after another
// and played here at the scene's own rate, looping; a frame not drawn yet holds the last one.
// Each frame is loaded the moment it is drawn and painted on a canvas only once it has loaded:
// swapping an <img>'s src at 30 fps showed the old picture while the new one loaded, so a
// slower machine saw about one frame in five (PAD-261, DragonRR: "plays 22 of the 120").
function TreePlayer({ s, onFrame }) {
  const play = s.tree_play;
  const t = s.tree_view;
  const W = t.stage[0], H = t.stage[1];
  const [f, setF] = useState(0);
  const [shown, setShown] = useState(false);
  const cvRef = useRef(null);
  const imgs = useRef(new Map());                    // frame file -> its Image, loading
  const playRef = useRef(play);
  playRef.current = play;
  useEffect(() => {
    for (const src of play.srcs || []) {
      if (src && !imgs.current.has(src)) {
        const im = new Image();
        im.src = mediaUrl(src);
        imgs.current.set(src, im);
      }
    }
  }, [play.srcs]);
  useEffect(() => {
    let i = 0;
    const ms = Math.max(15, Math.round(1000 / (play.fps || 30)));
    const timer = setInterval(() => {
      const p = playRef.current;
      const want = (p.map || [])[i];
      if (want == null) {                           // not drawn yet: hold
        if (p.done) i = 0;                          // (a play cut short loops what it has)
        return;
      }
      const src = (p.srcs || [])[want] || "";
      const im = src ? imgs.current.get(src) : null;
      if (src && !(im && im.complete && im.naturalWidth > 0)) return;  // still loading: hold
      const cv = cvRef.current;
      if (im && cv) {                               // (a frame that failed to draw: skipped)
        if (cv.width !== im.naturalWidth || cv.height !== im.naturalHeight) {
          cv.width = im.naturalWidth;
          cv.height = im.naturalHeight;
        }
        cv.getContext("2d").drawImage(im, 0, 0);
        cv.setAttribute("data-src", src);
        setShown(true);
      }
      setF(i);
      onFrame(i + 1);
      i = (i + 1) % p.frames;
    }, ms);
    return () => clearInterval(timer);
  }, [play.run, play.fps, play.frames]);
  return html`<div class="scenes-canvas tree-canvas" style=${`background:${s.bg_rgb || "#101014"};aspect-ratio:${W} / ${H}`}>
    <canvas class="tree-frame" ref=${cvRef} style=${shown ? "" : "visibility:hidden"}></canvas>
    ${shown ? null : html`<${Drawing} label="Drawing the frames…" />`}
    <div class="tree-playing small">Frame ${f + 1} of ${play.frames}</div>
  </div>`;
}

function TreeCanvas({ s }) {
  const t = s.tree_view;
  const W = t.stage[0], H = t.stage[1];
  // the scene's picture, and the selection's layers (what is under it, it, what is over it),
  // which let a drag move the selection's own pixels before the scene is drawn again
  const full = useLoaded((s.frames || []).slice(0, 1), s.tree_img_rev || 0);
  const L = s.tree_layers;
  const lay = useLoaded(L ? [L.under, L.sel, L.over] : [], L ? `${L.node}:${s.tree_img_rev || 0}` : null);
  const shownRev = full ? full.key : -1;
  const box = useRef(null);
  const [drag, setDrag] = useState(null);
  // edits made on the canvas whose redraw has not come back yet: {id, ops: [{m, ..., want}]},
  // newest first.  *want* is the edit count that draws it (null: a nudge not sent yet).
  const [pend, setPend] = useState(null);
  const pendRef = useRef(null);
  pendRef.current = pend;
  const wantRef = useRef(0);
  const nudgeT = useRef(null);
  const [hover, setHover] = useState(null);
  const p = t.props;
  // the selection (PAD-279: several at once): what a drag, the arrow keys and Delete act on.
  // *key* names it for the edits shown by hand and the layers the server draws for it.
  const sels = p ? ((t.sels || []).length ? t.sels : [p.id]) : [];
  const multi = sels.length > 1;
  const keyOf = (ids) => ids.join(",");
  const moveCall = (ids, dx, dy) => (ids.length > 1 ? call("text_scenes.tree_move_many", ids, dx, dy)
    : call("text_scenes.tree_move", ids[0], dx, dy));
  useEffect(() => { setPend(null); setDrag(null); }, [t.card]);
  // a redraw came in: the edits it draws are no longer shown by hand
  useEffect(() => {
    setPend((q) => {
      if (!q) return q;
      const ops = q.ops.filter((o) => o.want == null || o.want > shownRev);
      return ops.length ? (ops.length === q.ops.length ? q : { ...q, ops }) : null;
    });
  }, [shownRev]);
  useEffect(() => () => clearTimeout(nudgeT.current), []);

  const send = (ids, op, fn) => {
    const id = keyOf(ids);
    wantRef.current = Math.max(wantRef.current, t.rev || 0) + 1;
    const w = wantRef.current;
    setPend((q) => ({ id, ids, ops: [{ ...op, want: w }, ...(q && q.id === id ? q.ops : [])] }));
    const drop = () => setPend((q) => {
      if (!q) return q;
      const ops = q.ops.filter((o) => o.want !== w);
      return ops.length ? { ...q, ops } : null;
    });
    Promise.resolve(fn()).then((ok) => { if (ok === false) drop(); }, drop);
  };
  const flushNudge = () => {
    clearTimeout(nudgeT.current);
    const q = pendRef.current;
    const head = q && q.ops[0];
    if (!head || head.want != null) return;
    wantRef.current = Math.max(wantRef.current, t.rev || 0) + 1;
    const w = wantRef.current;
    const id = q.id, ids = q.ids, dx = head.dx, dy = head.dy;
    setPend((r) => (r && r.id === id && r.ops[0] && r.ops[0].want == null
      ? { ...r, ops: [{ ...r.ops[0], want: w }, ...r.ops.slice(1)] } : r));
    const drop = () => setPend((r) => {
      if (!r) return r;
      const ops = r.ops.filter((o) => o.want !== w);
      return ops.length ? { ...r, ops } : null;
    });
    moveCall(ids, dx, dy).then((ok) => { if (ok === false) drop(); }, drop);
  };
  // arrow keys: shown at once, sent as one move when the keys rest
  const nudge = (ids, dx, dy) => {
    const id = keyOf(ids);
    if (pendRef.current && pendRef.current.id !== id) flushNudge();
    setPend((q) => {
      const ops = q && q.id === id ? q.ops : [];
      const head = ops[0];
      if (head && head.want == null) return { id, ids, ops: [{ ...head, dx: head.dx + dx, dy: head.dy + dy }, ...ops.slice(1)] };
      return { id, ids, ops: [{ m: "move", dx, dy, want: null }, ...ops] };
    });
    clearTimeout(nudgeT.current);
    nudgeT.current = setTimeout(flushNudge, 350);
  };

  const toStage = (e) => {
    const r = box.current.getBoundingClientRect();
    return [((e.clientX - r.left) * W) / r.width, ((e.clientY - r.top) * H) / r.height];
  };
  const pick = (x, y) => {
    const hits = t.hits || [];
    for (let i = hits.length - 1; i >= 0; i--) if (inPoly(hits[i].pts, x, y)) return hits[i];
    return null;
  };
  const selBox = p && !multi && p.x != null ? { x: p.x, y: p.y, w: p.w, h: p.h } : null;
  const corner = (x, y) => {
    if (!selBox) return null;
    const r = box.current.getBoundingClientRect();
    const tol = (10 * W) / r.width;
    for (const [cx0, cy0] of [[selBox.x, selBox.y], [selBox.x + selBox.w, selBox.y],
      [selBox.x, selBox.y + selBox.h], [selBox.x + selBox.w, selBox.y + selBox.h]]) {
      if (Math.abs(x - cx0) < tol && Math.abs(y - cy0) < tol) return true;
    }
    return false;
  };
  const down = (e) => {
    if (e.button !== 0) return;
    flushNudge();
    const [x, y] = toStage(e);
    box.current.setPointerCapture(e.pointerId);
    if (corner(x, y)) {
      const cx0 = selBox.x + selBox.w / 2, cy0 = selBox.y + selBox.h / 2;
      setDrag({ mode: "scale", id: String(p.id), node: p.id, cx: cx0, cy: cy0, d0: Math.hypot(x - cx0, y - cy0) || 1, f: 1 });
      return;
    }
    const h = pick(x, y);
    const how = pickHow(e, false);
    if (!h) { if (!how) call("text_scenes.tree_select", null); setDrag(null); return; }
    if (how) { call("text_scenes.tree_select", h.id, how); setDrag(null); return; }
    // a picture already in a selection of several drags them all
    const ids = multi && sels.includes(h.id) ? sels : [h.id];
    if (!p || (ids.length === 1 && h.id !== p.id)) call("text_scenes.tree_select", h.id);
    setDrag({ mode: "move", id: keyOf(ids), ids, x0: x, y0: y, dx: 0, dy: 0 });
  };
  const move = (e) => {
    const [x, y] = toStage(e);
    if (!drag) { const h = pick(x, y); setHover(h ? h.id : null); return; }
    if (drag.mode === "move") setDrag({ ...drag, dx: x - drag.x0, dy: y - drag.y0 });
    else setDrag({ ...drag, f: Math.max(0.05, Math.hypot(x - drag.cx, y - drag.cy) / drag.d0) });
  };
  const up = () => {
    const d = drag;
    setDrag(null);
    if (!d) return;
    if (d.mode === "move" && Math.abs(d.dx) + Math.abs(d.dy) >= 1) {
      const dx = Math.round(d.dx), dy = Math.round(d.dy);
      send(d.ids, { m: "move", dx, dy }, () => moveCall(d.ids, dx, dy));
    }
    if (d.mode === "scale" && Math.abs(d.f - 1) > 0.01)
      send([d.node], { m: "scale", cx: d.cx, cy: d.cy, f: d.f }, () => call("text_scenes.tree_scale", d.node, d.f));
  };
  const key = (e) => {
    if (!p) return;
    const step = e.shiftKey ? 10 : 1;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) { e.preventDefault(); nudge(sels, ...moves[e.key]); }
    else if (e.key === "Delete") {
      e.preventDefault(); flushNudge();
      if (multi) call("text_scenes.tree_remove_many", sels); else call("text_scenes.tree_remove", p.id);
    }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); flushNudge(); call("text_scenes.tree_undo"); }
  };

  // what is moved by hand: the drag under way, then edits not yet drawn (on the picture) or
  // not yet in the outlines the page was sent (on the outline)
  const live = drag ? drag.id : pend ? pend.id : null;
  const dragOp = drag ? (drag.mode === "move" ? { m: "move", dx: drag.dx, dy: drag.dy }
    : { m: "scale", cx: drag.cx, cy: drag.cy, f: drag.f }) : null;
  const opsSince = (rev) => [...(dragOp ? [dragOp] : []),
    ...(pend && pend.id === live ? pend.ops.filter((o) => o.want == null || o.want > rev) : [])];
  const imgOps = opsSince(shownRev);
  const lineOps = opsSince(t.rev || 0);
  const layered = imgOps.length > 0 && lay && lay.key === `${live}:${shownRev}`;
  const loading = s.tree_loading || (!full && !s.canvas_msg);
  const busy = !loading && (s.tree_busy || !!(pend && pend.ops.some((o) => o.want == null || o.want > shownRev)));
  const hov = hover != null && !sels.includes(hover) ? (t.hits || []).filter((h) => h.id === hover) : [];
  const selPolys = (t.hits || []).filter((h) => sels.includes(h.id));
  return html`<div class=${cx("scenes-canvas tree-canvas", loading && "loading")} ref=${box} tabIndex="0" onKeyDown=${key}
      style=${`background:${s.bg_rgb || "#101014"};aspect-ratio:${W} / ${H}`}
      onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerLeave=${() => setHover(null)}>
    ${loading ? html`<${Drawing} />`
      : layered ? html`
        <img src=${mediaUrl(lay.srcs[0])} alt="" draggable="false" />
        <img src=${mediaUrl(lay.srcs[1])} alt="" draggable="false" class="tree-live" style=${`transform:${cssTf(imgOps, W, H)}`} />
        <img src=${mediaUrl(lay.srcs[2])} alt="" draggable="false" />`
      : full ? html`<img src=${mediaUrl(full.srcs[0])} alt="" draggable="false" />`
      : html`<span class="scenes-msg">${s.canvas_msg}</span>`}
    ${loading ? null : html`<svg viewBox=${`0 0 ${W} ${H}`} preserveAspectRatio="none" class="tree-svg">
      ${hov.map((h, i) => html`<polygon key=${"h" + i} points=${h.pts.map((q) => q.join(",")).join(" ")} class="tree-hover" />`)}
      <g transform=${svgTf(lineOps)}>
        ${selPolys.map((h, i) => html`<polygon key=${"s" + i} points=${h.pts.map((q) => q.join(",")).join(" ")} class="tree-sel" />`)}
        ${selBox ? html`<rect x=${selBox.x} y=${selBox.y} width=${selBox.w} height=${selBox.h} class="tree-box" />` : null}
        ${multi ? (t.sel_boxes || []).map(([bx, by, bw, bh], i) =>
          html`<rect key=${"b" + i} x=${bx} y=${by} width=${bw} height=${bh} class="tree-box" />`) : null}
        ${selBox ? [[selBox.x, selBox.y], [selBox.x + selBox.w, selBox.y], [selBox.x, selBox.y + selBox.h],
          [selBox.x + selBox.w, selBox.y + selBox.h]].map(([hx, hy], i) =>
          html`<rect key=${"k" + i} x=${hx - 7} y=${hy - 7} width="14" height="14" class="tree-handle" />`) : null}
      </g>
    </svg>`}
    ${busy ? html`<div class="tree-busy" role="status"><${Spinner} /><span>Updating</span></div>` : null}
  </div>`;
}

function TreeSide({ t, play, playFrame }) {
  const p = t.props;
  const [tint, setTint] = useState(p ? p.tint : "#ffffff");
  const [keepShape, setKeepShape] = useState(true);
  useEffect(() => { if (p) setTint(p.tint); }, [p && p.id, p && p.tint]);
  const num = (label, value, onCommit, title) => html`<label class="tree-num" ...${tip(title)}>
    <span class="lbl">${label}</span>
    <div class="field sm"><input type="number" value=${value ?? ""} onChange=${(e) => onCommit(e.target.value)} /></div>
  </label>`;
  return html`<div class="tree-side">
    <span class="eyebrow">Moment</span>
    <${Select} sm value=${t.moment} options=${t.moments} onChange=${(v) => call("text_scenes.tree_moment", v)}
      title="Which moment of the scene's timeline to show: where it rests, or one of its own labels." />
    <div class="scenes-ctl">
      <span class="lbl">Frame</span>
      <div class="field sm" style="width:84px"><input type="number" min="1" max=${t.frames}
        value=${playFrame || t.frame} disabled=${!!play}
        onChange=${(e) => call("text_scenes.tree_moment", "f:" + e.target.value)} /></div>
      <span class="small muted">of ${t.frames}</span>
      ${t.frames > 1 ? html`<${Button} size="xs" kind=${play ? "primary" : ""} icon=${play ? "stop" : "play"}
        title=${play ? "Stop, and go back to the frame you were on" : "Play the scene's animation at its own speed (it loops)"}
        onClick=${() => call("text_scenes.tree_play", !play)}>${play ? "Stop" : "Play"}<//>` : null}
    </div>
    ${play && !play.done ? html`<span class="small muted">${(play.map || []).length ? `Drawing frame ${play.map.length} of ${play.frames}…` : "Working out the frames…"}</span>` : null}
    ${(t.states || []).length ? html`<details class="tree-states">
      <summary class="small">States the game picks (${t.states.length})</summary>
      ${t.states.map((st) => html`<label key=${st.node} class="tree-state" title=${st.path}>
        <span class="small ellip">${st.name}</span>
        <${Select} sm value=${st.value} options=${st.options} onChange=${(v) => call("text_scenes.tree_state", st.node, v)} />
      </label>`)}
    </details>` : null}
    <span class="eyebrow">Selected</span>
    ${p && (t.sels || []).length > 1 ? html`<div class="tree-props">
      <div class="small"><b>${t.sels.length} selected</b></div>
      <div class="small muted">Drag any of them on the preview, or use the arrow keys, to move them together. Ctrl-click one to take it out; click one on its own to pick just that.</div>
      <div class="tree-row">
        <${Button} size="xs" title="Hide every selected layer" onClick=${() => call("text_scenes.tree_visible_many", t.sels, false)}>Hide<//>
        <${Button} size="xs" title="Show every selected layer again" onClick=${() => call("text_scenes.tree_visible_many", t.sels, true)}>Show<//>
      </div>
    </div>`
    : p ? html`<div class="tree-props">
      <div class="small ellip" title=${p.name}><b>${p.name}</b> <span class="muted">${p.kind}${p.added ? ", added" : ""}</span></div>
      ${p.peek ? html`<div class="small muted">The game does not draw this at this moment. It is shown on top while it is selected; an edit holds wherever the game shows it.</div>` : null}
      ${p.x != null ? html`<div class="tree-row">
        ${num("X", p.x, (v) => call("text_scenes.tree_move", p.id, Number(v) - p.x, 0), "Left edge on the glass (px)")}
        ${num("Y", p.y, (v) => call("text_scenes.tree_move", p.id, 0, Number(v) - p.y), "Top edge on the glass (px)")}
      </div>` : html`<div class="small muted">Not on the glass at this moment.</div>`}
      ${p.w != null ? html`<div class="tree-row">
        ${num("W px", p.w, (v) => call("text_scenes.tree_set_pixels", p.id, v, null, keepShape), "Its width on the screen, in pixels (the screen is 1360 x 768)")}
        ${num("H px", p.h, (v) => call("text_scenes.tree_set_pixels", p.id, null, v, keepShape), "Its height on the screen, in pixels")}
      </div>
      <label class="tree-row small tree-keep" title="On: a new width or height resizes it both ways, so it keeps its shape. Off: it stretches one way only.">
        <input type="checkbox" checked=${keepShape} onChange=${(e) => setKeepShape(e.target.checked)} /> Keep its shape
      </label>` : null}
      <div class="tree-row">
        ${num("Size %", p.scale === p.scale_y ? p.scale : "", (v) => call("text_scenes.tree_set_scale", p.id, v), "Both ways at once; 100 = the size the game ships")}
      </div>
      <div class="tree-row">
        ${num("Width %", p.scale, (v) => call("text_scenes.tree_set_size", p.id, v, null), "Stretch it sideways only")}
        ${num("Height %", p.scale_y, (v) => call("text_scenes.tree_set_size", p.id, null, v), "Stretch it up and down only")}
      </div>
      <div class="tree-row">
        ${num("Turn °", p.rotate, (v) => call("text_scenes.tree_set_rotation", p.id, v), "How far it is turned from as shipped, in degrees clockwise (0 = as shipped)")}
        <${Button} size="xs" title="Turn it 90° anticlockwise" onClick=${() => call("text_scenes.tree_rotate", p.id, -90)}>⟲ 90°<//>
        <${Button} size="xs" title="Turn it 90° clockwise" onClick=${() => call("text_scenes.tree_rotate", p.id, 90)}>⟳ 90°<//>
      </div>
      <div class="tree-row">
        <span class="lbl">Tint</span>
        <input type="color" class="tree-color" value=${tint} onInput=${(e) => setTint(e.target.value)}
          onChange=${(e) => call("text_scenes.tree_tint", p.id, e.target.value, p.alpha)} aria-label="Tint" />
        ${num("Opacity %", p.alpha, (v) => call("text_scenes.tree_tint", p.id, tint, v), "100 = as shipped")}
      </div>
      <div class="tree-row">
        <${Button} size="xs" onClick=${() => call("text_scenes.tree_visible", p.id, p.hidden)}>${p.hidden ? "Show" : "Hide"}<//>
        <${Button} size="xs" title="Draw it above the next layer" onClick=${() => call("text_scenes.tree_order", p.id, "up")}>Forward<//>
        <${Button} size="xs" title="Draw it below the layer before it" onClick=${() => call("text_scenes.tree_order", p.id, "down")}>Back<//>
        <span class="small muted">layer ${p.layer}/${p.layers}</span>
      </div>
      <div class="tree-row">
        <${Button} size="xs" onClick=${() => call("text_scenes.tree_order", p.id, "front")}>To front<//>
        <${Button} size="xs" onClick=${() => call("text_scenes.tree_order", p.id, "back")}>To back<//>
        <${Button} size="xs" onClick=${() => call("text_scenes.tree_reset", p.id)}>${p.added ? "Remove" : "As shipped"}<//>
      </div>
      ${p.kind === "Text" ? html`<div class="tree-row">
        <${Button} size="xs" title="A dark copy of this text just beneath it, a few pixels down and right. It is selected after, to move, tint or remove."
          onClick=${() => call("text_scenes.tree_shadow", p.id)}>Add a drop shadow<//>
      </div>` : null}
    </div>` : html`<div class="small muted">Click a picture or a line of text in the preview, or a row in Layers. Ctrl-click (or Shift-click) to pick several and move them together.</div>`}
    ${(t.notes || []).length ? html`<div class="small warn-ink">${t.notes.join("; ")}</div>` : null}
  </div>`;
}

// The whole scene's actions, in the bar under the preview: add a picture or a line of text,
// undo, put the scene back as shipped.
function TreeActions({ t }) {
  const [adding, setAdding] = useState(false);
  const [words, setWords] = useState("");
  return html`<div class="row tree-actions">
    <${Button} size="sm" kind="ghost" icon="plus" title="Add a picture of your own (PNG, JPG or WEBP) to this scene"
      onClick=${() => call("text_scenes.tree_add_picture")}>Picture…<//>
    <${Button} size="sm" kind="ghost" icon="plus" title="Add a line of text to this scene"
      onClick=${() => { setWords(""); setAdding(true); }}>Text…<//>
    <span class="tree-actions-sep"></span>
    <${Button} size="sm" kind="ghost" icon="undo" disabled=${!t.edits} title="Undo the last edit in this scene (Ctrl+Z)"
      onClick=${() => call("text_scenes.tree_undo")}>Undo<//>
    <${Button} size="sm" kind="ghost" iconRight="down" disabled=${!t.edits && !t.all_edits}
      title="Put this scene (or every scene) back: as the last Write left it, or as the game shipped it"
      onClick=${(e) => openMenu(e.currentTarget, [
        { label: "Back to the last Write (this scene)", icon: "undo", disabled: t.built !== "changed",
          title: t.built === "none" ? "No Write has been made from this project folder yet."
            : t.built === "same" ? "Nothing in this scene has changed since the last Write."
            : "Drop every edit made to this scene since the last Write put it on a card.",
          onClick: () => call("text_scenes.tree_revert_built") },
        { label: "As shipped (this scene)", icon: "refresh", disabled: !t.edits,
          title: "Put this scene back the way the game shipped it.", onClick: () => call("text_scenes.tree_clear") },
        { sep: true },
        { label: "As shipped (every scene)…", icon: "trash", disabled: !t.all_edits,
          title: "Put every scene in this project back the way the game shipped it.",
          onClick: () => call("text_scenes.tree_clear_all") },
      ])}>Reset<//>
    ${t.built === "same" && t.edits ? html`<span class="small nw ok-ink" title=${STATE_TIP.written}><span class="sc-dot written"></span> Written to a card</span>`
      : t.edits || t.built === "changed" ? html`<span class="small nw warn-ink" title="Edits are kept as you make them; there is nothing to save. The next Write puts them on the card.">
          <span class="sc-dot edited"></span> ${t.edits ? `${t.edits} edit${t.edits === 1 ? "" : "s"}` : "Back as shipped"}, not written yet</span>` : null}
    ${adding ? html`<${Modal} title="Add a line of text" onClose=${() => setAdding(false)}
        footer=${html`<${Button} onClick=${() => setAdding(false)}>Cancel<//><${Button} kind="primary"
          disabled=${!words.trim()} onClick=${() => { setAdding(false); call("text_scenes.tree_add_text", words); }}>Add<//>`}>
      <p class="small muted" style="margin-top:0">Written in the font and size of the selected line (or the scene's first one), in the middle of the screen: drag it where you want it.</p>
      <${Field} value=${words} onChange=${setWords} placeholder="Words" />
    <//>` : null}
  </div>`;
}
