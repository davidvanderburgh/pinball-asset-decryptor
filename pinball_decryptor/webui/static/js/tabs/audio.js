// Replace Audio: the slot list, the Original / Replacement preview panes and
// every per-slot action of the Tk tab.  Python (webui/tabs/audio.py) decides
// everything; this page renders it and plays sound with two <audio> players
// (Python says what to play with "audio_play" / "audio_stop" events, and hears
// back when a clip ends on its own, for "Play sequentially").

import { html, useEffect, useMemo, useRef, useState, Button, Field, Select, Seg, Check, Card, Chip,
  Note, Table, Modal, openMenu, tip, Icon, PageHead, Spinner, mediaUrl, call, cx } from "../core/ui.js";
import { useNs, useEvent, state } from "../core/store.js";

export const css = true;

// ------------------------------------------------------------------ words
// (the Tk tab's tooltips, unchanged)
const T = {
  intro: "Assign a replacement track to any slot — almost any audio format is accepted and auto-converted — then build the update on the Write tab.",
  folder: "The project folder — shared by every tab. It is set on the Extract tab. Click to open it.",
  fromFolder: "Pick a folder of your own files and each one becomes the replacement for the slot with the same name — for a whole set you reworked outside the app, like every clip made black and white. The file type and capital letters don't have to match (Intro.mp4 is used for Intro.mov and converted to suit it), and subfolders are fine. Nothing changes until you confirm, and every file left out is named in the log.\n\nKeep the extract's own files where they are: files dropped into the project folder only count under the card's exact name.",
  clear: "Drop every replacement picked on this tab in one go — for starting a project over without clearing 48 rows one at a time. It only drops the picks: your own files are untouched, and a slot already built into the project folder keeps the bytes it has (use “Revert all changes…” on the Write tab for those). To clear only some, select the rows — click, then Shift-click or Ctrl-click — and right-click the selection.",
  csv: "Save the whole audio table (every slot, not just the filtered view) as a CSV — name, length, format, type, replacement and changed-on-disk status — for tracking a big replacement project in a spreadsheet.",
  type: "Show only one kind of audio — every row matches the Type column, so a filtered list only ever holds that Type. Music = the game's song/bank tracks. Sound FX = effects named by the game's own Sound Test menu. Callouts = spoken lines found by Auto-name call-outs. Other = the rest — short unnamed effects. On a game that identifies no music at all (some pins store their songs as Sound-Test-named sequences), anything 20 seconds or longer counts as Music instead, and the Type column says so.",
  dups: "Group the slots that carry byte-identical factory audio under one row, so every copy of a sound sits together. The first tick scans the sound banks (about ten seconds). The game may play any copy of a duplicated sound, so mod them together — assign a replacement to one copy, then right-click it and choose \"Apply to all copies\".",
  show: "Narrow the list by what you've already done to it. Changed = the slots with a pending replacement or already changed on disk by a previous build. Unchanged = everything you haven't touched yet, so a part-finished pass is what's left in front of you instead of something to scroll past.",
  seq: "When a clip finishes, select and play the next row in the list, following whatever sort, search and Type filter are showing.\n\nStops at the end of the list, and any ■ (or clicking another row) stops it.",
  subst: "While playing sequentially, a row that has a replacement (picked now, or already changed on disk) plays the replacement instead of the original — the whole list sounds the way the built card will.\n\nSo anything that still sounds stock is a clip you haven't replaced yet.\n\nIt applies to the ▶ buttons too: with this ticked, pressing ▶ under Original on a row you have replaced plays your replacement, so what you hear is always what the card will play.\n\nTicking this turns on \"Play sequentially\" as well.",
  adv: "Fine-tune how replacements are encoded: experimental head/tail block handling and the anti-pop codec seed — plus machine-render preview WAVs on Build.\n\nThese are levers for chasing clicks heard on the real machine. Defaults match the standard behavior.\n\nA * on the button means at least one option is currently OFF its default (they persist between sessions) — open the dialog to see which, or to set everything back.",
  profile: "Characterize every sound in the scanned extract folder — lead-in, fade-out, peak/RMS level, DC offset, spectral brightness — and flag replacements that deviate from the game's own callout style. Writes audio_profile.csv into the extract folder.",
  loop: "Loop this replacement in-game.\n\nThese music stems normally play once — there's no built-in loop — so a replacement that's shorter than the original goes silent partway through its mode. Ticking Loop bakes a forward-loop flag into the rebuilt audio (the same loop_mode flag Godot's importer would set), so the engine repeats your clip to fill the mode; the game stops or fades it on the next song change.\n\nDefaults ON for tracks with \"LOOP\" in the name (the mode music). Leave it OFF for one-shot sound effects and callouts.",
  keep: "Keep this replacement's full length.\n\nBy default every track is trimmed (or padded) to its original slot length on Write. Tick Full to skip that for this one slot, so a longer replacement plays at its full length.\n\nThe file validates and boots at any length (the game's checksums are re-forged regardless of size). Whether it actually plays to the end is up to the game: best for a cue nothing plays over — e.g. the end-of-game track before attract — since the show may still cut it short. Test on the machine.",
  level: "How loud THIS replacement lands, in dB.\n\nEvery replacement is normally gained to the loudness of the sound it replaces, so it sits with its neighbours instead of jumping out — and that ignores the level you mixed your own file at, so exporting the same track louder changes nothing. This is the way to overrule it for one clip.\n\nIt stacks on the build-wide \"Replacement loudness\" offset in Advanced Audio Options: that one moves every replacement together, this one moves this clip relative to the rest. 0 dB = whatever the rest of the build does.\n\nHandy for music, which Stern mixes as a bed under the callouts. Boosts are soft-limited, never hard-clipped, and the build log lists every clip you levelled by hand.\n\nThe Replacement preview redraws and plays at this offset, so you can see and hear it. What the preview can't show is the automatic match to the stock sound's own level: that happens inside the encoder, against audio only the machine's own decoder can produce.",
  levelAll: "Give every row the list is currently showing this same offset — the search box, the Type filter and Show: Changed/Unchanged all narrow what \"shown\" means.\n\nSo: set Type to Music, type this box to +4, and every song sits 4 dB above stock while the callouts stay where they are.\n\nSetting it back to 0 the same way clears them.",
};
const TYPES = ["All types", "Music", "Sound FX", "Callouts", "Other"];
const SHOWS = ["All", "Changed", "Unchanged"];

// ---------------------------------------------------------------- players
// One <audio> per pane, kept outside Preact so a play command can act on it
// the moment it arrives.
let actx = null;
const players = {};
function player(side) {
  if (!players[side]) {
    players[side] = { side, el: null, path: null, v: -1, playing: false, limit: null, gainDb: 0,
      node: null, raf: 0, subs: new Set(), tried: false, want: false, pendingPos: null, last: 0 };
  }
  return players[side];
}
function notify(p) { for (const fn of [...p.subs]) fn(); }
function elOf(p) {
  if (p.el) return p.el;
  const a = new Audio();
  a.preload = "metadata";
  a.addEventListener("ended", () => finished(p));
  a.addEventListener("error", () => onError(p));
  a.addEventListener("loadedmetadata", () => {
    if (p.pendingPos != null) { try { a.currentTime = p.pendingPos; } catch (e) { /* not seekable yet */ } p.pendingPos = null; }
    notify(p);
  });
  p.el = a;
  return a;
}
function syncPlayer(side, pane) {
  const p = player(side);
  if (!pane) return p;
  p.limit = pane.limit ?? null;
  if (p.gainDb !== (pane.gain || 0)) { p.gainDb = pane.gain || 0; if (p.el) applyGain(p); }
  if (p.v === pane.v) return p;
  p.v = pane.v;
  stopPlayer(p);
  p.path = pane.path || null;
  p.tried = false;
  p.pendingPos = null;
  const a = elOf(p);
  if (p.path) { a.src = mediaUrl(p.path); a.load(); } else { a.removeAttribute("src"); try { a.load(); } catch (e) { /* empty */ } }
  notify(p);
  return p;
}
function applyGain(p) {
  const a = elOf(p);
  const db = Number(p.gainDb) || 0;
  if (db > 0 && !p.node) {
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      const src = actx.createMediaElementSource(a);
      const g = actx.createGain();
      src.connect(g); g.connect(actx.destination);
      p.node = g;
    } catch (e) { p.node = null; }
  }
  const lin = Math.pow(10, db / 20);
  if (p.node) { p.node.gain.value = lin; a.volume = 1; } else { a.volume = Math.max(0, Math.min(1, lin)); }
}
function seekTo(p, pos) {
  const a = elOf(p);
  if (a.readyState >= 1) { try { a.currentTime = pos; } catch (e) { p.pendingPos = pos; } } else p.pendingPos = pos;
  notify(p);
}
function stopPlayer(p) {
  p.want = false;
  if (p.raf) { cancelAnimationFrame(p.raf); p.raf = 0; }
  if (p.el && !p.el.paused) p.el.pause();
  if (p.playing) { p.playing = false; notify(p); }
}
function stopAll() { for (const k of Object.keys(players)) stopPlayer(players[k]); }
function playingSide() {
  if (players.orig && players.orig.playing) return "orig";
  if (players.rep && players.rep.playing) return "rep";
  return null;
}
async function startPlayer(p, pos) {
  for (const k of Object.keys(players)) if (players[k] !== p) stopPlayer(players[k]);   // never over the sibling
  const a = elOf(p);
  if (!p.path) return;
  const dur = isFinite(a.duration) ? a.duration : 0;
  if (pos != null) seekTo(p, pos);
  else {
    const stopAt = p.limit != null ? p.limit : dur;
    if (stopAt > 0 && a.currentTime >= stopAt - 0.05) seekTo(p, 0);
  }
  applyGain(p);
  if (actx && actx.state === "suspended") actx.resume().catch(() => {});
  p.want = true;
  try {
    await a.play();
    if (!p.want) { a.pause(); return; }
    p.playing = true;
    tick(p);
  } catch (e) {
    p.playing = false;   // an unreadable file also raises "error" (see onError)
  }
  notify(p);
}
function tick(p) {
  if (p.raf) cancelAnimationFrame(p.raf);
  const step = (t) => {
    p.raf = 0;
    if (!p.playing || !p.el) return;
    if (p.limit != null && p.el.currentTime >= p.limit) {   // the trim point: what the machine plays
      p.el.pause();
      finished(p);
      return;
    }
    if (t - p.last > 50) { p.last = t; notify(p); }
    p.raf = requestAnimationFrame(step);
  };
  p.raf = requestAnimationFrame(step);
}
function finished(p) {
  if (p.raf) { cancelAnimationFrame(p.raf); p.raf = 0; }
  const was = p.playing;
  p.playing = false; p.want = false;
  try { p.el.currentTime = 0; } catch (e) { /* ignore */ }
  notify(p);
  if (was) call("audio.clip_finished", p.side, p.path);
}
async function onError(p) {
  const path = p.path;
  if (!path) return;
  if (p.tried) {
    if (p.want) { stopPlayer(p); call("audio.cant_preview", path); }
    return;
  }
  p.tried = true;
  const alt = await call("audio.playable", path);
  if (p.path !== path) return;
  if (alt) {
    const a = elOf(p);
    a.src = mediaUrl(alt); a.load();
    if (p.want) startPlayer(p, 0);
  } else if (p.want) {
    stopPlayer(p);
    call("audio.cant_preview", path);
  }
}
function usePlayer(side) {
  const [, force] = useState(0);
  useEffect(() => {
    const p = player(side);
    const fn = () => force((n) => n + 1);
    p.subs.add(fn);
    return () => p.subs.delete(fn);
  }, [side]);
  return player(side);
}

// ---------------------------------------------------------------- helpers
const clock = (s) => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
const byIndex = (list, index) => [...list].sort((a, b) => (index.get(a) ?? 1e9) - (index.get(b) ?? 1e9));

// The Tk tree's keyboard (ttk::treeview::Keynav): the arrows move from the
// FOCUS row (the cursor: the row last clicked, Ctrl-clicked, Shift-clicked or
// arrowed to), never from "the selection", so Down after Ctrl-clicking rows 3
// and 6 lands on 7.  Up/Down select only the new row; Right opens a closed
// duplicate group, Left closes an open one or steps from a copy up to its
// group row, and each then selects the focus row, as Tk did.  Shift+Up/Down
// extends from the anchor to the new row (Tk 8.6 had no Shift binding, so
// there it moved like a plain arrow).  Nothing above the top or below the
// bottom.  -> {cursor, anchor, sel, toggle?} or null (nothing to do).
export function keyNav(rows, index, cur, key, shift) {
  const n = rows ? rows.length : 0;
  if (!n) return null;
  let idx = cur.cursor != null && index.has(cur.cursor) ? index.get(cur.cursor) : -1;
  if (idx < 0) {
    for (const k of cur.sel || []) if (index.has(k) && (idx < 0 || index.get(k) < idx)) idx = index.get(k);
  }
  const r = idx >= 0 ? rows[idx] : null;
  const only = (x, extra) => ({ cursor: x.k, anchor: x.k, sel: [x.k], ...extra });
  if (key === "ArrowRight") {
    if (!r) return null;
    return only(r, r.g && !r.open ? { toggle: r.k } : {});
  }
  if (key === "ArrowLeft") {
    if (!r) return null;
    if (r.g) return r.open ? only(r, { toggle: r.k }) : null;
    if (r.d) {
      for (let j = idx - 1; j >= 0; j--) if (rows[j].g) return only(rows[j]);
    }
    return null;
  }
  if (key !== "ArrowDown" && key !== "ArrowUp") return null;
  let next;
  if (idx < 0) next = 0;
  else if (key === "ArrowDown") { if (idx >= n - 1) return null; next = idx + 1; }
  else { if (idx <= 0) return null; next = idx - 1; }
  const nr = rows[next];
  if (shift) {
    const a = cur.anchor != null && index.has(cur.anchor) ? index.get(cur.anchor) : (idx >= 0 ? idx : next);
    const lo = Math.min(a, next), hi = Math.max(a, next);
    const range = rows.slice(lo, hi + 1).filter((x) => !x.g).map((x) => x.k);
    if (range.length) return { cursor: nr.k, anchor: rows[a].k, sel: range };
  }
  return only(nr);
}

function NameCell({ r, prefix }) {
  if (r.g) return html`<span class="aud-name aud-glabel">${r.label}</span>`;
  let rel = r.k;
  if (prefix && rel.startsWith(prefix)) rel = rel.slice(prefix.length);
  const slash = rel.lastIndexOf("/");
  const dir = slash >= 0 ? rel.slice(0, slash + 1) : "";
  const base = rel.slice(slash + 1);
  const m = base.match(/^((?:\d+m\d+s\d+ - )?(?:idx\d+|music_cat\d+_\d+)) - (.+)$/);
  return html`<span class=${cx("aud-name", r.d && "aud-child")}>${dir ? html`<span class="muted">${dir}</span>` : null}${m
    ? html`<span class="mono muted">${m[1]}</span> ${m[2]}` : html`<span class=${/^(idx\d+|music_cat)/.test(base) ? "mono" : ""}>${base}</span>`}</span>`;
}

// ------------------------------------------------------------------ panes
function Pane({ side, pane, actions, extra, onPlay }) {
  const p = usePlayer(side);
  const strip = useRef(null);
  const a = p.el;
  const dur = (pane && pane.dur) || (a && isFinite(a.duration) ? a.duration : 0);
  const pos = a && p.path ? a.currentTime : 0;
  const loaded = !!(pane && pane.path);
  const lim = loaded ? pane.limit : null;
  const grow = loaded && lim == null ? pane.grow_from : null;
  let time = "0:00 / 0:00";
  if (loaded && dur > 0) {
    if (lim != null) time = `${clock(Math.min(pos, lim))} / ${clock(lim)}  (trimmed from ${clock(dur)})`;
    else if (grow) time = `${clock(pos)} / ${clock(dur)}  (original ${clock(grow)}; the sound bank grows)`;
    else time = `${clock(pos)} / ${clock(dur)}`;
  }
  const seek = (e) => {
    if (!loaded || dur <= 0 || e.button !== 0) return;
    e.preventDefault();
    const at = (ev) => {
      const r = strip.current.getBoundingClientRect();
      const frac = Math.max(0, Math.min(1, (ev.clientX - r.left) / Math.max(1, r.width)));
      let t = frac * dur;
      if (lim != null) t = Math.min(t, Math.max(0, lim - 0.05));   // nothing to hear in the trimmed tail
      syncPlayer(side, pane);
      seekTo(p, t);
    };
    at(e);
    const move = (ev) => at(ev);
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  const pct = (t) => `${Math.max(0, Math.min(100, (t / dur) * 100))}%`;
  const hint = !loaded ? (pane ? pane.hint : "")
    : pane.spec_state === "rendering" ? "rendering preview…" : pane.spec ? "" : "(preview needs ffmpeg)";
  return html`<div class="aud-pane">
    <div class="row aud-pane-hd">
      <span class="eyebrow nw">${pane ? pane.base : ""}</span>
      ${loaded ? html`<span class=${cx("mono small ellip", side === "rep" ? "acc-ink" : "muted")} title=${pane.path}>— ${pane.name}</span>` : null}
      <span class="grow"></span>
      ${actions}
    </div>
    <div ref=${strip} class=${cx("aud-strip", loaded && "live", !loaded && hint && hint.length > 60 && "tall")} onMouseDown=${seek}
      role=${loaded ? "slider" : undefined} aria-label=${loaded ? "Seek" : undefined}
      aria-valuemin="0" aria-valuemax=${Math.round(dur)} aria-valuenow=${Math.round(pos)}>
      ${loaded && pane.spec ? html`<img src=${mediaUrl(pane.spec)} alt="" draggable="false" />` : null}
      ${hint ? html`<span class="aud-hint">${hint}</span>` : null}
      ${loaded && dur > 0 && lim != null ? html`<i class="aud-cut" style=${`left:${pct(lim)}`}><b>trimmed</b></i>` : null}
      ${loaded && dur > 0 && grow && grow < dur ? html`<i class="aud-grow" style=${`left:${pct(grow)}`}><b>original ended; bank grows</b></i>` : null}
      ${loaded && pane.gain ? html`<b class="aud-gain">${(pane.gain > 0 ? "+" : "") + Math.round(pane.gain)} dB</b>` : null}
      ${loaded && dur > 0 ? html`<i class="aud-head" style=${`left:${pct(pos)}`}></i>` : null}
    </div>
    <div class="row aud-transport">
      <${Button} size="sm" icon=${p.playing ? "pause" : "play"} label=${p.playing ? "Pause" : "Play"}
        onClick=${() => { if (p.playing) stopPlayer(p); else onPlay(side); }}>${p.playing ? "Pause" : "Play"}<//>
      <${Button} size="sm" kind="ghost" icon="stop" label="Stop" onClick=${() => {
        stopAll(); seekTo(p, 0); call("audio.stop"); }} />
      <span class="mono small muted nw aud-clock">${time}</span>
      ${extra ? html`<span class="grow"></span>${extra}` : null}
    </div>
  </div>`;
}

function Loudness({ s, selRel }) {
  const [val, setVal] = useState(s.level ?? "0");
  const focused = useRef(false);
  const timer = useRef(0);
  useEffect(() => { if (!focused.current) setVal(s.level ?? "0"); }, [s.level, selRel]);
  const send = (v, rel) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { if (rel) call("audio.set_level", rel, v); }, 200);
  };
  return html`<span class="row aud-loud" style="gap:8px">
    <label class="lbl nw" for="aud-db" ...${tip(T.level)}>Loudness for this clip:</label>
    <span class=${cx("field sm aud-db", !s.level_enabled && "disabled")} ...${tip(T.level)}>
      <input id="aud-db" type="number" min="-12" max="12" step="1" value=${val} disabled=${!s.level_enabled}
        aria-label="Loudness in dB"
        onFocus=${() => { focused.current = true; }} onBlur=${() => { focused.current = false; }}
        onInput=${(e) => { setVal(e.target.value); send(e.target.value, selRel); }} />
      <span class="muted">dB</span>
    </span>
    <${Button} size="sm" kind="ghost" disabled=${!s.level_enabled} title=${T.levelAll}
      onClick=${() => call("audio.level_apply_all", val)}>Apply to all shown<//>
  </span>`;
}

// ---------------------------------------------------------------- dialogs
function PropsModal({ data, onClose }) {
  const [name, setName] = useState(data.label || "");
  const [cat, setCat] = useState(data.category || "other");
  const ok = () => { onClose(); call("audio.rename", data.rel, name, cat); };
  return html`<${Modal} title="Audio Properties" icon="edit" onClose=${onClose}
    footer=${html`<${Button} kind="danger" onClick=${onClose}>Cancel<//><${Button} kind="primary" onClick=${ok}>OK<//>`}>
    <div onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); ok(); } }} class="stack" style="gap:10px">
      <div class="msg">${data.prompt}</div>
      ${data.suggestions && data.suggestions.length ? html`<div class="small muted" style="font-style:italic">Pick one of the game's own Sound Test names, or type anything:</div>` : null}
      <${Field} value=${name} onChange=${setName} list="aud-sugg" autoFocus />
      <datalist id="aud-sugg">${(data.suggestions || []).map((x) => html`<option value=${x} />`)}</datalist>
      <div class="row wrap">
        <span class="lbl">Type:</span>
        <${Select} value=${cat} options=${data.cats} onChange=${setCat} width=${150} />
        <span class="small muted" style="font-style:italic">(the Type is remembered with the name)</span>
      </div>
    </div>
  <//>`;
}

function AdvancedModal({ data, onClose }) {
  const [cfg, setCfg] = useState({ ...data.cfg });
  const put = (k) => (v) => setCfg((c) => ({ ...c, [k]: v }));
  const ok = () => { onClose(); call("audio.advanced_set", cfg); };
  const defaults = () => setCfg((c) => ({ ...c, head_mode: "encode", leadout: "silence", previews: false,
    experiment_idxs: "", slot_seed: false, slot_seed_db: 65, blip_free_optin: false, loudness: "match", loudness_db: 0 }));
  const num = (k, lo, hi, step) => html`<span class="field sm aud-num"><input type="number" min=${lo} max=${hi} step=${step}
    value=${cfg[k]} onInput=${(e) => put(k)(e.target.value)} /></span>`;
  return html`<${Modal} title="Advanced Audio Options" icon="gear" wide onClose=${onClose}
    footer=${html`<${Button} onClick=${defaults}>Restore defaults<//><span class="grow"></span>
      <${Button} onClick=${onClose}>Cancel<//><${Button} kind="primary" onClick=${ok}>OK<//>`}>
    <div class="stack aud-adv" style="gap:10px" onKeyDown=${(e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); ok(); } }}>
      <p class="aud-p">How Stern Spike 2 audio replacements are encoded. The loudness setting below is an everyday one; the rest are experiment levers. Defaults match the standard behavior; change one thing at a time when chasing a click on the real machine.</p>
      <hr />
      <div class="row wrap"><span class="lbl nw">Replacement loudness:</span>
        <${Select} value=${cfg.loudness} options=${data.loudness} onChange=${put("loudness")} width=${340} />
        <span class="lbl">then</span>${num("loudness_db", -12, 12, 1)}<span class="lbl">dB</span></div>
      <p class="aud-expl">This row is the setting for the WHOLE build: it moves every replacement together. For one clip on its own, use the "Loudness for this clip" box beside the Replacement preview on the Audio tab (its dB stacks on top of this one).
By default every replacement is gained to the same loudness as the sound it replaces, so it sits with its neighbours instead of jumping out. That match ignores the level you mixed your own file at: exporting the same track louder and rebuilding produces exactly the same card. Use the dB box to sit deliberately above or below stock — handy for music, which Stern mixes as a bed under the callouts. "Normalize to full scale" ignores the stock level instead and pushes each replacement as loud as the codec will carry. Boosts are soft-limited, never hard-clipped. The build log records whichever setting built the card.</p>
      <hr />
      <div class="kv aud-kv">
        <span class="k">Head block (first 4.5 ms):</span><${Select} value=${cfg.head_mode} options=${data.head} onChange=${put("head_mode")} />
        <span class="k">Tail block (last 4.5 ms):</span><${Select} value=${cfg.leadout} options=${data.leadout} onChange=${put("leadout")} />
        <span class="k">Only these idx numbers:</span>
        <div class="row wrap"><${Field} sm value=${cfg.experiment_idxs} onChange=${put("experiment_idxs")} width=${180} />
          <span class="small muted" style="font-style:italic">head/tail modes only, e.g. 231, 258 — blank = all; lets one card carry treated slots and untouched controls</span></div>
      </div>
      <hr />
      <div class="row wrap"><${Check} checked=${cfg.slot_seed} onChange=${put("slot_seed")} label="Anti-pop codec seed for silent / quiet callouts" />
        <span class="lbl">level -</span>${num("slot_seed_db", 40, 90, 5)}<span class="lbl">dBFS</span></div>
      <p class="aud-expl">Mixes an inaudible low tone (default -65 dBFS) into replacements so a callout is never completely silent. On some machines a silent or very quiet replacement clicks at the start while audible ones and the stock callouts do not — the machine's audio output adds that pop on dead silence (the decoded audio itself is correct). Keeping a whisper-level signal present is meant to stop that. Turn on if silent or quiet replacements click at the start; combine with the 'only these idx numbers' box above to seed some slots and leave others as an on-card A/B. Experimental, hardware-unverified.</p>
      <hr />
      <${Check} wrap checked=${cfg.blip_free_optin} onChange=${put("blip_free_optin")} label="Blip-free callouts: patch the game firmware so a replaced sound plays your audio for its whole length (image builds only)" />
      <p class="aud-expl">What it does, technically. At boot the game reads two ~512-byte windows out of every sound's body to work out that sound's decoder settings, and each result feeds the next, so the whole sound bank is one forward chain. Re-encoding a sound changes those bytes and desyncs the chain, which makes the machine reboot the moment any audio plays. The safe fallback is to put the original bytes back in just those two windows — but they sit inside the audible part, so you hear a ~6 ms scrap of the ORIGINAL sound twice inside every replacement (the "blip"). Instead of that, this stashes a copy of the original window bytes inside the firmware and adds a small piece of ARM code that points the boot-time read at the copy, for the replaced sounds only. The chain then sees exactly what it saw on a stock card while the card itself carries your audio end to end. The added code needs somewhere to live: it is appended to the game binary and given a memory mapping of its own, at an address no part of the game claims. (Before v0.94.0 it was tucked into a run of zero bytes inside the game's own data instead, which on some titles turned out to be memory the game was using — on Elvira, the node board table — and those cards booted slowly and threw node board errors.) Because the binary gets longer, this needs the Linux filesystem driver, the same as full-size video replacement, and it is skipped for a direct-SD write. Every build re-derives all the sounds' settings from the patched firmware first and falls back to the plain stock-byte restore if anything would drift. Why it is opt-in. This has been confirmed working on real machines, so it is safe to use; it is left as a choice because it needs an image build (with the Linux filesystem driver) rather than a direct-SD write, and it rebuilds the game binary. Leaving it off costs you a ~6 ms scrap of the original sound at two points inside each replacement, which at least one tester listening for it could not hear. As with any image build, keep your original image so you can rebuild the card if you want to.</p>
      <hr />
      <${Check} wrap checked=${cfg.audio_grow} onChange=${put("audio_grow")} label="Allow replacements longer than the original (grows the sound bank; image builds only)" />
      <p class="aud-expl">What it does. A replacement that runs longer than the sound it replaces is trimmed to fit, because the card's sound bank records where every sound starts and how long it is, and making one longer in place would strand every sound after it. Ticking this appends instead: your audio goes into new space at the end of the bank, and a copy of that sound's record is added pointing at it. Nothing that already exists moves, so every other sound on the card is untouched, and the game's play tables are re-pointed at the copy so it is the one that plays. The file gets bigger, so this needs the Linux filesystem driver, the same as full-size video replacement, and it is skipped for a direct-SD write. Why it is opt-in. This has been confirmed on a real machine (longer cues play, do not loop, and cut off correctly), so it is safe to use; it is left as a choice because it needs an image build. There are two limits. The game can only open a sound bank up to about 2 GB, and every lengthened sound is added on top of the original bank at its whole length, not just the extra (on Godzilla 1.16 that is room for about 45 minutes of lengthened stereo sound). Anything over that is trimmed and named in the log. The lengthened sounds also need room on the card's games partition, which they share with full-size replacement videos, and a stock 8 GB card can have only a few hundred MB free. SD card size on the Write tab gives the games partition more room, but it does not raise the 2 GB limit. Leaving this off trims longer clips exactly as before.</p>
      <hr />
      <${Check} wrap checked=${cfg.previews} onChange=${put("previews")} label="On Build, export machine-render WAVs of every changed sound (hear exactly what the card will play)" />
      <p class="aud-expl">Previews land in a ${"<build name>"}_machine_previews folder next to the built image. Note: they show what our decoder renders — an artifact the real machine adds on its own cannot appear in a preview.</p>
    </div>
  <//>`;
}

// -------------------------------------------------------------------- tab
// Default column widths (px) until the user drags one; the dragged ones are
// the Tk tree's own (settings.json column_widths.audio, shared with Tk).
const FIXED = { play: 30, len: 96, fmt: 184, type: 92, loop: 58, keep: 58, lvl: 76 };
const ROW_H = 32;
const MIN_W = { "#0": 80, rep: 110 };    // the Tk columns' minwidth
// A control inside a row: its second click of a double-click does nothing
// (one picker, one play, one toggle), and the double-click never reaches the
// row, whose double-click opens the replacement picker.
const once = (fn) => (e) => { e.stopPropagation(); if (e.detail > 1) return; fn(e); };
const noDbl = (e) => e.stopPropagation();

export default function AudioTab() {
  const s = useNs("audio");
  const shell = useNs("shell");
  const rows = s.rows || [];
  const panes = s.panes || {};
  const [sel, setSel] = useState(s.sel || []);
  const selRef = useRef(sel); selRef.current = sel;
  const anchor = useRef(null);
  const cursor = useRef(null);         // the Tk tree's focus row (see keyNav)
  const sentSel = useRef(null);        // the last selection this page sent
  const gripW = useRef(null);          // header widths when a column drag began
  const wrapRef = useRef(null);
  const [props, setProps] = useState(null);
  const [adv, setAdv] = useState(null);
  const selKey = JSON.stringify(s.sel || []);
  useEffect(() => {
    const next = s.sel || [];
    setSel(next);
    // a selection Python made (sequential play, a pick, a rename) moves the
    // focus row to it; the echo of the page's own selection leaves it be
    if (selKey !== sentSel.current && next.length) { cursor.current = next[0]; anchor.current = next[0]; }
  }, [selKey]);
  const index = useMemo(() => new Map(rows.map((r, i) => [r.k, i])), [rows]);

  // keep the players on what the panes hold
  useEffect(() => { syncPlayer("orig", panes.orig); }, [panes.orig && panes.orig.v, panes.orig && panes.orig.limit, panes.orig && panes.orig.gain]);
  useEffect(() => { syncPlayer("rep", panes.rep); }, [panes.rep && panes.rep.v, panes.rep && panes.rep.limit, panes.rep && panes.rep.gain]);
  useEvent("audio_play", (e) => {
    const pane = ((state.audio || {}).panes || {})[e.pane];
    const p = syncPlayer(e.pane, pane);
    if (!pane || pane.path !== e.path) return;
    startPlayer(p, e.pos);
  }, []);
  useEvent("audio_stop", () => stopAll(), []);
  // leaving the tab silences it (the Tk tab change did the same): Python's
  // select_tab stops every preview, but its "audio_stop" can land after this
  // page has unmounted, and the players outlive it
  useEffect(() => () => stopAll(), []);

  const select = (next) => {
    const ordered = byIndex(next, index);
    sentSel.current = JSON.stringify(ordered);
    setSel(ordered);
    call("audio.select", ordered, playingSide());
  };
  // one row, as a plain click or a row control does
  const selectOne = (k) => { cursor.current = k; anchor.current = k; select([k]); };
  // a mouse click on a row (the Table's keyboard never gets here: onKeyCapture)
  const onSelect = (r, i, e) => {
    if (!r) return;
    const click = !e || e.type === "click";
    if (r.g) {
      // a group row: select it (Tk's press did) and open / close it; the
      // second click of a double-click leaves it as the first one set it
      if (!click || (e && e.detail > 1)) return;
      selectOne(r.k);
      call("audio.toggle_group", r.k);
      return;
    }
    const cur = selRef.current;
    cursor.current = r.k;
    if (e && (e.ctrlKey || e.metaKey) && click) {
      anchor.current = r.k;
      select(cur.includes(r.k) ? cur.filter((k) => k !== r.k) : [...cur, r.k]);
      return;
    }
    if (e && e.shiftKey && anchor.current != null && index.has(anchor.current)) {
      const a = index.get(anchor.current), b = i;
      const lo = Math.min(a, b), hi = Math.max(a, b);
      select(rows.slice(lo, hi + 1).filter((x) => !x.g).map((x) => x.k));
      return;
    }
    selectOne(r.k);
  };
  // keep the focus row in view when the keyboard moves it (the Table only
  // follows a single selection)
  const reveal = (k) => {
    const el = wrapRef.current && wrapRef.current.querySelector(".scroller");
    const i = index.get(k);
    if (!el || i == null) return;
    const y = i * ROW_H;
    if (y < el.scrollTop) el.scrollTop = y;
    else if (y + ROW_H > el.scrollTop + el.clientHeight - ROW_H) el.scrollTop = y - el.clientHeight + ROW_H * 2;
  };
  // the arrows (and Enter on a group row), ahead of the Table's own keys
  const onKeyCapture = (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target && e.target.closest && e.target.closest("input, textarea, select")) return;
    const k = e.key;
    if (k === "Enter") {
      const i = cursor.current != null ? index.get(cursor.current) : null;
      const r = i != null ? rows[i] : null;
      if (r && r.g && selRef.current.length === 1 && selRef.current[0] === r.k) {
        e.preventDefault(); e.stopPropagation();
        call("audio.toggle_group", r.k);
      }
      return;
    }
    if (k !== "ArrowDown" && k !== "ArrowUp" && k !== "ArrowLeft" && k !== "ArrowRight") return;
    e.preventDefault(); e.stopPropagation();
    const got = keyNav(rows, index, { cursor: cursor.current, anchor: anchor.current, sel: selRef.current }, k, e.shiftKey);
    if (!got) return;
    cursor.current = got.cursor;
    anchor.current = got.anchor;
    select(got.sel);
    if (got.toggle) call("audio.toggle_group", got.toggle);
    reveal(got.cursor);
  };
  const doAction = async (action, rel, cur) => {
    const res = await call("audio.menu_action", action, rel, cur);
    if (res && res.open === "props" && res.data) setProps(res.data);
  };
  const onContext = async (r, i, e) => {
    if (!r || r.g) return;
    const x = e.clientX, y = e.clientY;
    let cur = selRef.current;
    if (!(cur.includes(r.k) && cur.length >= 2)) { cur = [r.k]; selectOne(r.k); }
    const items = await call("audio.menu", r.k, cur);
    if (!items || !items.length) return;
    // a toggle entry reads as a box, ticked or not ("☑  Keep this song
    // whole…" / "☐  …", the Tk menu's own labels)
    openMenu({ x, y }, items.map((it) => it.sep ? { sep: true } : ({
      label: it.checked == null ? it.label : (it.checked ? "☑  " : "☐  ") + it.label,
      icon: it.icon, kbd: it.kbd, disabled: it.disabled,
      onClick: it.action ? () => doAction(it.action, r.k, cur) : undefined })));
  };
  const openProps = async () => {
    const data = await call("audio.props_info");
    if (data) setProps(data);
  };
  const openAdv = async () => {
    const data = await call("audio.advanced_get");
    if (data) setAdv(data);
  };
  const onKey = (e) => {
    if (e.key === " " || e.code === "Space") {
      e.preventDefault();
      const side = playingSide();
      if (side) stopPlayer(player(side)); else call("audio.space");
    } else if (e.key === "F2") {
      e.preventDefault();
      openProps();
    }
  };
  const playPane = (side) => {
    syncPlayer(side, panes[side]);
    call("audio.play", side);
  };

  // ---- the table
  const col = s.col;
  // Column drags go through the core Table (resizable / widths / onResize).
  // Like the Tk tree, only the columns the drag actually changed are saved
  // (column_widths.audio): the widths the header had when the grip was
  // pressed are the "before".
  const headerWidths = () => {
    const hdr = wrapRef.current && wrapRef.current.querySelector(".tr.th");
    const out = {};
    if (hdr) [...hdr.children].forEach((c, n) => { if (columns[n]) out[columns[n].key] = Math.round(c.getBoundingClientRect().width); });
    return out;
  };
  const onGripDown = (e) => {
    gripW.current = e.target && e.target.classList && e.target.classList.contains("col-grip") ? headerWidths() : null;
  };
  const onResize = (after) => {
    const before = gripW.current || {};
    gripW.current = null;
    // both are measured on screen, so under the app zoom they are zoomed
    // pixels; what is saved (and laid out) is CSS pixels
    const z = parseFloat(document.documentElement.style.zoom) || 1;
    const changed = {};
    for (const [k, w] of Object.entries(after || {})) {
      if (k !== "play" && Math.abs((before[k] ?? -1) - w) >= 1) changed[k] = Math.round(w / z);
    }
    if (Object.keys(changed).length) call("audio.save_widths", changed);
  };
  const flagName = col === "loop" ? "Loop" : "Full";
  // The two columns that stretch in Tk (Original Track, Replacement) keep
  // their Tk minwidth here too: a tuned Original Track width is its widest,
  // and it gives way before the Replacement column drops under 110 px (the
  // Tk tree clipped Replacement instead; the Table has no horizontal room).
  const saved = s.widths || {};
  const tblWidths = {};
  for (const [k, w] of Object.entries(saved)) if (k !== "#0") tblWidths[k] = w;
  const name0 = saved["#0"] ? `minmax(${MIN_W["#0"]}px,${saved["#0"]}px)` : `minmax(${MIN_W["#0"]}px,1.25fr)`;
  const columns = [
    { key: "play", label: "", width: FIXED.play + "px", cls: "aud-pc",
      render: (r) => r.g
        ? html`<span class="aud-caret"><${Icon} name=${r.open ? "down" : "right"} /></span>`
        : html`<button type="button" class="aud-rowplay" aria-label="Play" ...${tip("Play")} onDblClick=${noDbl}
            onClick=${once(() => { cursor.current = r.k; anchor.current = r.k; sentSel.current = JSON.stringify([r.k]); setSel([r.k]); call("audio.play_row", r.k); })}><${Icon} name="play" /></button>` },
    { key: "#0", label: "Original Track", sort: "#0", width: name0, titleOf: (r) => r.g ? r.label : r.k,
      render: (r) => html`<${NameCell} r=${r} prefix=${s.prefix} />` },
    { key: "len", label: "Length", sort: "len", width: FIXED.len + "px", num: true, render: (r) => r.len },
    { key: "fmt", label: "Format", sort: "fmt", width: FIXED.fmt + "px", titleOf: (r) => r.fmt, render: (r) => html`<span class="dim">${r.fmt || ""}</span>` },
    { key: "type", label: "Type", sort: "type", width: FIXED.type + "px", render: (r) => r.type || "" },
    ...(col === "loop" || col === "keep" ? [{ key: col, label: html`<span class="aud-hc">${flagName}</span>`, sort: col,
      title: col === "loop" ? T.loop : T.keep, width: FIXED[col] + "px", cls: "aud-flagc",
      titleOf: () => (col === "loop" ? T.loop : T.keep),
      render: (r) => r.g ? "" : html`<button type="button" role="checkbox" aria-checked=${!!r[col]} aria-label=${flagName}
        class=${cx("aud-flag", r[col] && "on")} onDblClick=${noDbl}
        onClick=${once(() => call("audio.toggle_flag", r.k, col))}>${r[col] ? html`<${Icon} name="check" />` : null}</button>` }] : []),
    ...(col === "lvl" ? [{ key: "lvl", label: "Level", sort: "lvl", title: T.level, width: FIXED.lvl + "px", num: true,
      titleOf: () => T.level, render: (r) => r.lvl || "" }] : []),
    { key: "rep", label: "Replacement", sort: "rep", width: `minmax(${MIN_W.rep}px,1fr)`, titleOf: (r) => r.rep,
      render: (r) => r.g ? html`<span class="muted">${r.rep}</span>`
        : html`<button type="button" class=${cx("aud-rep", r.t === "picked" && "picked", r.t === "ondisk" && "ondisk", r.t === "stray" && "stray", !r.t && "choose")}
            onDblClick=${noDbl} onClick=${once(() => { selectOne(r.k); call("audio.choose", r.k); })}>${r.rep}</button>` },
  ];
  const selected = sel.length === 1 ? sel[0] : new Set(sel);
  const selRel = sel.find((k) => index.has(k) && !String(k).startsWith("::dupgrp::")) || null;
  const cur = s.cur;

  const empty = html`<div class=${cx("aud-empty", (s.scanning || s.dup_scanning) && "busy")}>
    ${s.scanning || s.dup_scanning ? html`<${Spinner} />` : null}<span class="wrap">${s.empty || ""}</span></div>`;

  const repActions = html`
    <${Button} size="sm" disabled=${!cur} onClick=${() => call("audio.choose_selected")}>Choose…<//>
    ${cur && cur.built ? html`<${Button} size="sm" kind="ghost" icon="undo" onClick=${() => call("audio.remove_selected")}>Revert to original<//>`
      : cur && cur.assigned ? html`<${Button} size="sm" kind="ghost" onClick=${() => call("audio.remove_selected")}>Remove replacement<//>` : null}`;

  return html`<div class="page aud-page">
    <${PageHead} title="Audio" sub=${T.intro}>
      ${s.status ? html`<${Chip} kind="acc">${s.status}<//>` : null}
      <${Button} onClick=${() => call("audio.scan")} icon=${s.scanning ? "x" : "refresh"}>${s.scanning ? "Cancel scan" : "Scan"}<//>
      <${Button} disabled=${s.running} title=${T.fromFolder} onClick=${() => call("audio.replace_from_folder")}>Replace from folder…<//>
      <${Button} kind="ghost" title=${T.csv} onClick=${() => call("audio.export_csv")}>Export CSV<//>
      <${Button} kind="ghost" title=${T.clear} disabled=${!s.can_clear || s.running} onClick=${() => call("audio.clear_all")}>Clear replacements…<//>
      ${s.adv_cap ? html`
        <${Button} kind="ghost" title=${T.adv} onClick=${openAdv}>${s.adv_marker ? "Advanced…*" : "Advanced…"}<//>
        <${Button} kind="ghost" title=${T.profile} disabled=${s.profile_busy} busy=${s.profile_busy} onClick=${() => call("audio.profile")}>Profile vs stock<//>` : null}
    <//>
    <div class="row small aud-folder">
      <span class="lbl nw">Project Folder:</span>
      ${s.folder ? html`<a class="mono ellip" href="#" onClick=${(e) => { e.preventDefault(); call("audio.open_folder"); }} ...${tip(T.folder)}>${s.folder}</a>`
        : html`<span class="muted ellip">${s.folder_note}</span>`}
    </div>
    ${s.ffmpeg_missing ? html`<${Note} kind="err">${s.ffmpeg_text}<//>` : null}
    <${Card} cls="aud-card" bodyCls="flush aud-body" footer=${html`<div class="aud-panes">
        <${Pane} side="orig" pane=${panes.orig} onPlay=${playPane} />
        <span class="aud-vsep"></span>
        <${Pane} side="rep" pane=${panes.rep} onPlay=${playPane} actions=${repActions}
          extra=${s.level_cap ? html`<${Loudness} s=${s} selRel=${selRel} />` : null} />
      </div>`}>
      <div class="toolbar aud-tools">
        <${Field} cls="search" ns="audio" k="search" value=${s.search} placeholder="Search" prefix=${html`<${Icon} name="search" />`} />
        ${s.type_useful ? html`<span class="row aud-seg" ...${tip(T.type)}><span class="lbl">Type</span>
          <${Seg} value=${s.type} options=${TYPES} onChange=${(v) => call("audio.set_type", v)} /></span>` : null}
        ${s.dups_cap ? html`<${Check} checked=${s.group_dups} label="Group duplicates" title=${T.dups}
          onChange=${(v) => call("audio.set_group_dups", v)} />` : null}
        <span class="row aud-seg" ...${tip(T.show)}><span class="lbl">Show</span>
          <${Seg} value=${s.show} options=${SHOWS} onChange=${(v) => call("audio.set_show", v)} /></span>
        <span class="sp"></span>
        ${s.trim_visible ? html`<${Check} cls="small" checked=${s.trim} label="Trim / pad replacements to the original slot length" title=${s.trim_tip}
          onChange=${(v) => call("audio.set_trim", v)} />` : null}
        <${Check} cls="small" ns="audio" k="play_through" checked=${s.play_through} label="Play sequentially" title=${T.seq} />
        <${Check} cls="small" checked=${s.play_subst} label="Play replacements" title=${T.subst}
          onChange=${(v) => call("audio.set_play_subst", v)} />
      </div>
      <div class="aud-tblwrap" ref=${wrapRef} onKeyDown=${onKey} onKeyDownCapture=${onKeyCapture} onMouseDownCapture=${onGripDown}>
        <${Table} cls="aud-tbl" columns=${columns} rows=${rows} rowKey=${(r) => r.k} selected=${selected}
          onSelect=${onSelect} onActivate=${(r) => { if (!r.g) call("audio.choose", r.k); }} onContext=${onContext}
          sort=${s.sort || {}} onSort=${(k) => call("audio.sort", k)}
          resizable widths=${tblWidths} onResize=${onResize}
          rowClass=${(r) => cx(r.g && "aud-grp", r.t === "stray" && "aud-stray")} empty=${empty} rowHeight=${ROW_H} />
      </div>
    <//>
    ${props ? html`<${PropsModal} data=${props} onClose=${() => setProps(null)} />` : null}
    ${adv ? html`<${AdvancedModal} data=${adv} onClose=${() => setAdv(null)} />` : null}
  </div>`;
}
