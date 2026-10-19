// Modes: the Playfield view of a blocks mode (PAD-612, from PAD-611's plan). The game's own playfield picture, read
// off the person's card (modes.blocks_playfield), with every insert the port places on it: lit in the color the
// mode lights it, its shot picked by a click. The picked shot's card holds its rules, the same blocks as the Blocks
// tab and edited in place; rules tied to no shot are listed beside it, so nothing of the mode is hidden here.
//
// It is a tab over the one program (modes_blocks.js useModeProgram): an edit here is a step of the mode's one
// history and is saved to the same blocks.json; the Blocks tab shows it when opened.
//
// PAD-614: it is also every view's shot picker: beside each shot's list in a block, a button opens the same picture
// and a click on an insert picks its shot (or, for a Light block, the light itself).

import { html, useEffect, useRef, useState, Button, Note, tip, cx, call, openMenu } from "../core/ui.js";
import { Script, useEd, pickers } from "./modes_blocks.js";
import { lights, names, usedShots, hatWords, countBlocks } from "./modes_views.js";

const WHENS = [["idle", "While it is not running"], ["running", "While it runs"], ["any", "Any time"]];
const PACE = { blink: "pf-blink", hurry: "pf-blink fast", pulse: "pf-pulse", chase: "pf-pulse" };
// how the mode lights it, on its card and in an insert's tip
const LIT_WORDS = { solid: "lit solid", blink: "lit blinking", pulse: "lit pulsing", chase: "lit chasing",
  hurry: "lit blinking faster", off: "held dark" };
const LIT_TIPS = { solid: "The mode lights it solid", blink: "The mode lights it blinking", pulse: "The mode lights it pulsing",
  chase: "The mode lights it chasing", hurry: "The mode lights it blinking faster", off: "The mode holds it dark" };
const TIP = {
  noArt: "The game's own playfield picture could not be read from the card, so the inserts are drawn on an outline.",
  shot: "Press to see what the mode does when this shot is made.",
  noLight: "This shot has no light of its own on the picture.",
  add: "A new rule for this shot, at the end of the mode's rules: what it does when the shot is made.",
  lamp: "Not one of the game's shots: a Light block can light it by name, under The game's lights.",
  lampOff: "Not one of the game's shots, and not a light a block can light on this card.",
  picker: "Pick it on the playfield: the game's own picture, with the mode's lit shots on it.",
  pickHint: "Press an insert to pick its shot.",
  pickLamp: "Press an insert to pick its shot, or a light that is no shot's to light it alone.",
};

// The picture and its inserts, read once per mode while the page is open (the Playfield tab reads it again)
const fieldCache = new Map();
export function loadPlayfield(slug, fresh = false) {
  if (fresh || !fieldCache.has(slug)) {
    fieldCache.set(slug, Promise.resolve(call("modes.blocks_playfield")).then((r) => r || {}, () => ({})));
  }
  return fieldCache.get(slug);
}
function usePlayfield(slug, fresh) {
  const [pf, setPf] = useState(null);
  useEffect(() => {
    let live = true;
    setPf(null);
    loadPlayfield(slug, fresh).then((r) => { if (live) setPf(r); });
    return () => { live = false; };
  }, [slug]);
  return pf;
}

function Swatch({ l }) {
  return html`<span class=${cx("pf-swatch", !l.color && "dark")} style=${l.color ? { background: l.color } : null}></span>`;
}

// A rule, shut to its one line (what sets it off, how many blocks) or open to its blocks
function RuleRow({ sc, si, n, ed, open, onToggle }) {
  const k = countBlocks(sc);
  return html`<div class=${cx("pf-rule", open && "open")}>
    <button type="button" class="pf-rule-h" aria-expanded=${open ? "true" : "false"} onClick=${onToggle}>
      <span class="pf-rule-k">${open ? "▾" : "▸"}</span><span>${hatWords(sc.hat, ed.ch)}</span>
      <span class="small muted">${k === 1 ? "1 block" : `${k} blocks`}</span></button>
    ${open ? html`<${Script} s=${sc} si=${si} n=${n} ed=${ed} />` : null}
  </div>`;
}

// The picture and its inserts
function Field({ pf, lit, pick, onPick, used, cls }) {
  const ins = pf.inserts || [];
  const w = pf.w || Math.max(300, ...ins.map((i) => i.x + 24));
  const h = pf.h || Math.max(600, ...ins.map((i) => i.y + 40));
  const colorOf = (i) => lit.lamps[i.name] || i.shots.map((n) => lit.shots[n]).find(Boolean) || null;
  const sel = (i) => (pick.kind === "shot" ? i.shots.includes(pick.name) : i.name === pick.name);
  // a label under the first light of each shot the mode uses
  const labelled = new Set();
  const labels = [];
  ins.forEach((i) => i.shots.forEach((n) => {
    if (used.has(n) && !labelled.has(n)) { labelled.add(n); labels.push({ n, x: i.x, y: i.y + 17 }); }
  }));
  return html`<svg class=${cx("pf-svg", !pf.art && "pf-none", cls)} viewBox=${`0 0 ${w} ${h}`} style=${{ aspectRatio: `${w} / ${h}` }}
      role="img" aria-label="The playfield">
    ${pf.art ? html`<image class="pf-art" href=${pf.art} x="0" y="0" width=${w} height=${h} />`
      : html`<rect class="pf-outline" x="3" y="3" width=${w - 6} height=${h - 6} rx="48" />`}
    ${ins.map((i) => {
      const l = colorOf(i);
      const words = [i.name, i.shots.length ? "Shot: " + i.shots.join(", ") : "Not a shot's light",
        l ? LIT_TIPS[l.color ? l.pattern || "solid" : "off"] : ""].filter(Boolean);
      return html`<circle key=${i.name + i.x} class=${cx("pf-ins", l && l.color && "lit", l && l.color && PACE[l.pattern], sel(i) && "sel")}
        cx=${i.x} cy=${i.y} r=${sel(i) ? 8 : 6} style=${l && l.color ? { fill: l.color, color: l.color } : null}
        onClick=${(e) => onPick(i, e)} ...${tip({ head: words[0], lines: words.slice(1) })} />`;
    })}
    ${labels.map((t) => html`<text key=${"t" + t.n} class=${cx("pf-label", pick.kind === "shot" && pick.name === t.n && "sel")} x=${t.x} y=${t.y}
      text-anchor="middle">${t.n}</text>`)}
  </svg>`;
}

export function PlayfieldView({ c, pg }) {
  const ch = (c.blocks || {}).choices || {};
  const ed = useEd(pg, ch);
  const { prog } = pg;
  const pf = usePlayfield(c.slug, true);
  const [open, setOpen] = useState({});
  const shots = ch.shots || [];
  const used = usedShots(prog);
  const [pick, setPick] = useState(() => ({ kind: "shot", name: shots.find((n) => used.has(n)) || shots[0] || "" }));
  const lit = lights(prog);
  const scripts = prog.scripts || [];
  const toggle = (si) => setOpen((o) => ({ ...o, [si]: !o[si] }));
  const onInsert = (i) => {
    if (!i.shots.length) { setPick({ kind: "lamp", name: i.name }); return; }
    const k = pick.kind === "shot" ? i.shots.indexOf(pick.name) : -1;     // a light of several shots: each in turn
    setPick({ kind: "shot", name: i.shots[(k + 1) % i.shots.length] });
  };
  const placed = new Set((pf && pf.inserts || []).flatMap((i) => i.shots));
  const rows = (list) => list.map(([sc, si]) => html`<${RuleRow} key=${si} sc=${sc} si=${si} n=${scripts.length} ed=${ed}
    open=${!!open[si]} onToggle=${() => toggle(si)} />`);
  const all = scripts.map((sc, si) => [sc, si]);
  let card;
  if (pick.kind === "shot" && pick.name) {
    const own = all.filter(([sc]) => (sc.hat || {}).kind === "shot" && sc.hat.shot === pick.name);
    const others = all.filter(([sc]) => !((sc.hat || {}).kind === "shot" && sc.hat.shot === pick.name) && names(sc, pick.name));
    const l = lit.shots[pick.name];
    const lamps = (pf && pf.inserts || []).filter((i) => i.shots.includes(pick.name)).map((i) => i.name);
    card = html`<div class="pf-card">
      <div class="pf-card-hd row wrap">
        <span class="h3">${pick.name}</span>
        ${l ? html`<span class="row pf-litword"><${Swatch} l=${l} /><span class="small">${LIT_WORDS[l.color ? l.pattern || "solid" : "off"]}</span></span>`
          : html`<span class="small muted">not lit by this mode</span>`}
        <span class="sp"></span>
        <span class="small muted ellip">${lamps.length ? "Its lights: " + lamps.join(", ") : TIP.noLight}</span>
      </div>
      ${WHENS.map(([w, label]) => {
        const list = own.filter(([sc]) => (sc.hat.when || "any") === w);
        return html`<div class="pf-group" key=${w}>
          <div class="pf-group-h"><span>${label}</span><span class="sp"></span>
            <${Button} size="xs" kind="ghost" icon="plus" title=${TIP.add} onClick=${() => ed.addScript({ kind: "shot", shot: pick.name, when: w })}>Add a rule<//></div>
          ${list.length ? list.map(([sc, si]) => html`<${Script} key=${si} s=${sc} si=${si} n=${scripts.length} ed=${ed} />`)
            : html`<div class="small muted pf-empty">Nothing yet.</div>`}
        </div>`;
      })}
      ${others.length ? html`<div class="pf-group"><div class="pf-group-h">Other rules that name it</div>${rows(others)}</div>` : null}
    </div>`;
  } else if (pick.kind === "lamp") {
    const others = all.filter(([sc]) => names(sc, pick.name, true));
    const l = lit.lamps[pick.name];
    card = html`<div class="pf-card">
      <div class="pf-card-hd row wrap"><span class="h3">${pick.name}</span>
        ${l ? html`<span class="row pf-litword"><${Swatch} l=${l} /><span class="small">${LIT_WORDS[l.color ? l.pattern || "solid" : "off"]}</span></span>` : null}</div>
      <div class="small muted">${(ch.inserts || []).includes(pick.name) ? TIP.lamp : TIP.lampOff}</div>
      ${others.length ? html`<div class="pf-group"><div class="pf-group-h">Rules that light it</div>${rows(others)}</div>` : null}
    </div>`;
  }
  const free = all.filter(([sc]) => (sc.hat || {}).kind !== "shot");
  return html`<div class="pf-view">
    <div class="pf-field">
      ${pf == null ? html`<div class="small muted pf-reading">Reading the playfield picture off the card…</div>`
        : html`<${Field} pf=${pf} lit=${lit} pick=${pick} onPick=${onInsert} used=${used} />`}
      ${pf && pf.why ? html`<div class="small muted pf-why" ...${tip(TIP.noArt)}>${pf.why}</div>` : null}
    </div>
    <div class="pf-side">
      <div class="pf-shots" role="list" aria-label="Shots">
        ${shots.map((n) => {
          const l = lit.shots[n];
          return html`<button type="button" role="listitem" key=${n} class=${cx("pf-shot", used.has(n) && "used", pick.kind === "shot" && pick.name === n && "on")}
            onClick=${() => setPick({ kind: "shot", name: n })} ...${tip(placed.has(n) || pf == null ? TIP.shot : TIP.noLight)}>
            ${l ? html`<${Swatch} l=${l} />` : null}${n}</button>`;
        })}
      </div>
      ${card}
      ${pf && !(pf.inserts || []).length ? html`<${Note}>The app has no places for this game's inserts, so the shots are picked from the list above.<//>` : null}
      <div class="pf-group">
        <div class="pf-group-h">Rules not tied to a shot</div>
        ${free.length ? rows(free) : html`<div class="small muted pf-empty">None.</div>`}
      </div>
    </div>
  </div>`;
}

// PAD-614: the Playfield as a shot picker, beside a shot's list in any view's blocks. `lamps`: the prefix a light
// that is no shot's is picked with (a Light block's), else only shots are picked.
export function PickOnField({ value, ed, lamps, onPick }) {
  const [at, setAt] = useState(null);
  const box = useRef(null);
  const btn = useRef(null);
  const close = () => setAt(null);
  useEffect(() => {
    if (!at) return undefined;
    const onDown = (e) => {
      if (box.current && !box.current.contains(e.target) && !(btn.current && btn.current.contains(e.target))
          && !e.target.closest(".menu")) close();
    };
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
    window.addEventListener("mousedown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("mousedown", onDown, true); window.removeEventListener("keydown", onKey, true); };
  }, [at]);
  const toggle = (e) => {
    e.stopPropagation();
    if (at) { close(); return; }
    const r = e.currentTarget.getBoundingClientRect();
    const h = Math.min(620, window.innerHeight - 24);
    setAt({ left: Math.max(8, Math.min(r.left, window.innerWidth - 360)), top: Math.max(12, Math.min(r.bottom + 4, window.innerHeight - h - 12)), h });
  };
  const choose = (v) => { onPick(v); close(); };
  const picked = lamps && String(value || "").startsWith(lamps) ? { kind: "lamp", name: value.slice(lamps.length) }
    : { kind: "shot", name: value || "" };
  return html`<button type="button" ref=${btn} class=${cx("pf-pickbtn", at && "on")} aria-label="Pick it on the playfield"
      ...${tip(TIP.picker)} onClick=${toggle}>◎</button>
    ${at ? html`<${FieldPop} at=${at} box=${box} ed=${ed} lamps=${lamps} pick=${picked} onClose=${close} onChoose=${choose} />` : null}`;
}

function FieldPop({ at, box, ed, lamps, pick, onClose, onChoose }) {
  const pf = usePlayfield(ed.slug, false);
  const lit = lights(ed.prog);
  const used = usedShots(ed.prog);
  const onInsert = (i, e) => {
    const shots = i.shots.filter((n) => (ed.ch.shots || []).includes(n));
    const lamp = lamps && (ed.ch.inserts || []).includes(i.name);
    if (!shots.length) { if (lamp) onChoose(lamps + i.name); return; }
    if (shots.length === 1 && !lamp) { onChoose(shots[0]); return; }
    openMenu(e.currentTarget, [{ header: i.name }, ...shots.map((n) => ({ label: n, onClick: () => onChoose(n) })),
      ...(lamp ? [{ sep: true }, { label: `The light ${i.name} alone`, onClick: () => onChoose(lamps + i.name) }] : [])]);
  };
  return html`<div class="pf-pop" ref=${box} style=${{ left: at.left + "px", top: at.top + "px", height: at.h + "px" }}
      role="dialog" aria-label="Pick on the playfield" onClick=${(e) => e.stopPropagation()}>
    <div class="pf-pop-hd row"><span class="small muted grow">${lamps ? TIP.pickLamp : TIP.pickHint}</span>
      <button type="button" class="bk-x pf-pop-x" aria-label="Close" onClick=${onClose}>×</button></div>
    ${pf == null ? html`<div class="small muted pf-reading">Reading the playfield picture off the card…</div>`
      : (pf.inserts || []).length ? html`<${Field} pf=${pf} lit=${lit} pick=${pick} onPick=${onInsert} used=${used} cls="pf-svg-pop" />`
      : html`<div class="small muted pf-reading">The app has no places for this game's inserts, so the shots are picked from the list.</div>`}
    ${pf && pf.why ? html`<div class="small muted pf-why">${pf.why}</div>` : null}
  </div>`;
}

pickers.shot = PickOnField;
