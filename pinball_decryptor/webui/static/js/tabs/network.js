// Network (PR #38 review, David's call): what a card does with the owner's home network, each said plainly for
// someone who has never heard of it. The score feed (PAD-1204) moved here from Play options, whose other options
// change how the game plays; its state and actions are the Modes service's (the `modes` namespace). Remote access
// (SSH, PR #38) is this tab's own (the `network` namespace).
import { html, useState, useEffect, PageHead, Card, Field, Check, Note, Button, Select, Progress, call, cx, mediaUrl } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

// David: "I'd like to see the sample API contract for the scores API" - what the machine sends your server after a
// game, and what it expects back (plugins/stern/score_feed.py contract(): the runtime's own format)
function FeedContract({ c }) {
  const [open, setOpen] = useState(false);
  if (!c) return null;
  return html`<div class="net-contract">
    <button type="button" class="net-contract-hd" aria-expanded=${open} onClick=${() => setOpen(!open)}>
      ${open ? "▾" : "▸"} What your server receives (API contract)</button>
    ${open ? html`<div class="net-contract-bd">
      <div class="lbl">The request, one per game</div>
      <pre class="mono net-pre">${c.request}</pre>
      <div class="lbl">The body, laid out</div>
      <pre class="mono net-pre">${c.body}</pre>
      <div class="lbl">Fields</div>
      <table class="net-fields"><thead><tr><th>Field</th><th>Type</th><th>What it holds</th></tr></thead>
        <tbody>${(c.fields || []).map((f) => html`<tr key=${f.name}><td class="mono">${f.name}</td>
          <td class="muted">${f.type}</td><td>${f.what}</td></tr>`)}</tbody></table>
      <div class="lbl">Your server's answer</div>
      <p class="small">${c.answer}</p>
    </div>` : null}
  </div>`;
}

function Said({ text, kind }) {
  return text ? html`<span class=${cx("small", kind === "err" ? "err-ink" : kind === "ok" ? "ok-ink" : "muted")}>${text}</span>` : null;
}

// PAD-1467: how a panel's settings reach a card, said on the panel (David: "explicitly show on each panel if a
// build is required too ... make it obvious how the settings can get to the card: build required, send over remote
// access, etc."): one chip a way, ticked when this panel's settings can go that way, crossed when they cannot.
function Ways({ n, panel }) {
  const list = (n.ways || {})[panel] || [];
  const note = (n.way_notes || {})[panel] || "";
  if (!list.length) return null;
  const build = list.every((w) => !w.on || w.key === "build" || w.key === "send");
  return html`<div class="net-ways" role="group" aria-label="How these settings reach the card">
    <div class="net-ways-hd">${build ? "Needs a build" : "No build needed"}
      <span class="muted small">${build ? " — these settings reach the card only through a build" : " — these settings can also go straight on"}</span></div>
    <div class="net-ways-row">${list.map((w) => html`<span key=${w.key} title=${w.hint}
      class=${cx("net-way", w.on ? "on" : "off")}><span aria-hidden="true">${w.on ? "✓" : "✕"}</span> ${w.label}</span>`)}</div>
    ${note ? html`<span class="small muted">${note}</span>` : null}
  </div>`;
}

// PAD-1467: the two direct routes, for a panel whose settings are only files on the card's system partition
function Direct({ n, kind }) {
  const busy = !!n.direct_busy || n.running;
  const mine = n.direct_for === kind;
  return html`<div class="net-direct">
    <div class="row">
      <${Button} disabled=${busy || !n.card} title=${n.card ? "The card picked under Remote access" : "Put the machine's card in this computer's reader and pick it under Remote access"}
        onClick=${() => call("network.put_on_card", kind)}>Put on the attached card<//>
      <${Button} disabled=${busy || !n.address} title=${n.address ? "Over remote access; the machine restarts" : "Find your machine first"}
        onClick=${() => call("network.put_on_machine", kind)}>Put on my machine now<//>
    </div>
    ${mine && n.direct_busy ? html`<span class="small">${n.direct_busy}…</span>` : null}
    ${mine && n.direct_pct != null ? html`<${Progress} pct=${n.direct_pct} />` : null}
    ${mine ? html`<${Said} text=${n.direct_note} kind=${n.direct_kind} />` : null}
    <span class="small muted">Both put on what is ticked here, and take off what is not, without a build.</span>
  </div>`;
}

function ScoreFeed({ s, n }) {
  return html`<${Card} cls="net-opt" title="Score feed">
    <p class="net-does">${s.feed_tip}</p>
    <${Check} checked=${s.feed_on} wrap label="Score feed" onChange=${(v) => call("modes.set_score_feed", v)} />
    ${s.feed_on ? html`<div class="net-field"><span class="lbl">Your server's address</span>
      <${Field} value=${s.feed_url} mono placeholder=${s.feed_placeholder} title=${s.feed_url_tip}
        bad=${s.feed_note_kind === "err"} onChange=${() => {}} onCommit=${(v) => call("modes.set_score_feed", true, v)} /></div>` : null}
    <${Said} text=${s.feed_note} kind=${s.feed_note_kind} />
    <${FeedContract} c=${s.feed_contract} />
    <${Ways} n=${n || {}} panel="score_feed" />
  <//>`;
}

// PAD-1479: online co-op - machines in different places playing toward one shared goal (plugins/stern/online_coop.py).
// The campaign's design (teams, what counts, regions) is edited here and saved with the project; the campaign file
// is what its server runs and what the other machines' owners load to join.
function OnlineCoop({ n }) {
  const o = n.online;
  const [d, setD] = useState(o ? o.design : null);
  const [dirty, setDirty] = useState(false);
  const designKey = o ? JSON.stringify(o.design) : "";
  useEffect(() => { if (o) { setD(o.design); setDirty(false); } }, [designKey]);
  if (!o || !d) return null;
  const lim = o.limits || {};
  const edit = (fn) => { const c = JSON.parse(JSON.stringify(d)); fn(c); setD(c); setDirty(true); };
  const set = (k) => (v) => call("network.online_set", { [k]: v });
  const goal = d.goal || { kind: "score" };
  const unit = goal.kind === "score" ? "points" : (goal.count || "count");
  const teams = (o.teams || []).map((t) => ({ value: t, label: t }));
  return html`<${Card} cls="net-opt" title="Online co-op">
    <p class="net-does">Machines in different places play toward one shared goal. At the end of every game this
      machine posts its score, and any online counts its modes add to, to the campaign's server, which adds every
      machine's games up for its team and posts the campaign's map to Discord.</p>
    <${Check} checked=${o.on} wrap label="Play in an online co-op campaign" onChange=${(v) => call("network.online_on", v)} />
    <div class="net-field"><span class="lbl">The campaign's server</span>
      <${Field} value=${o.url} mono placeholder=${o.placeholder} bad=${o.on && !o.url}
        title="The server's address: http://, its public IP address, its port. The machine looks no names up and does not do https."
        onChange=${() => {}} onCommit=${set("url")} /></div>
    <div class="net-field"><span class="lbl">Campaign</span>
      <${Field} value=${o.campaign} maxLength=${lim.word} placeholder="Kaiju War" title="The campaign's name, the same on every machine in it (the campaign file has it)"
        onChange=${() => {}} onCommit=${set("campaign")} /></div>
    <div class="net-field"><span class="lbl">This machine's team</span>
      <${Select} value=${o.team} options=${[{ value: "", label: "(pick a team)" }, ...teams]} onChange=${set("team")}
        title="Every game on this machine counts for this team" /></div>
    <div class="net-field"><span class="lbl">This machine's name</span>
      <${Field} value=${o.machine} maxLength=${lim.word} placeholder="Dave's Godzilla LE" title="How the server and the map name this machine"
        onChange=${() => {}} onCommit=${set("machine")} /></div>
    <div class="net-field"><span class="lbl">Join key</span>
      <${Field} value=${o.key} mono maxLength=${lim.key} placeholder="(none)" title="The campaign's join key, when its server asks for one: the server counts no game without it"
        onChange=${() => {}} onCommit=${set("key")} /></div>
    <${Said} text=${o.note} kind=${o.kind} />
    <${Advanced} title="Campaign design: teams, what counts, regions">
      <div class="net-oc-row">
        <span class="lbl">Start from</span>
        ${(o.examples || []).map(([k, t]) => html`<${Button} key=${k} size="sm" onClick=${() => call("network.online_example", k)}>${t}<//>`)}
      </div>
      <div class="net-field"><span class="lbl">Title on the map</span>
        <${Field} value=${d.title} maxLength=${63} onChange=${(v) => edit((c) => { c.title = v; })} /></div>
      <div class="net-oc-row"><span class="lbl">What counts</span>
        <${Select} value=${goal.kind} options=${[{ value: "score", label: "each game's score" }, { value: "count", label: "an online count" }]}
          onChange=${(v) => edit((c) => { c.goal = v === "score" ? { kind: "score" } : { kind: "count", count: (o.counts || [])[0] || "rescued" }; })} />
        ${goal.kind === "count" ? html`<${Field} value=${goal.count} mono width=${150} maxLength=${lim.count} list="net-oc-counts"
          title=${"The name a mode of yours adds to (the Modes tab's Scoring page or a blocks mode's Add to online count)" + ((o.counts || []).length ? ": " + o.counts.join(", ") : "")}
          onChange=${(v) => edit((c) => { c.goal = { kind: "count", count: v }; })} />
          <datalist id="net-oc-counts">${(o.counts || []).map((x) => html`<option key=${x} value=${x} />`)}</datalist>` : null}
      </div>
      <div class="lbl">Teams</div>
      ${(d.teams || []).map((t, i) => html`<div class="net-oc-row" key=${"t" + i}>
        <input type="color" class="net-oc-colour" value=${t.colour} title="The team's colour on the map"
          onInput=${(e) => edit((c) => { c.teams[i].colour = e.target.value; })} />
        <${Field} value=${t.name} width=${180} maxLength=${lim.word} onChange=${(v) => edit((c) => { c.teams[i].name = v; })} />
        <${Button} size="sm" title="Remove this team" disabled=${(d.teams || []).length < 2} onClick=${() => edit((c) => { c.teams.splice(i, 1); })}>×<//>
      </div>`)}
      <${Button} size="sm" disabled=${(d.teams || []).length >= lim.teams} onClick=${() => edit((c) => {
        c.teams.push({ name: "Team " + (c.teams.length + 1), colour: (o.colours || [])[c.teams.length % 8] || "#888888" }); })}>Add a team<//>
      <div class="lbl">Regions, taken in this order: the first team to reach a region's target (in ${unit}) takes it</div>
      ${(d.regions || []).map((r, i) => html`<div class="net-oc-row" key=${"r" + i}>
        <${Field} value=${r.name} width=${120} maxLength=${31} onChange=${(v) => edit((c) => { c.regions[i].name = v; })} />
        <${Field} value=${String(r.target)} mono width=${112} title=${"How many " + unit + " take it"}
          onChange=${(v) => edit((c) => { c.regions[i].target = parseInt(String(v).replace(/[^0-9]/g, "") || "0", 10); })} />
        <${Button} size="sm" title="Remove this region" disabled=${(d.regions || []).length < 2} onClick=${() => edit((c) => { c.regions.splice(i, 1); })}>×<//>
      </div>`)}
      <${Button} size="sm" disabled=${(d.regions || []).length >= lim.regions} onClick=${() => edit((c) => {
        const last = c.regions[c.regions.length - 1];
        c.regions.push({ name: "Region " + (c.regions.length + 1), target: last ? last.target * 2 : 1000000 }); })}>Add a region<//>
      <div class="net-oc-row">
        <${Button} kind="primary" size="sm" disabled=${!dirty} onClick=${() => call("network.online_design", d)}>Save the design<//>
        ${dirty ? html`<${Button} size="sm" onClick=${() => { setD(o.design); setDirty(false); }}>Undo changes<//>` : null}
      </div>
    <//>
    <div class="net-oc-row">
      <${Button} size="sm" onClick=${() => call("network.online_save_campaign")}>Save campaign file…<//>
      <${Button} size="sm" onClick=${() => call("network.online_load_campaign")}>Load campaign file…<//>
    </div>
    <${Advanced} title="Run the campaign's server">
      <p class="small">One computer runs the campaign's server for every machine in it: a small cloud server, or a
        computer at home with the port forwarded from the router. It needs a fixed public IPv4 address, because the
        machines look no names up. Save the campaign file, then run (Python 3.9 or newer, with Pillow for the map):</p>
      <pre class="mono net-pre">${o.server}</pre>
      <p class="small muted">The webhook is a Discord channel's (Edit Channel, Integrations, Webhooks). The server posts
        the map there as a region is taken and when the campaign is won; its own page shows the map at any time.</p>
    <//>
    <${Ways} n=${n} panel="score_feed" />
  <//>`;
}

// PAD-1427: what the friendly path leaves out, folded away (the score feed's API contract does the same)
function Advanced({ title = "Advanced", children }) {
  const [open, setOpen] = useState(false);
  return html`<div class="net-contract net-adv">
    <button type="button" class="net-contract-hd" aria-expanded=${open} onClick=${() => setOpen(!open)}>
      ${open ? "▾" : "▸"} ${title}</button>
    ${open ? html`<div class="net-contract-bd">${children}</div>` : null}
  </div>`;
}

// The project's own setting (PR #38): whether a card Written from it carries remote access, and, under Advanced,
// the public keys of the user's own SSH programs
function ProjectRemote({ n }) {
  const [keys, setKeys] = useState(n.public_keys || "");
  const [enabled, setEnabled] = useState(!!n.enabled);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    setKeys(n.public_keys || ""); setEnabled(!!n.enabled); setDirty(false);
  }, [n.project, n.source]);
  useEffect(() => {
    if (!dirty && document.activeElement?.id !== "net-ssh-public-keys") {
      setKeys(n.public_keys || ""); setEnabled(!!n.enabled);
    }
  }, [n.enabled, n.public_keys]);
  const locked = !n.supported || n.running;
  const save = (on, text) => call("network.configure", on, text, n.project);
  useEffect(() => {
    if (!dirty || locked) return;
    const timer = setTimeout(() => { save(enabled, keys); setDirty(false); }, 350);
    return () => clearTimeout(timer);
  }, [keys, enabled, dirty, locked, n.project]);
  if (!n.project) return null;
  return html`<div class="net-sub">
    ${!n.supported ? html`<${Note}>${n.reason}<//>` : null}
    <${Check} label="Keep remote access on cards I write from this project" checked=${enabled} disabled=${locked}
      wrap onChange=${(on) => { setEnabled(on); save(on, keys); }} />
    <span class="small muted">Writing a card without it takes remote access off the machine again.</span>
    <${Advanced} title="Advanced: let your own SSH programs in too">
      <p class="small">PAD needs nothing here: it keeps its own key. To log in with a program of your own as well,
        paste your SSH key's <b>public</b> half below (the line that starts${" "}
        <span class="mono">ssh-ed25519</span>, <span class="mono">ssh-rsa</span> or <span class="mono">ecdsa-</span>),
        one per line, then connect as <span class="mono">root</span> on port 22 at the machine's address.</p>
      <${Note} kind="warn">Anyone with a matching key has full control of the machine. There is no password login.<//>
      <label for="net-ssh-public-keys" class="lbl">Public keys (one per line)</label>
      <textarea id="net-ssh-public-keys" class="field mono net-keys" rows="5" spellcheck="false"
        value=${keys} disabled=${locked} placeholder="ssh-ed25519 AAAA… my-laptop"
        onInput=${(e) => { setKeys(e.target.value); setDirty(true); }}
        onBlur=${() => { if (dirty && !locked) { save(enabled, keys); setDirty(false); } }} />
      <span class="small muted">${dirty ? "Saving…" : "Saved with this project and put on the card when you Write it. Never included in a mod pack you share."}</span>
    <//>
    ${n.error ? html`<p role="alert" class="err-ink">${n.error}</p>` : null}
  </div>`;
}

// PAD-1427 (David: "modify an attached SD card with the push of a button ... they don't have to manually enter
// secrets or keys"): the machine's card in this computer's reader gets remote access in place
function RemoteAccess({ n }) {
  const cards = n.cards || [];
  const opts = cards.length ? cards.map((c) => ({ value: c.device, label: c.display }))
    : [{ value: "", label: n.cards_state === "detecting" ? "Looking for cards…" : "No card found" }];
  const busy = n.setup_busy || n.running;
  return html`<${Card} cls="net-opt" title="Remote access">
    <p class="net-does">Lets PAD send your changes to the machine over your home network, without taking the SD
      card out again. Set it up once: put the machine's SD card in this computer's card reader and press the button.
      There is nothing to type: PAD keeps its own key on this computer.</p>
    <label for="net-card" class="lbl">The machine's SD card</label>
    <div class="row net-send-row">
      <${Select} id="net-card" cls="grow" value=${n.card || ""} options=${opts} title=${n.card || ""}
        disabled=${!cards.length || busy} onChange=${(v) => call("network.pick_card", v)} />
      <${Button} icon="refresh" disabled=${busy} onClick=${() => call("network.refresh_cards")}>Refresh<//>
    </div>
    ${n.cards_state === "none" ? html`<span class="small muted">Put the machine's SD card in this computer's card
      reader, then Refresh.</span>` : null}
    <div class="row net-send-row">
      <${Button} kind="primary" disabled=${busy || !n.card} onClick=${() => call("network.set_up_card")}>
        ${n.setup_busy ? "Setting up…" : "Set up remote access on this card"}<//>
      <${Button} kind="ghost" disabled=${busy} title="Put remote access on a card image file instead, then write it to the card as usual"
        onClick=${() => call("network.set_up_image")}>Use a card image file…<//>
    </div>
    ${n.setup_busy ? html`<${Progress} pct=${n.setup_pct} />` : null}
    <${Said} text=${n.setup_note} kind=${n.setup_kind} />
    <${ProjectRemote} n=${n} />
    <${Ways} n=${n} panel="remote_access" />
  <//>`;
}

// PAD-1397: Send to machine - the machine's address, a check that this computer gets in, and any card image sent
// over (the Write tab's Send to machine builds and sends the project's own changes).  PAD-1427: the machine is
// found by a scan and remembered; typing its address is under Advanced.
function SendToMachine({ n }) {
  const busy = n.running || n.checking || n.scanning;
  const found = n.found || [];
  const machines = n.machines || [];
  // David: "I can have MANY machines on my network": every one found is remembered, and this picks where Send goes
  return html`<${Card} cls="net-opt" title=${machines.length > 1 ? "Your machines" : "Your machine"}>
    <p class="net-does">${n.send_intro}</p>
    ${machines.length > 1 ? html`<div class="net-field">
        <label for="net-machine" class="lbl">Send to</label>
        <${Select} id="net-machine" value=${n.address || ""} disabled=${busy}
          options=${machines.map((m) => ({ value: m.address, label: m.label }))}
          onChange=${(v) => call("network.use_machine", v)} />
        <span class="small muted">Send to machine on the Write tab picks the machine that runs that card's game
          by itself.</span>
      </div>`
      : html`<div class="net-machine">
      ${n.address ? html`<span>Your machine: <b>${n.machine_game || "the machine"}</b> at <span class="mono">${n.address}</span></span>`
        : html`<span class="muted">No machine yet: switch it on, then Find my machine.</span>`}
    </div>`}
    <div class="row net-send-row">
      <${Button} kind=${n.address ? "" : "primary"} icon="search" disabled=${busy} onClick=${() => call("network.scan")}>
        ${n.scanning ? "Looking…" : "Find my machine"}<//>
      <${Button} disabled=${busy || !n.address} onClick=${() => call("network.check_connection")}>${n.checking ? "Checking…" : "Check connection"}<//>
      <${Button} kind=${n.address ? "primary" : ""} disabled=${busy || !n.address} title="Pick any card image: a new code version, a custom code card, a multi-boot card or a build"
        onClick=${() => call("network.send_image")}>Send an image to the machine…<//>
    </div>
    ${n.scanning ? html`<${Progress} pct=${n.scan_pct} />` : null}
    <${Said} text=${n.scan_note} kind=${n.scan_kind} />
    ${found.length ? html`<ul class="net-found">
      ${found.map((f) => html`<li key=${f.address} class="muted"><span>${f.line}</span></li>`)}
    </ul>` : null}
    <${Said} text=${n.check} kind=${n.check_kind} />
    <${Advanced} title="Advanced: type the machine's address">
      <label for="net-send-address" class="lbl">The machine's address on your network</label>
      <${Field} id="net-send-address" value=${n.address || ""} mono placeholder="192.168.1.40"
        title="Its IP address or name (192.168.1.40, or 192.168.1.40:2222 for another port). Your router's list of connected devices shows it."
        onChange=${() => {}} onCommit=${(v) => call("network.set_address", v)} />
      ${n.known ? html`<div><${Button} kind="ghost" disabled=${busy} title="If the machine's card was written from scratch, it has a new identity: forget the old one"
        onClick=${() => call("network.forget_machine")}>Forget this machine<//></div>` : null}
    <//>
  <//>`;
}

// PAD-1467: a card whose Wi-Fi program talks to the adapter the current way (core/wifi_card.py). Measured on a
// Godzilla with an AC1200 adapter: the shipped way failed nine joins of nine in 150 s on one access point,
// this one joined at the first attempt, 14 s after it started.
function WifiStartup({ n }) {
  const [enabled, setEnabled] = useState(!!n.wifi_enabled);
  const [band, setBand] = useState(!!n.wifi_band5);
  useEffect(() => { setEnabled(!!n.wifi_enabled); setBand(!!n.wifi_band5); },
    [n.wifi_enabled, n.wifi_band5, n.project, n.source]);
  const locked = !n.wifi_supported || n.running;
  const bandLocked = locked || !enabled || !n.wifi_band5_supported;
  // David: "the wifi panel is also reading as a wall of text ... trim it up and make it legible and clean. we can put
  // extra advanced details behind other ticks": the purpose in a line, the two boxes with a line each, the short
  // comparison, and everything else folded away
  const details = (rows, now) => html`<table class="net-fields net-wifi-details">
    <tbody>${(rows || []).map((r) => html`<tr key=${r[0]}><th scope="row">${r[0]}</th>
      <td class=${r[2] ? "mono" : ""}>${r[1]}</td></tr>`)}
      ${now ? html`<tr><th scope="row">The card you picked has</th><td class="mono">${now}</td></tr>` : null}
    </tbody></table>`;
  return html`<${Card} cls="net-opt" title="Wi-Fi">
    <p class="net-does">Makes the machine join your Wi-Fi at the first try, and on 5 GHz if it has an AC1200
      adapter.</p>
    ${!n.wifi_supported ? html`<${Note}>${n.wifi_reason}<//>` : null}
    ${n.wifi_hint ? html`<span class="small muted">${n.wifi_hint}</span>` : null}
    <div class="net-pick">
      <${Check} label="Use the reliable Wi-Fi start-up on cards I write from this project" checked=${enabled}
        disabled=${locked} wrap
        onChange=${(on) => { setEnabled(on); if (!on) setBand(false); call("network.configure_wifi", on, n.project); }} />
      <span class="small muted">Joins in about 15 seconds instead of minutes. Your network, band and password are
        not changed.</span>
    </div>
    <div class="net-pick">
      ${n.wifi_supported && !n.wifi_band5_supported && n.wifi_band5_reason
        ? html`<${Note}>${n.wifi_band5_reason}<//>` : null}
      <${Check} label="Also use the newer adapter driver, so the machine can join on 5 GHz" checked=${band}
        disabled=${bandLocked} wrap
        onChange=${(on) => { setBand(on); call("network.configure_wifi", enabled, n.project, on); }} />
      <span class="small muted">For AC1200 (RTL8822BU) adapters only. Send to machine runs several times faster.
        Needs the box above.</span>
    </div>
    ${n.wifi_compare ? html`<div class="lbl">What each option gets you</div>
      <table class="net-fields net-wifi-compare">
        <thead><tr>${n.wifi_compare.head.map((h, i) => html`<th scope="col" key=${i}>${h}</th>`)}</tr></thead>
        <tbody>${n.wifi_compare.rows.map((r, i) => html`<tr key=${r[0]}
          class=${(i === 0 && !enabled) || (i === 1 && enabled && !band) || (i === 2 && band) ? "net-wifi-yours" : ""}>
          <th scope="row">${r[0]}</th>${r.slice(1).map((c, j) => html`<td key=${j}>${c}</td>`)}</tr>`)}</tbody>
      </table>` : null}
    ${n.wifi_compare ? html`<${Advanced} title="How these were measured">
      <span class="small muted">${n.wifi_compare.note}</span>
      <span class="small muted">Start-up: with <span class="mono">wext</span>, nine tries of nine to join failed
        on one access point; with <span class="mono">nl80211</span> it joined at the first try, 14 to 15 seconds
        after <span class="mono">wpa_supplicant</span> started, on three starts of three.</span>
      <span class="small muted">5 GHz: the shipped driver was dropped on 12 tries of 12; the newer one joined and
        held (channel 40, 80 MHz wide).</span>
    <//>` : null}
    ${n.wifi_adapters ? html`<${Advanced} title="Which adapter do I need for 5 GHz?">
      <table class="net-fields net-wifi-compare">
        <thead><tr>${n.wifi_adapters.head.map((h) => html`<th scope="col" key=${h}>${h}</th>`)}</tr></thead>
        <tbody>${n.wifi_adapters.rows.map((r) => html`<tr key=${r[0]}>
          <th scope="row">${r[0]}</th>${r.slice(1).map((c, j) => html`<td key=${j}>${c}</td>`)}</tr>`)}</tbody>
      </table>
      <span class="small muted">${n.wifi_adapters.note}</span><//>` : null}
    <${Advanced} title="Exactly what it changes on the card: Wi-Fi start-up">
      <span class="small muted">As shipped, the machine starts its Wi-Fi program (<span class="mono">wpa_supplicant</span>)
        with the old <span class="mono">wext</span> driver interface, with which joining often fails and is tried
        again. This starts it with the current one, <span class="mono">nl80211</span>, and keeps${" "}
        <span class="mono">wext</span> as the fallback.</span>
      ${details(n.wifi_details, n.wifi_now)}
    <//>
    <${Advanced} title="Exactly what it changes on the card: 5 GHz driver">
      <span class="small muted">The driver the machine ships for its AC1200 adapter (Realtek RTL8822BU, a 2018
        build) is dropped by a current router the moment it joins on 5 GHz. A newer build of the same Realtek
        driver holds it; the machine then moves to your network's 5 GHz signal when it is in reach, and stays on
        2.4 GHz when it is not. The driver is Realtek's own open-source code, unmodified; its source and how it
        was built are in the app's <span class="mono">resources/wifi</span> folder.</span>
      ${details(n.wifi_band_details, n.wifi_band_now)}
    <//>
    <${Ways} n=${n} panel="wifi" />
    <${Direct} n=${n} kind="wifi" />
    ${n.wifi_error ? html`<p role="alert" class="err-ink">${n.wifi_error}</p>` : null}
  <//>`;
}

// PAD-1467: what the machine's own screen shows, over remote access (core/machine_screen.py): one picture, or a
// live view the page server plays as a changing picture (/screen).  David: "the remote screenshot feature is
// actually really useful" and "a 'screen share' live feed ... would be killer".
function MachineScreen({ n }) {
  const busy = n.running || n.checking || n.scanning || n.screen_busy;
  const token = encodeURIComponent(new URLSearchParams(location.search).get("t") || "");
  return html`<${Card} cls="net-opt" title="Machine screen">
    <p class="net-does">See what your machine's own screen shows right now, from here. It only reads the screen:
      the game keeps running and nothing on the machine is changed. It needs remote access on the machine's card,
      like Send to machine.</p>
    <div class="row">
      <${Button} kind=${n.screen_live ? "" : "primary"} disabled=${busy || n.screen_live || !n.address}
        onClick=${() => call("network.capture_screen")}>${n.screen_busy ? "Capturing…" : "Capture the screen"}<//>
      ${n.screen_live
        ? html`<${Button} kind="primary" onClick=${() => call("network.stop_live")}>Stop live view<//>`
        : html`<${Button} disabled=${busy || !n.address} onClick=${() => call("network.start_live")}>Live view<//>`}
      <${Button} disabled=${!(n.screen_path || n.screen_live)}
        onClick=${() => call("network.save_screen")}>Save picture…<//>
      ${n.screen_live || n.screen_recording ? html`<${Button}
        onClick=${() => call("network.record_live", !n.screen_recording)}>${n.screen_recording ? "Stop and save the recording…" : "Record"}<//>` : null}
    </div>
    ${n.screen_live
      ? html`<img class="net-screen" alt="The machine's screen, live"
          src=${"/screen?t=" + token + "&v=" + (n.screen_live_id || 0)} />`
      : n.screen_path
        ? html`<img class="net-screen" alt="The machine's screen" src=${mediaUrl(n.screen_path) + "&v=" + (n.screen_seq || 0)} />`
        : null}
    <${Said} text=${n.screen_note} kind=${n.screen_kind} />
    ${n.buttons_offered ? html`<div class="lbl">Remote buttons</div>
      <div class="row net-btn-row">
        ${(n.buttons_labels || []).map(([key, label]) => html`<${Button} key=${key}
          disabled=${n.running || !n.address} onClick=${() => call("network.press_button", key)}>${label}<//>`)}
      </div>
      <${Said} text=${n.buttons_note} kind=${n.buttons_kind} />
      <span class="small muted">The machine's coin-door service buttons, pressed from here: they work only while
        the coin door is open, as the real ones do (that is also when the machine's coil power is off). With Live
        view running a press is immediate; without it each takes a second or two. The machine's card needs
        Remote buttons on it (the box beside this card).</span>
      ` : null}
    <span class="small muted">Live view shows a few frames a second, up to about 5 on 5 GHz Wi-Fi (measured on a Godzilla LE; less
      on 2.4 GHz), with no sound. It is for setting up and troubleshooting: while it runs it takes most of the machine's Wi-Fi and some of its processor, so do not leave it on during a game that matters. The pictures of the screen cross your home network on a plain connection, as
      Send to machine's big files do. It stops when you leave this tab, and by itself after 30 minutes.</span>
  <//>`;
}

// PAD-1467: the remote-buttons choice, with the other things a card can carry (the buttons themselves are under
// the machine's screen)
function RemoteButtonsOption({ n }) {
  return html`<${Card} cls="net-opt" title="Remote buttons">
    <p class="net-does">Lets you press the machine's coin-door service buttons (Back, Minus, Plus, Enter) from this
      computer, under the machine's screen. They work only while the coin door is open, as the real
      ones do.</p>
    ${!n.buttons_supported && n.buttons_reason ? html`<${Note}>${n.buttons_reason}<//>` : null}
    ${n.buttons_hint ? html`<span class="small muted">${n.buttons_hint}</span>` : null}
    <${Check} label="Put remote buttons on cards I write from this project" checked=${!!n.buttons_enabled}
      disabled=${!n.buttons_supported || n.running} wrap
      onChange=${(on) => call("network.configure_buttons", on, n.project)} />
    <${Advanced} title="Exactly what it changes on the card">
      <table class="net-fields net-wifi-details">
        <tbody>${(n.buttons_details || []).map((r) => html`<tr key=${r[0]}><th scope="row">${r[0]}</th>
          <td class=${r[2] ? "mono" : ""}>${r[1]}</td></tr>`)}
          ${n.buttons_now ? html`<tr><th scope="row">The card you picked has</th><td class="mono">${n.buttons_now}</td></tr>` : null}
        </tbody></table>
    <//>
    <${Ways} n=${n} panel="buttons" />
    <${Direct} n=${n} kind="buttons" />
    ${n.buttons_error ? html`<p role="alert" class="err-ink">${n.buttons_error}</p>` : null}
  <//>`;
}

// PAD-1467: looking after the machine over remote access (core/machine_care.py): its status, logs, settings and
// scores, a restart, PAD's mode log.  David: "grabbing logs from the machine would be very
// useful. what else?" ... "make all of these".
function MachineCare({ n }) {
  const off = n.running || !!n.care_busy || !n.address;
  return html`<${Card} cls="net-opt" title="Machine care">
    <p class="net-does">Look after your machine from here, over remote access: see how it is doing, collect its
      logs for a problem report, keep its settings and high scores safe, or restart it.</p>
    <div class="lbl">Status</div>
    <div class="row"><${Button} disabled=${off} onClick=${() => call("network.machine_status")}>Read the status<//></div>
    ${(n.care_status || []).length ? html`<table class="net-fields net-wifi-details">
      <tbody>${n.care_status.map((r) => html`<tr key=${r[0]}><th scope="row">${r[0]}</th><td>${r[1]}</td></tr>`)}</tbody>
    </table>` : null}
    <div class="lbl">Logs</div>
    <div class="row">
      <${Button} disabled=${off} onClick=${() => call("network.grab_logs")}>Save the logs…<//>
      <${Button} disabled=${n.running || !n.address}
        onClick=${() => call("network.follow_log", !n.care_following)}>${n.care_following ? "Stop following" : "Follow the mode log"}<//>
    </div>
    <span class="small muted">One zip: the system and kernel logs, PAD's mode log, the connectivity logs and a
      report of the machine's state. It names your Wi-Fi network and the machine's addresses; it holds no
      password.</span>
    ${n.care_following || n.care_log ? html`<pre class="net-log">${n.care_log || ""}</pre>` : null}
    <div class="lbl">Settings, audits and high scores</div>
    <div class="row">
      <${Button} disabled=${off} onClick=${() => call("network.backup_settings")}>Back up…<//>
      <${Button} disabled=${off} onClick=${() => call("network.restore_settings")}>Restore…<//>
    </div>
    <span class="small muted">The game keeps them on a small part of the card that writing a whole card wipes.
      A backup is a small zip; a restore holds the game for a few seconds and keeps what it replaces on the
      machine once.</span>
    <div class="lbl">Restart</div>
    <div class="row">
      <${Button} disabled=${off} onClick=${() => call("network.restart_game")}>Restart the game<//>
      <${Button} disabled=${off} onClick=${() => call("network.restart_machine")}>Restart the machine<//>
    </div>
    ${n.care_busy ? html`<span class="small">${n.care_busy}…</span>` : null}
    ${n.care_pct != null ? html`<${Progress} pct=${n.care_pct} />` : null}
    <${Said} text=${n.care_note} kind=${n.care_kind} />
  <//>`;
}

export default function NetworkTab() {
  const n = useNs("network");
  const s = useNs("modes");
  return html`<div class="page net-page">
    <${PageHead} title="Network" sub=${n.intro} />
    ${n.offered === false ? html`<${Note}>Remote access works on Stern Spike 2 and Spike 3 cards only.<//>` : null}
    <div class="net-layout">
      ${(n.project && s.feed_shown) || n.wifi_offered ? html`<section class="net-group" aria-label="Network settings">
        <div class="net-group-hd"><b>Network settings</b><span class="muted small">What the machine does on your
          network by itself. Saved with this project and put on the card when you write it</span></div>
        <div class="net-col">
          ${n.project && s.feed_shown ? html`<${ScoreFeed} s=${s} n=${n} />` : null}
          ${n.project && s.feed_shown ? html`<${OnlineCoop} n=${n} />` : null}
          ${!(n.project && s.feed_shown) && n.online_missing ? html`<${Card} cls="net-opt" title="Score feed and Online co-op">
            <${Note}>${n.online_missing}<//>
          <//>` : null}
          ${n.wifi_offered ? html`<${WifiStartup} n=${n} />` : null}
        </div>
      </section>` : null}
      ${n.offered !== false ? html`<section class="net-group" aria-label="Remote access">
        <div class="net-group-hd"><b>Remote access</b><span class="muted small">Reach the machine from this computer
          over your network: send changes, see its screen, look after it. Set it up once, on the card</span></div>
        <div class="net-cols2">
          <div class="net-col">
            <${RemoteAccess} n=${n} />
            <${SendToMachine} n=${n} />
            ${n.buttons_offered ? html`<${RemoteButtonsOption} n=${n} />` : null}
          </div>
          <div class="net-col">
            <${MachineScreen} n=${n} />
            <${MachineCare} n=${n} />
          </div>
        </div>
      </section>` : null}
    </div>
  </div>`;
}
