// The scenes ("what each scene is made of") and the scene editor (PAD-251).  A page of its
// own now, the Scenes tab (tabs/scenes.js hosts ScenesPage); it was a floating window.
// Python: webui/text_scenes.py (ns "text_scenes").

import { html, useState, useEffect, useLayoutEffect, useRef, Button, Field, Select, Seg, Table, Modal, openMenu, InfoBadge, Check,
         Icon, Progress, Spinner, tip, call, mediaUrl, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { LookRow } from "../core/look.js";

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
// The preview's magnifier (PAD-282): 1 = the whole screen fits the room, more = bigger, and the
// stage scrolls.  Ctrl or Shift + the wheel zooms about the pointer; the buttons about the middle.
const ZOOM_MAX = 8;
const ZOOM_STEPS = [1, 1.25, 1.5, 2, 3, 4, 6, 8];
const clampZoom = (z) => Math.max(1, Math.min(ZOOM_MAX, z));
function useStageZoom() {
  const [zoom, setZoom] = useState(1);
  const ref = useRef(null);                     // the .scenes-stage (the part that scrolls)
  const zoomRef = useRef(1);
  zoomRef.current = zoom;
  const anchor = useRef(null);                  // where the zoom holds still: {fx, fy, px, py}
  // zoom to *z*, keeping the point under (clientX, clientY) (the middle without) where it is
  const zoomTo = (z, at) => {
    const el = ref.current;
    const c = el && el.firstElementChild;
    z = clampZoom(Math.round(z * 100) / 100);
    if (!el || !c || z === zoomRef.current) return;
    const r = el.getBoundingClientRect(), cr = c.getBoundingClientRect();
    const x = at ? at[0] : r.left + r.width / 2, y = at ? at[1] : r.top + r.height / 2;
    const frac = (v, lo, len) => (len ? Math.max(0, Math.min(1, (v - lo) / len)) : 0.5);
    anchor.current = { fx: frac(x, cr.left, cr.width), fy: frac(y, cr.top, cr.height), px: x - r.left, py: y - r.top };
    setZoom(z);
  };
  const step = (dir) => {
    const z = zoomRef.current;
    zoomTo(dir > 0 ? ZOOM_STEPS.find((v) => v > z + 0.01) || ZOOM_MAX
      : [...ZOOM_STEPS].reverse().find((v) => v < z - 0.01) || 1);
  };
  useLayoutEffect(() => {
    const el = ref.current, a = anchor.current;
    anchor.current = null;
    const c = el && el.firstElementChild;
    if (!a || !c) return;
    const r = el.getBoundingClientRect(), cr = c.getBoundingClientRect();
    const k = r.width ? el.offsetWidth / r.width : 1;     // screen px -> page px (the app can be zoomed)
    el.scrollLeft += (cr.left + a.fx * cr.width - (r.left + a.px)) * k;
    el.scrollTop += (cr.top + a.fy * cr.height - (r.top + a.py)) * k;
  }, [zoom]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const wheel = (e) => {
      if (!e.ctrlKey && !e.shiftKey && !e.metaKey) return;
      e.preventDefault();
      // (Shift + the wheel comes in sideways on Windows)
      const d = e.deltaY || e.deltaX;
      if (d) zoomTo(zoomRef.current * Math.exp(-d * (e.deltaMode === 1 ? 0.05 : 0.0015)), [e.clientX, e.clientY]);
    };
    // the middle button drags the view about when it is zoomed
    let pan = null;
    const down = (e) => {
      if (e.button !== 1 || zoomRef.current <= 1) return;
      e.preventDefault();
      pan = { x: e.clientX, y: e.clientY, l: el.scrollLeft, t: el.scrollTop };
      el.setPointerCapture(e.pointerId);
    };
    const move = (e) => {
      if (!pan) return;
      const r = el.getBoundingClientRect(), k = r.width ? el.offsetWidth / r.width : 1;
      el.scrollLeft = pan.l - (e.clientX - pan.x) * k;
      el.scrollTop = pan.t - (e.clientY - pan.y) * k;
    };
    const up = () => { pan = null; };
    el.addEventListener("wheel", wheel, { passive: false });
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    return () => {
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
  }, []);
  return { zoom, ref, zoomTo, step };
}

function ZoomControls({ z }) {
  const pct = Math.round(z.zoom * 100);
  return html`<div class="row scenes-zoom" role="group" aria-label="Zoom">
    <${Button} size="xs" kind="ghost" icon="zoomout" disabled=${z.zoom <= 1} title="Zoom out (or Ctrl + the mouse wheel)"
      onClick=${() => z.step(-1)} />
    <span class="small muted scenes-zoom-pct" title="How big the preview is drawn: 100% = the whole screen fits">${pct}%</span>
    <${Button} size="xs" kind="ghost" icon="zoomin" disabled=${z.zoom >= ZOOM_MAX} title="Zoom in (or Ctrl + the mouse wheel over the spot to look at)"
      onClick=${() => z.step(1)} />
    <${Button} size="xs" kind="ghost" icon="fit" disabled=${z.zoom <= 1} title="Back to the whole screen"
      onClick=${() => z.zoomTo(1)} />
  </div>`;
}

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

// The page head's buttons (Export picture… / Export video…, Export all pictures…, Export all
// videos…, Re-read from card…): none of them is needed to keep an edit (edits are kept as they
// are made; Write puts them on the card).  PAD-365: a scene that moves exports as a video, and
// "Export all videos…" writes one MP4 per listed scene; the message beside the buttons follows
// an export along and says what it wrote.
export function ScenesActions() {
  const s = useNs("text_scenes");
  if (!s.alive) return null;
  const tips = s.tips || {};
  const any = !!(s.scenes || []).length;
  return html`
    ${s.rebuild_msg ? html`<span class="small muted scenes-msg-head">${s.rebuild_msg}</span>` : null}
    ${!s.rebuild_msg && s.export_msg ? html`<span class="small muted scenes-msg-head" title=${s.export_msg}>${s.export_msg}</span>` : null}
    <${Button} kind="ghost" icon=${s.can_video ? "video" : "download"} disabled=${!s.can_save && !s.exporting}
      title=${tips.save} onClick=${() => call("text_scenes.save_preview")}>${s.exporting ? "Cancel" : s.can_video ? "Export video…" : "Export picture…"}<//>
    <${Button} kind="ghost" title=${tips.save_all} disabled=${(!any && !s.bulk) || s.bulk_video}
      onClick=${() => call("text_scenes.save_all")}>${s.bulk ? "Cancel" : "Export all pictures…"}<//>
    <${Button} kind="ghost" icon="video" title=${tips.save_all_video} disabled=${(!any && !s.bulk_video) || s.bulk}
      onClick=${() => call("text_scenes.save_all_videos")}>${s.bulk_video ? "Cancel" : "Export all videos…"}<//>
    <${Button} kind="ghost" iconRight="down" disabled=${!(s.scenes || []).length}
      title="Save your scene edits to a file, to keep as a backup or send to someone, and load a file of scene edits into this project"
      onClick=${(e) => openMenu(e.currentTarget, [
        { label: "Save this scene's edits to a file…", icon: "download", disabled: !(s.tree_view || {}).edits,
          title: "The moves, resizes, tints, hidden layers and added pictures and text of this scene, in one .zip file",
          onClick: () => call("text_scenes.edits_save", "this") },
        { label: "Save every scene's edits to a file…", icon: "download", disabled: !(s.tree_view || {}).all_edits,
          title: "The edits of every scene you changed in this project, in one .zip file",
          onClick: () => call("text_scenes.edits_save", "all") },
        { sep: true },
        { label: "Load scene edits from a file…", icon: "upload",
          title: "Put the edits in a file saved here or by someone else onto the same scenes of this card. A scene this card does not have is left out.",
          onClick: () => call("text_scenes.edits_load") },
      ])}>Save / load edits<//>
    <${Button} kind="ghost" icon=${s.rebuilding ? "x" : "refresh"} title=${tips.rebuild}
      onClick=${() => call("text_scenes.rebuild")}>${s.rebuilding ? "Cancel" : "Re-read from card…"}<//>`;
}

// colorsOpen / openColors(mode): the Color profiles bar on the page's edge (PAD-350,
// scenes.js); while it is open the scene list steps aside unless shown again
export function ScenesPage({ colorsOpen = false, openColors } = {}) {
  const s = useNs("text_scenes");
  const [color, setColor] = useState(null);     // {text, start, stock, title}
  const [wideOwn, setWideOwn] = useState(false); // the scene editor without the scene list
  const [listWithColors, setListWithColors] = useState(false);
  const wide = colorsOpen ? !listWithColors : wideOwn;
  const setWide = (v) => (colorsOpen ? setListWithColors(!v) : setWideOwn(v));
  const [playFrame, setPlayFrame] = useState(0); // the frame a playback is on
  useEffect(() => { if (!s.tree_play) setPlayFrame(0); }, [s.tree_play]);
  const [split, setSplit] = useState(loadSplit);
  const zoom = useStageZoom();
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
  // PAD-349 (DragonRR): the advanced unlock sits beside Preview colors, not in the Layers head
  const unlock = editor ? s.tree_view.color_unlock : null;
  // The page is one screen tall: the scene list, the preview (as big as the room lets it be,
  // width AND height) and the inspector side by side, each scrolling on its own.
  return html`<section class="card scenes-card">
    <div class=${cx("scenes-body", wide && "wide")} ref=${bodyRef} style=${bodyStyle}>
      ${wide ? html`<button type="button" class="sc-list-tab" onClick=${() => setWide(false)}
          aria-label="Show the scene list" ...${tip("Show the scene list")}>
        <${Icon} name="right" /><span class="sc-list-tab-txt">Scenes</span><${Icon} name="right" /></button>` : null}
      <div class="scenes-left">
        <div class="row scenes-search">
          <${Field} sm value=${s.search} placeholder="Search" onChange=${(v) => call("text_scenes.set_search", v)}
            delay=${200} prefix=${html`<${Icon} name="search" />`} />
          <${InfoBadge} text=${s.hint} />
          <${Button} size="sm" icon="left" cls="sc-list-hide" label="Hide the scene list"
            title="Hide the scene list: more room for the preview (the Scenes tab on the left brings it back)"
            onClick=${() => setWide(true)} />
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
      <div class="scenes-center" onPointerDown=${editor ? (e) => deselectOnBlank(s.tree_view, e) : null}>
        ${[s.card_note, editor && s.pic_note].filter(Boolean).map((t, i) => html`<div key=${"w" + i}
          class="note warn scenes-warn" role="status"><${Icon} name="warn" /><div class="body-text small">${t}</div></div>`)}
        ${editor && s.mode_layout && s.mode_layout.scene_dir === s.sel ? html`<div class="note scenes-warn scenes-modelay" role="status">
          <${Icon} name="info" /><div class="body-text small grow">Laying out <b>${s.mode_layout.mode}</b>'s screen: drag the
            picture or its words, size them, and Send to back to put the screen under the HUD's own pictures.
            Saved into the mode as you go${s.mode_layout.under ? " (now under the HUD)" : ""}.</div>
          ${s.mode_layout.laid_out ? html`<${Button} size="xs" kind="ghost" title="Back to where the app places it by itself"
            onClick=${() => call("text_scenes.mode_layout_auto")}>Place automatically<//>` : null}
          <${Button} size="xs" onClick=${() => call("text_scenes.mode_layout_done")}>Done<//></div>` : null}
        <div class=${cx("scenes-stage", zoom.zoom > 1 && "zoomed")} ref=${zoom.ref}
          style=${`--ar:${stage[0] / stage[1]};--z:${zoom.zoom}`}>
          ${s.preparing ? html`<${Preparing} p=${s.preparing} />`
            : editor && s.tree_play ? html`<${TreePlayer} s=${s} onFrame=${setPlayFrame} />`
            : editor ? html`<${TreeCanvas} s=${s} />` : html`<${Preview} s=${s} tip=${tips.preview} />`}
        </div>
        <div class="scenes-stagebar">
          <${Button} size="sm" kind="ghost" icon=${wide ? "right" : "left"} label=${wide ? "Show the scene list" : "Hide the scene list"}
            title=${wide ? "Show the scene list" : "Hide the scene list: more room for the preview"} onClick=${() => setWide(!wide)} />
          <${ZoomControls} z=${zoom} />
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
        <div class="scenes-lookbar">
          <${LookRow} look=${s.look} ns="text_scenes" note=${false} onOpen=${openColors} />
          ${unlock && unlock.offered ? html`<div class=${cx("scenes-unlock", unlock.on && "on")} ...${tip(UNLOCK_TIP)}>
            <span class="look-head">Advanced</span>
            <${Check} checked=${!!unlock.on} onChange=${(v) => call("text_scenes.tree_color_unlocked", v)}
              label="Unlock extracted images" cls="small" /></div>` : null}
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
    <div class="sc-views"><${Seg} value=${view} onChange=${setView} options=${[
      { value: "layers", label: html`<${Icon} name="scenes" />Layers`,
        title: "Every part of the scene, in the order it is drawn: pick, hide or edit them" },
      { value: "contents", label: html`<${Icon} name="list" />Contents`,
        title: "The pictures, fonts and text this scene uses: double-click one to find it on its own tab" }]} /></div>
    ${view === "layers" ? html`<${TreeLayers} t=${s.tree_view} />` : html`<${Contents} s=${s} onMenu=${onMenu} />`}
  </div>`;
}

// Ctrl (Cmd on a Mac) adds a layer to the selection or takes it out; Shift selects a run of
// them in the Layers list (PAD-279).
const pickHow = (e, range) => (range && e.shiftKey ? "range" : e.ctrlKey || e.metaKey || e.shiftKey ? "add" : "");

// PAD-294 (DragonRR): a plain click on the empty room around the picture, or below the rows
// in Layers, drops the selection (a selected layer is drawn on top until then).  A click on
// a control, the picture itself or a scrollbar is left alone.
const BLANK_SKIP = ".tree-canvas, .sc-item, button, input, select, textarea, a, label, [role=button], [role=listbox], .field, .scenes-edit";
function deselectOnBlank(t, e) {
  if (!t || e.button !== 0 || pickHow(e, false) || (t.sel == null && !(t.sels || []).length)) return;
  const el = e.target;
  if (!el || !el.closest || el.closest(BLANK_SKIP)) return;
  const r = el.getBoundingClientRect();
  const k = (r.width ? el.offsetWidth / r.width : 1) || 1;       // the app can be zoomed
  if ((e.clientX - r.left) * k > el.clientLeft + el.clientWidth
      || (e.clientY - r.top) * k > el.clientTop + el.clientHeight) return;
  call("text_scenes.tree_select", null);
}

// PAD-293 (DragonRR): as in Photoshop or Fusion, a layer's eye is the preview only - it never
// changes the card - and Alt+click on it shows that layer alone.  Hiding a layer in the game
// is its own mark (the card at the row's end, like Fusion's Suppress): the row is struck
// through and reads "hidden in game", and the preview is not changed.  Every tooltip in a row
// is the page's own (tip()), never a title="": the browser's would come up late beside it.
const eyeTip = (l, solo) => ({
  head: solo === l.id ? "Preview: shown alone" : l.view_off ? "Preview: hidden"
    : l.state_off ? "Preview: off (its part shows another look)" : l.shown ? "Preview: turned on here" : "Preview: shown",
  lines: [
    ["Click", l.view_off ? "show it here again" : l.state_off ? "turn it on here" : l.shown ? "turn it back off"
      : "hide it here, to see or reach what is under it"],
    ["Alt+click", solo === l.id ? "bring the other layers back" : "show only this layer"],
    ["H", "hide or show the selected layers"],
    "The game is not changed.",
  ] });
const gameTip = (l) => ({
  head: l.hidden ? "Game: hidden" : "Game: shown",
  lines: l.hidden ? [
    "Write leaves it out of the card, so the machine never draws it. The preview still shows it.",
    ["Click", "put it back in the game"],
  ] : [
    ["Click", "hide it in the game (Write leaves it out of the card)"],
    ["Delete", "hide it in the game and the preview (with the preview focused)"],
    `The preview is not changed; the eye hides it here.${l.part_off ? " It shows only when the look it sits in is on." : ""}`,
  ] });
// PAD-312: a picture's colour switch - the individual files profile baked into it (green), its
// own colours (red), or the game's own picture, which has no switch (blue lock) until the
// advanced box beside Preview colors unlocks it (PAD-344; moved there in PAD-349)
const colorTip = (l, cs) => {
  const c = l.color || {};
  if (c.locked) return { head: "Color: the game's own picture", lines: [
    "Stern made it for the machine's screen, so the individual files profile is not offered on it.",
    "Replace it on the Images tab to correct a picture of your own, or tick Unlock extracted images (Advanced, beside Preview colors)." ] };
  return { head: c.on ? "Color profile attached to this file" : "No color profile attached to this file", lines: [
    layerProfile(l, cs),
    ["Click", c.on ? "detach the color profile" : "attach the color profile"],
    c.on ? "Its color profile is baked into this picture when you build; the preview shows it. Open Colors with the layer selected to give it one of its own."
      : "It goes on the card as it is.",
    c.stock ? "The game's own picture, unlocked: corrected from its original when you build, so never twice."
      : c.own ? "Set for this picture." : "Follows the Color profile tab's box for every replaced picture." ] };
};
const UNLOCK_TIP = { head: "Advanced: unlock extracted images", lines: [
  "Off: the original extracted images are locked (blue lock), so the individual files profile is never applied to them twice by accident. Pictures you replaced or added are not locked.",
  "On: each extracted image gets a red / green palette too, whatever is drawn in it now. A green one has the color profile attached: it is corrected from its original extracted copy when you build.",
  "The same box as on the Images tab. Turning it off locks them again as they were." ] };
// PAD-368: the profile a layer's picture has ("" for a layer with no colour switch)
export const layerProfile = (l, cs) => {
  const c = l.color;
  if (!c) return "";
  if (c.locked || !c.on) return "Color profile: None";
  return `Color profile: ${((cs.own_names || {}).images || {})[c.rel] || cs.asset_name || "Recommended"}`;
};
const rowTip = (l, cs) => ({
  head: `${l.name}${l.added ? " (added)" : ""}`,
  lines: [
    l.edits || l.kind,
    l.state_off ? "Off in the preview: the part it sits in shows another of its looks. Its eye turns it on here."
      : l.part_off && !l.view_off ? "The look it sits in is off in the preview: it shows when that look is on."
      : !l.drawn && !l.view_off ? "Not on the screen at this moment." : null,
    layerProfile(l, cs) || null,
    ["Click", "select it (shown on top while selected)"],
    ["Ctrl+click", "add it to the selection or take it out"],
    ["Shift+click", "select a run of layers"],
    ["Right-click", "hide, show alone, hide in the game"],
  ].filter(Boolean) });

function eyeClick(l, e) {
  e.stopPropagation();
  if (e.altKey) call("text_scenes.tree_view_solo", l.id);
  else if (l.view_off) call("text_scenes.tree_view", l.id, true);
  else if (l.state_off || l.shown) call("text_scenes.tree_force", l.id, !l.shown);
  else call("text_scenes.tree_view", l.id, false);
}

function layerMenu(t, l, e) {
  e.preventDefault();
  const sels = t.sels || [];
  const ids = sels.includes(l.id) && sels.length > 1 ? sels : [l.id];
  const many = ids.length > 1;
  const byId = Object.fromEntries((t.layers || []).map((x) => [x.id, x]));
  const allOff = ids.every((id) => (byId[id] || {}).view_off);
  const allGone = ids.every((id) => (byId[id] || {}).hidden);
  const what = many ? `the ${ids.length} selected layers` : "it";
  openMenu({ x: e.clientX, y: e.clientY }, [
    { label: allOff ? "Show in the preview" : "Hide in the preview", icon: allOff ? "eye" : "eye-off", kbd: "H",
      title: `${allOff ? "Show" : "Hide"} ${what} here only; the game is not changed`,
      onClick: () => call("text_scenes.tree_view_many", ids, allOff) },
    many ? null : { label: t.solo === l.id ? "Show every layer again" : "Show only this layer", icon: "eye", kbd: "Alt+click eye",
      title: "The preview shows this layer alone, and back again",
      onClick: () => call("text_scenes.tree_view_solo", l.id) },
    { sep: true },
    { label: allGone ? "Put back in the game" : "Hide in the game", icon: "sd",
      title: allGone ? `Write puts ${what} on the card again` : `Write leaves ${what} out of the card; the preview is not changed`,
      onClick: () => call("text_scenes.tree_visible_many", ids, allGone) },
  ].filter(Boolean));
}

function TreeLayers({ t }) {
  const cs = useNs("color");
  const listRef = useRef(null);
  const sels = t.sels || [];
  useEffect(() => {
    if (t.sel == null || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-node="${t.sel}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [t.sel]);
  // H hides or shows the selected layers in the preview, wherever the focus is on the tab
  const tRef = useRef(t);
  tRef.current = t;
  useEffect(() => {
    const onKey = (e) => {
      if (e.key.toLowerCase() !== "h" || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      const el = e.target;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      const cur = tRef.current;
      const ids = (cur.sels || []).length ? cur.sels : cur.sel != null ? [cur.sel] : [];
      if (!ids.length || !listRef.current || !listRef.current.getClientRects().length
          || document.querySelector(".scrim")) return;
      e.preventDefault();
      const off = ids.every((id) => ((cur.layers || []).find((x) => x.id === id) || {}).view_off);
      call("text_scenes.tree_view_many", ids, off);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return html`<div class="scenes-contents tree-layers" ref=${listRef} role="tree" aria-label="Layers"
      onPointerDown=${(e) => deselectOnBlank(t, e)}>
    <div class="sc-head"><span class="eyebrow">Layers — last drawn on top</span>
      ${t.solo != null ? html`<button type="button" class="ly-solo small"
        ...${tip({ head: "One layer is shown alone", lines: [["Click", "bring the other layers back"], ["Alt+click", "its eye does the same"]] })}
        onClick=${() => call("text_scenes.tree_view_solo", t.solo)}>Showing one layer · show all</button>` : null}</div>
    ${(t.layers || []).map((l) => html`<div key=${l.id} data-node=${l.id}
        class=${cx("sc-item", "ly-item", (t.sel === l.id || sels.includes(l.id)) && "sel", !l.drawn && !l.state_off && "ly-off", l.hidden && "not-in-game")}
        style=${`padding-left:${10 + l.depth * 14}px`} ...${tip(rowTip(l, cs))}
        onMouseDown=${(e) => { if (e.shiftKey) e.preventDefault(); }}
        onContextMenu=${(e) => layerMenu(t, l, e)}
        onClick=${(e) => call("text_scenes.tree_select", l.id, pickHow(e, true))}>
      <button type="button" class=${cx("ly-eye", (l.view_off || l.state_off) && "shut", t.solo === l.id && "solo")}
        aria-label="Shown in the preview" ...${tip(eyeTip(l, t.solo))} onClick=${(e) => eyeClick(l, e)}>
        <${Icon} name=${l.view_off || l.state_off ? "eye-off" : "eye"} /></button>
      <span class="sc-t ellip">${l.name}${l.added ? " (added)" : ""}</span>
      <span class=${cx("sc-i small ellip", l.hidden ? "in-game" : "muted")}>${l.edits || l.kind}</span>
      <button type="button" class=${cx("ly-game", l.hidden && "on")} aria-label="Hidden in the game"
        aria-pressed=${l.hidden ? "true" : "false"} ...${tip(gameTip(l))}
        onClick=${(e) => { e.stopPropagation(); call("text_scenes.tree_visible", l.id, l.hidden); }}>
        <${Icon} name="sd" /></button>
      ${l.color ? html`<button type="button" class=${cx("ly-color", l.color.locked ? "locked" : l.color.on ? "on" : "off")}
        aria-label="Color profile on this picture" aria-pressed=${l.color.on ? "true" : "false"} ...${tip(colorTip(l, cs))}
        onClick=${(e) => { e.stopPropagation(); if (!l.color.locked) call("text_scenes.tree_color", l.id, !l.color.on); }}>
        <${Icon} name=${l.color.locked ? "lock" : "palette"} /></button>` : html`<span></span>`}
      ${(l.pics || []).length ? html`<button type="button" class="ly-img"
        aria-label="Show on the Images tab" ...${tip(l.pics.length === 1 ? "Show this picture on the Images tab"
          : `Show one of the ${l.pics.length} pictures it draws on the Images tab`)}
        onClick=${(e) => { e.stopPropagation(); showPics(l.pics, e); }}><${Icon} name="image" /></button>`
        : html`<span></span>`}
    </div>`)}
  </div>`;
}

// PAD-287: a layer's button to its picture on the Images tab; a group that draws several
// lists them to pick from.
const MAX_PICS = 25;
function showPics(pics, e) {
  if (pics.length === 1) { call("text_scenes.activate", "img::" + pics[0]); return; }
  const items = pics.slice(0, MAX_PICS).map((rel) => ({
    label: rel.split("/").pop(), onClick: () => call("text_scenes.activate", "img::" + rel) }));
  if (pics.length > MAX_PICS) {
    items.push({ sep: true }, { label: `${pics.length - MAX_PICS} more: see Contents`, disabled: true, onClick: () => {} });
  }
  openMenu({ x: e.clientX, y: e.clientY }, items);
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
// The first loop waits until enough frames are ready that, at the speed they are being drawn,
// the rest are done before it gets to them (a fifth of the scene at least), and waits again the
// same way if it ever catches up: run frame by frame as they came, it froze every few frames
// wherever drawing was slower than the scene (PAD-361, a scene of over 100 pictures).
const PLAY_AHEAD = 0.2;
function TreePlayer({ s, onFrame }) {
  const play = s.tree_play;
  const t = s.tree_view;
  const W = t.stage[0], H = t.stage[1];
  const [f, setF] = useState(0);
  const [shown, setShown] = useState(false);
  const [filling, setFilling] = useState(true);    // holding until frames are ready ahead
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
    let fill = true;                                // start (and after a stall) on a full buffer
    const t0 = performance.now();
    const fps = play.fps || 30;
    const ms = Math.max(15, Math.round(1000 / fps));
    const ready = (p, k) => {                       // frame k drawn and loaded (or failed)
      const want = (p.map || [])[k];
      if (want == null) return false;
      const src = (p.srcs || [])[want] || "";
      const im = src ? imgs.current.get(src) : null;
      return !src || !!(im && im.complete && im.naturalWidth > 0);
    };
    const paint = (p, k) => {                       // frame k on the canvas
      const src = (p.srcs || [])[p.map[k]] || "";
      const im = src ? imgs.current.get(src) : null;
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
    };
    let still = false;                              // the opening frame shown while waiting
    const timer = setInterval(() => {
      const p = playRef.current;
      if ((p.map || [])[i] == null && p.done) i = 0; // (a play cut short loops what it has)
      if (fill) {
        if (!still && i === 0 && ready(p, 0)) {
          still = true;
          paint(p, 0);
        }
        const ahead = Math.min(Math.max(1, Math.ceil(p.frames * PLAY_AHEAD)), p.frames - i);
        let k = 0;
        while (k < ahead && ready(p, i + k)) k++;
        if (k < ahead && !(p.done && k > 0 && (p.map || [])[i + k] == null)) return;
        if (!p.done) {                              // and the drawing will stay ahead
          const drawn = (p.map || []).length;
          const rate = drawn / Math.max(0.001, (performance.now() - t0) / 1000);
          if ((p.frames - drawn) / rate > (drawn - i) / fps) return;
        }
        fill = false;
        setFilling(false);
      }
      if (!ready(p, i)) {                           // caught up with the drawing: refill
        fill = true;
        setFilling(true);
        return;
      }
      paint(p, i);
      setF(i);
      onFrame(i + 1);
      i = (i + 1) % p.frames;
    }, ms);
    return () => clearInterval(timer);
  }, [play.run, play.fps, play.frames]);
  return html`<div class="scenes-canvas tree-canvas" style=${`background:${s.bg_rgb || "#101014"};aspect-ratio:${W} / ${H}`}>
    <canvas class="tree-frame" ref=${cvRef} style=${shown ? "" : "visibility:hidden"}></canvas>
    ${shown ? null : html`<${Drawing} label="Drawing the frames…" />`}
    <div class="tree-playing small">${filling && !play.done
      ? `Getting frames ready… ${(play.map || []).length} of ${play.frames}`
      : `Frame ${f + 1} of ${play.frames}`}</div>
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
  };
  // Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z anywhere on the page, not only with the preview focused
  // (PAD-283: after a click on Draw 1:1 or any side-panel button the preview has no focus).
  // A text box keeps its own undo; a dialog or another tab is left alone.
  const flushRef = useRef(flushNudge);
  flushRef.current = flushNudge;
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const k = e.key.toLowerCase();
      const redo = k === "y" || (k === "z" && e.shiftKey);
      if (k !== "z" && !redo) return;
      const el = e.target;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (!box.current || !box.current.getClientRects().length || document.querySelector(".scrim")) return;
      e.preventDefault();
      flushRef.current();
      call(redo ? "text_scenes.tree_redo" : "text_scenes.tree_undo");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
      <summary title="Parts of this scene that can look more than one way. The game's code picks which one shows; the list lets you preview each.">
        <span class="eyebrow">Switchable parts</span>
        <span class="small muted">${t.states.length} ${t.states.length === 1 ? "part" : "parts"}, click to <span class="ts-shut">show</span><span class="ts-open">hide</span></span>
      </summary>
      <div class="small muted tree-states-hint">Each part below can look more than one way, and the game picks which while it runs (which monster, Locked or open). Pick one to see it here. This only changes the preview, not the card.</div>
      ${t.states.map((st, i) => html`<label key=${st.node} class="tree-state" title=${st.path}>
        <span class="small muted tree-state-n">${i + 1}.</span>
        <span class="small ellip">${st.name}</span>
        <${Select} sm value=${st.value} options=${st.options} onChange=${(v) => call("text_scenes.tree_state", st.node, v)} />
      </label>`)}
    </details>` : null}
    <span class="eyebrow">Selected</span>
    ${p && (t.sels || []).length > 1 ? html`<div class="tree-props">
      <div class="small"><b>${t.sels.length} selected</b></div>
      <div class="small muted">Drag any of them on the preview, or use the arrow keys, to move them together. Ctrl-click one to take it out; click one on its own to pick just that.</div>
      <div class="tree-row">
        <span class="lbl">Preview</span>
        <${Button} size="xs" title="Hide every selected layer in the preview only; the game is not changed (H)" onClick=${() => call("text_scenes.tree_view_many", t.sels, false)}>Hide<//>
        <${Button} size="xs" title="Show every selected layer in the preview again (H)" onClick=${() => call("text_scenes.tree_view_many", t.sels, true)}>Show<//>
      </div>
      <div class="tree-row">
        <span class="lbl">Game</span>
        <${Button} size="xs" title="Hide every selected layer in the game: Write leaves them out of the card; the preview is not changed" onClick=${() => call("text_scenes.tree_visible_many", t.sels, false)}>Hide<//>
        <${Button} size="xs" title="Put every selected layer back in the game" onClick=${() => call("text_scenes.tree_visible_many", t.sels, true)}>Show<//>
      </div>
    </div>`
    : p ? html`<div class="tree-props">
      <div class="small ellip" title=${p.name}><b>${p.name}</b> <span class="muted">${p.kind}${p.added ? ", added" : ""}</span></div>
      ${p.peek && p.view_off ? html`<div class="small muted">Hidden in the preview with its eye. It is shown on top while it is selected.</div>`
      : p.peek && p.view_in ? html`<div class="small muted">It sits in ${p.view_in}, hidden in the preview with its eye. It is shown on top while it is selected.</div>`
      : p.peek ? html`<div class="small muted">The game does not draw this at this moment. It is shown on top while it is selected; an edit holds wherever the game shows it.</div>` : null}
      ${p.hidden ? html`<div class="small in-game">Hidden in the game: Write leaves it out of the card. The preview still shows it.</div>`
      : p.hid_in ? html`<div class="small in-game">It sits in ${p.hid_in}, hidden in the game: Write leaves it out of the card.</div>` : null}
      ${p.pic ? html`<div class="tree-row">
        <span class="small muted" ...${tip("The picture's own size, and how much the game scales it to draw it here. Anything but 100% is resized by the game as it draws, which can leave jagged edges: make the picture at the size it shows, replace it on the Images tab with \"Keep this picture's own size\" ticked, then press Draw 1:1.")}>
          Picture ${p.pic.w} x ${p.pic.h} px, drawn at ${p.pic.sx === p.pic.sy ? p.pic.sx : `${p.pic.sx} x ${p.pic.sy}`}%</span>
        <${Button} size="xs" disabled=${p.pic.sx === 100 && p.pic.sy === 100}
          title="Draw the picture pixel for pixel (100%), keeping its top-left corner where it is"
          onClick=${() => call("text_scenes.tree_one_to_one", p.id)}>Draw 1:1<//>
      </div>` : null}
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
        <${Button} size="xs" title=${p.hidden ? "Put it back in the game" : "Hide it in the game: Write leaves it out of the card; the preview is not changed"}
          onClick=${() => call("text_scenes.tree_visible", p.id, p.hidden)}>${p.hidden ? "Show in game" : "Hide in game"}<//>
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
    <${Button} size="sm" kind="ghost" icon="undo" disabled=${!t.can_undo} title="Undo the last edit in this scene (Ctrl+Z)"
      onClick=${() => call("text_scenes.tree_undo")}>Undo<//>
    <${Button} size="sm" kind="ghost" icon="redo" disabled=${!t.can_redo} title="Redo the edit just undone (Ctrl+Y or Ctrl+Shift+Z)"
      onClick=${() => call("text_scenes.tree_redo")}>Redo<//>
    <${Button} size="sm" kind="ghost" iconRight="down" disabled=${!t.edits && !t.all_edits && !t.view_apart}
      title="Put this scene (or every scene) back: as the last Write left it, or as the game shipped it"
      onClick=${(e) => openMenu(e.currentTarget, [
        { label: "Back to the last Write (this scene)", icon: "undo", disabled: t.built !== "changed",
          title: t.built === "none" ? "No Write has been made from this project folder yet."
            : t.built === "same" ? "Nothing in this scene has changed since the last Write."
            : "Drop every edit made to this scene since the last Write put it on a card.",
          onClick: () => call("text_scenes.tree_revert_built") },
        { label: "Preview eyes as in the game (this scene)", icon: "eye", disabled: !t.view_apart,
          title: "Every eye back to what the game shows, as when the scene was first opened: shut on the layers hidden in the game, open on the rest. The card is not changed.",
          onClick: () => call("text_scenes.tree_view_reset") },
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
    ${(t.hidden_names || []).length ? html`<span class="small nw warn-ink"
        title=${`Hidden in the game, so the machine never draws it: ${t.hidden_names.join(", ")}. Click the card at the end of its row in Layers to put it back.`}>
        <${Icon} name="eye-off" /> ${t.hidden_names.length} hidden in game</span>` : null}
    ${adding ? html`<${Modal} title="Add a line of text" onClose=${() => setAdding(false)}
        footer=${html`<${Button} onClick=${() => setAdding(false)}>Cancel<//><${Button} kind="primary"
          disabled=${!words.trim()} onClick=${() => { setAdding(false); call("text_scenes.tree_add_text", words); }}>Add<//>`}>
      <p class="small muted" style="margin-top:0">Written in the font and size of the selected line (or the scene's first one), in the middle of the screen: drag it where you want it.</p>
      <${Field} value=${words} onChange=${setWords} placeholder="Words" />
    <//>` : null}
  </div>`;
}
