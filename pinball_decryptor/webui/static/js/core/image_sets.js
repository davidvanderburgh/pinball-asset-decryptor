// The image sets picker (Simon, 2026-11-18): "a drop down ... which would let the user switch between video (etc.)
// sets. The first option would be the main set, then SET 2 and so on". ONE choice shared by the Images, Video and
// Scenes tabs (Python: webui/tabs/image_sets.py, namespace "imgsets"): set 1 is the project as it is; set 2 and up
// start empty (the same as set 1) and hold only what differs. SetPicker goes in a tab's toolbar, SetStrip above its
// list, so a change made in another set never looks like a change to the project itself.
import { html, useState, Select, Button, Field, Modal, Note, call } from "./ui.js";
import { useNs } from "./store.js";

const MANAGE = "__manage";
const PICK_TIP = "Which image set you are looking at and changing. Set 1 is the project as it is; each other set "
  + "starts the same as set 1 and keeps only what you change while it is picked. The operator chooses the set in the "
  + "game's service menu (Image Set).";

export function SetPicker({ cls = "" }) {
  const s = useNs("imgsets");
  const [managing, setManaging] = useState(false);
  if (!s.on) return null;
  const names = s.names || [];
  const options = names.map((n, i) => ({ value: String(i + 1), label: `Set ${i + 1}: ${n}` }))
    .concat([{ value: MANAGE, label: names.length > 1 ? "Manage sets…" : "Add a set…" }]);
  const change = (v) => {
    if (v === MANAGE) setManaging(true);
    else call("imgsets.pick", Number(v));
  };
  return html`<span class=${`imgsets-pick ${cls}`}>
    <${Select} sm value=${String(s.current || 1)} options=${options} onChange=${change} title=${PICK_TIP} />
    ${managing ? html`<${ManageSets} onClose=${() => setManaging(false)} />` : null}
  </span>`;
}

// The tabs whose changes already go to the picked set (the rest still change set 1: said on the strip, so nothing
// made while trying the picker lands somewhere unexpected)
const WIRED = new Set(["images"]);
// what the strip says is per set on a wired tab, beyond its own words (the tab's other tools still change set 1)
const WIRED_NOTE = {
  images: " Choose… and Clear work on this set's pictures (scene pictures only). Replace from folder, groups, Keep size and colour still change set 1.",
};

// Above a tab's list while a set other than set 1 is picked
export function SetStrip({ what = "changes", tab = "" }) {
  const s = useNs("imgsets");
  if (!s.on || (s.current || 1) === 1) return null;
  const name = (s.names || [])[(s.current || 1) - 1] || "";
  return html`<div class="imgsets-strip"><${Note} kind="warn" action=${html`<${Button} size="sm"
      onClick=${() => call("imgsets.pick", 1)}>Back to set 1<//>`}>
    ${WIRED.has(tab) ? html`<b>Editing set ${s.current}: ${name}.</b> The ${what} now are for this set only;
      anything you leave alone is the same as set 1.${WIRED_NOTE[tab] || ""}` : html`<b>Set ${s.current}: ${name} is picked.</b> This tab does
      not keep changes per set yet: anything you change here still changes set 1.`}<//></div>`;
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
  return html`<${Modal} title="Image sets" icon="images" onClose=${onClose}
      footer=${html`<${Button} kind="primary" onClick=${onClose}>Done<//>`}>
    <p class="small muted">Set 1 is the project as it is. Each other set starts the same as set 1; while it is picked,
      the pictures, clips and scene changes you make are kept for it alone. The operator picks a set in the game's
      service menu (Image Set). At most ${s.most || 8} sets.</p>
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
          <${Button} size="sm" kind="ghost" icon="trash" title="Remove this set and everything made for it"
            onClick=${() => call("imgsets.remove", i + 1)} />
        </span>`}
      </div>`)}
    </div>
    <div class="imgsets-add">
      <${Field} sm value=${fresh} placeholder=${`Set ${names.length + 1}`} maxLength=${24} width=${220}
        disabled=${full} onChange=${setFresh} onCommit=${() => {}} />
      <${Button} size="sm" icon="plus" disabled=${full} onClick=${add}>Add a set<//>
      ${full ? html`<span class="small muted">That is the most the service menu can offer.</span>` : null}
    </div>
  <//>`;
}
