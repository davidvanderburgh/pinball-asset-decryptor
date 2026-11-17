// Service menu (PAD-1382): the game's operator menu as this card will show it at the machine, with the app's own rows
// where the Write puts them. David: "how does the user edit the service menu? ... a visual render of the service menu
// in our app". The pages come from webui/tabs/svcmenu.py (plugins/stern/service_menu.py, planned exactly as a Write
// plans); here they are drawn the way the machine draws them (Godzilla 1.16, emulator), a row is picked as the
// operator picks one, and stepping MORE SETTINGS turns the row under it into the setting picked, as on the machine.
import { html, useState, useEffect, PageHead, Card, Button, Check, Note, Empty, Seg, Spinner, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

// the rows as shown now: the shared value row follows the MORE SETTINGS pick
function shownRows(page, picks) {
  const more = page.rows.find((r) => r.key === "more_select");
  const pick = more ? (picks.more_select ?? 1) : 1;
  return page.rows.map((r) => {
    if (r.shared_value && more && more.options && more.options[pick - 1]) {
      const o = more.options[pick - 1];
      return { ...o, key: "more_value", shared_value: true };
    }
    return r;
  });
}

function valueText(r, picks) {
  if (!r.ours || !r.values) return r.value;
  const k = r.shared_value ? r.setting : r.key;
  const v = picks[k];
  if (v === undefined) return r.value;
  const hit = r.values.find((x) => x.v === v);
  return hit ? hit.text : r.value;
}

function Screen({ page, sel, setSel, picks }) {
  const rows = shownRows(page, picks);
  const cur = rows[sel] || rows[0];
  const now = cur ? valueText(cur, picks) : "";
  return html`<div class="sm-screen" role="listbox" aria-label=${page.name}>
    <div class="sm-title">${page.name}</div>
    <div class="sm-body">
      <div class="sm-rows">
        ${rows.map((r, i) => {
          const val = valueText(r, picks);
          return html`<button type="button" key=${i} role="option" aria-selected=${i === sel}
              class=${cx("sm-row", i === sel && "on", r.ours && "ours")} onClick=${() => setSel(i)}>
            <span class="sm-cap">${r.caption}</span>
            <span class=${cx("sm-val", r.ours && val !== r.default && "changed")}>${val}</span>
          </button>`;
        })}
      </div>
      <div class="sm-help">
        ${cur ? html`<div class="sm-help-cap">${cur.caption}</div>
          <div class="sm-help-text">${cur.help}</div>
          ${now !== "" ? html`<div class="sm-help-vals">Current Value = ${now}<br />Default Value = ${cur.default}</div>` : null}`
          : null}
      </div>
    </div>
  </div>`;
}

function Stepper({ row, picks, setPicks }) {
  if (!row || !row.ours || !row.values) return null;
  const k = row.shared_value ? row.setting : row.key;
  const vals = row.values;
  const at = Math.max(0, vals.findIndex((x) => x.text === valueText(row, picks)));
  const go = (d) => {
    const n = Math.min(vals.length - 1, Math.max(0, at + d));
    setPicks({ ...picks, [k]: vals[n].v });
  };
  return html`<div class="sm-step">
    <${Button} size="sm" icon="minus" disabled=${at === 0} onClick=${() => go(-1)} title="As the machine's minus button" />
    <span class="sm-step-val">${row.caption}: <b>${vals[at].text}</b></span>
    <${Button} size="sm" icon="plus" disabled=${at === vals.length - 1} onClick=${() => go(1)} title="As the machine's plus button" />
    <span class="small muted">${row.key === "more_select"
      ? "Picks which setting the row under it shows, as at the machine."
      : "Try the values here; the operator sets them at the machine, and the card keeps them."}</span>
  </div>`;
}

function Rows({ s, menu }) {
  const where = {};
  for (const p of (menu && menu.pages) || []) {
    for (const r of p.rows) {
      if (r.key === "more_select") for (const o of r.options || []) where[o.setting] = `${p.name}, More Settings`;
      else if (r.ours && !r.shared_value) where[r.key] = p.name;
    }
  }
  const refused = (menu && menu.refused) || {};
  return html`<${Card} title="The app's rows" cls="sm-ours">
    ${(s.settings || []).map((x) => {
      const placed = where[x.key];
      const why = refused[x.key];
      return html`<div class="sm-our" key=${x.key}>
        ${x.can || x.on ? html`<${Check} checked=${x.on} label=${x.name} disabled=${!x.can}
            onChange=${(v) => call("svcmenu.set_row", x.key, v)} />`
          : html`<span class="sm-our-name">${x.name}</span>`}
        <span class="small muted">${placed ? `On ${placed}.` : why ? `Not on the card: ${why}.` : x.note || x.where}</span>
      </div>`;
    })}
    ${menu ? html`<p class="small muted sm-count">This game has ${menu.spare} spare row${menu.spare === 1 ? "" : "s"} for
      the app's settings${menu.shared ? "; there are more settings than that, so they share two: More Settings picks one and the row under it shows it. The card keeps each one's value." : "."}</p>` : null}
  <//>`;
}

export default function ServiceMenuTab() {
  const s = useNs("svcmenu");
  const menu = s.menu;
  const pages = (menu && menu.pages) || [];
  const [pi, setPi] = useState(0);
  const [sel, setSel] = useState(0);
  const [picks, setPicks] = useState({});
  const page = pages[Math.min(pi, pages.length - 1)];
  useEffect(() => {
    if (!page) return;
    const first = page.rows.findIndex((r) => r.ours);
    setSel(first < 0 ? 0 : first);
  }, [pi, menu]);
  const rows = page ? shownRows(page, picks) : [];
  const onKey = (e) => {
    if (!page) return;
    if (e.key === "ArrowDown") { setSel(Math.min(rows.length - 1, sel + 1)); e.preventDefault(); }
    if (e.key === "ArrowUp") { setSel(Math.max(0, sel - 1)); e.preventDefault(); }
  };
  return html`<div class="page sm-page" onKeyDown=${onKey}>
    <${PageHead} title="Service menu" sub=${s.intro}>
      ${s.project ? html`<${Button} size="sm" icon="refresh" onClick=${() => call("svcmenu.refresh")}>Read again<//>` : null}
    <//>
    ${!s.project ? html`<${Empty} icon="list" title="No project">${s.none_why}<//>`
      : s.reading && !menu ? html`<div class="sm-wait"><${Spinner} /> Reading the game's menu…</div>`
      : s.why ? html`<${Note} kind="warn">${s.why}<//>`
      : html`<div class="sm-layout">
        <div class="sm-main">
          ${pages.length > 1 ? html`<${Seg} value=${pi} options=${pages.map((p, i) => ({ value: i, label: p.name }))}
              onChange=${(v) => setPi(Number(v))} />` : null}
          ${page ? html`<div class="small muted sm-path">${page.path}</div>
              <${Screen} page=${page} sel=${sel} setSel=${setSel} picks=${picks} />
              <${Stepper} row=${rows[sel]} picks=${picks} setPicks=${setPicks} />`
            : html`<${Empty} icon="list" title="No rows of the app's yet">Nothing on this project adds a row to the
                service menu. Switch one on below, or on its own tab, and it shows here where the Write puts it.<//>`}
        </div>
        <${Rows} s=${s} menu=${menu} />
      </div>`}
  </div>`;
}
