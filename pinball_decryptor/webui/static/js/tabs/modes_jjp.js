// Modes on a Jersey Jack game (PAD-1350): custom modes for the JJP mode SDK. A title's modes are
// one folder of key = value files the runtime reads inside the retail game; this page edits them
// as forms, every name (switches, lamps, lamp groups, sounds, fonts) picked from the title's port
// report, runs the build's own check after each edit, and builds the stock install ISO again
// with the modes in it - or writes a USB stick the game's own Update USB hot fix installs them
// from, no reinstall (PAD-1375).
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

function NamePick({ k, value, names, multi, sound, have, title, inherit, onSet }) {
  const [open, setOpen] = useState(false);
  const put = onSet || ((v) => set(k, v));          // a part of a longer key hands its value up (PAD-1376)
  const list = multi ? words(value) : (value ? [value] : []);
  const pick = (n) => {
    if (!multi) { put(n); setOpen(false); return; }
    const cur = words(value);
    put((cur.includes(n) ? cur.filter((x) => x !== n) : cur.concat([n])).join(" "));
  };
  const drop = (n) => put(multi ? words(value).filter((x) => x !== n).join(" ") : "");
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

// ------------------------------------------------------------------ balls and coils (PAD-1376)
// The runtime's keys of several words (MODES.md "Mode keys"), each word its own input: the coils
// picked from the title's port report (only those a mode may pulse, or hold), numbers in their
// ranges. Any part changed writes the whole line back; no first part (balls, coil, switch) clears it.
const isNum = (w) => /^\d+$/.test(w);
const line = (...parts) => parts.filter((p) => p !== "" && p != null).join(" ");

function Num({ value, placeholder, min, max, unit, width = 90, onSet, title }) {
  return html`<span class="jjpm-num" ...${title ? tip(title) : {}}><${Field} sm type="number" inputCls="num" width=${width}
    value=${value || ""} min=${min} max=${max} placeholder=${placeholder || ""} onChange=${() => {}}
    onCommit=${(v) => onSet(String(v || "").trim())} />${unit ? html`<span class="small muted">${unit}</span>` : null}</span>`;
}

function BallCoil({ k, kind, value, j }) {
  const names = j.names || {};
  const w = words(value);
  const put = (v) => set(k, v);
  if (kind === "multiball") {                      // <balls 2-6> [ball save s 0-120]
    const [balls = "", save = ""] = w;
    return html`<div class="row nw jjpm-parts">
      <${Select} sm value=${balls} onChange=${(v) => put(v ? line(v, save) : "")}
        options=${[{ value: "", label: "none" }].concat([2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `${n} balls in play` })))} />
      ${balls ? html`<span class="small muted">ball save</span>
        <${Num} value=${save} placeholder="10" min="0" max="120" unit="s" title="Drained balls are served back for this long (10 s when empty)"
          onSet=${(v) => put(line(balls, v))} />` : null}
    </div>`;
  }
  if (kind === "ball_save") {
    return html`<div class="row nw jjpm-parts"><${Num} value=${value} placeholder="none" min="1" max="120" unit="s"
      title="A ball that drains in this time after the start is served back (1-120 s)" onSet=${put} /></div>`;
  }
  if (kind === "add_ball") {                       // <switches> [times 1-6]
    const times = w.length > 1 && isNum(w[w.length - 1]) ? w[w.length - 1] : "";
    const sw = (times ? w.slice(0, -1) : w).join(" ");
    return html`<div class="row wrap jjpm-parts">
      <${NamePick} k=${k} value=${sw} names=${names.switches} multi title="The game's switches"
        onSet=${(v) => put(v ? line(v, times) : "")} />
      ${sw ? html`<span class="small muted">up to</span><${Num} value=${times} placeholder="1" min="1" max="6" width=${70} unit="times a run"
        onSet=${(v) => put(line(sw, v))} />` : null}
    </div>`;
  }
  if (kind === "coil_pulse") {                     // <coil> [ms]
    const [coil = "", ms = ""] = w;
    return html`<div class="row wrap jjpm-parts">
      <${NamePick} k=${k} value=${coil} names=${names.coil_pulse || []} title="The game's coils a mode may fire"
        onSet=${(v) => put(v ? line(v, ms) : "")} />
      ${coil ? html`<${Num} value=${ms} placeholder="own pulse" min="1" max="1000" width=${110} unit="ms"
        title="Shorter than the coil's own pulse only; empty is its own" onSet=${(v) => put(line(coil, v))} />` : null}
    </div>`;
  }
  if (kind === "coil_hold") {                      // <coil> <ms 100-5000> [power 1-16 of 32]
    const [coil = "", ms = "", power = ""] = w;
    const off = (j.title_cfg || {}).coil_holds !== "on";
    return html`<div class="jjpm-parts">
      <div class="row wrap" style="gap:8px">
        <${NamePick} k=${k} value=${coil} names=${names.coil_hold || []}
          title="The game's coils built to stay on: magnets, diverters, posts, gates, the shaker, lights"
          onSet=${(v) => put(v ? line(v, ms || "1000", power) : "")} />
        ${coil ? html`<span class="small muted">for</span>
          <${Num} value=${ms} min="100" max="5000" width=${90} unit="ms" title="100-5000 ms"
            onSet=${(v) => put(line(coil, v || "1000", power))} />
          <span class="small muted">at</span>
          <${Select} sm value=${power} onChange=${(v) => put(line(coil, ms || "1000", v))}
            options=${[{ value: "", label: "8 of 32 (default)" }].concat(Array.from({ length: 16 }, (_, i) => ({ value: String(i + 1), label: `${i + 1} of 32` })))} />
          <span class="small muted">power</span>` : null}
      </div>
      ${coil && off ? html`<div class="small warn-ink">Off on this game until Every mode of this game sets Coil holds on this title to on (after watching it on the machine).</div>` : null}
    </div>`;
  }
  if (kind === "hold_on") return html`<${HoldOn} k=${k} value=${value} names=${names} />`;
  return null;
}
// coil_hold_on: shots | start | switches; "switches of its own" stays picked while none is chosen yet
function HoldOn({ k, value, names }) {
  const [pickSw, setPickSw] = useState(false);
  const how = !value ? (pickSw ? "switches" : "") : (value === "shots" || value === "start" ? value : "switches");
  const choose = (v) => {
    setPickSw(v === "switches");
    if (v !== "switches") set(k, v);
    else if (how !== "switches") set(k, "");
  };
  return html`<div class="row wrap jjpm-parts">
    <${Select} sm value=${how} onChange=${choose}
      options=${[{ value: "", label: "(default: each scoring shot)" }, { value: "shots", label: "each scoring shot" },
                 { value: "start", label: "the mode's start" }, { value: "switches", label: "switches of its own" }]} />
    ${how === "switches" ? html`<${NamePick} k=${k} value=${value} names=${names.switches} multi title="The game's switches" />` : null}
  </div>`;
}
const BALL_COIL = new Set(["multiball", "ball_save", "add_ball", "coil_pulse", "coil_hold", "hold_on"]);

// one key of a mode (or of title.cfg: prefix "title:")
function Row({ k, prefix = "", meta, value, j, have }) {
  // an empty key of a mode takes Every mode of this game's value, else the runtime's default
  const inherit = prefix ? "" : ((j.title_cfg || {})[k] || "");
  const m = meta || {};
  const key = prefix + k;
  const names = j.names || {};
  let input;
  if (BALL_COIL.has(m.kind)) input = html`<${BallCoil} k=${key} kind=${m.kind} value=${value} j=${j} />`;
  else if (m.kind === "switches") input = html`<${NamePick} k=${key} value=${value} names=${names.switches} multi title="The game's switches" />`;
  else if (m.kind === "lamps") input = html`<${NamePick} k=${key} value=${value} names=${names.lamps} multi title="The game's lamps (lp_) and lamp groups (ls_)" />`;
  else if (m.kind === "events") input = html`<${NamePick} k=${key} value=${value} names=${names.events || []} multi title="The game's own events (its hook lists)" />`;
  else if (m.kind === "after") input = html`<${NamePick} k=${key} value=${value} names=${names.after || []} multi title="The game's own modes (a global or a class), or any" />`;
  else if (m.kind === "sound") input = html`<${NamePick} k=${key} value=${value} names=${names.sound} sound have=${have} title="The game's sounds" inherit=${inherit} />`;
  else if (m.kind === "sound_or_file") input = html`<${NamePick} k=${key} value=${value} names=${names.sound_or_file} sound have=${have} title="The game's sounds, or a sound file of yours in this game's mode folder" inherit=${inherit} />`;
  else if (m.kind === "sound_file" || m.kind === "picture_file" || m.kind === "video_file") input = html`<${NamePick} k=${key} value=${value} names=${names[m.kind] || []} title="A file of yours in this game's mode folder (Open the mode folder, put it there, then pick it)" inherit=${inherit} />`;
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
      <span class="muted small">defaults a mode's own settings override: fonts, colors, the panel${t.game ? ` - loads only into ${t.game}` : ""}</span></div>
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
        <${Button} kind="primary" icon="disk" busy=${b.running} disabled=${b.busy || !c.ok || !b.iso}
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

const STICK_TIP = {
  install: "Copies these modes and the mode runtime to the stick, for the game's Update USB hot fix to install",
  off: "A stick that turns the custom modes off (they stay installed)",
  on: "A stick that turns the custom modes back on",
  remove: "A stick that takes the custom modes out and puts the game's start script back as shipped",
};

function StickCard({ j }) {
  const k = j.stick || {};
  const c = j.check || {};
  const lines = k.lines || [];
  const install = k.action === "install";
  const fsBad = k.fs && !/^FAT/i.test(k.fs);
  const why = !k.path ? "Put in a USB stick, or pick a folder to copy to one"
    : k.owner === "other" ? "This stick already has another hot fix on it"
    : install && !c.ok ? "Fix what the check found first"
    : install && !k.iso ? "Pick the stock ISO under Build first: the mode runtime is built against its system"
    : "";
  const busy = k.busy;
  const note = install && k.iso && !k.runtime_ready
    ? "The first stick for this ISO builds the mode runtime in the app's Linux as administrator: seconds, or about 20 minutes if this ISO's game partition has not been unpacked before (once per ISO)."
    : "";
  return html`<section class="card jjpm-stick">
    <div class="hd"><span class="h2">Write to USB stick</span><span class="muted small">no reinstall: the game's own Update USB hot fix installs the modes, scores and settings kept</span></div>
    <div class="bd">
      <div class="jjpm-row"><span class="jjpm-lbl">USB stick</span><div class="jjpm-in"><${PathField} ns="modes" k="jjp_stick" value=${k.path}
        history=${k.drives || []} placeholder="Put in a USB stick (FAT32)" browseLabel="Pick…"
        onBrowse=${() => call("modes.jjp_stick_browse")} onCommit=${(v) => call("modes.jjp_set_stick", v)} disabled=${busy} /></div></div>
      <div class="jjpm-row"><span class="jjpm-lbl">The stick</span><div class="jjpm-in row" style="gap:8px">
        <${Select} value=${k.action} options=${k.actions || []} width=${240} disabled=${busy}
          title=${STICK_TIP[k.action] || ""} onChange=${(v) => call("modes.jjp_stick_action", v)} />
        <${Button} kind="ghost" size="sm" icon="refresh" disabled=${busy} title="Look for USB sticks again"
          onClick=${() => call("modes.jjp_stick_refresh")}>Find sticks<//>
      </div></div>
      ${fsBad ? html`<${Note} kind="warn">This stick is ${k.fs}. The machine reads FAT32 sticks: format it FAT32 first.<//>` : null}
      ${k.owner === "other" ? html`<${Note} kind="warn">This stick already has a hotfix folder that is not a modes stick. Use another stick, or delete that folder first.<//>` : null}
      <div class="row" style="gap:8px;margin-top:8px">
        <${Button} kind="primary" icon="download" busy=${k.running} disabled=${busy || !!why}
          title=${why || (k.owner === "pad" ? "Replaces the modes stick already on it" : "Writes a hotfix folder to the top of the stick")}
          onClick=${() => call("modes.jjp_write_stick")}>${k.running ? "Writing…" : "Write to USB stick"}<//>
        ${k.running && !k.runtime_ready ? html`<${Button} kind="ghost" onClick=${() => call("modes.jjp_stick_cancel")}>Cancel<//>` : null}
        ${k.done && k.ok ? html`<${Button} kind="ghost" onClick=${() => call("modes.jjp_reveal_stick")}>Show it<//>` : null}
        <span class=${cx("small", k.done ? (k.ok ? "ok-ink" : "warn-ink") : "muted")}>${k.msg || note}</span>
      </div>
      ${lines.length && (k.running || (k.done && !k.ok)) ? html`<pre class="jjpm-log">${lines.join("\n")}</pre>` : null}
      <div class=${cx("jjpm-steps", k.done && k.ok && "jjpm-steps-now")}>
        <div class="small jjpm-steps-hd">At the machine</div>
        <ol>${(k.steps || []).map((st) => html`<li>${st}</li>`)}</ol>
      </div>
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
          <${StickCard} j=${j} />
          <${BuildCard} j=${j} />
        </div>
      </div>` : null}
  </div>`;
}
