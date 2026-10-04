// The Color profiles pop-out bar (PAD-350, DragonRR): the Color profile tab's controls on
// the Scenes tab's right edge, so a slider is moved with the scene in view instead of
// remembering how it looked on another tab.  A rainbow tab sticks out of the edge (Blender's
// way); a click slides the bar out over the inspector on the right, so the Scenes preview
// keeps its size.  One tab per profile (the whole screen overlay, the individual files, the machine
// screen); the same sliders, number boxes, presets, ranges, curves, Save a copy and Load as
// the Color profile tab, which they share (ns "color", webui/tabs/color.py).  Each move
// is saved a moment after it is made, and the Scenes editor draws its scene again through it.

import { html, useEffect, Button, Check, Icon, tip, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { Controls, Ranges, CurveEditor, WhichFiles, MODES, MODE_WORDS, useProfile, statusNote } from "./color.js";

for (const href of ["/static/css/tabs/color.css", "/static/css/tabs/color_drawer.css"]) {
  if (typeof document !== "undefined" && !document.querySelector(`link[href="${href}"]`)) {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    document.head.appendChild(l);
  }
}

const OPEN_KEY = "pad.colordrawer.open";

export function drawerOpenAtStart() {
  try { return localStorage.getItem(OPEN_KEY) === "1"; } catch (e) { return false; }
}

const TABS = { display: "Overlay", assets: "Files", screen: "Machine screen" };

// each tab's Preview colors switch on the Scenes preview (js/core/look.js)
const PART = { display: "overlay", assets: "files", screen: "screen" };
const PART_OFF = {
  overlay: "No whole screen overlay is set yet: move a slider or pick a starting point and the preview draws through it.",
  files: "No switched-on file is changed by it yet: switch files on below or on the Images tab, or move a slider.",
  screen: "This screen changes nothing: move a slider or pick a starting point.",
};

// The scene shows the profile on show only while its Preview colors switch is on: the same
// switch, here, so a change is never made blind.
function ShowHere({ mode }) {
  const look = useNs("text_scenes").look;
  if (!look || !look.parts) return null;
  const k = PART[mode];
  const part = look.parts[k] || {};
  const on = !!(look.sw || {})[k];
  return html`<${Check} cls="small cpd-show" checked=${!!(part.set && on)} disabled=${!part.set}
    label="Show it in the Scenes preview"
    title=${part.set ? "The same switch as under Preview colors: untick to see the scene without it. The card is not changed."
      : PART_OFF[k]}
    onChange=${(v) => call("text_scenes.set_look_part", k, v)} />`;
}

// the Scenes editor redraws a moment after a move: sooner than the Color profile tab, whose
// own preview is drawn on the page while the slider moves
const SEND_MS = 120;

export function ColorDrawer({ open, setOpen }) {
  const s = useNs("color");
  const [p, update, setMode] = useProfile(s, SEND_MS);
  // what the bar shows is read again from the project as it opens
  useEffect(() => { if (open) call("color.panel_open"); }, [open]);
  const toggle = () => {
    const next = !open;
    try { localStorage.setItem(OPEN_KEY, next ? "1" : "0"); } catch (e) { /* private mode */ }
    setOpen(next);
  };
  const mode = s.per_file ? (s.mode || "display") : "display";
  return html`<div class=${cx("cpd", open && "open")}>
    <button type="button" class="cpd-handle" aria-expanded=${open ? "true" : "false"} aria-controls="cpd-panel"
        aria-label="Color profiles" onClick=${toggle} ...${tip("Color profiles")}>
      <span class="cpd-handle-ico"><${Icon} name="palette" /></span>
      <span class="cpd-handle-txt">Colors</span>
    </button>
    <div class="cpd-clip"><aside class="cpd-panel" id="cpd-panel" aria-label="Color profiles" aria-hidden=${open ? "false" : "true"}
        inert=${open ? undefined : ""}>
      <div class="cpd-hd">
        <span class="cpd-title">Color profiles</span>
        <span class="sp"></span>
        <${Button} size="xs" kind="ghost" icon="emulate" disabled=${!s.has_project} onClick=${() => call("color.try_emulator")}
          title="See it in the emulator: run this project with these profiles (a running game restarts)" />
        <${Button} size="xs" kind="ghost" icon="x" onClick=${toggle} title="Close the Color profiles bar" />
      </div>
      ${s.per_file ? html`<div class="cpd-tabs" role="tablist">
        ${MODES.map((m) => html`<button type="button" role="tab" key=${m.value} aria-selected=${mode === m.value ? "true" : "false"}
          class=${cx(mode === m.value && "on")} onClick=${() => mode !== m.value && setMode(m.value)} ...${tip(m.title)}>${TABS[m.value]}</button>`)}
      </div>` : null}
      <div class="cpd-body" role="tabpanel">
        <p class="small muted cpd-words">${s.per_file ? MODE_WORDS[mode] || MODE_WORDS.display
          : "Corrects your replaced pictures and videos when you build."}</p>
        ${statusNote(s)}
        <${ShowHere} mode=${mode} />
        ${s.try_note ? html`<div class="small muted">${s.try_note}</div>` : null}
        ${s.per_file && mode === "assets" ? html`<${WhichFiles} s=${s} />` : null}
        <${Controls} s=${s} p=${p} update=${update} />
        <${Ranges} s=${s} p=${p} update=${update} />
        <${CurveEditor} s=${s} p=${p} update=${update} />
      </div>
    </aside></div>
  </div>`;
}
