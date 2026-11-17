import { html, useState, useEffect, PageHead, Card, Check, Note, call } from "../core/ui.js";
import { useNs } from "../core/store.js";

export default function ExtrasTab() {
  const s = useNs("extras");
  const [keys, setKeys] = useState(s.public_keys || "");
  const [enabled, setEnabled] = useState(!!s.enabled);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    setKeys(s.public_keys || ""); setEnabled(!!s.enabled); setDirty(false);
  }, [s.project, s.source]);
  useEffect(() => {
    if (!dirty && document.activeElement?.id !== "extras-ssh-public-keys") {
      setKeys(s.public_keys || ""); setEnabled(!!s.enabled);
    }
  }, [s.enabled, s.public_keys]);
  const locked = !s.supported || s.running;
  const save = (on, text) => call("extras.configure", on, text, s.project);
  useEffect(() => {
    if (!dirty || locked) return;
    const timer = setTimeout(() => { save(enabled, keys); setDirty(false); }, 350);
    return () => clearTimeout(timer);
  }, [keys, enabled, dirty, locked, s.project]);
  return html`<div class="page">
    <${PageHead} title="Extras" sub="Additional options for the card you build." />
    <${Card} title="SSH server">
      ${!s.supported ? html`<${Note}>${s.reason}<//>` : null}
      <${Check} label="Enable SSH server" checked=${enabled} disabled=${locked}
        onChange=${(on) => { setEnabled(on); save(on, keys); }} />
      <p class="small muted">Connect as root on port 22 using one of these public keys. Password login is disabled.</p>
      <label for="extras-ssh-public-keys" class="lbl">SSH public keys (one key per line)</label>
      <textarea id="extras-ssh-public-keys" class="field mono" rows="9" spellcheck="false"
        style="width:100%;resize:vertical;min-height:10rem" value=${keys} disabled=${locked}
        placeholder="ssh-ed25519 AAAA… computer-name"
        onInput=${(e) => { setKeys(e.target.value); setDirty(true); }}
        onBlur=${() => { if (dirty && !locked) { save(enabled, keys); setDirty(false); } }} />
      ${s.error ? html`<p role="alert" class="err-ink">${s.error}</p>` : null}
      <p class="small muted">${dirty ? "Saving…" : s.error ? "Changes need attention before building." : "Saved with this project. Applied when you build the card."}</p>
      <p class="small muted">SSH settings and keys are excluded from shared mods.</p>
    <//>
  </div>`;
}
