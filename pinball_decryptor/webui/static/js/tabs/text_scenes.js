// The Scenes window ("what each scene is made of"): a floating tool window
// (ToolWindow, text_fonts.js) over whichever tab is showing.
// Python: webui/text_scenes.py (ns "text_scenes").  The shell renders it over
// every tab; it shows itself while text_scenes.open is true.

import { html, useState, useEffect, useRef, Button, Field, Select, Table, Modal, openMenu, InfoBadge,
         Icon, tip, call, mediaUrl, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { ToolWindow } from "./text_fonts.js";

// Styled wherever it is hosted: load its own sheet once.
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
  { key: "label", label: "Scene", width: "minmax(0,1fr)", sort: "#0", titleOf: (r) => r.label + "\n" + r.d },
  { key: "imgs", label: "Images", width: "60px", sort: "imgs", num: true },
  { key: "fonts", label: "Fonts", width: "50px", sort: "fonts", num: true },
  { key: "texts", label: "Text", width: "44px", sort: "texts", num: true },
  { key: "vids", label: "Video", width: "minmax(50px,50px)", sort: "vids", num: true },
];
let sceneWidths = null;         // dragged column widths, kept for the session

export function ScenesWindow() {
  const s = useNs("text_scenes");
  const [color, setColor] = useState(null);     // {text, start, stock, title}
  useEffect(() => { if (!s.open) setColor(null); }, [s.open]);
  if (!s.open) return null;
  const tips = s.tips || {};
  const layout = s.layout_dialog;               // Move… / Font size…, shown in the side column
  const close = () => call("text_scenes.close");
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
  const shotLabel = s.exporting ? "Cancel" : "Save preview…";
  return html`<${ToolWindow} ns="text_scenes" title="Scenes — what each scene is made of" cls="scenes-win"
      raiseN=${s.raise_n} onClose=${close} onAside=${() => call("text_scenes.hide")} holdEsc=${!!color}
      footer=${html`<${Button} onClick=${close}>Close<//>`}>
    <p class="small muted" style="margin:0">${s.hint}</p>
    <div class="scenes-body">
      <div class="scenes-left" ...${tip(tips.list)}>
        <${Field} sm value=${s.search} placeholder="Search" onChange=${(v) => call("text_scenes.set_search", v)}
          delay=${200} prefix=${html`<${Icon} name="search" />`} />
        <${Table} cls="scenes-list" columns=${SCENE_COLS} rows=${s.scenes || []} rowKey=${(r) => r.d}
          selected=${s.sel} onSelect=${(r) => call("text_scenes.select", r.d)} rowHeight=${30}
          sort=${{ key: (s.sort || {}).col, desc: (s.sort || {}).rev }}
          onSort=${(k) => call("text_scenes.sort_by", k)}
          resizable widths=${sceneWidths} onResize=${(w) => { sceneWidths = w; }} />
      </div>
      <div class="scenes-right">
        <${Contents} s=${s} onMenu=${itemMenu} />
        <div class="scenes-preview">
          <${Preview} s=${s} tip=${tips.preview} />
          <div class="scenes-side">
            <span class="eyebrow">Scene preview</span>
            <${Button} size="sm" disabled=${!s.can_save && !s.exporting} title=${tips.save}
              onClick=${() => call("text_scenes.save_preview")}>${shotLabel}<//>
            <${Button} size="sm" title=${tips.save_all} disabled=${!(s.scenes || []).length && !s.bulk}
              onClick=${() => call("text_scenes.save_all")}>${s.bulk ? "Cancel" : "Save all previews…"}<//>
            <${Button} size="sm" title=${tips.rebuild} onClick=${() => call("text_scenes.rebuild")}>
              ${s.rebuilding ? "Cancel" : "Rebuild previews…"}<//>
            ${s.rebuild_msg ? html`<span class="small muted">${s.rebuild_msg}</span>` : null}
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
        </div>
        ${layout ? html`<${LayoutEditor} key=${layout.kind + "\u0000" + layout.text} d=${layout} />` : null}
        <div class="row scenes-caption">
          <span class="small muted ellip">${s.caption}</span>
          ${s.caption_full ? html`<${InfoBadge} text=${s.caption_full} />` : null}
        </div>
        <div class="row scenes-bottom">
          <div class="thumb scenes-thumb">${s.thumb ? html`<img src=${mediaUrl(s.thumb)} alt="" />` : null}</div>
          <span class="small muted mono scenes-detail">${s.detail}</span>
        </div>
      </div>
    </div>
  <//>
  ${color ? html`<${ColorDialog} c=${color} onClose=${() => setColor(null)} />` : null}`;
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
      : html`<span class="scenes-msg">${s.canvas_msg}</span>`}
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
