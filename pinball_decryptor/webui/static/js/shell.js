// The frame around every tab: top bar, rail, status bar, log drawer,
// the manufacturer picker, banners, toasts and the dialog host.

import { html, useEffect, useLayoutEffect, useRef, useState, Icon, Button, Chip, openMenu, cx, fmtClock, tip, Empty, Spinner }
  from "./core/ui.js";
import { Component } from "./vendor/preact-htm.js";
import { useNs, useLog, useConnected, useEvent, state } from "./core/store.js";
import { call, onCallError } from "./core/rpc.js";
import { DialogHost, openDialog } from "./core/dialogs.js";
// The app-wide windows (Tips, Preview features, disk space, the Project
// menu's windows) register themselves on import; ShellxOverlays draws the
// progress windows the shellx service drives (docs/plans/web_ui_tabs/shellx.md).
import { ShellxOverlays } from "./shellx_dialogs.js";
// The Build / flash dialog floats over any tab (Write, and Multi-boot's
// Build / flash card...), so opening it no longer switches tabs.
import { WriteOverlays } from "./tabs/write_dialogs.js";
// The Fonts and Scenes tool windows float over any tab: Text, Images (Fonts...,
// Scenes...) and Video (Show scene contents...) all open them.
import { ScenesWindow } from "./tabs/text_scenes.js";
import { FontsWindow } from "./tabs/text_fonts.js";

// ------------------------------------------------------------------ zoom
let currentZoom = 1;
// The layout classes follow the EFFECTIVE width (see app.css "responsive").
export function applyBreakpoints() {
  const w = window.innerWidth / currentZoom, h = window.innerHeight / currentZoom;
  const cl = document.documentElement.classList;
  cl.toggle("w-rail", w < 1180);
  cl.toggle("w-stack", w < 1020);
  cl.toggle("h-short", h < 700);
  // the tab stylesheets' breakpoints (css/tabs/*.css "html.bp-N ...")
  for (const n of [640, 700, 720, 760, 860, 900, 1020, 1100, 1180, 1280]) cl.toggle("bp-" + n, w < n);
  for (const n of [700, 760]) cl.toggle("bph-" + n, h < n);
}
window.addEventListener("resize", applyBreakpoints);
export function applyZoom(z) {
  const zoom = Math.max(0.6, Math.min(2, Number(z) || 1));
  currentZoom = zoom;
  document.documentElement.style.zoom = String(zoom);
  applyBreakpoints();
}
const ZOOMS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
export function stepZoom(dir) {
  const cur = Number((state.shell && state.shell.zoom) || 1);
  let next = cur;
  if (dir === 0) next = 1;
  else if (dir > 0) next = ZOOMS.find((z) => z > cur + 0.001) || cur;
  else next = [...ZOOMS].reverse().find((z) => z < cur - 0.001) || cur;
  call("shell.zoom", next);
}

// ---------------------------------------------------------------- theme
function applyTheme(theme) {
  let t = theme || "dark";
  if (t === "system") t = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.classList.toggle("light", t === "light");
}

// ----------------------------------------------------------------- tabs
const loaded = new Map();          // ns -> component | "error"
const cssDone = new Set();
function loadCss(href) {
  if (cssDone.has(href)) return;
  cssDone.add(href);
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = href;
  document.head.appendChild(l);
}
loadCss("/static/css/tabs/shellx.css");
function TabHost({ ns }) {
  const [, force] = useState(0);
  const tabState = useNs(ns);
  useEffect(() => {
    if (!ns || loaded.has(ns)) return;
    import("./tabs/" + ns + ".js").then((mod) => {
      if (mod.css) loadCss("/static/css/tabs/" + ns + ".css");
      loaded.set(ns, mod.default);
      force((n) => n + 1);
    }).catch((err) => {
      console.error(err);
      loaded.set(ns, "error");
      force((n) => n + 1);
    });
  }, [ns]);
  if (!ns) return html`<div class="page"><${Empty} title="Nothing to show" icon="info">This manufacturer has no tabs.<//></div>`;
  const C = loaded.get(ns);
  if (tabState.placeholder) {
    return html`<div class="page"><${Empty} title=${"This tab is not ready"} icon="warn">${tabState.placeholder}<//></div>`;
  }
  if (!C) return html`<div class="page"><div class="row"><${Spinner} /><span class="muted">Loading…</span></div></div>`;
  if (C === "error") return html`<div class="page"><${Empty} title="This tab could not load" icon="error">The details are in the session log.<//></div>`;
  return html`<${C} key=${ns} />`;
}

// ---------------------------------------------------------------- menus
// Core openMenu places a submenu at its parent row's right edge, clamped to
// innerWidth - 240, never flipped, and moves no focus into it; and it mixes
// the zoomed rects (getBoundingClientRect, innerWidth: window px) with
// unzoomed style px, so at 125 % the gear menu opens off the window (core
// requests 7, 8 and 10, docs/plans/web_ui_tabs/shellx.md).  Until core does
// it, the menus this file opens place themselves in window px and write
// style px (÷ the zoom, measured as rect width / offsetWidth), fit their
// submenus (right of the parent menu when there is room, else left of it,
// the top kept in the window) and walk like Tk's menus from the keyboard
// (Up / Down within a menu, Right / Enter into a cascade, Left back).
const zoomOf = (el, r) => (el.offsetWidth ? r.width / el.offsetWidth : 1) || 1;
function placeMenu(m, ar, align) {
  const r = m.getBoundingClientRect();
  if (!r.width) return;
  const k = zoomOf(m, r), W = window.innerWidth, H = window.innerHeight;
  let x = align === "right" ? ar.right - r.width : ar.left;
  let y = ar.bottom + 4 * k;
  x = Math.max(8, Math.min(W - r.width - 8, x));
  if (y + r.height > H - 8) y = Math.max(8, ar.top - r.height - 4 * k);
  m.style.left = (x / k) + "px";
  m.style.top = (y / k) + "px";
}
function fitSubmenu(sub, row) {
  const outer = sub.parentElement && sub.parentElement.closest(".menu");
  if (!outer) return;
  const s = sub.getBoundingClientRect(), o = outer.getBoundingClientRect();
  if (!s.width) return;
  const k = zoomOf(sub, s), W = window.innerWidth, H = window.innerHeight;
  let left = s.left;
  // level with its row (the menu's 6 px padding above the first entry)
  let top = row && outer.contains(row) ? row.getBoundingClientRect().top - 6 * k : s.top;
  if ((s.left < o.right - 1 && s.right > o.left + 1) || s.right > W - 8 || s.left < 8) {
    left = o.right + 2;
    if (left + s.width > W - 8) left = o.left - s.width - 2;
    if (left < 8) left = Math.max(8, W - 8 - s.width);
  }
  if (top + s.height > H - 8) top = Math.max(8, H - 8 - s.height);
  if (top < 8) top = 8;
  if (Math.abs(left - s.left) > 0.5) sub.style.left = (left / k) + "px";
  if (Math.abs(top - s.top) > 0.5) sub.style.top = (top / k) + "px";
}

function menuKeys(e, host) {
  const btn = e.target && e.target.closest ? e.target.closest("button.mi") : null;
  if (!btn || !host.contains(btn)) return;
  const level = btn.parentElement;
  const rows = [...level.children].filter((c) => c.matches("button.mi:not(:disabled)"));
  const i = rows.indexOf(btn);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!rows.length) return;
    const n = rows.length;
    rows[(i < 0 ? 0 : i + (e.key === "ArrowDown" ? 1 : n - 1)) % n].focus();
  } else if (btn.getAttribute("aria-haspopup") && (e.key === "ArrowRight" || e.key === "Enter")) {
    // core opens the cascade (ArrowRight / the click); focus goes into it
    host._sxParent = btn;
    setTimeout(() => {
      const sub = host.querySelector(".menu .menu");
      const first = sub && sub.querySelector("button.mi:not(:disabled)");
      if (first) first.focus();
    }, 0);
  } else if (e.key === "ArrowLeft" && level.parentElement && level.parentElement.closest(".menu")) {
    e.preventDefault();
    if (host._sxParent && host.contains(host._sxParent)) host._sxParent.focus();
  }
}

export function openShellMenu(anchor, items, opts = {}) {
  const ar = anchor.getBoundingClientRect ? anchor.getBoundingClientRect()
    : { left: anchor.x, right: anchor.x, top: anchor.y, bottom: anchor.y };
  openMenu(anchor, items, opts);
  const menus = document.querySelectorAll("body > div > .menu");
  const m = menus.length ? menus[menus.length - 1] : null;
  const host = m ? m.parentElement : null;
  if (!host) return;
  host.classList.add("sx-menuhost");
  placeMenu(m, ar, opts.align || "left");
  // the cascade row a submenu belongs to: the one last pointed at or keyed
  host.addEventListener("mouseover", (e) => {
    const row = e.target && e.target.closest ? e.target.closest("button.mi[aria-haspopup]") : null;
    if (row && row.parentElement === m) host._sxParent = row;
  });
  const fit = () => host.querySelectorAll(".menu .menu").forEach((sub) => fitSubmenu(sub, host._sxParent));
  if (typeof MutationObserver !== "undefined") {
    new MutationObserver(fit).observe(host, { childList: true, subtree: true, attributes: true, attributeFilter: ["style"] });
  }
  host.addEventListener("keydown", (e) => menuKeys(e, host));
  fit();
}

// A menu level with a check column: every plain row gets the (empty) column
// too, so the labels line up as in Tk's menus.
function alignChecks(items) {
  if (!items.some((it) => it && it.checked != null)) return items;
  return items.map((it) => (it && !it.sep && !it.header && !it.submenu && !it.icon && it.checked == null
    ? { ...it, checked: false } : it));
}

// --------------------------------------------------------------- top bar
// The Project menu (Tk _build_project_menu): every entry is off while a run
// is in flight; Save / Save as / Properties / Change history / Relink need
// a project folder and a manufacturer.  "Recent projects" is a cascade of
// the last 8 ("name    (path)", one disabled "(nothing yet)" when empty).
// The gaps are no-break spaces, which HTML does not collapse.
const GAP2 = "\u00a0\u00a0", GAP4 = GAP2 + GAP2;
export function projectMenuItems(shell) {
  const running = !!shell.running;
  const recents = (shell.recent_projects || []).filter((r) => r && r.folder);
  const proj = shell.project || {};
  const have = !!(proj.folder && shell.mfr);
  const base = (f) => (f || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || f;
  return [
    { label: "New project…", disabled: running, onClick: () => call("ui.call_back", "on_new_project") },
    { label: "Open project…", disabled: running, onClick: () => call("ui.call_back", "on_load_project") },
    { sep: true },
    { label: "Save project", disabled: running || !have, onClick: () => call("ui.call_back", "on_save_project") },
    { label: "Save project as…" + GAP2 + "(fork)", disabled: running || !have, onClick: () => call("ui.call_back", "on_save_project_as") },
    { sep: true },
    { label: "Recent projects", submenu: recents.length ? recents.slice(0, 8).map((r) => ({
      label: base(r.folder) + GAP4 + "(" + r.folder + ")", disabled: running,
      title: r.caption || undefined, onClick: () => call("ui.call_back", "on_open_recent_project", r.folder) }))
      : [{ label: "(nothing yet)", disabled: true }] },
    { label: "Projects…", disabled: running, onClick: () => call("ui.call_back", "on_open_project_manager") },
    { sep: true },
    { label: "Properties…", disabled: running || !have, onClick: () => call("ui.call_back", "on_project_properties") },
    { label: "Change history…", disabled: running || !have, onClick: () => call("shellx.change_history") },
    { label: "Relink moved files…", disabled: running || !have, onClick: () => call("ui.call_back", "on_relink_project") },
  ];
}
function projectMenu(anchor, shell) {
  openShellMenu(anchor, projectMenuItems(shell));
}

function eraMenu(anchor, shell) {
  const mfr = shell.mfr || {};
  const items = [];
  if (mfr.eras && mfr.eras.length > 1) {
    items.push({ header: mfr.display });
    for (const e of mfr.eras) {
      items.push({ label: e.label + (e.flag ? "  " + e.flag : ""), checked: e.key === mfr.era,
        disabled: shell.running, onClick: () => call("ui.set_era", e.key) });
    }
    items.push({ sep: true });
  }
  // every manufacturer, one click away (this replaced the header's Home
  // button: the picker page is only the FIRST launch's landing page now)
  const locked = shell.running || shell.back_enabled === false;
  items.push({ header: "Manufacturer" });
  for (const m of shell.mfrs || []) {
    items.push({ label: m.display + (m.badge ? "  " + m.badge : ""), checked: m.key === mfr.key,
      disabled: locked, onClick: () => { if (m.key !== mfr.key) call("ui.pick_manufacturer", m.key); } });
  }
  items.push({ sep: true });
  items.push({ label: "Browse manufacturers and their games…", icon: "home", disabled: locked,
    onClick: () => call("ui.back_to_picker") });
  openShellMenu(anchor, items);
}

// The gear menu's prerequisite line (Tk _prereq_menu_summary): the live
// status, counted from what the probes reported.
export function prereqSummary(rows) {
  if (!rows.length) return ["Prerequisites: none for this view", false];
  const missing = rows.filter((r) => r.state === "missing").length;
  if (rows.some((r) => r.state === "checking")) return ["Prerequisites: checking…", missing > 0];
  if (missing) return ["Prerequisites: " + missing + " missing ✗", true];
  return ["Prerequisites: all " + rows.length + " ready ✓", false];
}

// The gear menu (Tk _build_settings_menu).  The shellx service publishes
// the items (shell.settings_items, Tk's cascades as `submenu`) and answers
// them (ui.settings_action); Appearance and Zoom are the page's own, where
// Tk had its theme toggle.  The prerequisites cascade's LABEL is the live
// summary, as in Tk.
// Tk labels space things out ("Manage disk space…   ⚠ 1.2 GB"); HTML would
// collapse the run to one space.
const keepGaps = (t) => String(t == null ? "" : t).replace(/ {2,}/g, (m) => "\u00a0".repeat(m.length));
const MOD = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";
export function settingsMenuItems(shell) {
  const zoom = Number(shell.zoom || 1);
  const theme = shell.theme || "dark";
  const all = shell.settings_items || [];
  const rows = shell.prereqs || [];
  const [summary, anyMissing] = prereqSummary(rows);
  let i = 0;
  const lead = [];
  while (i < all.length && all[i].dot) lead.push(all[i++]);
  if (lead.length && all[i] && all[i].sep) i++;
  const item = (it) => it.sep ? { sep: true }
    : it.header ? { header: it.header }
    : it.submenu ? { label: it.prereq_summary ? summary : it.label, disabled: !!it.disabled,
                     submenu: alignChecks(it.submenu.map(item)) }
    : ({ label: keepGaps((it.dot ? "● " : "") + (anyMissing && it.label_missing ? it.label_missing : it.label)),
         checked: it.checked, title: it.title,
         disabled: !!(it.disabled || (it.needs_idle && shell.running) || (it.needs_prereqs && !rows.length)),
         onClick: () => call("ui.settings_action", it.id, ...(it.args || [])) });
  return [
    ...lead.map(item),
    ...(lead.length ? [{ sep: true }] : []),
    { label: "Appearance", submenu: [
      { label: "Dark", checked: theme === "dark", onClick: () => call("ui.set_theme", "dark") },
      { label: "Light", checked: theme === "light", onClick: () => call("ui.set_theme", "light") },
      { label: "Match the system", checked: theme === "system", onClick: () => call("ui.set_theme", "system") },
    ] },
    { label: "Zoom (" + Math.round(zoom * 100) + "%)", submenu: [
      { label: "Zoom in", kbd: MOD + " +", onClick: () => stepZoom(1) },
      { label: "Zoom out", kbd: MOD + " −", onClick: () => stepZoom(-1) },
      { label: "Actual size", kbd: MOD + " 0", onClick: () => stepZoom(0) },
    ] },
    { sep: true },
    ...all.slice(i).map(item),
  ];
}
function settingsMenu(anchor, shell) {
  openShellMenu(anchor, settingsMenuItems(shell), { align: "right" });
}

// A top-bar icon button with an accessible name (the label is also its
// tooltip).
function IconBtn({ icon, label, onClick, disabled, cls = "" }) {
  return html`<button type="button" class=${cx("btn ghost sm icon", cls)} disabled=${!!disabled} onClick=${onClick}
    ...${tip(label)} aria-label=${label}><${Icon} name=${icon} /></button>`;
}

function TopBar({ shell }) {
  const mfr = shell.mfr;
  const proj = shell.project || {};
  const eraLabel = mfr && mfr.eras && mfr.eras.length > 1 ? (mfr.eras.find((e) => e.key === mfr.era) || mfr.eras[0]).label : null;
  const upd = shell.update;
  const sx = useNs("shellx");
  const working = shell.view === "mfr";
  const dots = shell.gear_dots || {};
  const connectedNow = useConnected();
  const [connected, setShown] = useState(true);
  useEffect(() => {
    if (connectedNow) { setShown(true); return; }
    const id = setTimeout(() => setShown(false), 2500);
    return () => clearTimeout(id);
  }, [connectedNow]);
  // broad to specific, left to right: manufacturer (and era), then project
  const pyChanged = shell.dev_py_changed || [];
  return html`<header class="topbar">
    ${mfr && working ? html`<button type="button" class="btn sm" style="gap:8px" onClick=${(e) => eraMenu(e.currentTarget, shell)}
        ...${tip("Switch manufacturer" + (eraLabel ? " or era" : ""))}
        aria-label=${"Manufacturer " + mfr.display + (eraLabel ? ", era " + eraLabel : "")}>
        <span class="ellip">${mfr.display}</span>${eraLabel ? html`<span class="chip acc sm">${eraLabel}</span>` : null}<span class="muted">▾</span>
      </button>
      <span class="crumb" aria-hidden="true">›</span>` : null}
    <button type="button" class="btn sm" style="gap:10px;max-width:420px" disabled=${!!shell.running && false}
      onClick=${(e) => projectMenu(e.currentTarget, shell)} ...${tip(proj.folder || "Project")} aria-label="Project menu">
      <${Icon} name="folder" />
      <span class="mono ellip" style="color:var(--accent)">${proj.name || "No project"}</span>
      ${proj.caption ? html`<span class="dim ellip hide-narrow">${proj.caption}</span>` : null}
      <span class="muted">▾</span>
    </button>
    <span class="grow"></span>
    ${pyChanged.length ? html`<${Chip} kind="warn" dot onClick=${() => call("shell.dev_restart")}
        title=${"Python files changed since this app started:\n" + pyChanged.slice(0, 12).join("\n") + (pyChanged.length > 12 ? "\n…" : "") + "\n\nClick to restart the app with them (development checkout only)."}>Python changed · Restart<//>` : null}
    ${!connected ? html`<${Chip} kind="err" dot>Reconnecting…<//>` : null}
    ${upd && upd.available ? html`<${Chip} kind="info" dot onClick=${() => call("ui.settings_action", "install_update")}
        title=${"Pinball Asset Decryptor v" + upd.version + " is available — you're on v" + (shell.version || "") + "."}>${upd.label || ("v" + upd.version + " available")}<//>`
      : html`<span class="hide-narrow"><${Chip} kind="ok" dot title=${sx.update_state === "latest" ? "You're on the latest version." : "This version"}>v${shell.version || ""}${sx.update_state === "latest" ? ", latest" : ""}<//></span>`}
    ${working ? html`<${IconBtn} icon="help" label="Tips for this tab" cls="sx-help" onClick=${() => openDialog("tips")} />` : null}
    <span class="sx-gear">
      <${IconBtn} icon="gear" label="Settings" onClick=${(e) => settingsMenu(e.currentTarget, shell)} />
      ${dots.update ? html`<span class="sx-dot upd" title="An update is available"></span>` : null}
      ${dots.warn ? html`<span class="sx-dot warn" title="Leftover staging found: Settings, Manage disk space"></span>` : null}
    </span>
  </header>`;
}

// ------------------------------------------------------------------ rail
const GROUP_ORDER = ["Card", "Replace", "Make", "Build", "Inspect", "Play"];
function Rail({ shell }) {
  const tabs = (shell.tabs || []).filter((t) => t.visible);
  const groups = [];
  for (const g of GROUP_ORDER) {
    const items = tabs.filter((t) => t.group === g);
    if (items.length) groups.push([g, items]);
  }
  return html`<nav class="rail" aria-label="Tabs">
    ${groups.map(([g, items], gi) => html`
      <div class="eyebrow group">${g}</div>${gi > 0 ? html`<hr class="gsep" />` : null}
      ${items.map((t) => html`<button type="button" class=${cx("item", shell.tab === t.ns && "on")}
          aria-current=${shell.tab === t.ns ? "page" : undefined}
          onClick=${() => call("ui.select_tab", t.ns)} ...${tip(t.label)}>
          <${Icon} name=${t.icon} /><span class="lbl">${t.label}</span>
          ${t.badge != null && t.badge !== "" ? html`<span class="n">${t.badge}</span>` : null}
        </button>`)}`)}
  </nav>`;
}

// ------------------------------------------------------------ status bar
function Elapsed({ started }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!started) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [started]);
  if (!started) return null;
  return html`<span class="mono muted">${fmtClock(Date.now() / 1000 - started)}</span>`;
}

function StatusBar({ shell }) {
  const f = shell.footer || {};
  const running = shell.running;
  const phases = f.phases || [];
  const idx = f.index ?? -1;
  // Tk had ONE Cancel per run: the running tab's own button.  The status bar
  // offers one only on the other tabs.
  const ownCancel = (shell.run_mode === "extract" && shell.tab === "extract")
    || (shell.run_mode === "write" && shell.tab === "write");
  // an emulator on its own tab owns the footer: its chip says its state
  const emuLive = !running && f.mode === "emulate" && idx >= 0;
  const chip = shell.cancelling ? html`<${Chip} kind="warn" dot>Cancelling<//>`
    : emuLive ? html`<${Chip} kind=${idx >= phases.length - 1 ? "ok" : "acc"} dot>${idx >= phases.length - 1 ? (f.status || "Running") : "Starting"}<//>`
    : running ? html`<${Chip} kind="acc" dot>${f.mode === "write" ? "Building" : f.mode === "extract" ? "Working" : "Running"}<//>`
    : html`<${Chip} kind="ok" dot>Ready<//>`;
  return html`<div class="statusbar" role="status">
    ${chip}
    ${phases.length ? html`<div class="phases">${phases.map((p, i) => html`<span class=${cx("phase", i < idx && "done", i === idx && "now", idx >= phases.length && "done")}>${p}</span>`)}</div>` : null}
    <span class="status" title=${f.status}>${f.status}</span>
    ${running && !ownCancel ? html`<${Button} kind="danger" size="sm" disabled=${shell.cancelling}
      onClick=${() => call("ui.cancel")}>${shell.cancelling ? "Cancelling…" : "Cancel"}<//>` : null}
  </div>`;
}

// ------------------------------------------------------- progress strip
// Tk's footer: a full-width bar (determinate, or a marquee while the total
// is unknown) with the elapsed clock beside it.  Here it heads the log, so
// it stays on screen with the log hidden, and adds the percent and an
// estimate of the time left in the CURRENT step (each step runs its bar
// from 0 again), taken from that step's pace so far.
function useStepEta(f, running) {
  const ref = useRef({ key: null, t0: 0, p0: 0, last: -1 });
  const [, tick] = useState(0);
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [running]);
  const pct = f.pct;
  if (!running || f.busy || pct == null) { ref.current = { key: null, t0: 0, p0: 0, last: -1 }; return null; }
  const key = (f.mode || "") + ":" + (f.index ?? -1);
  const r = ref.current;
  const now = Date.now() / 1000;
  if (r.key !== key || pct < r.last) { ref.current = { key, t0: now, p0: pct, last: pct }; return null; }
  r.last = pct;
  const done = pct - r.p0, spent = now - r.t0;
  if (pct >= 100 || done < 2 || spent < 4) return null;
  const left = spent * (100 - pct) / done;
  return left > 0 && left < 36000 ? left : null;
}

function ProgressStrip({ shell }) {
  const f = shell.footer || {};
  const running = !!shell.running;
  const eta = useStepEta(f, running);
  const pct = f.pct == null ? null : Math.max(0, Math.min(100, f.pct));
  const busy = !!f.busy;
  return html`<div class="lprog" role="progressbar" aria-valuemin="0" aria-valuemax="100"
      aria-valuenow=${busy || pct == null ? undefined : pct} aria-label="Progress">
    <div class=${cx("pbar", busy && "busy", running && !busy && "live")}>
      <i style=${busy ? "" : `width:${pct || 0}%`}></i>
    </div>
    <span class="pct mono">${busy ? (running ? "working…" : "") : pct != null && (running || pct > 0) ? pct + "%" : ""}</span>
    ${eta != null ? html`<span class="eta mono" title="About this long left in this step, from its pace so far">ETA ${fmtClock(eta)}</span>` : null}
    ${f.started ? html`<span class="elapsed" title="Time since this run started"><${Elapsed} started=${f.started} /> elapsed</span>` : null}
  </div>`;
}

// The border above the log: drag it to give the log more or less room,
// drag it down to the bottom to hide the log (up again to show it), or
// double-click it.  Arrow keys resize it and Enter toggles it when focused.
const LOG_MIN_H = 60, LOG_HIDE_BELOW = 44;
function logMaxH() { return Math.max(LOG_MIN_H + 40, window.innerHeight / currentZoom - 200); }
function LogSplit({ open, setOpen, height, setHeight }) {
  const toggle = () => setOpen(!open);
  const startDrag = (e) => {
    if (e.button != null && e.button !== 0) return;
    e.preventDefault();
    const y0 = e.clientY;
    const h0 = open ? height : 0;
    const keep = open && height >= 100 ? height : Math.max(height, 150);
    let hidden = !open;
    const move = (ev) => {
      const h = h0 + (y0 - ev.clientY) / currentZoom;
      if (h < LOG_HIDE_BELOW) { if (!hidden) { hidden = true; setOpen(false); } return; }
      if (hidden) { hidden = false; setOpen(true); }
      setHeight(Math.max(LOG_MIN_H, Math.min(logMaxH(), h)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      document.documentElement.classList.remove("dragging-log");
      if (hidden) setHeight(keep);           // showing it again brings back its size
    };
    document.documentElement.classList.add("dragging-log");
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const onKey = (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const step = e.key === "ArrowUp" ? 24 : -24;
      if (!open) { if (step > 0) setOpen(true); return; }
      const h = height + step;
      if (h < LOG_HIDE_BELOW) setOpen(false);
      else setHeight(Math.max(LOG_MIN_H, Math.min(logMaxH(), h)));
    }
  };
  return html`<div class="logsplit" role="separator" aria-orientation="horizontal" aria-label="Log size"
      aria-valuenow=${open ? Math.round(height) : 0} tabindex="0"
      title="Drag to give the log more or less room; drag it down to hide it. Double-click to hide or show."
      onPointerDown=${startDrag} onDblClick=${toggle} onKeyDown=${onKey}><span class="knob"></span></div>`;
}

// Under the status row: the progress strip and the log's Hide / Show.
function LogHead({ shell, open, setOpen }) {
  const toggle = () => setOpen(!open);
  return html`<div class=${cx("loghead", !open && "closed")}>
    <div class="logbar">
      <${ProgressStrip} shell=${shell} />
      <${Button} kind="ghost" size="sm" cls="logtoggle" onClick=${toggle}
        title=${open ? "Hide the log (the progress stays here)" : "Show the log"}>${open ? "Hide log ▾" : "Show log ▴"}<//>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- log
const logLine = (l) => "[" + l.ts + "] " + l.text;
function selectionIn(el) {
  const sel = window.getSelection && window.getSelection();
  if (!sel || sel.isCollapsed || !el) return "";
  const node = sel.anchorNode;
  return node && el.contains(node) ? sel.toString() : "";
}
function copyText(text) {
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(() => {});
  else {
    const t = document.createElement("textarea");
    t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    t.remove();
  }
}

// The pane's rules are Tk's (main_window.py LOG_PANE_MAX_LINES / _TRIM_TO
// and the _log_follow notes): it keeps up to 4 000 lines and cuts back to
// 2 500 only when that is passed, so a trim is occasional; it follows the
// end until the USER moves the view (the wheel, a key, a drag on the
// scrollbar), and neither a new line nor a trim moves what a parked reader
// is looking at (the row at the top of the view is pinned across renders;
// the engines' own scroll anchoring is off so WebKit and Chromium agree).
const LOG_PANE_MAX = 4000, LOG_PANE_TRIM_TO = 2500, LOG_CHUNK = 200;

function openLogLink(url) { call("shellx.open_link", url); }

// A run of rows (ids in one LOG_CHUNK bucket): re-rendered only when one of
// its lines changed, so a new line costs one small diff, not 4 000.
class LogRows extends Component {
  shouldComponentUpdate(next) {
    const a = this.props.lines, b = next.lines;
    if (a.length !== b.length) return true;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return true;
    return false;
  }
  render({ lines }) {
    return lines.map((l) => html`<div key=${l.id} data-id=${l.id} class=${cx("line", l.level, l.history && "history")}>
      <span class="t">${l.ts}</span>${l.url ? html`<a role="link" tabindex="0" title=${l.url} onClick=${() => openLogLink(l.url)}
        onKeyDown=${(e) => { if (e.key === "Enter") openLogLink(l.url); }}>${l.text}</a>` : l.text}</div>`);
  }
}

function firstAtLeast(lines, id) {
  let lo = 0, hi = lines.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (lines[mid].id < id) lo = mid + 1; else hi = mid; }
  return lo;
}

function LogDrawer({ open, height, setHeight }) {
  const allLines = useLog();
  const sx = useNs("shellx");
  const shellNs = useNs("shell");
  // Clear (the right-click menu) empties the pane, as Tk's did; the
  // session log file keeps everything.
  const [cleared, setCleared] = useState({ at: 0, seed: false });
  const mfrKey = (shellNs.mfr && shellNs.mfr.key) || "";
  useEffect(() => { setCleared({ at: 0, seed: false }); }, [mfrKey]);
  const lines = cleared.at ? allLines.filter((l) => l.id > cleared.at) : allLines;
  const seed = !cleared.seed && sx.log_seed ? sx.log_seed : null;
  const ref = useRef(null);
  const follow = useRef(true);                   // a decision, not a position
  const anchor = useRef(null);                   // {id, off}: the parked reader's top row
  const user = useRef({ at: 0, drag: false });   // when the USER last moved the view
  const trim = useRef({ mfr: mfrKey, from: 0 });  // the first line id the pane shows
  const [showJump, setShowJump] = useState(false);

  if (trim.current.mfr !== mfrKey) trim.current = { mfr: mfrKey, from: 0 };
  let start = trim.current.from ? firstAtLeast(lines, trim.current.from) : 0;
  if (lines.length - start > LOG_PANE_MAX) {
    start = lines.length - LOG_PANE_TRIM_TO;
    trim.current.from = lines[start].id;
  }
  const shown = start > 0 ? lines.slice(start) : lines;
  const chunks = [];
  for (const l of shown) {
    const b = Math.floor(l.id / LOG_CHUNK);
    const last = chunks[chunks.length - 1];
    if (last && last.b === b) last.lines.push(l); else chunks.push({ b, lines: [l] });
  }

  const recordAnchor = () => {
    const el = ref.current;
    if (!el) return;
    const rows = el.children, top = el.scrollTop;
    let lo = 0, hi = rows.length - 1, hit = rows.length;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1, r = rows[mid];
      if (r.offsetTop + r.offsetHeight > top) { hit = mid; hi = mid - 1; } else lo = mid + 1;
    }
    for (let i = hit; i < rows.length; i++) {
      const id = rows[i].getAttribute("data-id");
      if (id) { anchor.current = { id, off: rows[i].offsetTop - top }; return; }
    }
    anchor.current = null;
  };
  // after every render: follow the end, or keep the parked reader's row put
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (follow.current) { el.scrollTop = el.scrollHeight; return; }
    const a = anchor.current;
    const row = a && el.querySelector('[data-id="' + a.id + '"]');
    if (row) {
      const want = row.offsetTop - a.off;
      if (Math.abs(el.scrollTop - want) > 1) el.scrollTop = want;
    }
  });
  // a resize (the grip, the window) keeps a following pane at the end
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => { if (follow.current) el.scrollTop = el.scrollHeight; });
    ro.observe(el);
    return () => ro.disconnect();
  }, [open]);
  useEffect(() => {
    const up = () => { user.current.drag = false; };
    window.addEventListener("mouseup", up);
    window.addEventListener("touchend", up);
    return () => { window.removeEventListener("mouseup", up); window.removeEventListener("touchend", up); };
  }, []);
  const touched = () => { user.current.at = performance.now(); };
  // a move UP is a decision to leave the end, before its scroll event
  // lands: a line rendered in between must not pull the view back down
  const wheel = (e) => { touched(); if (e.deltaY < 0) follow.current = false; };
  const key = (e) => {
    touched();
    if (["PageUp", "ArrowUp", "Home"].includes(e.key)) follow.current = false;
  };
  const onScroll = () => {
    recordAnchor();
    const u = user.current;
    if (!u.drag && performance.now() - u.at > 600) return;   // not the user: a trim, a line, a resize
    const el = ref.current;
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 8;
    follow.current = atEnd;
    setShowJump(!atEnd);
  };
  const jump = () => {
    follow.current = true;
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
    setShowJump(false);
  };
  if (!open) return null;
  // The right-click menu (Tk _log_context_menu): Copy (the selection) or
  // Copy all, Copy current session log, Save As…, the two on-disk logs,
  // Clear.
  const everything = () => [...(seed ? [...seed.lines, seed.cut] : []), ...lines.map(logLine)].join("\n");
  const menu = (e) => {
    e.preventDefault();
    const sel = selectionIn(ref.current);
    openShellMenu({ getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY }) }, [
      { label: sel ? "Copy" : "Copy all", onClick: () => copyText(sel || everything()) },
      { label: "Copy current session log", onClick: () => copyText(lines.map(logLine).join("\n")) },
      { label: "Save As…", onClick: () => call("shellx.save_log", everything()) },
      { label: "View log history…", onClick: () => call("ui.settings_action", "log_history") },
      { label: "View this project's log…", onClick: () => call("ui.settings_action", "project_log") },
      { sep: true },
      { label: "Clear", onClick: () => {
        follow.current = true; setShowJump(false);
        setCleared({ at: allLines.length ? allLines[allLines.length - 1].id : 0, seed: true });
      } },
    ]);
  };
  return html`<div class="logdrawer" style=${`height:${Math.min(height, logMaxH())}px`}>
    <div class="lines" ref=${ref} tabindex="0" aria-label="Log" onScroll=${onScroll} onContextMenu=${menu}
      onWheel=${wheel} onKeyDown=${key} onTouchMove=${touched}
      onMouseDown=${() => { user.current.drag = true; touched(); }} onTouchStart=${() => { user.current.drag = true; }}>
      ${seed ? html`<div class="sx-seed">${seed.lines.map((t, i) => html`<div key=${"h" + i} class="line history">${t}</div>`)}</div>
        <div class="line sx-cut">${seed.cut}</div>` : null}
      ${chunks.map((c) => html`<${LogRows} key=${"c" + c.b} lines=${c.lines} />`)}
    </div>
    ${showJump ? html`<${Button} size="sm" cls="jump" onClick=${jump}>↓ Jump to latest<//>` : null}
  </div>`;
}

// ---------------------------------------------------------- prereqs panel
// The Prerequisites strip (Tk reset_prereqs / set_prereq_result): hidden
// until a probe CONFIRMS something is missing, then every prerequisite as a
// [?] / [✓] / [✗] chip with its status, reason and fix on hover; Re-check and
// Install Missing everywhere but macOS.
function prereqTip(r, hints) {
  if (r.state === "checking") return r.name + "\n\nChecking...\n\nWhy: " + (r.reason || "");
  const ok = r.state === "ok";
  let t = r.name + "\n\nStatus: " + (ok ? "OK" : "MISSING") + "\n" + (r.message || "") + "\n\nWhy: " + (r.reason || "");
  const hint = r.hint || (hints && hints[r.name]) || "";
  if (!ok && hint) t += "\n\nFix: " + hint;
  return t;
}
function Prereqs({ shell }) {
  const sx = useNs("shellx");
  const rows = shell.prereqs || [];
  if (!rows.some((r) => r.state === "missing")) return null;
  return html`<div class="banner warn sx-prereqs" role="alert" aria-label="Prerequisites">
    <${Icon} name="warn" />
    <b class="nw">Prerequisites</b>
    <div class="sx-prereq-chips">
      ${rows.map((r) => html`<${Chip} sm kind=${r.state === "ok" ? "ok" : r.state === "missing" ? "err" : ""} title=${prereqTip(r, sx.prereq_hints)}>
        <span class="mono">[${r.state === "ok" ? "✓" : r.state === "missing" ? "✗" : "?"}]</span> ${r.name}<//>`)}
    </div>
    ${shell.prereq_buttons !== false ? html`<${Button} size="sm" onClick=${() => call("ui.call_back", "on_recheck_prereqs")}>Re-check<//>
      <${Button} size="sm" kind="primary" onClick=${() => call("shellx.install_prereqs")}>Install Missing<//>` : null}
  </div>`;
}

function Banners({ shell }) {
  return html`${(shell.banners || []).map((b) => html`<div class=${cx("banner", b.kind || "info", "sx-banner-" + b.id)} key=${b.id} role=${b.kind === "warn" ? "alert" : "status"}>
    ${b.icon === "bolt" ? html`<span class="sx-bolt" aria-hidden="true">⚡</span>` : html`<${Icon} name=${b.kind === "warn" ? "warn" : "info"} />`}<div class="body-text">${b.text}</div>
    ${(b.actions || []).map((a) => html`<${Button} size="sm" kind=${a.primary ? "primary" : ""} onClick=${() => call("ui.banner_action", b.id, a.id)}>${a.label}<//>`)}
    ${b.dismiss !== false ? html`<${Button} size="sm" kind="ghost" icon="x" title="Dismiss" onClick=${() => call("ui.banner_action", b.id, "dismiss")} />` : null}
  </div>`)}`;
}

function Toasts({ shell }) {
  const toasts = shell.toasts || [];
  useEffect(() => {
    const timers = toasts.filter((t) => t.ms).map((t) => setTimeout(() => call("ui.dismiss_toast", t.id), t.ms));
    return () => timers.forEach(clearTimeout);
  }, [toasts.map((t) => t.id).join(",")]);
  const [local, setLocal] = useState([]);
  useEffect(() => {
    onCallError((msg) => {
      const id = Math.random();
      setLocal((l) => [...l.slice(-2), { id, text: msg }]);
      setTimeout(() => setLocal((l) => l.filter((x) => x.id !== id)), 8000);
    });
  }, []);
  return html`<div class="toasts" aria-live="polite">
    ${toasts.map((t) => html`<div class="toast" key=${t.id}><${Icon} name=${t.level === "error" ? "error" : t.level === "warning" ? "warn" : "info"} />
      <div class="body-text">${t.text}</div><${Button} kind="ghost" size="xs" icon="x" title="Dismiss" onClick=${() => call("ui.dismiss_toast", t.id)} /></div>`)}
    ${local.map((t) => html`<div class="toast" key=${t.id}><span class="err-ink"><${Icon} name="error" /></span><div class="body-text">${t.text}</div></div>`)}
  </div>`;
}

// --------------------------------------------------------------- picker
// The manufacturer picker (gui/picker.py): a letter logo in the maker's
// colour, the name and its EXTRACT ONLY / BETA badge, the game count and
// file types, the games (an unsupported one greyed, its reason on hover) and
// the whole list on hover of the card.
function Picker({ shell }) {
  const sx = useNs("shellx");
  const cards = sx.picker && sx.picker.length ? sx.picker : (shell.mfrs || []).map((m) => ({ ...m, stats: "", letter: "", peek: "" }));
  return html`<div class="picker"><div class="inner">
    <div class="row" style="align-items:flex-end;gap:16px">
      <div class="grow"><div class="eyebrow">Pinball Asset Decryptor</div><h1 class="h1" style="font-size:28px">Choose a manufacturer</h1>
        <p class="dim" style="margin:6px 0 0">Pick the maker of the game you are working on. You can switch at any time from the manufacturer menu in the top bar.</p></div>
      ${shell.mfr ? html`<${Button} onClick=${() => call("ui.pick_manufacturer", shell.mfr.key)}>Back to ${shell.mfr.display}<//>` : null}
    </div>
    <div class="grid">
      ${cards.map((m) => html`<button type="button" class="mfrcard" onClick=${() => call("ui.pick_manufacturer", m.key)}
          ...${tip(m.tip)} aria-label=${m.display + (m.badge ? ", " + m.badge : "")}>
        <div class="row" style="align-items:flex-start">
          ${m.letter ? html`<span class=${cx("sx-logo", m.letter.length > 2 && "long")} style=${m.color ? "background:" + m.color : ""} aria-hidden="true">${m.letter}</span>` : null}
          <div class="stack grow" style="gap:2px">
            <div class="row wrap" style="gap:4px 8px"><span class="t">${m.display}</span>
              ${m.badge ? html`<span class=${cx("sx-badge", m.beta ? "beta" : "")}>${m.badge}</span>` : null}</div>
            ${m.stats ? html`<div class="muted small">${m.stats}</div>` : null}
          </div>
        </div>
        <div class="games">${(m.games || []).slice(0, 14).map((g, i) => html`${i ? " · " : ""}<span class=${g.supported ? "" : "sx-unsup"} title=${g.supported ? undefined : (g.reason ? g.display + " — " + g.reason : g.display + " — not supported")}>${g.display}</span>`)}${(m.games || []).length > 14 ? html` · <span class="muted">+${m.games.length - 14} more</span>` : ""}</div>
      </button>`)}
    </div>
  </div></div>`;
}

// The first-launch disclaimer (gui/disclaimer.py): "I Agree" or "Quit".  It
// is a GATE, as in Tk (app.py shows it before any window exists): Shell
// draws nothing else while it is up, so no menu or window can be reached
// behind it.  Focus starts on I Agree; Enter agrees and Escape quits (Tk's
// bindings), except that Enter on a focused Quit is that button's own click.
function Disclaimer({ shell }) {
  const box = useRef(null);
  const answered = useRef(false);
  const answer = async (yes) => {
    if (answered.current) return;
    answered.current = true;
    const r = await call("shell.accept_disclaimer", !!yes);
    if (r === undefined) answered.current = false;      // the call failed: let them try again
  };
  useEffect(() => {
    const agree = box.current && box.current.querySelector(".sx-agree");
    if (agree) agree.focus();
    const onKey = (e) => {
      if (((state.modals && state.modals.open) || []).length) return;   // a question from Python is on top
      if (e.key === "Escape") { e.preventDefault(); answer(false); }
      else if (e.key === "Enter") {
        const a = document.activeElement;
        if (a && a.classList && a.classList.contains("sx-quit")) return;
        e.preventDefault();
        answer(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  const title = shell.disclaimer_title || "Important — Read Before Use";
  return html`<div class="scrim sx-gate"><div class="modal wide sx-disc" ref=${box} role="dialog" aria-modal="true" aria-label=${title}>
    <div class="hd"><span class="icon-w"><${Icon} name="warn" cls="lg" /></span><span class="h2">${title}</span></div>
    <div class="bd">${shell.disclaimer_header ? html`<div class="h2">${shell.disclaimer_header}</div>` : null}
      <div class="msg sx-disclaimer">${shell.disclaimer_text || "This tool changes game files and SD cards. Keep a backup of every original image and card. You use it at your own risk."}</div></div>
    <div class="ft"><${Button} cls="sx-quit" onClick=${() => answer(false)}>Quit<//><${Button} kind="primary" cls="sx-agree" onClick=${() => answer(true)}>I Agree<//></div>
  </div></div>`;
}

// ---------------------------------------------------------------- shell
export function Shell() {
  const shell = useNs("shell");
  const [logOpen, setLogOpen] = useState(() => { try { return localStorage.getItem("pad.log.open") !== "0"; } catch (e) { return true; } });
  const [logH, setLogH] = useState(() => { try { return Number(localStorage.getItem("pad.log.h")) || 150; } catch (e) { return 150; } });
  useEffect(() => { try { localStorage.setItem("pad.log.open", logOpen ? "1" : "0"); localStorage.setItem("pad.log.h", String(Math.round(logH))); } catch (e) {} }, [logOpen, logH]);
  useEffect(() => applyZoom(shell.zoom), [shell.zoom]);
  useEffect(() => applyTheme(shell.theme), [shell.theme]);
  useEffect(() => { document.title = shell.title || "Pinball Asset Decryptor"; }, [shell.title]);
  useEvent("clipboard", (e) => { if (navigator.clipboard) navigator.clipboard.writeText(e.text).catch(() => {}); }, []);
  useEvent("open_url", (e) => window.open(e.url, "_blank"), []);
  // hot reload (a development checkout only; webui/devreload.py): a saved
  // stylesheet is swapped in place, anything else reloads the page, whose
  // state all lives in Python and comes straight back
  useEvent("dev_reload", (e) => {
    if (e.kind !== "css") { location.reload(); return; }
    const stamp = "v=" + Date.now();
    for (const l of document.querySelectorAll('link[rel="stylesheet"]')) {
      const u = new URL(l.href, location.href);
      if (!u.pathname.startsWith("/static/")) continue;
      const fresh = l.cloneNode();
      fresh.href = u.pathname + "?" + stamp;
      fresh.onload = () => l.remove();
      l.after(fresh);
    }
  }, []);
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "=" || e.key === "+") { e.preventDefault(); stepZoom(1); }
      else if (e.key === "-" || e.key === "_") { e.preventDefault(); stepZoom(-1); }
      else if (e.key === "0") { e.preventDefault(); stepZoom(0); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  // the first-launch disclaimer is a gate: nothing else until it is answered
  // (Python's own questions can still show, above it)
  if (shell.disclaimer) {
    return html`<div class="app">
      <${Disclaimer} shell=${shell} />
      <${Toasts} shell=${shell} />
      <${DialogHost} />
    </div>`;
  }
  if (!shell.view) return html`<div class="app"><div class="page"><div class="row"><${Spinner} /><span class="muted">Starting…</span></div></div></div>`;
  return html`<div class="app">
    <${TopBar} shell=${shell} />
    <${Banners} shell=${shell} />
    ${shell.view === "picker" ? html`<${Picker} shell=${shell} />` : html`
      <${Prereqs} shell=${shell} />
      <div class="body">
        <${Rail} shell=${shell} />
        <main class="main">
          <${TabHost} ns=${shell.tab} />
          <${LogSplit} open=${logOpen} setOpen=${setLogOpen} height=${logH} setHeight=${setLogH} />
          <${StatusBar} shell=${shell} />
          <${LogHead} shell=${shell} open=${logOpen} setOpen=${setLogOpen} />
          <${LogDrawer} open=${logOpen} height=${logH} setHeight=${setLogH} />
        </main>
      </div>`}
    <${Toasts} shell=${shell} />
    <${ShellxOverlays} />
    <${WriteOverlays} />
    <${FontsWindow} />
    <${ScenesWindow} />
    <${DialogHost} />
  </div>`;
}
