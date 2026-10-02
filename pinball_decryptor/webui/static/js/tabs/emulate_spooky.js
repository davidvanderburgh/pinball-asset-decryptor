// Emulate (Spooky Pinball): run a Spooky game on this PC from its update file
// - the games the rig runs, which the page names up front.  Python half:
// webui/tabs/emulate_spooky.py.  Laid out as the American Pinball tab is
// (the template every maker's Emulate tab follows): the game file with
// Cache…, Start / Playfield window / Volume, and the status.  The virtual
// playfield is AP's window (tools/spooky_emu/spkpf.py -> tools/ap_emu/appf.py);
// it opens by itself when the game reaches attract.  "Playfield window" is a
// real button, as on the AP and PB tabs: as ghost text beside Stop it read as
// a label, and a player never found the window (PAD-295, PAD-313).

import { html, PageHead, Card, Button, PathField, Chip, Note, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { VolumeControl, StateChip, introLines } from "./emulate_jjp_shared.js";
import { CacheModal } from "./emulate_ap.js";

export const css = true;

export default function EmulateSpooky() {
  const s = useNs("emulate_spooky");
  const shell = useNs("shell");
  const up = !!s.up;
  const cells = s.cells || [];
  const supported = s.supported || [];
  const hist = (shell.path_history || {}).spooky_emulate_file || [];
  // while a start is in flight the button is Cancel
  const stopish = up || !!s.starting;
  const goKind = s.go_busy ? "" : stopish ? "danger" : "primary";
  const footer = html`
    <${Button} kind=${goKind} size="big" icon=${stopish ? "stop" : "play"} busy=${s.go_busy}
      disabled=${!s.go_enabled} onClick=${() => call("emulate_spooky.toggle")}>${s.go_label || "Start"}<//>
    ${up ? html`<${Button} icon="external" title=${s.switches_tip}
      onClick=${() => call("emulate_spooky.switches")}>Playfield window<//>` : null}
    <span class="emu-sp"></span>
    <${VolumeControl} ns="emulate_spooky" s=${s} title=${s.volume_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Game" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <label class="small">Update file</label>
          <${PathField} ns="emulate_spooky" k="file" value=${s.file} title=${s.file_tip} history=${hist}
            placeholder="v2026.09.15.11.beetlejuice, code_UM.pkg… - or a build from Write" onBrowse=${() => call("emulate_spooky.browse")}
            extra=${html`<${Button} kind="ghost" disabled=${!s.rig_ok} onClick=${() => call("emulate_spooky.open_cache")}
              title="Shows and manages what the emulator keeps in the app's Linux: each game unpacked from its update file. Deleting frees the space now; it is unpacked again on the next Start.">Cache…<//>`} />
          <span class="small muted">${s.file_tip}</span>
        <//>
        ${s.note ? html`<${Note} kind="warn">${s.note}<//>` : null}
      </div>
      <div class="stack emu-col">
        <${Card} title="Status" extra=${html`<${StateChip} tone=${s.tone} label=${s.state_label} />`}>
          ${s.state_hint ? html`<div class=${"emu-hint " + (s.tone === "warn" ? "warn" : "")}>${s.state_hint}</div>` : null}
          <div class="kv emu-kv">
            ${cells.map((c) => html`<span class="k">${c.label}</span><span class="mono v">${c.value}</span>`)}
          </div>
        <//>
        <${Card} title="Supported games" cls="spk-supported">
          <div class="spk-games">
            ${supported.map((g) => html`<${Chip} kind="ok" dot>${g}<//>`)}
          </div>
          <span class="small muted">Not yet: Total Nuclear Annihilation (its update cannot be opened yet), or the DMD games (America's Most Haunted, Rob Zombie, Domino's, Jetsons).</span>
        <//>
      </div>
    </div>
    ${s.cache ? html`<${CacheModal} c=${s.cache} ns="emulate_spooky" title="Cache — Spooky Pinball emulator" />` : null}
  </div>`;
}
