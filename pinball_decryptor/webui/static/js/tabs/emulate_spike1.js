// Emulate (Stern Spike 1): run a DMD-era game on this PC.  Python half:
// webui/tabs/emulate_spike1.py (the Tk panel was gui/spike1_emulate_tab.py;
// the DMD and switch/LED windows were gui/spike1_windows.py's two windows).
//
// The display and the switch / LED panel are their OWN native windows while
// a game runs, as in Tk: the view page emulate_spike1_view.html calls
// mountView() below and draws one of them full-window.  Without a native
// window (--browser / --serve) the tab draws them as two cards instead.

import { html, useEffect, useRef, useState, PageHead, Card, Button, PathField, Note, Table,
  Modal, InfoBadge, openMenu, cx, call } from "../core/ui.js";
import { render } from "../vendor/preact-htm.js";
import { raw } from "../core/rpc.js";
import { useNs, loadAll, connect } from "../core/store.js";
import { VolumeControl, StateChip, introLines } from "./emulate_jjp_shared.js";

export const css = true;
const NS = "emulate_spike1";
const c = (m, ...a) => call(NS + "." + m, ...a);

// ------------------------------------------------------------ keyboard
// The Tk keysyms the switch window's handlers expect (the Spike 2
// playfield's keys: arrows flippers, 1 Start, 5 coin, T tilt, F shooter
// lane, Enter / - / = / Backspace the service buttons, C door, B trough).
const NAMED_KEYS = { ArrowLeft: "Left", ArrowRight: "Right", ArrowUp: "Up", Enter: "Return",
  Backspace: "BackSpace", Escape: "Escape", "=": "equal", "-": "minus" };
const PLAIN_KEYS = new Set(["1", "5", "t", "f", "c", "b"]);
function keysymOf(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (e.code === "NumpadEnter") return "KP_Enter";
  if (NAMED_KEYS[e.key]) return NAMED_KEYS[e.key];
  const k = (e.key || "").toLowerCase();
  return PLAIN_KEYS.has(k) ? k : null;
}
function keyDown(e) {
  const k = keysymOf(e);
  if (!k) return;
  e.preventDefault();
  if (!e.repeat) c("key_down", k);
}
function keyUp(e) {
  const k = keysymOf(e);
  if (!k) return;
  e.preventDefault();
  c("key_up", k);
}
// On a card in the tab: the keys work while the card has focus.
function playKeys() {
  return { tabIndex: 0, onKeyDown: keyDown, onKeyUp: keyUp, onBlur: () => c("keys_release") };
}

// A poll the page runs while a view is on screen (a loop=False call, so a
// 20 Hz display never goes through the event stream).
function usePoll(method, ms, active, argsFn) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!active) { setData(null); return undefined; }
    let alive = true;
    let timer = null;
    const tick = async () => {
      if (!alive) return;
      let j = null;
      try { j = await raw(NS + "." + method, argsFn ? argsFn() : []); } catch (err) { j = null; }
      if (!alive) return;
      if (j && j.ok) setData((prev) => (j.r && j.r.png === undefined && j.r.sig && prev && prev.sig === j.r.sig ? prev : j.r));
      timer = setTimeout(tick, ms);
    };
    timer = setTimeout(tick, 0);
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [active]);
  return data;
}

// --------------------------------------------------------------- display
function useFrame(active) {
  const sig = useRef("");
  const frame = usePoll("view_frame", 50, active, () => [sig.current]);
  if (frame && frame.png) sig.current = frame.sig;
  return frame;
}

function DisplayBody({ s, frame, keys }) {
  const alpha = s.view_mode === "alpha";
  return html`
    <div class=${cx("emu-screen", alpha && "alpha")} ...${keys || {}} aria-label="Game display">
      ${frame && frame.png
        ? html`<img src=${frame.png} alt="" style=${`aspect-ratio:${frame.w}/${frame.h}`} draggable="false" />`
        : html`<span class="emu-wait">waiting for the game to draw…</span>`}
    </div>
    ${alpha && frame && frame.text ? html`<div class="emu-readouts">
      ${frame.text.map((t, i) => html`<div class="emu-readout"><span class="big">${t}</span>
        <span class="cap">${(frame.labels || [])[i] || ""}</span></div>`)}
    </div>` : null}`;
}

function DisplayCard({ s }) {
  const frame = useFrame(!!s.view_open);
  return html`<${Card} title=${s.view_mode === "alpha" ? "Display" : "DMD"} cls="emu-display" bodyCls="flush">
    <${DisplayBody} s=${s} frame=${frame} keys=${playKeys()} />
  <//>`;
}

// --------------------------------------------------------------- switches
// Cell colours are the theme's (emulate_spike1.css --emu-*); a lit lamp
// shows its own colour.
function KeyPanel({ sw, live }) {
  const made = new Set((live && live.made) || []);
  const ball = (live && live.ball) || { balls: 0, nballs: 6, in_shooter: false, door_closed: true };
  const dead = !!sw.early;
  const nb = ball.nballs || 6;
  const shooterAt = Math.min(ball.balls || 0, 5);
  return html`<div class="emu-keys">
    <div class="emu-kh"><b>KEYBOARD</b><span class="muted">works in the DMD window</span></div>
    ${(sw.key_rows || []).map((r) => html`<div class=${cx("emu-krow", r.slot == null && "dead", r.slot != null && made.has(r.slot) && "on")}>
      <span class="key">${r.key}</span><span class="lab">${r.label}</span></div>`)}
    <div class="emu-svc">
      ${(sw.svc || []).map((b) => html`<div class="emu-svcb">
        <button type="button" class=${cx("svc", dead && "dead")} style=${dead ? "" : `background:${b.color}`}
          disabled=${dead} onClick=${() => c("ball_cmd", "svc " + b.name)}>${b.text}</button>
        <span class="k">${dead ? "" : b.key}</span></div>`)}
    </div>
    ${dead ? html`<div class="small muted">no service buttons on this machine</div>` : null}
    <button type="button" class=${cx("emu-door", dead ? "dead" : ball.door_closed ? "closed" : "open")}
      disabled=${dead} onClick=${() => c("ball_cmd", "door toggle")}>
      <span>${dead ? "TEST MODE: hold both flippers 3s" : ball.door_closed ? "COIN DOOR CLOSED" : "COIN DOOR OPEN"}</span>
      ${dead ? null : html`<span class="k">C</span>`}
    </button>
    <div class="emu-kh"><b>BALLS</b><span class="k">B</span></div>
    <div class="emu-balls">
      ${[0, 1, 2, 3, 4, 5].map((i) => html`<button type="button" aria-label=${"Ball " + (i + 1)}
        class=${cx("ball", i >= nb && "none", i < (ball.balls || 0) && "in", ball.in_shooter && i === shooterAt && "shooter")}
        onClick=${() => c("ball_click", i)}></button>`)}
    </div>
  </div>`;
}

function SwitchList({ sw, live, setHover }) {
  const made = new Set((live && live.made) || []);
  const byNode = new Map();
  for (const n of sw.names || []) {
    if (!byNode.has(n.node)) byNode.set(n.node, []);
    byNode.get(n.node).push(n);
  }
  const describe = (n) => `node ${n.node} · index ${n.idx} — ${n.name}`;
  return html`<div class="emu-swlist-wrap">
    <div class="emu-kh"><b>SWITCHES</b><span class="muted">click = pulse · right-click = hold/release · node,index</span></div>
    <div class="emu-swlist">
      ${[...byNode.keys()].sort((a, b) => a - b).map((node) => html`<div class="emu-node">
        <div class="emu-nodeh">NODE ${node}</div>
        ${byNode.get(node).map((n) => html`<button type="button" class=${cx("emu-sw", made.has(n.slot) && "on")}
          onClick=${() => c("sw_pulse", n.node, n.idx)}
          onContextMenu=${(e) => { e.preventDefault(); c("sw_toggle", n.node, n.idx); }}
          onMouseEnter=${() => setHover(describe(n))} onMouseLeave=${() => setHover("")}>
          <span class="pos">${n.node},${n.idx}</span><span class="nm">${n.name}</span></button>`)}
      </div>`)}
    </div>
  </div>`;
}

function SwitchGrid({ sw, live, setHover }) {
  const made = new Set((live && live.made) || []);
  const lamps = (live && live.lamps) || {};
  const coils = new Set((live && live.coils) || []);
  const nodes = (live && live.nodes) || [0, 1, 8, 9, 10, 11, 12];
  const sections = (live && live.sections) || [["sw", "Switch matrix — click to inject"]];
  const cols = sw.cols || 16;
  const cellCls = (kind, slot) => kind === "sw" ? cx("cell", "sw", made.has(slot) && "on")
    : kind === "lamp" ? "cell lamp" : cx("cell", "coil", coils.has(slot) && "on");
  return html`<div class="emu-grid-wrap">
    ${sections.map(([kind, label]) => html`<div class="emu-gsec">
      <div class="emu-gh">${label}</div>
      <div class="emu-grid" style=${`grid-template-columns: 58px repeat(${cols}, 20px)`}>
        ${nodes.map((node) => html`<span class="nl">node ${node}</span>
          ${Array.from({ length: cols }, (_, i) => {
            const slot = node * 64 + i;
            const lit = kind === "lamp" ? lamps[String(slot)] : null;
            return html`<span class=${cellCls(kind, slot)} style=${lit ? `background:${lit}` : undefined}
              onClick=${kind === "sw" ? () => c("sw_pulse", node, i) : undefined}
              onContextMenu=${kind === "sw" ? (e) => { e.preventDefault(); c("sw_toggle", node, i); } : undefined}
              onMouseEnter=${kind === "sw" ? () => setHover(`node ${node} · index ${i} — (unassigned)`) : undefined}
              onMouseLeave=${kind === "sw" ? () => setHover("") : undefined}></span>`;
          })}`)}
      </div>
    </div>`)}
  </div>`;
}

const BALL_BAR = [["Start", "start"], ["Plunge", "plunge"], ["Drain", "drain"], ["Ball in", "ballin"],
  ["Ball out", "ballout"], ["Coin", "coin 1"]];
function BallBar() {
  return html`<div class="row emu-bar">${BALL_BAR.map(([label, cmd]) => html`<${Button} size="sm"
    onClick=${() => c("ball_cmd", cmd)}>${label}<//>`)}</div>`;
}

// The readout line: the switch under the pointer, else the last click's
// own words ("pulsed …", "held …", "sent …"), which stay until the pointer
// moves on to another switch, as the Tk window's did.
function useSwitchView(s) {
  const sw = s.sw || {};
  const [hover, setHover] = useState("");
  useEffect(() => setHover(""), [sw.readout]);
  return { sw, setHover, readout: hover || sw.readout || "" };
}

// The switch list (or the raw matrix for a title with no map yet) and the
// keyboard / service / door / trough panel.
function SwitchBody({ sw, live, setHover, keys }) {
  const named = (sw.names || []).length > 0;
  return html`<div class="emu-swbody" ...${keys || {}} aria-label="Switches and LEDs">
    ${named ? html`<${SwitchList} sw=${sw} live=${live} setHover=${setHover} />`
      : html`<${SwitchGrid} sw=${sw} live=${live} setHover=${setHover} />`}
    <${KeyPanel} sw=${sw} live=${live} />
  </div>`;
}

function SwitchCard({ s }) {
  const live = usePoll("view_state", 80, !!s.view_open);
  const v = useSwitchView(s);
  return html`<${Card} title="Switches / LEDs" cls="emu-switches" extra=${html`<${BallBar} />`}
    footer=${html`<span class="small dim emu-rdo">${v.readout}</span>`}>
    <${SwitchBody} sw=${v.sw} live=${live} setHover=${v.setHover} keys=${playKeys()} />
  <//>`;
}

// ----------------------------------------------------- the view windows
// emulate_spike1_view.html?view=display|switches: one panel, full-window,
// fed like the cards.  The play keys work anywhere in the window (Tk bound
// them on the whole Toplevel), and a window losing focus lets them go.
function applyTheme(theme) {
  let t = theme || "dark";
  if (t === "system") t = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.classList.toggle("light", t === "light");
}

function DisplayWindow({ s }) {
  const frame = useFrame(!!s.view_open);
  return html`<div class="emu-view-display"><${DisplayBody} s=${s} frame=${frame} /></div>`;
}

function SwitchWindow({ s }) {
  const live = usePoll("view_state", 80, !!s.view_open);
  const v = useSwitchView(s);
  return html`<div class="emu-view-switches">
    <div class="emu-view-bar"><${BallBar} /></div>
    <div class="emu-view-scroll"><${SwitchBody} sw=${v.sw} live=${live} setHover=${v.setHover} /></div>
    <div class="emu-view-rdo small dim emu-rdo">${v.readout}</div>
  </div>`;
}

function ViewApp({ which }) {
  const s = useNs(NS);
  const shell = useNs("shell");
  useEffect(() => applyTheme(shell.theme), [shell.theme]);
  useEffect(() => {
    const z = Math.max(0.6, Math.min(2, Number(shell.zoom) || 1));
    document.documentElement.style.zoom = String(z);
  }, [shell.zoom]);
  useEffect(() => {
    const release = () => c("keys_release");
    document.addEventListener("keydown", keyDown);
    document.addEventListener("keyup", keyUp);
    window.addEventListener("blur", release);
    // right-click is the switches' hold / release, never the browser's menu
    const noMenu = (e) => e.preventDefault();
    document.addEventListener("contextmenu", noMenu);
    return () => {
      document.removeEventListener("keydown", keyDown);
      document.removeEventListener("keyup", keyUp);
      window.removeEventListener("blur", release);
      document.removeEventListener("contextmenu", noMenu);
    };
  }, []);
  useEffect(() => {
    document.title = which === "switches" ? "Spike 1 — switches / LEDs"
      : s.view_mode === "alpha" ? "Spike 1 — display" : "Spike 1 — DMD";
  }, [which, s.view_mode]);
  return which === "switches" ? html`<${SwitchWindow} s=${s} />` : html`<${DisplayWindow} s=${s} />`;
}

export async function mountView(root) {
  const which = new URLSearchParams(location.search).get("view") === "switches" ? "switches" : "display";
  document.body.classList.add("emu-view", "emu-view-" + which);
  try {
    await loadAll();
  } catch (err) {
    root.textContent = "The app did not answer (" + String(err.message || err) + ").";
    return;
  }
  render(html`<${ViewApp} which=${which} />`, root);
  connect();
}

// ------------------------------------------------------------ save states
// Column widths the user dragged, kept for the session (Tk's Treeview
// columns kept theirs while the app ran).
const colWidths = {};
function useColWidths(key) {
  const [w, setW] = useState(colWidths[key] || null);
  return [w, (next) => { colWidths[key] = next; setW(next); }];
}

function SaveStates({ s }) {
  const [sel, setSel] = useState(null);
  const [widths, setWidths] = useColWidths("slots");
  const rows = s.slots || [];
  const ok = !!s.slots_enabled;
  useEffect(() => { if (sel && !rows.some((r) => r.ref === sel)) setSel(null); }, [rows]);
  const cols = [
    { key: "slot", label: "Slot", width: "64px", cls: "mono" },
    { key: "name", label: "Name", width: "minmax(0,1fr)" },
    { key: "game", label: "Game", width: "96px", cls: "mono" },
    { key: "size", label: "Size", width: "70px", num: true },
    { key: "saved", label: "Saved", width: "118px", cls: "dim" },
  ];
  return html`<${Card} cls="emu-states"
    head=${html`<span class="h2">Save states</span><${InfoBadge} text=${(s.tips || {}).states} />`}>
    <div class="emu-states-row">
      <${Table} columns=${cols} rows=${rows} rowKey=${(r) => r.ref} selected=${sel}
        onSelect=${(r) => setSel(r.ref)} cls="emu-slots" resizable widths=${widths} onResize=${setWidths} />
      <div class="stack emu-slotbtns">
        <${Button} size="sm" disabled=${!ok} onClick=${() => c("slot_save")}>Save now<//>
        <${Button} size="sm" kind="primary" disabled=${!ok} onClick=${() => c("slot_load", sel)}>Load<//>
        <${Button} size="sm" disabled=${!ok} onClick=${() => c("slots_refresh")}>Refresh<//>
        <${Button} size="sm" disabled=${!ok} onClick=${() => c("slot_rename", sel)}>Rename…<//>
        <${Button} size="sm" kind="ghost" disabled=${!ok} onClick=${() => c("slot_delete", sel)}>Delete<//>
      </div>
    </div>
    <span class="small muted">${s.slots_sum}</span>
  <//>`;
}

// ----------------------------------------------------------------- cache
function CacheModal({ cache }) {
  const [sel, setSel] = useState(null);
  const [widths, setWidths] = useColWidths("cache");
  const rows = cache.rows || [];
  const row = rows.find((r) => r.label === sel);
  const cols = [
    { key: "game", label: "Game", width: "150px" },
    { key: "label", label: "Card", width: "minmax(0,1fr)", cls: "mono" },
    { key: "size", label: "Size", width: "80px", num: true },
    { key: "used", label: "Last used", width: "96px" },
    { key: "active", label: "", width: "64px", render: (r) => (r.active ? html`<span class="acc-ink">active</span>` : "") },
  ];
  const close = () => c("cache_close");
  return html`<${Modal} title="Extracted games — Spike 1 emulator" wide onClose=${close}
    footer=${html`<${Button} onClick=${() => c("cache_reload")}>Refresh<//>
      <${Button} kind="danger" disabled=${!row || row.active || cache.busy}
        onClick=${() => c("cache_delete", sel)}>Delete selected<//>
      <${Button} kind="primary" onClick=${close}>Close<//>`}>
    <p class="dim" style="margin:0">Each card you Start is extracted once and kept here, so switching between titles
      reuses the extraction instead of re-extracting (~1 min). The one in use is marked ‘active’ and can't be deleted.</p>
    <${Table} columns=${cols} rows=${rows} rowKey=${(r) => r.label} selected=${sel}
      onSelect=${(r) => setSel(r.label)} cls="emu-cache" resizable widths=${widths} onResize=${setWidths} />
    <span class="small muted">${cache.header}</span>
  <//>`;
}

// ------------------------------------------------------------------ page
function fixMenu(anchor) {
  openMenu(anchor, [
    { label: "Delete the emulator's data…", icon: "trash", onClick: () => c("delete_rig_data") },
    { label: "Delete downloaded files…", icon: "trash", onClick: () => c("delete_downloads") },
    { sep: true },
    { label: "Remove the app’s Linux…", icon: "x", onClick: () => c("remove_runtime") },
  ]);
}

export default function EmulateSpike1() {
  const s = useNs(NS);
  const shell = useNs("shell");
  const tips = s.tips || {};
  const up = !!s.up;
  const viewRef = useRef(null);
  const hist = (shell.path_history && shell.path_history.spike1_emulate_card) || [];
  useEffect(() => {
    if (s.reveal && viewRef.current) viewRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [s.reveal]);
  // the spinner is Start's own (a start or stop in flight); a WSL restart
  // only greys Start and spins on Restart WSL…
  const goKind = s.go_busy ? "" : up ? "danger" : "primary";
  const rows = s.rows || [];
  const cache = s.cache || {};
  // the cards stand in for the two windows only when the app has none
  const cards = !!s.view_open && !s.view_popout;
  return html`<div class="page emu-page emu-s1">
    <${PageHead} title="Emulate" sub=${introLines(s.intro)}>
      <${Button} title=${tips.check} onClick=${() => c("check_setup")}>Check setup…<//>
      <div class="emu-split" onContextMenu=${(e) => { e.preventDefault(); fixMenu(e.currentTarget); }}>
        <${Button} title=${tips.fix} disabled=${!s.fix_enabled} onClick=${() => c("fix_setup")}
          label="Fix setup">Fix setup<//>
        <button type="button" class="btn icon" aria-label="Fix setup menu"
          onClick=${(e) => fixMenu(e.currentTarget)}>▾</button>
      </div>
      ${s.win ? html`<${Button} kind="ghost" title=${tips.reset} disabled=${!s.reset_enabled} busy=${s.reset_busy}
        onClick=${() => c("fix_state")}>${s.reset_label || "Restart WSL…"}<//>` : null}
      <${Button} kind="ghost" title=${tips.winreset} onClick=${() => c("window_reset")}>Reset windows<//>
    <//>
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${Card} title="Card image (extracted once, then kept)" cls="emu-src"
          footer=${html`
            <${Button} kind=${goKind} size="big" icon=${up ? "stop" : "play"} busy=${s.go_busy}
              disabled=${!s.go_enabled} onClick=${() => c("toggle")}>${s.go_label || "Start emulator"}<//>
            <span class="emu-sp"></span>
            <${VolumeControl} ns=${NS} s=${s} />`}>
          <${PathField} ns=${NS} k="card" value=${s.card} title=${tips.card} history=${hist}
            placeholder="A Spike 1 game card image (.img/.raw/.vhd/.iso)"
            onBrowse=${() => c("browse")}
            extra=${html`<${Button} kind="ghost" onClick=${() => c("cache_open")}>Cache…<//>`} />
        <//>
        <${SaveStates} s=${s} />
      </div>
      <div class="stack emu-col">
        <${Card} title="Status" extra=${html`<${StateChip} tone=${s.tone}
          label=${(rows[0] || {}).value && (rows[0] || {}).value !== "—" ? rows[0].value : ""} />`}>
          <div class="kv emu-kv">
            ${rows.map((r) => html`<span class="k">${r.label.replace(/:$/, "")}</span><span class="mono v">${r.value}</span>`)}
          </div>
          ${s.hint ? html`<div class="small muted">${s.hint}</div>` : null}
        <//>
        ${s.note ? html`<${Note} kind=${s.note_kind || "warn"}>${s.note}<//>` : null}
        ${cards && s.view_display ? html`<div ref=${viewRef}><${DisplayCard} s=${s} /></div>` : null}
      </div>
    </div>
    ${cards ? html`<div ref=${s.view_display ? undefined : viewRef}><${SwitchCard} s=${s} /></div>` : null}
    ${cache.open ? html`<${CacheModal} cache=${cache} />` : null}
  </div>`;
}
