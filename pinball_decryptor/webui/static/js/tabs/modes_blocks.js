// Modes: a mode made of BLOCKS (PAD-232). The third way to make a mode, beside the form and C:
// scripts, each a "When ..." block with the blocks it runs under it, snapped together from the
// palette on the left (drag a block in, or press it to add it to the script picked last, or use
// a stack's own +). Values and conditions sit in the slots of a block and nest: a sum of a
// variable and a number, "hits of Left ramp >= 3 and not a game mode runs".
//
// Python (plugins/stern/block_modes.py) owns what a program means: it saves blocks.json, writes
// the C the program makes (a code mode, so Try it and Write build it like any other) and says
// what is wrong with it. This page edits its own copy of the program and sends the whole of it
// after each change (modes.blocks_save), a moment after the person stops.
//
// PAD-375: Its HUD gives the mode what the examples have at the glass's edges (the title and an
// instruction line, three counters, a timer badge, a gauge, an award line); the HUD blocks write it.
// PAD-374: a mode's OWN clips and sounds sit above its scripts (picked from files, copied into its
// folder by modes.blocks_pick), each with the name its Play a clip / Play a sound blocks call it by.
//
// PAD-378: Undo and Redo, here in the page (the program is the page's own copy): every change is a
// step, a run of typing or dragging in one box is one step, and Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z
// work them as on the Color profile tab (a text box keeps its own undo).

import { html, useEffect, useRef, useState, Button, Field, Select, Check, Note, tip, cx, call,
         openMenu } from "../core/ui.js";
import { PlayButton } from "./modes_dialogs.js";

const WHEN = [["any", "any time"], ["idle", "while it is not running"], ["running", "while it runs"]];
const RESETS = [["ball", "each ball"], ["mode", "each time it starts"], ["game", "each game"]];
const SHARED_RESETS = RESETS.filter(([r]) => r !== "mode");
// MODE_SDK.md "Display priority": a mode's 180 lets jackpots, starts and the tilt warning through
const DISPLAY_PRIORITIES = [[0, "none"], [180, "a mode's (180)"], [190, "a wizard mode's (190)"]];
const PATTERNS = [["solid", "solid"], ["blink", "blinking"], ["pulse", "pulsing"], ["chase", "chasing"],
  ["hurry", "blinking faster"]];
const PACED = ["blink", "pulse", "chase"];
const OPS = [["+", "+"], ["-", "−"], ["*", "×"], ["/", "÷"]];
const CMPS = [["<", "<"], ["<=", "≤"], ["=", "="], ["!=", "≠"], [">=", "≥"], [">", ">"]];
const SCOOP_WHICH = [["next", "the next ball"], ["every", "every ball"]];   // PAD-395
const SHIELD_WHERE = [["toward", "toward the player"], ["away", "away"], ["leave", "where they are"]];   // PAD-392
const SHAKE_STRENGTH = [["hard", "a hard"], ["strong", "a strong"], ["medium", "a medium"], ["soft", "a soft"]];   // PAD-414
// PAD-474: only the strengths the card's game shakes at (a one-power shaker: hard alone)
const shakeStrengths = (ch) => { const m = ch.shake_max || []; return m.some((v) => v) ? SHAKE_STRENGTH.filter((_s, i) => m[i]) : SHAKE_STRENGTH; };
const CLIP_WHERE = [["full", "full screen"], ["behind", "behind the HUD, once"], ["loop", "behind the HUD, over and over"]];
const PRIORITIES = [3, 4, 5, 6, 7].map((p) => [String(p), "priority " + p]);
const SAVE_MS = 450;
const UNDO_STEPS = 100;
const MERGE_MS = 1000;        // the same box changed again within this is the same step

const TIP = {
  palette: "Drag a block into a script, or press it to add it to the script you picked last (the one with the lit edge).",
  hat: "A script: what sets it off, and the blocks it runs, top to bottom.",
  vars: "A variable holds a number for each player. Reset says when it goes back to 0.",
  screen: "The build makes the mode a screen of its own: a panel with its name, and a line the Show words block writes. It costs a little build time.",
  seconds: "How long the mode runs once it starts. 0 = no clock: it runs until a block ends it (or the ball drains, if ticked).",
  drain: "The ball draining ends the mode.",
  undo: "Undo the last change to the blocks (Ctrl+Z)",
  redo: "Redo the change just undone (Ctrl+Y or Ctrl+Shift+Z)",
  asC: "Carry on in C: the mode keeps the C its blocks made, and the blocks are put away.",
  hits: "How many times the player up has made this shot in this ball (while the mode runs or not).",
  scored: "How many times a Score block has paid since the mode started.",
  total: "The points the mode's Score blocks have paid since it started.",
  stock: "One of the game's own modes, battles or multiballs is running.",
  addTime: "Adds this many seconds to the mode's clock (less than 0 takes some off). Any value: a number, a variable, a sum.",
  hud: "The mode's HUD at the edges of the screen, as the game's own battles have: its name and an instruction line above the score, up to three counters along the top, a timer badge counting its clock and a gauge on the right. It steps out of the way of the game's own displays and modes by itself. Built on Godzilla cards.",
  hudOff: "This card's game has no HUD scene for it: the mode runs the same with nothing at the edges.",
  hudLine: "The white line under the mode's name: what to shoot. The Show on the HUD block changes it.",
  counter: "A counter along the top: a label, a big number and a smaller line under it. No label = not shown.",
  follows: "The number it shows, kept up to date by itself (a variable, points so far). Empty: a Set counter block sets it.",
  timer: "The badge on the left edge counting the mode's clock down, with its label and icon (a mode with no clock has none).",
  gauge: "Pips on the right edge, lit up to a number: a gauge of how far along the mode is.",
  gaugeFollows: "How many pips are lit, kept up to date by itself. Empty: a Fill the gauge block sets it.",
  hudAward: "A big line, and a smaller one under it, for a moment (a jackpot). Before the mode starts it is a note shown alone, when no other mode's HUD is up.",
  setTime: "Puts the mode's clock at this many seconds, up or down (0 = time is up). Put up, a When that many seconds are left does not run again.",
  shared: "Shared with the other modes: every mode with a variable of this name reads and writes the same number, so one mode can be lit by what another did (played it, won it). It resets each ball or each game.",
  timers: "A timer counts down in milliseconds, apart from the mode's clock: start it from a block (any value, so a window can get shorter), and a When it runs out script runs the moment it does. A ball ending stops every timer.",
  timerStart: "Starts the timer (again, if it runs) at this many milliseconds: 1000 = one second. Any value: a variable makes a window that shrinks.",
  timerLeft: "The milliseconds the timer has left; 0 when it is not running.",
  wait: "A Start the mode block while a multiball or one of the game's own modes runs does nothing, and the mode stays ready: the next one after it starts it, as the example modes do.",
  canStart: "The mode is not running, a game is on, and (with waits out a multiball) no multiball is running: a Start the mode block now would start it.",
  displayPriority: "Kept for the total on its own screen. It no longer makes the game's displays wait: a mode always gives way to them (holding one kept Godzilla's Magna-Grab magnet on until the machine was switched off).",
  gameModes: "Cannot start (the usual): while this mode runs it is the only thing going - the modes ticked below cannot start, and none of the game's features lights, locks, counts or awards unless you tick it under Keep counting. May start: the game's modes start as usual while this one runs. End this one: it starts only while none of the game's modes runs (a Start the mode then waits, and the next one starts it), and one of them starting ends it. Its own Multiball block does not end it.",
  keepRule: "Ticked: this feature of the game's goes on counting its shots while this mode runs (its progress, its jackpots, its locks and the multiball it leads to). Not ticked: it sees none of them until this mode ends.",
  blockPick: "While this mode runs, the game does not start this one of its modes. A shot that would have started it does what it does when the mode is not lit.",
  blockLast: "One at least: to let them all start, choose \"may start\" above.",
  own: "Clips and sounds of the mode's own, picked from your files and copied into its folder. Write and Try it carry them onto the card; a Play a clip or Play a sound block plays one by its name.",
  where: "Full screen plays over everything, the HUD too, half a second after it is asked for (so the game's own clip for the same shot does not take its place). Behind the HUD, over and over, plays in the city's place under the score while the mode runs. Behind the HUD, once, plays in that loop's place and then the loop again.",
  fallback: "What to say instead when the card could not carry this sound (a card with no spare sound for it): one of the game's own callouts, or nothing.",
  priority: "Its priority on the voice bus: it fades the game's lower speech and waits for higher. 4 is a call's usual; 3 for one that repeats (a play while the last still sounds is skipped).",
  music: "Its own music: it plays instead of the game's while the mode runs, and the game's comes back at the end.",
  name: "The name its blocks call it by: lower-case letters, digits and _.",
  rate: "How fast it blinks, pulses or chases: one beat every this many ms (20 to 5000). Any value: a number, a variable, a sum. Empty = its usual pace.",
  hurry: "Blinks slowly with most of the time left, faster as the clock runs down, and flickers in the last three seconds.",
  show: "A light show over the playfield's inserts (the ones the game's port places), a few seconds long: the shots' own lights come back when it is over. A new show takes the place of one still running.",
  ownShow: "Its own steps, one after another: each a pattern over the inserts for some ms, in two colours, from a place on the playfield.",
  stepRate: "The pattern's pace, ms (a strobe's flash, a beam's turn, a chase's step). 0 = its usual.",
  gi: "The lights between the inserts (the general illumination) during this step: the game's, dark, or flashing white.",
  hold: "Holds the mechanism this many ms (100 to 5000) at its own power settings, then lets go. Only while the mode runs, never while the game uses it, 3 s apart and 6 a minute at most; the mode ending, the ball draining or a tilt lets go at once. Any value: a number, a variable, a sum.",
  scoopHold: "A ball that settles in the scoop waits this many ms (100 to 10000), then the game kicks it out as always. The next ball, or every ball while the mode runs. The game's own use of the scoop comes first; the mode ending lets it go.",
  letGo: "Lets go of a held mechanism now, or stops holding balls in the scoop (a ball held there goes).",
  shake: "Shakes the cabinet's shaker motor for this long, the way the game shakes it: the operator's Shaker Motor setting still applies (switched off, or no shaker fitted: nothing). A strength the game itself shakes at (some games have one only), never longer than the game's own longest at that strength. One at a time, never over one of the game's own, 20 shakes and 15 seconds of shaking a minute at most; the mode, the ball or the game ending stops it, except a shake in When the mode ends, which runs out.",
  shakeGame: "Plays one of the game's own shakes, as the game does: on Godzilla its hit (a battle's shot), its big hit, its jackpot (every super jackpot), its long rumble or its multiball start (five shakes over 4 seconds); on the other games the one it plays most of each length (a tap, a short, medium or long shake, a rumble). The same limits as Shake the cabinet.",
  gameShow: "One of the game's own playfield light shows, played as the game plays it, for its own few seconds; a new one takes the place of one still playing. Only while the mode runs or as it ends (When the mode ends), never as the ball drains: the game stops its own shows then.",
  gameWizard: "Hands the player one of the game's own mini-wizards, the game's mode itself with its own shots, lights, screens, sounds and award. Light it: it waits for the game's own start shot, as when the game lights one. Start it: it begins at once, or the moment the game would start one (one of the game's own modes, or this mode holding the game's modes off, in the way), and if the ball ends first it stays lit for the start shot. Until it starts it is the only one lit, so the game's own choosing cannot swap it for another. The game no longer lights a mini-wizard named here by itself: only this mode hands it out. Works whether this mode runs or not: in When the game does an event (a film done) it is a mini-wizard for that event. One the player has played this game plays again.",
  shield: "Turns the platform the shield targets sit on (about a second) and keeps it there while the mode runs: the game's ball search swings it, and it is turned back after. Where they are: stop keeping them. Only while the mode runs, never while one of the game's own modes runs, 1.5 s between moves, 12 a minute at most; the mode ending, the ball draining or a tilt turns them back where they were. They stay turned only while the game's modes cannot start and its own shield feature does not keep counting.",
};

// ------------------------------------------------------------------ the blocks there are
const num = (v) => ({ k: "num", v });

function hatTemplates(ch, timers) {
  const shot = (ch.shots || [])[0] || "";
  const ev = ((ch.events || [])[0] || {}).name || "";
  return [
    { kind: "mode_start" }, { kind: "mode_end" },
    { kind: "shot", shot, when: "running" }, { kind: "any_shot", when: "running" },
    { kind: "every", seconds: 5 }, { kind: "seconds_left", seconds: 10 },
    { kind: "ball_end" }, { kind: "event", event: ev, when: "any" },
    { kind: "timer_done", timer: (timers[0] || {}).name || "" },
  ];
}

function stmtTemplates(ch, vars, prog = {}) {
  const shot = (ch.shots || [])[0] || "";
  const v = (vars[0] || {}).name || "";
  const t = ((prog.timers || [])[0] || {}).name || "";
  const clip = ((prog.clips || [])[0] || {}).name || "";
  const sound = ((prog.sounds || [])[0] || {}).name || "";
  return [
    ["Mode", [{ op: "start_mode" }, { op: "end_mode" }, { op: "add_time", seconds: num(5) },
      { op: "set_time", seconds: num(10) },
      { op: "multiball", balls: 2, save: 10 },
      { op: "game_wizard", name: ((ch.game_wizards || [])[0] || {}).name || "", how: "light" }]],
    // PAD-395: the mechanisms the form's Magnet, Scoop and Other mechanisms hold (greyed where the game cannot)
    ["Mechanisms", [{ op: "hold", what: ((ch.mechs || [])[0] || {}).name || "magnet", ms: num(2000) },
      { op: "scoop_hold", ms: num(3000), which: "next" }, { op: "let_go", what: "*" },
      { op: "shield", where: "toward" }, { op: "shake", ms: num(500), strength: "hard" },
      { op: "shake_game", shake: ((ch.shakes || [])[0] || {}).name || "jackpot" }].filter((t) => !machineLacks(t, ch))],
    ["Score and variables", [{ op: "score", points: num(1000000) }, { op: "set", var: v, value: num(0) },
      { op: "change", var: v, by: num(1) }]],
    ["Timers", [{ op: "timer_start", timer: t, ms: num(5000) }, { op: "timer_stop", timer: t }]],
    ["Control", [{ op: "if", cond: null, then: [], else: null }, { op: "if", cond: null, then: [], else: [] }]],
    ["Show and sound", [{ op: "callout", role: "ten_seconds" }, { op: "words", text: "JACKPOT", value: null },
      { op: "light_shot", shot, color: "#ffd000", pattern: "blink", rate: null }, { op: "lights_off", shot: "*" },
      { op: "show", show: "burst" }, { op: "game_show", name: (ch.game_shows || []).find((x) => x.kind === "flashy")?.name || ((ch.game_shows || [])[0] || {}).name || "" },
      { op: "log", text: "" }]],
    ["Its own clips and sounds", [{ op: "clip", clip, where: "full" }, { op: "sound", sound, fallback: null }]],
    ["HUD", [{ op: "hud_text", which: "line", text: "SHOOT THE LIT SHOT", value: null },
      { op: "hud_counter", counter: 1, value: num(0), sub: null }, { op: "hud_gauge", value: num(1) },
      { op: "hud_award", text: "JACKPOT", value: null, sub: "", seconds: 2 }]],
  ];
}

function valueTemplates(ch, vars, timers) {
  return [num(1000), { k: "var", name: (vars[0] || {}).name || "" }, { k: "hits", shot: (ch.shots || [])[0] || "" },
    { k: "scored" }, { k: "total" }, { k: "secs_left" }, { k: "timer_left", timer: ((timers || [])[0] || {}).name || "" },
    { k: "balls" }, { k: "player" }, { k: "op", op: "+", a: null, b: null }];
}

const condTemplates = () => [{ k: "cmp", op: ">=", a: null, b: null }, { k: "and", a: null, b: null },
  { k: "or", a: null, b: null }, { k: "not", a: null }, { k: "running" }, { k: "can_start" }, { k: "stock" }];

const VALUE_WORDS = { num: "a number", var: "a variable", hits: "hits of a shot this ball", scored: "times it has scored",
  total: "points so far", secs_left: "seconds left", timer_left: "ms left on a timer", balls: "balls in play",
  player: "the player up", op: "a sum" };
const COND_WORDS = { cmp: "compare two values", and: "both", or: "either", not: "not", running: "the mode is running",
  can_start: "the mode could start now", stock: "a game mode of its own runs" };
const STMT_CLASS = { start_mode: "mode", end_mode: "mode", add_time: "mode", set_time: "mode", multiball: "mode", game_wizard: "mode", score: "score",
  set: "var", change: "var", if: "flow", callout: "show", words: "show", light_shot: "show", lights_off: "show", show: "show", game_show: "show", log: "show",
  clip: "own", sound: "own", timer_start: "timer", timer_stop: "timer", hud_text: "hud", hud_counter: "hud",
  hud_gauge: "hud", hud_award: "hud", hold: "mech", scoop_hold: "mech", let_go: "mech", shield: "mech",
  shake: "mech", shake_game: "mech" };
const WHICH = [["title", "title"], ["line", "instruction line"]];
const COUNTERS = [[1, "counter 1"], [2, "counter 2"], [3, "counter 3"]];
const GAUGES = [["diamond", "diamonds"], ["segment", "a bar of segments"], ["spike", "spikes"]];

// ------------------------------------------------------------------ the program, by path
const clone = (x) => JSON.parse(JSON.stringify(x));
function at(obj, path) { return path.reduce((o, k) => (o == null ? o : o[k]), obj); }
function put(obj, path, value) { at(obj, path.slice(0, -1))[path[path.length - 1]] = value; }
const samePath = (a, b) => a && b && a.length === b.length && a.every((x, i) => x === b[i]);
const within = (inner, outer) => inner.length >= outer.length && outer.every((x, i) => inner[i] === x);

// Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z: undo (false), redo (true), or null for another key. A text box
// keeps its own undo; a list box has none, so there it is the blocks'.
function undoKeyOf(e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return null;
  const k = (e.key || "").toLowerCase();
  const redo = k === "y" || (k === "z" && e.shiftKey);
  if (k !== "z" && !redo) return null;
  const el = e.target;
  if (el && (el.isContentEditable || el.tagName === "TEXTAREA"
      || (el.tagName === "INPUT" && !/^(range|checkbox|radio|button|color)$/.test(el.type)))) return null;
  return redo;
}

// what is being dragged: {tpl} from the palette, or {from: stack path, i} a block in a script
let dragging = null;

// ------------------------------------------------------------------ small inline controls
function Num({ value, onChange, width = 58, title }) {
  return html`<${Field} sm mono width=${width} value=${value == null ? "" : String(value)} title=${title}
    onChange=${(t) => { const n = Number(String(t).replace(/,/g, "")); onChange(t.trim() !== "" && Number.isInteger(n) ? n : t); }} />`;
}

function Pick({ value, options, onChange, width, title, missing = "(not on this card)" }) {
  const opts = options.map((o) => (Array.isArray(o) ? { value: o[0], label: o[1] } : typeof o === "object" ? o : { value: o, label: o }));
  if (value != null && value !== "" && !opts.some((o) => o.value === value)) opts.unshift({ value, label: `${value} ${missing}` });
  if (value == null || value === "") opts.unshift({ value: "", label: "(choose)" });
  return html`<${Select} sm value=${value ?? ""} options=${opts} onChange=${onChange} width=${width} title=${title} />`;
}

function TimerPick({ value, ed, onChange }) {
  return html`<${Pick} value=${value} options=${ed.timers.map((t) => t.name)} missing="(no such timer)" onChange=${onChange} />`;
}

function Text({ value, onChange, width = 150, placeholder, max = 60, title }) {
  return html`<${Field} sm width=${width} value=${value || ""} maxLength=${max} placeholder=${placeholder} title=${title} onChange=${onChange} />`;
}

function X({ onClick, title = "Take this block out" }) {
  return html`<button type="button" class="bk-x" aria-label=${title} ...${tip(title)}
    onClick=${(e) => { e.stopPropagation(); onClick(); }}>×</button>`;
}

// ------------------------------------------------------------------ values and conditions
// A slot: empty, it is a hole to drop a value into (or press for a menu); filled, the value's
// own block, which can hold slots of its own.
function slotMenu(e, kind, ed, path) {
  const items = kind === "bool"
    ? condTemplates().map((t) => ({ label: COND_WORDS[t.k], onClick: () => ed.set(path, t) }))
    : valueTemplates(ed.ch, ed.vars, ed.timers).map((t) => ({ label: VALUE_WORDS[t.k], onClick: () => ed.set(path, t) }));
  openMenu(e.currentTarget, items);
}

function Slot({ kind, value, path, ed, optional, empty }) {
  const [over, setOver] = useState(false);
  const fits = () => dragging && dragging.tpl && (kind === "bool" ? dragging.tpl.k && condTemplates().some((t) => t.k === dragging.tpl.k)
    : dragging.tpl.k && valueTemplates(ed.ch, ed.vars, ed.timers).some((t) => t.k === dragging.tpl.k));
  const drop = {
    onDragOver: (e) => { if (fits()) { e.preventDefault(); e.stopPropagation(); setOver(true); } },
    onDragLeave: () => setOver(false),
    onDrop: (e) => { if (!fits()) return; e.preventDefault(); e.stopPropagation(); setOver(false); ed.set(path, clone(dragging.tpl)); dragging = null; },
  };
  if (!value) {
    return html`<button type="button" class=${cx("bk-slot", kind, over && "over")} ...${drop}
      onClick=${(e) => slotMenu(e, kind, ed, path)} ...${tip(kind === "bool" ? "A condition: drop one here, or press to pick" : "A value: drop one here, or press to pick")}>
      ${kind === "bool" ? "condition" : empty || (optional ? "(no number)" : "value")}</button>`;
  }
  return html`<span class=${cx("bk-rep", kind, over && "over")} ...${drop}>
    ${kind === "bool" ? html`<${Cond} e=${value} path=${path} ed=${ed} />` : html`<${Val} e=${value} path=${path} ed=${ed} />`}
    <${X} title="Empty this slot" onClick=${() => ed.set(path, null)} />
  </span>`;
}

function Val({ e, path, ed }) {
  const set = (k, v) => ed.set([...path, k], v);
  switch (e.k) {
    case "num": return html`<${Num} value=${e.v} onChange=${(v) => set("v", v)} width=${96} />`;
    case "var": return html`<${Pick} value=${e.name} options=${ed.vars.map((v) => v.name)} missing="(no such variable)"
      onChange=${(v) => set("name", v)} />`;
    case "hits": return html`<span class="bk-w" ...${tip(TIP.hits)}>hits of</span><${Pick} value=${e.shot} options=${ed.ch.shots || []} onChange=${(v) => set("shot", v)} />`;
    case "timer_left": return html`<span class="bk-w" ...${tip(TIP.timerLeft)}>ms left on</span><${TimerPick} value=${e.timer} ed=${ed} onChange=${(v) => set("timer", v)} />`;
    case "op": return html`<span class="bk-w">(</span><${Slot} kind="num" value=${e.a} path=${[...path, "a"]} ed=${ed} />
      <${Pick} value=${e.op} options=${OPS} width=${54} onChange=${(v) => set("op", v)} />
      <${Slot} kind="num" value=${e.b} path=${[...path, "b"]} ed=${ed} /><span class="bk-w">)</span>`;
    default: return html`<span class="bk-w" ...${tip(TIP[e.k] || "")}>${VALUE_WORDS[e.k] || e.k}</span>`;
  }
}

function Cond({ e, path, ed }) {
  switch (e.k) {
    case "cmp": return html`<${Slot} kind="num" value=${e.a} path=${[...path, "a"]} ed=${ed} />
      <${Pick} value=${e.op} options=${CMPS} width=${54} onChange=${(v) => ed.set([...path, "op"], v)} />
      <${Slot} kind="num" value=${e.b} path=${[...path, "b"]} ed=${ed} />`;
    case "and": case "or": return html`<${Slot} kind="bool" value=${e.a} path=${[...path, "a"]} ed=${ed} />
      <span class="bk-w b">${e.k}</span><${Slot} kind="bool" value=${e.b} path=${[...path, "b"]} ed=${ed} />`;
    case "not": return html`<span class="bk-w b">not</span><${Slot} kind="bool" value=${e.a} path=${[...path, "a"]} ed=${ed} />`;
    default: return html`<span class="bk-w" ...${tip(TIP[e.k] || "")}>${COND_WORDS[e.k] || e.k}</span>`;
  }
}

// ------------------------------------------------------------------ statements
function StmtBody({ b, path, ed }) {
  const set = (k, v) => ed.set([...path, k], v);
  const shots = ed.ch.shots || [];
  switch (b.op) {
    case "start_mode": return html`<span class="bk-w">Start the mode</span>`;
    case "end_mode": return html`<span class="bk-w">End the mode</span>`;
    case "score": return html`<span class="bk-w">Score</span><${Slot} kind="num" value=${b.points} path=${[...path, "points"]} ed=${ed} /><span class="bk-w">points</span>`;
    case "set": return html`<span class="bk-w">Set</span><${Pick} value=${b.var} options=${ed.vars.map((v) => v.name)} missing="(no such variable)" onChange=${(v) => set("var", v)} />
      <span class="bk-w">to</span><${Slot} kind="num" value=${b.value} path=${[...path, "value"]} ed=${ed} />`;
    case "change": return html`<span class="bk-w">Change</span><${Pick} value=${b.var} options=${ed.vars.map((v) => v.name)} missing="(no such variable)" onChange=${(v) => set("var", v)} />
      <span class="bk-w">by</span><${Slot} kind="num" value=${b.by} path=${[...path, "by"]} ed=${ed} />`;
    case "callout": {
      const opts = (ed.ch.callouts || []).map((c) => ({ value: c.role || String(c.id), label: c.label }));
      const cur = b.role || (b.id != null ? String(b.id) : "");
      return html`<span class="bk-w">Say</span><${Pick} value=${cur} options=${opts}
        onChange=${(v) => { const c = (ed.ch.callouts || []).find((x) => (x.role || String(x.id)) === v);
          ed.edit((d) => { const t = at(d, path); delete t.role; delete t.id; if (c && c.role) t.role = c.role; else t.id = Number(v); }); }} />`;
    }
    case "words": return html`<span class="bk-w">Show</span><${Text} value=${b.text} onChange=${(v) => set("text", v)} placeholder="words" />
      <span class="bk-w">and</span><${Slot} kind="num" optional value=${b.value} path=${[...path, "value"]} ed=${ed} /><span class="bk-w">on its screen</span>`;
    case "light_shot": return html`<span class="bk-w">Light</span><${Pick} value=${b.shot} options=${shots} onChange=${(v) => set("shot", v)} />
      <input type="color" class="bk-color" value=${b.color || "#ffd000"} onInput=${(e) => set("color", e.target.value)} ...${tip("The insert's colour")} />
      <${Pick} value=${b.pattern} options=${PATTERNS} title=${b.pattern === "hurry" ? TIP.hurry : undefined} onChange=${(v) => set("pattern", v)} />
      ${PACED.includes(b.pattern) ? html`<span class="bk-w" ...${tip(TIP.rate)}>every</span><${Slot} kind="num" optional empty="its usual pace"
        value=${b.rate} path=${[...path, "rate"]} ed=${ed} /><span class="bk-w">ms</span>` : null}`;
    case "show": {
      const shows = (ed.ch.light || {}).shows || [];
      const pick = (v) => ed.edit((d) => {
        const t = at(d, path);
        if (v === "own") {
          const from = shows.find((x) => x.key === t.show) || shows[0];
          if (!(t.steps || []).length) t.steps = clone((from || {}).steps || []);
        } else delete t.steps;
        t.show = v;
      });
      return html`<span class="bk-w" ...${tip(TIP.show)}>Run the light show</span><${Pick} value=${b.show}
        options=${[...shows.map((x) => [x.key, x.label]), ["own", "its own steps…"]]} onChange=${pick} />`;
    }
    case "lights_off": return html`<span class="bk-w">Hand back the lights of</span><${Pick} value=${b.shot} options=${[["*", "every shot"], ...shots.map((n) => [n, n])]} onChange=${(v) => set("shot", v)} />`;
    case "add_time": return html`<span class="bk-w" ...${tip(TIP.addTime)}>Add</span><${Slot} kind="num" value=${b.seconds} path=${[...path, "seconds"]} ed=${ed} /><span class="bk-w">seconds</span>`;
    case "set_time": return html`<span class="bk-w" ...${tip(TIP.setTime)}>Set the clock to</span><${Slot} kind="num" value=${b.seconds} path=${[...path, "seconds"]} ed=${ed} /><span class="bk-w">seconds</span>`;
    case "multiball": return html`<span class="bk-w">Multiball of</span><${Num} value=${b.balls} width=${44} onChange=${(v) => set("balls", v)} />
      <span class="bk-w">balls, ball save</span><${Num} value=${b.save} width=${44} onChange=${(v) => set("save", v)} /><span class="bk-w">s</span>`;
    case "log": return html`<span class="bk-w">Write</span><${Text} value=${b.text} onChange=${(v) => set("text", v)} placeholder="a line" /><span class="bk-w">in the log</span>`;
    case "hud_text": return html`<span class="bk-w">Show</span><${Text} value=${b.text} max=${40} width=${220} onChange=${(v) => set("text", v)} placeholder="words" />
      <span class="bk-w">and</span><${Slot} kind="num" optional value=${b.value} path=${[...path, "value"]} ed=${ed} />
      <span class="bk-w">as the HUD's</span><${Pick} value=${b.which} options=${WHICH} onChange=${(v) => set("which", v)} />`;
    case "hud_counter": return html`<span class="bk-w">Set the HUD's</span><${Pick} value=${b.counter} options=${COUNTERS}
        onChange=${(v) => set("counter", Number(v))} /><span class="bk-w">to</span><${Slot} kind="num" value=${b.value} path=${[...path, "value"]} ed=${ed} />
      <${Check} checked=${b.sub != null} label="and its line to" onChange=${(on) => set("sub", on ? "" : null)} />
      ${b.sub != null ? html`<${Text} value=${b.sub} max=${16} width=${120} onChange=${(v) => set("sub", v)} placeholder="words" />` : null}`;
    case "hud_gauge": return html`<span class="bk-w">Fill the HUD's gauge to</span><${Slot} kind="num" value=${b.value} path=${[...path, "value"]} ed=${ed} /><span class="bk-w">pips</span>`;
    case "hud_award": return html`<span class="bk-w" ...${tip(TIP.hudAward)}>Award</span><${Text} value=${b.text} max=${40} width=${120} onChange=${(v) => set("text", v)} placeholder="words" />
      <span class="bk-w">and</span><${Slot} kind="num" optional value=${b.value} path=${[...path, "value"]} ed=${ed} />
      <span class="bk-w">over</span><${Text} value=${b.sub} max=${40} width=${120} onChange=${(v) => set("sub", v)} placeholder="a smaller line" />
      <span class="bk-w">for</span><${Num} value=${b.seconds} width=${40} onChange=${(v) => set("seconds", v)} /><span class="bk-w">s</span>`;
    case "timer_start": return html`<span class="bk-w" ...${tip(TIP.timerStart)}>Start timer</span><${TimerPick} value=${b.timer} ed=${ed} onChange=${(v) => set("timer", v)} />
      <span class="bk-w">at</span><${Slot} kind="num" value=${b.ms} path=${[...path, "ms"]} ed=${ed} /><span class="bk-w">ms</span>`;
    case "timer_stop": return html`<span class="bk-w">Stop timer</span><${TimerPick} value=${b.timer} ed=${ed} onChange=${(v) => set("timer", v)} />`;
    case "clip": return html`<span class="bk-w">Play the clip</span><${Pick} value=${b.clip} options=${(ed.prog.clips || []).map((x) => x.name)} missing="(not one of its own)" onChange=${(v) => set("clip", v)} />
      <${Pick} value=${b.where} options=${CLIP_WHERE} title=${TIP.where} onChange=${(v) => set("where", v)} />`;
    case "sound": {
      const opts = [["-", "nothing"], ...(ed.ch.callouts || []).map((c) => [c.role || String(c.id), c.label])];
      const cur = b.fallback == null || b.fallback === "" ? "-" : String(b.fallback);
      return html`<span class="bk-w">Play the sound</span><${Pick} value=${b.sound} options=${(ed.prog.sounds || []).map((x) => x.name)} missing="(not one of its own)" onChange=${(v) => set("sound", v)} />
        <span class="bk-w" ...${tip(TIP.fallback)}>else say</span><${Pick} value=${cur} options=${opts} title=${TIP.fallback}
          onChange=${(v) => set("fallback", v === "-" ? null : (/^[0-9]+$/.test(v) ? Number(v) : v))} />`;
    }
    case "hold": return html`<span class="bk-w" ...${tip(TIP.hold)}>Hold the</span><${Pick} value=${b.what}
        options=${(ed.ch.mechs || []).map((m) => [m.name, m.label])} missing="(not on this game)" onChange=${(v) => set("what", v)} />
      <span class="bk-w">for</span><${Slot} kind="num" value=${b.ms} path=${[...path, "ms"]} ed=${ed} /><span class="bk-w">ms</span>`;
    case "scoop_hold": return html`<span class="bk-w" ...${tip(TIP.scoopHold)}>Hold</span><${Pick} value=${b.which || "next"} options=${SCOOP_WHICH} onChange=${(v) => set("which", v)} />
      <span class="bk-w">in the scoop for</span><${Slot} kind="num" value=${b.ms} path=${[...path, "ms"]} ed=${ed} /><span class="bk-w">ms</span>`;
    case "let_go": return html`<span class="bk-w" ...${tip(TIP.letGo)}>Let go of</span><${Pick} value=${b.what}
        options=${[["*", "everything it holds"], ...(ed.ch.mechs || []).map((m) => [m.name, "the " + m.label]), ["scoop", "the scoop"]]}
        missing="(not on this game)" onChange=${(v) => set("what", v)} />`;
    case "game_show": {
      // PAD-418: by the port's name, grouped by its kind for it
      const groups = { flashy: "Flashy (a start)", subdued: "Subdued (an end)", accent: "Accent (a moment)" };
      const opts = Object.keys(groups).flatMap((k) => (ed.ch.game_shows || []).filter((x) => x.kind === k)
        .map((x) => ({ value: x.name, label: `${x.name} (${x.secs} s)`, group: groups[k] })));
      return html`<span class="bk-w" ...${tip(TIP.gameShow)}>Play the game's light show</span><${Pick} value=${b.name}
        options=${opts} missing="(not on this game)" width=${200} onChange=${(v) => set("name", v)} />`;
    }
    case "game_wizard": {
      // PAD-436: by the port's name; lit for the game's start shot, or started at once
      const shotWord = ed.ch.wizard_shot ? `the ${ed.ch.wizard_shot} starts it` : "its start shot starts it";
      return html`<${Pick} value=${b.how || "light"} options=${[["light", "Light"], ["start", "Start"]]} onChange=${(v) => set("how", v)} />
        <span class="bk-w" ...${tip(TIP.gameWizard)}>the game's mini-wizard</span><${Pick} value=${b.name}
        options=${(ed.ch.game_wizards || []).map((w) => [w.name, w.film ? `${w.name} (${w.film})` : w.name])} missing="(not on this game)" width=${260}
        onChange=${(v) => set("name", v)} />${(b.how || "light") === "light" ? html`<span class="bk-w">: ${shotWord}</span>` : null}`;
    }
    case "shield": return html`<span class="bk-w" ...${tip(TIP.shield)}>Turn the shield targets</span><${Pick} value=${b.where || "toward"} options=${SHIELD_WHERE} onChange=${(v) => set("where", v)} />`;
    case "shake": return html`<span class="bk-w" ...${tip(TIP.shake)}>Shake the cabinet:</span><${Pick} value=${b.strength || "hard"} options=${shakeStrengths(ed.ch)} missing="(not on this game)" onChange=${(v) => set("strength", v)} />
      <span class="bk-w">shake for</span><${Slot} kind="num" value=${b.ms} path=${[...path, "ms"]} ed=${ed} /><span class="bk-w">ms</span>`;
    case "shake_game": return html`<span class="bk-w" ...${tip(TIP.shakeGame)}>Shake the cabinet with</span><${Pick} value=${b.shake}
        options=${(ed.ch.shakes || []).map((m) => [m.name, m.label])} missing="(not on this game)" onChange=${(v) => set("shake", v)} />`;
    default: return html`<span class="bk-w">${b.op}</span>`;
  }
}

function Stmt({ b, path, ed }) {
  const [stack, i] = [path.slice(0, -1), path[path.length - 1]];
  // only the grip drags (a drag that starts in a box would steal its text selection)
  const grip = html`<span class="bk-grip" draggable="true" aria-hidden="true" ...${tip("Drag to move this block")}
    onDragStart=${(e) => { e.stopPropagation(); dragging = { from: stack, i }; e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "block"); const el = e.currentTarget.closest(".bk"); if (el) e.dataTransfer.setDragImage(el, 12, 12); }}
    onDragEnd=${() => { dragging = null; ed.setOver(null); }}>⋮⋮</span>`;
  if (b.op === "if") {
    return html`<div class="bk bk-flow bk-c">
      <div class="bk-line">${grip}<span class="bk-w b">If</span>
        <${Slot} kind="bool" value=${b.cond} path=${[...path, "cond"]} ed=${ed} /><span class="bk-w">then</span>
        <span class="sp"></span>
        <${Check} checked=${Array.isArray(b.else)} label="else" onChange=${(on) => ed.set([...path, "else"], on ? (b.else || []) : null)} />
        <${X} onClick=${() => ed.remove(stack, i)} /></div>
      <div class="bk-in"><${Stack} list=${b.then || []} path=${[...path, "then"]} ed=${ed} /></div>
      ${Array.isArray(b.else) ? html`<div class="bk-line bk-else"><span class="bk-w b">else</span></div>
        <div class="bk-in"><${Stack} list=${b.else} path=${[...path, "else"]} ed=${ed} /></div>` : null}
      <div class="bk-foot"></div>
    </div>`;
  }
  return html`<div class=${cx("bk", "bk-" + (STMT_CLASS[b.op] || "show"))}>
    <div class="bk-line">${grip}<${StmtBody} b=${b} path=${path} ed=${ed} />
      <span class="sp"></span><${X} onClick=${() => ed.remove(stack, i)} /></div>
    ${b.op === "show" && b.show === "own" ? html`<${ShowSteps} steps=${b.steps || []} path=${[...path, "steps"]} ed=${ed} />` : null}
  </div>`;
}

// A Light show block's own steps: one line each, in the order they run.
const SHOW_STEPS = 10;
function ShowSteps({ steps, path, ed }) {
  const light = ed.ch.light || {};
  const move = (i, dir) => ed.edit((d) => { const l = at(d, path); const [x] = l.splice(i, 1); l.splice(i + dir, 0, x); });
  const add = () => ed.edit((d) => {
    const l = at(d, path);
    l.push(l.length ? clone(l[l.length - 1]) : { fx: "burst", ms: 800, a: "#ffffff", b: "#ffb000", at: "center", rate: 0, gi: "keep" });
  });
  return html`<div class="bk-steps" ...${tip(TIP.ownShow)}>
    ${steps.map((st, i) => {
      const p = [...path, i];
      const set = (k, v) => ed.set([...p, k], v);
      return html`<div class="bk-line bk-step" key=${i}>
        <span class="bk-w">${i + 1}.</span>
        <${Pick} value=${st.fx} options=${light.fx || []} width=${140} onChange=${(v) => set("fx", v)} />
        <${Num} value=${st.ms} width=${52} title="How long this step lasts, ms" onChange=${(v) => set("ms", v)} /><span class="bk-w">ms</span>
        <input type="color" class="bk-color" value=${st.a || "#ffffff"} onInput=${(e) => set("a", e.target.value)} ...${tip("Its first colour")} />
        <input type="color" class="bk-color" value=${st.b || "#000000"} onInput=${(e) => set("b", e.target.value)} ...${tip("Its second colour")} />
        <span class="bk-w">at</span><${Pick} value=${st.at || "center"} options=${light.places || []} width=${104} onChange=${(v) => set("at", v)} />
        <span class="bk-w" ...${tip(TIP.stepRate)}>pace</span><${Num} value=${st.rate ?? 0} width=${44} title=${TIP.stepRate} onChange=${(v) => set("rate", v)} />
        <${Pick} value=${st.gi || "keep"} options=${light.gi || []} width=${118} title=${TIP.gi} onChange=${(v) => set("gi", v)} />
        <button type="button" class="bk-x" disabled=${i === 0} aria-label="Move this step up" ...${tip("Move this step up")} onClick=${() => move(i, -1)}>↑</button>
        <button type="button" class="bk-x" disabled=${i === steps.length - 1} aria-label="Move this step down" ...${tip("Move this step down")} onClick=${() => move(i, 1)}>↓</button>
        <${X} title="Take this step out" onClick=${() => ed.edit((d) => { at(d, path).splice(i, 1); })} />
      </div>`;
    })}
    ${steps.length < SHOW_STEPS ? html`<button type="button" class="bk-add" onClick=${add} ...${tip("Add a step at the end of the show")}>+ step</button>` : null}
  </div>`;
}

// A drop line between two blocks of a stack: lit while a block is dragged over it.
function Gap({ path, i, ed }) {
  const lit = ed.over && samePath(ed.over.path, path) && ed.over.i === i;
  const ok = () => dragging && (dragging.tpl ? !!dragging.tpl.op : !(dragging.from && within(path, [...dragging.from, dragging.i])));
  return html`<div class=${cx("bk-gap", lit && "on")}
    onDragOver=${(e) => { if (!ok()) return; e.preventDefault(); e.stopPropagation(); if (!lit) ed.setOver({ path, i }); }}
    onDrop=${(e) => { if (!ok()) return; e.preventDefault(); e.stopPropagation(); ed.dropAt(path, i); }}></div>`;
}

function Stack({ list, path, ed }) {
  const picked = samePath(ed.target, path);
  return html`<div class=${cx("bk-stack", picked && "picked", !list.length && "bk-empty")} onClick=${(e) => { e.stopPropagation(); ed.setTarget(path); }}>
    <${Gap} path=${path} i=${0} ed=${ed} />
    ${list.map((b, i) => html`<div key=${i}><${Stmt} b=${b} path=${[...path, i]} ed=${ed} /><${Gap} path=${path} i=${i + 1} ed=${ed} /></div>`)}
    <button type="button" class="bk-add" onClick=${(e) => { e.stopPropagation(); ed.setTarget(path); openMenu(e.currentTarget, addMenu(ed, path)); }}
      ...${tip("Add a block at the end of this stack")}>+ ${list.length ? "" : "add a block"}</button>
  </div>`;
}

function addMenu(ed, path) {
  const out = [];
  stmtTemplates(ed.ch, ed.vars, ed.prog).filter(([_g, items]) => items.length).forEach(([group, items], gi) => {
    if (gi) out.push({ sep: true });
    out.push({ header: group });
    items.forEach((t) => out.push({ label: stmtLabel(t), onClick: () => ed.insert(path, at(ed.prog, path).length, clone(t)) }));
  });
  return out;
}

// ------------------------------------------------------------------ scripts
function HatBody({ h, path, ed }) {
  const set = (k, v) => ed.set([...path, k], v);
  const when = html`<${Pick} value=${h.when || "any"} options=${WHEN} onChange=${(v) => set("when", v)} />`;
  switch (h.kind) {
    case "mode_start": return html`<span class="bk-w b">When the mode starts</span>`;
    case "mode_end": return html`<span class="bk-w b">When the mode ends</span>`;
    case "ball_end": return html`<span class="bk-w b">When the ball drains</span>`;
    case "shot": return html`<span class="bk-w b">When</span><${Pick} value=${h.shot} options=${ed.ch.shots || []} onChange=${(v) => set("shot", v)} /><span class="bk-w b">is made</span>${when}`;
    case "any_shot": return html`<span class="bk-w b">When any shot is made</span>${when}`;
    case "every": return html`<span class="bk-w b">Every</span><${Num} value=${h.seconds} width=${48} onChange=${(v) => set("seconds", v)} /><span class="bk-w b">seconds while it runs</span>`;
    case "seconds_left": return html`<span class="bk-w b">When</span><${Num} value=${h.seconds} width=${48} onChange=${(v) => set("seconds", v)} /><span class="bk-w b">seconds are left</span>`;
    case "event": return html`<span class="bk-w b">When</span><${Pick} value=${h.event} options=${(ed.ch.events || []).map((x) => [x.name, x.label])} onChange=${(v) => set("event", v)} />${when}`;
    case "timer_done": return html`<span class="bk-w b">When timer</span><${TimerPick} value=${h.timer} ed=${ed} onChange=${(v) => set("timer", v)} /><span class="bk-w b">runs out</span>`;
    default: return html`<span class="bk-w b">${h.kind}</span>`;
  }
}

function Script({ s, si, n, ed }) {
  return html`<div class="bk-script">
    <div class="bk bk-hat"><div class="bk-line">
      <${HatBody} h=${s.hat || {}} path=${["scripts", si, "hat"]} ed=${ed} />
      <span class="sp"></span>
      <button type="button" class="bk-x" disabled=${si === 0} aria-label="Move this script up" ...${tip("Move this script up")} onClick=${() => ed.moveScript(si, -1)}>↑</button>
      <button type="button" class="bk-x" disabled=${si === n - 1} aria-label="Move this script down" ...${tip("Move this script down")} onClick=${() => ed.moveScript(si, 1)}>↓</button>
      <${X} title="Take this script out, with its blocks" onClick=${() => ed.removeScript(si)} />
    </div></div>
    <div class="bk-body"><${Stack} list=${s.do || []} path=${["scripts", si, "do"]} ed=${ed} /></div>
  </div>`;
}

// ------------------------------------------------------------------ the palette
function hatLabel(h) {
  return { mode_start: "When the mode starts", mode_end: "When the mode ends", shot: "When a shot is made",
    any_shot: "When any shot is made", every: "Every N seconds", seconds_left: "When N seconds are left",
    ball_end: "When the ball drains", event: "When the game does…", timer_done: "When a timer runs out" }[h.kind] || h.kind;
}

function stmtLabel(b) {
  return { start_mode: "Start the mode", end_mode: "End the mode", add_time: "Add seconds", set_time: "Set the clock", multiball: "Multiball",
    score: "Score points", set: "Set a variable", change: "Change a variable", callout: "Say a callout",
    words: "Show words", light_shot: "Light a shot", lights_off: "Hand back lights", show: "Run a light show", game_show: "Play the game's light show", log: "Write in the log",
    clip: "Play a clip", sound: "Play a sound",
    hud_text: "Show on the HUD", hud_counter: "Set a counter", hud_gauge: "Fill the gauge", hud_award: "Award line",
    timer_start: "Start a timer", timer_stop: "Stop a timer",
    hold: "Hold a mechanism", scoop_hold: "Hold a ball in the scoop", let_go: "Let go", shield: "Turn the shield targets",
    shake: "Shake the cabinet for", shake_game: "Shake it the game's way", game_wizard: "The game's mini-wizard",
    if: b.else ? "If … else" : "If" }[b.op] || b.op;
}

// PAD-420: a mechanism block for hardware this machine does not have is left out of the palette
function machineLacks(t, ch) {
  const no = new Set(ch.absent || []);
  if (t.op === "hold") return no.has("magnet") && no.has("coils");
  if (t.op === "scoop_hold") return no.has("scoop");
  if (t.op === "let_go") return no.has("magnet") && no.has("coils") && no.has("scoop");
  if (t.op === "shield") return no.has("shield");
  if (t.op === "shake" || t.op === "shake_game") return no.has("shaker");
  return false;
}

// PAD-395: why a palette block cannot be used on this card's game ("" = it can)
function whyOff(t, ch) {
  if (t.op === "hold") return ch.mechs_off || "";
  if (t.op === "scoop_hold") return ch.scoop_off || "";
  if (t.op === "let_go") return ch.mechs_off && ch.scoop_off ? ch.mechs_off : "";
  if (t.op === "shield") return ch.shield_off || "";
  if (t.op === "shake" || t.op === "shake_game") return ch.shaker_off || "";   // PAD-414
  if (t.op === "game_show") return ch.game_shows_off || "";   // PAD-418
  if (t.op === "game_wizard") return ch.game_wizards_off || "";   // PAD-436
  return "";
}

function Palette({ ed }) {
  const piece = (cls, label, tpl, onPress, title, off) => html`<button type="button" class=${cx("bk-pal", cls)} draggable=${off ? "false" : "true"}
    aria-disabled=${off ? "true" : undefined}
    onDragStart=${(e) => { if (off) { e.preventDefault(); return; } dragging = { tpl: clone(tpl) }; e.dataTransfer.effectAllowed = "copy"; e.dataTransfer.setData("text/plain", "block"); }}
    onDragEnd=${() => { dragging = null; ed.setOver(null); }}
    onClick=${off ? null : onPress} ...${tip(off || title || TIP.palette)}>${label}</button>`;
  const vals = valueTemplates(ed.ch, ed.vars, ed.timers);
  return html`<div class="bk-palette" aria-label="Blocks">
    <div class="bk-pal-h">When</div>
    ${hatTemplates(ed.ch, ed.timers).map((h) => piece("bk-hat", hatLabel(h), { hat: h }, () => ed.addScript(clone(h)), "Press to start a new script with this"))}
    ${stmtTemplates(ed.ch, ed.vars, ed.prog).filter(([_g, items]) => items.length).map(([group, items]) => html`<div class="bk-pal-h">${group}</div>
      ${items.map((t) => piece("bk-" + (STMT_CLASS[t.op] || "show"), stmtLabel(t), t, () => ed.addToTarget(clone(t)), null, whyOff(t, ed.ch)))}`)}
    <div class="bk-pal-h">Values</div>
    ${vals.map((t) => piece("bk-num", VALUE_WORDS[t.k], t, null, "Drag into a value slot (the round holes)"))}
    <div class="bk-pal-h">Conditions</div>
    ${condTemplates().map((t) => piece("bk-bool", COND_WORDS[t.k], t, null, "Drag into an If's condition slot"))}
  </div>`;
}

// ------------------------------------------------------------------ the HUD (PAD-375)
function Hud({ prog, ed }) {
  const h = prog.hud || {};
  const can = ed.ch.hud !== false;
  const icons = ed.ch.icons || ["xilien"];
  const counters = h.counters || [{}, {}, {}];
  const timer = h.timer || {};
  const gauge = h.gauge || {};
  const at_ = (...k) => ["hud", ...k];
  return html`<div class="bk bk-hud bk-hudset">
    <div class="bk-line"><span class="bk-w b" ...${tip(TIP.hud)}>Its HUD</span>
      <span class="bk-w">${prog.name || "its name"}, and under it</span>
      <${Text} value=${h.line} max=${40} width=${340} title=${TIP.hudLine} onChange=${(v) => ed.set(at_("line"), v)} placeholder="what to shoot" />
      ${can ? null : html`<span class="bk-w small" ...${tip(TIP.hudOff)}>(not on this card's game)</span>`}</div>
    ${counters.map((c, k) => html`<div class="bk-line" key=${k}>
      <span class="bk-w" ...${tip(TIP.counter)}>Counter ${k + 1}</span>
      <${Text} value=${c.label} max=${16} width=${120} onChange=${(v) => ed.set(at_("counters", k, "label"), v)} placeholder="its label" />
      <span class="bk-w">shows</span><${Slot} kind="num" value=${c.value} path=${at_("counters", k, "value")} ed=${ed} empty="(set by a block)" />
      <span class="bk-w">over</span><${Text} value=${c.sub} max=${16} width=${120} onChange=${(v) => ed.set(at_("counters", k, "sub"), v)} placeholder="a smaller line" />
    </div>`)}
    <div class="bk-line">
      <${Check} checked=${timer.on !== false} label="timer badge" title=${TIP.timer} onChange=${(v) => ed.set(at_("timer", "on"), v)} />
      ${timer.on !== false ? html`<${Text} value=${timer.label} max=${12} width=${110} onChange=${(v) => ed.set(at_("timer", "label"), v)} placeholder=${(prog.name || "").slice(0, 12) || "its label"} />
        <${Pick} value=${timer.icon} options=${icons} onChange=${(v) => ed.set(at_("timer", "icon"), v)} title="Its icon" />` : null}
    </div>
    <div class="bk-line">
      <${Check} checked=${!!gauge.on} label="gauge" title=${TIP.gauge} onChange=${(v) => ed.set(at_("gauge", "on"), v)} />
      ${gauge.on ? html`<${Text} value=${gauge.label} max=${16} width=${110} onChange=${(v) => ed.set(at_("gauge", "label"), v)} placeholder="its label" />
        <span class="bk-w">of</span><${Num} value=${gauge.count} width=${40} onChange=${(v) => ed.set(at_("gauge", "count"), v)} />
        <${Pick} value=${gauge.kind} options=${GAUGES} onChange=${(v) => ed.set(at_("gauge", "kind"), v)} />
        <input type="color" class="bk-color" value=${gauge.color || "#ff7800"} onInput=${(e) => ed.set(at_("gauge", "color"), e.target.value)} ...${tip("The lit pips' colour")} />
        <span class="bk-w" ...${tip(TIP.gaugeFollows)}>lit to</span><${Slot} kind="num" value=${gauge.value} path=${at_("gauge", "value")} ed=${ed} empty="(set by a block)" />` : null}
    </div>
  </div>`;
}

// ------------------------------------------------------------------ the whole editor
function Variables({ prog, ed }) {
  const vars = prog.vars || [];
  const add = () => {
    let n = 1;
    while (vars.some((v) => (v.name || "").toLowerCase() === ("count " + n))) n++;
    ed.edit((d) => { d.vars = [...(d.vars || []), { name: "count " + n, reset: "ball" }]; });
  };
  return html`<div class="bk-vars">
    <span class="lbl" ...${tip(TIP.vars)}>Variables</span>
    ${vars.map((v, i) => html`<span class="bk-varbox" key=${i}>
      <${Field} sm width=${110} value=${v.name} maxLength=${24} onChange=${(t) => ed.renameVar(i, t)} title="Its name" />
      <span class="small muted">reset</span>
      <${Select} sm value=${v.reset || "ball"} options=${(v.shared ? SHARED_RESETS : RESETS).map(([value, label]) => ({ value, label }))}
        onChange=${(r) => ed.set(["vars", i, "reset"], r)} />
      <${Check} checked=${!!v.shared} label="shared" title=${TIP.shared}
        onChange=${(on) => ed.edit((d) => { d.vars[i].shared = on; if (on && d.vars[i].reset === "mode") d.vars[i].reset = "game"; })} />
      <${X} title="Take this variable out" onClick=${() => ed.edit((d) => { d.vars.splice(i, 1); })} />
    </span>`)}
    <${Button} size="sm" kind="ghost" icon="plus" onClick=${add}>Variable<//>
  </div>`;
}

function Timers({ prog, ed }) {
  const timers = prog.timers || [];
  const add = () => {
    let n = 1;
    while (timers.some((t) => (t.name || "").toLowerCase() === ("timer " + n))) n++;
    ed.edit((d) => { d.timers = [...(d.timers || []), { name: "timer " + n }]; });
  };
  return html`<div class="bk-vars">
    <span class="lbl" ...${tip(TIP.timers)}>Timers</span>
    ${timers.map((t, i) => html`<span class="bk-varbox timer" key=${i}>
      <${Field} sm width=${110} value=${t.name} maxLength=${24} onChange=${(name) => ed.renameTimer(i, name)} title="Its name" />
      <${X} title="Take this timer out" onClick=${() => ed.edit((d) => { d.timers.splice(i, 1); })} />
    </span>`)}
    <${Button} size="sm" kind="ghost" icon="plus" onClick=${add}>Timer<//>
  </div>`;
}

// PAD-373: what the mode does about the game's own modes, as the form asks it (PAD-363). No ticks
// saved = the title's usual ones, shown ticked; the last tick stays, so the list never goes back to
// those by itself.
function GameModes({ prog, ed }) {
  const ch = ed.ch;
  const gm = prog.game_modes || "block";
  const rows = ch.game_modes || [];
  const rules = ch.game_rules || [];                         // PAD-398
  const keep = new Set(prog.keep_rules || []);
  const keepTick = (n, v) => {
    const next = new Set(keep);
    if (v) next.add(n); else next.delete(n);
    ed.set(["keep_rules"], [...next].sort());
  };
  const on = new Set(prog.block_modes && prog.block_modes.length ? prog.block_modes : (ch.game_modes_default || []));
  const opts = [{ value: "stack", label: "may start (this one carries on)" },
    { value: "give_way", label: "may start, and end this one", disabled: !!ch.give_way_off && gm !== "give_way" },
    { value: "block", label: "cannot start (the ones ticked)", disabled: !!ch.block_off && gm !== "block" }];
  const tick = (id, v) => {
    const next = new Set(on);
    if (v) next.add(id); else next.delete(id);
    ed.set(["block_modes"], [...next].sort((a, b) => a - b));
  };
  const why = gm === "give_way" ? ch.give_way_off : gm === "block" ? (ch.block_off
    || (rows.length && !on.size ? "None ticked: none is held off, and one of them starting ends this mode." : "")) : "";
  return html`<div class="bk-gamemodes">
    <div class="row wrap">
      <span class="lbl" ...${tip(TIP.gameModes)}>While it runs, the game's modes</span>
      <${Select} sm value=${gm} options=${opts} width=${260} title=${TIP.gameModes} onChange=${(v) => ed.set(["game_modes"], v)} />
    </div>
    ${gm === "block" && rows.length ? html`<div class="modes-shots">
      ${rows.map((m) => {
        const last = on.size === 1 && on.has(m.id);
        return html`<${Check} key=${"b" + m.id} label=${m.label} checked=${on.has(m.id)} disabled=${last}
          title=${last ? TIP.blockLast : TIP.blockPick} onChange=${(v) => tick(m.id, v)} />`;
      })}
    </div>` : null}
    ${why ? html`<div class="small muted">${why}</div>` : null}
    ${gm === "block" && rules.length ? html`
      <div class="row wrap"><span class="lbl" ...${tip(TIP.keepRule)}>The game's features that keep counting while it runs</span></div>
      <div class="modes-shots">
        ${rules.map((n) => html`<${Check} key=${"k" + n} label=${n} checked=${keep.has(n)} title=${TIP.keepRule}
          onChange=${(v) => keepTick(n, v)} />`)}
      </div>
      <div class="small muted">${keep.size ? "The ones ticked go on counting; every other feature of the game's waits until this mode ends." : "None ticked: only this mode counts while it runs."}</div>` : null}
  </div>`;
}

// PAD-374: the mode's own clips, sounds and music: each a file in its folder and a name.
function OwnMedia({ prog, ed, s, folder }) {
  const ch = ed.ch;
  const clips = prog.clips || [];
  const sounds = prog.sounds || [];
  const sep = String(folder || "").includes("/") ? "/" : "\\";
  const pathOf = (f) => (folder && f ? folder + sep + f : "");
  const pick = async (what) => {
    const got = await call("modes.blocks_pick", what, (what === "clip" ? clips : sounds).map((x) => x.name));
    if (!got) return;
    ed.edit((d) => {
      if (what === "music") d.music = got.file;
      else if (what === "clip") d.clips = [...(d.clips || []), { name: got.name, file: got.file }];
      else d.sounds = [...(d.sounds || []), { name: got.name, file: got.file, priority: 4 }];
    });
  };
  const name = (kind, i, x) => html`<${Field} sm mono width=${104} value=${x.name} maxLength=${15} title=${TIP.name}
    onChange=${(t) => ed.renameMedia(kind, i, String(t).toLowerCase())} />`;
  const file = (f) => html`<span class="small dim ellip bk-file" ...${tip(pathOf(f))}>${f}</span>`;
  return html`<div class="bk-vars bk-media">
    <span class="lbl" ...${tip(TIP.own)}>Its own clips and sounds</span>
    ${clips.map((x, i) => html`<span class="bk-varbox bk-ownbox" key=${"c" + i}>
      <span class="small muted">clip</span>${name("clips", i, x)}${file(x.file)}
      ${s._showClip ? html`<${Button} size="xs" kind="ghost" icon="play" onClick=${() => s._showClip(pathOf(x.file), x.name)}>Play<//>` : null}
      <${X} title="Take this clip out (its file stays in the folder)" onClick=${() => ed.edit((d) => { d.clips.splice(i, 1); })} />
    </span>`)}
    ${sounds.map((x, i) => html`<span class="bk-varbox bk-ownbox" key=${"s" + i}>
      <span class="small muted">sound</span>${name("sounds", i, x)}${file(x.file)}
      <${Select} sm value=${String(x.priority || 4)} options=${PRIORITIES.map(([value, label]) => ({ value, label }))} title=${TIP.priority}
        onChange=${(v) => ed.set(["sounds", i, "priority"], Number(v))} />
      <${PlayButton} path=${pathOf(x.file)} />
      <${X} title="Take this sound out (its file stays in the folder)" onClick=${() => ed.edit((d) => { d.sounds.splice(i, 1); })} />
    </span>`)}
    ${prog.music ? html`<span class="bk-varbox bk-ownbox" ...${tip(TIP.music)}>
      <span class="small muted">music</span>${file(prog.music)}<${PlayButton} path=${pathOf(prog.music)} />
      <${X} title="No music of its own (the game's plays on)" onClick=${() => ed.set(["music"], "")} />
    </span>` : null}
    <${Button} size="sm" kind="ghost" icon="plus" disabled=${!!ch.why_clip} title=${ch.why_clip || "Pick a video for the mode to play (it is copied into its folder)."} onClick=${() => pick("clip")}>Clip…<//>
    <${Button} size="sm" kind="ghost" icon="plus" disabled=${!!ch.why_sound} title=${ch.why_sound || "Pick a WAV for the mode to play (it is copied into its folder)."} onClick=${() => pick("sound")}>Sound…<//>
    ${prog.music ? null : html`<${Button} size="sm" kind="ghost" icon="plus" disabled=${!!ch.why_music} title=${ch.why_music || TIP.music} onClick=${() => pick("music")}>Music…<//>`}
  </div>`;
}

export function BlocksEditor({ s, c }) {
  const b = c.blocks || {};
  const [prog, setProg] = useState(() => clone(b.program || {}));
  const [target, setTarget] = useState(null);
  const [over, setOver] = useState(null);
  const [saving, setSaving] = useState(false);
  const timer = useRef(null);
  const slugRef = useRef(c.slug);
  const progRef = useRef(prog);
  // the steps back and forward; key + when: the last change's box, to fold typing into one step
  const hist = useRef({ past: [], future: [], key: null, when: 0 });
  // another mode opened (or this one duplicated, or put back by Python): take its program
  useEffect(() => {
    slugRef.current = c.slug;
    progRef.current = clone(b.program || {});
    hist.current = { past: [], future: [], key: null, when: 0 };
    setProg(progRef.current); setTarget(null);
  }, [c.slug]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const save = (next) => {
    clearTimeout(timer.current);
    setSaving(true);
    const slug = slugRef.current;
    timer.current = setTimeout(() => {
      Promise.resolve(call("modes.blocks_save", slug, next)).finally(() => setSaving(false));
    }, SAVE_MS);
  };
  const show = (next) => { progRef.current = next; setProg(next); save(next); };
  // key: the box changed, so a run of changes to it is one step (none = a step of its own)
  const edit = (fn, key = null) => {
    const was = progRef.current;
    const d = clone(was);
    fn(d);
    if (JSON.stringify(d) === JSON.stringify(was)) return;      // a box giving back what it had
    const h = hist.current, now = Date.now();
    if (!(key && key === h.key && now - h.when < MERGE_MS)) {
      h.past.push(was);
      if (h.past.length > UNDO_STEPS) h.past.shift();
    }
    h.future = [];
    h.key = key;
    h.when = now;
    show(d);
  };
  const undo = (redo = false) => {
    const h = hist.current;
    const [from, to] = redo ? [h.future, h.past] : [h.past, h.future];
    if (!from.length) return;
    to.push(progRef.current);
    h.key = null;
    const p = from.pop();
    show(p);
    setTarget((t) => (t && Array.isArray(at(p, t)) ? t : null));
  };
  const undoRef = useRef(undo);
  undoRef.current = undo;
  useEffect(() => {
    const onKey = (e) => {
      if (document.querySelector(".scrim, .menu")) return;          // a window or a menu is open
      const redo = undoKeyOf(e);
      if (redo == null) return;
      e.preventDefault();
      e.stopPropagation();
      undoRef.current(redo);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const ed = {
    prog, ch: b.choices || {}, vars: prog.vars || [], timers: prog.timers || [], target, over, setOver,
    setTarget, edit,
    set: (path, v) => edit((d) => put(d, path, v), path.join("/")),
    remove: (stack, i) => edit((d) => { at(d, stack).splice(i, 1); }),
    insert: (stack, i, blk) => edit((d) => { at(d, stack).splice(i, 0, blk); }),
    addScript: (hat) => edit((d) => { d.scripts = [...(d.scripts || []), { hat, do: [] }]; setTarget(["scripts", d.scripts.length - 1, "do"]); }),
    addToTarget: (blk) => edit((d) => {
      let path = target && at(d, target) ? target : null;
      if (!path) {
        if (!(d.scripts || []).length) d.scripts = [{ hat: { kind: "mode_start" }, do: [] }];
        path = ["scripts", d.scripts.length - 1, "do"];
        setTarget(path);
      }
      at(d, path).push(blk);
    }),
    removeScript: (si) => edit((d) => { d.scripts.splice(si, 1); setTarget(null); }),
    moveScript: (si, dir) => edit((d) => { const [x] = d.scripts.splice(si, 1); d.scripts.splice(si + dir, 0, x); setTarget(null); }),
    renameVar: (i, name) => edit((d) => {
      const old = (d.vars[i] || {}).name;
      d.vars[i].name = name;
      // every block naming the variable follows it
      const walk = (o) => {
        if (Array.isArray(o)) { o.forEach(walk); return; }
        if (!o || typeof o !== "object") return;
        if ((o.op === "set" || o.op === "change") && o.var === old) o.var = name;
        if (o.k === "var" && o.name === old) o.name = name;
        Object.values(o).forEach(walk);
      };
      walk(d.scripts);
      walk(d.hud);                                                // PAD-375: what its counters and gauge follow
    }, "vars/" + i + "/name"),
    renameTimer: (i, name) => edit((d) => {
      const old = (d.timers[i] || {}).name;
      d.timers[i].name = name;
      // every block naming the timer follows it
      const walk = (o) => {
        if (Array.isArray(o)) { o.forEach(walk); return; }
        if (!o || typeof o !== "object") return;
        if (o.timer === old) o.timer = name;
        Object.values(o).forEach(walk);
      };
      walk(d.scripts);
    }, "timers/" + i + "/name"),
    // a clip or sound renamed: every block playing it follows it
    renameMedia: (kind, i, name) => edit((d) => {
      const old = (d[kind][i] || {}).name;
      d[kind][i].name = name;
      const op = kind === "clips" ? "clip" : "sound";
      const walk = (o) => {
        if (Array.isArray(o)) { o.forEach(walk); return; }
        if (!o || typeof o !== "object") return;
        if (o.op === op && o[op] === old) o[op] = name;
        Object.values(o).forEach(walk);
      };
      walk(d.scripts);
    }, kind + "/" + i + "/name"),
    dropAt: (path, i) => {
      const drag = dragging;
      dragging = null;
      setOver(null);
      if (!drag) return;
      if (drag.tpl && drag.tpl.op) { ed.insert(path, i, clone(drag.tpl)); setTarget(path); return; }
      if (!drag.from) return;
      edit((d) => {
        const src = at(d, drag.from);
        const [blk] = src.splice(drag.i, 1);
        let j = i;
        if (samePath(drag.from, path) && drag.i < i) j -= 1;       // the stack closed up above the gap
        at(d, path).splice(j, 0, blk);
      });
    },
  };
  // a hat dropped on the workspace starts a new script
  const wsDrop = {
    onDragOver: (e) => { if (dragging && dragging.tpl && dragging.tpl.hat) e.preventDefault(); },
    onDrop: (e) => { if (dragging && dragging.tpl && dragging.tpl.hat) { e.preventDefault(); ed.addScript(clone(dragging.tpl.hat)); dragging = null; } },
  };
  const scripts = prog.scripts || [];
  return html`<div class="bk-editor">
    <${Palette} ed=${ed} />
    <div class="bk-ws" ...${wsDrop} onClick=${() => setTarget(null)}>
      <div class="bk-bar row" onClick=${(e) => e.stopPropagation()}>
        <${Button} size="sm" kind="ghost" icon="undo" disabled=${!hist.current.past.length} title=${TIP.undo} onClick=${() => undo()}>Undo<//>
        <${Button} size="sm" kind="ghost" icon="redo" disabled=${!hist.current.future.length} title=${TIP.redo} onClick=${() => undo(true)}>Redo<//>
        <span class="sp"></span>
        <span class="small muted">${saving ? "Saving…" : "Saved · Try it builds it in"}</span>
      </div>
      <div class="bk-settings row wrap">
        <label class="lbl" for="bk-name">Name</label>
        <${Field} id="bk-name" sm width=${180} value=${prog.name || ""} maxLength=${40} onChange=${(t) => ed.set(["name"], t)} />
        <span class="lbl" ...${tip(TIP.seconds)}>Runs for</span>
        <${Num} value=${prog.seconds} width=${56} title=${TIP.seconds} onChange=${(v) => ed.set(["seconds"], v)} /><span class="small muted">seconds</span>
        <${Check} checked=${prog.ends_on_drain !== false} label="ends when the ball drains" title=${TIP.drain} onChange=${(v) => ed.set(["ends_on_drain"], v)} />
        <${Check} checked=${!!prog.screen} label="its own screen" title=${TIP.screen} onChange=${(v) => ed.set(["screen"], v)} />
        <${Check} checked=${!!prog.wait_multiball} label="waits out a multiball" title=${TIP.wait} onChange=${(v) => ed.set(["wait_multiball"], v)} />
        <span class="lbl" ...${tip(TIP.displayPriority)}>Display priority</span>
        <${Select} sm value=${String(prog.priority || 0)} title=${TIP.displayPriority} onChange=${(v) => ed.set(["priority"], Number(v))}
          options=${[...DISPLAY_PRIORITIES, ...(DISPLAY_PRIORITIES.some(([n]) => n === (prog.priority || 0)) ? [] : [[prog.priority, String(prog.priority)]])]
            .map(([value, label]) => ({ value: String(value),
              // PAD-375: a HUD keeps a priority of its own, so its words wait under the game's displays
              label: value === 0 && (prog.hud || {}).on ? "the HUD's (180)" : label }))} />
        <${Check} checked=${!!(prog.hud || {}).on} label="its HUD" title=${TIP.hud} onChange=${(v) => ed.set(["hud", "on"], v)} />
      </div>
      <${GameModes} prog=${prog} ed=${ed} />
      <${Variables} prog=${prog} ed=${ed} />
      <${Timers} prog=${prog} ed=${ed} />
      ${(prog.hud || {}).on ? html`<${Hud} prog=${prog} ed=${ed} />` : null}
      <${OwnMedia} prog=${prog} ed=${ed} s=${s} folder=${c.folder} />
      ${(b.notes || []).map((t) => html`<${Note} key=${t}>${t}<//>`)}
      <div class="bk-scripts">
        ${scripts.map((sc, si) => html`<${Script} key=${si} s=${sc} si=${si} n=${scripts.length} ed=${ed} />`)}
        <div class="bk-newscript small muted">${scripts.length ? "Drag a When block here, or press one on the left, for another script." : "Start with a When block from the left: drag it here or press it."}</div>
      </div>
    </div>
  </div>`;
}

// The C the blocks make, to read (and the way out to C for good).
export function BlocksCode({ c }) {
  const b = c.blocks || {};
  return html`<div class="stack" style="gap:10px">
    <div class="row wrap">
      <span class="small muted grow">What Try it and Write build: the Modes tab writes it again from the blocks at every change (modes/${c.slug}/${c.slug}.c).</span>
      <${Button} size="sm" icon="edit" title=${TIP.asC} onClick=${() => call("modes.blocks_to_code")}>Edit as C…<//>
    </div>
    <pre class="bk-c-src mono">${b.c || ""}</pre>
  </div>`;
}

export const BLOCKS_WORDS = {
  pick: "Snap blocks together: when a shot is made, score it; if a count gets high enough, start the mode. The app turns them into a mode in C for you.",
  newTip: "A mode built from blocks: rules like \"when Left ramp is made 3 times, start the mode\", snapped together. For what the form can't say, without writing C.",
};
