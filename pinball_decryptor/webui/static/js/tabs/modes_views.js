// Modes: what every view of a blocks mode reads off its program (PAD-612): which shots and lights it lights and in
// what color, which rules name a shot, and a rule's When in words. No imports, so a test loads it alone.

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
    case "shot": return `When ${h.shot || "a shot"} is made${when}`;
    case "any_shot": return `When any shot is made${when}`;
    case "every": return `Every ${h.seconds} seconds while it runs`;
    case "seconds_left": return `When ${h.seconds} seconds are left`;
    case "event": return `When ${((ch.events || []).find((x) => x.name === h.event) || {}).label || h.event}${when}`;
    case "timer_done": return `When timer ${h.timer} runs out`;
    default: return h.kind || "";
  }
}

export function countBlocks(sc) {
  let n = 0;
  eachStmt(sc.do, () => { n += 1; });
  return n;
}
