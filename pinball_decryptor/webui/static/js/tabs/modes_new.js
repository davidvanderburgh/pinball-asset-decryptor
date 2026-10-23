// Making a new mode (PAD-652): New opens a wizard instead of a drop-down. Its first step is
// three tiles, one per way of building a mode, each saying what it takes and what it can do:
// Blocks (recommended), C (recommended to hand to an AI agent) and the form (a playground).
// The second step is that way's own: a name for blocks; a name, an optional brief for an
// agent and the SDK's guide for C; a blank form or the form example (PAD-691: TARGET RUSH on every game).
// The first-mode page shows the same tiles in place, and a tile there opens the wizard at
// its second step. Python makes the mode (modes.new / example / new_blocks_mode /
// new_code_mode / blocks_example); this only asks.

import { html, useEffect, useRef, useState, Modal, Button, Field, Chip, Note, Icon, tip, cx, call } from "../core/ui.js";

// The three ways, in the order they are offered. level: how much it asks of a person (1-3).
export const KINDS = [
  { key: "blocks", icon: "blocks", title: "Blocks", badge: "Recommended", badgeKind: "ok",
    pitch: "Snap rules together: when a shot is made, score it; if a count gets high enough, start the mode.",
    level: 2, levelWords: "No coding",
    can: ["Rules of your own: counts, If … else, timers",
          "Light shows, words on screen, callouts, multiball",
          "Eight views of one mode: Blocks, Rule cards, Story, Playfield…"],
    cant: ["Calls the blocks don't have (Edit as C carries on in C)"],
    workIn: "The app turns the blocks into C for you." },
  { key: "c", icon: "edit", title: "C", badge: "Best with an AI agent", badgeKind: "info",
    pitch: "Write the mode in C on the Mode SDK, or have an AI agent write it: the SDK's guide is written for one.",
    level: 3, levelWords: "A programmer, or an AI agent",
    can: ["Everything the Mode SDK can do",
          "Boss fights, hurry-ups, combo chains, wizard modes",
          "A clip, picture, music and calls of its own"],
    cant: ["The app's editors: it is C, edited as text"],
    workIn: "Starts from the SDK's template or a C example." },
  { key: "form", icon: "list", title: "Form", badge: "Playground", badgeKind: "",
    pitch: "The bare minimum: fill in the boxes for a quick mode to play with.",
    level: 1, levelWords: "Anyone",
    can: ["What starts it, how long it runs, points per shot",
          "Its screen, clip, sounds and lights"],
    cant: ["Rules of your own: no counters, no If, no phases"],
    workIn: "Boxes to fill in; nothing to learn." },
];

const KIND = Object.fromEntries(KINDS.map((k) => [k.key, k]));

// why a way can't be used here, or ""
export function kindOff(s, key) {
  if (!s.project) return s.project_label || "Pick a project first.";
  if (key === "form") return s.new_ok || s.ex_ok ? "" : (s.cap_text || s.ex_tip || s.project_label);
  return s.no_port || "";
}

function Level({ n, words }) {
  return html`<div class="nmw-level" ...${tip("How much it asks of you: " + words)}>
    <span class="nmw-level-lbl">Skill</span>
    <span class="nmw-level-bar" aria-hidden="true">${[1, 2, 3].map((i) => html`<span key=${i} class=${cx(i <= n && "on")}></span>`)}</span>
    <span class="nmw-level-words">${words}</span>
  </div>`;
}

function Tile({ k, off, onPick, compact }) {
  return html`<button type="button" class=${cx("nmw-tile", "nmw-" + k.key, off && "off", compact && "compact")} data-kind=${k.key}
      disabled=${!!off} onClick=${() => onPick(k.key)} ...${off ? tip(off) : {}}>
    <div class="nmw-tile-top">
      <span class="nmw-tile-ic"><${Icon} name=${k.icon} /></span>
      <span class="nmw-tile-title">${k.title}</span>
      ${k.badge ? html`<span class=${cx("nmw-badge", k.badgeKind)}>${k.badge}</span>` : null}
    </div>
    <div class="nmw-pitch">${k.pitch}</div>
    <${Level} n=${k.level} words=${k.levelWords} />
    <ul class="nmw-can">
      ${k.can.map((c) => html`<li key=${c}><${Icon} name="check" /><span>${c}</span></li>`)}
      ${k.cant.map((c) => html`<li key=${c} class="no"><${Icon} name="x" /><span>${c}</span></li>`)}
    </ul>
    <div class="nmw-tile-ft">
      <span class="nmw-work">${off || k.workIn}</span>
      <span class="nmw-go">${off ? null : html`Choose <${Icon} name="right" />`}</span>
    </div>
  </button>`;
}

// The three tiles: the wizard's first step, and the first-mode page's choice.
export function KindTiles({ s, onPick, compact }) {
  return html`<div class=${cx("nmw-tiles", compact && "compact")}>
    ${KINDS.map((k) => html`<${Tile} key=${k.key} k=${k} off=${kindOff(s, k.key)} onPick=${onPick} compact=${compact} />`)}
  </div>`;
}

function EnterKey({ onEnter }) {
  const ref = useRef(onEnter);
  ref.current = onEnter;
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Enter" || e.shiftKey || (e.target && e.target.tagName === "TEXTAREA")) return;
      e.preventDefault(); ref.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return null;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

// What an AI agent is told: the mode's file, the SDK's guide, and what the mode is to do.
export function agentBrief({ game, file, sdkDoc, brief }) {
  return [
    `Write a game mode in C for ${game || "this Stern Spike 2 game"}.`,
    brief && brief.trim() ? `What it does: ${brief.trim()}` : "What it does: (describe the mode here)",
    `Its file is ${file}: a copy of the Mode SDK's template, already in the card project. Change only that mode's folder.`,
    `Read ${sdkDoc} top to bottom first, then pad_mode.h and template_mode.c beside it. MODE_SDK.md says how to build the mode and test it in the emulator.`,
  ].join("\n");
}

function NameField({ id, name, setName, ask }) {
  return html`<div class="stack nmw-name">
    <label class="lbl" for=${id}>${ask || "What is the mode called?"}</label>
    <${Field} id=${id} value=${name} onChange=${setName} autoFocus />
  </div>`;
}

// PAD-658: the blocks examples for this card's title (PAD-675: just TARGET RUSH, on every game)
function BlocksExamples({ s, onExample }) {
  const all = s.blocks_examples || [];
  if (!all.length) return null;
  const group = (title, list) => list.length ? html`<div class="stack">
      <div class="nmw-sub">${title}</div>
      <div class="nmw-exlist">${list.map((x) => html`<button type="button" key=${x.name} class="nmw-ex"
          onClick=${() => onExample(x.name)} ...${tip({ head: x.about || x.name, lines: (x.lost || []).length
            ? ["What the blocks lost against its C:", ...x.lost.map((l) => "- " + l)] : [] })}><${Icon} name="blocks" /><span class="ellip">${x.name}</span><${Icon} name="right" /></button>`)}</div>
    </div>` : null;
  return html`<div class="nmw-cols">
    <div class="stack nmw-col">${group("Or start from the example", all.filter((x) => !x.based_on))}</div>
    <div class="stack nmw-col">${group("Or one of the C examples, in blocks", all.filter((x) => x.based_on))}</div>
  </div>`;
}

function BlocksStep({ s, name, setName, onExample }) {
  return html`<div class="nmw-step">
    <${NameField} id="nmw-blocks-name" name=${name} setName=${setName} />
    <div class="nmw-how">
      <div class="nmw-how-row"><span class="nmw-num">1</span><span>It starts as a small working mode on this card's shots: a shot starts it, every shot scores.</span></div>
      <div class="nmw-how-row"><span class="nmw-num">2</span><span>Drag blocks from the left into its rules: when something happens, do this.</span></div>
      <div class="nmw-how-row"><span class="nmw-num">3</span><span>Try it builds it in and plays it in the emulator.</span></div>
    </div>
    <${BlocksExamples} s=${s} onExample=${onExample} />
  </div>`;
}

function CStep({ s, name, setName, brief, setBrief }) {
  return html`<div class="nmw-step">
    <div class="nmw-cols">
      <div class="stack nmw-col">
        <div class="nmw-sub">A blank mode</div>
        <${NameField} id="nmw-c-name" name=${name} setName=${setName} />
        <div class="small muted wrap">A copy of the Mode SDK's template (TARGET RUSH, which uses nearly every call) in this project's modes folder, opened for you.</div>
        <div class="nmw-agent">
          <div class="row"><${Icon} name="star" /><b>With an AI agent</b></div>
          <div class="small muted wrap">Say what the mode should do. Make it and copy for an agent makes the mode, then copies what to tell the agent: its file, the SDK's guide, and this.</div>
          <textarea class="nmw-brief" rows="3" placeholder="A two-minute hurry-up: the ramps light one by one, each pays more than the last…"
            value=${brief} onInput=${(e) => setBrief(e.currentTarget.value)}></textarea>
        </div>
      </div>
      <div class="stack nmw-col">
        <div class="nmw-sub">The SDK's guide</div>
        <div class="small muted wrap">Every call a mode can make, what each does on the machine, and how to build and try it.</div>
        <button type="button" class="modes-doc-link small nmw-sdk" ...${tip(s.sdk_doc || "")} onClick=${() => call("modes.open_sdk_doc")}>
          <${Icon} name="file" /> Open MODE_SDK.md, the SDK's guide</button>
      </div>
    </div>
  </div>`;
}

function FormStep({ s, onBlank, onExample }) {
  const ex = (s.examples || []).filter((x) => !x.code);
  return html`<div class="nmw-step">
    <div class="small muted wrap">A playground: a form mode can't have rules of its own. For more, make it from Blocks.</div>
    <div class="nmw-exgrid">
      <button type="button" class="nmw-ex big" disabled=${!s.new_ok} onClick=${onBlank} ...${s.new_ok ? {} : tip(s.cap_text || s.project_label)}>
        <${Icon} name="plus" /><span class="nmw-ex-words"><b>Blank mode</b><span class="small muted">Start empty and fill in the boxes.</span></span></button>
      ${ex.map((x) => html`<button type="button" key=${x.name} class="nmw-ex big"
          disabled=${!s.ex_ok || x.disabled} onClick=${() => onExample(x.name)}>
        <${Icon} name="play" /><span class="nmw-ex-words"><b>${x.name}</b><span class="small muted">A finished example to play and change.</span></span></button>`)}
    </div>
    ${!ex.length && s.ex_tip ? html`<div class="small dim">${s.ex_tip}</div>` : null}
  </div>`;
}

// The wizard. start: a way's key to open at its second step, or "" for the tiles.
export function NewModeWizard({ s, start = "", onClose }) {
  const [kind, setKind] = useState(start || "");
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [copied, setCopied] = useState("");
  const k = KIND[kind];
  const named = !!name.trim();
  const make = async (agent) => {
    if (kind === "blocks" && named) { call("modes.new_blocks_mode", name.trim()); onClose(); return; }
    if (kind !== "c" || !named) return;
    const file = await call("modes.new_code_mode", name.trim());
    if (agent && file) {
      const ok = await copyText(agentBrief({ game: s.title_label || s.card_label, file, sdkDoc: s.sdk_doc, brief }));
      if (!ok) { setCopied("Could not copy: the mode is made, its file is " + file); return; }
    }
    onClose();
  };
  const back = html`<${Button} kind="ghost" icon="left" onClick=${() => { setKind(""); setCopied(""); }}>Back<//>`;
  const limits = html`<button type="button" class="modes-doc-link small" ...${tip("Opens the Tips for this tab")}
      onClick=${() => call("modes.open_limits_doc")}>What a mode can and can't do</button>`;
  const footer = !k ? html`${limits}<span class="grow"></span><${Button} onClick=${onClose}>Cancel<//>`
    : kind === "blocks" ? html`${back}<span class="grow"></span><${Button} onClick=${onClose}>Cancel<//>
        <${Button} kind="primary" icon="blocks" disabled=${!named} onClick=${() => make(false)}>Make it<//>`
    : kind === "c" ? html`${back}<span class="grow"></span>${copied ? html`<span class="small warn-ink">${copied}</span>` : null}
        <${Button} onClick=${onClose}>Cancel<//>
        <${Button} icon="copy" disabled=${!named} onClick=${() => make(true)}
          title="Makes the mode, then copies what to tell an AI agent: the mode's file, the SDK's guide to read first, and what you said it should do.">Make it and copy for an agent<//>
        <${Button} kind="primary" icon="edit" disabled=${!named} onClick=${() => make(false)}>Make it<//>`
    : html`${back}<span class="grow"></span><${Button} onClick=${onClose}>Cancel<//>`;
  const title = !k ? "New mode" : kind === "form" ? "New mode: Form" : "New mode: " + k.title;
  const pick = (key) => { setKind(key); setCopied(""); };
  return html`<${Modal} title=${title} icon=${k ? k.icon : "plus"} xwide=${!k} wide=${!!k} cls="nmw" onClose=${onClose} footer=${footer}>
    ${!k ? html`<div class="nmw-intro">
        <div class="nmw-lead">How do you want to build it?</div>
        <div class="small muted wrap">Each way makes a mode that plays inside the game, with the game's own scoring, sound, lights and display. A project can mix them.</div>
      </div>
      ${!s.project ? html`<${Note} kind="warn">${s.project_label}<//>` : s.no_port ? html`<${Note} kind="warn">${s.no_port}<//>` : null}
      <${KindTiles} s=${s} onPick=${pick} />`
    : html`<div class="nmw-crumb"><span class=${cx("nmw-tile-ic", "nmw-" + kind)}><${Icon} name=${k.icon} /></span>
        <span class="nmw-pitch">${k.pitch}</span></div>
      ${kind === "blocks" ? html`<${BlocksStep} s=${s} name=${name} setName=${setName}
            onExample=${(n) => { call("modes.blocks_example", n); onClose(); }} />`
        : kind === "c" ? html`<${CStep} s=${s} name=${name} setName=${setName} brief=${brief} setBrief=${setBrief} />`
        : html`<${FormStep} s=${s} onBlank=${() => { call("modes.new"); onClose(); }}
            onExample=${(n) => { call("modes.example", n); onClose(); }} />`}`}
    ${k && kind !== "form" ? html`<${EnterKey} onEnter=${() => make(false)} />` : null}
  <//>`;
}
