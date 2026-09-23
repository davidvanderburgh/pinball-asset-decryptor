// Pieces the JJP and Spike 1 Emulate tabs share: the live Volume / Mute
// knob (one control file for every rig), the state chip and the intro text.
// (The save-state name prompts are Tk's simpledialog.askstring, asked from
// Python through compat.simpledialog: the app's own prompt dialog.)

import { html, useEffect, useRef, useState, Check, Chip, tip, setField } from "../core/ui.js";

// The Tk intro was one label with a line break; keep the break.
export function introLines(text) {
  const parts = String(text || "").split("\n");
  return parts.map((p, i) => (i ? html`<br />${p}` : p));
}

// Volume 0-100 + Mute.  Every move writes the shared control file at once
// (Python's var trace), so a running game's sound follows the slider.
export function VolumeControl({ ns, s, title }) {
  const [v, setV] = useState(Math.round(s.volume ?? 100));
  const dragging = useRef(false);
  useEffect(() => { if (!dragging.current) setV(Math.round(s.volume ?? 100)); }, [s.volume]);
  const id = ns + "-vol";
  return html`<div class="row emu-vol" ...${tip(title)}>
    <label class="lbl" for=${id}>Volume</label>
    <input type="range" id=${id} min="0" max="100" step="1" value=${v}
      onPointerDown=${() => { dragging.current = true; }}
      onInput=${(e) => { const n = Number(e.target.value); setV(n); setField(ns, "volume", n, { delay: 60 }); }}
      onChange=${(e) => { dragging.current = false; setField(ns, "volume", Number(e.target.value), { flush: true }); }} />
    <span class="mono muted emu-volv">${v}</span>
    <${Check} ns=${ns} k="mute" checked=${!!s.mute} label="Mute" />
  </div>`;
}

export function StateChip({ tone, label }) {
  if (!label) return null;
  return html`<${Chip} kind=${tone || ""} dot>${label}<//>`;
}
