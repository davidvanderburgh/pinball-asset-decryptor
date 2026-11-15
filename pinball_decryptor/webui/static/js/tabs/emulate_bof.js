// Emulate (Barrels of Fun): run a BoF game on this PC.  Python half:
// webui/tabs/emulate_bof.py.  The machine's switches are a window of their
// own (tools/bof_emu/bofpf.py), as the Stern and JJP rigs' are; it opens by
// itself when the game is ready, and "Switches window" brings it back.

import { html, PageHead, Card, Button, PathField, Chip, Note, Check, Select, Seg, tip, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { StateChip, introLines } from "./emulate_jjp_shared.js";

export const css = true;

// PAD-1308: a cabinet with a screen per display.  The setting is
// tools/spike2_emu/vpx/padsplit.py's (shared with the Visual Pinball kit);
// each change is saved at once and applies when the game next starts.
function CabinetScreens({ sp, tipText }) {
  const set = (k) => (v) => call("emulate_bof.split_set", k, v);
  const off = !sp.on;
  return html`<${Card} title="Cabinet screens" cls="emu-split">
    <${Check} checked=${!!sp.on} onChange=${set("on")} title=${tipText}
      label="Show each display on its own screen" />
    <div class="kv emu-split-kv">
      <span class="k">Main display</span>
      <${Select} sm value=${sp.main} options=${sp.mons} onChange=${set("main")} disabled=${off} />
      <span class="k" ...${tip("The strip over the playfield on Dune and Labyrinth; the reflected display on Winchester.")}>Second display</span>
      <${Select} sm value=${sp.second} options=${sp.mons} onChange=${set("second")} disabled=${off} />
      <span class="k">Picture</span>
      <${Seg} value=${sp.fit} onChange=${set("fit")} disabled=${off}
        options=${[{ value: "keep", label: "Keep its shape" }, { value: "fill", label: "Fill the screen" }]} />
    </div>
    <span class="small muted">${tipText}</span>
  <//>`;
}

export default function EmulateBoF() {
  const s = useNs("emulate_bof");
  const shell = useNs("shell");
  const up = !!s.up;
  const cells = s.cells || [];
  const hist = (shell.path_history && shell.path_history.bof_emulate_fun) || [];
  // while a start is in flight the button is Cancel
  const stopish = up || !!s.starting;
  const goKind = s.go_busy ? "" : stopish ? "danger" : "primary";
  const footer = html`
    <${Button} kind=${goKind} size="big" icon=${stopish ? "stop" : "play"} busy=${s.go_busy}
      disabled=${!s.go_enabled} onClick=${() => call("emulate_bof.toggle")}>${s.go_label || "Start"}<//>
    ${up ? html`<${Button} kind="ghost" title=${s.switches_tip}
      onClick=${() => call("emulate_bof.switches")}>Switches window<//>` : null}
    <span class="emu-sp"></span>
    <${Check} ns="emulate_bof" k="mute" checked=${!!s.mute} label="Mute" title=${s.sound_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Game file" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <${PathField} ns="emulate_bof" k="fun" value=${s.fun} title=${s.fun_tip} history=${hist}
            placeholder="dune.fun, winchester.fun, lab.fun - or a build from Write" onBrowse=${() => call("emulate_bof.browse")} />
          <span class="small muted">${s.fun_tip}</span>
        <//>
        ${s.split ? html`<${CabinetScreens} sp=${s.split} tipText=${s.split_tip} />` : null}
        ${s.note ? html`<${Note} kind="warn">${s.note}<//>` : null}
      </div>
      <div class="stack emu-col">
        <${Card} title="Status" extra=${html`<${StateChip} tone=${s.tone} label=${s.state_label} />`}>
          ${s.state_hint ? html`<div class=${"emu-hint " + (s.tone === "warn" ? "warn" : "")}>${s.state_hint}</div>` : null}
          <div class="kv emu-kv">
            ${cells.map((c) => html`<span class="k">${c.label}</span><span class="mono v">${c.value}</span>`)}
          </div>
        <//>
      </div>
    </div>
  </div>`;
}
