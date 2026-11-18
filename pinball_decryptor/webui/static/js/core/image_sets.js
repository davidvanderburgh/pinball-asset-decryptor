// The themes picker (Simon, 2026-11-18; "image sets" in the code): "a drop down ... which would let the user switch
// between ... sets. The first option would be the main set, then SET 2 and so on". Simplified with him: a theme is the
// project's PICTURES, each picture chosen and colour profiled per theme; nothing else (no scene layout, no clips). On
// the Images tab only (Python: webui/tabs/image_sets.py, namespace "imgsets"). Theme 1 is the project as it is; each
// other theme starts the same as theme 1 and holds only what differs. Behind an Advanced switch (ThemesSwitch: "hide
// ... behind an advanced curtain because to a new user it will be very hard to understand"), so a project that never
// switches themes on shows none of it. SetPicker goes in the toolbar, SetStrip above the list, so a change made in
// another theme never looks like a change to the project itself.
import { html, useState, Select, Button, Field, Modal, Note, Check, call } from "./ui.js";
import { useNs } from "./store.js";

const MANAGE = "__manage";
const PICK_TIP = "Which theme you are looking at and changing. Theme 1 is the project as it is; each other theme "
  + "starts the same as theme 1 and keeps only the pictures you change while it is picked. The operator chooses the "
  + "theme in the game's service menu (Image Set); it takes effect on the next power up.";
const SWITCH_TIP = "Themes: other versions of the game's pictures (a dark and a light Battle Select, say), each picture "
  + "chosen and colour profiled per theme. The operator picks one in the service menu. Off, none of it shows.";

// the Advanced switch (Images tab): themes on for this project
export function ThemesSwitch() {
  const s = useNs("imgsets");
  if (!s.on) return null;
  return html`<span title=${!s.can_off && s.enabled ? "Remove the other themes first (Manage themes)" : SWITCH_TIP}>
    <${Check} checked=${!!s.enabled} disabled=${s.enabled && !s.can_off} label="Themes"
      onChange=${(v) => call("imgsets.set_enabled", v)} /></span>`;
}

export function SetPicker({ cls = "" }) {
  const s = useNs("imgsets");
  const [managing, setManaging] = useState(false);
  if (!s.on || !s.enabled) return null;
  const names = s.names || [];
  const options = names.map((n, i) => ({ value: String(i + 1), label: `Theme ${i + 1}: ${n}` }))
    .concat([{ value: MANAGE, label: names.length > 1 ? "Manage themes…" : "Add a theme…" }]);
  const change = (v) => {
    if (v === MANAGE) setManaging(true);
    else call("imgsets.pick", Number(v));
  };
  return html`<span class=${`imgsets-pick ${cls}`}>
    <${Select} sm value=${String(s.current || 1)} options=${options} onChange=${change} title=${PICK_TIP} />
    ${managing ? html`<${ManageSets} onClose=${() => setManaging(false)} />` : null}
  </span>`;
}

// Above the Images tab's list while a theme other than theme 1 is picked: what this theme keeps, and what still
// changes theme 1
const STRIP_NOTE = " Choose… and Clear work on this theme's pictures (pictures in scenes only). Replace from folder, "
  + "groups, Keep size and colour profiles still change theme 1.";

export function SetStrip() {
  const s = useNs("imgsets");
  if (!s.on || !s.enabled || (s.current || 1) === 1) return null;
  const name = (s.names || [])[(s.current || 1) - 1] || "";
  return html`<div class="imgsets-strip"><${Note} kind="warn" action=${html`<${Button} size="sm"
      onClick=${() => call("imgsets.pick", 1)}>Back to theme 1<//>`}>
    <b>Editing theme ${s.current}: ${name}.</b> The pictures you choose now are for this theme only; anything you
    leave alone is the same as theme 1.${STRIP_NOTE}<//></div>`;
}

function ManageSets({ onClose }) {
  const s = useNs("imgsets");
  const [fresh, setFresh] = useState("");
  const names = s.names || [];
  const full = names.length >= (s.most || 8);
  const add = async () => {
    const got = await call("imgsets.add", fresh.trim());
    if (got && got.ok) setFresh("");
  };
  return html`<${Modal} title="Themes" icon="images" onClose=${onClose}
      footer=${html`<${Button} kind="primary" onClick=${onClose}>Done<//>`}>
    <p class="small muted">Theme 1 is the project as it is. Each other theme starts the same as theme 1; while it is
      picked, the pictures you choose are kept for it alone. The operator picks a theme in the game's service menu
      (Image Set); it takes effect on the next power up. At most ${s.most || 8} themes.</p>
    ${s.why ? html`<${Note} kind="err">${s.why}<//>` : null}
    <div class="imgsets-list">
      ${names.map((n, i) => html`<div class="imgsets-row" key=${`${i}:${n}`}>
        <span class="imgsets-num mono">${i + 1}</span>
        <${Field} sm value=${n} maxLength=${24} width=${220} title="Its name, as the service menu's help line shows it"
          onChange=${() => {}} onCommit=${(v) => { if (v.trim() && v.trim() !== n) call("imgsets.rename", i + 1, v.trim()); }} />
        ${i === 0 ? html`<span class="small muted">the project as it is</span>` : html`<span class="imgsets-acts">
          <${Button} size="sm" kind="ghost" icon="up" title="Move up" disabled=${i < 2}
            onClick=${() => call("imgsets.move", i + 1, i)} />
          <${Button} size="sm" kind="ghost" icon="down" title="Move down" disabled=${i === names.length - 1}
            onClick=${() => call("imgsets.move", i + 1, i + 2)} />
          <${Button} size="sm" kind="ghost" icon="trash" title="Remove this theme and every picture chosen for it"
            onClick=${() => call("imgsets.remove", i + 1)} />
        </span>`}
      </div>`)}
    </div>
    <div class="imgsets-add">
      <${Field} sm value=${fresh} placeholder=${`Theme ${names.length + 1}`} maxLength=${24} width=${220}
        disabled=${full} onChange=${setFresh} onCommit=${() => {}} />
      <${Button} size="sm" icon="plus" disabled=${full} onClick=${add}>Add a theme<//>
      ${full ? html`<span class="small muted">That is the most the service menu can offer.</span>` : null}
    </div>
  <//>`;
}
