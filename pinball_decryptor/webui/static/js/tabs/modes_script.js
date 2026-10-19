// Modes: the Script view of a blocks mode, and the app's own code editor (PAD-614, step 5 of PAD-611's plan).
//
// The Script is the same program as the blocks, typed: plugins/stern/mode_script.py writes it (modes.blocks_script)
// and reads it back (modes.blocks_read_script) to exactly the same blocks.json. It is a tab over the one program like
// the others: typing that reads as a program puts it in the blocks' place as one step of the mode's history, and an
// edit in another tab (or Undo) writes the text again. Text that does not read leaves the blocks as they were and
// says what is wrong on its line. The text is read with Python's own parser and never run.
//
// CodeEditor colors the words and numbers the lines; the C it makes is shown in it, and a mode written in C is edited
// in it too (modes.js CodePane), so C no longer needs the OS's editor.

import { html, useEffect, useRef, useState, Button, Note, tip, cx, call } from "../core/ui.js";
import { hatTemplates, hatLabel, stmtTemplates, stmtLabel } from "./modes_blocks.js";

const READ_MS = 450;
const TAB = "    ";
const TIP = {
  ref: "Press one to put it in at the cursor: a rule at the end, a block on the line under the cursor.",
  err: "Until this is put right the blocks stay as they were: nothing typed since is in the mode.",
  goto: "Put the cursor on that line",
};

// ------------------------------------------------------------------ coloring
const KW = {
  py: new Set(["with", "if", "else", "elif", "and", "or", "not", "pass", "True", "False", "None", "on"]),
  c: new Set(["if", "else", "for", "while", "do", "return", "static", "const", "void", "int", "unsigned", "signed", "char",
    "bool", "struct", "union", "switch", "case", "break", "continue", "default", "typedef", "enum", "true", "false", "NULL",
    "sizeof", "extern", "long", "short", "float", "double", "volatile", "inline", "goto",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t", "int64_t", "size_t"]),
};
const TOKEN = /("(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?)|(\b0[xX][0-9a-fA-F]+\b|\b\d[\d_]*(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+)|([^\sA-Za-z0-9_"']+)/g;

// One line as [{t, c}] pieces; `state.block`: inside a C /* comment */ carried from the line before
export function colorLine(line, lang, state = {}) {
  const out = [];
  let rest = line;
  if (lang === "c" && state.block) {
    const end = rest.indexOf("*/");
    if (end < 0) return [{ t: rest, c: "cm" }];
    out.push({ t: rest.slice(0, end + 2), c: "cm" });
    rest = rest.slice(end + 2);
    state.block = false;
  }
  if (lang === "c" && /^\s*#/.test(rest)) return [...out, { t: rest, c: "pp" }];
  let i = 0;
  while (i < rest.length) {
    const tail = rest.slice(i);
    if (lang === "py" && tail[0] === "#") { out.push({ t: tail, c: "cm" }); break; }
    if (lang === "c" && tail.startsWith("//")) { out.push({ t: tail, c: "cm" }); break; }
    if (lang === "c" && tail.startsWith("/*")) {
      const end = tail.indexOf("*/", 2);
      if (end < 0) { out.push({ t: tail, c: "cm" }); state.block = true; break; }
      out.push({ t: tail.slice(0, end + 2), c: "cm" });
      i += end + 2;
      continue;
    }
    TOKEN.lastIndex = 0;
    const m = TOKEN.exec(tail);
    if (!m || m.index !== 0) { out.push({ t: tail[0], c: "" }); i += 1; continue; }
    const [all, str, num, word] = m;
    let c = "";
    if (str) c = "st";
    else if (num) c = "nu";
    else if (word) {
      const after = tail.slice(all.length);
      if (KW[lang].has(word)) c = "kw";
      else if (/^\s*\(/.test(after)) c = "fn";
      else if (lang === "py" && /^\s*=(?!=)/.test(after)) c = "ar";
    }
    out.push({ t: all, c });
    i += all.length;
  }
  return out;
}

function Lines({ text, lang, err }) {
  const state = {};
  return text.split("\n").map((l, i) => html`<div key=${i} class=${cx("ce-l", err === i + 1 && "err")}>${colorLine(l, lang, state)
    .map((p, k) => (p.c ? html`<span key=${k} class=${"ce-" + p.c}>${p.t}</span>` : p.t))}</div>`);
}

function Gutter({ n, err, gut }) {
  const out = [];
  for (let i = 1; i <= n; i += 1) out.push(html`<div key=${i} class=${cx(err === i && "err")}>${i}</div>`);
  return html`<div class="ce-gutter" ref=${gut} aria-hidden="true">${out}</div>`;
}

// Read only: the C the blocks make
export function CodeView({ text, lang = "c" }) {
  const t = text || "";
  return html`<div class="ce ce-ro mono"><${Gutter} n=${t.split("\n").length} /><pre class="ce-hl"><${Lines} text=${t} lang=${lang} /></pre></div>`;
}

// Editable: a text box over its own colored copy, with the lines numbered and `err` (a line number) marked
export function CodeEditor({ text, lang, err, onInput, onKey, taRef, label }) {
  const pre = useRef(null);
  const gut = useRef(null);
  const own = useRef(null);
  const ta = taRef || own;
  const sync = () => {
    const el = ta.current;
    if (!el) return;
    if (pre.current) pre.current.style.transform = `translate(${-el.scrollLeft}px, ${-el.scrollTop}px)`;
    if (gut.current) gut.current.style.transform = `translateY(${-el.scrollTop}px)`;
  };
  useEffect(sync);
  const key = (e) => {
    if (onKey && onKey(e)) return;
    if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      const el = e.currentTarget;
      const [a, b] = [el.selectionStart, el.selectionEnd];
      const v = el.value;
      if (e.shiftKey) {                                       // take one indent off the line
        const ls = v.lastIndexOf("\n", a - 1) + 1;
        const n = v.slice(ls, ls + TAB.length).match(/^ */)[0].length;
        if (!n) return;
        onInput(v.slice(0, ls) + v.slice(ls + n));
        requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = Math.max(ls, a - n); });
        return;
      }
      onInput(v.slice(0, a) + TAB + v.slice(b));
      requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = a + TAB.length; });
    } else if (e.key === "Enter" && !e.ctrlKey && !e.altKey && !e.metaKey) {
      // the new line keeps the indent, one more after a line ending in ":" or "{"
      e.preventDefault();
      const el = e.currentTarget;
      const [a, b] = [el.selectionStart, el.selectionEnd];
      const v = el.value;
      const line = v.slice(v.lastIndexOf("\n", a - 1) + 1, a);
      const ind = line.match(/^\s*/)[0] + (/[:{]\s*$/.test(line) ? TAB : "");
      onInput(v.slice(0, a) + "\n" + ind + v.slice(b));
      requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = a + 1 + ind.length; });
    }
  };
  return html`<div class="ce mono">
    <div class="ce-gutter-box"><${Gutter} n=${text.split("\n").length} err=${err} gut=${gut} /></div>
    <div class="ce-body">
      <pre class="ce-hl" ref=${pre} aria-hidden="true"><${Lines} text=${text + "\n"} lang=${lang} err=${err} /></pre>
      <textarea class=${cx("ce-ta", lang === "py" && "sc-text")} ref=${ta} value=${text} spellcheck="false" wrap="off" autocapitalize="off"
        autocomplete="off" aria-label=${label} onInput=${(e) => onInput(e.currentTarget.value)} onScroll=${sync} onKeyDown=${key}></textarea>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ what a script can say
// A template as script text (mode_script.py's form for it)
function lit(v) {
  if (v == null) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(lit).join(", ") + "]";
  if (v.k === "num") return String(v.v);
  if (v.k === "var") return /^[A-Za-z_][A-Za-z0-9_]*$/.test(v.name || "") ? v.name : `var(${JSON.stringify(v.name || "")})`;
  return "{" + Object.entries(v).map(([k, x]) => `${JSON.stringify(k)}: ${lit(x)}`).join(", ") + "}";
}
const args = (o, skip) => Object.entries(o).filter(([k]) => k !== skip).map(([k, v]) => `${k}=${lit(v)}`).join(", ");
export const hatText = (h) => `with on.${h.kind}(${args(h, "kind")}):`;
export function stmtText(b) {
  if (b.op === "if") return Array.isArray(b.else) ? ["if running():", TAB + "pass", "else:", TAB + "pass"] : ["if running():", TAB + "pass"];
  return [`${b.op}(${args(b, "op")})`];
}

function Reference({ ch, prog, onHat, onStmt }) {
  const hats = hatTemplates(ch, prog.timers || []);
  return html`<div class="sc-ref" ...${tip(TIP.ref)}>
    <div class="pf-group-h">What sets a rule off</div>
    ${hats.map((h) => html`<button type="button" key=${h.kind} class="sc-ref-i" onClick=${() => onHat(h)}>
      <span class="mono">on.${h.kind}</span><span class="small muted">${hatLabel(h)}</span></button>`)}
    ${stmtTemplates(ch, prog.vars || [], prog).filter(([, items]) => items.length).map(([group, items]) => html`
      <div class="pf-group-h" key=${group}>${group}</div>
      ${items.map((b, i) => html`<button type="button" key=${group + i} class="sc-ref-i" onClick=${() => onStmt(b)}>
        <span class="mono">${b.op === "if" ? (b.else ? "if … else" : "if") : b.op}</span><span class="small muted">${stmtLabel(b)}</span></button>`)}`)}
    <div class="pf-group-h">Values</div>
    <div class="small muted sc-ref-words">A number, a variable by its name, a sum (a + b, a * b), or hits(shot="…"), scored(), total(), secs_left(), timer_left(timer="…"), balls(), player(). A condition compares two (&gt;=, ==, &lt;) and joins them with and, or, not.</div>
  </div>`;
}

// ------------------------------------------------------------------ the Script view
// The program typed text read as, in the blocks' place: one step of the mode's history ("script": typing merges into
// it), or nothing when it is the program already. True when it changed the mode.
const sorted = (v) => (Array.isArray(v) ? v.map(sorted) : v && typeof v === "object"
  ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);
export const sameProgram = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));

export function applyProgram(pg, program, now) {
  if (sameProgram(program, now)) return false;
  pg.edit((d) => { Object.keys(d).forEach((k) => { delete d[k]; }); Object.assign(d, JSON.parse(JSON.stringify(program))); }, "script");
  return true;
}

export function ScriptView({ c, pg }) {
  const ch = (c.blocks || {}).choices || {};
  const [text, setText] = useState(null);
  const [err, setErr] = useState(null);
  const [reading, setReading] = useState(false);
  const mine = useRef(null);            // the program (JSON) the text is
  const progRef = useRef(pg.prog);
  progRef.current = pg.prog;
  const timer = useRef(null);
  const seq = useRef(0);
  const ta = useRef(null);
  const progJson = JSON.stringify(pg.prog);
  // the blocks changed in another tab, or by Undo: write the text again
  useEffect(() => {
    if (mine.current === progJson) return undefined;
    let live = true;
    Promise.resolve(call("modes.blocks_script", pg.prog)).then((r) => {
      if (!live || !r || typeof r.text !== "string") return;
      mine.current = progJson;
      seq.current += 1;
      clearTimeout(timer.current);
      setText(r.text);
      setErr(null);
      setReading(false);
    });
    return () => { live = false; };
  }, [progJson]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const read = (t) => {
    const n = ++seq.current;
    Promise.resolve(call("modes.blocks_read_script", t)).then((r) => {
      if (n !== seq.current || !r) return;
      setReading(false);
      if (r.error) { setErr({ line: r.line || 0, msg: r.error }); return; }
      setErr(null);
      mine.current = JSON.stringify(r.program);
      applyProgram(pg, r.program, progRef.current);
    });
  };
  const onInput = (t) => {
    setText(t);
    setReading(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => read(t), READ_MS);
  };
  const putAt = (lines, end) => {
    const el = ta.current;
    const v = text || "";
    let at, ins;
    if (end || !el) {
      at = v.length;
      ins = (v.endsWith("\n") ? "\n" : "\n\n") + lines.join("\n") + "\n";
    } else {
      const a = el.selectionStart;
      const le = v.indexOf("\n", a);
      at = le < 0 ? v.length : le;
      const line = v.slice(v.lastIndexOf("\n", at - 1) + 1, at);
      const ind = line.match(/^\s*/)[0] + (/:\s*$/.test(line) ? TAB : "");
      ins = lines.map((l) => "\n" + ind + l).join("");
    }
    const next = v.slice(0, at) + ins + v.slice(at);
    onInput(next);
    if (el) requestAnimationFrame(() => { el.focus(); el.selectionStart = el.selectionEnd = at + ins.length; });
  };
  const goto = (line) => {
    const el = ta.current;
    if (!el || !line) return;
    const v = el.value;
    let a = 0;
    for (let i = 1; i < line && a >= 0; i += 1) a = v.indexOf("\n", a) + 1;
    el.focus();
    el.selectionStart = a;
    el.selectionEnd = Math.max(a, v.indexOf("\n", a) < 0 ? v.length : v.indexOf("\n", a));
    el.scrollTop = Math.max(0, (line - 4) * 19);
  };
  return html`<div class="sc-view">
    <div class="sc-main">
      <div class="rv-bar row"><span class="small muted grow">The same mode as text: type here and the blocks follow; change the blocks and this follows. It is read, never run.</span>
        <span class=${cx("small", err ? "warn" : "muted")}>${text == null ? "Writing it out…" : reading ? "Reading…" : err ? "Not read: the blocks are as they were" : "In the blocks"}</span></div>
      ${text == null ? html`<div class="small muted">Writing the mode out as text…</div>`
        : html`<${CodeEditor} text=${text} lang="py" err=${err && err.line} onInput=${onInput} taRef=${ta} label="The mode as a script" />`}
      ${err ? html`<div class="sc-err row" role="alert" ...${tip(TIP.err)}><span class="grow">${err.msg}</span>
        ${err.line ? html`<${Button} size="xs" kind="ghost" title=${TIP.goto} onClick=${() => goto(err.line)}>Go to line ${err.line}<//>` : null}</div>` : null}
    </div>
    <${Reference} ch=${ch} prog=${pg.prog} onHat=${(h) => putAt([hatText(h), TAB + "pass"], true)} onStmt=${(b) => putAt(stmtText(b), false)} />
  </div>`;
}

// ------------------------------------------------------------------ a mode written in C, edited here
export function CEditor({ c }) {
  const [text, setText] = useState(null);
  const [saved, setSaved] = useState(null);
  const [why, setWhy] = useState("");
  const load = () => Promise.resolve(call("modes.code_text")).then((r) => {
    if (!r) return;
    setText(r.text || "");
    setSaved(r.text || "");
    setWhy(r.error || "");
  });
  useEffect(() => { setText(null); load(); }, [c.slug]);
  const dirty = text != null && text !== saved;
  const save = () => Promise.resolve(call("modes.code_save", text)).then((r) => {
    if (r && r.ok) { setSaved(text); setWhy(""); } else setWhy((r && r.error) || "It could not be saved.");
  });
  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key || "").toLowerCase() === "s") { e.preventDefault(); if (dirty) save(); return true; }
    return false;
  };
  return html`<div class="stack ce-cmode">
    <div class="row wrap">
      <${Button} size="sm" kind="primary" icon="save" disabled=${!dirty} onClick=${save}>Save<//>
      <${Button} size="sm" kind="ghost" disabled=${!dirty} title="Put back what is saved" onClick=${() => setText(saved)}>Undo changes<//>
      <${Button} size="sm" kind="ghost" title="Read the file again (after a change in another editor)" onClick=${load}>Read again<//>
      <span class=${cx("small", dirty ? "warn" : "muted")}>${dirty ? "Not saved (Ctrl+S saves)" : "Saved"}</span>
    </div>
    ${why ? html`<${Note} kind="warn">${why}<//>` : null}
    ${text == null ? html`<div class="small muted">Reading ${c.slug}.c…</div>`
      : html`<${CodeEditor} text=${text} lang="c" onInput=${setText} onKey=${onKey} label=${c.slug + ".c"} />`}
  </div>`;
}
