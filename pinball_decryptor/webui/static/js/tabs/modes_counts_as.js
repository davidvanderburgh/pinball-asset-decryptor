// The Modes tab's "counts as" dialog (item 160): one of the game's OWN rules takes another shot
// for one of its own. Python (webui/modes_stock_remap.py) owns the state (modes.remap); this only
// renders it and calls back.

import { html, useEffect, useState, Modal, Button, Select, Table, Note, tip, cx, call } from "../core/ui.js";

const COUNTS_AS_TIP = "A shot of your choosing counts as one of a rule's own while that rule runs: every Left ramp reaches the battle vs Ebirah as a left spin (200,000 and the count down by one) while its left spinner is still lit, and the LEFT RAMP insert blinks the battle's yellow. One ramp is one spin, so a ramp standing in for a spinner needs the spinner's count of hits (15 on Ebirah's left spinner). The table is saved with this project and put on the card by Write with the modes; with no rows the game's rules play as they always did.";

export function CountsAsDialog({ s, onClose }) {
  const st = s.remap || {};
  const rows = st.rows || [];
  const rules = st.rules || [];
  const shots = st.shots || [];
  const [rule, setRule] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  useEffect(() => { call("modes.remap_refresh"); }, []);
  useEffect(() => {
    if (!rule && rules.length) setRule(String(rules[0].id));
    if (!from && shots.length) setFrom(shots[0]);
    if (!to && shots.length > 1) setTo(shots[1]);
  }, [st.on, rules.length, shots.length]);
  const columns = [
    { key: "label", label: "The game's rule", width: "minmax(170px, 1.2fr)", titleOf: (r) => r.label },
    { key: "from", label: "This shot", width: "minmax(130px, 1fr)", titleOf: (r) => r.from },
    { key: "to", label: "Counts as", width: "minmax(130px, 1fr)", titleOf: (r) => r.to },
    { key: "problem", label: "", width: "minmax(140px, 1.4fr)", titleOf: (r) => r.problem },
  ];
  const canAdd = st.on && rule && from && to;
  const add = () => { if (canAdd) call("modes.remap_add", Number(rule), from, to); };
  return html`<${Modal} title="A shot that counts as one of the game's own" icon="list" xwide onClose=${onClose}
    footer=${html`<${Select} sm width=${190} value=${rule} onChange=${setRule} disabled=${!st.on}
        options=${rules.map((r) => ({ value: String(r.id), label: r.label }))} title="One of the game's own rules this port names." />
      <${Select} sm width=${150} value=${from} onChange=${setFrom} disabled=${!st.on} options=${shots} title="The shot the player makes." />
      <span class="dim">counts as</span>
      <${Select} sm width=${150} value=${to} onChange=${setTo} disabled=${!st.on} options=${shots} title="The rule's own shot it stands in for (one bit)." />
      <${Button} size="sm" kind="primary" disabled=${!canAdd} onClick=${add}>Add<//>
      <${Button} size="sm" disabled=${st.sel == null} onClick=${() => call("modes.remap_delete")}
        title="Take the selected row out.">Remove<//>
      <span class="grow"></span>
      <${Button} onClick=${onClose}>Close<//>`}>
    <div class="small dim wrap" ...${tip(COUNTS_AS_TIP)}>${st.msg}</div>
    ${st.on ? html`<${Table} cls="modes-stock" columns=${columns} rows=${rows} rowKey=${(r) => r.i}
        selected=${st.sel} onSelect=${(r) => call("modes.remap_select", r.i)}
        rowClass=${(r) => cx(r.problem && "readonly")}
        empty="No rows. Pick a rule and two shots below, then Add."
        style="height:min(40vh, 320px)" />` : null}
    ${st.note ? html`<${Note} kind=${/cannot|not a shot|already|Pick/.test(st.note) ? "warn" : "info"}>${st.note}<//>` : null}
  <//>`;
}
