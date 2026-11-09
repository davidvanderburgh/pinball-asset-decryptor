// The Modes tab's dialogs: the game's own modes (the stock timers and awards table), the
// video cutter ("Cut from a video") and a clip's preview.
// Python owns the state (modes.stock, modes.film); these only render it and call back.

import { html, useEffect, useState, Modal, Button, Field, Check, Radio, Select, Table, Note,
         tip, cx, call, mediaUrl } from "../core/ui.js";

const STOCK_TIP = "The timers, awards and shots of the modes the game shipped with. Pick a row, type a new value (or pick a shot) and press Set. Changes are saved with this project and put on the card by Write, like the Defaults tab. A timer that is an operator setting is the same number the Defaults tab shows (a machine still on the game's default takes the new one when it boots). A number the game works out in code, or one the game never uses in play, can't be changed here; the row says why. To rename a mode, edit its title on the Text tab.";

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
    { key: "where", label: "Where it lives", width: "minmax(180px, 1.6fr)", titleOf: (r) => r.hint || r.where },
  ];
  const can = st.on && st.row_on;
  const set = () => { if (can) call("modes.stock_set", val); };
  // item 159: a tank position is picked by shot name (Python lists the shots the switches
  // send alone, and none); every other number is typed
  const choices = st.choices || null;
  return html`<${Modal} title="The game's own modes" icon="list" xwide onClose=${onClose}
    footer=${html`<span class="lbl">New value</span>
      ${choices ? html`<${Select} value=${val} options=${choices} onChange=${setVal} sm width=${240} disabled=${!can} />`
                : html`<div style="width:150px" onKeyDown=${(e) => { if (e.key === "Enter") set(); }}>
        <${Field} value=${val} onChange=${setVal} mono sm disabled=${!can} /></div>`}
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
const FILM_TIP = "Cut this mode's clip, its sound or its screen's picture from a video file of your own (a film, an episode, anything): pick the video, a start time and a length (up to 30 seconds), and whether to keep its letterbox or fill the frame. The mode keeps only the cut (clip.mp4, end.wav, art.png), never the video.";
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
  return html`<${Modal} title="Cut from a video" icon="film" wide onClose=${close}
    footer=${html`<span class="grow"></span>
      <${Button} onClick=${close}>Cancel<//>
      <${Button} kind="primary" busy=${busy} disabled=${busy} onClick=${() => call("modes.film_cut", v)}>Cut<//>`}>
    <div class="modes-film">
      <label class="lbl">Video</label>
      <div class="row">
        <${Field} value=${v.film} onChange=${put("film")} mono cls="grow" placeholder="A video file on this computer"
          onCommit=${(x) => call("modes.film_probe", Object.assign({}, v, { film: x }))} />
        <${Button} drop onClick=${() => call("modes.film_choose", v)}>Choose…<//>
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

// ------------------------------------------------------------------ co-op awards (PAD-1028)
// What the machine shows after a co-op game: one award a row, ticked or not, its words as the page's title.
// Python reads the rows off the project's card (modes.coop_aw) and keeps the choices in the project.
/* PAD-1033: what each handicap level does on the card's game (read off its program) */
export function HandicapLevelsDialog({ s, onClose }) {
  const lv = s.hand_levels || {};
  const grid = lv.grid || [];
  const levels = lv.levels || [];
  useEffect(() => { call("modes.handicap_levels_refresh"); }, []);
  // a cell: the app's default (its words), the game's own value, or any value the game's own setting offers
  const opts = (r, c) => [{ value: "", label: `app: ${c.default}` }, { value: "own", label: "game's own" },
    ...Array.from({ length: r.hi - r.lo + 1 }, (_, k) => ({ value: String(r.lo + k), label: String(r.lo + k) }))];
  const ink = (l) => (l.startsWith("-") ? "warn-ink" : "ok-ink");
  return html`<${Modal} title="Handicap levels" icon="list" xwide onClose=${onClose}
    footer=${html`<span class="small muted">${lv.changed ? `${lv.changed} setting(s) changed from the app's.` : "Every level as the app worked it out."}</span>
      <span class="grow"></span>
      <${Button} size="sm" kind="ghost" disabled=${!lv.changed} onClick=${() => call("modes.handicap_defaults")}
        title="Every level as the app worked it out for this game again.">Defaults<//>
      <${Button} onClick=${onClose}>Close<//>`}>
    <div class="small dim wrap">Each column is a level, each row one of the game's own difficulty settings. "app:" is the app's choice; pick the game's own value or any value the setting offers in the service menu instead. Level 0 is always the game's own settings.</div>
    ${lv.why ? html`<${Note} kind="info">${lv.why}<//>` : null}
    ${grid.length ? html`<div class="modes-hand-grid" style=${`grid-template-columns: minmax(170px, 1fr) repeat(${levels.length}, 136px)`}>
      <span></span>${levels.map((l) => html`<b key=${l} class=${cx("modes-hand-lv", ink(l))}>${l}</b>`)}
      ${grid.map((r) => html`
        <span class="small wrap modes-hand-name" key=${r.name} title=${`${r.name}: ${r.lo} to ${r.hi}`}>${r.label}</span>
        ${r.cells.map((c) => html`<${Select} key=${r.name + c.level} sm value=${c.value} options=${opts(r, c)}
          cls=${cx(c.custom && "modes-hand-custom")} title=${`${r.label} at ${c.level}: the app's choice is ${c.default}`}
          onChange=${(v) => call("modes.handicap_cell", c.level, r.name, v)} />`)}`)}
    </div>` : lv.why ? null : html`<div class="small muted">Reading the game program on the card…</div>`}
    ${(lv.said || []).length ? html`<div class="modes-hand-levels">
      ${lv.said.map((r) => html`<div class="modes-hand-row" key=${r.level}><b class=${ink(r.level)}>${r.level}</b>
        <span class="small wrap">${r.words}</span></div>`)}
    </div>` : null}
  <//>`;
}

export function CoopAwardsDialog({ s, onClose }) {
  const aw = s.coop_aw || {};
  const rows = aw.rows || [];
  useEffect(() => { call("modes.coop_awards_refresh"); }, []);
  const every = rows.filter((r) => r.kind !== "champion");
  const own = rows.filter((r) => r.kind === "champion");
  const row = (r) => html`<div class="modes-coop-aw-row" key=${r.key}>
    <${Check} checked=${r.on} title=${`Counts ${r.counts}.`}
      onChange=${(v) => call("modes.coop_award_set", r.key, v, null)} />
    <${Field} value=${r.words} sm maxLength=${aw.max_words || 27} width=${260} disabled=${!r.on}
      title=${`The page's title. The game's own words: ${r.stock_words}`}
      onCommit=${(v) => { if (v !== r.words) call("modes.coop_award_set", r.key, null, v); }} />
    <span class="small dim wrap">${r.counts}</span>
  </div>`;
  return html`<${Modal} title="Co-op awards" icon="star" wide onClose=${onClose}
    footer=${html`<span class="small muted">${aw.note}</span><span class="grow"></span>
      <${Button} size="sm" kind="ghost" disabled=${!rows.length} onClick=${() => call("modes.coop_awards_defaults")}
        title="Every award ticked and worded as the app first had it for this game.">Defaults<//>
      <${Button} onClick=${onClose}>Close<//>`}>
    <div class="small dim wrap">${s.coop_awards_tip}</div>
    ${aw.why ? html`<${Note} kind="info">${aw.why}<//>` : null}
    ${rows.length ? html`<div class="modes-coop-aw" style="max-height:min(56vh, 520px)">
      <div class="modes-list-grp">Every game</div>
      ${every.map(row)}
      ${own.length ? html`<div class="modes-list-grp">This game's own counts</div>` : null}
      ${own.map(row)}
    </div>` : null}
  <//>`;
}

// ------------------------------------------------------------------ co-op characters (PAD-1031)
// Each teammate picks one at the start of their first ball; its ability holds while they are up. One row a character:
// its name (the top line shows it) with a smaller sub header under it on its cards (PAD-1056),
// its ability (only the ones this game's program can have are offered), what that
// does. Python reads the abilities off the project's card (modes.coop_ch) and keeps the characters in the project.
// Round 6 (David: the end user customizes the abilities in the app): a character is a list of powers, each one thing
// the game does differently while its teammate is up; the row shows its badge (its powers' words, or a header of its
// own) and Powers... opens the list, grouped, with a tick per power this game can have. The set abilities of before
// are starting points (Start from...). Python composes the list and refuses what the runtime has no room for.
// PAD-1079 (DoomWalrus666: change the colours of certain text, other customizations): Look... opens the pick screen's
// look - its title, a colour for each text and the panel, a background picture behind every card - and each row has
// a colour of its own for its card's frame. Python keeps them with the characters and redraws the preview.

// a colour well that sends the colour once it is picked (the native picker's change, not every drag)
function Well({ value, title, onPick }) {
  const v = /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : "#000000";
  return html`<label class="modes-swatch" ...${tip(title)}>
    <input type="color" value=${v} aria-label=${title} onChange=${(e) => onPick(e.target.value)} />
    <span class="chip-c" style=${`background:${v}`}></span>
  </label>`;
}

function CoopLook({ look }) {
  return html`<div class="modes-coop-look">
    <div class="row" style="gap:8px">
      <span class="small dim">Title</span>
      <${Field} value=${look.title} sm maxLength=${40} width=${300}
        title="The words across the top of every pick card (capitals)."
        onCommit=${(v) => { if (v !== look.title) call("modes.coop_chars_look", "title", v); }} />
      <span class="grow"></span>
      <${Button} size="sm" kind="ghost" onClick=${() => call("modes.coop_chars_look_default")}
        title="The game's set's own title and colours again, and no background picture.">Default look<//>
    </div>
    <div class="modes-coop-look-grid">
      ${look.colours.map((c) => html`<span class="modes-coop-look-c" key=${c.key}>
        <${Well} value=${c.value} title=${`${c.label}${c.hint ? `: ${c.hint}` : ""}`}
          onPick=${(v) => call("modes.coop_chars_look", c.key, v)} />
        <span class="small">${c.label}</span>
        ${c.own ? html`<${Button} size="xs" kind="ghost" icon="x" title="Its default colour again."
          onClick=${() => call("modes.coop_chars_look", c.key, "")} />` : null}
      </span>`)}
    </div>
    <div class="row" style="gap:8px">
      <${Button} size="sm" kind="ghost" icon="image" onClick=${() => call("modes.coop_chars_backdrop", false)}
        title=${look.backdrop ? "The picture behind every pick card and award card: choose another." : "A picture of your own behind every pick card and award card, in place of the panel (the panel's colour then goes unused)."}>
        ${look.backdrop ? "Background ✓" : "Background…"}<//>
      ${look.backdrop ? html`<${Button} size="xs" kind="ghost" icon="x" title="Back to the panel."
        onClick=${() => call("modes.coop_chars_backdrop", true)} />` : null}
      <span class="small dim" style="margin-left:8px">Darken it</span>
      <${Select} sm value=${String(look.dim)} width=${110} disabled=${!look.backdrop}
        options=${look.dims.map((d) => ({ value: String(d), label: d ? `${d}%` : "Not at all" }))}
        title="How much darker the background picture is drawn, so the words over it stay easy to read."
        onChange=${(v) => call("modes.coop_chars_look", "dim", v)} />
    </div>
  </div>`;
}

export function CoopCharsDialog({ s, onClose }) {
  const ch = s.coop_ch || {};
  const rows = ch.rows || [];
  const abil = ch.abilities || [];
  const powers = ch.powers || [];
  const groups = ch.groups || [];
  const [open, setOpen] = useState(-1);
  const [looking, setLooking] = useState(false);
  useEffect(() => { call("modes.coop_chars_refresh"); }, []);
  const opts = [{ value: "", label: "Start from..." }, { value: "-", label: "No powers" }].concat(abil.map((a) => (
    { value: a.key, label: a.ok ? a.words : `${a.words} (not on this game)`, disabled: !a.ok })));
  const powerTitle = (p, has) => p.ok ? `${p.does}${has ? "" : " Tick to give this character the power."}`
    : `${p.why} Not on this game: a character with it has it left off its card here.`;
  const powersOf = (r, i) => html`<div class="modes-coop-ch-powers">
    ${groups.map((g) => {
      const list = powers.filter((p) => p.group === g);
      return list.length ? html`<div class="modes-coop-ch-grp" key=${g}>
        <div class="modes-list-grp">${g}</div>
        ${list.map((p) => html`<${Check} key=${p.key} checked=${r.powers.includes(p.key)} disabled=${!p.ok && !r.powers.includes(p.key)}
          label=${p.ok ? p.words : `${p.words} (not on this game)`} title=${powerTitle(p, r.powers.includes(p.key))}
          onChange=${(v) => call("modes.coop_char_power", i, p.key, v)} />`)}
      </div>` : null;
    })}
    <div class="row" style="gap:8px;margin-top:6px">
      <${Field} value=${r.header || ""} sm maxLength=${ch.max_header || 96} width=${320} placeholder=${r.words || "Header: the badge's words (optional)"}
        title="The badge on its cards. Empty: its powers' words (a set ability's name when the list is exactly one)."
        onCommit=${(v) => { if (v !== (r.header || "")) call("modes.coop_char_set", i, null, null, null, v); }} />
      <${Select} sm value="" options=${opts} width=${260}
        title="Put one of the set abilities' powers on this character in place of its list, as a starting point (No powers: an empty list)."
        onChange=${(v) => { if (v) call("modes.coop_char_set", i, null, v === "-" ? "" : v); }} />
    </div>
  </div>`;
  const row = (r, i) => html`<div class="modes-coop-ch-row" key=${i + ":" + r.name}>
    <span class="small dim">${i + 1}</span>
    <div class="modes-coop-ch-names">
    <${Field} value=${r.name} sm maxLength=${ch.max_name || 27} width=${210}
      title="Its name, as the machine's top line shows it at the pick."
      onCommit=${(v) => { if (v !== r.name) call("modes.coop_char_set", i, v, null); }} />
    <${Field} value=${r.sub || ""} sm maxLength=${ch.max_sub || 48} width=${210} placeholder="Sub header (optional)"
      title="A smaller line under its name on its pick and award cards, as typed (Godzilla vs Biollante (1989)). Empty: none."
      onCommit=${(v) => { if (v !== (r.sub || "")) call("modes.coop_char_set", i, null, null, v); }} />
    </div>
    <${Button} size="sm" kind=${open === i ? "" : "ghost"} icon="list" onClick=${() => setOpen(open === i ? -1 : i)}
      title=${r.lost ? "None of this character's powers is on this game yet." : "Its powers: what it does while its teammate is up. Click to tick them on and off."}>
      ${r.powers.length ? `Powers (${r.powers.length})` : "Powers…"}<//>
    <span class=${cx("small wrap modes-coop-ch-does", r.lost ? "warn-ink" : "dim")}>${r.lost ? "Its powers are not on this game yet: none on the card."
      : r.powers.length ? html`<b>${r.words}</b> ${r.line}${r.missing.length ? html` <span class="warn-ink">(${r.missing.length} not on this game, left off the card)</span>` : null}`
      : "Plays as the game always does."}</span>
    <span class="row" style="gap:4px">
      <${Well} value=${r.colour || (ch.look ? ch.look.colours[0].value : "")}
        title=${r.colour ? "Its own frame colour on its cards: pick another." : "The frame colour on its cards (the look's): pick one of its own."}
        onPick=${(v) => call("modes.coop_char_colour", i, v)} />
      ${r.colour ? html`<${Button} size="xs" kind="ghost" icon="x" title="The look's frame colour again." onClick=${() => call("modes.coop_char_colour", i, "")} />` : null}
      <${Button} size="xs" kind="ghost" icon="image" onClick=${() => call("modes.coop_char_picture", i, false)}
        title=${r.picture ? "Its picture on the pick screen: choose another." : "Choose a picture of your own for its pick screen (without one it gets a panel with its name)."}>${r.picture ? "Picture ✓" : "Picture…"}<//>
      ${r.picture ? html`<${Button} size="xs" kind="ghost" icon="x" title="Back to the panel with its name." onClick=${() => call("modes.coop_char_picture", i, true)} />` : null}
      <${Button} size="xs" kind="ghost" icon="film" onClick=${() => call("modes.coop_char_video", i, false)}
        title=${r.video ? "Its video, playing in its picture's frame on the pick screen: choose another." : "A video of your own, played over and over in its picture's frame while the pick is on it."}>${r.video ? "Video ✓" : "Video…"}<//>
      ${r.video ? html`<${Button} size="xs" kind="ghost" icon="x" title="No video: its picture again." onClick=${() => call("modes.coop_char_video", i, true)} />` : null}
      <${Button} size="xs" kind="ghost" icon="eye" title="Show its pick screen in the preview below." onClick=${() => call("modes.coop_chars_show", i)} />
      <${Button} size="xs" kind="ghost" icon="trash" title="Take this character out." onClick=${() => call("modes.coop_char_remove", i)} />
    </span>
  </div>`;
  return html`<${Modal} title="Co-op characters" icon="list" wide onClose=${onClose}
    footer=${html`<span class="small muted">${ch.note}</span><span class="grow"></span>
      ${ch.preset ? html`<${Button} size="sm" kind="ghost" onClick=${() => call("modes.coop_chars_preset")}
        title=${`The app's set for ${ch.preset}, in place of these: a character for each ability, named after the game's eras. Rename them as you like.`}>Load ${ch.preset}'s set<//>` : null}
      ${rows.length ? html`<${Button} size="sm" kind="ghost" icon="image" onClick=${() => call("modes.coop_chars_pictures")}
        title="A folder of pictures, one per character, named after it (godzilla_1954.png): each becomes that character's picture.">Pictures from folder…<//>` : null}
      <${Button} size="sm" icon="plus" disabled=${rows.length >= (ch.max || 16)} onClick=${() => call("modes.coop_char_add")}
        title=${`One more character (up to ${ch.max || 16}).`}>Add<//>
      <${Button} onClick=${onClose}>Close<//>`}>
    <div class="small dim wrap">${s.coop_chars_tip}</div>
    ${ch.why ? html`<${Note} kind="info">${ch.why}<//>` : null}
    <div class="row" style="margin-top:8px">
      <${Check} checked=${ch.pick} label="Each teammate picks a character at their first ball"
        disabled=${!rows.length} title="Off: the card plays co-op as before, with no characters."
        onChange=${(v) => call("modes.coop_chars_pick", v)} />
      <span class="small dim" style="margin-left:16px">Time to pick</span>
      <${Select} sm value=${String(ch.time ?? 30)} width=${130} disabled=${!rows.length || !ch.pick}
        options=${(ch.times || [30]).map((t) => ({ value: String(t), label: t ? `${t} seconds` : "No time limit" }))}
        title="How long each teammate has to pick; the machine counts the seconds down, and when they run out the one shown is taken. No time limit: the pick waits for the Action button."
        onChange=${(v) => call("modes.coop_chars_time", Number(v))} />
      <span class="grow"></span>
      <${Button} size="sm" kind=${looking ? "" : "ghost"} icon="image" disabled=${!rows.length || !ch.look}
        title="The pick screen's look: its title, the colour of each of its words, a background picture."
        onClick=${() => setLooking(!looking)}>Look…<//>
    </div>
    ${looking && ch.look ? html`<${CoopLook} look=${ch.look} />` : null}
    ${ch.preview ? html`<div class="modes-coop-ch-pv">
      <img src=${mediaUrl(ch.preview.path) + "&v=" + ch.preview.seq} alt="The machine's pick screen" />
      <span class="small dim wrap">What the machine shows while the pick is on ${ch.preview.at < rows.length ? rows[ch.preview.at].name : "RANDOM"}. Give each character a picture of your own with Picture... or a video with Video..., the screen colours and a background with Look..., and see it here; Write puts the cards on the machine.</span>
    </div>` : null}
    ${ch.refused ? html`<${Note} kind="warn">${ch.refused}<//>` : null}
    ${ch.videos && rows.some((r) => r.video) ? html`<${Note} kind="info">${ch.videos}<//>` : null}
    ${rows.length ? html`<div class="modes-coop-ch" style="max-height:min(50vh, 520px)">${rows.map((r, i) => html`${row(r, i)}${open === i ? powersOf(r, i) : null}`)}</div>`
      : html`<div class="small muted" style="margin-top:8px">No characters yet: press Add${ch.preset ? `, or load ${ch.preset}'s set` : ""}.</div>`}
  <//>`;
}
