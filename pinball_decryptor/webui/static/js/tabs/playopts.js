// Play options (PAD-1204): what changes how the game plays and keeps Insider Connected - Handicap per player,
// Prolonged Competition and inactivity pausing the timers (the score feed moved to the Network tab) - each with
// room to say what it does. David: the Modes tab's banner made people think every tick there cost them Insider
// Connected, and the ticks were crammed beside the mode list. The state and the actions are the Modes service's
// (the `modes` namespace); webui/tabs/playopts.py asks it to publish them for the project.
import { html, useState, PageHead, Card, Button, Check, Note, Empty, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { HandicapLevelsDialog } from "./modes_dialogs.js";

export const css = true;

function Said({ text, kind }) {
  return text ? html`<span class=${cx("small", kind === "err" ? "err-ink" : "muted")}>${text}</span>` : null;
}

function Option({ title, on, tip, onChange, children }) {
  return html`<${Card} cls="po-opt" title=${title}>
    <p class="po-does">${tip}</p>
    <${Check} checked=${on} wrap label=${title} onChange=${onChange} />
    ${children}
  <//>`;
}

export default function PlayOptionsTab() {
  const p = useNs("playopts");
  const s = useNs("modes");
  const [levels, setLevels] = useState(false);
  const any = s.hand_shown || s.comp_shown || s.idle_shown || s.cvd_shown || s.spk_shown;
  return html`<div class="page po-page">
    <${PageHead} title="Play options" sub=${p.intro} />
    ${p.keeps_ic ? html`<div class="po-note"><${Note} kind="ok"><b>${p.keeps_ic_head}.</b> ${p.keeps_ic}<//></div>` : null}
    ${!p.project ? html`<${Empty} icon="gear" title="No project">${p.none_why}<//>`
      : !any ? html`<${Empty} icon="gear" title="Nothing for this game">None of the play options is offered for this card's game.<//>`
      : html`<div class="po-grid">
        ${s.hand_shown ? html`<${Option} title="Handicap per player" on=${s.hand_on} tip=${s.hand_tip}
            onChange=${(v) => call("modes.set_handicap", v)}>
          <${Said} text=${s.hand_note} kind=${s.hand_note_kind} />
          ${s.hand_on && s.hand_note_kind !== "err" ? html`<div class="row"><${Button} size="sm" icon="list"
            onClick=${() => setLevels(true)}
            title="What each level, -3 to +3, does on this card's game.">Levels…<//></div>` : null}
        <//>` : null}
        ${s.comp_shown ? html`<${Option} title="Prolonged Competition" on=${s.comp_on} tip=${s.comp_tip}
            onChange=${(v) => call("modes.set_prolonged_comp", v)}>
          <${Said} text=${s.comp_note} kind=${s.comp_note_kind} />
        <//>` : null}
        ${s.idle_shown ? html`<${Option} title="Inactivity pauses timers" on=${s.idle_on} tip=${s.idle_tip}
            onChange=${(v) => call("modes.set_idle_pause", v)}>
          <${Said} text=${s.idle_note} kind=${s.idle_note_kind} />
        <//>` : null}
        ${s.cvd_shown ? html`<${Option} title="Color-blind insert colors" on=${s.cvd_on} tip=${s.cvd_tip}
            onChange=${(v) => call("modes.set_colour_blind", v, s.cvd_preset)}>
          <div class="row po-presets" role="group" aria-label="Color-blind preset">
            ${(s.cvd_presets || []).map((p) => html`<label key=${p.key} class="chk">
              <input type="radio" name="po-cvd" checked=${s.cvd_preset === p.key}
                onChange=${() => call("modes.set_colour_blind", s.cvd_on, p.key)} /><span>${p.name}</span></label>`)}
          </div>
          <${Said} text=${s.cvd_note} kind=${s.cvd_note_kind} />
        <//>` : null}
        ${s.spk_shown ? html`<${Option} title="Spoken scores" on=${s.spk_on} tip=${s.spk_tip}
            onChange=${(v) => call("modes.set_spoken_scores", v)}>
          <${Said} text=${s.spk_note} kind=${s.spk_note_kind} />
        <//>` : null}
      </div>`}
    ${levels ? html`<${HandicapLevelsDialog} s=${s} onClose=${() => setLevels(false)} />` : null}
  </div>`;
}
