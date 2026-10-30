// Visual Pinball: the Spike 2 emulator plays a Visual Pinball table (a
// preview feature, PAD-802).  Python half: webui/tabs/vpx.py, which runs the
// kit in tools/spike2_emu/vpx.  The app ships no tables: the person downloads
// one the kit knows from its author and patches it here.

import { html, PageHead, Card, Button, Chip, Note, Radio, Progress, Spinner, call } from "../core/ui.js";
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
  // PAD-850: ONE list, alphabetical - the tables the app knows, a patched one
  // with its Play button, and any other (PAD) table in the folder as its own row
  const known = new Set(tables.map((t) => t.output));
  const rows = tables.concat(patched.filter((n) => !known.has(n)).map((n) => ({
    name: n.replace(/ \(PAD\)\.vpx$/i, ""), output: n, patched: true, extra: true })))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  const rtOk = s.runtime_state === "ready";
  // PAD-840: installed from here; the Emulate tab only offers it in some cases
  const rtFix = s.runtime_state === "absent" || s.runtime_state === "stale";
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
    <div class="cols c75 vpx-cols">
      <div class="stack">
        <${Card} title="Setup">
          <${Row} ok=${rtOk} label="The emulator's Linux (PAD runtime)" value=${s.runtime_text || ""}>
            ${rtFix ? html`<${Button} size="sm" disabled=${busy || !s.ok} icon="download"
              onClick=${() => call("vpx.install_runtime")}>${s.runtime_state === "stale" ? "Update" : "Install"}<//>` : null}
          <//>
          <${Row} ok=${!!s.vpx} label="Visual Pinball" value=${s.vpx || "Not found on this PC."}>
            <${Button} drop size="sm" kind="ghost" disabled=${busy || !s.ok} onClick=${() => call("vpx.choose_vpx")}>Choose folder…<//>
            ${s.vpx ? null : html`<${Button} size="sm" disabled=${busy || !s.ok} icon="download"
              onClick=${() => call("vpx.download_vpx")}>Download 10.8.0<//>`}
          <//>
          <${Row} ok=${!!s.registered} label="The game's link to Visual Pinball (PAD.Controller)"
            value=${s.registered ? "Registered." : "Not registered."}>
            ${s.registered ? null : html`<${Button} size="sm" disabled=${busy || !s.ok} onClick=${() => call("vpx.register")}>Register<//>`}
          <//>
        <//>
        <${Card} title="Card images" sub=${s.cards_tip}>
          <div class="vpx-row">
            <${Chip} kind=${have.length ? "ok" : "warn"} dot sm>${have.length ? "Ready" : "Needed"}<//>
            <div class="vpx-what"><div class="mono small vpx-val">${s.library || "No folder chosen."}</div>
              ${cardWords ? html`<div class="small muted">${cardWords}</div>` : null}</div>
            <div class="vpx-acts"><${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
              onClick=${() => call("vpx.choose_library")}>Choose folder…<//></div>
          </div>
        <//>
        <${Card} title="Windows" sub="Where Visual Pinball's playfield and the game's screen go when a table opens.">
          ${presets.map((p) => html`<div class="vpx-pre">
            <${Radio} name="vpx-layout" checked=${s.layout === p.key} disabled=${busy || !s.ok} label=${p.words}
              onChange=${() => call("vpx.layout", p.key)} /></div>`)}
          ${s.display && s.display.text ? html`<div class="small muted">The game's screen: ${s.display.text}. The Emulate tab's Game display changes it, live.</div>` : null}
        <//>
      </div>
      <div class="stack">
        <${Card} title="Tables" sub=${s.tables_tip}
          footer=${html`<${Button} drop kind="primary" icon="upload" disabled=${busy || !s.ok}
            onClick=${() => call("vpx.patch")}>Patch a table…<//>`}>
          <div class="vpx-row">
            <div class="vpx-what"><div class="small muted">Your tables folder</div>
              <div class="mono small vpx-val">${s.tables_dir || "Not set: choose where your patched tables are."}</div></div>
            <div class="vpx-acts"><${Button} drop size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
              onClick=${() => call("vpx.choose_tables")}>Choose folder…<//></div>
          </div>
          ${rows.length ? rows.map((t) => html`<div class="vpx-table">
            <div class="vpx-what"><div><b>${t.name}</b></div>
              ${t.extra ? html`<div class="small muted">${t.output}</div>` : html`
              <div class="small muted">${t.by ? "by " + t.by : ""}${t.where ? ", on " + t.where : ""}</div>
              <div class="small muted">${t.card ? playsAs(t) + "Card: " + base(t.card) : "No card image for " + fits(t).join(" or ") + " yet."}</div>`}</div>
            ${t.patched ? html`<${Button} size="sm" kind="primary" icon="play" disabled=${busy || !s.vpx}
                onClick=${() => call("vpx.play", t.output)}>Play<//>`
              : html`<${Chip} dot sm>Not patched<//>`}
          </div>`) : html`<div class="muted small">${s.loaded ? "No tables." : "Checking…"}</div>`}
        <//>
      </div>
    </div>
  </div>`;
}
