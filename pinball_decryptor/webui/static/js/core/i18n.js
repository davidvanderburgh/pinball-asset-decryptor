// The app's languages (PAD-458, docs/plans/app_languages.md).
//
// The page is written in English and translated where it is SHOWN: every
// text node the page draws (and every placeholder) is looked up in the
// language's catalog, /static/i18n/<lang>.json, and the translation put in
// its place.  So the tabs, Python's labels and messages, dialogs, menus and
// tooltips all follow the language without any of them knowing about it.
//
// A catalog maps English to the language.  A key with {} holes is a
// TEMPLATE: a hole matches any run of text (numbers included), and the
// translation fills its holes in order, or by number ({1} ... {0}).  The
// same lookup is in Python (webui/i18n.py) for the ? window's words.
//
// Preact owns the text nodes: when it changes one it writes new English
// over our translation, the observer sees a text that is not the one we
// put there, and translates that.  Text that sits side by side in one
// element ("Saved ", "12", " files") is looked up joined, so a sentence
// with a number in it is one catalog entry.
//
// Never translated: anything inside class "notr" (the log, which stays
// English so support reports read the same everywhere; names of games and
// projects; the game's own words in a table), text fields, code, and the
// page's own scripts and styles.  Not translate="no": Preact sets that as
// the DOM property, and it comes out "yes".

let lang = "en";
let cat = null;          // {exact: Map, buckets: Map, general: []}
let observer = null;
const cache = new Map();
const CACHE_MAX = 20000;
const own = new WeakMap();     // text node -> {src, out}: what we put there, and its English
const ownAttr = new WeakMap(); // element -> {attr: {src, out}}
const ATTRS = ["placeholder"];
const SKIP = 'textarea, script, style, code, .notr, [translate="no"], [contenteditable="true"]';

const WS = /[\s ]+/g;
// a template needs this many letters of its own (webui/i18n.py MIN_LETTERS)
const MIN_LETTERS = 4;
// an English grammar word or plural ending in a hole ("{} file{}" with "s",
// "it {} not" with "does") would land in the translation as English: such a
// match is no match, and the text stays English, whole (webui/i18n.py _GRAMMAR)
const GRAMMAR = /^(?:s|es|ies|y|is|are|was|were|does|do|did|has|have|it|its|they|them|their|this|these|that|those|one|isn't|aren't|doesn't|don't)$/i;
const norm = (s) => s.replace(WS, " ").trim();
const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function currentLanguage() { return lang; }

export function compile(mapping) {
  const exact = new Map(), buckets = new Map(), general = [];
  for (const [k0, v] of Object.entries(mapping || {})) {
    if (typeof v !== "string" || !v || k0.startsWith("_")) continue;
    const k = norm(k0);
    if (!k.includes("{}")) { exact.set(k, v); continue; }
    const parts = k.split("{}");
    // "{} of {}" would turn a game called "House of Horrors" into "House de Horrors"
    if ((parts.join("").match(/[A-Za-z]/g) || []).length < MIN_LETTERS) continue;
    const lit = parts.reduce((n, p) => n + p.trim().length, 0);
    const entry = { lit, rx: new RegExp("^" + parts.map(escRe).join("(.*?)") + "$", "s"), v };
    let b = null;
    if (parts[0].length >= 2) b = "p" + parts[0].slice(0, 2);
    else if (parts[parts.length - 1].length >= 2) b = "s" + parts[parts.length - 1].slice(-2);
    if (b) { if (!buckets.has(b)) buckets.set(b, []); buckets.get(b).push(entry); }
    else general.push(entry);
  }
  for (const list of [...buckets.values(), general]) list.sort((a, b) => b.lit - a.lit);
  return { exact, buckets, general };
}

function fill(c, v, groups) {
  groups = groups.map((g) => { const t = c.exact.get(g.trim()); return t === undefined ? g : t; });
  let i = 0;
  return v.replace(/\{(\d*)\}/g, (_, n) => {
    const at = n === "" ? i++ : Number(n);
    return at < groups.length ? groups[at] : "";
  });
}

// The translation of one line of text in catalog *c*, or null.
export function lookup(c, text) {
  const s = norm(text);
  if (!s || !c) return null;
  const hit = c.exact.get(s);
  if (hit !== undefined) return hit;
  const cands = [...(c.buckets.get("p" + s.slice(0, 2)) || []),
    ...(c.buckets.get("s" + s.slice(-2)) || []), ...c.general];
  for (const e of cands) {
    const m = e.rx.exec(s);
    if (m && !m.slice(1).some((g) => GRAMMAR.test(g))) return fill(c, e.v, m.slice(1));
  }
  return null;
}

// *text* in the current language (itself when nothing matches).  A text of
// several lines is looked up a line at a time; the blanks around it stay.
export function t(text) {
  if (!cat || text == null) return text;
  const s = String(text);
  if (!/[A-Za-z]{2}/.test(s)) return s;
  let got = cache.get(s);
  if (got !== undefined) return got;
  if (s.includes("\n")) {
    got = s.split("\n").map((ln) => t(ln)).join("\n");
  } else {
    const lead = s.match(/^[\s ]*/)[0], tail = s.match(/[\s ]*$/)[0];
    const tr = lookup(cat, s);
    got = tr == null ? s : lead + tr + tail;
  }
  if (cache.size > CACHE_MAX) cache.clear();
  cache.set(s, got);
  return got;
}

function skipped(node) {
  const el = node.nodeType === 1 ? node : node.parentElement;
  return !el || !!el.closest(SKIP);
}

// The English a text node holds: its own text, or what we translated over.
function srcOf(node) {
  const r = own.get(node);
  return r && r.out === node.data ? r.src : node.data;
}

function put(node, src, out) {
  own.set(node, { src, out });
  if (node.data !== out) node.data = out;
}

// One element's text children, a run of neighbours at a time.
function doChildren(el) {
  if (!el || skipped(el)) return;
  let run = [];
  const flush = () => {
    if (!run.length) return;
    if (run.length === 1) {
      const n = run[0], src = srcOf(n);
      put(n, src, cat ? t(src) : src);
    } else {
      const srcs = run.map(srcOf);
      const whole = srcs.join("");
      const tr = cat ? t(whole) : whole;
      if (cat && tr !== whole) {
        run.forEach((n, i) => put(n, srcs[i], i === 0 ? tr : ""));
      } else {
        run.forEach((n, i) => put(n, srcs[i], cat ? t(srcs[i]) : srcs[i]));
      }
    }
    run = [];
  };
  for (let n = el.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 3) run.push(n);
    else flush();
  }
  flush();
  doAttrs(el);
}

function doAttrs(el) {
  for (const a of ATTRS) {
    if (!el.hasAttribute || !el.hasAttribute(a)) continue;
    const cur = el.getAttribute(a);
    let rec = ownAttr.get(el);
    if (!rec) { rec = {}; ownAttr.set(el, rec); }
    const r = rec[a];
    const src = r && r.out === cur ? r.src : cur;
    const out = cat ? t(src) : src;
    rec[a] = { src, out };
    if (cur !== out) el.setAttribute(a, out);
  }
}

function doTree(root) {
  if (!root) return;
  if (root.nodeType === 3) { doChildren(root.parentElement); return; }
  if (root.nodeType !== 1 || skipped(root)) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
    acceptNode: (el) => (el.matches(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let el = root; el; el = walker.nextNode()) doChildren(el);
}

function onMutations(records) {
  const parents = new Set();
  for (const r of records) {
    if (r.type === "characterData") {
      const own_ = own.get(r.target);
      if (own_ && own_.out === r.target.data) continue;       // our own write
      if (r.target.parentElement) parents.add(r.target.parentElement);
    } else if (r.type === "attributes") {
      doAttrs(r.target);
    } else {
      if (r.target.nodeType === 1) parents.add(r.target);
      for (const n of r.addedNodes) if (n.nodeType === 1) doTree(n);
    }
  }
  for (const p of parents) doChildren(p);
}

function watch() {
  if (observer) return;
  observer = new MutationObserver(onMutations);
  observer.observe(document.documentElement, {
    subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: ATTRS,
  });
}

const loaded = new Map();
let asked = 0;
async function load(code) {
  if (loaded.has(code)) return loaded.get(code);
  const r = await fetch("/static/i18n/" + code + ".json", { cache: "no-cache" });
  if (!r.ok) throw new Error("no catalog for " + code);
  const c = compile(await r.json());
  loaded.set(code, c);
  return c;
}

// What the page shows that is still English (a catalog's gaps; for the
// harvester's checks, scripts/i18n_extract.py).
export function untranslated(root = document.body) {
  const out = new Set();
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (skipped(n) || !/[A-Za-z]{3}/.test(n.data)) continue;
    const r = own.get(n);
    if (!r || (r.out === n.data && r.src === r.out)) {
      // a run's whole text, as the lookup saw it
      const p = n.parentElement;
      let whole = "";
      for (let c = p.firstChild; c; c = c.nextSibling) if (c.nodeType === 3) whole += srcOf(c); else whole += "\u0000";
      for (const piece of whole.split("\u0000")) {
        if (!/[A-Za-z]{3}/.test(piece)) continue;
        const known = piece.includes("\n") ? piece.split("\n").every((l) => !/[A-Za-z]{3}/.test(l) || lookup(cat, l) != null)
          : lookup(cat, piece) != null;
        if (!known) out.add(norm(piece));
      }
    }
  }
  return [...out];
}

// Switch the page to language *code* ("en" puts the English back).  A test
// hands its own *mapping* instead of the catalog file.
export async function setLanguage(code, mapping = null) {
  code = String(code || "en").toLowerCase();
  if (code === lang && !mapping) return;
  const mine = ++asked;
  let c = null;
  if (mapping) c = compile(mapping);
  else if (code !== "en") {
    try { c = await load(code); } catch (e) { console.warn(e); code = "en"; }
  }
  if (mine !== asked) return;               // a later choice came in while this one loaded
  lang = code;
  cat = c;
  cache.clear();
  document.documentElement.lang = code;
  watch();
  doTree(document.documentElement);
  if (!cat && observer) { observer.disconnect(); observer = null; }   // English: all put back
}
