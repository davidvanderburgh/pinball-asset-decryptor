// The Modes tab's "Rewrite in C" dialog (item 161): one CODE row per rule of the game's own, and an
// action that starts a rewrite from the SDK's template. Python (webui/modes_stock_rewrite.py) owns
// the state (modes.rewrite); this only renders it and calls back.

import { html, useEffect, Modal, Button, Table, Note, tip, cx, call } from "../core/ui.js";

const REWRITE_TIP = "The game's own rules (a battle, a multiball) are compiled into the game. A rewrite is a code mode of this project whose C runs INSTEAD of one rule's shot handler: what a shot does is yours (which shots, in what order, what they pay), while the rule's start, clock, screens and ending stay the game's own. It starts from the SDK's example for the rule, builds and writes like every code mode, and with the folder gone the rule plays as it always did.";

export function RewriteDialog({ s, onClose }) {
  const st = s.rewrite || {};
  const rows = st.rows || [];
  useEffect(() => { call("modes.rewrite_refresh"); }, []);
  const sel = rows.find((r) => r.id === st.sel);
  const canNew = !!(st.on && sel && sel.template && !sel.slug);
  const columns = [
    { key: "label", label: "The game's rule", width: "minmax(170px, 1.2fr)", titleOf: (r) => r.label },
    { key: "logic", label: "Shot logic", width: "minmax(220px, 2fr)", titleOf: (r) => r.status,
      render: (r) => r.slug ? html`<span><span class="pill">C</span> rewritten by <span class="mono">modes/${r.slug}/${r.slug}.c</span></span>` : html`<span class="dim">${r.status}</span>` },
  ];
  return html`<${Modal} title="Rewrite a rule's shots in C" icon="edit" xwide onClose=${onClose}
    footer=${html`<${Button} size="sm" kind="primary" disabled=${!canNew} onClick=${() => call("modes.rewrite_new", sel.id)}
        title="Make a code mode from the SDK's template for the selected rule.">Rewrite in C…<//>
      <span class="grow"></span>
      <${Button} onClick=${onClose}>Close<//>`}>
    <div class="small dim wrap" ...${tip(REWRITE_TIP)}>${st.msg}</div>
    ${st.on ? html`<${Table} cls="modes-stock" columns=${columns} rows=${rows} rowKey=${(r) => r.id}
        selected=${st.sel} onSelect=${(r) => call("modes.rewrite_select", r.id)}
        rowClass=${(r) => cx(!r.slug && !r.template && "readonly")}
        empty="This card's port names none of the game's own rules."
        style="height:min(40vh, 320px)" />` : null}
    ${st.note ? html`<${Note} kind=${/already|no template|names no|Pick/.test(st.note) ? "warn" : "info"}>${st.note}<//>` : null}
  <//>`;
}
