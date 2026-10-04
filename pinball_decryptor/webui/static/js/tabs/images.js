// Replace Images (the Tk tab's _build_image_tab): scan the project folder
// for image slots, filter and group them, pick / clear / keep-size a
// replacement, and compare the original with it.  Every rule lives in
// webui/tabs/images.py; this is the view.

import { html, useEffect, useLayoutEffect, useMemo, useRef, useState, PageHead, Button, Field, Select, Seg,
         Check, Chip, Note, Table, Empty, Modal, openMenu, Icon, Spinner, tip, call, mediaUrl, cx }
  from "../core/ui.js";
import { useNs } from "../core/store.js";
import { ColorBar, barOpenAtStart, rememberBarOpen } from "./color_pane.js";

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
const MORE_TIP = "More: Export CSV, Clear replacements…, Save / load settings";
const CSV_TIP = "Save every row of the list as a spreadsheet (CSV), exactly as it reads here.";
const FOLDER_TIP = "Pick a folder of your own files and each one becomes the replacement for the slot with the same name — for a whole set you reworked outside the app, like every clip made black and white. The file type and capital letters don't have to match (Intro.mp4 is used for Intro.mov and converted to suit it), and subfolders are fine. Nothing changes until you confirm, and every file left out is named in the log.\n\nKeep the extract's own files where they are: files dropped into the project folder only count under the card's exact name.";
const CLEAR_TIP = "Drop every replacement picked on this tab in one go — for starting a project over without clearing 48 rows one at a time. It only drops the picks: your own files are untouched, and a slot already built into the project folder keeps the bytes it has (use “Revert all changes…” on the Write tab for those). To clear only some, select the rows — click, then Shift-click or Ctrl-click — and right-click the selection.";
const KEEP_TIP = "Off: the replacement is scaled to the original picture's size, which squeezes a longer name. On: it keeps its own width and height, and the build grows the scene to fit it. The game draws it from the same top-left corner, so a wider picture reaches further right. Needs an image build (not a direct SD write). A picture nothing in its scene draws by size is fitted instead, and the log says so.";
const REP_TIP = "Click to choose a replacement for this image (double-click the row does the same).";
// PAD-312: the chosen-files color profile, baked into this picture as it is staged
const COLOR_TIP = "Green: a color profile is attached to this file. The Color profile tab's individual files profile is baked into it when you build. Red: no color profile is attached; it goes on the card as it is. Blue lock: the game's own picture, never touched (tick Unlock extracted images to give it a palette too). A palette you click is this picture's own setting; the Color profile tab's Every replaced picture box sets the rest.";
// PAD-368: the profile a file has, for its tooltips (null where the Color column is not offered);
// PAD-369: a {profile} line, drawn in the one color every tooltip gives it (core/ui.js)
const profileLine = (r, cs) => (r.cl ? { profile: "None" } : r.c == null ? null
  : { profile: r.c ? ((cs.own_names || {}).images || {})[r.r] || cs.asset_name || "Recommended" : "None" });
// PAD-335: the same blue lock / red / green palette as the Video tab's Color column
const colorTip = (r, cs) => (r.cl
  ? { head: "Color: the game's own picture", lines: [
      profileLine(r, cs),
      "Stern made it for the machine's screen, so the individual files profile is not offered on it.",
      "Choose a replacement to correct a picture of your own, or tick Unlock extracted images."] }
  : { head: r.c ? "Color profile attached to this file" : "No color profile attached to this file", lines: [
      profileLine(r, cs),
      ["Click", r.c ? "detach the color profile" : "attach the color profile"],
      r.c ? "Its color profile is baked into this picture when you build. Open Colors with it selected to give it one of its own."
        : "It goes on the card as it is.",
      r.cg ? "The game's own picture, unlocked: corrected from its original when you build."
        : r.co ? "Set for this picture." : "Follows the Color profile tab's box for every replaced picture."] });
const UNLOCK_TIP = "Advanced. Off: the original extracted images are locked (blue lock), and only the pictures you replace can have the individual files color profile baked in. On: every picture on this tab gets a palette, so a color profile can be attached to an extracted image too, whatever is drawn in it now. It is staged from its original extracted copy when you build, so building again never corrects it twice. The same box as the Scenes tab's Advanced box beside Preview colors; Video has its own. Turning it off puts the extracted images back as they were.";

const TAG_CLS = { assigned: "img-picked", changed: "img-ondisk", foreign: "img-stray" };

// Column widths (Tk _persist_tree_columns + _autosize_tree_columns).  A
// column the user dragged keeps that width (saved by images.save_widths);
// the others fit their widest cell and heading, capped at 480 px.  Original
// Image and Replacement share what is left, as the design has it.
const AUTOSIZE_MAX = 480;
// the Tk tree's minwidths
const MIN_W = { th: 36, "#0": 160, n: 50, res: 70, fmt: 80, src: 70, keep: 64, color: 56, rep: 110 };
const FIT_COLS = [["n", "Images"], ["res", "Resolution"], ["fmt", "Format"], ["src", "Source"], ["keep", "Keep size"], ["color", "Color"]];
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
  // PAD-364 (DragonRR): the Color profiles bar on the right edge, as on the Scenes tab,
  // so a profile is picked from the Saved profiles list with each picture's Color switch
  // in view.  It opens on Files the first time: the profile that column attaches.
  const colorNs = useNs("color");
  const [colors, setColorsState] = useState(() => barOpenAtStart("images"));
  const setColors = (v) => { setColorsState(v); rememberBarOpen(v, "images"); };
  const view = s.view || [];
  const p = s.preview || {};
  const grouped = !!(s.cols && s.cols.n);
  const keepCol = !!(s.cols && s.cols.keep);
  const colorCol = !!(s.cols && s.cols.color);
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
    out.color = Math.max(out.color, 22);
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
      const ttl = tip({ head: row.r, lines: [profileLine(row, colorNs)] });
      if (grouped) return html`<span class=${cx("img-name img-child", row.t === "foreign" && "img-stray")} ...${ttl}><span class="img-base">${base(row.r)}</span></span>`;
      return html`<span class=${cx("img-name", row.t === "foreign" && "img-stray")} ...${ttl}><span class="img-dir">${dirOf(row.r)}</span><span class="img-base">${base(row.r)}</span></span>`;
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
  // PAD-312: the chosen-files color profile, per picture (the same click rules)
  const colorColDef = {
    key: "color", label: "Color", sort: "color", width: autoW("color"), cls: "img-keepcell", title: COLOR_TIP,
    render: (e) => {
      if (typeof e !== "number") return "";
      const row = slotAt(s, e);
      if (!row) return "";
      // PAD-335: a blue lock on the game's own pictures, a red / green palette otherwise
      if (row.cl) return html`<span class="img-color locked" aria-label="The game's own picture: no color profile can be attached"
        ...${tip(colorTip(row, colorNs))}><${Icon} name="lock" /></span>`;
      if (row.c == null) return "";
      return html`<button type="button" class=${cx("img-color", row.c ? "on" : "off", row.co && !row.cg && "own")}
        aria-label="Correct this picture's colors for the machine" aria-pressed=${row.c ? "true" : "false"}
        ...${tip(colorTip(row, colorNs))} onClick=${(ev) => {
          ev.stopPropagation();
          if (ev.detail > 1) { ev.preventDefault(); return; }
          if (cur !== row.r) selectOnly(row.r);
          call("images.set_color", row.r, !row.c);
        }}><${Icon} name="palette" /></button>`;
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
      // PAD-369 (DragonRR): the chosen file's name tells its color profile too
      const pl = row.p === "Choose…" ? null : profileLine(row, colorNs);
      return html`<button type="button" class=${cx("img-rep ellip", TAG_CLS[row.t] || "muted")}
        ...${tip(pl ? { head: row.p, lines: [pl] } : row.p === "Choose…" ? REP_TIP : row.p)}
        onDblClick=${(ev) => ev.stopPropagation()}
        onClick=${(ev) => {
          ev.stopPropagation();
          if (ev.detail > 1) return;
          selectOnly(row.r);
          call("images.choose", row.r);
        }}>${row.p}</button>`;
    },
  };
  const columns = [thumbCol, nameCol, grouped && countCol, resCol, fmtCol, srcCol, keepCol && keepColDef, colorCol && colorColDef, repCol].filter(Boolean);

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
  return html`<div class="cpd-shell"><div class="page img-page">
    <${PageHead} title="Images" sub=${INTRO}>
      ${status ? html`<${Chip} kind=${s.changed ? "acc" : ""}>${status.trim()}<//>` : null}
      ${s.scanning
        ? html`<${Button} icon="x" onClick=${() => call("images.cancel_scan")}>Cancel scan<//>`
        : html`<${Button} icon="refresh" onClick=${() => call("images.scan")}>Scan<//>`}
      <${Button} icon="folder" onClick=${() => call("images.from_folder")} disabled=${running} title=${FOLDER_TIP}>Replace from folder…<//>
      <${Button} kind="ghost" icon="text" onClick=${() => call("images.open_fonts")} title=${FONTS_TIP}>Fonts…<//>
      <${Button} kind="ghost" icon="more" label="More" title=${MORE_TIP}
        onClick=${(e) => openMenu(e.currentTarget, [
          { label: "Export CSV", icon: "download", title: CSV_TIP, onClick: () => call("images.export_csv") },
          { label: "Clear replacements…", icon: "trash", title: CLEAR_TIP, disabled: !s.can_clear,
            onClick: () => call("images.clear_all") },
          { sep: true },
          { label: "Save settings to a file…", icon: "download", title: "Which file replaces which slot, and this tab's ticks and options, in one small file to keep or to send. The pictures themselves are not in it.",
            onClick: () => call("images.settings_save") },
          { label: "Load settings from a file…", icon: "upload", disabled: running,
            title: "Put the settings in a file saved here or by someone else onto the same slots of this card. A slot this card does not have is left out.",
            onClick: () => call("images.settings_load") },
        ], { align: "right" })} />
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
        ${s.color_unlock && s.color_unlock.offered ? html`<span class="img-unlock">
          <span class="eyebrow">Advanced</span>
          <${Check} checked=${!!s.color_unlock.on} onChange=${(v) => call("images.set_color_unlocked", v)} disabled=${running}
            label="Unlock extracted images" title=${UNLOCK_TIP} />
        </span>` : null}
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
          ${p.rep_name ? html`<span class="mono small ellip img-repname" ...${tip(p.color
            ? { head: p.rep, lines: [{ profile: p.color.on ? p.color.name : "None" }] } : p.rep)}>— ${p.rep_name}</span>` : null}
          <span class="grow"></span>
          ${prevRel ? html`<${Button} size="sm" onClick=${() => call("images.choose", prevRel)}>Choose…<//>` : null}
          ${prevRel && p.clearable ? html`<${Button} size="sm" kind="ghost" onClick=${() => call("images.clear_one", prevRel)}>Clear replacement<//>` : null}
        </div>
        ${p.hdr_note ? html`<div class="small img-shared img-on">${p.hdr_note}</div>` : null}
        ${p.keep || p.color ? html`<div class="img-rk img-opts">
          ${p.keep ? html`<div class="img-keeprow">
            <${Check} checked=${!!p.keep.on} onChange=${(v) => call("images.set_keep", prevRel, v)}
              label="Keep this picture's own size" title=${KEEP_TIP} />
            <span class="small muted">${p.keep.text}</span>
          </div>` : null}
          ${p.color ? html`<div class="img-keeprow img-colorrow">
            <${Check} checked=${!!p.color.on} onChange=${(v) => call("images.set_color", prevRel, v)}
              label="Correct its colors for the machine" title=${COLOR_TIP} />
            <span class="small muted">${p.color.stock ? "The game's own picture (unlocked): corrected from its original" : p.color.built ? "Your picture from an earlier build: corrected from its uncorrected copy, which goes back when this is off" : p.color.own ? "Set for this picture" : p.color.all ? "Follows the Color profile tab (every replaced picture)" : "Follows the Color profile tab (no replaced picture)"}${p.color.on ? ` · “${p.color.name}” is baked in when you build.` : "."}</span>
          </div>` : null}
        </div>` : null}
        <${Thumb} cls="img-op" path=${p.orig} ver=${p.ver} label="Original" />
        <${Thumb} cls="img-rp" path=${p.rep} ver=${p.ver} empty=${p.empty} label="Replacement" />
      </div>
    </section>

    ${s.note ? html`<p class="small muted img-note">${s.note}</p>` : null}
    ${rename ? html`<${RenameModal} spec=${rename} onClose=${() => setRename(null)} />` : null}
  </div>${colorNs.has_project ? html`<${ColorBar} host="images" startMode="assets" open=${colors} setOpen=${setColors}
    file=${prevRel && p.color ? { kind: "images", rel: prevRel, label: p.rep_name || base(prevRel), on: !!p.color.on,
      attach: { ns: "images" } } : null} />` : null}</div>`;
}
