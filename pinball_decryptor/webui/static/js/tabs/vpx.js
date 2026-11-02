// Visual Pinball: the Spike 2 emulator plays a Visual Pinball table (a
// preview feature, PAD-802).  Python half: webui/tabs/vpx.py, which runs the
// kit in tools/spike2_emu/vpx.  The app ships no tables: the person downloads
// one the kit knows from its author and patches it here.
//
// PAD-927 laid it out again: the setup folds to one line of marks once all of
// it is ready, the tables take the page with Patch on each table not yet
// patched, and the window layouts are Use buttons, not radios nobody had picked.

import { html, useState, PageHead, Card, Button, Chip, Note, Progress, Spinner, call } from "../core/ui.js";
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
  const patchBtn = (t, words) => html`<${Button} drop size="sm" kind=${t.patched ? "ghost" : ""} icon="upload"
    disabled=${busy || !s.ok} title=${"Choose your download of " + t.name
      + ": the app writes its \"(PAD)\" copy into your tables folder."}
    onClick=${() => call("vpx.patch", t.output)}>${words}<//>`;
  // no layout taken is the usual case, not a blank to fill: the windows open
  // where they were last left (the kit saves the playfield's place, the
  // renderer the game screen's in display.conf)
  const inUse = presets.find((p) => p.key === s.layout);
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
    <${Card} cls=${"vpx-setup" + (open ? "" : " shut")} head=${html`<span class="h2">Setup</span>
        <div class="vpx-marks">${setup.map(([words, ok]) => html`<${Chip} kind=${!s.loaded ? "" : ok ? "ok" : "warn"} dot sm>${words}<//>`)}</div>
        <span class="sp"></span>
        ${allOk ? html`<${Button} size="sm" kind="ghost" iconRight=${details ? "up" : "down"}
          onClick=${() => setDetails(!details)}>${details ? "Hide" : "Details"}<//>` : null}`}>
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
    <div class="cols c75 vpx-cols">
      <${Card} title="Tables" sub=${s.tables_tip}>
        <div class="vpx-row">
          <div class="vpx-what"><div class="small muted">Your tables folder</div>
            <div class="mono small vpx-val">${s.tables_dir || "Not set: choose where your patched tables are."}</div></div>
          <div class="vpx-acts"><${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
            onClick=${() => call("vpx.choose_tables")}>Choose folder…<//></div>
        </div>
        ${rows.length ? rows.map((t) => html`<div class="vpx-table">
          <div class="vpx-what"><div><b>${t.name}</b>${t.patched ? null : html` <span class="small muted">· not patched yet</span>`}</div>
            ${t.extra ? html`<div class="small muted">${t.output}</div>` : html`
            <div class="small muted">${t.by ? "by " + t.by : ""}${t.where ? ", on " + t.where : ""}</div>
            <div class="small muted">${t.card ? playsAs(t) + "Card: " + base(t.card) : "No card image for " + fits(t).join(" or ") + " yet."}</div>
            ${stale(t) && t.card ? html`<div class="small">Your copy was patched for the ${t.models[t.patched_title]} and still plays as it.
              Patch the table again to play it as the ${t.models[t.title]}.</div>` : null}`}</div>
          <div class="vpx-acts">
            ${stale(t) && t.card ? patchBtn(t, "Patch again…") : null}
            ${t.patched ? html`<${Button} size="sm" kind="primary" icon="play" disabled=${busy || !s.vpx}
                onClick=${() => call("vpx.play", t.output)}>Play<//>`
              : patchBtn(t, "Patch…")}
          </div>
        </div>`) : html`<div class="muted small">${s.loaded ? "No tables." : "Checking…"}</div>`}
      <//>
      <${Card} title="Windows" sub="Where Visual Pinball's playfield and the game's screen go when a table opens.">
        <div class="vpx-now"><div class="small muted">Now</div>
          <div>${inUse ? inUse.words + "."
            : "Where you left them: each window opens where you last moved it."}</div></div>
        ${presets.length ? html`<div class="small muted vpx-or">Or set them out once, in one of these layouts:</div>` : null}
        ${presets.map((p) => html`<div class="vpx-row vpx-pre">
          <div class="vpx-what">${p.words}</div>
          <div class="vpx-acts">${s.layout === p.key ? html`<${Chip} kind="ok" dot sm>In use<//>`
            : html`<${Button} size="sm" kind="ghost" disabled=${busy || !s.ok} onClick=${() => call("vpx.layout", p.key)}>Use<//>`}</div>
        </div>`)}
        ${s.display && s.display.text ? html`<div class="small muted vpx-disp">The game's screen: ${s.display.text}. The Emulate tab's Game display changes it, live.</div>` : null}
      <//>
    </div>
  </div>`;
}
