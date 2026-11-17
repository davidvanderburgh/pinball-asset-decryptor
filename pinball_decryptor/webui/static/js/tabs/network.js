// Network (PR #38 review, David's call): what a card does with the owner's home network, each said plainly for
// someone who has never heard of it. The score feed (PAD-1204) moved here from Play options, whose other options
// change how the game plays; its state and actions are the Modes service's (the `modes` namespace). Remote access
// (SSH, PR #38) is this tab's own (the `network` namespace).
import { html, useState, useEffect, PageHead, Card, Field, Check, Note, Empty, call, cx } from "../core/ui.js";
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
  return text ? html`<span class=${cx("small", kind === "err" ? "err-ink" : "muted")}>${text}</span>` : null;
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

function RemoteAccess({ n }) {
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
  return html`<${Card} cls="net-opt" title="Remote access (SSH)">
    <p class="net-does">Lets a computer on your home network log in to the machine and copy files to and from it,
      without taking the SD card out. People use it to:</p>
    <ul class="net-uses">
      <li>copy the machine's saved settings and high scores off it, as a backup</li>
      <li>read the game's logs when something goes wrong</li>
      <li>run add-on programs of their own on the machine</li>
    </ul>
    <p class="net-does">You need an SSH key on your computer. Paste its <b>public</b> half below (the line that starts
      <span class="mono">ssh-ed25519</span>, <span class="mono">ssh-rsa</span> or <span class="mono">ecdsa-</span>),
      one per line, then connect as <span class="mono">root</span> on port 22 at the machine's address on your network.</p>
    <${Note} kind="warn">Leave it off if you are not sure you need it. Anyone with a matching key has full control of
      the machine. There is no password login.<//>
    ${!n.supported ? html`<${Note}>${n.reason}<//>` : null}
    <${Check} label="Turn on remote access" checked=${enabled} disabled=${locked}
      onChange=${(on) => { setEnabled(on); save(on, keys); }} />
    <div class="net-field">
      <label for="net-ssh-public-keys" class="lbl">Public keys (one per line)</label>
      <textarea id="net-ssh-public-keys" class="field mono net-keys" rows="6" spellcheck="false"
        value=${keys} disabled=${locked} placeholder="ssh-ed25519 AAAA… my-laptop"
        onInput=${(e) => { setKeys(e.target.value); setDirty(true); }}
        onBlur=${() => { if (dirty && !locked) { save(enabled, keys); setDirty(false); } }} />
    </div>
    ${n.error ? html`<p role="alert" class="err-ink">${n.error}</p>` : null}
    <span class="small muted">${dirty ? "Saving…" : n.error ? "Fix the keys before building."
      : "Saved with this project and put on the card when you Write it. Never included in a mod pack you share."}</span>
  <//>`;
}

export default function NetworkTab() {
  const n = useNs("network");
  const s = useNs("modes");
  return html`<div class="page net-page">
    <${PageHead} title="Network" sub=${n.intro} />
    ${!n.project ? html`<${Empty} icon="globe" title="No project">Open or extract a card project first (Extract tab):
        these settings are the project's.<//>`
      : html`<div class="net-grid">
        ${s.feed_shown ? html`<${ScoreFeed} s=${s} />` : null}
        <${RemoteAccess} n=${n} />
      </div>`}
  </div>`;
}
