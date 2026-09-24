// Modes: make a game mode of your own, saved in the card project and put on the card by
// Write (item 127). The web port of the Tk ModesPanel in the audit's re-hang design:
// one list of both kinds (with the game's own modes as a group below them, each with a
// page of its numbers, the shots that count as its own and its rewrite in C), a five-page
// editor, a code mode's Code/Assets panes, every game mode's numbers in one dialog too,
// the video cutter, a pinned Try it footer, and the progress of reading a card's game
// build the first time the tab sees it. Everything that makes a mode is under New; the
// page head carries no buttons, and every tool sits on the page of the mode it changes.
//
// Python (tabs/modes.py) owns every decision; this page renders modes.* and edits the
// form through ui.set("modes", "f:<key>" | "shot:<name>" | "award:<name>", value).

import { html, useEffect, useRef, useState, Button, Field, Select, Check, Radio, Chip, Note, Empty,
         InfoBadge, Icon, Progress, tip, cx, call, setField, openMenu, mediaUrl, fmtClock } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { StockDialog, FilmDialog, NewCodeDialog, ClipDialog, PlayButton } from "./modes_dialogs.js";

export const css = true;

// the Tk tab's tooltips, word for word
const T = {
  name: "What the mode is called. It is the title on its screen and clip unless you give those their own.",
  startShot: "The shot that starts the mode.",
  itsShot: "The mode starts when its shot is made that many times in one ball.",
  startEvent: "Something the game itself does: a ball starting, a multiball starting, the skill shot being made. The mode starts the moment the game does it.",
  drain: "The mode ends when its time runs out, or sooner if the ball drains.",
  clock: "The mode keeps running into the next ball until its time runs out.",
  endEvent: "The mode ends when the game does this, when its time runs out, or when the ball drains, whichever comes first.",
  award: "Points for the first scoring shot. The second pays twice this, the third three times, and so on. The game's own scoring is used, so its playfield multiplier applies. Advanced can change this: Award ladder Fixed pays every shot once, and Points per shot gives a shot its own points.",
  raw: "Replace the colour sweep with light commands of your own, in the game's own light language. Leave both empty to use the colour above.",
  screenTitle: "The title on the panel. Empty uses the mode's name. Under it, the mode writes what each shot paid, and the total at the end.",
  clipTitle: "The title card's words, over the panel colour with a sweep in the title colour. Empty uses the mode's name.",
  cooldown: "0 = no wait. The wait runs from the moment the mode ends, and carries on through the end of a ball.",
  starts: "Counted for each player. Once a ball starts again on the player's next ball; once a game, and up to N times, start again in the next game.",
  stack: "On: the mode starts whenever its shot is made, even during one of the game's own battles or multiballs. Off: it waits until the game's own battle or multiball ends, and the next start shot after that starts it.",
  lit: "While the mode runs, the insert in front of every shot that scores (and every shot with its own points) shows this colour and pattern, over the game's own light shows; every other insert keeps doing what the game wants. They go back to the game the moment the mode ends. Blink and Pulse repeat about twice a second and every 1.6 s; Chase lights one of them at a time.",
  priority: "How the mode's screen and clip sit among the game's own displays while it runs, on the game's own scale (1-255). At 180 the game's full-screen shot awards wait until the mode ends (on Godzilla: LOOPS and BATTLE IS LIT); its jackpots, multiball and battle starts and the tilt warning still come through, and the mode's screen is back when they end. Higher holds more back (190: starts and jackpots wait too). 0 leaves the game's display order as it is.",
  film: "Cut this mode's clip, its sound or its screen's picture from a video file of your own (a film, an episode, anything): pick the video, a start time and a length (up to 30 seconds), and whether to keep its letterbox or fill the frame. The mode keeps only the cut (clip.mp4, end.wav, art.png), never the video.",
  rising: "The Nth scoring shot pays N times its points: 1x, 2x, 3x...",
  fixed: "Every scoring shot pays its points once.",
  endShot: "A shot that ends the mode at once. It pays first if it is a scoring shot.",
  secondClip: "A clip at the OTHER end from the one under Clip: at the end when that one plays at the start, and the other way round.",
  clip2Title: "The second title card's words. Empty uses the mode's name.",
  callouts: "One of the game's own callouts, by number, when that many seconds are left. Pick names the ones measured to play on this game; the countdown under Sound adds its own.",
  restore: "How long the mode's own screen (Screen, above) shows its total after the mode ends. With no screen of its own this does nothing.",
  tryit: "Try it builds this project's modes as Write puts them on a card (their screens, clips and own sounds, from the card itself) and starts the card in the Emulate tab with them. Then start a game: a mode starts on its shots, or at once with Start mode now. Edits you make while the game runs reach it within a second.",
  ownSoundCost: " A mode's own sound costs about a minute the first time it changes and is reused after that.",
  startNow: "Start the mode open on the left in the running game, without its starting shots. A game must be in play.",
  endNow: "End whichever of this project's modes is running.",
  codeMode: "A mode written in C, for what the form cannot do: a copy of the Mode SDK's template in this project's modes folder. Try it builds it in with the others.",
  cutFilms: "Cut this example's clip, picture, music and calls from your own copy of the films. Pick the folder that holds them; the app keeps only the cuts.",
  countsAs: "A shot of your choosing counts as one of this mode's own while it runs: a Left ramp can reach the battle vs Ebirah as a left spin (its points, and the count down by one). One ramp is one spin, so a ramp standing in for a spinner needs the spinner's count of hits. Saved with this project and put on the card by Write with the modes; with no rows the mode plays as it always did.",
  rewrite: "This mode is compiled into the game. A rewrite is a mode in C of this project whose code runs INSTEAD of this mode's shot handling: which shots, in what order and what they pay is yours, while its start, clock, screens and ending stay the game's own. It starts from the SDK's example for the mode; delete it and the mode plays as it always did.",
  leaveOut: "Build this Try it without the modes' own sounds: the game's own calls play, and the sound bank is not grown (the slow part of a build). A card Written from the project still carries them.",
  pointsFor: (n) => `What ${n} pays instead of the first shot's points. Blank = the usual points. A shot with its own points scores even when it is not ticked under Shots that score.`,
};

const PAGES = [["mode", "Mode"], ["show", "Show"], ["lights", "Lights"], ["sounds", "Sounds"], ["scoring", "Scoring"]];
const PATTERNS = ["Solid", "Blink", "Pulse", "Chase"];
const STATE_WORDS = { preflight: "Preparing", building: "Building", installing: "Installing", starting: "Starting",
                      live: "Live", ended: "Ended", failed: "Failed" };

const setF = (k, v, flush) => setField("modes", "f:" + k, v, { flush: !!flush, delay: 250 });

function useStored(key, init) {
  const [v, setV] = useState(() => { try { return localStorage.getItem(key) || init; } catch (e) { return init; } });
  const put = (x) => { setV(x); try { localStorage.setItem(key, x); } catch (e) { /* private window */ } };
  return [v, put];
}

// ---------------------------------------------------------------- small pieces
function Reason({ text }) {
  if (!text) return null;
  return html`<div class="modes-reason small">${text}</div>`;
}

function Sec({ title, reason, children, extra, tipText }) {
  return html`<section class="modes-sec">
    <div class="modes-sec-hd"><span class="lbl" ...${tip(tipText)}>${title}</span><span class="grow"></span>${extra}</div>
    ${children}
    <${Reason} text=${reason} />
  </section>`;
}

function Swatch({ k, value, disabled, title }) {
  const v = /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : "#000000";
  return html`<label class=${cx("modes-swatch", disabled && "disabled")} ...${tip(title)}>
    <input type="color" value=${v} disabled=${!!disabled} aria-label=${title}
      onInput=${(e) => setF(k, e.target.value)} onChange=${(e) => setF(k, e.target.value, true)} />
    <span class="chip-c" style=${`background:${v}`}></span>
  </label>`;
}

// The Tk tab's ttk.Spinbox: arrows, Up/Down stepping and its from_/to bounds, published by
// Python as modes.spin (key -> [from, to, step]). The bounds only guide the arrows, as a
// Spinbox's did: a typed value out of range is still sent, and the status line's sentence
// says what is wrong with it. A title card's seconds may be a fraction, so its step is
// "any" (the arrows still move it by one).
let SPIN = {};
function Num({ k, value, disabled, width = 64, title }) {
  const b = SPIN[k] || SPIN[k.replace(/_\d+$/, "")] || null;
  return html`<${Field} ns="modes" k=${"f:" + k} value=${value} disabled=${disabled} width=${width} sm title=${title}
    inputCls="num" type=${b ? "number" : "text"} min=${b ? b[0] : undefined} max=${b ? b[1] : undefined}
    step=${b ? (b[2] || 1) : undefined} />`;
}

// ------------------------------------------------------------------ the head
function Head({ s }) {
  const proj = s.project || "";
  const nForm = s.n_form || 0;
  const counts = `${nForm} mode${nForm === 1 ? "" : "s"}${s.n_code ? ` + ${s.n_code} in C` : ""}`;
  const modesDir = proj ? proj.replace(/[\\/]+$/, "").split(/[\\/]/).pop() + (proj.includes("\\") ? "\\" : "/") + "modes" : "";
  // one line: the card's game and version (its full words in the tooltip), the counts, the folder
  const compact = proj && (s.title_label || s.card_label) && (s.title_text || "").startsWith("Card:");
  const r = s.reading || {};
  const readLine = r.state === "done" && r.seconds >= 0 ? `Read ${r.label} in ${(r.seconds || 0).toFixed(1)} s.` : "";
  const headTip = [s.title_text, s.title_port ? "Its port: " + s.title_port : "", readLine, s.project_label].filter(Boolean).join("\n");
  return html`<div class="pagehead modes-head">
    <div class="grow">
      <div class="row" style="gap:8px"><h1 class="h1">Modes</h1><${InfoBadge} text=${s.about} /></div>
      <p class="modes-sub">${!proj ? html`<span>${s.project_label}</span>`
        : compact ? html`<span ...${tip(headTip)}><b>${s.title_label || s.card_label}</b>${s.title_label ? ` · ${s.title_shots} shots` : ""}</span> · ${counts} · <span class="mono" ...${tip(s.project_label)}>${modesDir}</span>`
        : html`<span ...${tip(headTip)}>${s.title_text}</span>${s.title_text ? " · " : ""}${counts} · <span class="mono" ...${tip(s.project_label)}>${modesDir}</span>`}</p>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ reading the card
// The first look at a card's game build reads it on a worker (tabs/modes.py through
// modes_reading.py): a bar for the whole read, the steps as a checklist, and Cancel. A
// read that failed or was stopped says so, with Read again. A finished read shows one
// quiet line (how long it took, and anything the reader wants said).
const READ_STATE = { reading: "Reading", failed: "Could not read", cancelled: "Stopped" };

function ReadingPanel({ r }) {
  if (!r || !r.state) return null;
  if (r.state === "done") return null;          // the head's tooltip says how long; the log has the rest
  const working = r.state === "reading";
  const kind = r.state === "failed" ? "err" : working ? "acc" : "warn";
  return html`<section class="card modes-read" role="status" aria-live="polite">
    <div class="bd modes-read-bd">
      <div class="row modes-read-top">
        <${Chip} kind=${kind} dot>${READ_STATE[r.state] || r.state}<//>
        <span class="modes-read-what"><b>${r.label}</b> <span class="mono small muted">${r.card}</span></span>
        <span class="grow"></span>
        ${working ? html`<span class="mono small muted">${r.pct || 0}%</span><${Elapsed} started=${r.started} />` : null}
        ${working ? html`<${Button} size="sm" kind="danger" icon="x" onClick=${() => call("modes.read_cancel")}
            title="Stop reading. Nothing is kept of a read that was stopped; Read again starts it over.">Cancel<//>`
          : html`<${Button} size="sm" icon="refresh" onClick=${() => call("modes.read_again")}>Read again<//>`}
      </div>
      ${working ? html`<${Progress} pct=${r.pct || 0} />` : null}
      <div class="phases modes-read-steps">
        ${(r.steps || []).map((x) => html`<span key=${x.key} class=${cx("phase", x.state === "done" && "done", x.state === "doing" && "now", x.state === "failed" && "fail")}
            title=${x.state === "done" ? "Done" : x.state === "doing" ? "Now" : x.state === "failed" ? "This step failed" : "Not yet"}>
          ${x.state === "done" ? "✓ " : ""}${x.words}</span>`)}
      </div>
      ${working && r.text ? html`<div class="small dim modes-read-text">${r.text}</div>` : null}
      ${r.state === "failed" && r.error ? html`<div class="small err-ink modes-read-text">${r.error}</div>` : null}
      ${r.state === "cancelled" ? html`<div class="small dim modes-read-text">Stopped before it was done, so this card's game build is not known yet.</div>` : null}
    </div>
  </section>`;
}

// ------------------------------------------------------------------ the list
// New ▾: everything that makes a mode. A blank mode, one from an example, and under
// Advanced a mode written in C (a blank one from the SDK's template, or one of the C
// examples) with the Mode SDK's document. With no project, Mode in C's Blank gives Tk's
// own sentence.
function exampleItems(s) {
  return (s.examples || []).filter((x) => !x.code).map((x) => ({ label: x.name, disabled: x.disabled,
    title: x.name === "KAIJU RUSH" ? "The example that has run on a real machine." : "",
    onClick: () => call("modes.example", x.name) }));
}

function codeItems(s, onNewCode) {
  const code = (s.examples || []).filter((x) => x.code);
  return [
    { label: "Blank mode in C…", icon: "edit", title: s.project && s.no_port ? s.no_port : T.codeMode,
      disabled: !!(s.project && s.no_port),
      onClick: () => (s.project ? onNewCode() : call("modes.new_code_mode", "")) },
    ...(code.length ? [{ sep: true }, { header: "Examples in C" },
      ...code.map((x) => ({ label: x.name, onClick: () => call("modes.code_example", x.name) }))] : []),
    { sep: true },
    { label: "Open MODE_SDK.md", icon: "file", title: s.sdk_doc, onClick: () => call("modes.open_sdk_doc") },
  ];
}

function newMenuItems(s, onNewCode) {
  const ex = exampleItems(s);
  return [
    { label: "Blank mode", icon: "plus", disabled: !s.new_ok, onClick: () => call("modes.new"),
      title: s.new_ok ? "" : (s.cap_text || s.project_label) },
    { label: "From an example", icon: "list", disabled: !s.ex_ok || !ex.length, submenu: ex,
      title: s.ex_ok ? "" : s.ex_tip },
    { sep: true },
    { header: "Advanced" },
    { label: "Mode in C", icon: "edit", submenu: codeItems(s, onNewCode) },
  ];
}

// One row of the list: the person's modes (form, and code with a C pill) and the game's own
// modes (kind "game", with a count of staged changes).
function ListRow({ r, i, selIdx, isSel }) {
  const where = r.kind === "code" ? "modes/" + r.slug + "/" + r.slug + ".c"
    : r.kind === "game" ? "One of the game's own modes: its timers and awards" : "modes/" + r.slug;
  return html`<button type="button" role="option" key=${r.kind + r.slug}
      aria-selected=${isSel(r)} tabindex=${i === Math.max(0, selIdx) ? 0 : -1}
      class=${cx("li", isSel(r) && "sel", r.kind === "game" && "game")}
      onClick=${() => call("modes.select", r.slug, r.kind)}
      ...${tip(where + (r.chip_tip ? "\n" + r.chip_tip : ""))}>
      <span class="ellip">${r.name}</span>
      ${r.kind === "code" ? html`<span class="r pill" title="Written in C">C</span>`
        : r.kind === "game" ? (r.chip ? html`<span class="r chip acc sm">${r.chip}</span>` : null)
        : r.chip === "ready" ? html`<span class="r chip ok sm">ready</span>`
        : r.chip ? html`<span class="r chip warn sm">${r.chip}</span>` : null}
    </button>`;
}

// The game's own modes sit BELOW the person's, folded by default when there are more than
// GAME_FOLD_AT of them (a person's choice to open or fold them is kept in this browser).
const GAME_FOLD_AT = 6;

function ModeList({ s, onNewCode, onAllNumbers }) {
  const [fold, setFold] = useStored("pad.modes.game_fold2", "auto");
  const sel = s.sel || {};
  const allGame = s.game_rows || [];
  const closed = fold === "closed" || (fold === "auto" && allGame.length > GAME_FOLD_AT);
  const folded = closed && sel.kind !== "game";
  const game = folded ? [] : allGame;
  const own = s.rows || [];
  const rows = [...own, ...game];
  const isSel = (r) => sel.slug === r.slug && sel.kind === r.kind;
  const selIdx = rows.findIndex(isSel);
  const listRef = useRef(null);
  useEffect(() => {
    const el = listRef.current && listRef.current.querySelector('[aria-selected="true"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }, [sel.slug, sel.kind, rows.length]);
  // the Tk Listbox: Up/Down (and Home/End) move the selection, and the mode opens
  const onKey = (e) => {
    if (!rows.length || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const last = rows.length - 1;
    const next = e.key === "Home" ? 0 : e.key === "End" ? last
      : e.key === "ArrowDown" ? Math.min(last, selIdx + 1) : Math.max(0, selIdx - 1);
    const opts = e.currentTarget.querySelectorAll('[role="option"]');
    if (opts[next]) opts[next].focus();
    if (next !== selIdx) call("modes.select", rows[next].slug, rows[next].kind);
  };
  return html`<section class="card modes-list">
    <div class="hd"><span class="h2">Modes</span><span class="sp"></span>
      <${Button} kind="primary" size="sm" iconRight="down" onClick=${(e) => openMenu(e.currentTarget, newMenuItems(s, onNewCode))}>New<//></div>
    <div class="bd modes-list-bd">
      ${rows.length || allGame.length ? html`<div class="list" role="listbox" aria-label="Modes in this project" onKeyDown=${onKey} ref=${listRef}>
        ${allGame.length ? html`<div class="modes-list-grp" role="presentation">Yours</div>` : null}
        ${own.map((r, i) => html`<${ListRow} key=${r.kind + r.slug} r=${r} i=${i} selIdx=${selIdx} isSel=${isSel} />`)}
        ${allGame.length && !own.length && s.project ? html`<div class="small muted modes-list-empty">No modes of your own yet.</div>` : null}
        ${allGame.length ? html`<button type="button" class="modes-list-grp" aria-expanded=${!folded}
            title=${(folded ? "Show the game's own modes: their timers and awards" : "Fold the game's own modes away")
              + (s.game_hidden ? `\n${s.game_hidden} more have nothing to change here (the game's own timers and awards dialog lists every number).` : "")}
            onClick=${() => setFold(folded ? "open" : "closed")}>
            <${Icon} name=${folded ? "right" : "down"} /> The game's own (${allGame.length})</button>` : null}
        ${game.map((r, i) => html`<${ListRow} key=${"g" + r.slug} r=${r} i=${i + own.length} selIdx=${selIdx} isSel=${isSel} />`)}
        ${game.length ? html`<button type="button" class="li modes-list-all" onClick=${onAllNumbers}
            ...${tip("Every timer and award of the game's own modes in one table, with All to stock.")}>
            <${Icon} name="list" /> <span>All timers and awards…</span></button>` : null}
      </div>` : s.project ? html`<div class="small muted modes-list-empty">No modes yet.</div>` : null}
    </div>
    <div class="ft modes-list-ft">
      ${s.cap_text ? html`<span class="small muted">${s.cap_text}</span>` : null}
      <div class="row" style="gap:6px">
        <${Button} size="sm" disabled=${!s.dup_ok} onClick=${() => call("modes.duplicate")}>Duplicate<//>
        <${Button} size="sm" kind="ghost" icon="trash" disabled=${!s.del_ok} onClick=${() => call("modes.delete")}>Delete<//>
      </div>
    </div>
  </section>`;
}

// ------------------------------------------------------------------ the pages
function ModePage({ s, f, off, dis, rs }) {
  const prof = s.profile || {};
  const shots = prof.shots || [];
  const on = new Set(s.shots_on || []);
  const events = (prof.events || []).map((x) => ({ value: x, label: x }));
  const withBlank = (list, v) => (!v ? [{ value: "", label: "(choose an event)", disabled: true }, ...list]
    : !list.some((o) => o.value === v) ? [{ value: v, label: v }, ...list] : list);
  const shotOpts = f.start_shot && !shots.includes(f.start_shot)
    ? [{ value: f.start_shot, label: f.start_shot }, ...shots.map((x) => ({ value: x, label: x }))]
    : shots.map((x) => ({ value: x, label: x }));
  const evOff = off || dis.events;
  return html`<div class="modes-grid2">
      <div class="stack">
        <label class="lbl" for="m-name">Name</label>
        <${Field} id="m-name" ns="modes" k="f:name" value=${f.name} disabled=${off} title=${T.name} />
      </div>
      <div class="stack">
        <span class="lbl">Runs for</span>
        <div class="row"><${Num} k="seconds" value=${f.seconds} disabled=${off} width=${84} /><span class="dim">seconds</span></div>
      </div>
      <${Sec} title="Starts on" reason=${rs.events}>
        <div class="row wrap">
          <${Radio} name="m-starts" value="shot" label="its shot" checked=${f.starts_kind !== "event"} disabled=${off} title=${T.itsShot} onChange=${(v) => setF("starts_kind", v, true)} />
          <${Select} value=${f.start_shot} options=${shotOpts} ns="modes" k="f:start_shot" disabled=${off || !shots.length} width=${180} title=${T.startShot} />
          <span class="row nw" style="gap:8px"><${Num} k="start_count" value=${f.start_count} disabled=${off} width=${64} />
          <span class="dim nw">times in one ball</span></span>
        </div>
        <div class="row wrap">
          <${Radio} name="m-starts" value="event" label="an event" checked=${f.starts_kind === "event"} disabled=${evOff} onChange=${(v) => setF("starts_kind", v, true)} />
          <${Select} value=${f.start_event} options=${withBlank(events, f.start_event)} ns="modes" k="f:start_event" disabled=${evOff} width=${230} title=${T.startEvent} />
        </div>
      <//>
      <${Sec} title="Ends on">
        <div class="row wrap">
          <${Radio} name="m-ends" value="drain" label="its clock, or the ball draining" checked=${f.ends_kind === "drain"} disabled=${off} title=${T.drain} onChange=${(v) => setF("ends_kind", v, true)} />
          <${Radio} name="m-ends" value="clock" label="its clock only" checked=${f.ends_kind === "clock"} disabled=${off} title=${T.clock} onChange=${(v) => setF("ends_kind", v, true)} />
        </div>
        <div class="row wrap">
          <${Radio} name="m-ends" value="event" label="an event" checked=${f.ends_kind === "event"} disabled=${evOff} onChange=${(v) => setF("ends_kind", v, true)} />
          <${Select} value=${f.end_event} options=${withBlank(events, f.end_event)} ns="modes" k="f:end_event" disabled=${evOff} width=${230} title=${T.endEvent} />
        </div>
      <//>
      <${Sec} title="How often it can start" tipText=${T.starts}>
        <div class="row wrap" style="gap:4px 16px">
          ${[["once_per_game", "once a game"], ["once_per_ball", "once a ball"], ["unlimited", "any number of times"]].map(([v, l]) =>
            html`<${Radio} name="m-often" value=${v} label=${l} checked=${f.starts_policy === v} disabled=${off} onChange=${(x) => setF("starts_policy", x, true)} />`)}
        </div>
        <div class="row wrap">
          <${Radio} name="m-often" value="count" label="up to" checked=${f.starts_policy === "count"} disabled=${off} onChange=${(x) => setF("starts_policy", x, true)} />
          <${Num} k="starts_count" value=${f.starts_count} disabled=${off} width=${64} /><span class="dim nw">times a game</span>
        </div>
        <div class="row">
          <span class="dim nw">Wait</span><${Num} k="cooldown" value=${f.cooldown} disabled=${off} width=${76} title=${T.cooldown} />
          <span class="dim">seconds after it ends before it can start again</span>
        </div>
        <div class="small muted">${s.starts_words}</div>
      <//>
      <${Sec} title="The game's own modes" reason=${rs.stack}>
        <${Check} label="Can run during the game's own modes" checked=${f.stack} disabled=${off || dis.stack} title=${T.stack} ns="modes" k="f:stack" />
      <//>
    </div>
    <${Sec} title="Shots that score while it runs"
      extra=${html`<span class="muted small">${on.size} of ${shots.length}</span>
        <${Button} size="xs" kind="ghost" disabled=${off || !shots.length} onClick=${() => call("modes.set_shots", shots)}>All<//>
        <${Button} size="xs" kind="ghost" disabled=${off || !shots.length} onClick=${() => call("modes.set_shots", [])}>None<//>`}>
      ${shots.length ? html`<div class="modes-shots">
        ${shots.map((n) => html`<${Check} key=${n} label=${n} checked=${on.has(n)} disabled=${off}
            onChange=${(v) => setField("modes", "shot:" + n, v, { flush: true })} />`)}
      </div>` : html`<div class="small muted">${s.shots_text || "(no shots)"}</div>`}
    <//>`;
}

function ShowPage({ s, f, off, dis, rs, labels, files, showClip }) {
  if (dis.show_order) {
    return html`<div class="modes-show-off"><${Reason} text=${rs.show_all} /></div>`;
  }
  const pv = s.preview;
  const scrOff = off || dis.screen;
  const clipOff = off || dis.clip;
  const c2Off = off || dis.clip_both;
  const radio = (name, key, v, label, extra = {}) => html`<${Radio} name=${name} value=${v} label=${label}
    checked=${f[key] === v} disabled=${extra.disabled} title=${extra.title}
    onChange=${(x) => (extra.choose ? call("modes.choose", extra.choose) : setF(key, x, true))} />`;
  return html`<div class="modes-grid2">
    <${Sec} title="Screen" reason=${rs.screen}>
      <${Check} label="Show a screen of its own while it runs" checked=${f.screen} disabled=${scrOff} ns="modes" k="f:screen" />
      <div class="modes-kv">
        <span class="lbl">Title</span>
        <${Field} ns="modes" k="f:screen_title" value=${f.screen_title} disabled=${scrOff} title=${T.screenTitle} placeholder=${f.name} />
        <span class="lbl">Picture</span>
        <div class="row wrap">
          ${radio("m-art", "art_mode", "panel", "A panel in these colours", { disabled: scrOff })}
          ${radio("m-art", "art_mode", "file", "My picture…", { disabled: scrOff, choose: "art" })}
        </div>
        <span class="lbl">Colours</span>
        <div class="row">
          <span class="dim">Panel</span><${Swatch} k="panel_color" value=${f.panel_color} disabled=${scrOff} title="Panel colour" />
          <span class="dim" style="margin-left:10px">Title</span><${Swatch} k="title_color" value=${f.title_color} disabled=${scrOff} title="Title colour" />
        </div>
      </div>
      ${labels.art ? html`<div class="row small"><span class="dim">${labels.art}</span>
        ${f.art_mode === "file" && !scrOff ? html`<${Button} size="xs" kind="ghost" onClick=${() => call("modes.choose", "art")}>Change…<//>` : null}</div>` : null}
      <div class="thumb modes-preview">${pv && pv.path ? html`<img src=${mediaUrl(pv.path)} alt="The mode's screen" />`
        : pv && pv.text ? html`<span class="small">${pv.text}</span>` : html`<span class="small muted">${f.screen ? "" : "No screen of its own"}</span>`}</div>
    <//>
    <div class="stack" style="gap:14px">
      <${Sec} title="Clip" reason=${rs.clip}>
        <div class="row wrap">
          ${radio("m-clip", "clip", "none", "None", { disabled: clipOff })}
          ${radio("m-clip", "clip", "title", "A title card", { disabled: clipOff })}
          ${radio("m-clip", "clip", "file", "My video…", { disabled: clipOff, choose: "clip" })}
        </div>
        <div class="row">
          <span class="lbl nw">Title card text</span>
          <${Field} ns="modes" k="f:clip_title" value=${f.clip_title} disabled=${clipOff} title=${T.clipTitle} cls="grow" placeholder=${f.name} />
          <${Num} k="clip_seconds" value=${f.clip_seconds} disabled=${clipOff} width=${64} /><span class="dim">seconds</span>
        </div>
        ${labels.clip ? html`<div class="row small"><span class="dim">${labels.clip}</span>
          ${files.clip ? html`<${Button} size="xs" kind="ghost" icon="play" onClick=${() => showClip(files.clip, "Clip")}>Play<//>` : null}
          ${!clipOff ? html`<${Button} size="xs" kind="ghost" onClick=${() => call("modes.choose", "clip")}>Change…<//>` : null}</div>` : null}
        <div class="row wrap">
          <span class="lbl">Plays</span>
          ${radio("m-when", "clip_when", "start", "When it starts", { disabled: clipOff })}
          ${radio("m-when", "clip_when", "end", "When it ends", { disabled: clipOff })}
        </div>
      <//>
      <${Sec} title="Second clip" tipText=${T.secondClip} reason=${rs.clip_both}>
        <div class="row wrap">
          ${[["none", "None"], ["same", "The same clip"], ["title", "A title card"]].map(([v, l]) => radio("m-clip2", "clip_both", v, l, { disabled: c2Off }))}
          ${radio("m-clip2", "clip_both", "file", "My video…", { disabled: c2Off, choose: "clip2" })}
        </div>
        <div class="row">
          <span class="lbl nw">Its title</span>
          <${Field} ns="modes" k="f:clip_both_title" value=${f.clip_both_title} disabled=${c2Off} title=${T.clip2Title} cls="grow" />
          <${Num} k="clip_both_seconds" value=${f.clip_both_seconds} disabled=${c2Off} width=${64} /><span class="dim">seconds</span>
        </div>
        ${labels.clip2 ? html`<div class="row small"><span class="dim">${labels.clip2}</span>
          ${files.clip2 ? html`<${Button} size="xs" kind="ghost" icon="play" onClick=${() => showClip(files.clip2, "Second clip")}>Play<//>` : null}
          ${f.clip_both === "file" && !c2Off ? html`<${Button} size="xs" kind="ghost" onClick=${() => call("modes.choose", "clip2")}>Change…<//>` : null}</div>` : null}
      <//>
      <${Sec} title="On the screen">
        <div class="row wrap">
          <span class="lbl nw" ...${tip(T.restore)}>Screen stays up</span>
          <${Num} k="restore_after" value=${f.restore_after} disabled=${off || dis.show_order} width=${64} title=${T.restore} />
          <span class="dim">seconds after it ends</span>
        </div>
        <div class="row wrap">
          <span class="lbl nw">Display priority</span>
          <${Num} k="priority" value=${f.priority} disabled=${off || dis.show_order} width=${72} title=${T.priority} />
          <span class="small muted">0 = none, 180 = over the game's shot awards</span>
        </div>
      <//>
      <${FilmSec} f=${f} off=${off} dis=${dis} rs=${rs} labels=${labels} />
    </div>
  </div>`;
}

function FilmSec({ off, dis, rs, labels, only }) {
  const btn = (take, text) => html`<${Button} size="sm" icon="film" disabled=${off || dis["film_" + take]} title=${T.film}
    onClick=${() => call("modes.film_open", take)}>${text}<//>`;
  return html`<${Sec} title="Cut from a video" tipText=${T.film} reason=${rs.film}>
    <div class="row wrap">
      <span class="dim">From a video file:</span>
      ${!only || only === "clip" ? btn("clip", "Clip…") : null}
      ${!only || only === "sound" ? btn("sound", "Sound…") : null}
      ${!only || only === "still" ? btn("still", "Picture…") : null}
    </div>
    <div class="small muted wrap">${labels.film || ""}</div>
  <//>`;
}

function LightsPage({ s, f, off, dis, rs }) {
  const lOff = off || dis.lights;
  return html`<div class="modes-grid2">
    <${Sec} title="Sweep the playfield" reason=${rs.lights}>
      <${Check} label="Sweep the playfield in a colour while it runs" checked=${f.lights} disabled=${lOff} ns="modes" k="f:lights" />
      <div class="row"><span class="lbl">Colour</span><${Swatch} k="light_color" value=${f.light_color} disabled=${lOff} title="Light colour" />
        <span class="mono small muted">${f.light_color}</span></div>
      <${Check} label="Advanced" checked=${f.advanced} disabled=${lOff} title=${T.raw} ns="modes" k="f:advanced" />
      ${f.advanced ? html`<div class="modes-kv">
        <span class="lbl">On command</span><${Field} ns="modes" k="f:light_on_raw" value=${f.light_on_raw} disabled=${lOff} mono />
        <span class="lbl">Off command</span><${Field} ns="modes" k="f:light_off_raw" value=${f.light_off_raw} disabled=${lOff} mono />
      </div>` : null}
    <//>
    <${Sec} title="The shots that score" reason=${rs.lit_shots}>
      <div class="row wrap">
        <${Check} label="Light the shots that score" checked=${f.light_shots_on} disabled=${off || dis.lit_shots} title=${T.lit} ns="modes" k="f:light_shots_on" />
        <${Swatch} k="light_shots_color" value=${f.light_shots_color} disabled=${off || dis.lit_shots} title="Colour of the lit shots" />
        <${Select} value=${f.light_shots_pattern} options=${PATTERNS.includes(f.light_shots_pattern) ? PATTERNS : [f.light_shots_pattern, ...PATTERNS]}
          ns="modes" k="f:light_shots_pattern" disabled=${off || dis.lit_shots} width=${110} sm />
      </div>
      ${dis.lit_shots ? null : html`<div class="small muted wrap">${T.lit}</div>`}
    <//>
  </div>`;
}

function SoundsPage({ s, f, off, dis, rs, labels, files }) {
  const prof = s.profile || {};
  const choices = prof.callouts || [];
  const pickMenu = (e, i) => openMenu(e.currentTarget, choices.length
    ? choices.map((c) => ({ label: c.label, onClick: () => setF("callout_id_" + i, String(c.number), true) }))
    : [{ label: prof.callouts_none || "(no callouts measured: type an id)", disabled: true }]);
  const own = [["sound_start", "start_sound_mode", "When it starts"], ["sound_shot", "shot_sound_mode", "On a scoring shot"],
               ["music", "music_mode", "Music underneath"]];
  return html`<div class="modes-grid2">
    <div class="stack" style="gap:14px">
      <${Sec} title="Sound" reason=${rs.sound}>
        <${Check} label="Count down the last seconds in the game's own voice" checked=${f.countdown} disabled=${off || dis.countdown} ns="modes" k="f:countdown" />
        <div class="row wrap">
          <span class="lbl nw">When time is up</span>
          <${Radio} name="m-end" value="game" label="The game's own call" checked=${f.end_mode === "game"} disabled=${off || dis.end_game} onChange=${(v) => setF("end_mode", v, true)} />
          <${Radio} name="m-end" value="file" label="My sound…" checked=${f.end_mode === "file"} disabled=${off || dis.own_sound} onChange=${() => call("modes.choose", "end")} />
        </div>
        ${labels.sound ? html`<div class="row small"><span class="dim">${labels.sound}</span><${PlayButton} path=${files.end} />
          ${f.end_mode === "file" && !(off || dis.own_sound) ? html`<${Button} size="xs" kind="ghost" onClick=${() => call("modes.choose", "end")}>Change…<//>` : null}</div>` : null}
        ${rs.sound_unheard ? html`<div class="modes-reason small">${rs.sound_unheard}</div>` : null}
      <//>
      <${Sec} title="Sounds of its own" reason=${rs.own_extra}>
        <div class="modes-kv top">
          ${own.map(([attr, mv, words]) => html`
            <span class="lbl">${words}</span>
            <div class="stack" style="gap:2px">
              <div class="row wrap">
                <${Radio} name=${"m-" + attr} value="none" label="Nothing" checked=${f[mv] !== "file"} disabled=${off || dis.own_extra} onChange=${(v) => setF(mv, v, true)} />
                <${Radio} name=${"m-" + attr} value="file" label="My sound…" checked=${f[mv] === "file"} disabled=${off || dis.own_extra} onChange=${() => call("modes.choose", attr)} />
              </div>
              ${attr === "sound_shot" ? html`<div class="row"><span class="dim nw">on every</span><${Num} k="sound_shot_every" value=${f.sound_shot_every} disabled=${off || dis.own_extra} width=${64} /><span class="dim nw">scoring shot(s)</span></div>` : null}
              ${labels[attr] ? html`<div class="row small"><span class="dim">${labels[attr]}</span><${PlayButton} path=${files[attr]} />
                ${!(off || dis.own_extra) ? html`<${Button} size="xs" kind="ghost" onClick=${() => call("modes.choose", attr)}>Change…<//>` : null}</div>` : null}
            </div>`)}
        </div>
        ${dis.own_extra ? null : html`<div class="small muted wrap">Each plays in place of a stock call the game never makes. Write puts them on the card, and names any it cannot carry.</div>`}
      <//>
    </div>
    <div class="stack" style="gap:14px">
      <${Sec} title="Callouts" tipText=${T.callouts}>
        ${[0, 1, 2, 3].map((i) => html`<div class="row" key=${i}>
          <span class="dim">at</span><${Num} k=${"callout_secs_" + i} value=${f["callout_secs_" + i]} disabled=${off} width=${68} />
          <span class="dim nw">s left, callout</span>
          <${Field} ns="modes" k=${"f:callout_id_" + i} value=${f["callout_id_" + i]} disabled=${off} width=${84} sm mono />
          <${Button} size="xs" iconRight="down" disabled=${off} onClick=${(e) => pickMenu(e, i)}>Pick<//>
        </div>`)}
        <div class="small muted wrap">${T.callouts}</div>
      <//>
      <${FilmSec} off=${off} dis=${dis} rs=${rs} labels=${labels} only="sound" />
    </div>
  </div>`;
}

function ScoringPage({ s, f, off }) {
  const prof = s.profile || {};
  const shots = prof.shots || [];
  const awards = s.awards || {};
  const ends = (prof.end_shots || ["(only when time runs out)"]).map((x) => ({ value: x, label: x }));
  const endOpts = f.end_shot && !ends.some((o) => o.value === f.end_shot) ? [{ value: f.end_shot, label: f.end_shot }, ...ends] : ends;
  return html`<div class="modes-grid2">
    <div class="stack" style="gap:14px">
      <${Sec} title="First shot pays">
        <div class="row"><${Field} ns="modes" k="f:award" value=${f.award} disabled=${off} width=${160} mono title=${T.award} /><span class="dim">points</span></div>
        <div class="small muted wrap">${T.award}</div>
      <//>
      <${Sec} title="Award ladder">
        <div class="row wrap">
          <${Radio} name="m-ladder" value="rising" label="Rising" checked=${f.award_ladder === "rising"} disabled=${off} title=${T.rising} onChange=${(v) => setF("award_ladder", v, true)} />
          <${Radio} name="m-ladder" value="fixed" label="Fixed" checked=${f.award_ladder === "fixed"} disabled=${off} title=${T.fixed} onChange=${(v) => setF("award_ladder", v, true)} />
        </div>
      <//>
      <${Sec} title="Ends early when hit">
        <${Select} value=${f.end_shot} options=${endOpts} ns="modes" k="f:end_shot" disabled=${off} width=${260} title=${T.endShot} />
      <//>
    </div>
    <${Sec} title="Points per shot">
      ${shots.length ? html`<div class="modes-points">
        ${shots.map((n) => html`<label class="lbl ellip" key=${"l" + n} title=${n}>${n}</label>
          <${Field} key=${"f" + n} ns="modes" k=${"award:" + n} value=${awards[n] || ""} disabled=${off} sm mono placeholder="usual" title=${T.pointsFor(n)} />`)}
      </div>` : html`<div class="small muted">(no shots)</div>`}
    <//>
  </div>`;
}

// ------------------------------------------------------------------ the editor
function Editor({ s, showClip }) {
  const [page, setPage] = useStored("pad.modes.page", "mode");
  const f = s.form || {};
  const off = !s.editor_on;
  const dis = s.dis || {};
  const rs = s.reasons || {};
  const labels = s.labels || {};
  const files = s.files || {};
  const ready = !!s.ready;
  const fixPages = new Set(s.fix_pages || []);
  const saveWords = s.no_port ? "" : s.save_state === "editing" ? "Saving…"
    : s.save_state === "saved" ? (s.write_waits ? "Saved · Write carries it after a Try it" : "Saved · put on the card by Write") : "";
  const offPages = new Set(dis.show_order ? ["show"] : []);
  const props = { s, f, off, dis, rs, labels, files, showClip };
  const P = { mode: ModePage, show: ShowPage, lights: LightsPage, sounds: SoundsPage, scoring: ScoringPage }[page] || ModePage;
  return html`<section class="card modes-editor">
    <div class="hd">
      <span class="h2 ellip">${f.name || "—"}</span>
      ${s.status ? html`<span class=${cx("chip", ready ? "ok" : "warn")}><span class="dot"></span>${ready ? "Ready to build" : s.no_port ? "Read-only" : "To fix"}</span>` : null}
      <span class="sp"></span>
      <span class="small muted">${saveWords}</span>
    </div>
    ${s.status && s.status !== "Ready to build." ? html`<div class=${cx("modes-status", s.no_port || ready ? "info" : "warn")} role="status">${s.status}</div>` : null}
    <div class="pages" role="tablist">
      ${PAGES.map(([k, l]) => html`<button type="button" role="tab" aria-selected=${page === k} class=${cx(page === k && "on", offPages.has(k) && "off")} onClick=${() => setPage(k)}
        ...${tip(fixPages.has(k) ? "What the line above says to fix is on this page." : offPages.has(k) ? "Nothing on this page works on this game yet: the page says why." : "")}>${l}${fixPages.has(k) ? html`<span class="m" aria-label="to fix">•</span>` : null}</button>`)}
    </div>
    <div class="bd modes-editor-bd"><${P} ...${props} /></div>
  </section>`;
}

function CodePane({ s }) {
  const [page, setPage] = useStored("pad.modes.codepage", "code");
  const c = s.code || {};
  const ready = c.status === "Ready to build.";
  return html`<section class="card modes-editor">
    <div class="hd">
      <span class="h2 ellip">${c.name}</span><span class="pill" title="Written in C">C</span>
      ${c.status ? html`<span class=${cx("chip", ready ? "ok" : "warn")}><span class="dot"></span>${ready ? "Ready to build" : "To fix"}</span>` : null}
      <span class="sp"></span><span class="small muted">A mode written in C</span>
    </div>
    ${c.status && !ready ? html`<div class="modes-status warn">${c.status}</div>` : null}
    ${c.error ? html`<div class="modes-status warn">${c.error}</div>` : null}
    ${c.needs_films ? html`<div class="modes-status warn row modes-films" role="status">
        <span class="grow">This example's clip, picture and music are cut from ${c.needs_films}, which can't ship with the app. Until then it plays the game's own sounds on a plain panel.</span>
        <${Button} size="sm" icon="film" disabled=${!s.cut_ok} title=${T.cutFilms + (c.needs_files ? "\nIt looks for: " + c.needs_files : "")}
          onClick=${() => call("modes.cut_films", c.slug)}>Choose your films folder…<//>
      </div>` : null}
    <div class="pages" role="tablist">
      ${[["code", "Code"], ["assets", "Assets"]].map(([k, l]) => html`<button type="button" role="tab" aria-selected=${page === k} class=${page === k ? "on" : ""} onClick=${() => setPage(k)}>${l}</button>`)}
    </div>
    <div class="bd modes-editor-bd">
      ${page === "code" ? html`
        <div class="kv">
          <span class="k">Source</span><span class="mono small ellip" title=${c.source}>${c.source}</span>
          <span class="k">Test trigger</span><span class="mono small">${c.trigger || "(none: its folder name is not a trigger name; use letters, digits and _)"}</span>
          <span class="k">Summary</span><span class="small">${c.summary || ""}</span>
        </div>
        <div class="row wrap">
          <${Button} icon="edit" onClick=${() => call("modes.open_code")}>Open ${c.slug}.c<//>
          <${Button} icon="file" onClick=${() => call("modes.open_sdk_doc")}>Open MODE_SDK.md<//>
        </div>
        <${Note}>${s.code_words}<//>
        <div class="small muted wrap">${T.codeMode}</div>`
      : html`
        <div class="kv">
          <span class="k">Runs for</span><span>${c.seconds != null ? c.seconds + " seconds" : ""}</span>
          <span class="k">Screen</span><span>${c.screen ? (c.screen_art ? "its own, with its picture " + c.screen_art : "its own panel") : "none"}
            ${c.screen && !c.screen_art ? html` <span class="swatch" style=${`background:${c.panel_color};width:14px;height:14px;vertical-align:-2px`}></span> <span class="swatch" style=${`background:${c.title_color};width:14px;height:14px;vertical-align:-2px`}></span>` : null}</span>
          <span class="k">Clip</span><span class="row">${c.clip || "none"}${c.files && c.files.clip ? html`<${Button} size="xs" kind="ghost" icon="play" onClick=${() => s._showClip(c.files.clip, c.name)}>Play<//>` : null}</span>
          <span class="k">Music</span><span class="row">${c.music || "none"}<${PlayButton} path=${c.files && c.files.music} /></span>
          <span class="k">Film recipe</span><span>${c.recipe || "none"}</span>
        </div>
        ${c.files && c.files.art ? html`<div class="thumb modes-preview"><img src=${mediaUrl(c.files.art)} alt="The mode's picture" /></div>` : null}
        ${(c.calls || []).length ? html`<div class="stack" style="gap:2px"><span class="lbl">Calls</span>
          ${c.calls.map((x) => html`<div class="row small" key=${x.cue}><span class="mono">${x.cue}</span><span class="dim">${x.wav}</span><span class="muted">priority ${x.priority}</span><${PlayButton} path=${x.path} /></div>`)}</div>` : null}
        ${c.describe ? html`<div class="small muted wrap">${c.describe}</div>` : null}`}
    </div>
  </section>`;
}

// ------------------------------------------------------------------ one of the game's own modes
// Its numbers (timer, shot counts, awards), each with the game's own value, a new value,
// Set and Stock. A number the app cannot change is greyed with the reason. The same
// backend as "The game's own timers and awards" (stock_modes stage / unstage; an operator
// setting is staged for the Defaults tab too).
function GameRow({ r }) {
  const [val, setVal] = useState(r.current || "");
  useEffect(() => { setVal(r.current || ""); }, [r.current, r.key]);
  const same = String(val).replace(/[,\s]/g, "") === String(r.current || "").replace(/[,\s]/g, "");
  const set = () => { if (String(val).trim() && !same) call("modes.game_set", r.key, val); };
  return html`<div class=${cx("modes-gm-row", r.readonly && "readonly", r.changed && "changed")}>
    <div class="modes-gm-what">
      <span class="lbl">${r.number}</span>
      <span class="small muted" ...${tip(r.hint || r.where)}>${r.where}</span>
    </div>
    <div class="modes-gm-stock small"><span class="dim">Stock</span> <span class="mono">${r.stock}</span></div>
    ${r.readonly ? html`<div class="modes-gm-why small" ...${tip(r.hint)}>${r.why}</div>`
      : html`<div class="row modes-gm-edit" onKeyDown=${(e) => { if (e.key === "Enter") set(); }}>
          <${Field} value=${val} onChange=${setVal} mono sm width=${120} title=${r.hint} />
          <${Button} size="sm" kind="primary" disabled=${!String(val).trim() || same} onClick=${set}>Set<//>
          <${Button} size="sm" disabled=${!r.changed} title="Put this number back to the game's own value."
            onClick=${() => call("modes.game_stock", r.key)}>Stock<//>
          ${r.changed ? html`<${Chip} kind="acc" sm>changed<//>` : null}
        </div>`}
  </div>`;
}

// Shots: the "counts as" rows of THIS mode (item 160; the project's modes/stock.json holds
// every mode's), an Add row, and Remove on each.
function CountsAsSec({ s, g }) {
  const st = s.remap || {};
  const shots = st.shots || [];
  const mine = (st.rows || []).filter((r) => r.rule === g.id);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  useEffect(() => {
    if (!from && shots.length) setFrom(shots[0]);
    if (!to && shots.length > 1) setTo(shots[1]);
  }, [shots.length]);
  const note = st.note && (st.sel == null || mine.some((r) => r.i === st.sel)) ? st.note : "";
  return html`<${Sec} title="Shots" tipText=${T.countsAs}>
    ${!st.on ? html`<div class="small muted wrap">${st.msg}</div>` : html`
      <div class="small muted wrap">A shot of your choosing can count as one of this mode's own while it runs.</div>
      ${mine.length ? html`<div class="stack" style="gap:4px">${mine.map((r) => html`<div class="row modes-ca-row" key=${r.i}>
          <span><b>${r.from}</b> <span class="dim">counts as</span> <b>${r.to}</b></span>
          ${r.problem ? html`<${Chip} kind="warn" sm title=${r.problem}>cannot be written<//>` : null}
          <span class="grow"></span>
          <${Button} size="xs" kind="ghost" icon="trash" title="Take this row out."
            onClick=${() => call("modes.remap_delete", r.i)}>Remove<//>
        </div>`)}</div>` : html`<div class="small dim">No shot counts as another here: the mode plays as it always did.</div>`}
      <div class="row wrap">
        <${Select} sm width=${160} value=${from} onChange=${setFrom} options=${shots} title="The shot the player makes." />
        <span class="dim">counts as</span>
        <${Select} sm width=${160} value=${to} onChange=${setTo} options=${shots} title="The mode's own shot it stands in for." />
        <${Button} size="sm" disabled=${!from || !to} onClick=${() => call("modes.remap_add", g.id, from, to)}>Add<//>
      </div>
      ${note ? html`<div class="small muted wrap">${note}</div>` : null}`}
  <//>`;
}

// Advanced: this mode's shot handling rewritten in C (item 161), or where its rewrite is.
function RewriteSec({ s, g }) {
  const st = s.rewrite || {};
  const row = (st.rows || []).find((r) => r.id === g.id);
  const note = st.note && st.sel === g.id ? st.note : "";
  return html`<${Sec} title="Advanced" tipText=${T.rewrite}>
    ${!st.on || !row ? html`<div class="small muted wrap">${st.msg || "This card's port does not let this mode be rewritten."}</div>`
      : row.slug ? html`<div class="row wrap">
          <span><span class="pill">C</span> Its shots are rewritten by <span class="mono">modes/${row.slug}/${row.slug}.c</span></span>
          <${Button} size="sm" onClick=${() => call("modes.select", row.slug, "code")}>Open it<//>
        </div>`
      : html`<div class="row wrap">
          <${Button} icon="edit" disabled=${!row.template} title=${row.template ? T.rewrite : row.status}
            onClick=${() => call("modes.rewrite_new", g.id)}>Rewrite this mode's shots in C…<//>
          ${!row.template ? html`<span class="small muted">${row.status}</span>` : null}
        </div>`}
    ${note ? html`<div class="small muted wrap">${note}</div>` : null}
  <//>`;
}

function GameModePage({ g, s }) {
  const rows = g.rows || [];
  return html`<section class="card modes-editor">
    <div class="hd">
      <span class="h2 ellip">${g.name}</span>
      <span class="chip info"><span class="dot"></span>The game's own</span>
      <span class="sp"></span>
      <span class="small muted">${g.n_changed ? `${g.n_changed} change(s) for the next Write` : g.build}</span>
    </div>
    <div class="modes-status info" role="status">${g.about}</div>
    <div class="bd modes-editor-bd">
      <${Sec} title="Timers and awards">
        ${rows.length ? html`<div class="modes-gm">${rows.map((r) => html`<${GameRow} key=${r.key} r=${r} />`)}</div>`
          : html`<div class="small muted">No numbers to show.</div>`}
        ${g.note ? html`<${Note} kind=${g.note.startsWith("Read-only") ? "" : "info"}>${g.note}<//>` : null}
      <//>
      ${g.rule ? html`<${CountsAsSec} s=${s} g=${g} />` : null}
      ${g.rule ? html`<${RewriteSec} s=${s} g=${g} />` : null}
      <div class="small muted wrap">To rename it, edit its title on the Text tab.</div>
    </div>
  </section>`;
}

// ------------------------------------------------------------------ Try it
function Elapsed({ started }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!started) return undefined;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [started]);
  return started ? html`<span class="mono muted small">${fmtClock(Date.now() / 1000 - started)}</span>` : null;
}

function idleWords(s) {
  const n = s.n_form || 0, c = s.n_code || 0;
  const what = `${n} mode${n === 1 ? "" : "s"}${c ? ` and ${c} in C` : ""}`;
  return `${what}, built as Write puts them on a card.${s.own_extra_ok === false ? "" : T.ownSoundCost}`;
}

const tryTip = (s) => T.tryit + (s.own_extra_ok === false ? "" : T.ownSoundCost);

// A long card path shows its END (the image's file name, which says which card) unless it is
// being edited: the Emulate tab's own card box does the same.
function useEndScroll(ref, value) {
  useEffect(() => {
    const el = ref.current && ref.current.querySelector("input");
    if (!el) return undefined;
    const toEnd = () => { if (document.activeElement !== el) el.scrollLeft = el.scrollWidth; };
    toEnd();
    el.addEventListener("blur", toEnd);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(toEnd) : null;
    if (ro) ro.observe(el);
    return () => { el.removeEventListener("blur", toEnd); if (ro) ro.disconnect(); };
  }, [value]);
}

const TRY_ON_TIP = "The Emulate tab's card: Try it boots it and builds the modes for it.";

function TryFooter({ s }) {
  const t = s.tryit || {};
  const emu = s.emu || {};
  const cardRef = useRef(null);
  useEndScroll(cardRef, emu.card);
  const working = !!t.working;
  const prog = t.progress;
  const pct = prog && prog[1] != null ? prog[1] : null;
  const live = t.state === "live";
  const stateKind = t.state === "failed" ? "err" : live ? "ok" : working ? "acc" : "";
  return html`<section class="card modes-foot">
    <div class="bd modes-foot-bd">
      <div class="row modes-tryon">
        <span class="lbl nw">Try it on</span>
        <div class="grow modes-tryon-path" ref=${cardRef}>
          <${Field} value=${emu.card} mono readOnly=${!emu.box} placeholder="The card in the Emulate tab's box"
            onCommit=${(v) => setField("modes", "try_on", v, { flush: true })} title=${emu.card ? emu.card + "\n" + TRY_ON_TIP : TRY_ON_TIP} />
        </div>
        <${Button} disabled=${!emu.box || working} onClick=${() => call("modes.browse_card")}>Browse…<//>
        ${emu.verdict ? html`<${Chip} kind=${emu.verdict_kind} dot title=${emu.verdict_tip}>${emu.verdict}<//>` : null}
      </div>
      <div class="row modes-tryrow">
        <${Button} kind=${working ? "danger" : "primary"} size="big" icon=${working ? "x" : "play"}
          title=${!working && s.no_port ? s.no_port : tryTip(s)}
          disabled=${!s.project || (!working && !!s.no_port)} onClick=${() => call("modes.tryit")}>${working ? "Cancel" : "Try it"}<//>
        <${Check} label=${html`leave out own sounds<span class="modes-long"> (the game's calls play; skips the sound bank)</span>`} title=${T.leaveOut}
          checked=${s.leave_out} disabled=${working} ns="modes" k="leave_out" />
        <button type="button" class="chip modes-tryon-chip" disabled=${!emu.box || working} onClick=${() => call("modes.browse_card")}
          ...${tip((emu.card ? emu.card + "\n" : "") + TRY_ON_TIP + " Click to pick another.")}>
          <${Icon} name="file" /><span class="ellip">${emu.card ? emu.card.split(/[\\/]/).pop() : "Pick a card…"}</span></button>
        <span class="vsep"></span>
        <${Button} disabled=${!emu.up} title=${emu.up ? T.startNow : "The emulator is not running: press Try it first."} onClick=${() => call("modes.start_now")}>Start mode now<//>
        <${Button} disabled=${!emu.up} title=${emu.up ? T.endNow : "The emulator is not running."} onClick=${() => call("modes.end_now")}>End mode<//>
        <span class="grow"></span>
        ${working || live ? html`<${Button} kind="ghost" size="sm" icon="emulate" onClick=${() => call("modes.goto_emulate")}>Emulate tab<//>`
          : s.project && !s.tryit_line ? html`<span class="small dim modes-tryhint" ...${tip(tryTip(s))}>${idleWords(s)}</span>` : null}
      </div>
      ${(t.state && t.state !== "idle") || s.tryit_line ? html`<div class="row modes-tryline" role="status">
        ${t.state && t.state !== "idle" ? html`<${Chip} kind=${stateKind} dot>${STATE_WORDS[t.state] || t.state}<//>` : null}
        ${working ? html`<div class=${cx("modes-bar", pct == null && "busy")}><i style=${`width:${pct == null ? 30 : pct}%`}></i></div>` : null}
        ${working ? html`<${Elapsed} started=${t.started} />` : null}
        <span class="small dim modes-tryline-text">${s.tryit_line}</span>
      </div>` : null}
    </div>
  </section>`;
}

// ------------------------------------------------------------------ the title's note
// What the card's build cannot do yet, or what a person should do first. On a short window
// it is one line with "more"; the details for someone who writes C are in a tooltip.
function TitleNote({ s }) {
  const [more, setMore] = useState(false);
  const details = s.no_port_details ? html`<${InfoBadge} text=${s.no_port_details} />` : null;
  return html`<div class=${cx("modes-note", more && "open")}><${Note} kind="warn" action=${html`<span class="row nw modes-note-act">${details}
      <button type="button" class="linkish small modes-note-more" onClick=${() => setMore(!more)}>${more ? "less" : "more"}</button></span>`}>${s.title_note}<//></div>`;
}

// ------------------------------------------------------------------ the first mode
// A project with no mode of its own yet: the three ways in, the easiest first.
function FirstMode({ s, onNewCode }) {
  const ex = exampleItems(s);
  const off = !!s.no_port;
  return html`<section class="card modes-editor modes-first">
    <div class="bd modes-editor-bd">
      <div class="stack" style="gap:4px">
        <h2 class="h2">Make your first mode</h2>
        <div class="small muted wrap">A mode is something new for the game to do: what starts it, how long it runs, which shots score, and what the display, lights and speakers do meanwhile.</div>
        ${s.no_port ? html`<div class="small warn-ink wrap">${s.no_port}</div>` : null}
      </div>
      <div class="modes-first-grid">
        <div class="modes-first-opt rec">
          <div class="row wrap"><${Icon} name="list" /><b>From an example</b><${Chip} kind="ok" sm>recommended<//></div>
          <div class="small muted wrap">A finished mode to play and change.${ex.some((x) => x.label === "KAIJU RUSH") ? " KAIJU RUSH is the one that has run on a real machine." : ""}</div>
          <div class="row wrap">${ex.length ? ex.map((x) => html`<${Button} key=${x.label} size="sm" kind=${x.label === "KAIJU RUSH" ? "primary" : ""}
              disabled=${off || x.disabled} title=${x.title} onClick=${x.onClick}>${x.label}<//>`)
            : html`<span class="small dim">${s.ex_tip || "No example for this game yet."}</span>`}</div>
        </div>
        <div class="modes-first-opt">
          <div class="row"><${Icon} name="plus" /><b>Blank mode</b></div>
          <div class="small muted wrap">Start empty and fill in the form, page by page.</div>
          <div class="row"><${Button} size="sm" disabled=${!s.new_ok || off} onClick=${() => call("modes.new")}>Blank mode<//></div>
        </div>
        <div class="modes-first-opt">
          <div class="row wrap"><${Icon} name="edit" /><b>Write one in C</b><${Chip} sm>advanced<//></div>
          <div class="small muted wrap">For what the form can't do. It starts from the Mode SDK's template.</div>
          <div class="row wrap">
            <${Button} size="sm" disabled=${off} title=${s.no_port || T.codeMode} onClick=${onNewCode}>Blank mode in C…<//>
            <${Button} size="sm" kind="ghost" icon="file" onClick=${() => call("modes.open_sdk_doc")}>MODE_SDK.md<//>
          </div>
        </div>
      </div>
      ${(s.game_rows || []).length ? html`<div class="small muted wrap">Or change one of the game's own modes: they're listed on the left, under yours, each with its timers, awards and shots.</div>` : null}
    </div>
  </section>`;
}

// ------------------------------------------------------------------ the tab
export default function ModesTab() {
  const s = useNs("modes");
  if (s.spin) SPIN = s.spin;
  const [stock, setStock] = useState(false);
  const [newCode, setNewCode] = useState(false);
  const [clip, setClip] = useState(null);
  const showClip = (path, title) => setClip({ path, title });
  const withClip = Object.assign({}, s, { _showClip: showClip });
  const hasProject = !!s.project;
  return html`<div class="page modes-page">
    <${Head} s=${s} />
    <${ReadingPanel} r=${s.reading} />
    ${s.title_note ? html`<${TitleNote} s=${s} />` : null}
    <div class="modes-body">
      <${ModeList} s=${s} onNewCode=${() => setNewCode(true)} onAllNumbers=${() => setStock(true)} />
      ${s.game_mode ? html`<${GameModePage} g=${s.game_mode} s=${s} />`
        : s.code ? html`<${CodePane} s=${withClip} />`
        : s.open ? html`<${Editor} s=${s} showClip=${showClip} />`
        : hasProject && !(s.rows || []).length ? html`<${FirstMode} s=${s} onNewCode=${() => setNewCode(true)} />`
        : html`<section class="card modes-editor modes-empty">
            <${Empty} icon="modes" title=${hasProject ? "No mode open" : "No project"}>
              ${hasProject ? (s.status || "Pick a mode on the left.") : s.project_label}
            <//>
          </section>`}
    </div>
    <${TryFooter} s=${s} />
    ${stock ? html`<${StockDialog} s=${s} onClose=${() => setStock(false)} />` : null}
    ${s.film ? html`<${FilmDialog} film=${s.film} key=${s.film.seq} />` : null}
    ${newCode ? html`<${NewCodeDialog} onClose=${() => setNewCode(false)} />` : null}
    ${clip ? html`<${ClipDialog} path=${clip.path} title=${clip.title} onClose=${() => setClip(null)} />` : null}
  </div>`;
}
