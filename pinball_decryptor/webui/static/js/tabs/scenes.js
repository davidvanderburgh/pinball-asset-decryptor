// The Scenes tab (PAD-251): every scene of the card as the machine draws it, and the scene
// editor.  Python: webui/tabs/scenes.py (ns "scenes": which project shows) and
// webui/text_scenes.py (ns "text_scenes": the scenes themselves, ScenesPage).

import { html, useState, PageHead, Empty, Spinner, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { ScenesPage, ScenesActions } from "./text_scenes.js";
import { ColorBar, barOpenAtStart, rememberBarOpen } from "./color_pane.js";

const INTRO = "Each scene of the card, drawn the way the machine draws it. Click a picture or a line of text to move, resize, recolour, hide or re-layer it, or add your own; Write puts it on the card. Preview colors change only the preview: the card is not changed.";

export default function ScenesTab() {
  const p = useNs("scenes");
  const s = useNs("text_scenes");
  // PAD-350: the Color profiles bar on the right edge, open as it was left
  const [colors, setColorsState] = useState(() => barOpenAtStart("scenes"));
  const setColors = (v) => { setColorsState(v); rememberBarOpen(v, "scenes"); };
  // a name under Preview colors opens the bar on its profile
  const openColors = async (mode) => { await call("color.set_mode", mode); setColors(true); };
  const ready = !p.empty && s.alive;
  // PAD-368: the layer clicked, whose picture's own profile the bar shows (one with a switch)
  const t = s.tree_view;
  const lay = t && t.sel != null ? (t.layers || []).find((l) => l.id === t.sel) : null;
  const c = lay && lay.color;
  // PAD-438: a line of text has one too (kind "text"); a line in a font with colors of its
  // own shows that font picture's (kind "images"); PAD-451: the font's, on all its pictures
  const file = c && !c.locked && c.rel ? { kind: c.kind || "images", rel: c.rel,
    label: c.shared ? c.font || lay.name : lay.name, on: !!c.on,
    attach: { ns: "scenes", node: lay.id }, font: c.shared ? c.font || "its font" : null,
    pages: c.shared ? c.pages || null : null } : null;
  let body;
  if (p.empty === "no_project") {
    body = html`<${Empty} title="No project folder yet" icon="folder">Extract a Stern Spike 2 card on the Extract tab (or open a project) and its scenes show here.<//>`;
  } else if (p.empty === "unavailable") {
    body = html`<${Empty} title="The scenes could not open" icon="warn">The details are in the session log.<//>`;
  } else if (!s.alive) {
    body = html`<div class="row scenes-opening"><${Spinner} /><span class="muted">Opening the scenes…</span></div>`;
  } else {
    body = html`<${ScenesPage} colorsOpen=${colors} openColors=${openColors} />`;
  }
  return html`<div class="cpd-shell"><div class="page scenes-page">
    <${PageHead} title="Scenes" sub=${INTRO}><${ScenesActions} /><//>
    ${body}
  </div>${ready ? html`<${ColorBar} host="scenes" open=${colors} setOpen=${setColors} file=${file} />` : null}</div>`;
}
