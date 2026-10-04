// PAD-330: the preview's three colour switches, the same row on the Scenes
// preview and the Video tab's players.  Each switch turns one step of "as on
// the machine" on or off - the whole screen overlay, the individual files
// correction, the machine screen - so a user can flip them and see what each
// one does.  Only the preview changes: nothing staged for the card moves.
// Each name opens the Color profile tab in that mode.  Python: the tab's
// set_look_part RPC and core/colour_profile.py preview_parts.

import { html, Check, call, cx } from "./ui.js";

const TIPS = {
  overlay: "The whole screen overlay: one correction the game draws over everything on the screen, your files included. Untick to see the preview without it. The card still gets it.",
  files: "The individual files correction, baked into the files you switch on. Untick to see those files without it. The card still gets it.",
  by_overlay: "Recommended leaves your files as they are while the whole screen overlay is Recommended: the overlay already corrects them. Pick No change on the overlay to correct only your files.",
  screen: "The machine's screen: how it changes what it is given. Untick to see what is sent to the screen instead of what it shows.",
};

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

async function openColor(mode) {
  await call("color.set_mode", mode);
  call("ui.select_tab", "color");
}

// note=false leaves out the "Preview only" line: the Scenes tab says it in its page head
// (PAD-349) to make room for its advanced box beside the row.  onOpen(mode): a name opens its
// profile there instead (the Scenes tab's Color profiles bar, PAD-350)
export function LookRow({ look, ns, note = true, onOpen }) {
  if (!look || !look.parts) return null;
  const sw = look.sw || {};
  const p = look.parts;
  const items = [
    { k: "overlay", mode: "display", label: "Whole screen overlay",
      name: p.overlay.set ? p.overlay.name : "none set", set: p.overlay.set },
    { k: "files", mode: "assets", label: "Individual files",
      name: p.files.set ? `${p.files.name}, on ${plural(p.files.count, "file")}`
        : !p.files.count ? "no file switched on"
        : p.files.by_overlay ? "Done by the overlay" : "No change",
      set: p.files.set, tip: p.files.by_overlay && !p.files.set ? TIPS.by_overlay : "" },
    { k: "screen", mode: "screen", label: "Machine screen",
      name: p.screen.name || "No change", set: p.screen.set },
  ];
  const anyOn = items.some((it) => it.set && sw[it.k]);
  return html`<div class=${cx("look-row", anyOn && "on")} role="group" aria-label="Preview colors">
    <span class="look-head">Preview colors</span>
    ${items.map((it) => html`<span key=${it.k} class=${cx("look-item", !it.set && "unset")}>
      <${Check} checked=${!!(it.set && sw[it.k])} disabled=${!it.set} label=${it.label} cls="small"
        title=${it.tip || TIPS[it.k]} onChange=${(v) => call(ns + ".set_look_part", it.k, v)} />
      <button type="button" class="look-name" title=${onOpen ? "Change it in the Color profiles bar, beside the scene" : "Open it on the Color profile tab"}
        onClick=${() => (onOpen ? onOpen(it.mode) : openColor(it.mode))}>${it.name}</button>
    </span>`)}
    ${note ? html`<span class="look-note">Preview only: the card is not changed.</span>` : null}
  </div>`;
}
