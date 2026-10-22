// Modes: the Rule cards, Story, Shot table, Timeline and Node graph views of a blocks mode (PAD-614, steps 3-6 of
// PAD-611's plan). Each is a tab over the one program (modes_blocks.js useModeProgram), as the Blocks and Playfield
// tabs are: an edit here is a step of the mode's one history, saved to the same blocks.json, and every other tab draws
// it when opened. A rule a view cannot place in its own way is still listed, so nothing of the mode is hidden.
//
// A rule is edited as the same blocks everywhere (modes_blocks.js Script, Stack, HatBody): the Rule cards draw them
// as sentences, the other views open the rule they point at beside or under themselves.

import { html, useEffect, useRef, useState, Button, tip, cx, openMenu } from "../core/ui.js";
import { Script, Stack, HatBody, useEd, hatTemplates, hatLabel } from "./modes_blocks.js";
import { lights, hatWords, countBlocks, ruleLines, storyOf, storyArrows, MOVABLE, BOX_WHEN, shotGrid, cellHat,
  timelineOf, LANES, sharedUses } from "./modes_views.js";

const TIP = {
  addRule: "A new rule at the end of the mode's rules: pick what sets it off.",
  earlier: "Move this rule earlier: rules set off by the same thing run in this order",
  later: "Move this rule later",
  drop: "Take this rule out, with its blocks",
  open: "Press to see and change this rule's blocks.",
  move: "Drag it to another box to change when it works: while the mode is not running, while it runs, or any time.",
  fixed: "What sets this rule off decides where it sits; change that in its blocks.",
  startArrow: "What starts the mode: a Start the mode block, and what sets it off.",
  endArrow: "What ends the mode: its clock, the drain, or an End the mode block.",
  cell: "Press to open this rule.",
  addCell: "A new rule for this shot, in this column.",
  whenever: "These rules have no fixed time: a shot, a timer or the drain sets them off.",
  thing: "Press to light up the rules that use it.",
  sets: "Sets it",
  reads: "Reads it",
  starts: "Set off when it runs out",
};
const WHENS = [["idle", "While it is not running"], ["running", "While it runs"], ["any", "Any time"]];

// ------------------------------------------------------------------ shared pieces
// The rule a view has open: its index follows the rule when it moves, and it shuts when the rule goes
function useOpenRule(base) {
  const [open, setOpen] = useState(null);
  const n = (base.prog.scripts || []).length;
  const ed = {
    ...base,
    addScript: (hat) => { base.addScript(hat); setOpen(n); },
    removeScript: (si) => { base.removeScript(si); setOpen(null); },
    moveScript: (si, dir) => { base.moveScript(si, dir); if (open === si) setOpen(si + dir); },
  };
  return [open != null && open < n ? open : null, setOpen, ed];
}

// What a rule does, in one short line: its first block, and how many more
function gist(sc, ch) {
  const lines = ruleLines(sc.do, ch);
  if (!lines.length) return "Does nothing yet";
  return lines.length > 1 ? `${lines[0].words} … (+${lines.length - 1})` : lines[0].words;
}

// The open rule's blocks, beside or under the view
function OpenRule({ si, ed, onClose, hint }) {
  const scripts = ed.prog.scripts || [];
  const box = useRef(null);
  // a rule pressed in the view comes into sight (under the Story or the Timeline it is below the fold)
  useEffect(() => { if (si != null && box.current && box.current.scrollIntoView) box.current.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [si]);
  if (si == null) return html`<div class="rv-open rv-hint small muted">${hint || "Press a rule to see and change its blocks."}</div>`;
  return html`<div class="rv-open" ref=${box}>
    <div class="rv-open-hd row"><span class="pf-group-h grow">Rule ${si + 1} of ${scripts.length}</span>
      <button type="button" class="bk-x rv-x" aria-label="Close" ...${tip("Close this rule")} onClick=${onClose}>×</button></div>
    <${Script} s=${scripts[si]} si=${si} n=${scripts.length} ed=${ed} />
  </div>`;
}

// A rule, as one line: what sets it off and what it does
function RuleLine({ sc, si, ed, open, onOpen, drag, hat = true }) {
  const k = countBlocks(sc);
  const movable = drag && MOVABLE.has((sc.hat || {}).kind);
  return html`<button type="button" class=${cx("rv-rule", open && "on", movable && "drag")} draggable=${movable ? "true" : undefined}
      onDragStart=${movable ? (e) => { e.dataTransfer.setData("text/x-pad-rule", String(si)); e.dataTransfer.setData("text/plain", "rule"); e.dataTransfer.effectAllowed = "move"; } : undefined}
      onClick=${() => onOpen(si)} ...${tip(drag ? (movable ? TIP.move : TIP.fixed) : TIP.open)}>
    ${hat ? html`<span class="rv-rule-hat">${hatWords(sc.hat, ed.ch)}</span>` : null}
    <span class="rv-rule-do small muted">${k ? gist(sc, ed.ch) : "Does nothing yet"}</span>
  </button>`;
}

// "+ Add a rule": a menu of what can set a rule off (only `kinds`, each with `extra` fields, when given)
function addRuleMenu(e, ed, kinds, extra = {}) {
  const items = hatTemplates(ed.ch, ed.timers).filter((h) => !kinds || kinds.includes(h.kind))
    .map((h) => ({ label: hatLabel(h), onClick: () => ed.addScript({ ...h, ...(h.when !== undefined || MOVABLE.has(h.kind) ? extra : {}) }) }));
  openMenu(e.currentTarget, items);
}

// ------------------------------------------------------------------ Rule cards
// Each rule a card: WHEN what sets it off, THEN its blocks, written as sentences with a picker in each blank
function RuleCard({ sc, si, n, ed }) {
  return html`<div class="rc-card">
    <div class="rc-when">
      <div class="rc-hat bk-line"><${HatBody} h=${sc.hat || {}} path=${["scripts", si, "hat"]} ed=${ed} /></div>
      <span class="rc-tools">
        <button type="button" class="bk-x" disabled=${si === 0} aria-label="Move this rule earlier" ...${tip(TIP.earlier)} onClick=${() => ed.moveScript(si, -1)}>↑</button>
        <button type="button" class="bk-x" disabled=${si === n - 1} aria-label="Move this rule later" ...${tip(TIP.later)} onClick=${() => ed.moveScript(si, 1)}>↓</button>
        <button type="button" class="bk-x" aria-label="Take this rule out" ...${tip(TIP.drop)} onClick=${() => ed.removeScript(si)}>×</button>
      </span></div>
    <div class="rc-then"><span class="rc-k">Then</span>
      <${Stack} list=${sc.do || []} path=${["scripts", si, "do"]} ed=${ed} /></div>
  </div>`;
}

export function RuleCardsView({ c, pg }) {
  const ed = useEd(pg, (c.blocks || {}).choices || {});
  const scripts = pg.prog.scripts || [];
  return html`<div class="rv-scroll rc-view">
    <div class="rv-bar row"><span class="small muted grow">Each rule reads When … Then: what sets it off, and what it does. Every underlined word is a choice; ◎ picks a shot on the playfield.</span>
      <${Button} size="sm" icon="plus" title=${TIP.addRule} onClick=${(e) => addRuleMenu(e, ed)}>Add a rule<//></div>
    <div class="rc-grid">
      ${scripts.map((sc, si) => html`<${RuleCard} key=${si} sc=${sc} si=${si} n=${scripts.length} ed=${ed} />`)}
    </div>
    ${scripts.length ? null : html`<div class="bk-newscript small muted">No rules yet: press Add a rule.</div>`}
  </div>`;
}

// ------------------------------------------------------------------ Story
// The mode's life: WAITING → RUNNING → OVER, each rule in the box where it works; a shot's or an event's rule is
// dragged between the boxes to change when it works
function StoryBox({ name, title, sub, list, ed, open, onOpen, kinds, extra }) {
  const [over, setOver] = useState(false);
  const accepts = name in BOX_WHEN;
  const scripts = ed.prog.scripts || [];
  const drop = accepts ? {
    onDragOver: (e) => { if ([...e.dataTransfer.types].includes("text/x-pad-rule")) { e.preventDefault(); setOver(true); } },
    onDragLeave: () => setOver(false),
    onDrop: (e) => {
      setOver(false);
      const si = Number(e.dataTransfer.getData("text/x-pad-rule"));
      const h = (scripts[si] || {}).hat;
      if (!h || !MOVABLE.has(h.kind)) return;
      e.preventDefault();
      ed.set(["scripts", si, "hat", "when"], BOX_WHEN[name]);
    },
  } : {};
  return html`<div class=${cx("st-box", "st-" + name, over && "over")} ...${drop}>
    <div class="st-box-hd row"><span class="st-title">${title}</span><span class="sp"></span>
      ${kinds ? html`<button type="button" class="bk-add" ...${tip(TIP.addRule)} onClick=${(e) => addRuleMenu(e, ed, kinds, extra)}>+ rule</button>` : null}</div>
    ${sub ? html`<div class="small muted st-sub">${sub}</div>` : null}
    <div class="st-rules">
      ${list.length ? list.map((si) => html`<${RuleLine} key=${si} sc=${scripts[si]} si=${si} ed=${ed} open=${open === si} onOpen=${onOpen} drag />`)
        : html`<div class="small muted pf-empty">Nothing yet.</div>`}
    </div>
  </div>`;
}

function StoryArrow({ title, items, list, ed, open, onOpen, kind, why }) {
  const scripts = ed.prog.scripts || [];
  return html`<div class="st-arrow" ...${tip(why)}>
    <div class="st-arrow-line"><span>${title}</span></div>
    <div class="st-arrow-why">
      ${items.length ? items.map((x, i) => html`<div key=${i} class=${cx("small", x.si >= 0 && "st-link")}
        onClick=${x.si >= 0 ? () => onOpen(x.si) : undefined}>${x.words}</div>`) : html`<div class="small muted">Nothing starts it yet: put a Start the mode block in a rule.</div>`}
    </div>
    <div class="st-arrow-do">
      <span class="small muted">${kind === "mode_start" ? "On the way in" : "On the way out"}</span>
      ${list.map((si) => html`<${RuleLine} key=${si} sc=${scripts[si]} si=${si} ed=${ed} open=${open === si} onOpen=${onOpen} hat=${false} />`)}
      <button type="button" class="bk-add" ...${tip(TIP.addRule)} onClick=${() => ed.addScript({ kind })}>+ ${kind === "mode_start" ? "When the mode starts" : "When the mode ends"}</button>
    </div>
  </div>`;
}

export function StoryView({ c, pg }) {
  const [open, setOpen, ed] = useOpenRule(useEd(pg, (c.blocks || {}).choices || {}));
  const prog = pg.prog;
  const st = storyOf(prog);
  const arrows = storyArrows(prog, ed.ch);
  const shotKinds = ["shot", "any_shot", "switch", "event"];
  const things = [...(prog.vars || []).map((v) => `${v.name} (a variable)`), ...(prog.timers || []).map((t) => `${t.name} (a timer)`)];
  return html`<div class="rv-scroll st-view">
    <div class="st-flow">
      <${StoryBox} name="waiting" title="Waiting" sub="Before it starts: what counts toward starting it." list=${st.waiting} ed=${ed}
        open=${open} onOpen=${setOpen} kinds=${shotKinds} extra=${{ when: "idle" }} />
      <${StoryArrow} title="It starts" items=${arrows.ins} list=${st.start} ed=${ed} open=${open} onOpen=${setOpen} kind="mode_start" why=${TIP.startArrow} />
      <${StoryBox} name="running" title="Running" sub=${prog.seconds ? `For ${prog.seconds} seconds, and any time added.` : "Until something ends it."}
        list=${st.running} ed=${ed} open=${open} onOpen=${setOpen} kinds=${[...shotKinds, "every", "seconds_left", "timer_done"]} extra=${{ when: "running" }} />
      <${StoryArrow} title="It ends" items=${arrows.outs} list=${st.end} ed=${ed} open=${open} onOpen=${setOpen} kind="mode_end" why=${TIP.endArrow} />
      <div class="st-box st-over"><div class="st-box-hd row"><span class="st-title">Over</span></div>
        <div class="small muted st-sub">${prog.seconds || prog.ends_on_drain !== false ? "It can start again when its start comes round." : ""}</div></div>
    </div>
    <div class="st-under">
      <${StoryBox} name="any" title="Any time" sub="Whether it runs or not." list=${st.any} ed=${ed} open=${open} onOpen=${setOpen}
        kinds=${shotKinds} extra=${{ when: "any" }} />
      <${StoryBox} name="drain" title="When the ball drains" list=${st.drain} ed=${ed} open=${open} onOpen=${setOpen} kinds=${["ball_end"]} />
      <div class="st-box st-things"><div class="st-box-hd row"><span class="st-title">What it keeps</span></div>
        <div class=${cx("small", !things.length && "muted")}>${things.length ? things.join(", ") : "No variables or timers: add them on the Blocks tab."}</div></div>
    </div>
    <${OpenRule} si=${open} ed=${ed} onClose=${() => setOpen(null)} hint="Press a rule to see and change its blocks. Drag a shot's rule to another box to change when it works." />
  </div>`;
}

// ------------------------------------------------------------------ Shot table
export function ShotTableView({ c, pg }) {
  const [open, setOpen, ed] = useOpenRule(useEd(pg, (c.blocks || {}).choices || {}));
  const prog = pg.prog;
  const scripts = prog.scripts || [];
  const grid = shotGrid(prog, ed.ch.shots || [], ed.ch);
  const lit = lights(prog);
  const unused = grid.rows.filter((r) => !r.used && r.kind === "shot").length;
  return html`<div class="rv-split">
    <div class="rv-scroll">
      <table class="sg-table">
        <thead><tr><th>Shot</th>${WHENS.map(([w, l]) => html`<th key=${w}>${l}</th>`)}</tr></thead>
        <tbody>
          ${grid.rows.map((r) => {
            const l = r.kind === "shot" ? lit.shots[r.key] : null;
            return html`<tr key=${r.key} class=${cx(!r.used && "unused")}>
              <th scope="row"><span class="row sg-shot">${l ? html`<span class=${cx("pf-swatch", !l.color && "dark")} style=${l.color ? { background: l.color } : null}></span>` : null}
                <span class=${cx(r.missing && "warn")}>${r.label}${r.missing ? " (not on this card)" : ""}</span></span></th>
              ${WHENS.map(([w]) => html`<td key=${w}>
                ${r.cells[w].map((si) => html`<button type="button" key=${si} class=${cx("sg-chip", open === si && "on")} onClick=${() => setOpen(si)}
                  ...${tip({ head: hatWords(scripts[si].hat, ed.ch), lines: [...ruleLines(scripts[si].do, ed.ch).map((l) => "  ".repeat(l.depth) + l.words), TIP.cell] })}>${gist(scripts[si], ed.ch)}</button>`)}
                <button type="button" class="sg-add" aria-label="Add a rule here" ...${tip(TIP.addCell)} onClick=${() => ed.addScript(cellHat(r, w))}>+</button>
              </td>`)}
            </tr>`;
          })}
        </tbody>
      </table>
      <div class="small muted sg-note">Press a rule to see and change its blocks, or + to add one. ${unused ? `${unused} of the game's shots do nothing in this mode yet.` : "Every shot does something in this mode."}</div>
      <div class="pf-group"><div class="pf-group-h"><span>Rules not tied to a shot</span><span class="sp"></span>
        <${Button} size="xs" kind="ghost" icon="plus" title=${TIP.addRule} onClick=${(e) => addRuleMenu(e, ed, ["mode_start", "mode_end", "every", "seconds_left", "ball_end", "timer_done"])}>Add a rule<//></div>
        ${grid.others.length ? grid.others.map((si) => html`<${RuleLine} key=${si} sc=${scripts[si]} si=${si} ed=${ed} open=${open === si} onOpen=${setOpen} />`)
          : html`<div class="small muted pf-empty">None.</div>`}
      </div>
    </div>
    ${open != null ? html`<div class="rv-side"><${OpenRule} si=${open} ed=${ed} onClose=${() => setOpen(null)} /></div>` : null}
  </div>`;
}

// ------------------------------------------------------------------ Timeline
const pct = (t, S) => (S ? Math.max(0, Math.min(100, (t / S) * 100)) : t ? 100 : 0);

export function TimelineView({ c, pg }) {
  const [open, setOpen, ed] = useOpenRule(useEd(pg, (c.blocks || {}).choices || {}));
  const prog = pg.prog;
  const scripts = prog.scripts || [];
  const tl = timelineOf(prog, ed.ch);
  const S = tl.seconds;
  const step = S > 120 ? 30 : S > 40 ? 10 : 5;
  const ticks = [];
  for (let t = 0; S && t <= S; t += step) ticks.push(t);
  const repeats = tl.moments.filter((m) => m.repeat).flatMap((m) => {
    const out = [];
    for (let t = m.repeat * 2; t < S; t += m.repeat) out.push({ t, si: m.si });
    return out;
  });
  // what adds or sets the clock without a fixed time: said on the Clock lane
  const clockBy = [];
  tl.whenever.forEach((si) => ruleLines(scripts[si].do, ed.ch).forEach((l) => {
    if (/^(Add .* seconds|Set the clock)/.test(l.words)) clockBy.push({ si, words: `${l.words}: ${hatWords(scripts[si].hat, ed.ch).replace(/^When /, "when ")}` });
  }));
  const laneRows = Object.fromEntries(LANES.map(([k]) => [k, 1]));
  tl.clips.forEach((x) => { laneRows[x.lane] = Math.max(laneRows[x.lane], x.row + 1); });
  return html`<div class="rv-scroll tl-view">
    <div class="rv-bar row"><span class="small muted grow">${S ? `The mode's ${S} seconds, left to right: what happens at its start, at each moment of its clock, and at its end.`
      : "This mode has no clock (it runs until something ends it): its start and its end."}</span>
      <${Button} size="sm" icon="plus" title=${TIP.addRule} onClick=${(e) => addRuleMenu(e, ed, ["mode_start", "mode_end", "every", "seconds_left"])}>Add a moment<//></div>
    <div class="tl-grid">
      <div class="tl-lab"></div>
      <div class="tl-track tl-head">
        ${ticks.map((t) => html`<span key=${"t" + t} class=${cx("tl-tick", t === S && "end")} style=${{ left: pct(t, S) + "%" }}>${t} s</span>`)}
        ${tl.moments.map((m, i) => html`<button type="button" key=${"m" + i} class=${cx("tl-moment", m.end && "end", open === m.si && "on")}
          style=${{ left: pct(m.t, S) + "%" }} onClick=${() => setOpen(m.si)} ...${tip(hatWords(scripts[m.si].hat, ed.ch))}>${m.label}</button>`)}
      </div>
      ${LANES.map(([k, label]) => html`
        <div class="tl-lab small" key=${"l" + k}>${label}</div>
        <div class=${cx("tl-track", "tl-lane", "tl-" + k)} key=${"r" + k} style=${{ height: 8 + laneRows[k] * 26 + "px" }}>
          ${tl.moments.map((m, i) => html`<span key=${"g" + i} class="tl-guide" style=${{ left: pct(m.t, S) + "%" }}></span>`)}
          ${k === "clock" ? repeats.map((r, i) => html`<span key=${"r" + i} class="tl-guide ghost" style=${{ left: pct(r.t, S) + "%" }}></span>`) : null}
          ${tl.clips.filter((x) => x.lane === k).map((x, i) => html`<button type="button" key=${i}
            class=${cx("tl-clip", "fam-" + x.fam, x.end && "end", x.cond && "cond", open === x.si && "on")}
            style=${{ left: pct(x.t, S) + "%", top: 4 + x.row * 26 + "px" }} onClick=${() => setOpen(x.si)}
            ...${tip({ head: x.words, lines: [hatWords(scripts[x.si].hat, ed.ch), ...(x.cond ? ["Only if its If says so"] : [])] })}>${x.words}</button>`)}
        </div>`)}
    </div>
    ${clockBy.length ? html`<div class="small muted tl-clockby">The clock also: ${clockBy.map((x, i) => html`<span key=${i} class="st-link" onClick=${() => setOpen(x.si)}>${x.words}</span>`)
      .flatMap((x, i) => (i ? ["; ", x] : [x]))}.</div>` : null}
    <div class="pf-group"><div class="pf-group-h" ...${tip(TIP.whenever)}>Rules with no fixed time</div>
      ${tl.whenever.length ? tl.whenever.map((si) => html`<${RuleLine} key=${si} sc=${scripts[si]} si=${si} ed=${ed} open=${open === si} onOpen=${setOpen} />`)
        : html`<div class="small muted pf-empty">None.</div>`}
    </div>
    <${OpenRule} si=${open} ed=${ed} onClose=${() => setOpen(null)} hint="Press a moment, a block on a lane or a rule to see and change its blocks." />
  </div>`;
}

// ------------------------------------------------------------------ Node graph
// Every rule a node on the left, every variable, timer and shot count the rules share a node on the right, and a wire
// for each use: solid where a rule sets it, dashed where one reads it, dotted where its running out sets one off
const NODE_W = 360, THING_W = 210, GAP = 10, LINE = 16, HEAD = 24, MAX_LINES = 4, GRAPH_W = 900;
const clip = (t, n) => (t.length > n ? t.slice(0, n - 1) + "…" : t);

export function NodeGraphView({ c, pg }) {
  const [open, setOpen, ed] = useOpenRule(useEd(pg, (c.blocks || {}).choices || {}));
  const [lit, setLit] = useState(null);
  const prog = pg.prog;
  const scripts = prog.scripts || [];
  const things = sharedUses(prog);
  let y = 8;
  const nodes = scripts.map((sc, si) => {
    const lines = ruleLines(sc.do, ed.ch);
    const shown = lines.slice(0, MAX_LINES);
    const h = HEAD + Math.max(1, shown.length + (lines.length > MAX_LINES ? 1 : 0)) * LINE + 8;
    const n = { si, y, h, title: hatWords(sc.hat, ed.ch), lines: shown, more: lines.length - shown.length };
    y += h + GAP;
    return n;
  });
  const H = Math.max(y, things.length * 56 + 16, 120);
  const tx = GRAPH_W - THING_W - 4;
  const tSpace = things.length ? (H - 16) / things.length : 0;
  const tNodes = things.map((t, i) => ({ ...t, y: 8 + i * tSpace + Math.max(0, (tSpace - 44) / 2), h: 44 }));
  const litThing = lit && tNodes.find((t) => t.key === lit);
  const litRules = new Set(litThing ? litThing.uses.map((u) => u.si) : []);
  const fade = (si) => litThing && !litRules.has(si);
  const KIND = { var: "variable", timer: "timer", hits: "hits of a shot" };
  return html`<div class="rv-split">
    <div class="rv-scroll ng-view">
      <div class="rv-bar row"><span class="small muted grow">Each rule, wired to what it shares with the others: solid where it sets a variable or timer, dashed where it reads one, dotted where a timer running out sets it off. Press a variable to light up its rules, or a rule to change its blocks.</span></div>
      ${things.length ? null : html`<div class="small muted">No rule shares a variable, a timer or a shot's count with another yet.</div>`}
      <svg class="ng-svg" viewBox=${`0 0 ${GRAPH_W} ${H}`} style=${{ aspectRatio: `${GRAPH_W} / ${H}` }} role="img" aria-label="The rules and what they share">
        ${tNodes.flatMap((t) => t.uses.map((u, k) => {
          const n = nodes[u.si];
          if (!n) return null;
          const x1 = NODE_W + 4, y1 = n.y + n.h / 2, x2 = tx, y2 = t.y + t.h / 2, mx = (x1 + x2) / 2;
          return html`<path key=${t.key + k} class=${cx("ng-wire", "ng-" + u.how, "ng-k-" + t.kind, litThing && (litThing.key === t.key ? "lit" : "dim"))}
            d=${`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} />`;
        }))}
        ${nodes.map((n) => html`<g key=${"n" + n.si} class=${cx("ng-node", open === n.si && "on", fade(n.si) && "dim")} transform=${`translate(4,${n.y})`}
            onClick=${() => setOpen(n.si)} ...${tip({ head: n.title, lines: ruleLines(scripts[n.si].do, ed.ch).map((l) => "  ".repeat(l.depth) + l.words) })}>
          <rect width=${NODE_W} height=${n.h} rx="8" />
          <rect class="ng-hat" width=${NODE_W} height=${HEAD} rx="8" /><rect class="ng-hat" y=${HEAD - 8} width=${NODE_W} height="8" />
          <text class="ng-title" x="10" y="16">${clip(n.title, 52)}</text>
          ${n.lines.map((l, i) => html`<text key=${i} class=${cx("ng-line", "fam-" + l.fam)} x=${12 + l.depth * 12} y=${HEAD + 13 + i * LINE}>${clip(l.words, 54 - l.depth * 2)}</text>`)}
          ${n.more ? html`<text class="ng-line ng-more" x="12" y=${HEAD + 13 + n.lines.length * LINE}>… ${n.more} more</text>` : null}
          ${n.lines.length ? null : html`<text class="ng-line ng-more" x="12" y=${HEAD + 13}>Does nothing yet</text>`}
        </g>`)}
        ${tNodes.map((t) => html`<g key=${t.key} class=${cx("ng-thing", "ng-k-" + t.kind, lit === t.key && "on", litThing && lit !== t.key && "dim")}
            transform=${`translate(${tx},${t.y})`} onClick=${() => setLit(lit === t.key ? null : t.key)} ...${tip(TIP.thing)}>
          <rect width=${THING_W} height=${t.h} rx="22" />
          <text class="ng-title" x="16" y="19">${clip(t.name, 24)}</text>
          <text class="ng-line" x="16" y="34">${KIND[t.kind]} · ${t.uses.length === 1 ? "1 use" : `${t.uses.length} uses`}</text>
        </g>`)}
      </svg>
      ${litThing ? html`<div class="pf-group"><div class="pf-group-h">Who uses ${litThing.name}</div>
        ${litThing.uses.map((u, i) => html`<div key=${i} class="row ng-use"><span class=${cx("ng-how", "ng-" + u.how)}>${TIP[u.how]}</span>
          <${RuleLine} sc=${scripts[u.si]} si=${u.si} ed=${ed} open=${open === u.si} onOpen=${setOpen} /></div>`)}
      </div>` : null}
    </div>
    ${open != null ? html`<div class="rv-side"><${OpenRule} si=${open} ed=${ed} onClose=${() => setOpen(null)} /></div>` : null}
  </div>`;
}

