// Service menu (PAD-1382): the game's operator menu as this card will show it at the machine, with the app's own rows
// where the Write puts them. David: "how does the user edit the service menu? ... a visual render of the service menu
// in our app". The pages come from webui/tabs/svcmenu.py (plugins/stern/service_menu.py, planned exactly as a Write
// plans); here they are drawn the way the machine draws them (Godzilla 1.16, emulator), a row is picked as the
// operator picks one, and stepping MORE SETTINGS turns the row under it into the setting picked, as on the machine.
import { html, useState, useEffect, PageHead, Card, Button, Check, Field, Note, Empty, Seg, Spinner, call, cx, mediaUrl } from "../core/ui.js";
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

// round 4: the games without a category table (Aerosmith, Venom, TMNT... 22 of 53) have the older dot-matrix menu,
// one adjustment a screen (Aerosmith LE 1.16 in the emulator): "STANDARD ADJUSTMENT #n", the row's caption, its value
function DmdScreen({ page, sel, setSel, picks }) {
  const rows = shownRows(page, picks);
  const cur = rows[sel] || rows[0];
  const now = cur ? valueText(cur, picks) : "";
  return html`<div class="sm-dmd-wrap">
    <div class="sm-dmd" role="img" aria-label=${page.name}>
      <div>${page.label} #${sel + 1}</div>
      <div class="sm-dmd-cap">${(cur && cur.caption || "").toUpperCase()}</div>
      <div class="sm-dmd-val">${(now === "" ? "·" : now).toUpperCase()}</div>
      <div>${now !== "" && now === (cur && cur.default) ? "(INSTALLED/FACTORY DEFAULT)" : "(INSTALLED)"}</div>
    </div>
    <div class="sm-dmd-list" role="listbox" aria-label=${page.name}>
      ${rows.map((r, i) => html`<button type="button" key=${i} role="option" aria-selected=${i === sel}
          ref=${i === sel ? (el) => { if (el) el.scrollIntoView({ block: "nearest" }); } : null}
          class=${cx("sm-dmd-row", i === sel && "on", r.ours && "ours")} onClick=${() => setSel(i)}>
        <span class="muted">#${i + 1}</span> ${r.caption}<span class="sp"></span>${valueText(r, picks)}</button>`)}
    </div>
  </div>`;
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

// round 3 (David): "things like reordering existing settings? adding removing custom ones. we don't want to break any
// built-in ones though so keep it simple" - the order is the owner's (it sets the rows' order on a page and their
// numbers on More Settings); a setting of their own is a name and its values, read by the card's own code
function AddSetting({ said }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [vals, setVals] = useState("Off, On");
  const [def, setDef] = useState("1");
  if (!open) return html`<div class="row"><${Button} size="sm" icon="plus" onClick=${() => setOpen(true)}
      title="A row of your own: a name and its values. The card's own code reads what the operator set.">Add a setting…<//></div>`;
  const add = async () => {
    const why = await call("svcmenu.add_custom", name, vals, Number(def) || 1);
    if (!why) { setOpen(false); setName(""); }
  };
  return html`<div class="sm-add">
    <label class="lbl">Name, as the menu shows it</label>
    <${Field} value=${name} placeholder="Dark Screens" maxLength=${20} onChange=${setName} />
    <label class="lbl">Its values, in order, with commas</label>
    <${Field} value=${vals} placeholder="Off, On" onChange=${setVals} />
    <label class="lbl">The value it starts at (its number)</label>
    <${Field} value=${def} width=${70} type="number" min=${1} max=${8} onChange=${setDef} />
    ${said ? html`<span class="small err-ink">${said}</span>` : null}
    <div class="row"><${Button} size="sm" kind="primary" onClick=${add}>Add<//>
      <${Button} size="sm" onClick=${() => setOpen(false)}>Cancel<//></div>
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
  const list = s.settings || [];
  return html`<${Card} title="The app's rows" sub="in your order" cls="sm-ours">
    ${list.map((x, i) => {
      const placed = where[x.key];
      const why = refused[x.key];
      return html`<div class="sm-our" key=${x.key}>
        <div class="sm-our-hd">
          ${x.custom ? html`<span class="sm-our-name">${x.name} <span class="small muted">(yours)</span></span>`
            : x.can || x.on ? html`<${Check} checked=${x.on} label=${x.name} disabled=${!x.can}
                onChange=${(v) => call("svcmenu.set_row", x.key, v)} />`
            : html`<span class="sm-our-name">${x.name}</span>`}
          <span class="sp"></span>
          <${Button} size="sm" icon="up" disabled=${i === 0} title="Earlier on the page and on More Settings"
            onClick=${() => call("svcmenu.move", x.key, -1)} />
          <${Button} size="sm" icon="down" disabled=${i === list.length - 1} title="Later on the page and on More Settings"
            onClick=${() => call("svcmenu.move", x.key, 1)} />
          ${x.custom ? html`<${Button} size="sm" icon="trash" title="Remove this setting of yours"
            onClick=${() => call("svcmenu.remove_custom", x.key)} />` : null}
        </div>
        ${x.custom ? html`<span class="small">${x.values.map((v, k) => `${k + 1} ${v}`).join(", ")}; starts at ${x.default}.</span>` : null}
        <span class="small muted">${placed ? `On ${placed}. ` : why ? `Not on the card: ${why}. ` : ""}${x.custom ? x.where : placed ? "" : x.note || x.where}</span>
      </div>`;
    })}
    <${AddSetting} said=${s.custom_said} />
    ${menu ? html`<p class="small muted sm-count">This game has ${menu.spare} spare row${menu.spare === 1 ? "" : "s"} for
      the app's settings${menu.shared ? "; there are more settings than that, so they share two: More Settings picks one and the row under it shows it. The card keeps each one's value." : "."}</p>` : null}
  <//>`;
}

// round 3 (David): "make it like the multi-boot menu too where it renders the REAL thing ... if it's not performant,
// then add a check-box to toggle it and leave it off by default" - the game itself in the emulator, minutes a read
function Real({ s, page, pi, sel }) {
  return html`<div class="sm-real">
    <${Check} checked=${s.real_on} label="Show the real menu from the emulator" title=${s.real_note}
      onChange=${(v) => { call("svcmenu.set_real", v); if (v && page) call("svcmenu.render", pi, sel); }} />
    ${s.real_on ? html`<div class="sm-real-bd">
      <div class="row"><${Button} size="sm" icon="refresh" disabled=${s.real_busy || !page}
          onClick=${() => call("svcmenu.render", pi, sel)}>Read the real menu<//>
        <span class="small muted">${s.real_note}</span></div>
      ${s.real_busy ? html`<div class="sm-wait"><${Spinner} /> Booting the game in the emulator (hidden) and walking its menu…</div>`
        : s.real_why ? html`<${Note} kind="warn">${s.real_why}<//>`
        : s.real_png ? html`<figure class="sm-real-fig"><img src=${mediaUrl(s.real_png)} alt=${"The game's own " + (s.real_for || "menu")} />
            <figcaption class="small muted">The game itself, in the emulator: ${s.real_for}</figcaption></figure>`
        : null}
    </div>` : null}
  </div>`;
}

export default function ServiceMenuTab() {
  const s = useNs("svcmenu");
  const menu = s.menu;
  const pages = (menu && menu.pages) || [];
  const [pi, setPi] = useState(0);
  const [sel, setSel] = useState(0);
  const [picks, setPicks] = useState({});
  const page = pages[Math.min(pi, pages.length - 1)];
  // round 4: every Machine Settings page is listed; open on the first that holds a row of the app's, else Attract Mode
  useEffect(() => {
    if (!pages.length) return;
    let want = pages.findIndex((p) => p.ours);
    if (want < 0) want = pages.findIndex((p) => p.category === 16);
    setPi(want < 0 ? 0 : want);
  }, [menu]);
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
          ${page ? html`<div class="small muted sm-path">${page.path}${menu.source ? html` · read from <span class="mono">${menu.source}</span>` : null}
              ${menu.wide ? " · Spike 3: the page's system rows and the app's (the game's own rows for this game are not listed yet)" : null}</div>
              ${page.style === "dmd" ? html`<${DmdScreen} page=${page} sel=${sel} setSel=${setSel} picks=${picks} />`
                : html`<${Screen} page=${page} sel=${sel} setSel=${setSel} picks=${picks} />`}
              <${Stepper} row=${rows[sel]} picks=${picks} setPicks=${setPicks} />
              <${Real} s=${s} page=${page} pi=${pi} sel=${sel} />`
            : html`<${Empty} icon="list" title="No rows of the app's yet">Nothing on this project adds a row to the
                service menu. Switch one on below, or on its own tab, and it shows here where the Write puts it.<//>`}
        </div>
        <${Rows} s=${s} menu=${menu} />
      </div>`}
  </div>`;
}
