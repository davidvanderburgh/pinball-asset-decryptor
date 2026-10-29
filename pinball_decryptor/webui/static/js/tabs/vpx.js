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
  // the folder may hold every title; what matters here is the tables' own
  const want = tables.map((t) => t.title);
  const have = want.filter((t) => titles.includes(t));
  const lack = want.filter((t) => !titles.includes(t));
  const cardWords = !s.library ? "" : !titles.length ? "No card images in this folder."
    : (titles.length + " title" + (titles.length === 1 ? "" : "s") + " in this folder. "
      + (have.length ? "For the tables here: " + have.join(", ") + "." : "None of them is for a table here.")
      + (have.length && lack.length ? " No card for " + lack.join(", ") + "." : ""));
  const rtOk = s.runtime_state === "ready";
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
          <${Row} ok=${rtOk} label="The emulator's Linux (PAD runtime)"
            value=${rtOk ? s.runtime_text : (s.runtime_text || "") + " Set it up on the Emulate tab."} />
          <${Row} ok=${!!s.vpx} label="Visual Pinball" value=${s.vpx || "Not found on this PC."}>
            <${Button} size="sm" kind="ghost" disabled=${busy || !s.ok} onClick=${() => call("vpx.choose_vpx")}>Choose folder…<//>
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
            <div class="vpx-acts"><${Button} size="sm" kind="ghost" icon="folder" disabled=${busy || !s.ok}
              onClick=${() => call("vpx.choose_library")}>Choose folder…<//></div>
          </div>
        <//>
        <${Card} title="Windows" sub="Where Visual Pinball's playfield and the game's screen go when a table opens.">
          ${presets.map((p) => html`<div class="vpx-pre">
            <${Radio} name="vpx-layout" checked=${s.layout === p.key} disabled=${busy || !s.ok} label=${p.words}
              onChange=${() => call("vpx.layout", p.key)} /></div>`)}
        <//>
      </div>
      <div class="stack">
        <${Card} title="Tables" sub=${s.tables_tip}
          footer=${html`<${Button} kind="primary" icon="upload" disabled=${busy || !s.ok}
            onClick=${() => call("vpx.patch")}>Patch a table…<//>`}>
          ${tables.length ? tables.map((t) => html`<div class="vpx-table">
            <div class="vpx-what"><div><b>${t.name}</b></div>
              <div class="small muted">${t.by ? "by " + t.by : ""}${t.where ? ", on " + t.where : ""}</div>
              <div class="small muted">${t.card ? "Card: " + base(t.card) : "No card image for " + t.title + " yet."}</div></div>
            <${Chip} kind=${t.patched ? "ok" : ""} dot sm>${t.patched ? "Patched" : "Not patched"}<//>
          </div>`) : html`<div class="muted small">${s.loaded ? "No tables." : "Checking…"}</div>`}
        <//>
        <${Card} title="Play">
          ${patched.length ? patched.map((n) => html`<div class="vpx-table">
            <div class="vpx-what">${n}</div>
            <${Button} size="sm" kind="primary" icon="play" disabled=${busy || !s.vpx} onClick=${() => call("vpx.play", n)}>Play<//>
          </div>`) : html`<div class="muted small">Patched tables show up here.</div>`}
        <//>
      </div>
    </div>
  </div>`;
}
