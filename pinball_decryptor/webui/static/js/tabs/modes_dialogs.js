// The Modes tab's dialogs: the game's own modes (the stock timers and awards table), the
// film cutter ("Cut from a film"), New code mode's name, and a clip's preview.
// Python owns the state (modes.stock, modes.film); these only render it and call back.

import { html, useEffect, useRef, useState, Modal, Button, Field, Check, Radio, Table, Note,
         tip, cx, call, mediaUrl } from "../core/ui.js";

const STOCK_TIP = "The timers and awards of the modes the game shipped with. Pick a row, type a new value and press Set. Changes are saved with this project and put on the card by Write, like the Defaults tab. A timer that is an operator setting is the same number the Defaults tab shows (a machine still on the game's default takes the new one when it boots). A number the game works out in code can't be changed here; the row says why. To rename a mode, edit its title on the Text tab.";

// ------------------------------------------------------------ the game's own modes
// The Tk Treeview's headings could be dragged to widen a column: the widths a person drags
// are kept for the session and in this browser (a convenience; Tk kept them per session).
const STOCK_WIDTHS_KEY = "pad.modes.stock_widths";
let stockWidths = (() => { try { return JSON.parse(localStorage.getItem(STOCK_WIDTHS_KEY) || "null"); } catch (e) { return null; } })();

export function StockDialog({ s, onClose }) {
  const st = s.stock || {};
  const rows = st.rows || [];
  const [val, setVal] = useState(st.value || "");
  const [widths, setWidths] = useState(stockWidths);
  const keepWidths = (w) => {
    stockWidths = w;
    setWidths(w);
    try { localStorage.setItem(STOCK_WIDTHS_KEY, JSON.stringify(w)); } catch (e) { /* private window */ }
  };
  useEffect(() => { call("modes.stock_refresh"); }, []);
  useEffect(() => { setVal(st.value || ""); }, [st.sel, st.value]);
  const columns = [
    { key: "mode", label: "Mode", width: "minmax(160px, 1.3fr)", titleOf: (r) => r.mode },
    { key: "number", label: "Number", width: "minmax(120px, 1fr)", titleOf: (r) => r.number },
    { key: "value", label: "Value", width: "110px", num: true },
    { key: "stock", label: "Stock", width: "110px", num: true },
    { key: "where", label: "Where it lives", width: "minmax(180px, 1.6fr)", titleOf: (r) => r.where },
  ];
  const can = st.on && st.row_on;
  const set = () => { if (can) call("modes.stock_set", val); };
  return html`<${Modal} title="The game's own modes" icon="list" xwide onClose=${onClose}
    footer=${html`<span class="lbl">New value</span>
      <div style="width:150px" onKeyDown=${(e) => { if (e.key === "Enter") set(); }}>
        <${Field} value=${val} onChange=${setVal} mono sm disabled=${!can} /></div>
      <${Button} size="sm" kind="primary" disabled=${!can} onClick=${set}>Set<//>
      <${Button} size="sm" disabled=${!can} onClick=${() => call("modes.stock_reset")}
        title="Put the selected number back to the game's own value.">Stock<//>
      <${Button} size="sm" kind="ghost" disabled=${!st.on} onClick=${() => call("modes.stock_all")}>All to stock<//>
      <span class="grow"></span>
      <${Button} onClick=${onClose}>Close<//>`}>
    <div class="small dim wrap" ...${tip(STOCK_TIP)}>${st.msg}</div>
    ${st.on ? html`<${Table} cls="modes-stock" columns=${columns} rows=${rows} rowKey=${(r) => r.key}
        resizable widths=${widths} onResize=${keepWidths}
        selected=${st.sel} onSelect=${(r) => call("modes.stock_select", r.key)}
        rowClass=${(r) => cx(r.changed && "changed", r.readonly && "readonly")}
        style="height:min(52vh, 460px)" />` : null}
    ${st.note ? html`<${Note} kind=${st.note.startsWith("Read-only") ? "" : "info"}>${st.note}<//>` : null}
  <//>`;
}

// ------------------------------------------------------------------ the film cutter
const FILM_TIP = "Cut this mode's clip, its sound or its screen's picture from a film: pick the film, a start time and a length (up to 30 seconds), and whether to keep the film's letterbox or fill the frame. The mode keeps only the cut (clip.mp4, end.wav, art.png), never the film.";
const FILM_KEYS = ["film", "start", "length", "crop", "take_clip", "take_sound", "take_still",
                   "sound_same", "sound_start", "sound_length", "still_at"];
const pick = (film) => { const o = {}; for (const k of FILM_KEYS) o[k] = film[k]; return o; };

// The dialog keeps its own copy of the fields and hands them over with each action, as the
// Tk dialog's sync() copied its widgets into the form before a probe, a preview or a cut.
export function FilmDialog({ film }) {
  const [v, setV] = useState(() => pick(film));
  useEffect(() => { setV(pick(film)); }, [film.seq]);
  useEffect(() => { setV((o) => Object.assign({}, o, { film: film.film })); }, [film.film]);
  const put = (k) => (x) => setV((o) => Object.assign({}, o, { [k]: x }));
  const busy = !!film.busy;
  const close = () => call("modes.film_close");
  return html`<${Modal} title="Cut from a film" icon="film" wide onClose=${close}
    footer=${html`<span class="grow"></span>
      <${Button} onClick=${close}>Cancel<//>
      <${Button} kind="primary" busy=${busy} disabled=${busy} onClick=${() => call("modes.film_cut", v)}>Cut<//>`}>
    <div class="modes-film">
      <label class="lbl">Film</label>
      <div class="row">
        <${Field} value=${v.film} onChange=${put("film")} mono cls="grow" placeholder="A film on this computer"
          onCommit=${(x) => call("modes.film_probe", Object.assign({}, v, { film: x }))} />
        <${Button} onClick=${() => call("modes.film_choose", v)}>Choose…<//>
      </div>
      <span></span><div class="small muted wrap">${film.info}</div>

      <label class="lbl">Start at</label>
      <div class="row wrap">
        <${Field} value=${v.start} onChange=${put("start")} mono width=${90} />
        <span class="dim">(m:ss)   for</span>
        <${Field} value=${v.length} onChange=${put("length")} mono width=${76} type="number"
          min=${1} max=${film.max || 30} step="any" />
        <span class="dim">seconds (up to ${film.max || 30})</span>
      </div>

      <label class="lbl">Crop</label>
      <div class="row wrap">
        <${Radio} name="film-crop" value="letterbox" label="Keep the letterbox" checked=${v.crop === "letterbox"} onChange=${put("crop")} />
        <${Radio} name="film-crop" value="fill" label="Fill the frame" checked=${v.crop === "fill"} onChange=${put("crop")} />
      </div>

      <label class="lbl">Take</label>
      <div class="row wrap">
        <${Check} label="The clip" checked=${v.take_clip} onChange=${put("take_clip")} />
        <${Check} label="The sound" checked=${v.take_sound} onChange=${put("take_sound")} />
        <${Check} label="A picture" checked=${v.take_still} onChange=${put("take_still")} />
      </div>

      <label class="lbl">Sound</label>
      <div class="row wrap">
        <${Radio} name="film-sound" value="same" label="The same span" checked=${v.sound_same} onChange=${() => put("sound_same")(true)} />
        <${Radio} name="film-sound" value="other" label="From" checked=${!v.sound_same} onChange=${() => put("sound_same")(false)} />
        <${Field} value=${v.sound_start} onChange=${put("sound_start")} mono width=${90} />
        <span class="dim">for</span>
        <${Field} value=${v.sound_length} onChange=${put("sound_length")} mono width=${64} />
        <span class="dim">seconds</span>
      </div>

      <label class="lbl">Picture at</label>
      <div class="row">
        <${Field} value=${v.still_at} onChange=${put("still_at")} mono width=${90} />
        <span class="dim">(empty = the start)</span>
      </div>

      <span></span>
      <div class="row" style="align-items:flex-start;gap:12px;flex-wrap:wrap">
        <${Button} onClick=${() => call("modes.film_preview", v)}>Preview the start<//>
        <div class="thumb modes-film-frame">${film.preview
          ? html`<img src=${mediaUrl(film.preview)} alt="The frame at the start" />`
          : html`<span class="small">The frame at the start shows here.</span>`}</div>
      </div>
    </div>
    <div class=${cx("small wrap", film.error ? "err-ink" : "dim")} role="status" ...${tip(FILM_TIP)}>${film.status}</div>
  <//>`;
}

// ---------------------------------------------------------------- New code mode
export function NewCodeDialog({ onClose }) {
  const [name, setName] = useState("");
  const ok = () => { const n = name.trim(); if (!n) return; call("modes.new_code_mode", n); onClose(); };
  return html`<${Modal} title="New code mode" icon="edit" onClose=${onClose}
    footer=${html`<${Button} onClick=${onClose}>Cancel<//><${Button} kind="primary" disabled=${!name.trim()} onClick=${ok}>OK<//>`}>
    <label class="lbl" for="modes-code-name">What is the mode called?</label>
    <${Field} id="modes-code-name" value=${name} onChange=${setName} autoFocus onCommit=${(v) => { if (v.trim()) { setName(v); } }} />
    <div class="small muted">A mode written in C, for what the form cannot do: a copy of the Mode SDK's template in this project's modes folder. Try it builds it in with the others.</div>
    <${EnterKey} onEnter=${ok} />
  <//>`;
}

function EnterKey({ onEnter }) {
  const ref = useRef(onEnter);
  ref.current = onEnter;
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ref.current(); } };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return null;
}

// ------------------------------------------------------------------ a clip's preview
export function ClipDialog({ path, title, onClose }) {
  return html`<${Modal} title=${title || "Clip"} icon="video" wide onClose=${onClose}
    footer=${html`<span class="small mono muted grow ellip">${path}</span><${Button} onClick=${onClose}>Close<//>`}>
    <div class="thumb" style="height:min(56vh, 480px)">
      <video src=${mediaUrl(path)} controls autoplay style="width:100%;height:100%"></video>
    </div>
  <//>`;
}

// a sound's play/stop button (one sound at a time across the tab)
let playing = null;
export function PlayButton({ path, label = "Play" }) {
  const [on, setOn] = useState(false);
  useEffect(() => () => { if (playing && playing.owner === setOn) { playing.audio.pause(); playing = null; } }, []);
  if (!path) return null;
  const toggle = () => {
    if (playing) { playing.audio.pause(); playing.owner(false); const was = playing.path; playing = null; if (was === path) return; }
    const audio = new Audio(mediaUrl(path));
    audio.onended = () => { setOn(false); if (playing && playing.audio === audio) playing = null; };
    audio.play().catch(() => setOn(false));
    playing = { audio, owner: setOn, path };
    setOn(true);
  };
  return html`<${Button} size="xs" kind="ghost" icon=${on ? "stop" : "play"} title=${on ? "Stop" : label + ": " + path} onClick=${toggle}>${on ? "Stop" : label}<//>`;
}
