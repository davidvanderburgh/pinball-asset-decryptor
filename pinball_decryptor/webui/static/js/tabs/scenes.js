// The Scenes tab (PAD-251): every scene of the card as the machine draws it, and the scene
// editor.  Python: webui/tabs/scenes.py (ns "scenes": which project shows) and
// webui/text_scenes.py (ns "text_scenes": the scenes themselves, ScenesPage).

import { html, useState, PageHead, Empty, Spinner } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { ScenesPage, ScenesActions } from "./text_scenes.js";
import { ColorDrawer, drawerOpenAtStart } from "./color_drawer.js";

const INTRO = "Each scene of the card, drawn the way the machine draws it. Click a picture or a line of text to move, resize, recolour, hide or re-layer it, or add your own; Write puts it on the card. Preview colors change only the preview: the card is not changed.";

export default function ScenesTab() {
  const p = useNs("scenes");
  const s = useNs("text_scenes");
  // PAD-350: the Color profiles bar on the right edge, open as it was left
  const [colors, setColors] = useState(drawerOpenAtStart);
  let body;
  if (p.empty === "no_project") {
    body = html`<${Empty} title="No project folder yet" icon="folder">Extract a Stern Spike 2 card on the Extract tab (or open a project) and its scenes show here.<//>`;
  } else if (p.empty === "unavailable") {
    body = html`<${Empty} title="The scenes could not open" icon="warn">The details are in the session log.<//>`;
  } else if (!s.alive) {
    body = html`<div class="row scenes-opening"><${Spinner} /><span class="muted">Opening the scenes…</span></div>`;
  } else {
    body = html`<${ScenesPage} />`;
  }
  const page = html`<div class="page scenes-page">
    <${PageHead} title="Scenes" sub=${INTRO}><${ScenesActions} /><//>
    ${body}
  </div>`;
  return html`<div class="cpd-shell">${page}${!p.empty && s.alive
    ? html`<${ColorDrawer} open=${colors} setOpen=${setColors} />` : null}</div>`;
}
