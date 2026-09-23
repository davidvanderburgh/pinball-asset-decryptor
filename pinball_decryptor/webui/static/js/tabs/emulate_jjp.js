// Emulate (Jersey Jack): run a JJP game on this PC.  Python half:
// webui/tabs/emulate_jjp.py (the Tk panel was gui/jjp_emulate_tab.py).

import { html, PageHead, Card, Button, PathField, Chip, Note, call } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { VolumeControl, StateChip, introLines } from "./emulate_jjp_shared.js";

export const css = true;

export default function EmulateJJP() {
  const s = useNs("emulate_jjp");
  const shell = useNs("shell");
  const up = !!s.up;
  const cells = s.cells || [];
  const hist = (shell.path_history && shell.path_history.jjp_emulate_iso) || [];
  // the spinner is Start's own (a start or stop in flight); a WSL restart
  // only greys Start and spins on Fix stuck state
  const goKind = s.go_busy ? "" : up ? "danger" : "primary";
  const footer = html`
    <${Button} kind=${goKind} size="big" icon=${up ? "stop" : "play"} busy=${s.go_busy}
      disabled=${!s.go_enabled} onClick=${() => call("emulate_jjp.toggle")}>${s.go_label || "Start"}<//>
    <${Button} kind="ghost" title=${s.fix_tip} disabled=${!s.fix_enabled} busy=${s.fix_busy}
      onClick=${() => call("emulate_jjp.fix_state")}>${s.fix_label || "Fix stuck state"}<//>
    <span class="emu-sp"></span>
    <${VolumeControl} ns="emulate_jjp" s=${s} title=${s.volume_tip} />`;
  return html`<div class="page emu-page">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Game ISO" cls="emu-src"
          extra=${s.game ? html`<${Chip} kind="ok" dot>${s.game}<//>` : null} footer=${footer}>
          <${PathField} ns="emulate_jjp" k="iso" value=${s.iso} title=${s.iso_tip} history=${hist}
            placeholder="A JJP release ISO (Clonezilla image)" onBrowse=${() => call("emulate_jjp.browse")} />
          <span class="small muted">${s.iso_tip}</span>
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
      </div>
    </div>
  </div>`;
}
