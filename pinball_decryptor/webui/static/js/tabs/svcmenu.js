// Service menu (PAD-1382): the game's operator menu as this card will show it at the machine, with the app's own rows
// where the Write puts them. David: "how does the user edit the service menu? ... a visual render of the service menu
// in our app". The pages come from webui/tabs/svcmenu.py (plugins/stern/service_menu.py, planned exactly as a Write
// plans); here they are drawn the way the machine draws them (Godzilla 1.16, emulator), a row is picked as the
// operator picks one, and stepping MORE SETTINGS turns the row under it into the setting picked, as on the machine.
import { html, useState, useEffect, PageHead, Card, Button, Check, Note, Empty, Seg, Spinner, call, cx, mediaUrl } from "../core/ui.js";
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

// round 5 (David): "we should just be checking off items that exist ... with a 'custom code' tab, we shouldn't have the
// option to add these custom settings to those other ones" - the app's settings, ticked here or on their tabs, in the
// owner's order (their order on the page and their numbers on More Settings)
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
  return html`<${Card} title="The app's settings" sub="tick to put on the card" cls="sm-ours">
    ${list.map((x, i) => {
      const placed = where[x.key];
      const why = refused[x.key];
      return html`<div class="sm-our" key=${x.key}>
        <div class="sm-our-hd">
          ${/* PAD-1393: every row has its box - ticked when the card gets it, greyed when the project has no such setting yet */
            html`<${Check} checked=${x.on} label=${x.name} disabled=${!x.can}
                onChange=${(v) => call("svcmenu.set_row", x.key, v)} />`}
          <span class="sp"></span>
          <${Button} size="sm" icon="up" disabled=${i === 0} title="Earlier on the page and on More Settings"
            onClick=${() => call("svcmenu.move", x.key, -1)} />
          <${Button} size="sm" icon="down" disabled=${i === list.length - 1} title="Later on the page and on More Settings"
            onClick=${() => call("svcmenu.move", x.key, 1)} />
        </div>
        <span class="small muted">${placed ? `On ${placed}.` : why ? `Not on the card: ${why}.` : x.note || x.where}</span>
      </div>`;
    })}
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

// round 5 (David): "better highlight the 'custom code' tab and how the user gets there": the way there at the machine,
// and the Machine Settings list drawn with the page lit, as the operator steps to it
function WayThere({ menu, page }) {
  const own = menu.own;
  const dmd = page && page.style === "dmd";
  const steps = dmd ? ["Service menu", "Adjustments", "Standard Adjustments", "the last rows"]
    : ["Service menu", "Adjustments", "Machine Settings", own || (page && page.name) || "…"];
  const list = menu.machine_list || [];
  return html`<div class="sm-way">
    <div class="sm-way-steps" aria-label="The way there at the machine">
      ${steps.map((t, i) => html`<span key=${i} class=${cx("sm-way-step", i === steps.length - 1 && "last")}>${t}</span>
        ${i < steps.length - 1 ? html`<span class="sm-way-sep">›</span>` : null}`)}
    </div>
    <p class="small muted sm-way-note">${dmd
      ? "This game has the older dot-matrix menu, with no pages to add: the app's rows are the last ones of Standard Adjustments (press minus on the first row to go round to them)."
      : own ? `Open the coin door, press SELECT for the service menu, then Adjustments, Machine Settings and ${own}: the app's own page, with every setting the app adds.`
      : "The app's rows are on the page below."}</p>
    ${!dmd && own && list.length ? html`<div class="sm-screen sm-list-screen" aria-label="Machine Settings">
        <div class="sm-title">Machine Settings</div>
        <div class="sm-body">
          <div class="sm-rows sm-list-rows">${list.map((n) => html`<div key=${n} class=${cx("sm-row", n === own && "on ours")}>
            <span class="sm-cap">${n}</span></div>`)}</div>
          ${menu.own_help ? html`<div class="sm-help"><div class="sm-help-text">${menu.own_help}</div></div>` : null}
        </div>
      </div>` : null}
  </div>`;
}

function PageView({ page, picks, setPicks, sel, setSel, readOnly }) {
  const rows = shownRows(page, picks);
  return html`${page.style === "dmd" ? html`<${DmdScreen} page=${page} sel=${sel} setSel=${setSel} picks=${picks} />`
      : html`<${Screen} page=${page} sel=${sel} setSel=${setSel} picks=${picks} />`}
    ${readOnly ? null : html`<${Stepper} row=${rows[sel]} picks=${picks} setPicks=${setPicks} />`}`;
}

export default function ServiceMenuTab() {
  const s = useNs("svcmenu");
  const menu = s.menu;
  const pages = (menu && menu.pages) || [];
  // the app's page (Custom Code, or the page holding its rows) first; the game's others read-only, secondary
  const oi = pages.findIndex((p) => p.ours);
  const ours = oi >= 0 ? pages[oi] : null;
  const others = pages.filter((p, i) => i !== oi);
  const [sel, setSel] = useState(0);
  const [picks, setPicks] = useState({});
  const [qi, setQi] = useState(0);
  const [qsel, setQsel] = useState(0);
  const other = others[Math.min(qi, others.length - 1)];
  useEffect(() => {
    if (!ours) return;
    const first = ours.rows.findIndex((r) => r.ours);
    setSel(first < 0 ? 0 : first);
  }, [menu]);
  useEffect(() => { setQsel(0); }, [qi, menu]);
  const rows = ours ? shownRows(ours, picks) : [];
  const onKey = (e) => {
    if (!ours || (e.target.closest && e.target.closest(".sm-others"))) return;
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
          <${Card} cls="sm-hero" title=${ours ? (menu.own || ours.name) : "The app's page"}
              sub=${menu.source ? html`read from <span class="mono">${menu.source}</span>` : null}>
            ${ours ? html`<${WayThere} menu=${menu} page=${ours} />
                <${PageView} page=${ours} picks=${picks} setPicks=${setPicks} sel=${sel} setSel=${setSel} />
                <${Real} s=${s} page=${ours} pi=${oi} sel=${sel} />`
              : html`<${Empty} icon="list" title="No settings of the app's yet">Tick a setting on the right (or switch it
                  on its own tab) and it shows here, on the page the Write gives the app's settings.<//>`}
            ${menu.wide ? html`<p class="small muted">Spike 3: the page's system rows and the app's are shown (the game's own rows for this game are not listed yet).</p>` : null}
          <//>
          ${others.length ? html`<details class="sm-others">
            <summary>The game's other pages <span class="muted small">(read-only: nothing on them is changed)</span></summary>
            <${Seg} value=${qi} options=${others.map((p, i) => ({ value: i, label: p.name }))} onChange=${(v) => setQi(Number(v))} />
            <div class="small muted sm-path">${other.path}</div>
            <${PageView} page=${other} picks=${{}} setPicks=${() => {}} sel=${qsel} setSel=${setQsel} readOnly=${true} />
          </details>` : null}
        </div>
        <${Rows} s=${s} menu=${menu} />
      </div>`}
  </div>`;
}
