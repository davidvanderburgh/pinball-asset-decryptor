// The Scenes inspector's Colors view (PAD-350, DragonRR): the Color profile tab's controls
// beside the scene, so a slider is moved with the scene in view instead of remembering how
// it looked on another tab.  A third view next to Layers and Contents (text_scenes.js
// TreeTop); the Preview colors names under the scene open it on their profile.  The same
// profiles, presets, sliders, number boxes, ranges, curves, Save a copy and Load as the Color
// profile tab, which they share (ns "color", webui/tabs/color.py), made narrower.  Each move
// is saved a moment after it is made and the Scenes editor draws its scene again through it.

import { html, useEffect, Button, Check, Seg, call } from "../core/ui.js";
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

const SHORT = { display: "Overlay", assets: "Files", screen: "Machine screen" };

// each profile's Preview colors switch on the Scenes preview (js/core/look.js)
const PART = { display: "overlay", assets: "files", screen: "screen" };
const PART_OFF = {
  overlay: "No whole screen overlay is set yet: move a slider or pick a starting point and the preview draws through it.",
  files: "No switched-on file is changed by it yet: switch files on below or on the Images tab, or move a slider.",
  screen: "This screen changes nothing: move a slider or pick a starting point.",
};

// the Scenes editor redraws a moment after a move: sooner than the Color profile tab, whose
// own preview is drawn on the page while the slider moves
const SEND_MS = 120;

// The scene shows the profile on show only while its Preview colors switch is on: the same
// switch, here, so a change is never made blind.
function ShowHere({ mode }) {
  const look = useNs("text_scenes").look;
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

export function ColorPane() {
  const s = useNs("color");
  const [p, update, setMode] = useProfile(s, SEND_MS);
  // read again from the project as the view opens
  useEffect(() => { call("color.panel_open"); }, []);
  const mode = s.per_file ? (s.mode || "display") : "display";
  return html`<div class="scenes-contents cpane" role="region" aria-label="Color profiles">
    <div class="cpane-hd">
      ${s.per_file ? html`<${Seg} value=${mode} onChange=${(v) => v !== mode && setMode(v)}
        options=${MODES.map((m) => ({ value: m.value, label: SHORT[m.value], title: m.title }))} />` : null}
      <p class="small muted cpane-words">${s.per_file ? MODE_WORDS[mode] || MODE_WORDS.display
        : "Corrects your replaced pictures and videos when you build."}</p>
      <${ShowHere} mode=${mode} />
    </div>
    ${statusNote(s)}
    ${s.try_note ? html`<div class="small muted">${s.try_note}</div>` : null}
    ${s.per_file && mode === "assets" ? html`<${WhichFiles} s=${s} />` : null}
    <${Controls} s=${s} p=${p} update=${update} />
    <${Ranges} s=${s} p=${p} update=${update} />
    <${CurveEditor} s=${s} p=${p} update=${update} />
    <div class="row wrap cpane-ft">
      <${Button} size="sm" kind="ghost" icon="palette" onClick=${() => call("ui.select_tab", "color")}
        title="The Color profile tab: the same profiles with a test card, a before/after wipe and what each one does">Color profile tab<//>
      <${Button} size="sm" kind="ghost" icon="emulate" disabled=${!s.has_project} onClick=${() => call("color.try_emulator")}
        title="Run this project in the emulator with these profiles (a running game restarts)">See it in the emulator<//>
    </div>
  </div>`;
}
