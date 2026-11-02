// Visual Pinball: the Spike 2 emulator plays a Visual Pinball table (a
// preview feature, PAD-802).  Python half: webui/tabs/vpx.py, which runs the
// kit in tools/spike2_emu/vpx.  The app ships no tables: the person downloads
// one the kit knows from its author and patches it here.
//
// PAD-927 laid it out again: the setup folds to one line of marks once all of
// it is ready, the tables take the page with Patch on each table not yet
// patched, and the window layouts are Use buttons, not radios nobody had picked.
// PAD-940: the tables are ONE column under labelled headings (table, author,
// where from, model, card, your copy), not two or three columns of rows that
// crammed the model and the card into one cell; Patch and Play each a column
// of their own, Play greyed on a table not patched yet (David).

// PAD-941: a card for whoever builds or finishes a table: a checklist of
// every switch, coil and insert the game has, checked against a table.

import { html, useState, PageHead, Card, Button, Chip, Note, Progress, Spinner, Select, call, tip } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const base = (p) => (p || "").split(/[\\/]/).pop();

function Row({ ok, label, value, children }) {
  return html`<div class="vpx-row">
    <${Chip} kind=${ok ? "ok" : "warn"} dot sm>${ok ? "Ready" : "Needed"}<//>
    <div class="vpx-what"><div>${label}</div>${value ? html`<div class="small muted vpx-val">${value}</div>` : null}</div>
    <div class="vpx-acts">${children}</div>
  </div>`;
}

export default function Vpx() {
  const s = useNs("vpx");
  const [details, setDetails] = useState(false);
  const busy = !!s.busy;
  const tables = s.tables || [];
  const patched = s.patched || [];
  const presets = s.presets || [];
  const titles = Object.keys(s.cards || {});
  // the folder may hold every title; what matters here is the tables' own.
  // A table several titles fit (JP's Foo Fighters: Pro or LE) needs one of them
  const fits = (t) => t.titles || [t.title];
  const have = tables.filter((t) => fits(t).some((x) => titles.includes(x))).map((t) => t.title);
  const lack = tables.filter((t) => !fits(t).some((x) => titles.includes(x))).map((t) => fits(t).join(" or "));
  const cardWords = !s.library ? "" : !titles.length ? "No card images in this folder."
    : (titles.length + " title" + (titles.length === 1 ? "" : "s") + " in this folder. "
      + (have.length ? "For the tables here: " + have.join(", ") + "." : "None of them is for a table here.")
      + (have.length && lack.length ? " No card for " + lack.join(", ") + "." : ""));
  const playsAs = (t) => fits(t).length > 1 && (t.models || {})[t.title]
    ? "Plays as the " + t.models[t.title] + ". " : "";
  // PAD-900: the copy in the folder was patched for another model than Patch
  // takes now (Bond's, for the LE before its Pro map): it still plays as that
  const stale = (t) => t.patched && t.patched_title && t.patched_title !== t.title
    && fits(t).includes(t.patched_title) && (t.models || {})[t.patched_title] && t.models[t.title];
  // PAD-850: ONE list, alphabetical - the tables the app knows, a patched one
  // with its Play button, and any other (PAD) table in the folder as its own row
  const known = new Set(tables.map((t) => t.output));
  const rows = tables.concat(patched.filter((n) => !known.has(n)).map((n) => ({
    name: n.replace(/ \(PAD\)\.vpx$/i, ""), output: n, patched: true, extra: true })))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  const rtOk = s.runtime_state === "ready";
  // PAD-840: installed from here; the Emulate tab only offers it in some cases
  const rtFix = s.runtime_state === "absent" || s.runtime_state === "stale";
  const vpxOk = !!s.vpx && !s.vpx_old;
  // set up once, then only looked at: its rows (and their buttons) show under
  // Details, or by themselves while any of it is not ready
  const setup = [["The emulator's Linux", rtOk],
    ["Visual Pinball" + (s.vpx_version ? " " + s.vpx_version : ""), vpxOk],
    ["Controller", !!s.registered], ["Card images", have.length > 0]];
  const allOk = !!s.loaded && setup.every(([, ok]) => ok);
  const open = details || (!!s.loaded && !allOk);
  // PAD-939: a copy patched before a fix its map names (The Beatles' trough)
  const missed = (t) => t.patched && (t.repatch || []).length > 0;
  const patchBtn = (t, words) => html`<${Button} drop size="sm" kind=${t.patched && !missed(t) && !stale(t) ? "ghost" : ""} icon="upload"
    disabled=${busy || !s.ok} title=${(t.source ? "Patch " + base(t.source) + " again"
      : "Choose your download of " + t.name + (t.where ? " (from " + t.where + ")" : ""))
      + ": the app writes its \"(PAD)\" copy into your tables folder."}
    onClick=${() => call("vpx.patch", t.output)}>${words}<//>`;
  // no layout taken is the usual case, not a blank to fill: the windows open
  // where they were last left (the kit saves the playfield's place, the
  // renderer the game screen's in display.conf)
  const inUse = presets.find((p) => p.key === s.layout);
  const authorTitles = s.author_titles || [];
  return html`<div class="page vpx-page">
    <${PageHead} title="Visual Pinball" sub=${(s.intro || "").split("\n").map((l) => html`${l}<br />`)}>
      <${Chip} kind="info" sm>Preview<//>
      <${Button} kind="ghost" icon="refresh" disabled=${busy || !s.ok} onClick=${() => call("vpx.refresh")}>Check again<//>
    <//>
    ${s.note ? html`<${Note} kind="warn">${s.note}<//>` : null}
    ${busy || s.message ? html`<div class="vpx-status">
      ${busy ? html`<${Spinner} /><span>${s.busy}…</span>`
        : s.message_level === "error" ? html`<${Note} kind="warn">${s.message}<//>`
        : html`<span class="muted">${s.message}</span>`}
      ${busy && s.progress != null ? html`<div class="vpx-prog"><${Progress} pct=${s.progress * 100} /></div>` : null}
    </div>` : null}
    <${Card} cls=${"vpx-top" + (open ? "" : " shut")} head=${html`<div class="vpx-strip">
        <div class="vpx-strip-row">
          <span class="h2">Setup</span>
          <div class="vpx-marks">${setup.map(([words, ok]) => html`<${Chip} kind=${!s.loaded ? "" : ok ? "ok" : "warn"} dot sm>${words}<//>`)}</div>
          <span class="sp"></span>
          ${allOk ? html`<${Button} size="sm" kind="ghost" iconRight=${details ? "up" : "down"}
            onClick=${() => setDetails(!details)}>${details ? "Hide" : "Details"}<//>` : null}
        </div>
        <div class="vpx-strip-row">
          <span class="h2">Windows</span>
          <span class="small vpx-now" ...${tip({ head: "Where Visual Pinball's playfield and the game's screen go when a table opens.",
            lines: [s.display && s.display.text ? "The game's screen: " + s.display.text + ". The Emulate tab's Game display changes it, live." : ""] })}>
            ${inUse ? inUse.words + "." : "Where you left them: each window opens where you last moved it."}</span>
          <span class="sp"></span>
          ${presets.length ? html`<span class="small muted">Set them out:</span>` : null}
          ${presets.map((p) => s.layout === p.key
            ? html`<${Chip} kind="ok" dot sm ...${tip(p.words)}>${p.short || p.key}<//>`
            : html`<${Button} size="sm" kind="ghost" disabled=${busy || !s.ok} ...${tip(p.words)}
                onClick=${() => call("vpx.layout", p.key)}>${p.short || p.key}<//>`)}
        </div>
      </div>`}>
      ${open ? html`
      <${Row} ok=${rtOk} label="The emulator's Linux (PAD runtime)" value=${s.runtime_text || ""}>
        ${rtFix ? html`<${Button} size="sm" disabled=${busy || !s.ok} icon="download"
          onClick=${() => call("vpx.install_runtime")}>${s.runtime_state === "stale" ? "Update" : "Install"}<//>` : null}
      <//>
      <${Row} ok=${vpxOk} label=${html`Visual Pinball${s.vpx_min
          ? html` <span class="small muted">${s.vpx_min} or later</span>` : null}`}
        value=${!s.vpx ? "Not found on this PC."
          : s.vpx_old ? "Version " + s.vpx_version + " in " + s.vpx + ". The tables need " + s.vpx_min
            + " or later: choose a newer copy, or download " + s.vpx_min + " into another folder."
          : s.vpx + (s.vpx_version ? " (version " + s.vpx_version + ")" : "")}>
        <${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok} onClick=${() => call("vpx.choose_vpx")}>Choose folder…<//>
        ${vpxOk ? null : html`<${Button} size="sm" disabled=${busy || !s.ok} icon="download"
          onClick=${() => call("vpx.download_vpx")}>Download 10.8.0<//>`}
      <//>
      <${Row} ok=${!!s.registered} label="The game's link to Visual Pinball (PAD.Controller)"
        value=${s.registered ? "Registered." : "Not registered."}>
        ${s.registered ? null : html`<${Button} size="sm" disabled=${busy || !s.ok} onClick=${() => call("vpx.register")}>Register<//>`}
      <//>
      <${Row} ok=${have.length > 0} label=${html`Card images <span class="small muted">${s.cards_tip}</span>`}
        value=${html`<span class="mono">${s.library || "No folder chosen."}</span>${cardWords ? html`<br />${cardWords}` : null}`}>
        <${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
          onClick=${() => call("vpx.choose_library")}>Choose folder…<//>
      <//>` : null}
    <//>
    <${Card} cls="vpx-tables" head=${html`<span class="h2" ...${tip(s.tables_tip)}>Tables</span>
        <span class="mono small muted vpx-dir" ...${tip("Your tables folder: where Patch writes the (PAD) copies and Play looks for them.")}>${s.tables_dir || "No tables folder set"}</span>
        <span class="sp"></span>
        <${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
          onClick=${() => call("vpx.choose_tables")}>Choose folder…<//>
        <${Button} drop size="sm" kind="ghost" icon="upload" disabled=${busy || !s.ok}
          title="Patch every table in a folder of downloads at once: the ones the app knows get their (PAD) copy, the rest are counted."
          onClick=${() => call("vpx.patch_folder")}>Patch a folder…<//>`}>
      ${rows.length ? html`<div class="vpx-list">
        <div class="vpx-table vpx-head small muted">
          <span>Table</span><span class="vpx-by">By</span><span class="vpx-from">From</span>
          <span ...${tip("The machine the table plays as: the card image it boots is that model's.")}>Model</span>
          <span>Card image</span><span>Your copy</span><span></span><span></span>
        </div>
        ${rows.map((t) => html`<div class=${"vpx-table" + (t.patched ? "" : " unpatched")}>
        <b class="vpx-name" ...${tip(t.extra ? t.output : t.name + (t.by ? ", by " + t.by : "") + (t.where ? ", on " + t.where : ""))}>${t.name}</b>
        <span class="small vpx-by" ...${tip(t.by)}>${t.by}</span>
        <span class="small muted vpx-from" ...${tip(t.where)}>${t.where}</span>
        <span class="small" ...${tip(fits(t).length > 1 ? playsAs(t) + "The table fits "
            + fits(t).map((x) => t.models[x]).join(" or ") + "." : "")}>${t.extra ? "" : (t.models || {})[t.title] || ""}</span>
        <span class="small muted vpx-card" ...${tip(t.extra ? "" : t.card ? playsAs(t) + "Card: " + t.card
            : "No card image for " + fits(t).join(" or ") + " in your card folder yet.")}>${t.extra ? ""
          : !t.card ? "No card yet" : base(t.card)}</span>
        <span>${!t.patched ? html`<${Chip} sm>Not patched<//>`
          : stale(t) || missed(t) ? html`<${Chip} kind="warn" dot sm>Patch again<//>`
          : html`<${Chip} kind="ok" dot sm>Patched<//>`}</span>
        <span class="vpx-patch">${t.extra ? null
          : patchBtn(t, !t.patched ? "Patch…" : t.source ? "Patch again" : "Patch again…")}</span>
        <span class="vpx-play"><${Button} size="sm" kind="primary" icon="play" disabled=${busy || !s.vpx || !t.patched}
          title=${t.patched ? "" : "Patch " + t.name + " first: Play opens its (PAD) copy."}
          onClick=${() => call("vpx.play", t.output)}>Play<//></span>
        ${stale(t) && t.card ? html`<div class="small vpx-stale">Your copy was patched for the ${t.models[t.patched_title]} and still plays as it.
          Patch again to play it as the ${t.models[t.title]}.</div>` : null}
        ${missed(t) ? html`<div class="small vpx-stale">Your copy was patched before a fix: ${t.repatch.join("; ")}.
          Patch again to get it.</div>` : null}
      </div>`)}</div>` : html`<div class="muted small">${s.loaded ? "No tables." : "Checking…"}</div>`}
    <//>
    <${Card} cls="vpx-authors" head=${html`<span class="h2">For table authors</span>
        <span class="small muted vpx-authors-sub">${s.authors_intro}</span>`}>
      <div class="vpx-authors-row">
        <span class="small">Game</span>
        <${Select} sm width=${260} value=${s.author_title || ""} options=${authorTitles}
          disabled=${busy || !s.ok || !authorTitles.length} title=${s.authors_titles_tip}
          onChange=${(v) => call("vpx.pick_author_title", v)} />
        <${Button} size="sm" icon="file" disabled=${busy || !s.ok || !s.author_title}
          title="Write the game's checklist: every switch, coil and insert, its number and what a table does for it. Opens when written."
          onClick=${() => call("vpx.checklist", false)}>Checklist…<//>
        <${Button} size="sm" kind="ghost" icon="search" disabled=${busy || !s.ok || !s.author_title}
          title="Choose a .vpx: the checklist marks every part of the game that table leaves out (against the app's map for it), or comes with a starter map when the app has none."
          onClick=${() => call("vpx.checklist", true)}>Check a table…<//>
        ${!authorTitles.length && s.loaded ? html`<span class="small muted">No game has run on this PC yet: play one once and it appears here.</span>` : null}
      </div>
      ${s.author_note ? html`<div class="small vpx-authors-note">${s.author_note}</div>` : null}
    <//>
  </div>`;
}
