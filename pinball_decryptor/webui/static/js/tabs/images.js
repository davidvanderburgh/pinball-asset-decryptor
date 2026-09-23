// Replace Images (the Tk tab's _build_image_tab): scan the project folder
// for image slots, filter and group them, pick / clear / keep-size a
// replacement, and compare the original with it.  Every rule lives in
// webui/tabs/images.py; this is the view.

import { html, useEffect, useLayoutEffect, useMemo, useRef, useState, PageHead, Button, Field, Select, Seg,
         Check, Chip, Note, Table, Empty, Modal, openMenu, Icon, Spinner, tip, call, mediaUrl, cx }
  from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const GROUP = "::grp::";
const WEB_PICTURES = new Set(["png", "jpg", "jpeg", "gif", "bmp", "webp"]);

// Tk wording (gui/main_window.py _build_image_tab and the shared row helpers)
const INTRO = "Assign a replacement image to any slot — it's auto-scaled and converted to the slot's format — then build the update on the Write tab.";
const PILLOW = "Pillow not found — replacing images needs Pillow to scale + re-encode images. Install it with “Install Missing”.";
const SOURCE_TIP = "Show only images from one store: plain files on the card, scene.assets textures, radium-embedded images, or per-character font glyph slices (the Source column).";
const SHOW_TIP = "Narrow the list by what you've already done to it. Changed = the slots with a pending replacement or already changed on disk by a previous build. Unchanged = everything you haven't touched yet, so a part-finished pass is what's left in front of you instead of something to scroll past.";
const GROUP_TIP = "Group the images under the scene / animation they belong to (in play order), so a whole animation can be reviewed — or bulk-replaced via right-click — as one unit.";
const FONTS_TIP = "Preview any game font (type your own text, rendered from the real glyphs) and import a desktop font into it — letters are auto-fitted into the space each character has. Stern Spike 2.";
const SCENES_TIP = "Browse the card scene by scene: the images, fonts and on-screen text each scene is built from, with jumps to the matching rows here and on Replace Text. Stern Spike 2.";
const FOLDER_TIP = "Pick a folder of your own files and each one becomes the replacement for the slot with the same name — for a whole set you reworked outside the app, like every clip made black and white. The file type and capital letters don't have to match (Intro.mp4 is used for Intro.mov and converted to suit it), and subfolders are fine. Nothing changes until you confirm, and every file left out is named in the log.\n\nKeep the extract's own files where they are: files dropped into the project folder only count under the card's exact name.";
const CLEAR_TIP = "Drop every replacement picked on this tab in one go — for starting a project over without clearing 48 rows one at a time. It only drops the picks: your own files are untouched, and a slot already built into the project folder keeps the bytes it has (use “Revert all changes…” on the Write tab for those). To clear only some, select the rows — click, then Shift-click or Ctrl-click — and right-click the selection.";
const KEEP_TIP = "Off: the replacement is scaled to the original picture's size, which squeezes a longer name. On: it keeps its own width and height, and the build grows the scene to fit it. The game draws it from the same top-left corner, so a wider picture reaches further right. Needs an image build (not a direct SD write). A picture nothing in its scene draws by size is fitted instead, and the log says so.";
const REP_TIP = "Click to choose a replacement for this image (double-click the row does the same).";

const TAG_CLS = { assigned: "img-picked", changed: "img-ondisk", foreign: "img-stray" };

// Column widths (Tk _persist_tree_columns + _autosize_tree_columns).  A
// column the user dragged keeps that width (saved by images.save_widths);
// the others fit their widest cell and heading, capped at 480 px.  Original
// Image and Replacement share what is left, as the design has it.
const AUTOSIZE_MAX = 480;
// the Tk tree's minwidths
const MIN_W = { th: 36, "#0": 160, n: 50, res: 70, fmt: 80, src: 70, keep: 64, rep: 110 };
const FIT_COLS = [["n", "Images"], ["res", "Resolution"], ["fmt", "Format"], ["src", "Source"], ["keep", "Keep size"]];
let measureCtx = null;
function textWidth(font, text, spacing = 0) {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return 0;
  measureCtx.font = font;
  return measureCtx.measureText(text).width + spacing * text.length;
}
function fonts() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n, d) => cs.getPropertyValue(n).trim() || d;
  const sans = v("--sans", "sans-serif");
  return { sans, mono: v("--mono", "monospace"), cond: v("--cond", sans) };
}
function widest(font, values) {
  let w = 0;
  for (const v of values) {
    const x = textWidth(font, String(v == null ? "" : v));
    if (x > w) { w = x; if (w >= AUTOSIZE_MAX) break; }
  }
  return Math.ceil(w) + 6;
}
const fit = (key, w) => Math.max(MIN_W[key] || 36, Math.min(AUTOSIZE_MAX, Math.ceil(w)));

const base = (p) => { const s = String(p || "").replace(/\\/g, "/"); return s.slice(s.lastIndexOf("/") + 1); };
const dirOf = (p) => { const s = String(p || ""); const i = s.lastIndexOf("/"); return i < 0 ? "" : s.slice(0, i + 1); };
const extOf = (p) => { const b = base(p); const i = b.lastIndexOf("."); return i < 0 ? "" : b.slice(i + 1).toLowerCase(); };

function slotAt(s, i) {
  const c = s["rows_" + (i >> 8)];
  return c ? c[i & 255] : null;
}

// A preview picture: the Tk panes' own renderer (core.image.thumbnail_png),
// asked for at the size the box has on screen.
function Thumb({ path, ver, empty, label, cls = "" }) {
  const ref = useRef(null);
  const [box, setBox] = useState(null);
  const [src, setSrc] = useState("");
  const [busy, setBusy] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let t = null;
    const measure = () => {
      clearTimeout(t);
      t = setTimeout(() => {
        const w = el.clientWidth, h = el.clientHeight;
        setBox((b) => (b && Math.abs(b.w - w) < 24 && Math.abs(b.h - h) < 24 ? b : { w, h }));
      }, 120);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return () => clearTimeout(t);
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => { clearTimeout(t); ro.disconnect(); };
  }, []);
  useEffect(() => {
    if (!path || !box || box.w < 20) { setSrc(""); setBusy(false); return; }
    let alive = true;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    setBusy(true);
    call("images.thumb", path, Math.round((box.w - 8) * dpr), Math.round((box.h - 8) * dpr)).then((r) => {
      if (!alive) return;
      setSrc(r || "");
      setBusy(false);
    });
    return () => { alive = false; };
  }, [path, ver, box && box.w, box && box.h]);
  return html`<div class=${cx("thumb img-pic", cls)} ref=${ref} aria-label=${label}>
    ${src ? html`<img src=${src} alt=${label || ""} />`
      : busy ? html`<${Spinner} />`
      : !path && empty ? html`<span class="img-empty small">${empty}</span>` : null}
  </div>`;
}

function RenameModal({ spec, onClose }) {
  const [value, setValue] = useState(spec.initial || "");
  const ok = () => { call("images.rename_group", spec.key, value); onClose(); };
  const cancel = () => { call("images.rename_group", spec.key, null); onClose(); };
  // Tk _ask_text: entry.focus_set(); entry.selection_range(0, END), so
  // typing replaces the generic name instead of adding to it
  useEffect(() => {
    const el = document.getElementById("img-rename-input");
    if (el) { el.focus(); el.select(); }
  }, []);
  return html`<${Modal} title=${spec.title} icon="edit" onClose=${cancel}
      footer=${html`<${Button} onClick=${cancel}>Cancel<//><${Button} kind="primary" onClick=${ok}>OK<//>`}>
    <form class="stack" style="gap:10px" onSubmit=${(e) => { e.preventDefault(); ok(); }}>
      <label class="small" style="white-space:pre-line">${spec.prompt}</label>
      <${Field} id="img-rename-input" value=${value} onChange=${setValue} autoFocus cls="img-rename" />
    </form>
  <//>`;
}

export default function ImagesTab() {
  const s = useNs("images");
  const shell = useNs("shell");
  const view = s.view || [];
  const p = s.preview || {};
  const grouped = !!(s.cols && s.cols.n);
  const keepCol = !!(s.cols && s.cols.keep);
  const running = !!(s.running || shell.running);
  const [sel, setSel] = useState(() => new Set());
  const [cur, setCur] = useState(null);
  const [rename, setRename] = useState(null);
  const anchor = useRef(null);

  const idOf = (e) => (typeof e === "number" ? ((slotAt(s, e) || {}).r || "#" + e) : GROUP + e.g);

  // Python moves the selection (a fresh scan, a pick, a clear, a jump here)
  const focusN = s.focus && s.focus.n;
  useEffect(() => {
    if (!s.focus) return;
    setSel(new Set(s.focus.ids || []));
    setCur(s.focus.id || null);
    anchor.current = s.focus.id || null;
  }, [focusN]);

  const selectOnly = (id) => {
    setSel(new Set([id]));
    setCur(id);
    anchor.current = id;
    call("images.select", id);
  };

  const onSelect = (e, i, ev) => {
    const id = idOf(e);
    let next;
    if (ev && ev.shiftKey && anchor.current != null) {
      const a = view.findIndex((x) => idOf(x) === anchor.current);
      if (a >= 0) {
        const lo = Math.min(a, i), hi = Math.max(a, i);
        next = new Set(view.slice(lo, hi + 1).map(idOf));
      } else next = new Set([id]);
    } else if (ev && (ev.ctrlKey || ev.metaKey) && ev.type === "click") {
      next = new Set(sel);
      if (next.has(id)) next.delete(id); else next.add(id);
      anchor.current = id;
    } else {
      next = new Set([id]);
      anchor.current = id;
    }
    setSel(next);
    setCur(id);
    call("images.select", id);
  };

  const onActivate = (e) => {
    if (typeof e === "number") {
      const row = slotAt(s, e);
      if (row) call("images.choose", row.r);
    } else call("images.toggle_group", e.g);
  };

  // The ttk Treeview's own keys in "Group by scene" (ttk::treeview::Keynav):
  // Right opens a group, Left closes an open one, and on a picture Left
  // goes to its group.  The table itself handles Up / Down / Enter.
  const onTreeKey = (ev) => {
    if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
    if (!grouped || ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    if (!ev.target || !ev.target.closest || !ev.target.closest(".img-tbl .scroller")) return;
    const i = view.findIndex((x) => idOf(x) === cur);
    if (i < 0) return;
    const e = view[i];
    ev.preventDefault();
    if (typeof e !== "number") {
      if (ev.key === "ArrowLeft") { if (e.o) call("images.toggle_group", e.g, false); }
      else if (!e.o) call("images.toggle_group", e.g, true);
      return;
    }
    if (ev.key === "ArrowLeft") {
      for (let j = i - 1; j >= 0; j--) {
        if (typeof view[j] !== "number") { selectOnly(idOf(view[j])); return; }
      }
    }
  };

  // Widths: what each column's cells need (all the scan's rows, so a filter
  // does not make the columns jump), re-measured once the web fonts load.
  const [fontsReady, setFontsReady] = useState(0);
  useEffect(() => {
    let alive = true;
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (alive) setFontsReady(1); });
    return () => { alive = false; };
  }, []);
  const chunks = [];
  for (let k = 0; k < (s.nchunks || 0); k++) chunks.push(s["rows_" + k]);
  const cellFit = useMemo(() => {
    const f = fonts();
    const res = new Set(), fmt = new Set(), src = new Set();
    for (const c of chunks) for (const r of c || []) { res.add(r.s); fmt.add(r.f); src.add(r.o); }
    const out = {};
    for (const [key, label] of FIT_COLS) {
      // the heading, with room for the ▲/▼ and the drag grip
      out[key] = Math.ceil(textWidth(`600 12px ${f.cond}`, label.toUpperCase(), 0.72) + textWidth(`600 12px ${f.cond}`, " ▼", 0.72)) + 16;
    }
    out.res = Math.max(out.res, widest(`12.5px ${f.mono}`, res));
    out.fmt = Math.max(out.fmt, widest(`13.5px ${f.sans}`, fmt));
    out.src = Math.max(out.src, widest(`13.5px ${f.sans}`, src));
    out.keep = Math.max(out.keep, 22);
    return out;
  }, [fontsReady, ...chunks]);
  const groupCounts = grouped ? view.filter((e) => typeof e !== "number").map((e) => e.c) : [];
  const countFit = useMemo(() => (grouped ? widest(`13.5px ${fonts().sans}`, groupCounts) : 0),
    [fontsReady, grouped, groupCounts.join("|")]);
  const autoW = (key) => `${fit(key, key === "n" ? Math.max(cellFit.n, countFit) : cellFit[key])}px`;

  // Tk saved only the columns the user dragged: note every column's width
  // as a drag starts, and send the ones that changed when it ends.
  const dragStart = useRef(null);
  const onCardMouseDown = (ev) => {
    const g = ev.target && ev.target.closest ? ev.target.closest(".img-tbl .col-grip") : null;
    if (!g) return;
    const hdr = g.closest(".tr");
    dragStart.current = hdr ? [...hdr.children].map((c) => c.getBoundingClientRect().width) : null;
  };

  const runAct = async (act, id, selIds) => {
    const r = await call("images.act", act, id, selIds);
    if (act === "group_rename" && r && r.key != null) setRename(r);
  };

  const onContext = async (e, i, ev) => {
    const id = idOf(e);
    let selIds = [...sel];
    if (!sel.has(id) || sel.size < 2) {
      selectOnly(id);
      selIds = [id];
    }
    const at = { x: ev.clientX, y: ev.clientY };
    const items = await call("images.menu", id, selIds);
    if (!items || !items.length) return;
    openMenu(at, items.map((it) => (it.sep ? { sep: true }
      : { label: it.label, disabled: !!it.disabled, onClick: it.act ? () => runAct(it.act, id, selIds) : undefined })));
  };

  const thumbCol = {
    key: "th", label: "", width: "40px", cls: "img-thcell",
    render: (e) => {
      if (typeof e !== "number") {
        return html`<button type="button" class="img-chev" aria-label=${e.o ? "Collapse group" : "Expand group"}
          onClick=${(ev) => { ev.stopPropagation(); call("images.toggle_group", e.g); }}><${Icon} name=${e.o ? "down" : "right"} /></button>`;
      }
      const row = slotAt(s, e);
      if (!row) return null;
      const ext = extOf(row.r);
      if (!WEB_PICTURES.has(ext) || !s.dir) return html`<span class="img-mini img-ext">${ext.toUpperCase()}</span>`;
      return html`<span class="img-mini"><img loading="lazy" decoding="async" alt="" src=${mediaUrl(s.dir + "/" + row.r)} /></span>`;
    },
  };
  const nameCol = {
    key: "#0", label: "Original Image", sort: "#0", width: `minmax(${MIN_W["#0"]}px,1.5fr)`,
    render: (e) => {
      if (typeof e !== "number") return html`<span class="img-grp ellip" title=${e.l}>${e.l}</span>`;
      const row = slotAt(s, e);
      if (!row) return null;
      if (grouped) return html`<span class=${cx("img-name img-child", row.t === "foreign" && "img-stray")} title=${row.r}><span class="img-base">${base(row.r)}</span></span>`;
      return html`<span class=${cx("img-name", row.t === "foreign" && "img-stray")} title=${row.r}><span class="img-dir">${dirOf(row.r)}</span><span class="img-base">${base(row.r)}</span></span>`;
    },
  };
  const countCol = {
    key: "n", label: "Images", sort: "n", width: autoW("n"),
    render: (e) => (typeof e === "number" ? "" : html`<span class="muted">${e.c}</span>`),
  };
  const cell = (k, cls) => (e) => {
    if (typeof e !== "number") return "";
    const row = slotAt(s, e);
    return row ? html`<span class=${cls}>${row[k]}</span>` : "";
  };
  const resCol = { key: "res", label: "Resolution", sort: "res", width: autoW("res"), render: cell("s", "mono small") };
  const fmtCol = { key: "fmt", label: "Format", sort: "fmt", width: autoW("fmt"), render: cell("f", "img-dim") };
  const srcCol = { key: "src", label: "Source", sort: "src", width: autoW("src"), render: cell("o", "") };
  // Tk: a click on the tick flips it (and selects the row); the second click
  // of a double-click is the row's double-click, which opens the picker
  const keepColDef = {
    key: "keep", label: "Keep size", sort: "keep", width: autoW("keep"), cls: "img-keepcell", title: KEEP_TIP,
    render: (e) => {
      if (typeof e !== "number") return "";
      const row = slotAt(s, e);
      if (!row || row.k == null) return "";
      return html`<input type="checkbox" class="img-keep" checked=${!!row.k} aria-label="Keep this picture's own size"
        ...${tip(KEEP_TIP)} onClick=${(ev) => {
          ev.stopPropagation();
          if (ev.detail > 1) { ev.preventDefault(); return; }
          if (cur !== row.r) selectOnly(row.r);
          call("images.set_keep", row.r, !row.k);
        }} />`;
    },
  };
  // One picker per click: the second click of a double-click is ignored
  // and the double-click stops here (Tk's picker was modal and took the
  // grab, so there was only ever one)
  const repCol = {
    key: "rep", label: "Replacement", sort: "rep", width: `minmax(${MIN_W.rep}px,1fr)`,
    render: (e) => {
      if (typeof e !== "number") return "";
      const row = slotAt(s, e);
      if (!row) return "";
      return html`<button type="button" class=${cx("img-rep ellip", TAG_CLS[row.t] || "muted")} title=${row.p === "Choose…" ? REP_TIP : row.p}
        onDblClick=${(ev) => ev.stopPropagation()}
        onClick=${(ev) => {
          ev.stopPropagation();
          if (ev.detail > 1) return;
          selectOnly(row.r);
          call("images.choose", row.r);
        }}>${row.p}</button>`;
    },
  };
  const columns = [thumbCol, nameCol, grouped && countCol, resCol, fmtCol, srcCol, keepCol && keepColDef, repCol].filter(Boolean);

  // the dragged widths (never below the Tk tree's minwidths); the last
  // column always takes what is left
  const saved = s.widths || {};
  const widths = {};
  for (const c of columns.slice(0, -1)) {
    if (saved[c.key] > 0) widths[c.key] = Math.max(MIN_W[c.key] || 36, saved[c.key]);
  }
  const onResize = (out) => {
    const start = dragStart.current;
    dragStart.current = null;
    const changed = {};
    columns.forEach((c, i) => {
      if (out[c.key] == null) return;
      if (!start || start[i] == null || Math.round(start[i]) !== out[c.key]) changed[c.key] = out[c.key];
    });
    if (!Object.keys(changed).length) return;
    // Under the global zoom the table measures on-screen pixels; save CSS
    // pixels, or the column comes back zoom times wider.  A column that was
    // not dragged and has a known width tells which the table reported.
    const z = parseFloat(document.documentElement.style.zoom) || 1;
    let scale = 1;
    if (Math.abs(z - 1) > 0.01) {
      for (const c of columns.slice(0, -1)) {
        const w = widths[c.key] || parseFloat(c.width);
        if (c.key in changed || !(w > 0) || out[c.key] == null) continue;
        if (Math.abs(out[c.key] - w * z) < Math.abs(out[c.key] - w)) scale = z;
        break;
      }
    }
    for (const k of Object.keys(changed)) changed[k] = Math.round(changed[k] / scale);
    call("images.save_widths", changed);
  };

  const rowClass = (e) => {
    const id = idOf(e);
    const on = sel.has(id) && id !== cur ? "sel" : "";
    if (typeof e !== "number") return cx("img-grow", on);
    return on;
  };

  const status = s.status || "";
  const empty = s.empty;
  const tableEmpty = empty
    ? html`<${Empty} icon=${empty.busy ? "refresh" : "images"}>
        ${empty.busy ? html`<span class="row" style="justify-content:center"><${Spinner} /><span>${empty.text}</span></span>` : empty.text}<//>`
    : html`<${Empty} icon="search">No image matches the search and filters.<//>`;

  const prevRel = p.rel;
  return html`<div class="page img-page">
    <${PageHead} title="Images" sub=${INTRO}>
      ${status ? html`<${Chip} kind=${s.changed ? "acc" : ""}>${status.trim()}<//>` : null}
      ${s.scanning
        ? html`<${Button} icon="x" onClick=${() => call("images.cancel_scan")}>Cancel scan<//>`
        : html`<${Button} icon="refresh" onClick=${() => call("images.scan")}>Scan<//>`}
      <${Button} icon="folder" onClick=${() => call("images.from_folder")} disabled=${running} title=${FOLDER_TIP}>Replace from folder…<//>
      <${Button} kind="ghost" onClick=${() => call("images.export_csv")}>Export CSV<//>
      <${Button} kind="ghost" onClick=${() => call("images.clear_all")} disabled=${!s.can_clear} title=${CLEAR_TIP}>Clear replacements…<//>
      <${Button} kind="ghost" onClick=${() => call("images.open_fonts")} title=${FONTS_TIP}>Fonts…<//>
      <${Button} kind="ghost" onClick=${() => call("images.open_scenes")} title=${SCENES_TIP}>Scenes…<//>
    <//>

    ${s.pil_ok === false ? html`<${Note} kind="err">${PILLOW}<//>` : null}

    <section class="card img-card" onMouseDownCapture=${onCardMouseDown} onKeyDown=${onTreeKey}>
      <div class="toolbar">
        <${Field} ns="images" k="search" value=${s.search} placeholder="Search" cls="search"
          prefix=${html`<${Icon} name="search" />`} />
        <${Select} value=${s.source || "All sources"} options=${s.sources || []} width=${148}
          onChange=${(v) => call("images.set_source", v)} title=${SOURCE_TIP} />
        <span class="img-seg" ...${tip(SHOW_TIP)}>
          <${Seg} value=${s.show || "All"} options=${s.shows || []} onChange=${(v) => call("images.set_show", v)} />
        </span>
        <${Check} checked=${!!s.grouped} onChange=${(v) => call("images.set_grouped", v)} label="Group by scene" title=${GROUP_TIP} />
        <span class="sp"></span>
      </div>
      <${Table} cls="img-tbl" columns=${columns} rows=${view} rowKey=${idOf} selected=${cur}
        onSelect=${onSelect} onActivate=${onActivate} onContext=${onContext} rowClass=${rowClass}
        sort=${s.sort} onSort=${(k) => call("images.sort", k)} empty=${tableEmpty} rowHeight=${36}
        resizable widths=${widths} onResize=${onResize} />
      <div class="ft img-prev">
        <div class="row img-panehd img-oh">
          <span class="eyebrow nw">${p.hdr_main || "Original"}</span>
          ${prevRel ? html`<span class="mono small muted ellip" title=${prevRel}>— ${base(prevRel)}</span>` : null}
        </div>
        <span class="vsep img-vsep"></span>
        <div class="row img-panehd img-rh">
          <span class="eyebrow nw">Replacement</span>
          ${p.rep_name ? html`<span class="mono small ellip img-repname" title=${p.rep}>— ${p.rep_name}</span>` : null}
          <span class="grow"></span>
          ${prevRel ? html`<${Button} size="sm" onClick=${() => call("images.choose", prevRel)}>Choose…<//>` : null}
          ${prevRel && p.clearable ? html`<${Button} size="sm" kind="ghost" onClick=${() => call("images.clear_one", prevRel)}>Clear replacement<//>` : null}
        </div>
        ${p.hdr_note ? html`<div class="small img-shared img-on">${p.hdr_note}</div>` : null}
        ${p.keep ? html`<div class="img-keeprow img-rk">
          <${Check} checked=${!!p.keep.on} onChange=${(v) => call("images.set_keep", prevRel, v)}
            label="Keep this picture's own size" title=${KEEP_TIP} />
          <span class="small muted">${p.keep.text}</span>
        </div>` : null}
        <${Thumb} cls="img-op" path=${p.orig} ver=${p.ver} label="Original" />
        <${Thumb} cls="img-rp" path=${p.rep} ver=${p.ver} empty=${p.empty} label="Replacement" />
      </div>
    </section>

    ${s.note ? html`<p class="small muted img-note">${s.note}</p>` : null}
    ${rename ? html`<${RenameModal} spec=${rename} onClose=${() => setRename(null)} />` : null}
  </div>`;
}
