// Network (PR #38 review, David's call): what a card does with the owner's home network, each said plainly for
// someone who has never heard of it. The score feed (PAD-1204) moved here from Play options, whose other options
// change how the game plays; its state and actions are the Modes service's (the `modes` namespace). Remote access
// (SSH, PR #38) is this tab's own (the `network` namespace).
import { html, useState, useEffect, PageHead, Card, Field, Check, Note, Button, Select, Progress, call, cx } from "../core/ui.js";
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

function ScoreFeed({ s }) {
  return html`<${Card} cls="net-opt" title="Score feed">
    <p class="net-does">${s.feed_tip}</p>
    <${Check} checked=${s.feed_on} wrap label="Score feed" onChange=${(v) => call("modes.set_score_feed", v)} />
    ${s.feed_on ? html`<div class="net-field"><span class="lbl">Your server's address</span>
      <${Field} value=${s.feed_url} mono placeholder=${s.feed_placeholder} title=${s.feed_url_tip}
        bad=${s.feed_note_kind === "err"} onChange=${() => {}} onCommit=${(v) => call("modes.set_score_feed", true, v)} /></div>` : null}
    <${Said} text=${s.feed_note} kind=${s.feed_note_kind} />
    <${FeedContract} c=${s.feed_contract} />
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
  <//>`;
}

// PAD-1397: Send to machine - the machine's address, a check that this computer gets in, and any card image sent
// over (the Write tab's Send to machine builds and sends the project's own changes).  PAD-1427: the machine is
// found by a scan and remembered; typing its address is under Advanced.
function SendToMachine({ n }) {
  const busy = n.running || n.checking || n.scanning;
  const found = n.found || [];
  const many = found.filter((f) => f.lets_in).length > 1;
  return html`<${Card} cls="net-opt" title="Your machine">
    <p class="net-does">${n.send_intro}</p>
    <div class="net-machine">
      ${n.address ? html`<span>Your machine: <b>${n.machine_game || "the machine"}</b> at <span class="mono">${n.address}</span></span>`
        : html`<span class="muted">No machine yet: switch it on, then Find my machine.</span>`}
    </div>
    <div class="row net-send-row">
      <${Button} kind=${n.address ? "" : "primary"} icon="search" disabled=${busy} onClick=${() => call("network.scan")}>
        ${n.scanning ? "Looking…" : "Find my machine"}<//>
      <${Button} disabled=${busy || !n.address} onClick=${() => call("network.check_connection")}>${n.checking ? "Checking…" : "Check connection"}<//>
      <${Button} kind=${n.address ? "primary" : ""} disabled=${busy || !n.address} title="Pick any card image: a new code version, a custom code card, a multi-boot card or a build"
        onClick=${() => call("network.send_image")}>Send an image to the machine…<//>
    </div>
    ${n.scanning ? html`<${Progress} pct=${n.scan_pct} />` : null}
    <${Said} text=${n.scan_note} kind=${n.scan_kind} />
    ${found.length && (many || !found.some((f) => f.lets_in)) ? html`<ul class="net-found">
      ${found.map((f) => html`<li key=${f.address} class=${f.lets_in ? "" : "muted"}>
        <span>${f.line}</span>
        ${f.lets_in ? html`<${Button} size="sm" disabled=${busy} onClick=${() => call("network.use_machine", f.address)}>This one<//>` : null}
      </li>`)}
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

export default function NetworkTab() {
  const n = useNs("network");
  const s = useNs("modes");
  return html`<div class="page net-page">
    <${PageHead} title="Network" sub=${n.intro} />
    ${n.offered === false ? html`<${Note}>Remote access works on Stern Spike 2 and Spike 3 cards only.<//>` : null}
    <div class="net-grid">
      ${n.offered !== false ? html`<${RemoteAccess} n=${n} />` : null}
      ${n.offered !== false ? html`<${SendToMachine} n=${n} />` : null}
      ${n.project && s.feed_shown ? html`<${ScoreFeed} s=${s} />` : null}
    </div>
  </div>`;
}
