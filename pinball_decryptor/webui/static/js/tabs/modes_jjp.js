// Modes on a Jersey Jack game (PAD-1350): custom modes for the JJP mode SDK. A title's modes are
// one folder of key = value files the runtime reads inside the retail game; this page edits them
// as forms, every name (switches, lamps, lamp groups, sounds, fonts) picked from the title's port
// report, runs the build's own check after each edit, and builds the stock install ISO again
// with the modes in it.
//
// Python (webui/modes_jjp.py) owns every decision; this page renders modes.jjp and edits through
// call("modes.jjp_set", key, value).

import { html, useEffect, useRef, useState, Button, Field, PathField, Select, Chip, Note, Empty, cx, tip,
         call, mediaUrl } from "../core/ui.js";

const set = (k, v) => call("modes.jjp_set", k, v);
const words = (v) => String(v || "").split(/[\s,]+/).filter(Boolean);

// ------------------------------------------------------------------ hearing a game sound
let playing = null;
function Hear({ name, have }) {
  const [on, setOn] = useState(false);
  useEffect(() => () => { if (playing && playing.owner === setOn) { playing.audio.pause(); playing = null; } }, []);
  if (!name || !have || !have.has(name)) return null;
  const toggle = async (e) => {
    e.stopPropagation();
    if (playing) { playing.audio.pause(); playing.owner(false); const was = playing.name; playing = null; if (was === name) return; }
    const path = await call("modes.jjp_sound_path", name);
    if (!path) return;
    const audio = new Audio(mediaUrl(path));
    audio.onended = () => { setOn(false); if (playing && playing.audio === audio) playing = null; };
    audio.play().catch(() => setOn(false));
    playing = { audio, owner: setOn, name };
    setOn(true);
  };
  return html`<${Button} size="xs" kind="ghost" icon=${on ? "stop" : "play"} cls="jjpm-hear"
    title=${on ? "Stop" : "Hear " + name} onClick=${toggle}>${on ? "Stop" : "Hear"}<//>`;
}

// ------------------------------------------------------------------ the name picker
// A filtered list of the game's own names: one click picks (a list key adds or removes it).
function Picker({ names, value, multi, sound, have, onPick, onClose }) {
  const [q, setQ] = useState("");
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.focus();
    const key = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const on = new Set(multi ? words(value) : [value]);
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hits = (names || []).filter((n) => terms.every((t) => n.toLowerCase().includes(t)));
  const shown = hits.slice(0, 400);
  return html`<div class="jjpm-scrim" onClick=${onClose}>
    <div class="jjpm-picker card" onClick=${(e) => e.stopPropagation()}>
      <div class="row" style="gap:8px">
        <div class="field grow"><input ref=${ref} value=${q} placeholder=${`Search ${(names || []).length} names`}
          spellcheck="false" onInput=${(e) => setQ(e.target.value)} /></div>
        <${Button} size="sm" onClick=${onClose}>Done<//>
      </div>
      <div class="small muted">${hits.length} match${hits.length === 1 ? "" : "es"}${hits.length > shown.length ? `; the first ${shown.length} shown, type more to narrow it` : ""}${sound && have && have.size ? ` - ${have.size} of them can be heard` : ""}</div>
      <div class="jjpm-list">
        ${shown.map((n) => html`<div class=${cx("jjpm-item", on.has(n) && "on")} key=${n} onClick=${() => onPick(n)}>
          <span class="mono grow">${n}</span>${sound ? html`<${Hear} name=${n} have=${have} />` : null}
          ${on.has(n) ? html`<span class="jjpm-tick">✓</span>` : null}
        </div>`)}
      </div>
    </div>
  </div>`;
}

function NamePick({ k, value, names, multi, sound, have, title, inherit }) {
  const [open, setOpen] = useState(false);
  const list = multi ? words(value) : (value ? [value] : []);
  const pick = (n) => {
    if (!multi) { set(k, n); setOpen(false); return; }
    const cur = words(value);
    set(k, (cur.includes(n) ? cur.filter((x) => x !== n) : cur.concat([n])).join(" "));
  };
  const drop = (n) => set(k, multi ? words(value).filter((x) => x !== n).join(" ") : "");
  return html`<div class="jjpm-pick" data-key=${k}>
    ${list.length ? list.map((n) => html`<span class="jjpm-name" key=${n}><span class="mono">${n}</span>
        ${sound ? html`<${Hear} name=${n} have=${have} />` : null}
        <button type="button" class="jjpm-x" ...${tip("Take it out")} onClick=${() => drop(n)}>×</button></span>`)
      : inherit ? html`<span class="muted small" ...${tip("Set under Every mode of this game")}><span class="mono">${inherit}</span> (every mode)</span>`
      : html`<span class="muted small">none</span>`}
    <${Button} size="xs" cls="jjpm-pick-open" title=${title} onClick=${() => setOpen(true)}>${multi ? "Add…" : (list.length ? "Change…" : "Pick…")}<//>
    ${open ? html`<${Picker} names=${names} value=${value} multi=${multi} sound=${sound} have=${have}
      onPick=${pick} onClose=${() => setOpen(false)} />` : null}
  </div>`;
}

function Colour({ k, value, alpha, dflt }) {
  const v = (value || dflt || "ffffff").replace(/^#/, "");
  const rgb = "#" + (v.slice(0, 6).padEnd(6, "0"));
  const a = v.length >= 8 ? parseInt(v.slice(6, 8), 16) : 255;
  const put = (c, al) => set(k, c.replace(/^#/, "") + (alpha ? (al >= 255 ? "" : al.toString(16).padStart(2, "0")) : ""));
  return html`<div class="row nw" style="gap:8px">
    <label class="modes-swatch"><input type="color" value=${rgb} onChange=${(e) => put(e.target.value, a)} />
      <span class="chip-c" style=${`background:${rgb}`}></span></label>
    <span class="mono small">${v}</span>
    ${alpha ? html`<span class="small muted">see-through</span><input type="range" min="0" max="255" value=${255 - a}
      ...${tip("How much shows through")} onChange=${(e) => put(rgb, 255 - parseInt(e.target.value, 10))} />` : null}
    ${value ? html`<button type="button" class="jjpm-x" ...${tip("Back to the default")} onClick=${() => set(k, "")}>×</button>` : null}
  </div>`;
}

// one key of a mode (or of title.cfg: prefix "title:")
function Row({ k, prefix = "", meta, value, j, have }) {
  // an empty key of a mode takes Every mode of this game's value, else the runtime's default
  const inherit = prefix ? "" : ((j.title_cfg || {})[k] || "");
  const m = meta || {};
  const key = prefix + k;
  const names = j.names || {};
  let input;
  if (m.kind === "switches") input = html`<${NamePick} k=${key} value=${value} names=${names.switches} multi title="The game's switches" />`;
  else if (m.kind === "lamps") input = html`<${NamePick} k=${key} value=${value} names=${names.lamps} multi title="The game's lamps (lp_) and lamp groups (ls_)" />`;
  else if (m.kind === "events") input = html`<${NamePick} k=${key} value=${value} names=${names.events || []} multi title="The game's own events (its hook lists)" />`;
  else if (m.kind === "after") input = html`<${NamePick} k=${key} value=${value} names=${names.after || []} multi title="The game's own modes (a global or a class), or any" />`;
  else if (m.kind === "sound") input = html`<${NamePick} k=${key} value=${value} names=${names.sound} sound have=${have} title="The game's sounds" inherit=${inherit} />`;
  else if (m.kind === "font") input = html`<${NamePick} k=${key} value=${value} names=${names.font} title="The game's fonts" inherit=${inherit} />`;
  else if (m.kind === "rgb" || m.kind === "rgba") input = html`<${Colour} k=${key} value=${value} alpha=${m.kind === "rgba"} dflt=${inherit || m.default} />`;
  else if (m.kind === "choice") input = html`<${Select} sm value=${value || ""} onChange=${(v) => set(key, v)}
      options=${[{ value: "", label: inherit ? `(every mode: ${inherit})` : `(default: ${m.default})` }].concat(m.choices.map((c) => ({ value: c, label: c })))} />`;
  else input = html`<${Field} sm value=${value || ""} width=${m.kind === "int" ? 140 : 320} placeholder=${inherit ? "every mode: " + inherit : (m.default ? "default " + m.default : "")}
      type=${m.kind === "int" ? "number" : "text"} inputCls=${m.kind === "int" ? "num" : ""} onChange=${() => {}} onCommit=${(v) => set(key, v)} />`;
  return html`<div class="jjpm-row" data-key=${k}><span class="jjpm-lbl">${m.label || k}</span><div class="jjpm-in">${input}</div></div>`;
}

function ModeList({ j }) {
  const modes = j.modes || [];
  const full = modes.length >= (j.max || 24);
  return html`<section class="card jjpm-list-card">
    <div class="hd"><span class="h2">Your modes</span><span class="muted small">${modes.length} of ${j.max}</span></div>
    <div class="bd">
      ${modes.map((m) => html`<div class=${cx("jjpm-mode", m.file === j.open && "on")} key=${m.file} onClick=${() => call("modes.jjp_open", m.file)}>
        <div class="grow"><div>${m.name}</div><div class="small muted mono">${m.start || "no start switch"}</div></div></div>`)}
      ${!modes.length ? html`<div class="small muted">No modes yet.</div>` : null}
      <div class="row wrap" style="gap:6px;margin-top:10px">
        <${Button} size="sm" kind="primary" icon="plus" disabled=${full} title=${full ? "A game takes 24 custom modes" : "A new mode, from this game's starter picks"} onClick=${() => call("modes.jjp_new", "New Mode")}>New mode<//>
        <${Button} size="sm" disabled=${!j.open || full} onClick=${() => call("modes.jjp_duplicate")}>Duplicate<//>
        <${Button} size="sm" kind="ghost" disabled=${!j.open} onClick=${() => call("modes.jjp_delete")}>Delete<//>
      </div>
      <div style="margin-top:8px"><${Button} size="xs" kind="ghost" icon="folder" title=${j.folder} onClick=${() => call("modes.jjp_reveal", "folder")}>Open the mode folder<//></div>
    </div>
  </section>`;
}

function Editor({ j, have }) {
  const f = j.form || {};
  const meta = j.fields || {};
  if (!j.open) return html`<section class="card jjpm-editor"><${Empty} icon="modes" title="No mode open">Make one with New mode.<//></section>`;
  return html`<section class="card jjpm-editor">
    <div class="hd"><span class="h2">${f.name || j.open}</span><span class="muted small mono">${j.open}</span></div>
    <div class="bd">
      ${(j.groups || []).map((g) => html`<div class="jjpm-group" key=${g.title}>
        <div class="jjpm-gt">${g.title}</div>
        ${g.keys.map((k) => html`<${Row} key=${k} k=${k} meta=${meta[k]} value=${f[k]} j=${j} have=${have} />`)}
      </div>`)}
    </div>
  </section>`;
}

function TitleSettings({ j, have }) {
  const [open, setOpen] = useState(false);
  const t = j.title_cfg || {};
  return html`<section class="card jjpm-title-card">
    <div class="hd" style="cursor:pointer" onClick=${() => setOpen(!open)}><span class="h2">${open ? "▾" : "▸"} Every mode of this game</span>
      <span class="muted small">defaults a mode's own settings override: fonts, colours, the panel${t.game ? ` - loads only into ${t.game}` : ""}</span></div>
    ${open ? html`<div class="bd">${(j.title_keys || []).map((k) => html`<${Row} key=${k} k=${k} prefix="title:" meta=${(j.fields || {})[k]} value=${t[k]} j=${j} have=${have} />`)}</div>` : null}
  </section>`;
}

function CheckCard({ j }) {
  const c = j.check || {};
  const probs = c.problems || [];
  return html`<section class=${cx("card jjpm-check", c.ok ? "ok" : "bad")}>
    <div class="hd"><span class="h2">Check</span><span class="muted small">${c.ok ? `${c.n} mode${c.n === 1 ? "" : "s"}, no problems` : `${probs.length} problem${probs.length === 1 ? "" : "s"}`}${c.when ? " - " + c.when : ""}</span>
      <span class="sp"></span><${Button} size="sm" onClick=${() => call("modes.jjp_check")}>Check again<//></div>
    ${probs.length ? html`<div class="bd"><ul class="jjpm-probs">${probs.map((p) => html`<li class="mono small">${p}</li>`)}</ul></div>` : null}
  </section>`;
}

function SoundsRow({ j }) {
  const s = j.sounds || {};
  return html`<div class="jjpm-sounds small">
    <span class="lbl">Hear sounds from</span>
    <${PathField} ns="modes" k="jjp_sounds" value=${s.folder} placeholder="this game's extract folder"
      onBrowse=${() => call("modes.jjp_sounds_browse")} onCommit=${(v) => call("modes.jjp_set_sounds", v)} />
    <span class="muted">${s.folder ? `${(s.have || []).length} of ${s.total} sounds found` : "Extract this game to hear its sounds"}</span>
  </div>`;
}

function BuildCard({ j }) {
  const b = j.build || {};
  const c = j.check || {};
  const lines = b.lines || [];
  return html`<section class="card jjpm-build">
    <div class="hd"><span class="h2">Build the install ISO</span><span class="muted small">the stock ISO again, with the mode runtime and these modes in it; install it the way the stock one installs</span></div>
    <div class="bd">
      <div class="jjpm-row"><span class="jjpm-lbl">Stock ISO</span><div class="jjpm-in"><${PathField} ns="modes" k="jjp_iso" value=${b.iso}
        placeholder=${`${(j.title || {}).label || "the game"}.iso`} onBrowse=${() => call("modes.jjp_iso_browse")} onCommit=${(v) => call("modes.jjp_set_iso", v)} disabled=${b.running} /></div></div>
      <div class="jjpm-row"><span class="jjpm-lbl">New ISO</span><div class="jjpm-in"><${PathField} ns="modes" k="jjp_out" value=${b.out}
        onBrowse=${() => call("modes.jjp_out_browse")} onCommit=${(v) => call("modes.jjp_set_out", v)} disabled=${b.running} /></div></div>
      <div class="row" style="gap:8px;margin-top:8px">
        <${Button} kind="primary" icon="disk" busy=${b.running} disabled=${b.running || !c.ok || !b.iso}
          title=${!c.ok ? "Fix what the check found first" : "Runs in the app's Linux as administrator: it opens the ISO's game partition"}
          onClick=${() => call("modes.jjp_build")}>${b.running ? "Building…" : "Build"}<//>
        ${b.running ? html`<${Button} kind="ghost" onClick=${() => call("modes.jjp_build_cancel")}>Cancel<//>` : null}
        ${b.done && b.ok ? html`<${Button} kind="ghost" onClick=${() => call("modes.jjp_reveal", "out")}>Show it<//>` : null}
        <span class=${cx("small", b.done ? (b.ok ? "ok-ink" : "warn-ink") : "muted")}>${b.msg || ""}</span>
      </div>
      ${lines.length && (b.running || (b.done && !b.ok)) ? html`<pre class="jjpm-log">${lines.join("\n")}</pre>` : null}
      <div class="small muted" style="margin-top:6px">On the machine, a file named <span class="mono">/jjpe/perm/padmodes.off</span> turns the modes off without reinstalling.</div>
    </div>
  </section>`;
}

export function JjpModes({ s }) {
  const j = s.jjp || {};
  const titles = j.titles || [];
  const have = new Set(((j.sounds || {}).have) || []);
  const opts = titles.map((t) => ({ value: t.label, label: t.name + (t.can_run ? "" : " - can't run modes"),
                                    disabled: !t.can_run, group: t.can_run ? "Can run custom modes" : "Can't run custom modes" }));
  return html`<div class="page modes-page jjpm-page">
    <div class="pagehead"><div class="grow"><h1 class="h1">Modes</h1>
      <p>Custom modes that run inside a Jersey Jack game: started by its switches, timed by its mode timer, scored by its scoring, lit with its lamps and drawn in its fonts. The game's own modes go on as they were.</p></div>
      <div class="actions"><${Select} value=${j.label} options=${opts} width=${360} onChange=${(v) => call("modes.jjp_pick_title", v)} title="The game" /></div>
    </div>
    ${!titles.length ? html`<${Empty} icon="modes" title="No games">No port reports were found in tools/jjp_emu/modes/ports.<//>` : null}
    ${j.label && !j.can_run ? html`<${Note} kind="warn">${(j.title || {}).name} can't run custom modes: ${(j.title || {}).why}.<//>` : null}
    ${j.can_run ? html`
      <${SoundsRow} j=${j} />
      <div class="jjpm-body">
        <${ModeList} j=${j} />
        <div class="jjpm-main">
          <${Editor} j=${j} have=${have} />
          <${TitleSettings} j=${j} have=${have} />
          <${CheckCard} j=${j} />
          <${BuildCard} j=${j} />
        </div>
      </div>` : null}
  </div>`;
}
