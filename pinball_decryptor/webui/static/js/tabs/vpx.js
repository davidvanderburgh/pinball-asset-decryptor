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
// PAD-942: a picture of each patched table at the head of its row (the
// playfield out of the (PAD) copy, read by the kit into the app's cache),
// the large one in its tooltip.

import { html, useState, PageHead, Card, Button, Chip, Note, Progress, Spinner, Select, Check, Modal, call, tip, mediaUrl } from "../core/ui.js";
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

// PAD-941: the checklist sheet (David: it lives in the app, themed, with CSV
// export). One modal: the summary, the notes, then every part of the machine
// in the app's own tables, marked yes/NO against the map when a table was
// checked; "Only what is missing" narrows it to the NO rows.
const OK_WORDS = { yes: "yes", no: "NO", board: "board", listed: "listed", "-": "–", "": "" };
function Ok({ v }) {
  if (!v) return null;
  const kind = v === "no" ? "warn" : v === "yes" ? "ok" : "";
  return html`<${Chip} kind=${kind} sm dot=${v === "yes" || v === "no"}
    ...${tip(v === "no" ? "The map wires nothing for it: the table owes this part." : v === "yes" ? "Wired by the map."
      : v === "board" ? "The node board fires it from its own switch; the table owes the switch, not the coil."
      : v === "listed" ? "In the map with a number, but nothing on the table acts on it." : "Nothing to build.")}>${OK_WORDS[v]}<//>`;
}
const at = (r) => (r.x == null ? "–" : r.x + "," + r.y);
// a hint names map keys in `backticks`: shown as code
const hint = (t) => (t || "").split("`").map((part, i) => (i % 2 ? html`<code>${part}</code>` : part));
function Sheet({ d, onClose }) {
  const [onlyMissing, setOnlyMissing] = useState(false);
  const sum = d.summary || {};
  const marked = !!d.map;
  const keep = (r) => !onlyMissing || r.ok === "no";
  const pf = d.switches.filter((s) => (s.where === "playfield" || s.where === "unplaced") && keep(s));
  const cab = d.switches.filter((s) => s.where === "cabinet");
  const virt = d.switches.filter((s) => s.where === "virtual");
  const coils = d.coils.filter(keep);
  const ins = d.inserts.filter((g) => g.where === "playfield" && keep(g));
  const off = d.inserts.filter((g) => g.where !== "playfield");
  const inv = d.inventory;
  const w = sum.wired || {};
  const part = (k, name) => (w[k] ? html`<${Chip} kind=${w[k][0] === w[k][1] ? "ok" : "warn"} sm>${w[k][0]} of ${w[k][1]} ${name}<//>` : null);
  const head = (cols) => html`<thead><tr>${cols.map((c) => html`<th>${c}</th>`)}</tr></thead>`;
  return html`<${Modal} title=${(sum.title || d.title) + ": what a Visual Pinball table needs"} icon="file" xwide cls="vpx-sheet" onClose=${onClose}
    footer=${html`
      <${Check} checked=${onlyMissing} onChange=${setOnlyMissing} label="Only what is missing" disabled=${!marked} />
      <span class="sp"></span>
      ${d.starter ? html`<${Button} size="sm" icon="save" onClick=${() => call("vpx.export", "starter")}>Save starter map…<//>` : null}
      <${Button} size="sm" icon="save" onClick=${() => call("vpx.export", "md")}>Save Markdown…<//>
      <${Button} size="sm" kind="primary" icon="download" onClick=${() => call("vpx.export", "csv")}>Export CSV…<//>
      <${Button} size="sm" kind="ghost" onClick=${onClose}>Close<//>`}>
    <div class="vpx-sheet-sum">
      ${marked ? html`<${Chip} kind=${sum.pct >= 95 ? "ok" : "warn"} dot>${sum.pct}% wired<//>
        ${part("switches", "switches")}${part("coils", "coils the game fires")}${part("inserts", "inserts")}
        ${sum.guesses ? html`<${Chip} sm>${sum.guesses} GUESS<//>` : null}
        ${sum.id_mismatch ? html`<${Chip} kind="warn" sm>${sum.id_mismatch} ids disagree<//>` : null}`
        : html`<${Chip} sm>${sum.switches} switches<//><${Chip} sm>${sum.coils} coils<//><${Chip} sm>${sum.inserts} inserts<//>`}
      ${inv ? html`<span class="small muted">${inv.name}: ${inv.brain === "pad" ? "already patched for PAD.Controller" : inv.brain === "rom" ? "a ROM table" : "a scripted tribute"}, ${inv.script_lines} lines of script${d.map ? ", map " + d.map : ""}.</span>` : null}
    </div>
    <div class="small muted">The table talks to the game in the machine's own numbers: a switch is 1000 + id, a lamp 1000 + node × 100 + index (an RGB insert: its first LED), a coil the small number its map gives it (flippers 46/48/36). A map names the table object for each part; <code>tools/spike2_emu/vpx/README.md</code> has the shape.</div>
    ${(d.notes || []).map((n) => html`<${Note} kind="warn">${n}<//>`)}
    <h3>Switches <span class="small muted">${marked ? sum.missing_switches + " missing" : pf.length + " on the playfield"}</span></h3>
    <table class="vpx-sheet-table">${head([marked ? "ok" : null, "id", "#", "node/bit", "switch", "kind", "at (px)", "the table does"].filter((c) => c !== null))}
      <tbody>${pf.map((s) => html`<tr class=${s.ok === "no" ? "miss" : ""}>${marked ? html`<td><${Ok} v=${s.ok} /></td>` : null}
        <td class="mono">${s.id == null ? "?" : s.id}</td><td class="mono muted">${s.num == null ? "–" : s.num}</td>
        <td class="mono muted">${s.node == null ? "?" : s.node}/${s.bit == null ? "?" : s.bit}</td>
        <td><b>${s.name}</b>${s.where === "unplaced" ? html` <span class="small muted">(no position in this build)</span>` : null}</td>
        <td>${s.kind}</td><td class="mono muted">${at(s)}</td><td class="small">${hint(s.hint)}</td></tr>`)}</tbody></table>
    ${virt.length ? html`<div class="small muted"><b>The game's own</b> (nothing to build): ${virt.map((s) => s.name + " (" + s.id + ")").join(", ")}</div>` : null}
    <div class="small muted"><b>Cabinet</b> (PADSPIKE2.vbs presses these from the keys): ${cab.map((s) => s.name + " (" + s.id + ")").join(", ")}</div>
    <h3>Coils and mechs <span class="small muted">${marked ? sum.missing_coils + " nothing fires, " + sum.listed_coils + " listed without a table action" : coils.length}</span></h3>
    <div class="small muted">Flippers, slingshots and pop bumpers are fired by the node boards from their own switches: the table only has to send the switch. Every other coil is the game's decision, acted on through <code>solenoids</code>.</div>
    <table class="vpx-sheet-table">${head([marked ? "ok" : null, "node/index", "number", "coil", "kind", "at (px)", "the table does"].filter((c) => c !== null))}
      <tbody>${coils.map((c) => html`<tr class=${c.ok === "no" ? "miss" : ""}>${marked ? html`<td><${Ok} v=${c.ok} /></td>` : null}
        <td class="mono muted">${c.node == null ? "?" : c.node}/${c.index}</td><td class="mono">${c.number}</td>
        <td><b>${c.name}</b></td><td>${c.kind}</td><td class="mono muted">${at(c)}</td><td class="small">${hint(c.hint)}</td></tr>`)}</tbody></table>
    <h3>Lights <span class="small muted">${marked ? sum.missing_inserts + " no table light shows" : ins.length + " playfield inserts"}</span></h3>
    <div class="small muted">A Light at the insert's place; the map's <code>lamps</code> puts it on the LED (<code>"leds": [[node, index]]</code>, an RGB insert's three channels together with <code>"rgb": true</code>); an insert the table lacks is a <code>retrofit_lights</code> entry, a flasher or plastic a <code>lamp_calls</code> sub.</div>
    <table class="vpx-sheet-table">${head([marked ? "ok" : null, "lamp", "node/index", "insert", "RGB", "at (px)"].filter((c) => c !== null))}
      <tbody>${ins.map((g) => html`<tr class=${g.ok === "no" ? "miss" : ""}>${marked ? html`<td><${Ok} v=${g.ok} /></td>` : null}
        <td class="mono">${g.lamp}</td><td class="mono muted">${g.leds}</td><td><b>${g.name}</b></td><td>${g.rgb ? "yes" : ""}</td><td class="mono muted">${at(g)}</td></tr>`)}</tbody></table>
    ${off.length && !onlyMissing ? html`<div class="small muted"><b>Off the playfield</b> (no table light): ${off.slice(0, 120).map((g) => g.name + " (" + g.lamp + ")").join(", ")}${off.length > 120 ? " …" : ""}</div>` : null}
    ${d.wrong && d.wrong.length ? html`<h3>The map and this PC's switch table disagree <span class="small muted">${d.wrong.length}</span></h3>
      <div class="small muted">Either the map was built from an older reading of the title or the switch table here is stale: the switch table of the run the table attaches to is the numbering that counts.</div>
      <table class="vpx-sheet-table">${head(["object", "map id", "the map says", "this PC's switch table says"])}
        <tbody>${d.wrong.map(([obj, id, name, got]) => html`<tr><td class="mono">${obj}</td><td class="mono">${id}</td><td>${name}</td><td>${got}</td></tr>`)}</tbody></table>` : null}
    ${d.guesses && d.guesses.length && !onlyMissing ? html`<h3>Marked GUESS in the map <span class="small muted">check these on the machine</span></h3>
      <ul class="vpx-sheet-list">${d.guesses.map(([kind, obj, name]) => html`<li>${kind} <code>${obj}</code>: ${name}</li>`)}</ul>` : null}
    ${inv && !onlyMissing ? html`<h3>The table: ${inv.name}</h3>
      <table class="vpx-sheet-table">${head(["kind", "count", "objects"])}
        <tbody>${Object.entries(inv.kinds).filter(([, v]) => v.length).map(([k, v]) => html`<tr><td>${k}</td><td class="mono">${v.length}</td>
          <td class="small vpx-wrap">${v.slice(0, 40).join(", ")}${v.length > 40 ? " … (" + v.length + ")" : ""}</td></tr>`)}</tbody></table>` : null}
  <//>`;
}

export default function Vpx() {
  const s = useNs("vpx");
  const [details, setDetails] = useState(false);
  const busy = !!s.busy;
  // PAD-958: the tab lists every machine's tables, whatever the manufacturer;
  // the filter at the top narrows them to one machine (Stern's eras are
  // machines of their own). A row or title that names no platform is Spike
  // 2's. On a platform the app has no bridge for yet, the tables play as their
  // authors wrote them: no Patch, no cards.
  const platform = s.platform || "";
  const plats = (s.catalog || {}).platforms || {};
  const nameOf = (k) => (plats[k] || {}).name || (k === "spike2" ? "Stern Spike 2" : k || "");
  const shortOf = (k) => nameOf(k).replace(/^Stern /, "");
  const platName = nameOf(platform);
  const bridged = s.bridged !== false;
  const platOf = (p) => p || "spike2";
  const mine = (p) => !platform || platOf(p) === platform;
  const allTables = s.tables || [];
  const tables = allTables.filter((t) => mine(t.platform));
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
  // (every platform's: another machine's (PAD) copy is not a row of its own here)
  const known = new Set((s.tables || []).map((t) => t.output));
  // PAD-943: the person's own downloads in the folder: the one a known table's
  // map fits is that table's row (Patch takes it); the rest are rows of their
  // own, "no map yet", named after the catalogue's table where the name matches
  // its row carries the author's description from the catalogue (name, by, where
  // from, platform, card) when the file's name says which table it is
  // (a download another machine's table takes is that row's, filtered or not)
  const allLinked = new Set(allTables.map((t) => t.download).filter(Boolean));
  const allDownloads = (s.downloads || []).filter((d) => !allLinked.has(d.path));
  const downloads = allDownloads.filter((d) => mine((d.catalog || {}).platform)).map((d) => {
    const c = d.catalog || {};
    return { name: c.name || d.name, by: c.by || "", where: c.where || "", output: d.file, patched: false,
      extra: true, download: d, platform: c.platform || "", card: d.card || "" };
  });
  const rows = tables.concat(patched.filter((n) => !known.has(n)).map((n) => ({
    name: n.replace(/ \(PAD\)\.vpx$/i, ""), output: n, patched: true, extra: true })), downloads)
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  const rtOk = s.runtime_state === "ready";
  // PAD-958: the filter's machines: the ones with a table here or one to
  // download in the catalogue below, in the catalogue's order
  const catTables = ((s.catalog || {}).tables || []).filter((t) => !t.complete && t.url);
  const has = new Set(allTables.map((t) => platOf(t.platform))
    .concat(allDownloads.map((d) => (d.catalog || {}).platform).filter(Boolean), catTables.map((t) => t.platform)));
  const machines = Object.keys(plats).filter((k) => has.has(k)).concat([...has].filter((k) => !plats[k]));
  if (platform && !machines.includes(platform)) machines.push(platform);
  const filterOpts = [{ value: "", label: "All machines" }].concat(machines.map((k) => ({ value: k, label: nameOf(k) })));
  // the rows the filter leaves out, to say so under the list
  const hidden = platform ? allTables.length - tables.length
    + allDownloads.filter((d) => !mine((d.catalog || {}).platform)).length : 0;
  // PAD-840: installed from here; the Emulate tab only offers it in some cases
  const rtFix = s.runtime_state === "absent" || s.runtime_state === "stale";
  const vpxOk = !!s.vpx && !s.vpx_old;
  // set up once, then only looked at: its rows (and their buttons) show under
  // Details, or by themselves while any of it is not ready
  const setup = [["The emulator's Linux", rtOk],
    ["Visual Pinball" + (s.vpx_version ? " " + s.vpx_version : ""), vpxOk]].concat(bridged
    ? [["Controller", !!s.registered && s.registered_here !== false], ["Card images", have.length > 0]] : []);
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
  // PAD-942: the row's picture, the large one on hover; a patched table
  // whose picture is not read yet (or cannot be) shows an empty outline
  const pictures = s.pictures || {};
  const picture = (t) => {
    const p = pictures[t.output];
    if (p && p.file) {
      const url = mediaUrl(p.file);
      return html`<img class="vpx-pic-img" src=${url} width=${p.w} height=${p.h} alt=""
        ...${tip({ head: t.name, lines: [p.source === "screenshot" ? "The author's own picture of the table."
          : p.source === "backglass" ? "The table's backglass: its playfield is baked into its 3D parts, not a picture."
          : "The table's playfield, as its author drew it."], image: url, w: p.w, h: p.h })} />`;
    }
    const why = p && p.error ? "No picture: " + p.error + "."
      : !t.patched ? "No picture until the table is patched: it is read from your (PAD) copy."
      : s.pictures_busy ? "Reading the table's picture…" : "No picture read yet.";
    return html`<span class="vpx-nopic" ...${tip(why)}></span>`;
  };
  // PAD-943: a download's row says what the app knows of it
  const downloadChip = (d) => {
    if (!d.read) return html`<span class="vpx-skel vpx-skel-cov" ...${tip("Reading the table…")}></span>`;
    const c = d.catalog;
    // PAD-952: a game no table can ever play (America's Most Haunted)
    if (c && c.no_game) return html`<${Chip} sm kind="info" ...${tip({ head: c.platform_name + " game: plays as its author wrote it",
      lines: ["The name says it is " + c.name + " (" + c.game + ").", c.no_game,
        "Play opens your download as it is: the table's own rules play."] })}>Author's rules<//>`;
    const head = c ? c.platform_name + " game: no map yet" : "No map yet";
    return html`<${Chip} sm kind="warn" ...${tip({ head, lines: [
      c ? "The name says it is " + c.name + " (" + c.game + ")." : "The app does not recognize this table.",
      "Nothing plays behind it: the app has no map for it yet, so it plays as its author wrote it.",
      c && c.platform === "spike1" ? "A Spike 1 game: the checklist on the authors' card is where a map starts." : ""].filter(Boolean) })}>No map yet<//>`;
  };
  // PAD-952: a download whose game can never run here plays from the file itself
  const asIs = (t) => !!(t.extra && t.download && t.download.read && (t.download.catalog || {}).no_game);
  // PAD-941: a row's coverage (the map's wired parts over what the game has, from
  // this PC's tables) is the button that writes that table's checklist
  const coverage = s.coverage || {};
  const coverBtn = (t) => {
    const c = coverage[t.title];
    if (!c && s.coverage_busy) return html`<span class="vpx-skel vpx-skel-cov" ...${tip("Reading how much of the game the map wires…")}></span>`;
    const part = (k, name) => c && c[k] ? c[k][0] + " of " + c[k][1] + " " + name : "";
    const lines = c ? [part("switches", "switches"), part("coils", "coils the game fires"), part("inserts", "inserts"),
      "Click for the checklist: every part, marked by what the map wires, against "
      + (t.source ? base(t.source) : t.patched ? "your (PAD) copy" : "the game alone") + "."]
      : ["No tables for " + t.title + " on this PC yet: play it once and check again."];
    return html`<${Button} size="sm" kind=${c && c.pct >= 95 ? "ghost" : ""} icon="file" disabled=${busy || !s.ok || !c}
      ...${tip({ head: c ? "The map wires " + c.pct + "% of " + t.title + "." : "Coverage unknown.", lines })}
      onClick=${() => call("vpx.row_checklist", t.output)}>${c ? c.pct + "%" : "–"}<//>`;
  };
  return html`<div class="page vpx-page">
    ${s.sheet ? html`<${Sheet} d=${s.sheet} onClose=${() => call("vpx.close_sheet")} />` : null}
    <${PageHead} title="Visual Pinball" sub=${(s.intro || "").split("\n").map((l) => html`${l}<br />`)}>
      <span class="small muted">Machine</span>
      <${Select} sm width=${200} value=${platform} options=${filterOpts} cls="vpx-filter"
        title="Every machine's tables are listed. Pick one to see only its tables, its games for table authors and its tables to download."
        onChange=${(v) => call("vpx.set_filter", v)} />
      <${Chip} kind="info" sm>Preview<//>
      <${Button} kind="ghost" icon="refresh" disabled=${busy || !s.ok} onClick=${() => call("vpx.refresh")}>Check again<//>
      <${Button} kind="ghost" disabled=${busy || !s.ok} ...${tip({ head: "Restart WSL.", lines: [
        "The cure for the game's screen gone blank on the desktop while the table still plays, a game window that will not close, or crackly sound.",
        "It closes everything running in WSL: every game on every tab. WSL starts again by itself on the next use."] })}
        onClick=${() => call("vpx.restart_wsl")}>Restart WSL…<//>
    <//>
    ${s.note ? html`<${Note} kind="warn">${s.note}<//>` : null}
    ${platform && !bridged ? html`<${Note} kind="info">${platName} tables play as their authors wrote them: the app has no link from a table to its ${platName} emulator yet${(plats[platform] || {}).runs ? " (" + plats[platform].runs + ")" : ""}. The list below is where to get them.<//>` : null}
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
      ${bridged ? html`<${Row} ok=${!!s.registered && s.registered_here !== false} label="The game's link to Visual Pinball (PAD.Controller)"
        value=${!s.registered ? "Not registered."
          : s.registered_here === false ? html`Registered to another copy of the app: <span class="mono">${s.registered_to}</span>.
            Every table calls that one, so what is new here (a Spike 1 game, say) is not in play until this copy is registered.`
          : "Registered."}>
        ${s.registered && s.registered_here !== false ? null : html`<${Button} size="sm" disabled=${busy || !s.ok} onClick=${() => call("vpx.register")}>Register<//>`}
      <//>
      <${Row} ok=${have.length > 0} label=${html`Card images <span class="small muted">${s.cards_tip}</span>`}
        value=${html`<span class="mono">${s.library || "No folder chosen."}</span>${cardWords ? html`<br />${cardWords}` : null}`}>
        <${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
          onClick=${() => call("vpx.choose_library")}>Choose folder…<//>
      <//>` : null}` : null}
    <//>
    ${bridged ? html`<${Card} cls="vpx-authors" head=${html`<span class="h2">For table authors</span>
        <span class="small muted vpx-authors-sub">${s.authors_intro}</span>`}>
      <div class="vpx-authors-row">
        <span class="small">Game</span>
        <${Select} sm width=${260} value=${s.author_title || ""} options=${authorTitles}
          disabled=${busy || !s.ok || !authorTitles.length || s.authors_busy} title=${s.authors_titles_tip}
          onChange=${(v) => call("vpx.pick_author_title", v)} />
        ${s.authors_busy ? html`<span class="small muted vpx-authors-busy"><${Spinner} /> Finding the games on this PC…</span>` : null}
        <${Button} size="sm" icon="file" disabled=${busy || !s.ok || !s.author_title}
          title="Open the game's checklist: every switch, coil and insert, its number and what a table does for it. Export it as CSV or Markdown from there."
          onClick=${() => call("vpx.checklist", false)}>Checklist…<//>
        <${Button} size="sm" kind="ghost" icon="search" disabled=${busy || !s.ok || !s.author_title}
          title="Choose a .vpx: the checklist marks every part of the game that table leaves out (against the app's map for it), or offers a starter map when the app has none."
          onClick=${() => call("vpx.checklist", true)}>Check a table…<//>
        ${!authorTitles.length && s.loaded && !s.authors_busy ? html`<span class="small muted">No game has run on this PC yet: play one once and it appears here.</span>` : null}
      </div>
      ${s.author_note ? html`<div class="small vpx-authors-note">${s.author_note}</div>` : null}
    <//>` : null}
    <${Card} cls="vpx-tables" head=${html`<span class="h2" ...${tip(s.tables_tip)}>Tables</span>
        <span class="mono small muted vpx-dir" ...${tip("Your tables folder: where Patch writes the (PAD) copies and Play looks for them.")}>${s.tables_dir || "No tables folder set"}</span>
        ${s.pictures_busy ? html`<span class="small muted vpx-pics-busy"><${Spinner} /> ${s.pictures_busy}…</span>` : null}
        <span class="sp"></span>
        <${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
          onClick=${() => call("vpx.choose_tables")}>Choose folder…<//>
        ${bridged ? html`<${Button} drop size="sm" kind="ghost" icon="upload" disabled=${busy || !s.ok}
          title="Patch every table in a folder of downloads at once: the ones the app knows get their (PAD) copy, the rest are counted."
          onClick=${() => call("vpx.patch_folder")}>Patch a folder…<//>` : null}`}>
      ${rows.length ? html`<div class="vpx-list">
        <div class="vpx-table vpx-head small muted">
          <span class="vpx-pic" ...${tip(s.pictures_tip)}></span>
          <span>Table</span><span class="vpx-by">By</span><span class="vpx-from">From</span>
          <span class="vpx-machine">Machine</span>
          <span ...${tip("The machine the table plays as: the card image it boots is that model's.")}>Model</span>
          <span>Card image</span><span>Your copy</span>
          <span ...${tip("How much of the game the app's map for this table wires, from the game's own tables on this PC: switches, coils and inserts the table owes, less what the map leaves out. Click a row's for its checklist.")}>Coverage</span>
          <span></span><span></span>
        </div>
        ${rows.map((t) => html`<div class=${"vpx-table" + (t.patched ? "" : " unpatched")}>
        <span class="vpx-pic">${picture(t)}</span>
        <b class="vpx-name" ...${tip(t.extra && !t.download ? t.output : t.name + (t.by ? ", by " + t.by : "") + (t.where ? ", on " + t.where : "") + (t.download ? " (your file: " + t.download.file + ")" : ""))}>${t.name}</b>
        <span class="small vpx-by" ...${tip(t.by)}>${t.by}</span>
        <span class="small muted vpx-from" ...${tip(t.where)}>${t.where}</span>
        <span class="small vpx-machine" ...${tip(t.extra && !t.platform ? "" : nameOf(platOf(t.platform)))}>${t.extra && !t.platform ? "" : shortOf(platOf(t.platform))}</span>
        <span class="small" ...${tip(fits(t).length > 1 ? playsAs(t) + "The table fits "
            + fits(t).map((x) => t.models[x]).join(" or ") + "." : t.download && t.platform ? "A " + nameOf(t.platform) + " game: " + t.download.file : "")}>${t.extra ? "" : (t.models || {})[t.title] || ""}</span>
        <span class="small muted vpx-card" ...${tip(t.extra ? (t.card ? "Card: " + t.card : "") : t.card ? playsAs(t) + "Card: " + t.card
            : "No card image for " + fits(t).join(" or ") + " in your card folder yet.")}>${t.extra && !t.download ? ""
          : !t.card ? (t.extra ? "" : "No card yet") : base(t.card)}</span>
        <span>${t.download && t.extra ? downloadChip(t.download)
          : !t.patched ? html`<${Chip} sm ...${tip(t.download ? "Your download is in the folder: " + base(t.download) + ". Patch writes its (PAD) copy." : "")}>Not patched<//>`
          : stale(t) || missed(t) ? html`<${Chip} kind="warn" dot sm>Patch again<//>`
          : html`<${Chip} kind="ok" dot sm>Patched<//>`}</span>
        <span class="vpx-cover">${t.extra ? null : coverBtn(t)}</span>
        <span class="vpx-patch">${t.extra ? null
          : patchBtn(t, !t.patched ? "Patch…" : t.source ? "Patch again" : "Patch again…")}</span>
        <span class="vpx-play">${asIs(t) ? html`<${Button} size="sm" kind="primary" icon="play" disabled=${busy || !s.vpx}
          title=${"Open " + t.download.file + " in Visual Pinball as it is: its author's own rules play."}
          onClick=${() => call("vpx.play_download", t.download.path)}>Play<//>`
          : html`<${Button} size="sm" kind="primary" icon="play" disabled=${busy || !s.vpx || !t.patched}
          title=${t.patched ? "" : "Patch " + t.name + " first: Play opens its (PAD) copy."}
          onClick=${() => call("vpx.play", t.output)}>Play<//>`}</span>
        ${stale(t) && t.card ? html`<div class="small vpx-stale">Your copy was patched for the ${t.models[t.patched_title]} and still plays as it.
          Patch again to play it as the ${t.models[t.title]}.</div>` : null}
        ${missed(t) ? html`<div class="small vpx-stale">Your copy was patched before a fix: ${t.repatch.join("; ")}.
          Patch again to get it.</div>` : null}
      </div>`)}</div>` : s.loaded ? html`<div class="muted small">No tables${platform ? " for a " + platName + " machine in your folder yet" : ""}.</div>` : html`<${Skeleton} />`}
      ${hidden ? html`<div class="small muted vpx-others">Only ${platName} tables are shown: ${hidden} more of other machines are under <a href="#" onClick=${(e) => { e.preventDefault(); call("vpx.set_filter", ""); }}>All machines</a>.</div>` : null}
    <//>
    <${Catalog} s=${s} platform=${platform} platName=${platName} />
  </div>`;
}

// PAD-943: the tables' place while the kit's first state is read (half a
// second; the page itself never waits): four rows the shape of a table row.
function Skeleton() {
  return html`<div class="vpx-list vpx-skel-list">${[0, 1, 2, 3].map((i) => html`<div class="vpx-table vpx-skel-row" key=${i}>
    <span><span class="vpx-skel" style=${"width:" + (55 + (i * 17) % 35) + "%"}></span></span>
    <span class="vpx-by"><span class="vpx-skel" style="width:60%"></span></span>
    <span class="vpx-from"><span class="vpx-skel" style="width:70%"></span></span>
    <span class="vpx-machine"><span class="vpx-skel" style="width:60%"></span></span>
    <span><span class="vpx-skel" style="width:30px"></span></span>
    <span><span class="vpx-skel" style="width:80%"></span></span>
    <span><span class="vpx-skel" style="width:64px"></span></span>
    <span><span class="vpx-skel vpx-skel-cov"></span></span>
    <span></span><span></span>
  </div>`)}</div>`;
}

// PAD-943: the other platforms' tables. One card, a block per platform
// (what plays behind a table there), a line per table: the game, the table
// (a link to where its author put it), who made it, and whether it is the
// machine's own layout or a themed original.
const KIND_WORDS = { tribute: "scripted", mashup: "older ROM", "": "none" };
function Catalog({ s, platform, platName }) {
  const cat = s.catalog || {};
  const plats = cat.platforms || {};
  // a table that is in the person's folder is on the Tables list above, not here
  const have = new Set((s.downloads || []).map((d) => d.catalog && d.catalog.name).filter(Boolean));
  // PAD-956: nor is one complete on its own (TNA): it needs nothing from the app
  const tables = (cat.tables || []).filter((t) => !t.complete && (!t.url || !have.has(t.name)));
  // the filter's machine's block, every machine's under All machines (PAD-958)
  const order = Object.keys(plats).filter((k) => (!platform || k === platform) && tables.some((t) => t.platform === k));
  if (!order.length) return null;
  return html`<${Card} cls="vpx-cat" head=${html`<span class="h2" ...${tip(s.catalog_tip)}>${platform ? "More " + platName + " tables" : "More tables"}</span>
      <span class="small muted vpx-cat-sub">The app ships none of them: each is its author's download, and it plays as its author wrote it until the app has a map for it${platform ? "" : " (Stern SAM games are Visual PinMAME's already, so they are not here)"}.</span>`}>
    ${order.map((k) => html`<div class="vpx-cat-plat">
      <div class="vpx-cat-head"><b>${plats[k].name}</b> <span class="small muted">${plats[k].runs}</span>
        ${plats[k].needs ? html`<${Chip} kind="warn" dot sm ...${tip(plats[k].needs)}>needs the machine's security key<//>` : null}</div>
      ${plats[k].needs ? html`<div class="small vpx-cat-needs">${plats[k].needs}</div>` : null}
      ${tables.filter((t) => t.platform === k).map((t) => html`<div class=${"vpx-cat-row" + (t.url ? "" : " none")}>
        <span class="small vpx-cat-game" ...${tip(t.game)}>${t.game}</span>
        <span class="vpx-cat-name" ...${tip(t.url ? "Open " + t.where + ": " + t.url : t.notes)}>${t.url
          ? html`<a href=${t.url} target="_blank" rel="noopener">${t.name}</a>` : html`<span class="muted">${t.notes}</span>`}</span>
        <span class="small vpx-cat-by" ...${tip(t.by)}>${t.by}</span>
        <span class="small muted vpx-cat-from">${t.where}</span>
        <span class="vpx-cat-kind">${t.url ? html`<${Chip} sm kind=${t.faithful ? "ok" : ""} dot=${t.faithful}
          ...${tip((t.faithful ? "The machine's own layout" : "A themed original, not the machine's layout") + "; "
            + (t.kind === "mashup" ? "an older game's ROM plays under the playfield" : "its own script plays"
              ) + (t.map ? ". The app's map: " + t.map : "") + (t.notes ? ". " + t.notes : ""))}>${(t.faithful ? "layout" : "themed") + ", " + KIND_WORDS[t.kind || ""]}<//>` : null}</span>
      </div>`)}
    </div>`)}
  <//>`;
}
