// Plugins (PAD-1554, David: "maybe a new Plugins tab, where the user can choose optional plugins to install. they
// need to persist between PAD updates too"): optional add-ons made by other people, downloaded from their author's
// own project at the version the user picks (webui/tabs/plugins.py, core/card_plugins.py). One card a plugin, in
// two halves: what is installed on this computer, and whether this project's cards carry it.
import { html, useState, PageHead, Card, Check, Note, Button, Select, Progress, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

function Said({ text, kind }) {
  return text ? html`<span class=${cx("small", kind === "err" ? "err-ink" : kind === "ok" ? "ok-ink" : "muted")}
    role=${kind === "err" ? "alert" : undefined}>${text}</span>` : null;
}

function Advanced({ title, children }) {
  const [open, setOpen] = useState(false);
  return html`<div class="plg-adv">
    <button type="button" class="plg-adv-hd" aria-expanded=${open} onClick=${() => setOpen(!open)}>
      ${open ? "▾" : "▸"} ${title}</button>
    ${open ? html`<div class="plg-adv-bd">${children}</div>` : null}
  </div>`;
}

// the versions its author has published, newest first; the one this app was tested with says so
function versionOptions(p) {
  return (p.releases || []).map((r) => ({
    value: r.tag,
    label: r.tag + (r.date ? "  (" + r.date + ")" : "") + (r.tested ? "  tested with this app" : "  not tested yet"),
  }));
}

function OnThisComputer({ p, s }) {
  const off = !!p.busy || s.running;
  const same = p.installed && p.installed === p.pick;
  const picked = (p.releases || []).find((r) => r.tag === p.pick);
  return html`<div class="plg-half">
    <div class="plg-half-hd"><b>On this computer</b>
      <span class=${cx("plg-state", p.installed ? "on" : "off")}>${p.installed
        ? "Installed: " + p.installed : "Not installed"}</span></div>
    ${p.installed && !p.installed_tested ? html`<${Note} kind="warn">Version ${p.installed} is newer than this
      version of the app was tested with (${p.tested}). It was checked against its author's own checksums, and it
      may work differently from what this page says.<//>` : null}
    <div class="plg-row">
      <label class="lbl" for=${"plg-ver-" + p.key}>Version</label>
      <${Select} id=${"plg-ver-" + p.key} value=${p.pick} options=${versionOptions(p)} disabled=${off}
        onChange=${(v) => call("plugins.pick", p.key, v)} />
      <${Button} kind="primary" disabled=${off || same} busy=${!!p.busy}
        onClick=${() => call("plugins.install", p.key, p.pick)}>${same ? "Installed"
          : p.installed ? "Install this version" : "Install"}<//>
      ${p.installed ? html`<${Button} disabled=${off} onClick=${() => call("plugins.remove", p.key)}>Remove<//>` : null}
    </div>
    ${picked && !picked.tested ? html`<span class="small muted">${p.pick} has not been tested with this version of
      the app; ${p.tested} has.</span>` : null}
    ${p.busy ? html`<span class="small">${p.busy}…</span><${Progress} busy />` : null}
    <${Said} text=${p.note} kind=${p.kind} />
    ${p.releases_state && p.releases_state !== "ok" && p.releases_state !== "loading"
      ? html`<span class="small muted">${p.releases_state} Only ${p.tested} is offered until the list can be read.</span>` : null}
    <div class="plg-row">
      <${Button} size="sm" disabled=${off || p.releases_state === "loading"} busy=${p.releases_state === "loading"}
        onClick=${() => call("plugins.refresh_releases", p.key)}>Check for versions<//>
      <${Button} size="sm" disabled=${off} drop
        title="For a computer that cannot reach gitlab.com: pick the release's two .tar.gz files and its SHA256SUMS, downloaded on another computer"
        onClick=${() => call("plugins.install_from_files", p.key)}>Install from files…<//>
    </div>
    <span class="small muted">Kept in <span class="mono">${s.store}</span>, outside the app's own folder: updating
      the app leaves it installed. Nothing of a plugin runs on this computer.</span>
  </div>`;
}

function OnYourCards({ p, s }) {
  return html`<div class="plg-half">
    <div class="plg-half-hd"><b>On your cards</b>
      <span class="muted small">Saved with this project and put on the card when you write it</span></div>
    ${!p.offered || (!p.supported && p.reason) ? html`<${Note}>${p.reason}<//>` : null}
    <${Check} label=${p.tick} checked=${!!p.enabled} wrap
      disabled=${!p.offered || !p.supported || !p.has_project || s.running}
      onChange=${(on) => call("plugins.configure", p.key, on, s.project)} />
    ${p.hint ? html`<span class=${cx("small", p.enabled && !p.installed ? "err-ink" : "muted")}>${p.hint}</span>` : null}
    ${p.error ? html`<p role="alert" class="err-ink">${p.error}</p>` : null}
    <span class="small muted">${p.needs}</span>
    <${Advanced} title="Exactly what it changes on the card">
      <table class="plg-fields">
        <tbody>${(p.details || []).map((r) => html`<tr key=${r[0]}><th scope="row">${r[0]}</th>
          <td class=${r[2] ? "mono" : ""}>${r[1]}</td></tr>`)}
          ${p.now ? html`<tr><th scope="row">The card you picked has</th><td class="mono">${p.now}</td></tr>` : null}
        </tbody></table>
    <//>
  </div>`;
}

function Plugin({ p, s }) {
  return html`<${Card} cls="plg-card" title=${p.name} sub=${"by " + p.author}>
    <p class="plg-what">${p.what}</p>
    <div class="plg-meta small">
      <span>Licence: ${p.license}</span>
      <button type="button" class="plg-link" onClick=${() => call("plugins.open_project", p.key)}>${p.project_url}</button>
    </div>
    <div class="plg-halves">
      <${OnThisComputer} p=${p} s=${s} />
      <${OnYourCards} p=${p} s=${s} />
    </div>
  <//>`;
}

export default function PluginsTab() {
  const s = useNs("plugins");
  const list = s.plugins || [];
  return html`<div class="page plg-page">
    <${PageHead} title="Plugins" sub=${s.intro} />
    ${list.length ? list.map((p) => html`<${Plugin} key=${p.key} p=${p} s=${s} />`)
      : html`<${Note}>There are no plugins for this kind of card yet.<//>`}
  </div>`;
}
