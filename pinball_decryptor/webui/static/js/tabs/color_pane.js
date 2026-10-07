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

import { html, useEffect, useRef, useState, Button, Check, Icon, tip, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { Controls, Ranges, CurveEditor, WhichFiles, MODES, MODE_WORDS, useProfile, statusNote,
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
// where the file switches are.  Images has no preview that draws through the profiles, so
// the bar there has no such switch.
const HOSTS = {
  scenes: { lookNs: "text_scenes", files: "switch files on below or in Layers, or move a slider." },
  video: { lookNs: "video", files: "switch clips on below or in the Color column, or move a slider." },
  images: { lookNs: null, files: "" },
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

// The scene (or the Video tab's players) shows the profile on show only while its Preview
// colors switch is on: the same switch, here, so a change is never made blind.
function ShowHere({ mode, look, host }) {
  const h = HOSTS[host] || HOSTS.scenes;
  if (!h.lookNs || !look || !look.parts) return null;
  const k = PART[mode];
  const part = look.parts[k] || {};
  const on = !!(look.sw || {})[k];
  const what = host === "video" ? "the players" : "the scene";
  return html`<${Check} cls="small" checked=${!!(part.set && on)} disabled=${!part.set}
    label="Show it in this preview"
    title=${part.set ? `The same switch as under Preview colors: untick to see ${what} without it. The card is not changed.`
      : k === "files" ? PART_OFF.files + h.files : PART_OFF[k]}
    onChange=${(v) => call(h.lookNs + ".set_look_part", k, v)} />`;
}

// Copy this profile's numbers; Paste them into the one on show (its name stays)
function CopyPaste({ p, update, mode, name }) {
  const [clip, setClip] = useState(loadClip);
  const copy = () => {
    const c = { from: `${SHORT[mode]}: ${name || "No change"}`, values: {} };
    for (const k of FIELDS) c.values[k] = JSON.parse(JSON.stringify(p[k]));
    try { localStorage.setItem(CLIP_KEY, JSON.stringify(c)); } catch (e) { /* kept for this page only */ }
    setClip(c);
  };
  return html`<div class="row cpd-clipbtns">
    <${Button} size="xs" icon="copy" onClick=${copy}
      title=${`Copy every number of this profile (${SHORT[mode]}), its color ranges and curves too, to paste into another profile`}>Copy<//>
    <${Button} size="xs" disabled=${!clip} onClick=${() => clip && update(JSON.parse(JSON.stringify(clip.values)))}
      title=${clip ? `Paste ${clip.from} into this profile (${SHORT[mode]}). Its name stays.`
        : "Copy a profile first"}>Paste<//>
  </div>`;
}

// The file the bar is on (PAD-368): its name, and whether it has a profile of its own.
function FileLine({ s }) {
  const f = s.file;
  if (!f) return null;
  // PAD-438: a line of text in Scenes has one too
  const what = f.kind === "text" ? "This line of text" : "This file";
  return html`<div class="cpd-file">
    <div class="row cpd-file-hd"><span class="eyebrow nw">${what}</span>
      <span class="mono small ellip" title=${f.rel}>${f.label}</span></div>
    <div class="row cpd-file-own">${f.own
      ? html`<span class="small muted grow">It has a color profile of its own.</span>
        <${Button} size="xs" onClick=${() => call("color.file_shared")}
          title=${`Drop this file's own profile: it gets the individual files profile every other file gets (“${s.asset_name || "Recommended"}”)`}>Same as the other files<//>`
      : html`<span class="small muted">${`Same as the other files (“${s.asset_name || "Recommended"}”). A change here gives it a profile of its own.`}</span>`}</div>
  </div>`;
}

// host: "scenes" (the default), "images" or "video" (PAD-364).  startMode: the profile the
// bar opens on the first time it is opened here (Images and Video: "assets", the one their
// Color column attaches); after that it opens where it was left.  file (PAD-368): the file
// clicked on the host, {kind, rel, label, on, attach}, or null.
export function ColorBar({ open, setOpen, host = "scenes", startMode = null, file = null }) {
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
  const fileKey = file ? `${file.kind}\n${file.rel}\n${file.on}` : "";
  useEffect(() => {
    if (!open || !s.per_file) return;
    if (file) call("color.set_file", file.kind, file.rel, file.label || "", file.on, file.attach || null);
    else call("color.set_file");
  }, [open, fileKey, s.per_file]);
  useEffect(() => () => { call("color.set_file"); }, []);
  const mode = s.per_file ? (s.mode || "display") : "display";
  // the dots: the host's Preview colors row where it has one, else the profiles' own word
  const parts = (look && look.parts) || s.parts || {};
  return html`<div class=${cx("cpd", open && "open")} ref=${barRef}
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
            class=${cx(mode === m.value && "on")} onClick=${() => mode !== m.value && setMode(m.value)}
            ...${tip({ head: SHORT[m.value] + (used ? ": in use" : ": changes nothing yet"), lines: [m.title] })}>
            ${SHORT[m.value]}${used ? html`<span class="cpd-dot" aria-label="in use"></span>` : null}</button>`;
        })}
      </div>` : null}
      <div class="cpd-body" role="tabpanel">
        <p class="small muted cpd-words">${s.per_file ? MODE_WORDS[mode] || MODE_WORDS.display
          : "Corrects your replaced pictures and videos when you build."}</p>
        <div class="row cpd-show"><${ShowHere} mode=${mode} look=${look} host=${host} /><span class="sp"></span>
          <${UndoRedo} s=${s} flush=${flush} size="xs" />
          <${CopyPaste} p=${p} update=${update} mode=${mode} name=${s.name} /></div>
        ${s.per_file && mode === "assets" ? html`<${FileLine} s=${s} />` : null}
        <div class="cpd-status">${statusNote(s)}</div>
        ${s.try_note ? html`<div class="small muted">${s.try_note}</div>` : null}
        ${s.per_file && mode === "assets" && !s.file ? html`<${WhichFiles} s=${s} />` : null}
        <${Controls} s=${s} p=${p} update=${update} />
        <${Ranges} s=${s} p=${p} update=${update} />
        <${CurveEditor} s=${s} p=${p} update=${update} />
      </div>
    </aside></div>
  </div>`;
}
