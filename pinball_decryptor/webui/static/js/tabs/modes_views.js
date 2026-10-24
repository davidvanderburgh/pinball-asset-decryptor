// Modes: what every view of a blocks mode reads off its program (PAD-612): which shots and lights it lights and in
// what color, which rules name a shot, and a rule's When in words. PAD-614: and what the Rule cards, Story, Shot
// table, Timeline and Node graph tabs place where: a block in words, the state a rule works in, a shot's cell, a
// moment on the clock, who uses a variable. No imports, so a test loads it alone.

// a When with a "while": the words modes_blocks.js WHEN gives it
const WHILE = { idle: ", while it is not running", running: ", while it runs" };

// every block of a stack, If's branches included
function eachStmt(list, fn) {
  (list || []).forEach((b) => {
    fn(b);
    if (b.op === "if") { eachStmt(b.then, fn); eachStmt(b.else, fn); }
  });
}

// every object of a script (its hat, blocks, values, conditions)
function eachPart(o, fn) {
  if (Array.isArray(o)) { o.forEach((x) => eachPart(x, fn)); return; }
  if (!o || typeof o !== "object") return;
  fn(o);
  Object.values(o).forEach((x) => eachPart(x, fn));
}

const insertNames = (b) => String(b.insert || "").split(",").map((n) => n.trim()).filter(Boolean);

// What the mode lights: {shots: {name: {color, pattern}}, lamps: {...}}, the first block's color for each
export function lights(prog) {
  const shots = {}, lamps = {};
  const note = (map, name, color, pattern) => { if (name && name !== "*" && !map[name]) map[name] = { color, pattern }; };
  (prog.scripts || []).forEach((sc) => eachStmt(sc.do, (b) => {
    if (b.op === "light_shot") {
      const color = b.pattern === "off" ? "" : (b.color || "#ffd000");
      if (b.insert) note(lamps, b.insert, color, b.pattern); else note(shots, b.shot, color, b.pattern);
    } else if (b.op === "light_mode") {
      note(shots, b.shot, b.color || "#ffd000", b.pattern);
      insertNames(b).forEach((n) => note(lamps, n, b.color || "#ffd000", b.pattern));
      if (b.solid) note(lamps, b.solid, b.solid_color || "#ffffff", "solid");
    }
  }));
  return { shots, lamps };
}

// Does script `sc` name the shot (or, with lamp, the light) anywhere: its hat, a block, a value
export function names(sc, name, lamp = false) {
  let hit = false;
  eachPart(sc, (o) => {
    if (lamp) { if ((o.op && insertNames(o).includes(name)) || o.solid === name) hit = true; }
    else if (o.shot === name) hit = true;
  });
  return hit;
}

export function usedShots(prog) {
  const out = new Set();
  eachPart(prog.scripts || [], (o) => { if (typeof o.shot === "string" && o.shot && o.shot !== "*") out.add(o.shot); });
  return out;
}

export function hatWords(h = {}, ch = {}) {
  const when = WHILE[h.when] || "";
  switch (h.kind) {
    case "mode_start": return "When the mode starts";
    case "mode_end": return "When the mode ends";
    case "ball_end": return "When the ball drains";
    case "drain": return `When a ball goes into the trough${when}`;
    case "shot": return `When ${h.shot || "a shot"} is made${when}`;
    case "any_shot": return `When any shot is made${when}`;
    case "switch": return `When any playfield switch is hit${when}`;
    case "every": return `Every ${h.seconds} seconds while it runs`;
    case "seconds_left": return `When ${h.seconds} seconds are left`;
    case "event": return `When ${eventLabel(h.event, ch)}${when}`;
    case "timer_done": return `When timer ${h.timer} runs out`;
    case "battle": return h.more   // PAD-707: a new monster on the screen, in that battle's place
      ? `When the player picks it on the battle selection screen, a new monster in ${h.name || `battle ${h.slot}`}'s place`
      : `When the player picks ${h.name || (h.slot == null ? "a battle" : `battle ${h.slot}`)} on the battle selection screen`;   // PAD-706
    case "challenge": return `When the player picks the challenge ${h.challenge || "?"}${h.launch === "player" ? ", the player launching its ball" : /^\d+$/.test(h.launch || "") ? `, its ball launched ${h.launch} s after it starts` : ""}`;   // PAD-615, PAD-643
    default: return h.kind || "";
  }
}

const eventLabel = (name, ch = {}) => ((ch.events || []).find((x) => x.name === name) || {}).label || name;

export function countBlocks(sc) {
  let n = 0;
  eachStmt(sc.do, () => { n += 1; });
  return n;
}

// ------------------------------------------------------------------ a block in words (PAD-614)
// The block's family, as the Blocks tab colors it: modes_blocks.js STMT_CLASS (a test keeps the two the same)
export const FAMILY = { start_mode: "mode", light_mode: "mode", unlight_mode: "mode", set_hits: "var", end_mode: "mode",
  add_time: "mode", set_time: "mode", multiball: "mode", ball_save: "mode", game_wizard: "mode", score: "score", set: "var", change: "var",
  if: "flow", callout: "show", words: "show", light_shot: "show", lights_off: "show", show: "show", game_show: "show",
  log: "show", clip: "own", sound: "own", music: "own", timer_start: "timer", timer_stop: "timer", hud_text: "hud", hud_counter: "hud",
  hud_gauge: "hud", hud_award: "hud", hud_progress: "hud", hold: "mech", scoop_hold: "mech", let_go: "mech", shield: "mech", building: "mech",
  shake: "mech", shake_game: "mech" };
const COLOR_NAMES = { "#ffd000": "yellow", "#00a0ff": "blue", "#ff0000": "red", "#00c040": "green", "#ffffff": "white",
  "#ff7800": "orange", "#a040ff": "purple", "#00ff00": "green" };
const PATTERN_WORDS = { solid: "solid", blink: "blinking", pulse: "pulsing", chase: "chasing",
  hurry: "blinking faster as time runs out", off: "dark" };
const SYM = { "*": "×", "/": "÷", "-": "−", "+": "+", ">=": "≥", "<=": "≤", "!=": "≠", "=": "=", "<": "<", ">": ">" };
const big = (v) => (Number.isInteger(v) && Math.abs(v) >= 10000 ? v.toLocaleString("en-US") : String(v));
const colorWord = (c) => COLOR_NAMES[String(c || "").toLowerCase()] || String(c || "");
const msWords = (v) => (v && v.k === "num" && Number.isInteger(v.v) ? (v.v >= 1000 ? `${v.v / 1000} s` : `${v.v} ms`) : `${valWords(v)} ms`);
const quote = (t) => `“${t || ""}”`;

// A value in words
export function valWords(e) {
  if (e == null) return "?";
  if (typeof e !== "object") return String(e);
  switch (e.k) {
    case "num": return big(e.v);
    case "var": return String(e.name || "?");
    case "hits": return `hits of ${e.shot || "?"}`;
    case "scored": return "times it has scored";
    case "total": return "points so far";
    case "secs_left": return "seconds left";
    case "balls": return "balls in play";
    case "player": return "the player up";
    case "timer_left": return `ms left on ${e.timer || "?"}`;
    case "op": return `(${valWords(e.a)} ${SYM[e.op] || e.op} ${valWords(e.b)})`;
    default: return condWords(e);
  }
}

// A condition in words
export function condWords(e) {
  if (e == null) return "?";
  switch (e.k) {
    case "cmp": return `${valWords(e.a)} ${SYM[e.op] || e.op} ${valWords(e.b)}`;
    case "and": return `${condWords(e.a)} and ${condWords(e.b)}`;
    case "or": return `${condWords(e.a)} or ${condWords(e.b)}`;
    case "not": return `not (${condWords(e.a)})`;
    case "running": return "the mode is running";
    case "stock": return "a game mode of its own runs";
    case "can_start": return "the mode could start now";
    case "lit": return "the mode is lit";
    case "shields_away": return "the shield targets face away";
    default: return typeof e === "object" && e.k ? valWords(e) : "?";
  }
}

const lightName = (b) => b.insert || (b.shot === "*" ? "every shot" : b.shot) || "?";

// One block (not an If) in words, for the views that list blocks instead of drawing them
export function stmtWords(b, ch = {}) {
  if (!b || typeof b !== "object") return "?";
  const withValue = (t, v) => (v ? `${t} and ${valWords(v)}` : t);
  switch (b.op) {
    case "start_mode": return "Start the mode";
    case "end_mode": return b.won ? "End the mode, the battle won" : "End the mode";   // PAD-706
    case "light_mode": return `Light the mode at ${b.shot || "?"} (${colorWord(b.color)}, ${PATTERN_WORDS[b.pattern] || b.pattern || ""})`;
    case "unlight_mode": return `Put out the light of ${((ch.modes || []).find((m) => m.slug === b.mode) || {}).name || b.mode || "this mode"}`;
    case "add_time": return `Add ${valWords(b.seconds)} seconds`;
    case "set_time": return b.at_least ? `Keep at least ${valWords(b.seconds)} seconds on the clock`   // PAD-658
      : `Set the clock to ${valWords(b.seconds)} seconds`;
    case "multiball": return `Multiball of ${b.balls} balls, ball save ${b.save || 0} s`;
    case "ball_save": return `Ball save for ${b.seconds} s`;
    case "game_wizard": return `${b.how === "start" ? "Start" : "Light"} the game's ${b.name || "mini-wizard"}`;
    case "hold": return `Hold the ${b.what || "magnet"} for ${msWords(b.ms)}${b.clock === "wait" ? ", its clock waiting until it lets go" : ""}`;
    case "scoop_hold": return `Hold ${b.which === "every" ? "every ball" : "the next ball"} in the scoop for ${msWords(b.ms)}`;
    case "let_go": return `Let go of ${b.what === "*" ? "everything it holds" : b.what || "?"}`;
    case "shield": return `Turn the shield targets ${({ toward: "toward the player", away: "away", leave: "where they are" })[b.where] || b.where || "?"}`;
    case "building": return `Move the building to ${String(b.floor) === "0" ? "where the game keeps it" : "floor " + b.floor}`;
    case "shake": return `Shake the cabinet (${b.strength || "hard"}) for ${msWords(b.ms)}`;
    case "shake_game": return `Shake the cabinet with ${b.shake || "?"}`;
    case "score": return `Score ${valWords(b.points)} points`;
    case "set": return `Set ${b.var || "?"} to ${valWords(b.value)}`;
    case "change": return `Change ${b.var || "?"} by ${valWords(b.by)}`;
    case "set_hits": return `Set the hits of ${b.shot || "?"} to ${valWords(b.value)}`;
    case "timer_start": return `Start timer ${b.timer || "?"} at ${msWords(b.ms)}`;
    case "timer_stop": return `Stop timer ${b.timer || "?"}`;
    case "callout": {
      const c = (ch.callouts || []).find((x) => (x.role || String(x.id)) === (b.role || String(b.id)));
      return `Say ${quote(c ? c.label : b.role || b.id)}`;
    }
    case "words": return withValue(`Show ${quote(b.text)}`, b.value);
    case "light_shot": return b.pattern === "off" ? `Hold ${lightName(b)} dark`
      : `Light ${lightName(b)} ${colorWord(b.color)}, ${PATTERN_WORDS[b.pattern] || b.pattern || ""}`;
    case "lights_off": return `Hand back the lights of ${lightName(b)}`;
    case "show": {
      if (b.show === "own") return `Run its own light show (${(b.steps || []).length} steps)`;
      if (b.show === "mine") return `Run the mode's light show ${quote(b.name || "?")}`;     // PAD-646
      const s = ((ch.light || {}).shows || []).find((x) => x.key === b.show);
      return `Run the light show ${quote(s ? s.label : b.show)}`;
    }
    case "game_show": return `Play the game's light show ${b.name || "?"}`;
    case "log": return `Write ${quote(b.text)} in the log`;
    case "clip": return `Play the clip ${b.clip || "?"}`;
    case "sound": return `Play the sound ${b.sound || "?"}`;
    case "music": return b.bed ? `Play the music bed ${b.bed}` : "Play its own music";     // PAD-658
    case "hud_text": return withValue(`HUD ${b.which === "title" ? "title" : "line"}: ${quote(b.text)}`, b.value);
    case "hud_counter": return `HUD counter ${b.counter} to ${valWords(b.value)}`;
    case "hud_gauge": return `Fill the HUD's gauge to ${valWords(b.value)} pips`;
    case "hud_progress": return `Show ${valWords(b.value)} on the progress panel`;
    case "hud_award": return withValue(`Award ${quote(b.text)}`, b.value);
    case "if": return `If ${condWords(b.cond)}`;
    default: return `(${b.op})`;
  }
}

// A rule's blocks as lines in words: {depth, fam, words}, an If as its condition, "Otherwise", and its branches
export function ruleLines(stack, ch = {}, depth = 0) {
  const out = [];
  (stack || []).forEach((b) => {
    if (b && b.op === "if") {
      out.push({ depth, fam: "flow", words: stmtWords(b, ch) });
      out.push(...ruleLines(b.then, ch, depth + 1));
      if (Array.isArray(b.else)) {
        out.push({ depth, fam: "flow", words: "Otherwise" });
        out.push(...ruleLines(b.else, ch, depth + 1));
      }
    } else out.push({ depth, fam: FAMILY[(b || {}).op] || "show", words: stmtWords(b, ch) });
  });
  return out;
}

// ------------------------------------------------------------------ Story: the mode's life (PAD-614)
// A shot, any-shot or game-event rule has a "when" (not running / runs / any time): the Story moves it between boxes
export const MOVABLE = new Set(["shot", "any_shot", "switch", "event", "drain"]);

// Where each rule sits: waiting / running / any (a movable rule's when), start / end (on the arrows), drain (the
// ball drains), and the clock's rules inside running
export function storyOf(prog) {
  const out = { waiting: [], running: [], any: [], start: [], end: [], drain: [] };
  (prog.scripts || []).forEach((sc, si) => {
    const h = sc.hat || {};
    if (MOVABLE.has(h.kind)) out[h.when === "idle" ? "waiting" : h.when === "running" ? "running" : "any"].push(si);
    else if (h.kind === "mode_start") out.start.push(si);
    else if (h.kind === "mode_end") out.end.push(si);
    else if (h.kind === "ball_end") out.drain.push(si);
    else if (h.kind === "challenge" || h.kind === "battle") out.waiting.push(si);   // PAD-615, PAD-706: the pick comes before the mode starts
    else out.running.push(si);                       // every, seconds left, a timer: they work while it runs
  });
  return out;
}

// The "when" a movable rule takes in a box
export const BOX_WHEN = { waiting: "idle", running: "running", any: "any" };

// What starts the mode and what ends it, in words, each with the rule it comes from (si; -1: the mode's settings)
export function storyArrows(prog, ch = {}) {
  const ins = [], outs = [];
  const find = (list, op, path = []) => {
    const hits = [];
    (list || []).forEach((b) => {
      if (!b) return;
      if (b.op === op) hits.push(path);
      if (b.op === "if") {
        hits.push(...find(b.then, op, [...path, condWords(b.cond)]));
        hits.push(...find(b.else, op, [...path, `not (${condWords(b.cond)})`]));
      }
    });
    return hits;
  };
  (prog.scripts || []).forEach((sc, si) => {
    const h = hatWords(sc.hat, ch);
    find(sc.do, "start_mode").forEach((conds) => ins.push({ si, words: conds.length ? `${h}, if ${conds.join(" and ")}` : h }));
    find(sc.do, "end_mode").forEach((conds) => outs.push({ si, words: conds.length ? `${h}, if ${conds.join(" and ")}` : h }));
  });
  if (prog.seconds) outs.unshift({ si: -1, words: `The clock runs out (${prog.seconds} seconds)` });
  if (prog.ends_on_drain !== false) outs.push({ si: -1, words: "The ball drains" });
  return { ins, outs };
}

// ------------------------------------------------------------------ Shot table (PAD-614)
// One row per shot (and "any shot", and each game event the mode uses): which rules fire there, by when
export const ANY_SHOT = "*any";
export function shotGrid(prog, shots = [], ch = {}) {
  const rows = [...shots.map((n) => ({ key: n, kind: "shot", label: n })), { key: ANY_SHOT, kind: "any_shot", label: "Any shot" }];
  const events = [];
  (prog.scripts || []).forEach((sc) => {
    const h = sc.hat || {};
    if (h.kind === "event" && !events.includes(h.event)) events.push(h.event);
    if (h.kind === "shot" && !shots.includes(h.shot)) rows.push({ key: h.shot, kind: "shot", label: h.shot, missing: true });
  });
  events.forEach((e) => rows.push({ key: "event:" + e, kind: "event", event: e, label: eventLabel(e, ch) }));
  rows.forEach((r) => { r.cells = { idle: [], running: [], any: [] }; });
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));
  const others = [];
  (prog.scripts || []).forEach((sc, si) => {
    const h = sc.hat || {};
    const key = h.kind === "shot" ? h.shot : h.kind === "any_shot" ? ANY_SHOT : h.kind === "event" ? "event:" + h.event : null;
    if (key == null || !by[key]) { others.push(si); return; }
    by[key].cells[h.when === "idle" || h.when === "running" ? h.when : "any"].push(si);
  });
  rows.forEach((r) => { r.used = Object.values(r.cells).some((l) => l.length); });
  return { rows, others };
}

// The hat a new rule in a cell starts with
export function cellHat(row, when) {
  if (row.kind === "any_shot") return { kind: "any_shot", when };
  if (row.kind === "event") return { kind: "event", event: row.event, when };
  return { kind: "shot", shot: row.key, when };
}

// ------------------------------------------------------------------ Timeline (PAD-614)
export const LANES = [["clock", "Mode and clock"], ["lights", "Lights"], ["shows", "Light shows"], ["sound", "Sound"],
  ["screen", "Screen and HUD"], ["score", "Score and variables"], ["other", "Mechanisms and the rest"]];
const LANE_OF = { start_mode: "clock", end_mode: "clock", add_time: "clock", set_time: "clock", timer_start: "clock",
  timer_stop: "clock", multiball: "clock", ball_save: "clock", game_wizard: "clock", light_mode: "lights", unlight_mode: "lights",
  light_shot: "lights", lights_off: "lights", show: "shows", game_show: "shows", callout: "sound", sound: "sound",
  words: "screen", clip: "screen", hud_text: "screen", hud_counter: "screen", hud_gauge: "screen", hud_award: "screen", hud_progress: "screen",
  score: "score", set: "score", change: "score", set_hits: "score" };
export const laneOf = (op) => LANE_OF[op] || "other";
const TRACK_PX = 640;           // about how wide the Timeline's track is drawn, to keep its clips apart

// The mode's moments on its clock: {seconds, moments: [{t, si, label, repeat}], clips: [{lane, t, si, words, cond,
// row}], whenever: [si]} - a rule with no fixed time (a shot, a timer, the drain) is listed under it
export function timelineOf(prog, ch = {}) {
  const S = Number(prog.seconds) || 0;
  const moments = [], whenever = [];
  (prog.scripts || []).forEach((sc, si) => {
    const h = sc.hat || {};
    if (h.kind === "mode_start") moments.push({ t: 0, si, label: "It starts" });
    else if (h.kind === "mode_end") moments.push({ t: S, si, label: "It ends", end: true });
    else if (h.kind === "seconds_left" && S && h.seconds > 0 && h.seconds < S) moments.push({ t: S - h.seconds, si, label: `${h.seconds} s left` });
    else if (h.kind === "every" && S && h.seconds > 0) moments.push({ t: Math.min(h.seconds, S), si, label: `Every ${h.seconds} s`, repeat: h.seconds });
    else whenever.push(si);
  });
  const clips = [];
  moments.forEach((m) => {
    const add = (list, cond) => (list || []).forEach((b) => {
      if (!b) return;
      if (b.op === "if") { add(b.then, true); add(b.else, true); return; }
      clips.push({ lane: laneOf(b.op), fam: FAMILY[b.op] || "show", t: m.t, si: m.si, words: stmtWords(b, ch), cond, row: 0, end: !!m.end });
    });
    add((prog.scripts[m.si] || {}).do, false);
  });
  // each lane's clips in rows, none over another: a clip is about as wide as its words (a share of TRACK_PX), and an
  // end's runs back from the end
  const span = (x) => {
    const w = S ? (Math.min(220, x.words.length * 6.4 + 18) / TRACK_PX) * S : 0;
    return x.end ? [x.t - w, x.t] : [x.t, x.t + w];
  };
  const taken = {};
  clips.forEach((x) => {
    const [a, b] = span(x);
    const rows = taken[x.lane] || (taken[x.lane] = []);
    let r = 0;
    while ((rows[r] || []).some(([c, d]) => a < d && c < b)) r += 1;
    (rows[r] || (rows[r] = [])).push([a, b]);
    x.row = r;
  });
  return { seconds: S, moments, clips, whenever };
}

// ------------------------------------------------------------------ Node graph: who uses what (PAD-614)
// Every variable, timer and shot count the rules share: [{key, kind, name, uses: [{si, how}]}], how = sets (writes
// it), reads, or starts (a timer's run-out sets the rule off)
export function sharedUses(prog) {
  const things = new Map();
  const thing = (kind, name) => {
    const key = kind + ":" + name;
    if (!things.has(key)) things.set(key, { key, kind, name, uses: [] });
    return things.get(key);
  };
  (prog.vars || []).forEach((v) => thing("var", v.name));
  (prog.timers || []).forEach((t) => thing("timer", t.name));
  const use = (t, si, how) => { if (!t.uses.some((u) => u.si === si && u.how === how)) t.uses.push({ si, how }); };
  (prog.scripts || []).forEach((sc, si) => {
    const h = sc.hat || {};
    if (h.kind === "timer_done" && h.timer) use(thing("timer", h.timer), si, "starts");
    eachPart(sc.do, (o) => {
      if ((o.op === "set" || o.op === "change") && o.var) use(thing("var", o.var), si, "sets");
      else if ((o.op === "timer_start" || o.op === "timer_stop") && o.timer) use(thing("timer", o.timer), si, "sets");
      else if (o.op === "set_hits" && o.shot) use(thing("hits", o.shot), si, "sets");
      if (o.k === "var" && o.name) use(thing("var", o.name), si, "reads");
      else if (o.k === "timer_left" && o.timer) use(thing("timer", o.timer), si, "reads");
      else if (o.k === "hits" && o.shot) use(thing("hits", o.shot), si, "reads");
    });
  });
  return [...things.values()];
}
