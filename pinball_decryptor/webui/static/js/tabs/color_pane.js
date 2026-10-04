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

import { html, useEffect, useState, Button, Check, Icon, tip, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { Controls, Ranges, CurveEditor, WhichFiles, MODES, MODE_WORDS, useProfile, statusNote } from "./color.js";

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

export function barOpenAtStart() {
  try { return localStorage.getItem(OPEN_KEY) === "1"; } catch (e) { return false; }
}

export function rememberBarOpen(open) {
  try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch (e) { /* private mode */ }
}

const SHORT = { display: "Overlay", assets: "Files", screen: "Machine screen" };

// each profile's Preview colors switch on the Scenes preview (js/core/look.js)
const PART = { display: "overlay", assets: "files", screen: "screen" };
const PART_OFF = {
  overlay: "No whole screen overlay is set yet: move a slider or pick a starting point and the preview draws through it.",
  files: "No switched-on file is changed by it yet: switch files on below or in Layers, or move a slider.",
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

// The scene shows the profile on show only while its Preview colors switch is on: the same
// switch, here, so a change is never made blind.
function ShowHere({ mode, look }) {
  if (!look || !look.parts) return null;
  const k = PART[mode];
  const part = look.parts[k] || {};
  const on = !!(look.sw || {})[k];
  return html`<${Check} cls="small" checked=${!!(part.set && on)} disabled=${!part.set}
    label="Show it in this preview"
    title=${part.set ? "The same switch as under Preview colors: untick to see the scene without it. The card is not changed."
      : PART_OFF[k]}
    onChange=${(v) => call("text_scenes.set_look_part", k, v)} />`;
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

export function ColorBar({ open, setOpen }) {
  const s = useNs("color");
  const look = useNs("text_scenes").look;
  const [p, update, setMode] = useProfile(s, SEND_MS);
  // what the bar shows is read again from the project as it opens
  useEffect(() => { if (open) call("color.panel_open"); }, [open]);
  const mode = s.per_file ? (s.mode || "display") : "display";
  const parts = (look && look.parts) || {};
  return html`<div class=${cx("cpd", open && "open")}>
    <button type="button" class="cpd-handle" aria-expanded=${open ? "true" : "false"} aria-controls="cpd-panel"
        aria-label="Color profiles" onClick=${() => setOpen(!open)} ...${tip("Color profiles")}>
      <span class="cpd-handle-ico"><${Icon} name="palette" /></span>
      <span class="cpd-handle-txt">Colors</span>
    </button>
    <div class="cpd-clip"><aside class="cpd-panel" id="cpd-panel" aria-label="Color profiles"
        aria-hidden=${open ? "false" : "true"} inert=${open ? undefined : ""}>
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
        <div class="row cpd-show"><${ShowHere} mode=${mode} look=${look} /><span class="sp"></span>
          <${CopyPaste} p=${p} update=${update} mode=${mode} name=${s.name} /></div>
        ${statusNote(s)}
        ${s.try_note ? html`<div class="small muted">${s.try_note}</div>` : null}
        ${s.per_file && mode === "assets" ? html`<${WhichFiles} s=${s} />` : null}
        <${Controls} s=${s} p=${p} update=${update} />
        <${Ranges} s=${s} p=${p} update=${update} />
        <${CurveEditor} s=${s} p=${p} update=${update} />
      </div>
    </aside></div>
  </div>`;
}
