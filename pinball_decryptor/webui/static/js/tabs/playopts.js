// Play options (PAD-1204): what changes how the game plays or reports and keeps Insider Connected - Handicap per
// player, Prolonged Competition, the score feed and inactivity pausing the timers - on a tab of their own, each with
// room to say what it does. David: the Modes tab's banner made people think every tick there cost them Insider
// Connected, and the ticks were crammed beside the mode list. The state and the actions are the Modes service's
// (the `modes` namespace); webui/tabs/playopts.py asks it to publish them for the project.
import { html, useState, PageHead, Card, Button, Field, Check, Note, Empty, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { HandicapLevelsDialog } from "./modes_dialogs.js";

export const css = true;

// David: "I'd like to see the sample API contract for the scores API" - what the machine sends your server after a
// game, and what it expects back (plugins/stern/score_feed.py contract(): the runtime's own format)
function FeedContract({ c }) {
  const [open, setOpen] = useState(false);
  if (!c) return null;
  return html`<div class="po-contract">
    <button type="button" class="po-contract-hd" aria-expanded=${open} onClick=${() => setOpen(!open)}>
      ${open ? "▾" : "▸"} What your server receives (API contract)</button>
    ${open ? html`<div class="po-contract-bd">
      <div class="lbl">The request, one per game</div>
      <pre class="mono po-pre">${c.request}</pre>
      <div class="lbl">The body, laid out</div>
      <pre class="mono po-pre">${c.body}</pre>
      <div class="lbl">Fields</div>
      <table class="po-fields"><thead><tr><th>Field</th><th>Type</th><th>What it holds</th></tr></thead>
        <tbody>${(c.fields || []).map((f) => html`<tr key=${f.name}><td class="mono">${f.name}</td>
          <td class="muted">${f.type}</td><td>${f.what}</td></tr>`)}</tbody></table>
      <div class="lbl">Your server's answer</div>
      <p class="small">${c.answer}</p>
    </div>` : null}
  </div>`;
}

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
  const any = s.hand_shown || s.comp_shown || s.feed_shown || s.idle_shown;
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
        ${s.feed_shown ? html`<${Option} title="Score feed" on=${s.feed_on} tip=${s.feed_tip}
            onChange=${(v) => call("modes.set_score_feed", v)}>
          ${s.feed_on ? html`<div class="po-field"><span class="lbl">Your server's address</span>
            <${Field} value=${s.feed_url} mono placeholder=${s.feed_placeholder} title=${s.feed_url_tip}
              bad=${s.feed_note_kind === "err"} onChange=${() => {}} onCommit=${(v) => call("modes.set_score_feed", true, v)} /></div>` : null}
          <${Said} text=${s.feed_note} kind=${s.feed_note_kind} />
          <${FeedContract} c=${s.feed_contract} />
        <//>` : null}
        ${s.idle_shown ? html`<${Option} title="Inactivity pauses timers" on=${s.idle_on} tip=${s.idle_tip}
            onChange=${(v) => call("modes.set_idle_pause", v)}>
          <${Said} text=${s.idle_note} kind=${s.idle_note_kind} />
        <//>` : null}
      </div>`}
    ${levels ? html`<${HandicapLevelsDialog} s=${s} onClose=${() => setLevels(false)} />` : null}
  </div>`;
}
