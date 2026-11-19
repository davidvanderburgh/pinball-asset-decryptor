// The Scenes tab's Color profiles bar (PAD-350, DragonRR): the Color profile tab's controls
// beside the scene, so a slider is moved with the scene in view instead of remembering how
// it looked on another tab.  A rainbow tab sticks out of the page's right edge (Blender's
// way); a click slides the bar out and pushes the page aside, and the scene list steps out
// of the way while it is open (scenes.js, text_scenes.js ScenesPage), so the preview and
// Layers, with each picture's color switch, stay in view.  One tab per profile, a dot on
// those in use; Copy / Paste carry one profile's numbers to another.  The same presets,
// sliders, number boxes, ranges, curves, Save a copy and Load as the Color profile tab,
// which they share (ns "color", webui/tabs/color.py).  Each move is saved a moment after
// it is made and the Scenes editor draws its scene again through it.
// PAD-354 (DragonRR): Undo / Redo (and Ctrl+Z) for the profile on show, a status note that
// keeps its size as the starting points are clicked, and a divider on the bar's edge to
// make it wider or narrower (kept across sessions, double-click puts it back).
// PAD-364 (DragonRR): the same bar on the Images and Video tabs (host="images" / "video"),
// so a profile is picked from the Saved profiles list and tuned with each file's own
// color switch in view there too.  It is the one set of profiles wherever it is opened:
// a change made here is the change made in Scenes or on the Color profile tab.  Each tab
// remembers whether its bar was left open; the width is shared.  On Images and Video the
// bar opens on Files the first time, the profile their Color column attaches.
// PAD-368 (DragonRR): one profile per file.  A file clicked (a picture, a clip, a layer) with
// the bar open, or the bar opened with one clicked, turns the bar to Files on THAT file: it
// shows the profile baked into it now, and a change gives it a profile of its own.  "Same as
// the other files" puts it back on the project's individual files profile.
// PAD-439 (DragonRR): on the Images and Video tabs, "Apply to all images / videos" gives
// every file there the profile of the one on show, attached, after an "Are you sure?"
// (color.py apply_to_all); Undo / Redo take the whole of it back as one step.
// PAD-462 (DragonRR): two of them: "Apply to all profiled videos", the ones with a color
// profile attached, and "Apply to all videos", every one not locked, attached.  Several
// clips selected on the Video tab are one target (file.count): a change gives them all
// the profile, attached.
// PAD-463 (DragonRR): the Images tab the same: several pictures selected are one target, and
// its panes draw through the profiles, so the bar there has "Show it in this preview" too.
// The Which files card's boxes are All images / All videos (color.js WhichFiles).
// PAD-514 (DragonRR): on a line of text in Scenes, a Font text color row: Default, or the
// color the Font bar gave the line (drawn in exactly it, the profile no longer changing it),
// and a word that lines of text can be colored directly there.

import { html, useEffect, useRef, useState, Button, Check, Icon, Seg, tip, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { Controls, Ranges, CurveEditor, WhichFiles, WhichFilesNotes, EVERY_KINDS, MODES, MODE_WORDS, useProfile, statusNote,
  UndoRedo, undoKey } from "./color.js";

for (const href of ["/static/css/tabs/color.css", "/static/css/tabs/color_pane.css"]) {
  if (typeof document !== "undefined" && !document.querySelector(`link[href="${href}"]`)) {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    document.head.appendChild(l);
  }
}

const OPEN_KEY = "pad.colorbar.open";
const CLIP_KEY = "pad.colorbar.clip";
const WIDTH_KEY = "pad.colorbar.width";
const WIDTH_MIN = 300, WIDTH_MAX = 900;

function loadWidth() {
  try { const w = Number(localStorage.getItem(WIDTH_KEY)); return w > 0 ? w : null; } catch (e) { return null; }
}

function saveWidth(w) {
  try { if (w) localStorage.setItem(WIDTH_KEY, String(w)); else localStorage.removeItem(WIDTH_KEY); } catch (e) { /* private mode */ }
}

// the most the bar may take: the page keeps room for the preview beside it
const widthLimit = () => Math.max(WIDTH_MIN, Math.min(WIDTH_MAX,
  (typeof window !== "undefined" ? window.innerWidth : 1600) - 620));
const clampWidth = (w) => Math.round(Math.max(WIDTH_MIN, Math.min(widthLimit(), w)));

// The divider on the bar's left edge: drag it (or the arrow keys) for a wider or narrower bar.
function Grip({ barRef, width, setWidth }) {
  const drag = useRef(false);
  const down = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    drag.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    barRef.current && barRef.current.classList.add("sizing");
  };
  const move = (e) => {
    const el = barRef.current;
    if (!drag.current || !el) return;
    const r = el.getBoundingClientRect();
    const k = r.width ? el.offsetWidth / r.width : 1;     // the app can be zoomed
    setWidth(clampWidth((r.right - e.clientX) * k));
  };
  const up = () => {
    if (!drag.current) return;
    drag.current = false;
    barRef.current && barRef.current.classList.remove("sizing");
    setWidth((w) => { saveWidth(w); return w; });
  };
  const key = (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const cur = width || (barRef.current ? barRef.current.offsetWidth : 380);
    const w = clampWidth(cur + (e.key === "ArrowLeft" ? 1 : -1) * (e.shiftKey ? 64 : 16));
    setWidth(w);
    saveWidth(w);
  };
  const reset = () => { setWidth(null); saveWidth(null); };
  return html`<div class="cpd-grip" role="separator" tabIndex="0" aria-orientation="vertical"
    aria-label="Color profiles width" title="Color profiles width: drag to resize, double-click to put it back"
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}
    onDblClick=${reset} onKeyDown=${key}><span></span></div>`;
}

// each host keeps its own "left open" (Scenes keeps the key it had before PAD-364)
const openKey = (host) => (host && host !== "scenes" ? OPEN_KEY + "." + host : OPEN_KEY);

export function barOpenAtStart(host) {
  try { return localStorage.getItem(openKey(host)) === "1"; } catch (e) { return false; }
}

export function rememberBarOpen(open, host) {
  try { localStorage.setItem(openKey(host), open ? "1" : "0"); } catch (e) { /* private mode */ }
}

// Where the bar hangs (PAD-364): which preview its "Show it in this preview" switch is, and
// where the file switches are (PAD-463: the Images tab's panes draw through the profiles too).
const HOSTS = {
  scenes: { lookNs: "text_scenes", files: "switch files on below or in Layers, or move a slider.", what: "the scene" },
  video: { lookNs: "video", files: "switch clips on below or in the Color column, or move a slider.", what: "the players" },
  images: { lookNs: "images", files: "switch pictures on in the Color column, or move a slider.", what: "the pictures" },
};

// the hosts whose bar has opened on its startMode this page load (once each, so a bar
// left open and found open again as the tab is shown keeps the profile it was on)
const STARTED = {};

const SHORT = { display: "Overlay", assets: "Files", screen: "Machine screen" };

// each profile's Preview colors switch on the Scenes preview (js/core/look.js)
const PART = { display: "overlay", assets: "files", screen: "screen" };
const PART_OFF = {
  overlay: "No whole screen overlay is set yet: move a slider or pick a starting point and the preview draws through it.",
  files: "No switched-on file is changed by it yet: ",
  screen: "This screen changes nothing: move a slider or pick a starting point.",
};

// the Scenes editor redraws a moment after a move: sooner than the Color profile tab, whose
// own preview is drawn on the page while the slider moves
const SEND_MS = 120;

// what Copy keeps: every number of a profile, not its name (the one pasted into keeps its own)
const FIELDS = ["gamma", "gain", "lift", "saturation", "brightness", "contrast", "ranges", "curves"];

function loadClip() {
  try { return JSON.parse(localStorage.getItem(CLIP_KEY) || "null"); } catch (e) { return null; }
}

// Simon (2026-11-19): the bar's own "Show it in this preview" is gone - the same switch is in the Preview colours
// bar beside every preview (js/core/look.js), so the bar no longer repeats it.

// Copy this profile's numbers; Paste them into the one on show (its name stays)
function CopyPaste({ p, update, mode, name }) {
  const [clip, setClip] = useState(loadClip);
  const copy = () => {
    const c = { from: `${SHORT[mode]}: ${name || "No change"}`, values: {} };
    for (const k of FIELDS) c.values[k] = JSON.parse(JSON.stringify(p[k]));
    try { localStorage.setItem(CLIP_KEY, JSON.stringify(c)); } catch (e) { /* kept for this page only */ }
    setClip(c);
  };
  return html`<${Button} size="xs" icon="copy" onClick=${copy}
      title=${`Copy every number of this profile (${SHORT[mode]}), its color ranges and curves too, to paste into another profile`}>Copy<//>
    <${Button} size="xs" disabled=${!clip} onClick=${() => clip && update(JSON.parse(JSON.stringify(clip.values)))}
      title=${clip ? `Paste ${clip.from} into this profile (${SHORT[mode]}). Its name stays.`
        : "Copy a profile first"}>Paste<//>`;
}

// PAD-439: the words of Apply to all, by the kind of file, on the hosts that list them
// (PAD-471: lines of text, in Scenes; PAD-566 (DragonRR): a picture in Scenes too, as on
// the Images tab)
const ALL_WORDS = {
  images: ["image's", "images", "image"],
  videos: ["video's", "videos", "video"],
  text: ["line's", "lines of text", "line of text"],
};
const ALL_HOSTS = { images: ["images"], video: ["videos"], scenes: ["text", "images"] };
// PAD-462 (DragonRR, round 2): Apply to all's tooltip in his words, exactly as he wrote them
// (Images: the same, of images)
const ALL_TIP = (one, many) => `This will change all of your unlocked ${many} to the profile you have selected below in this tab. This may mean that every single ${one} existing and replaced will be affected. You can undo this function`;
// PAD-471: lines of text, in the same words; a line is the game's own or added, not replaced
const TEXT_ALL_TIP = "This will change all of your unlocked lines of text to the profile you have selected below in this tab. This may mean that every single line of text, the game's own and the ones you added, in every scene will be affected. You can undo this function";

// The file the bar is on (PAD-368), whether it has a profile of its own, and copying its profile to other files
// (PAD-439 / PAD-462). Simon (2026-11-19): one panel, the same on the Images, Video and Scenes tabs, with what does
// not apply greyed out rather than missing - "SELECTED" and the file (or NONE) in boxes, "THEME" and the theme in
// boxes (Images and Scenes only), and one copy action with its choices spelled out, asked first with a WARNING.
const COPY_WHICH = { profiled: "With a profile attached", all: "All" };

// (Simon: "if a filename is really long then truncate but pop out the full name if mouse over ... Ditto with the
// Theme name": the value box ends in "..." where it is cut, and its tooltip is the whole of it)
function Tagged({ tag, value, off, title, none, full }) {
  return html`<div class=${cx("row cpd-tagrow", off && "cpd-off")} title=${title || ""}>
    <span class="cpd-tag">${tag}</span>
    <span class=${cx("cpd-val mono", none && "cpd-none")} title=${full || value}>${value}</span></div>`;
}

function FileLine({ s, host, tools }) {
  const f = s.file;
  const sets = useNs("imgsets");
  const [which, setWhich] = useState("profiled");
  const [where, setWhere] = useState("this");
  const [toKind, setToKind] = useState(host === "video" ? "videos" : "images");
  const [summary, setSummary] = useState({ n: 0, text: "" });
  const n = f ? (f.count || 1) : 0;
  const kind = f ? f.kind : (host === "video" ? "videos" : "images");
  const words = ALL_WORDS[kind] || ALL_WORDS.images;
  // themes: pictures on the Images and Scenes tabs (Simon: "Theme applies in scenes and images only")
  const names = sets.names || [];
  const themesOn = !!(sets.on && sets.enabled && names.length > 1);
  const themeHost = host === "images" || host === "scenes";
  const m = f ? /^@(\d+):/.exec(f.rel || "") : null;
  const t = m ? Number(m[1]) : 1;
  const themeLive = themeHost && themesOn && kind === "images";
  const themeValue = !themeHost ? "not on this tab" : !themesOn ? "off" : kind !== "images" ? "pictures only"
    : `${t}: ${names[t - 1] || ""}`;
  const label = f ? String(f.label || "").replace(/ \(theme \d+\)$/, "") : "NONE";
  const shared = `“${s.asset_name || "Recommended"}”`;
  const own = f ? (n > 1 ? (f.own_n || 0) > 0 : !!f.own) : false;
  const status = !f ? "Nothing selected: click a file to give it a profile of its own, or copy the shared files profile below."
    : t > 1 ? (own ? `It has a profile of its own in this theme (“${s.name || ""}”).`
      : "It uses theme 1's profile. Change anything below and it gets a profile of its own in this theme only.")
    : own ? (n > 1 ? `${f.own_n === n ? "Each has" : `${f.own_n} of them have`} a profile of their own.`
      : `It has a profile of its own (“${s.name || ""}”).`)
    : `It uses the individual files profile (${shared}), like the other files. A change here gives it one of its own.`;
  // Simon: the reset buttons always there, across the panel, greyed where they do not apply
  const canShared = !!(f && own && t === 1);
  const canTheme1 = !!(f && own && t > 1);
  const canEvery = !!(f && themeLive);
  const reset = html`<div class="cpd-resets">
    <${Button} size="xs" disabled=${!canShared} onClick=${() => call("color.file_shared", "this")}
      title=${canShared ? `Drop its own profile: it gets the individual files profile every other file gets (${shared})`
        : "Only for a file with a profile of its own, in theme 1"}>Same as the other files<//>
    <${Button} size="xs" disabled=${!canTheme1} onClick=${() => call("color.file_shared", "this")}
      title=${canTheme1 ? "Drop this theme's own profile for it: it uses theme 1's again"
        : "Only for a picture with a profile of its own in theme 2 or up"}>Reset to theme 1<//>
    <${Button} size="xs" disabled=${!canEvery} onClick=${() => call("color.file_shared", "all")}
      title=${canEvery ? `Drop its own profile in every theme, theme 1 too: it gets the individual files profile (${shared}) everywhere`
        : "Only for a picture, with themes on"}>Reset in every theme<//>
  </div>`;

  // ---- Copy (Simon: one copy action, the same every time, what cannot be done greyed with the reason) ----
  // From: the selected file's profile (PAD-439 Apply to all) or the shared files profile (PAD-463 All images / videos
  // / text, which needs no file selected - as the Which files card did)
  const source = f ? "file" : "shared";
  const fileKinds = f && (ALL_HOSTS[host] || []).includes(f.kind) ? [f.kind] : [];
  const kinds = source === "file" ? fileKinds : EVERY_KINDS().map((e) => e.k);
  const to = source === "file" ? (fileKinds[0] || kind) : toKind;
  const toWords = ALL_WORDS[to] || ALL_WORDS.images;
  const canCopy = source === "file" ? fileKinds.length > 0 : true;
  const whichOk = source === "file";                    // the shared profile goes to every file not locked (All)
  const scope = whichOk ? which : "all";
  const themesOk = source === "file" && themeLive;
  const themes = themesOk ? where : "this";
  useEffect(() => {
    let live = true;
    if (!canCopy) { setSummary({ n: 0, text: "" }); return undefined; }
    call("color.copy_preview", source, to, scope, themes).then((r) => {
      if (live) setSummary({ n: (r && r.n) || 0, text: (r && r.text) || "" });
    });
    return () => { live = false; };
  }, [source, to, scope, themes, f && f.rel, f && f.own, s.name, s.asset_name, canCopy]);
  const tipAll = f && f.kind === "text" ? TEXT_ALL_TIP : ALL_TIP(toWords[2], toWords[1]);
  const copyTip = !canCopy ? "Copying is not offered for this file here"
    : source === "shared" ? { head: `Give every ${toWords[2]} the shared files profile`, lines: [{ profile: s.asset_name || "Recommended" },
      `Every ${toWords[2]} that is not locked gets it, attached. A ${toWords[2]} with a color profile of its own loses it.`,
      "You are asked first. Undo puts them all back."] }
    : scope === "all" ? tipAll
      : { head: `Copy this ${toWords[0]} color profile to every profiled ${toWords[2]}`, lines: [{ profile: s.name || "Recommended" },
        `Every ${toWords[2]} ${f.kind === "text" ? "in every scene" : host === "scenes" ? "on the Images tab" : "on this tab"} with a color profile attached gets this one, in place of the one it has now.`,
        `A ${toWords[2]} with no color profile attached is left as it is.`, "You are asked first. Undo puts them all back."] };
  const doCopy = () => (source === "shared" ? call("color.apply_to_all", "all", to)
    : call("color.apply_to_all", which, null, themes));
  const kindLabel = { images: "Images", videos: "Videos", text: "Text" };
  // Simon: "match up the look and feel of the SELECTED and THEME with the Copy from, to which kind and so on ...
  // as columnized as possible, box sizes the same" - one grid: a tag column, then six equal columns; three choices
  // take two each, two choices three each, "With profile attached" four and "All" two
  const opt = (key, label, { on, disabled, title, span, onClick }) => html`<button type="button" key=${key}
      class=${cx("cpd-opt", on && "on")} style=${`grid-column: span ${span}`} disabled=${!!disabled}
      onClick=${onClick} ...${tip(title || "")}>${label}</button>`;
  const tag = (word, off) => html`<span class=${cx("cpd-tag", off && "cpd-off")}>${word}</span>`;
  const value = (text, full, { none, off } = {}) => html`<span class=${cx("cpd-val mono", none && "cpd-none",
      off && "cpd-off")} style="grid-column: span 6" title=${full || text}>${text}</span>`;
  // Simon: "Lets make the profile area its own panel ... and the same with selected and theme (one panel for those)"
  return html`<div class="cpd-file cpd-sel">
    <div class="cpd-grid">
      ${tag("SELECTED")}
      ${value(f && n > 1 ? `${label} and ${n - 1} more` : label,
        f ? `${label}${n > 1 ? ` and ${n - 1} more` : ""}\n${String(f.rel || "").replace(/^@\d+:/, "")}` : "Nothing selected",
        { none: !f })}
      ${tag("THEME", !themeLive)}
      ${value(themeValue, themeLive ? `Theme ${themeValue}\nThe theme picked on the Images tab: what you change here is this theme's`
        : "Themes are for pictures, on the Images and Scenes tabs, once switched on (Advanced)", { off: !themeLive })}
    </div>
    <div class="small muted cpd-status-line">${status}</div>
  </div>
  ${tools}
  <div class="cpd-file cpd-resetpanel">${reset}</div>
  <div class="cpd-file cpd-copy">
      <div class="eyebrow">Copy a profile to other files</div>
      <div class="cpd-grid">
        ${tag("COPY FROM")}
        ${opt("file", "Selected file", { on: source === "file", disabled: !f, span: 3, onClick: () => {},
          title: f ? "The profile of the file selected above" : "Select a file first" })}
        ${opt("shared", "Shared profile", { on: source === "shared", disabled: !!f, span: 3, onClick: () => {},
          title: f ? "Click away from the file (nothing selected) to give the shared files profile to every file of a kind"
            : `The individual files profile every file without one of its own gets (${shared})` })}
        ${tag("TO KIND")}
        ${["images", "videos", "text"].map((k) => opt(k, kindLabel[k], { on: to === k, disabled: !kinds.includes(k), span: 2,
          onClick: () => setToKind(k),
          title: kinds.includes(k) ? "" : source === "file" ? `A ${words[2]}'s profile is copied to other ${words[1]}` : "" }))}
        ${tag("WHICH", !whichOk)}
        ${opt("profiled", "With profile attached", { on: scope === "profiled", disabled: !whichOk, span: 4,
          onClick: () => setWhich("profiled"), title: whichOk ? `Only ${toWords[1]} whose colour switch is on`
            : "The shared profile goes to every file that is not locked (All)" })}
        ${opt("all", "All", { on: scope === "all", disabled: !whichOk, span: 2, onClick: () => setWhich("all"),
          title: `Every ${toWords[2]} that is not locked: with Unlock extracted ticked (Advanced) that is every one, otherwise the ones replaced or added` })}
        ${tag("THEMES", !themesOk)}
        ${opt("this", "This theme", { on: themes !== "all", disabled: !themesOk, span: 3, onClick: () => setWhere("this"),
          title: themesOk ? `Theme ${t} (${names[t - 1] || ""}) only` : "Themes are for a file's own profile, on pictures, with themes on" })}
        ${opt("every", "Every theme", { on: themes === "all", disabled: !themesOk, span: 3, onClick: () => setWhere("all"),
          title: "Theme 1 and every other theme too" })}
      </div>
      ${summary.text ? html`<div class="small cpd-summary">${summary.text}</div>` : null}
      <div class="cpd-actions">
        ${/* Simon: APPLY NOW on the left, the count on the right, equal halves; the count in the tags' colour and font */""}
        <span class="cpd-applywrap" ...${tip(copyTip)}><button type="button"
          class="cpd-apply" disabled=${!canCopy} onClick=${doCopy}>APPLY</button></span>
        <span class="cpd-tag cpd-counttag"
          title=${`${canCopy ? `${summary.n} ${summary.n === 1 ? toWords[2] : toWords[1]}` : "Nothing to apply"}. You are asked first, with a WARNING, and Undo puts them all back.`}>${canCopy
          ? `${summary.n} ${summary.n === 1 ? "ASSET" : "ASSETS"}` : "NONE"}</span>
      </div>
    ${!f ? html`<${WhichFilesNotes} s=${s} />` : null}
  </div>`;
}

// PAD-514: a line of text's own color (line: its font.colour, with game for a score panel
// line the game paints), and the way to the Font bar where it is set
function TextColorLine({ line, openFont }) {
  const own = line.own && !line.game;
  return html`<div class="cpd-file cpd-textcol">
    <div class="row cpd-file-hd">
      <span class="eyebrow nw">Font text color</span>
      ${own ? html`<span class="cpd-textcol-sw" style=${`background:${line.hex}`}></span>
          <span class="mono small">${line.hex}</span>`
        : html`<span class="cpd-textcol-def small">${line.game ? "Painted by the game" : "Default"}</span>`}
      <span class="sp"></span>
      ${openFont ? html`<${Button} size="xs" icon="text" onClick=${openFont}
        title="Open the Font bar on this line: its Color sets the line's own color">Font bar<//>` : null}
    </div>
    <div class="small muted">${line.game
      ? "The game paints this line's color as it plays: pick it in the Font bar (or under Selected)."
      : own ? "This line has its own color, set in the Font bar, so the color profile does not change it. Default there puts the profile back."
      : "Lines of text can be colored directly in the Font bar. A color set there is drawn exactly and takes the color profile off that line."}</div>
  </div>`;
}

// host: "scenes" (the default), "images" or "video" (PAD-364).  startMode: the profile the
// bar opens on the first time it is opened here (Images and Video: "assets", the one their
// Color column attaches); after that it opens where it was left.  file (PAD-368): the file
// clicked on the host, {kind, rel, label, on, attach, more}, or null (PAD-462: more, the other
// files selected with it that are not locked).  cls: more classes for the bar
// (Scenes: "cpd-beside" while its Font bar is open, PAD-452, so this tab hangs from that one).
// line, openFont (Scenes, PAD-514): the line of text selected, its own color, and the Font bar.
export function ColorBar({ open, setOpen, host = "scenes", startMode = null, file = null, cls = "",
  line = null, openFont = null }) {
  const s = useNs("color");
  const h = HOSTS[host] || HOSTS.scenes;
  const lookState = useNs(h.lookNs || "color");
  const look = h.lookNs ? lookState.look : null;
  const [p, update, setMode, flush] = useProfile(s, SEND_MS);
  const [width, setWidth] = useState(loadWidth);
  const barRef = useRef(null);
  // what the bar shows is read again from the project as it opens
  useEffect(() => {
    if (!open) return;
    if (startMode && !STARTED[host] && s.per_file) {
      STARTED[host] = true;
      call("color.set_mode", startMode).then(() => call("color.panel_open"));
    } else call("color.panel_open");
  }, [open]);
  // the file clicked: the bar's Files mode is its profile while the bar is open here
  const fileKey = file ? `${file.kind}\n${file.rel}\n${file.on}\n${(file.more || []).join("\n")}` : "";
  useEffect(() => {
    if (!open || !s.per_file) return;
    if (file) call("color.set_file", file.kind, file.rel, file.label || "", file.on, file.attach || null, file.more || []);
    else call("color.set_file");
  }, [open, fileKey, s.per_file]);
  useEffect(() => () => { call("color.set_file"); }, []);
  const mode = s.per_file ? (s.mode || "display") : "display";
  const tools = html`<div class="cpd-file cpd-tools"><div class="eyebrow">File Colour Profile Tools</div>
    <div class="cpd-four"><${UndoRedo} s=${s} flush=${flush} size="xs" kind="" />
      <${CopyPaste} p=${p} update=${update} mode=${mode} name=${s.name} /></div></div>`;
  // the dots: the host's Preview colors row where it has one, else the profiles' own word
  const parts = (look && look.parts) || s.parts || {};
  return html`<div class=${cx("cpd", open && "open", cls)} ref=${barRef}
      style=${width ? `--cpd-w:${clampWidth(width)}px` : ""}>
    <button type="button" class="cpd-handle" aria-expanded=${open ? "true" : "false"} aria-controls="cpd-panel"
        aria-label="Color profiles" onClick=${() => setOpen(!open)}
        ...${tip({ head: "Color profiles", lines: [host === "scenes"
          ? "The Color profile tab's controls beside the scene: tune a profile with the scene and its Layers in view."
          : `The Color profile tab's controls beside the list: pick a saved profile and tune it with each ${host === "video" ? "clip's" : "picture's"} own color switch in view. The same profiles as the Scenes and Color profile tabs.`] })}>
      <span class="cpd-handle-ico"><${Icon} name="palette" /></span>
      <span class="cpd-handle-txt">Colors</span>
    </button>
    <div class="cpd-clip"><aside class="cpd-panel" id="cpd-panel" aria-label="Color profiles"
        aria-hidden=${open ? "false" : "true"} inert=${open ? undefined : ""}
        onKeyDown=${(e) => undoKey(e, flush)}>
      ${open ? html`<${Grip} barRef=${barRef} width=${width} setWidth=${setWidth} />` : null}
      <div class="cpd-hd">
        <span class="cpd-title">Color profiles</span>
        <span class="sp"></span>
        <${Button} size="xs" kind="ghost" icon="palette" onClick=${() => call("ui.select_tab", "color")}
          title="The Color profile tab: the same profiles with a test card, a before/after wipe and what each one does" />
        <${Button} size="xs" kind="ghost" icon="emulate" disabled=${!s.has_project} onClick=${() => call("color.try_emulator")}
          title="See it in the emulator: run this project with these profiles (a running game restarts)" />
        <${Button} size="xs" kind="ghost" icon="x" onClick=${() => setOpen(false)} title="Close the Color profiles bar" />
      </div>
      ${s.per_file ? html`<div class="cpd-tabs" role="tablist">
        ${MODES.map((m) => {
          const used = !!(parts[PART[m.value]] || {}).set;
          return html`<button type="button" role="tab" key=${m.value} aria-selected=${mode === m.value ? "true" : "false"}
            class=${cx(mode === m.value && "on", m.value === "display" && "cpd-apart")} onClick=${() => mode !== m.value && setMode(m.value)}
            ...${tip({ head: SHORT[m.value] + (used ? ": in use" : ": changes nothing yet"), lines: [m.title] })}>
            ${SHORT[m.value]}${used ? html`<span class="cpd-dot" aria-label="in use"></span>` : null}</button>`;
        })}
      </div>` : null}
      <div class="cpd-body" role="tabpanel">
        <p class="small muted cpd-words">${s.per_file ? MODE_WORDS[mode] || MODE_WORDS.display
          : "Corrects your replaced pictures and videos when you build."}</p>
        ${/* Simon (2026-11-19): the profile's own tools in a panel of their own, four equal boxes - under the Selected
             panel in Files, where the bar has one; first in the other modes */""}
        ${s.per_file && mode === "assets" ? html`<${FileLine} s=${s} host=${host} tools=${tools} />` : tools}
        ${line ? html`<${TextColorLine} line=${line} openFont=${openFont} />` : null}
        <div class="cpd-status">${statusNote(s, line && line.own && !line.game ? line.hex : null)}</div>
        ${s.try_note ? html`<div class="small muted">${s.try_note}</div>` : null}
        <${Controls} s=${s} p=${p} update=${update} />
        <${Ranges} s=${s} p=${p} update=${update} />
        <${CurveEditor} s=${s} p=${p} update=${update} />
      </div>
    </aside></div>
  </div>`;
}
