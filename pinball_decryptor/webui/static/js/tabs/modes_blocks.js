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
// PAD-374: a mode's OWN clips and sounds sit above its scripts (picked from files, copied into its
// folder by modes.blocks_pick), each with the name its Play a clip / Play a sound blocks call it by.

import { html, useEffect, useRef, useState, Button, Field, Select, Check, Note, tip, cx, call,
         openMenu } from "../core/ui.js";
import { PlayButton } from "./modes_dialogs.js";

const WHEN = [["any", "any time"], ["idle", "while it is not running"], ["running", "while it runs"]];
const RESETS = [["ball", "each ball"], ["mode", "each time it starts"], ["game", "each game"]];
const PATTERNS = [["solid", "solid"], ["blink", "blinking"], ["pulse", "pulsing"], ["chase", "chasing"]];
const OPS = [["+", "+"], ["-", "−"], ["*", "×"], ["/", "÷"]];
const CMPS = [["<", "<"], ["<=", "≤"], ["=", "="], ["!=", "≠"], [">=", "≥"], [">", ">"]];
const CLIP_WHERE = [["full", "full screen"], ["behind", "behind the HUD, once"], ["loop", "behind the HUD, over and over"]];
const PRIORITIES = [3, 4, 5, 6, 7].map((p) => [String(p), "priority " + p]);
const SAVE_MS = 450;

const TIP = {
  palette: "Drag a block into a script, or press it to add it to the script you picked last (the one with the lit edge).",
  hat: "A script: what sets it off, and the blocks it runs, top to bottom.",
  vars: "A variable holds a number for each player. Reset says when it goes back to 0.",
  screen: "The build makes the mode a screen of its own: a panel with its name, and a line the Show words block writes. It costs a little build time.",
  seconds: "How long the mode runs once it starts. 0 = no clock: it runs until a block ends it (or the ball drains, if ticked).",
  drain: "The ball draining ends the mode.",
  asC: "Carry on in C: the mode keeps the C its blocks made, and the blocks are put away.",
  hits: "How many times the player up has made this shot in this ball (while the mode runs or not).",
  scored: "How many times a Score block has paid since the mode started.",
  total: "The points the mode's Score blocks have paid since it started.",
  stock: "One of the game's own modes, battles or multiballs is running.",
  addTime: "Adds this many seconds to the mode's clock (less than 0 takes some off). Any value: a number, a variable, a sum.",
  setTime: "Puts the mode's clock at this many seconds, up or down (0 = time is up). Put up, a When that many seconds are left does not run again.",
  gameModes: "May start: the game's modes start as usual while this one runs. End this one: it starts only while none of the game's modes runs (a Start the mode then waits, and the next one starts it), and one of them starting ends it. Cannot start: as End this one, and while it runs the modes ticked below cannot start at all. A multiball of the game's is never held off: it starts, and this mode ends. Its own Multiball block does not end it.",
  blockPick: "While this mode runs, the game does not start this one of its modes. A shot that would have started it does what it does when the mode is not lit.",
  blockLast: "One at least: to let them all start, choose \"may start\" above.",
  own: "Clips and sounds of the mode's own, picked from your files and copied into its folder. Write and Try it carry them onto the card; a Play a clip or Play a sound block plays one by its name.",
  where: "Full screen plays over everything, the HUD too, half a second after it is asked for (so the game's own clip for the same shot does not take its place). Behind the HUD, over and over, plays in the city's place under the score while the mode runs. Behind the HUD, once, plays in that loop's place and then the loop again.",
  fallback: "What to say instead when the card could not carry this sound (a card with no spare sound for it): one of the game's own callouts, or nothing.",
  priority: "Its priority on the voice bus: it fades the game's lower speech and waits for higher. 4 is a call's usual; 3 for one that repeats (a play while the last still sounds is skipped).",
  music: "Its own music: it plays instead of the game's while the mode runs, and the game's comes back at the end.",
  name: "The name its blocks call it by: lower-case letters, digits and _.",
};

// ------------------------------------------------------------------ the blocks there are
const num = (v) => ({ k: "num", v });

function hatTemplates(ch) {
  const shot = (ch.shots || [])[0] || "";
  const ev = ((ch.events || [])[0] || {}).name || "";
  return [
    { kind: "mode_start" }, { kind: "mode_end" },
    { kind: "shot", shot, when: "running" }, { kind: "any_shot", when: "running" },
    { kind: "every", seconds: 5 }, { kind: "seconds_left", seconds: 10 },
    { kind: "ball_end" }, { kind: "event", event: ev, when: "any" },
  ];
}

function stmtTemplates(ch, vars, prog = {}) {
  const shot = (ch.shots || [])[0] || "";
  const v = (vars[0] || {}).name || "";
  const clip = ((prog.clips || [])[0] || {}).name || "";
  const sound = ((prog.sounds || [])[0] || {}).name || "";
  return [
    ["Mode", [{ op: "start_mode" }, { op: "end_mode" }, { op: "add_time", seconds: num(5) },
      { op: "set_time", seconds: num(10) },
      { op: "multiball", balls: 2, save: 10 }]],
    ["Score and variables", [{ op: "score", points: num(1000000) }, { op: "set", var: v, value: num(0) },
      { op: "change", var: v, by: num(1) }]],
    ["Control", [{ op: "if", cond: null, then: [], else: null }, { op: "if", cond: null, then: [], else: [] }]],
    ["Show and sound", [{ op: "callout", role: "ten_seconds" }, { op: "words", text: "JACKPOT", value: null },
      { op: "light_shot", shot, color: "#ffd000", pattern: "blink" }, { op: "lights_off", shot: "*" },
      { op: "log", text: "" }]],
    ["Its own clips and sounds", [{ op: "clip", clip, where: "full" }, { op: "sound", sound, fallback: null }]],
  ];
}

function valueTemplates(ch, vars) {
  return [num(1000), { k: "var", name: (vars[0] || {}).name || "" }, { k: "hits", shot: (ch.shots || [])[0] || "" },
    { k: "scored" }, { k: "total" }, { k: "secs_left" }, { k: "balls" }, { k: "player" },
    { k: "op", op: "+", a: null, b: null }];
}

const condTemplates = () => [{ k: "cmp", op: ">=", a: null, b: null }, { k: "and", a: null, b: null },
  { k: "or", a: null, b: null }, { k: "not", a: null }, { k: "running" }, { k: "stock" }];

const VALUE_WORDS = { num: "a number", var: "a variable", hits: "hits of a shot this ball", scored: "times it has scored",
  total: "points so far", secs_left: "seconds left", balls: "balls in play", player: "the player up", op: "a sum" };
const COND_WORDS = { cmp: "compare two values", and: "both", or: "either", not: "not", running: "the mode is running",
  stock: "a game mode of its own runs" };
const STMT_CLASS = { start_mode: "mode", end_mode: "mode", add_time: "mode", set_time: "mode", multiball: "mode", score: "score",
  set: "var", change: "var", if: "flow", callout: "show", words: "show", light_shot: "show", lights_off: "show", log: "show",
  clip: "own", sound: "own" };

// ------------------------------------------------------------------ the program, by path
const clone = (x) => JSON.parse(JSON.stringify(x));
function at(obj, path) { return path.reduce((o, k) => (o == null ? o : o[k]), obj); }
function put(obj, path, value) { at(obj, path.slice(0, -1))[path[path.length - 1]] = value; }
const samePath = (a, b) => a && b && a.length === b.length && a.every((x, i) => x === b[i]);
const within = (inner, outer) => inner.length >= outer.length && outer.every((x, i) => inner[i] === x);

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

function Text({ value, onChange, width = 150, placeholder }) {
  return html`<${Field} sm width=${width} value=${value || ""} maxLength=${60} placeholder=${placeholder} onChange=${onChange} />`;
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
    : valueTemplates(ed.ch, ed.vars).map((t) => ({ label: VALUE_WORDS[t.k], onClick: () => ed.set(path, t) }));
  openMenu(e.currentTarget, items);
}

function Slot({ kind, value, path, ed, optional }) {
  const [over, setOver] = useState(false);
  const fits = () => dragging && dragging.tpl && (kind === "bool" ? dragging.tpl.k && condTemplates().some((t) => t.k === dragging.tpl.k)
    : dragging.tpl.k && valueTemplates(ed.ch, ed.vars).some((t) => t.k === dragging.tpl.k));
  const drop = {
    onDragOver: (e) => { if (fits()) { e.preventDefault(); e.stopPropagation(); setOver(true); } },
    onDragLeave: () => setOver(false),
    onDrop: (e) => { if (!fits()) return; e.preventDefault(); e.stopPropagation(); setOver(false); ed.set(path, clone(dragging.tpl)); dragging = null; },
  };
  if (!value) {
    return html`<button type="button" class=${cx("bk-slot", kind, over && "over")} ...${drop}
      onClick=${(e) => slotMenu(e, kind, ed, path)} ...${tip(kind === "bool" ? "A condition: drop one here, or press to pick" : "A value: drop one here, or press to pick")}>
      ${kind === "bool" ? "condition" : optional ? "(no number)" : "value"}</button>`;
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
      <${Pick} value=${b.pattern} options=${PATTERNS} onChange=${(v) => set("pattern", v)} />`;
    case "lights_off": return html`<span class="bk-w">Hand back the lights of</span><${Pick} value=${b.shot} options=${[["*", "every shot"], ...shots.map((n) => [n, n])]} onChange=${(v) => set("shot", v)} />`;
    case "add_time": return html`<span class="bk-w" ...${tip(TIP.addTime)}>Add</span><${Slot} kind="num" value=${b.seconds} path=${[...path, "seconds"]} ed=${ed} /><span class="bk-w">seconds</span>`;
    case "set_time": return html`<span class="bk-w" ...${tip(TIP.setTime)}>Set the clock to</span><${Slot} kind="num" value=${b.seconds} path=${[...path, "seconds"]} ed=${ed} /><span class="bk-w">seconds</span>`;
    case "multiball": return html`<span class="bk-w">Multiball of</span><${Num} value=${b.balls} width=${44} onChange=${(v) => set("balls", v)} />
      <span class="bk-w">balls, ball save</span><${Num} value=${b.save} width=${44} onChange=${(v) => set("save", v)} /><span class="bk-w">s</span>`;
    case "log": return html`<span class="bk-w">Write</span><${Text} value=${b.text} onChange=${(v) => set("text", v)} placeholder="a line" /><span class="bk-w">in the log</span>`;
    case "clip": return html`<span class="bk-w">Play the clip</span><${Pick} value=${b.clip} options=${(ed.prog.clips || []).map((x) => x.name)} missing="(not one of its own)" onChange=${(v) => set("clip", v)} />
      <${Pick} value=${b.where} options=${CLIP_WHERE} title=${TIP.where} onChange=${(v) => set("where", v)} />`;
    case "sound": {
      const opts = [["-", "nothing"], ...(ed.ch.callouts || []).map((c) => [c.role || String(c.id), c.label])];
      const cur = b.fallback == null || b.fallback === "" ? "-" : String(b.fallback);
      return html`<span class="bk-w">Play the sound</span><${Pick} value=${b.sound} options=${(ed.prog.sounds || []).map((x) => x.name)} missing="(not one of its own)" onChange=${(v) => set("sound", v)} />
        <span class="bk-w" ...${tip(TIP.fallback)}>else say</span><${Pick} value=${cur} options=${opts} title=${TIP.fallback}
          onChange=${(v) => set("fallback", v === "-" ? null : (/^[0-9]+$/.test(v) ? Number(v) : v))} />`;
    }
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
  stmtTemplates(ed.ch, ed.vars, ed.prog).forEach(([group, items], gi) => {
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
    ball_end: "When the ball drains", event: "When the game does…" }[h.kind] || h.kind;
}

function stmtLabel(b) {
  return { start_mode: "Start the mode", end_mode: "End the mode", add_time: "Add seconds", set_time: "Set the clock", multiball: "Multiball",
    score: "Score points", set: "Set a variable", change: "Change a variable", callout: "Say a callout",
    words: "Show words", light_shot: "Light a shot", lights_off: "Hand back lights", log: "Write in the log",
    clip: "Play a clip", sound: "Play a sound",
    if: b.else ? "If … else" : "If" }[b.op] || b.op;
}

function Palette({ ed }) {
  const piece = (cls, label, tpl, onPress, title) => html`<button type="button" class=${cx("bk-pal", cls)} draggable="true"
    onDragStart=${(e) => { dragging = { tpl: clone(tpl) }; e.dataTransfer.effectAllowed = "copy"; e.dataTransfer.setData("text/plain", "block"); }}
    onDragEnd=${() => { dragging = null; ed.setOver(null); }}
    onClick=${onPress} ...${tip(title || TIP.palette)}>${label}</button>`;
  const vals = valueTemplates(ed.ch, ed.vars);
  return html`<div class="bk-palette" aria-label="Blocks">
    <div class="bk-pal-h">When</div>
    ${hatTemplates(ed.ch).map((h) => piece("bk-hat", hatLabel(h), { hat: h }, () => ed.addScript(clone(h)), "Press to start a new script with this"))}
    ${stmtTemplates(ed.ch, ed.vars, ed.prog).map(([group, items]) => html`<div class="bk-pal-h">${group}</div>
      ${items.map((t) => piece("bk-" + (STMT_CLASS[t.op] || "show"), stmtLabel(t), t, () => ed.addToTarget(clone(t))))}`)}
    <div class="bk-pal-h">Values</div>
    ${vals.map((t) => piece("bk-num", VALUE_WORDS[t.k], t, null, "Drag into a value slot (the round holes)"))}
    <div class="bk-pal-h">Conditions</div>
    ${condTemplates().map((t) => piece("bk-bool", COND_WORDS[t.k], t, null, "Drag into an If's condition slot"))}
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
      <${Select} sm value=${v.reset || "ball"} options=${RESETS.map(([value, label]) => ({ value, label }))}
        onChange=${(r) => ed.set(["vars", i, "reset"], r)} />
      <${X} title="Take this variable out" onClick=${() => ed.edit((d) => { d.vars.splice(i, 1); })} />
    </span>`)}
    <${Button} size="sm" kind="ghost" icon="plus" onClick=${add}>Variable<//>
  </div>`;
}

// PAD-373: what the mode does about the game's own modes, as the form asks it (PAD-363). No ticks
// saved = the title's usual ones, shown ticked; the last tick stays, so the list never goes back to
// those by itself.
function GameModes({ prog, ed }) {
  const ch = ed.ch;
  const gm = prog.game_modes || "stack";
  const rows = ch.game_modes || [];
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
  // another mode opened (or this one duplicated, or put back by Python): take its program
  useEffect(() => { slugRef.current = c.slug; setProg(clone(b.program || {})); setTarget(null); }, [c.slug]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const save = (next) => {
    clearTimeout(timer.current);
    setSaving(true);
    const slug = slugRef.current;
    timer.current = setTimeout(() => {
      Promise.resolve(call("modes.blocks_save", slug, next)).finally(() => setSaving(false));
    }, SAVE_MS);
  };
  const edit = (fn) => setProg((p) => { const d = clone(p); fn(d); save(d); return d; });
  const ed = {
    prog, ch: b.choices || {}, vars: prog.vars || [], target, over, setOver,
    setTarget, edit,
    set: (path, v) => edit((d) => put(d, path, v)),
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
    }),
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
    }),
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
      <div class="bk-settings row wrap">
        <label class="lbl" for="bk-name">Name</label>
        <${Field} id="bk-name" sm width=${180} value=${prog.name || ""} maxLength=${40} onChange=${(t) => ed.set(["name"], t)} />
        <span class="lbl" ...${tip(TIP.seconds)}>Runs for</span>
        <${Num} value=${prog.seconds} width=${56} title=${TIP.seconds} onChange=${(v) => ed.set(["seconds"], v)} /><span class="small muted">seconds</span>
        <${Check} checked=${prog.ends_on_drain !== false} label="ends when the ball drains" title=${TIP.drain} onChange=${(v) => ed.set(["ends_on_drain"], v)} />
        <${Check} checked=${!!prog.screen} label="its own screen" title=${TIP.screen} onChange=${(v) => ed.set(["screen"], v)} />
        <span class="sp"></span>
        <span class="small muted">${saving ? "Saving…" : "Saved · Try it builds it in"}</span>
      </div>
      <${GameModes} prog=${prog} ed=${ed} />
      <${Variables} prog=${prog} ed=${ed} />
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
