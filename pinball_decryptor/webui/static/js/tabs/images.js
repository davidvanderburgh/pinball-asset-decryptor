// Replace Images (the Tk tab's _build_image_tab): scan the project folder
// for image slots, filter and group them, pick / clear / keep-size a
// replacement, and compare the original with it.  Every rule lives in
// webui/tabs/images.py; this is the view.
// PAD-463 (DragonRR): the Video tab's color work on pictures.  The panes draw
// through the color profiles (Preview colors, and Original / With its color
// profile on each), Compare puts up to four pictures side by side beside the
// Colors bar, and several pictures selected are one target for the bar.

import { html, useEffect, useLayoutEffect, useMemo, useRef, useState, PageHead, Button, Field, Select, Seg,
         Check, Chip, Note, Table, Empty, Modal, openMenu, menuOpen, Icon, Spinner, tip, call, mediaUrl, cx }
  from "../core/ui.js";
import { useNs } from "../core/store.js";
import { LookRow } from "../core/look.js";
import { ColorBar, barOpenAtStart, rememberBarOpen } from "./color_pane.js";
import { OriginalsWindow } from "./originals.js";

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
const ORIGINALS_TIP = "Find the files your replacements were made from in a folder of your own, by how they look: the names don't matter.\n\nFor picks that are copies off a card, like the ones \"Transfer Mods to New Version\" takes from an extract of a built card: those pictures were already squeezed into the card's format once by the Write that built that card. With your own files picked instead, the next Write converts from them. Nothing changes until you press Use.";
const CLEAR_TIP = "Drop every replacement picked on this tab in one go — for starting a project over without clearing 48 rows one at a time. It only drops the picks: your own files are untouched, and a slot already built into the project folder keeps the bytes it has (use “Revert all changes…” on the Write tab for those). To clear only some, select the rows — click, then Shift-click or Ctrl-click — and right-click the selection.";
const KEEP_TIP = "Off: the replacement is scaled to the original picture's size, which squeezes a longer name. On: it keeps its own width and height, and the build grows the scene to fit it. The game draws it from the same top-left corner, so a wider picture reaches further right. Needs an image build (not a direct SD write). A picture nothing in its scene draws by size is fitted instead, and the log says so.";
const REP_TIP = "Click to choose a replacement for this image (double-click the row does the same).";
// PAD-312: the chosen-files color profile, baked into this picture as it is staged
const COLOR_TIP = "Green: a color profile is attached to this file. The Color profile tab's individual files profile is baked into it when you build. Red: no color profile is attached; it goes on the card as it is. Blue lock: the game's own picture, never touched (tick Unlock extracted images to give it a palette too). Click a palette to attach or detach it. Select several pictures (Shift-click or Ctrl-click) and pick a profile in the Colors bar to give it to all of them.";
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
      r.cb ? "Your own picture from an earlier build: corrected from its uncorrected copy when you build."
        : r.cg ? "The game's own picture, unlocked: corrected from its original when you build."
        : r.co ? "Set for this picture." : r.c ? "Attached by the old Every replaced picture box, still ticked in this project." : null] });
// PAD-463: Compare, as on the Video tab
const COMPARE_TIP = "Show the selected pictures side by side, big, beside the Color profiles bar: up to 4 (Ctrl-click or Shift-click rows to select them). One picture shows its Original beside its Replacement.\n\nClick a picture there and the bar changes its colors, so you see a profile or a slider on it against the others as you go.";
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
// asked for at the size the box has on screen.  look (PAD-463): the token of the
// colour steps it is drawn through (images.py look.keys / a Compare picture's key).
function Thumb({ path, ver, empty, label, cls = "", look = null }) {
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
    call("images.thumb", path, Math.round((box.w - 8) * dpr), Math.round((box.h - 8) * dpr), look || null).then((r) => {
      if (!alive) return;
      setSrc(r || "");
      setBusy(false);
    });
    return () => { alive = false; };
  }, [path, ver, look, box && box.w, box && box.h]);
  return html`<div class=${cx("thumb img-pic", cls)} ref=${ref} aria-label=${label}>
    ${src ? html`<img src=${src} alt=${label || ""} />`
      : busy ? html`<${Spinner} />`
      : !path && empty ? html`<span class="img-empty small">${empty}</span>` : null}
  </div>`;
}

// PAD-463 (DragonRR): the Video tab's Original / With its color profile switch, on each of
// the two panes: the picture as it is, or drawn through its color profile, attached or not.
// Only the pane changes (images.py set_pane_view); the palette is what attaches it.
const PROFILE_WORDS = "With its color profile";
function PaneView({ side, view, look }) {
  if (!view) return null;
  const filesOn = !!(look.on && (look.sw || {}).files);
  const plainTip = side === "orig" ? "The game's picture without its color profile."
    : "Your replacement as you made it, without its color profile.";
  const options = [
    { value: "plain", label: view.plain, title: { head: view.plain, lines: [plainTip,
      "The other Preview colors switches still apply."] } },
    { value: "profile", label: PROFILE_WORDS, disabled: !filesOn, title: { head: PROFILE_WORDS, lines: [
      { profile: view.name },
      filesOn ? (view.on ? "The picture drawn through the color profile attached to it, as the card gets it."
        : "The picture drawn through its color profile as it would be attached. It is not attached: click its palette for that.")
        : "Tick Individual files under Preview colors to see it.",
      "Only this pane changes: nothing is attached or changed."] } },
  ];
  return html`<div class="row img-view">
    <${Seg} value=${view.view} options=${options} onChange=${(v) => call("images.set_pane_view", side, v)} />
    <span class="small ellip">${!filesOn ? html`<span class="muted">Individual files is off under Preview colors.</span>`
      : html`Color profile: <span class="icm-cp">${view.name}</span>${view.on ? null
        : html`<span class="muted">, not attached</span>`}`}</span>
  </div>`;
}

// ----------------------------------------------------------------- Compare
// PAD-463 (DragonRR): the Video tab's Compare (PAD-440) for pictures: up to four side by
// side, big, beside the Color profiles bar.  Each is drawn through its own colors
// (images.py _cmp_steps), so a profile picked or a slider moved shows on the picture
// clicked, against the others, as it is made.  The picture clicked is the bar's.

// a clear mark on each picture that is the game's own, locked or not
function CmpBadge({ row, cs }) {
  if (!row) return null;
  if (row.cl) return html`<span class="icm-badge locked" ...${tip(colorTip(row, cs))}><${Icon} name="lock" />Locked</span>`;
  if (row.cg && !row.cb && row.c != null) return html`<span class="icm-badge unlocked" ...${tip(colorTip(row, cs))}><${Icon} name="unlock" />Game's own picture</span>`;
  return null;
}

// its palette under it, so a color profile is attached from here as from the list
function CmpColor({ t, row, cs }) {
  if (!row || (row.c == null && !row.cl)) return null;
  if (row.cl) return html`<div class="row icm-color">
    <span class="img-color locked" ...${tip(colorTip(row, cs))}><${Icon} name="lock" /></span>
    <span class="small ellip muted">The game's own picture, locked: tick Unlock extracted images to give it a color profile.</span>
  </div>`;
  const stock = row.cg && !row.cb;
  const line = profileLine(row, cs);
  return html`<div class="row icm-color">
    <button type="button" class=${cx("img-color", row.c ? "on" : "off", row.co && !row.cg && "own")}
      aria-pressed=${row.c ? "true" : "false"} aria-label="Attach or detach this picture's color profile" ...${tip(colorTip(row, cs))}
      onClick=${(e) => { e.stopPropagation(); call("images.set_color", row.r, !row.c); }}><${Icon} name="palette" /></button>
    <span class="small ellip">${!row.c ? "No color profile attached"
      : t.side === "orig" && !stock ? "The original, as it is now."
      : html`Color profile: <span class="icm-cp">${line ? line.profile : ""}</span>`}</span>
  </div>`;
}

function CmpTile({ t, row, cs, active, onPick, canRemove }) {
  const pane = t.pane || {};
  const sides = (t.sides || []).map(([value, label]) => ({ value, label }));
  const name = base(t.rel);
  return html`<div class=${cx("icm-tile", active && "on")}>
    <div class="row icm-tilehd">
      <span class="mono small ellip icm-name" ...${tip({ head: t.rel, lines: [pane.label ? `${pane.title}: ${pane.label}` : pane.title] })}>${name}</span>
      <span class="grow"></span>
      ${sides.length > 1 ? html`<${Seg} value=${t.side} options=${sides} onChange=${(v) => call("images.compare_side", t.id, v)} />`
        : html`<span class="small muted nw">${pane.title || "Original"}</span>`}
      <${Button} size="xs" kind="ghost" icon="x" title="Take this picture out of Compare" disabled=${!canRemove}
        onClick=${() => call("images.compare_remove", t.id)} />
    </div>
    <div class="icm-screen" role="button" tabindex="0" aria-pressed=${active ? "true" : "false"}
        aria-label=${"Pick " + name + " for the Color profiles bar"}
        onClick=${onPick} onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(); } }}
        ...${tip(active ? "The picture the Color profiles bar changes." : "Click: the Color profiles bar changes this picture's colors.")}>
      <${Thumb} cls="icm-pic" path=${pane.path} ver=${t.id} look=${t.key} empty=${pane.path ? "" : "nothing to show"} label=${name} />
      <${CmpBadge} row=${row} cs=${cs} />
    </div>
    <${CmpColor} t=${t} row=${row} cs=${cs} />
  </div>`;
}

function CompareView({ cmp, byRel, cs, look, active, setActive, onOpenColors, unlock, running }) {
  const tiles = cmp.tiles || [];
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.focus({ preventScroll: true }); }, []);
  const close = () => call("images.compare_close");
  const onKey = (e) => { if (e.key === "Escape" && !menuOpen()) { e.stopPropagation(); close(); } };
  const n = tiles.length;
  return html`<div class="page fill img-page icm-page" ref=${ref} tabindex="-1" onKeyDown=${onKey}>
    <section class="card icm" aria-label="Compare pictures">
      <div class="icm-hd">
        <div class="row icm-hdrow">
          <${Icon} name="compare" cls="lg" />
          <span class="h2">Compare</span>
          <span class="grow"></span>
          ${unlock && unlock.offered ? html`<span class="img-unlock">
            <span class="eyebrow">Advanced</span>
            <${Check} checked=${!!unlock.on} onChange=${(v) => call("images.set_color_unlocked", v)} disabled=${running}
              label="Unlock extracted images" cls="small" title=${UNLOCK_TIP} />
          </span>` : null}
          <${Button} kind="ghost" icon="x" onClick=${close} title="Back to the list (Esc)">Close<//>
        </div>
        <div class="small muted">${look.offered
          ? "Click a picture: the Color profiles bar changes its colors while you see the others."
          : "Each picture as it is."}</div>
      </div>
      ${look.offered ? html`<div class="icm-look"><${LookRow} look=${look} ns="images" onOpen=${onOpenColors} /></div>` : null}
      <div class=${cx("icm-grid", "n" + Math.min(n, 4))}>
        ${tiles.map((t) => html`<${CmpTile} key=${t.id} t=${t} row=${byRel.get(t.rel)} cs=${cs} active=${t.id === active}
          onPick=${() => setActive(t.id)} canRemove=${n > 1} />`)}
      </div>
    </section>
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
  // PAD-463: a name under Preview colors opens the bar on that profile
  const openColors = async (mode) => { await call("color.set_mode", mode); setColors(true); };
  const look = s.look || {};
  const cmp = s.compare || {};
  const cmpOpen = !!cmp.open;
  const [cmpActive, setCmpActive] = useState(null);
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
    // PAD-463: the pictures selected, side by side
    const pics = selIds.filter((x) => !String(x).startsWith(GROUP));
    const more = pics.length ? [{ sep: true }, { label: pics.length > 1
      ? `Compare ${Math.min(pics.length, cmp.max || 4)} pictures side by side` : "Compare side by side",
      onClick: () => openCompare(pics) }] : [];
    openMenu(at, items.map((it) => (it.sep ? { sep: true }
      : { label: it.label, disabled: !!it.disabled, onClick: it.act ? () => runAct(it.act, id, selIds) : undefined }))
      .concat(more));
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
  // PAD-463 (DragonRR): the rows by slot path, for the selected pictures' palettes and Compare
  const byRel = useMemo(() => {
    const m = new Map();
    for (const c of chunks) for (const r of c || []) m.set(r.r, r);
    return m;
  }, chunks);
  const picked = () => view.filter((e) => typeof e === "number" && sel.has(idOf(e))).map(idOf);
  // several pictures selected: the bar is on every one of them that is not locked (the one on
  // show named first), and a change gives them all the profile, attached (PAD-462's rule)
  const selOpen = cmpOpen || sel.size < 2 ? [] : picked().map((r) => byRel.get(r)).filter((r) => r && r.c != null);
  const cmpTiles = cmp.tiles || [];
  const activeTile = cmpTiles.find((t) => t.id === cmpActive) || cmpTiles[0] || null;
  let colorFile = null;
  if (cmpOpen) {
    const r = activeTile ? byRel.get(activeTile.rel) : null;
    if (r && r.c != null) {
      colorFile = { kind: "images", rel: r.r, label: !r.cg ? r.p : base(r.r), on: !!r.c,
        attach: { ns: "images" } };
    }
  } else {
    const one = prevRel && p.color ? { rel: prevRel, label: p.rep_name || base(prevRel), on: !!p.color.on }
      : selOpen[0] ? { rel: selOpen[0].r, label: !selOpen[0].cg ? selOpen[0].p : base(selOpen[0].r),
        on: !!selOpen[0].c } : null;
    if (one) {
      colorFile = { kind: "images", ...one, attach: { ns: "images" },
        more: selOpen.filter((r) => r.r !== one.rel).map((r) => r.r) };
    }
  }
  // the selected pictures, in list order, side by side; the Colors bar opens beside them
  async function openCompare(rels) {
    const n = await call("images.compare_open", rels);
    if (!n) return;
    setCmpActive(null);
    if (look.offered && colorNs.has_project && !colors) setColors(true);
  }
  const compareRels = () => {
    const pics = picked();
    return pics.length ? pics : prevRel ? [prevRel] : [];
  };
  const bar = colorNs.has_project ? html`<${ColorBar} host="images" startMode="assets" open=${colors} setOpen=${setColors}
    file=${colorFile} />` : null;
  if (cmpOpen) {
    return html`<div class="cpd-shell"><${CompareView} cmp=${cmp} byRel=${byRel} cs=${colorNs} look=${look}
      active=${activeTile ? activeTile.id : null} setActive=${setCmpActive}
      onOpenColors=${colorNs.has_project ? openColors : undefined} unlock=${s.color_unlock} running=${running} />${bar}</div>`;
  }
  const views = look.offered ? look.views || {} : {};
  const keys = look.offered && look.on ? look.keys || {} : {};
  return html`<div class="cpd-shell"><div class="page img-page">
    <${PageHead} title="Images" sub=${INTRO}>
      ${status ? html`<${Chip} kind=${s.changed ? "acc" : ""}>${status.trim()}<//>` : null}
      ${s.scanning
        ? html`<${Button} icon="x" onClick=${() => call("images.cancel_scan")}>Cancel scan<//>`
        : html`<${Button} icon="refresh" onClick=${() => call("images.scan")}>Scan<//>`}
      <${Button} icon="folder" onClick=${() => call("images.from_folder")} disabled=${running} title=${FOLDER_TIP}>Replace from folder…<//>
      <${Button} icon="search" onClick=${() => call("images.originals_open")} disabled=${running} title=${ORIGINALS_TIP}>Find originals…<//>
      <${Button} icon="compare" cls="img-cmp-open" onClick=${() => openCompare(compareRels())} disabled=${!compareRels().length}
        title=${COMPARE_TIP}>Compare<//>
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
      <div class=${cx("ft img-prev", look.offered && "img-looks")}>
        ${look.offered ? html`<div class="img-lk"><${LookRow} look=${look} ns="images" note=${false}
          onOpen=${colorNs.has_project ? openColors : undefined} /></div>` : null}
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
            <span class="small muted">${p.color.stock ? "The game's own picture (unlocked): corrected from its original" : p.color.built ? "Your picture from an earlier build: corrected from its uncorrected copy, which goes back when this is off" : p.color.own ? "Set for this picture" : p.color.on ? "Attached by the old Every replaced picture box, still ticked in this project" : "Not attached"}${p.color.on ? ` · “${p.color.name}” is baked in when you build.` : "."}</span>
          </div>` : null}
        </div>` : null}
        <${Thumb} cls="img-op" path=${p.orig} ver=${p.ver} look=${keys.orig || null} label="Original" />
        <${Thumb} cls="img-rp" path=${p.rep} ver=${p.ver} look=${keys.rep || null} empty=${p.empty} label="Replacement" />
        ${views.orig || views.rep ? html`<div class="img-ov"><${PaneView} side="orig" view=${views.orig} look=${look} /></div>
          <div class="img-rv"><${PaneView} side="rep" view=${views.rep} look=${look} /></div>` : null}
      </div>
    </section>

    ${s.note ? html`<p class="small muted img-note">${s.note}</p>` : null}
    ${rename ? html`<${RenameModal} spec=${rename} onClose=${() => setRename(null)} />` : null}
    ${s.originals && s.originals.open ? html`<${OriginalsWindow} ns="images" o=${s.originals} />` : null}
  </div>${bar}</div>`;
}
