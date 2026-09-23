// Emulate (Stern Spike 2): run a card image under the rig and watch the
// run's health.  Every decision lives in tabs/emulate.py (the port of
// gui/emulate_tab.py); this page renders the `emulate` namespace and sends
// the clicks back.

import { html, useEffect, useRef, useState, PageHead, Card, Button, Field, Select, Check,
  Chip, Note, Table, Modal, InfoBadge, Icon, tip, call, setField, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const INTRO = "Runs a real Stern Spike 2 game binary on this PC under emulation, in its own window, with sound. "
  + "Pick a card image and it runs straight off it — nothing is extracted and the image is opened read only.";

// ------------------------------------------------------------ notices
// A notice whose first paragraph is its headline ("This PC cannot run the
// emulator yet.") shows that line in bold.
function Headed({ text }) {
  const i = (text || "").indexOf("\n\n");
  if (i <= 0 || i > 120) return text;
  return html`<b class="emu-nhead">${text.slice(0, i)}</b>${text.slice(i)}`;
}

function Notices({ s }) {
  const mac = s.platform === "darwin";
  const setupBtn = s.setup_btn ? html`<${Button} kind="primary" size="sm" disabled=${!s.setup_enabled}
      busy=${!s.setup_enabled} onClick=${() => call("emulate.setup_fix")}>${s.setup_label}<//>` : null;
  const dockerBtn = s.docker_btn ? html`<${Button} kind="primary" size="sm" disabled=${s.docker_enabled === false}
      onClick=${() => call("emulate.docker_fix")}>${s.docker_btn}<//>` : null;
  const out = [];
  if (s.rig_missing) out.push(html`<${Note} kind="warn"><${Headed} text=${s.rig_missing} /><//>`);
  if (s.docker_msg) out.push(html`<${Note} kind="warn" action=${mac ? (setupBtn || dockerBtn) : dockerBtn}>${s.docker_msg}<//>`);
  if (s.setup_msg) out.push(html`<${Note} kind="warn" action=${mac ? null : setupBtn}><${Headed} text=${s.setup_msg} /><//>`);
  if (s.rt_msg) out.push(html`<${Note} kind="warn" action=${s.rt_btn ? html`<${Button} kind="primary" size="sm"
      disabled=${!s.rt_enabled} busy=${!s.rt_enabled} onClick=${() => call("emulate.runtime_fix")}>${s.rt_label}<//>` : null}>${s.rt_msg}<//>`);
  if (!out.length) return null;
  return html`<div class="stack emu-notices">${out}</div>`;
}

// ---------------------------------------------------------- run button
function RunButton({ s }) {
  const b = s.run_btn || { label: "Start emulator", enabled: false, mode: "start" };
  const kind = b.mode === "stop" ? "danger" : b.mode === "cancel" ? "" : "primary";
  const icon = b.mode === "stop" ? "stop" : b.mode === "cancel" ? "x" : b.mode === "start" ? "play" : null;
  return html`<${Button} kind=${kind} size="big" cls="emu-run" icon=${icon} busy=${b.mode === "busy"}
    disabled=${!b.enabled} onClick=${() => call("emulate.toggle")}>${b.label}<//>`;
}

function Volume({ s }) {
  const [v, setV] = useState(Math.round(s.volume ?? 100));
  const dragging = useRef(false);
  useEffect(() => { if (!dragging.current) setV(Math.round(s.volume ?? 100)); }, [s.volume]);
  const send = (x, flush) => setField("emulate", "volume", x, { delay: 80, flush });
  return html`<div class="row emu-vol">
    <label class="lbl" for="emu-vol">Volume</label>
    <input id="emu-vol" type="range" min="0" max="100" step="1" value=${v}
      onPointerDown=${() => { dragging.current = true; }}
      onPointerUp=${(e) => { dragging.current = false; send(Number(e.target.value), true); }}
      onInput=${(e) => { const x = Number(e.target.value); setV(x); send(x, false); }}
      onChange=${(e) => send(Number(e.target.value), true)} />
    <span class="mono small emu-volpct">${v}%</span>
    <${Check} ns="emulate" k="mute" checked=${s.mute} label="Mute" />
  </div>`;
}

// --------------------------------------------------------- card source
// A long card path shows its END (the file name) unless it is being edited.
function useEndScroll(ref, value) {
  useEffect(() => {
    const el = ref.current && ref.current.querySelector("input");
    if (el && document.activeElement !== el) el.scrollLeft = el.scrollWidth;
  }, [value]);
}

function CardSource({ s }) {
  const pathRef = useRef(null);
  useEndScroll(pathRef, s.card);
  const countries = (s.countries || []).map((c) => ({ value: c, label: c }));
  const powers = (s.powers || []).map((p) => ({ value: p, label: p }));
  const head = html`<span class="h2">Card image to run</span><span class="sp"></span>
    ${s.game ? html`<${Chip} kind="ok" dot title="The title read from the card's file name; the save states below are this title's.">${s.game}<//>` : null}`;
  // The hint (a refused Start's reason, a path, the WSL-boot paragraph) gets
  // a full-width row of its own under the button and the volume, as Tk's
  // own label under the controls did: it never shares a line with them.
  return html`<${Card} head=${head} cls="emu-card" footer=${html`
      <${RunButton} s=${s} />
      <${Volume} s=${s} />
      ${s.hint ? html`<span class="small dim emu-hint" role="status">${s.hint}</span>` : null}`}>
    <div class="row emu-src">
      <div class="grow emu-path" ref=${pathRef}>
        <${Field} ns="emulate" k="card" value=${s.card} mono placeholder="Pick a Spike 2 card image" title=${s.card || ""} />
      </div>
      <${Button} onClick=${() => call("emulate.browse")}>Browse…<//>
      <${Button} kind="ghost" onClick=${() => call("emulate.open_cache")}
        title="Shows and manages the card cache: the copies of each card on the WSL disk that later boots start from. Deleting frees the space now; the card re-copies on its next boot.">Cache…<//>
    </div>
    <div class="grid2 emu-machine">
      <div class="stack emu-lblf"><label class="lbl" for="emu-country">Country (DIP switches)</label>
        <${Select} id="emu-country" ns="emulate" k="country" value=${s.country} options=${countries} title=${s.country_tip} /></div>
      <div class="stack emu-lblf"><label class="lbl" for="emu-power">Power</label>
        <${Select} id="emu-power" ns="emulate" k="power" value=${s.power} options=${powers} title=${s.power_tip} /></div>
    </div>
    <div class="row emu-flags">
      <${Check} checked=${s.select} label="Boot selector" title=${s.select_tip}
        onChange=${(v) => call("emulate.set_select", v)} />
      <${Check} ns="emulate" k="topper" checked=${s.topper} label="Topper" title=${s.topper_tip} />
    </div>
    <div class=${cx("note emu-ovr", s.ovr_refused && "warn")}>
      <${Check} ns="emulate" k="overrides" checked=${s.overrides} wrap
        label="Apply my replaced assets on top, without rebuilding the card" />
      <div class="row emu-ovr-row">
        <span class="lbl nw">Assets folder</span>
        <${Field} value=${s.assets} readOnly mono sm cls="grow" placeholder="(none)"
          title="The Write tab's Assets Folder: the edits that would run." />
      </div>
      <span class=${cx("small emu-ovr-hint", s.ovr_refused ? "warn-ink" : "muted")}>${s.ovr_hint}</span>
    </div>
  <//>`;
}

// -------------------------------------------------------- save states
// A cell cut short shows the whole of it on hover, and every column but the
// last can be dragged wider (the Tk Treeviews' headers could).  The widths a
// drag leaves last for the session, like Tk's; they were never saved.
const SLOT_COLS = [
  { key: "slot", label: "Slot", width: "64px", cls: "mono", titleOf: (r) => r.iid },
  { key: "name", label: "Name", width: "minmax(96px,1fr)", titleOf: (r) => r.name || undefined },
  { key: "game", label: "Game", width: "minmax(70px,108px)", cls: "mono", titleOf: (r) => r.game || undefined },
  { key: "size", label: "Size", width: "64px", num: true },
  { key: "saved", label: "Saved", width: "96px", cls: "dim" },
];
const widthsKept = { slots: null, cache: null };
function useKeptWidths(key) {
  const [w, setW] = useState(widthsKept[key]);
  return [w, (next) => { widthsKept[key] = next; setW(next); }];
}

function SaveStates({ s }) {
  const rows = s.slots || [];
  const on = !!s.slots_enabled;
  const [widths, setWidths] = useKeptWidths("slots");
  const h = 32 + Math.max(3, Math.min(rows.length, 6)) * 34;
  const head = html`<span class="h2">Save states</span><${InfoBadge} text=${s.states_tip} />
    <span class="sp"></span><span class="small muted">saved and loaded from the virtual playfield window</span>`;
  // "No save states" only once the slots were read: before that (and while
  // WSL boots) the table is simply empty and the summary under it speaks.
  const empty = s.slots_read
    ? html`<div class="small muted emu-empty">${s.game ? "No save states for this title" : "No save states"}</div>`
    : null;
  return html`<${Card} head=${head} cls="emu-states" bodyCls="emu-states-bd">
    <div class="emu-states-row">
      <div class="stack emu-states-tbl">
        <${Table} columns=${SLOT_COLS} rows=${rows} rowKey=${(r) => r.iid} selected=${s.slot_sel}
          style=${`height:${h}px`} resizable widths=${widths} onResize=${setWidths}
          onSelect=${(r) => call("emulate.select_slot", r.iid)}
          empty=${empty} />
        <span class="small muted emu-sum">${s.slots_sum}</span>
      </div>
      <div class="stack emu-states-btns">
        <${Button} kind="primary" size="sm" disabled=${!on} title=${s.launch_tip}
          onClick=${() => call("emulate.slot_launch")}>Launch<//>
        <${Button} size="sm" disabled=${!on} onClick=${() => call("emulate.slots_refresh")}>Refresh<//>
        <${Button} size="sm" disabled=${!on} onClick=${() => call("emulate.slot_rename_begin")}>Rename…<//>
        <${Button} kind="ghost" size="sm" disabled=${!on} onClick=${() => call("emulate.slot_delete")}>Delete<//>
      </div>
    </div>
  <//>`;
}

// ------------------------------------------------------------- status
function Status({ s }) {
  const v = s.vals || {};
  const kind = s.state_kind || "";
  const dropping = /dropping/.test(v.audio || "");
  const known = v.state && v.state !== "—";
  return html`<${Card} head=${html`<span class="h2">Status</span><span class="sp"></span>
      ${known ? html`<${Chip} kind=${kind} dot>${v.state}<//>` : null}`} cls="emu-status">
    <div class="kv emu-kv">
      <span class="k">State</span>
      <span class="row emu-state">${v.state || "—"}${s.state_tip ? html`<${InfoBadge} text=${s.state_tip} />` : null}</span>
      <span class="k">Processes</span><span>${v.procs || "—"}</span>
      <span class="k">Game CPU / memory</span><span class="mono">${v.cpu || "—"}</span>
      <span class="k">Renderer</span><span class="mono">${v.host || "—"}</span>
      <span class="k">Audio</span><span class=${cx("mono", dropping && "warn-ink")}>${v.audio || "—"}</span>
    </div>
  <//>`;
}

// The game window and the virtual playfield open on every platform: under
// WSL the playfield is a Windows process PAD or the run opens, on a Linux
// desktop (and inside the macOS container) watch.sh opens it as a local Tk
// window.  A window is named by its real title only when the card's file
// name gives the game; otherwise it is described, never a placeholder.
function WindowsCard({ s }) {
  const game = s.game;
  const mac = s.platform === "darwin";
  const gameWin = html`<div class="note emu-win"><div class="stack">
      ${game ? html`<b class="emu-wt mono">${game} - Stern Spike 2 emulator</b>` : html`<b class="emu-wt">The game window</b>`}
      <span class="small">The game's own picture and sound, with a “Controls - Spike 2 emulator” window beside it that lists the keys.</span>
    </div></div>`;
  const playfield = html`<div class="note emu-win"><div class="stack">
      ${game ? html`<b class="emu-wt mono">${game} - virtual playfield</b>` : html`<b class="emu-wt">The virtual playfield</b>`}
      <span class="small">Every switch by name, the key panel, Insert coin · Start · Plunge · Reset balls · Clear switch alerts, and Save state / Load state.</span>
    </div></div>`;
  let body;
  if (mac) {
    body = html`
      <div class="note emu-win"><div class="stack">
        <b class="emu-wt">Screen Sharing</b>
        <span class="small">On macOS the game runs in a container and its picture is shown over VNC: Screen Sharing opens by itself once a run starts here (VNC password: pinball). The game window and the virtual playfield appear inside that picture.</span>
      </div></div>`;
  } else {
    body = html`${gameWin}${playfield}
      <span class="small muted">Both open by themselves at Start. Reset windows above puts them back on screen if one is lost.</span>`;
  }
  return html`<${Card} title="Windows the emulator opens" cls="emu-wins">${body}<//>`;
}

// ------------------------------------------------------------- modals
const CACHE_COLS = [
  { key: "label", label: "Card", width: "minmax(160px,1.2fr)", cls: "mono", titleOf: (r) => r.label },
  { key: "size", label: "On disk", width: "90px", num: true },
  { key: "booted", label: "Last booted", width: "140px", titleOf: (r) => r.booted || undefined },
  { key: "src", label: "Source image", width: "minmax(0,1.6fr)", cls: "mono dim", titleOf: (r) => r.src || undefined },
];

function CacheModal({ c }) {
  const rows = c.rows || [];
  const sel = new Set(c.sel || []);
  const [widths, setWidths] = useKeptWidths("cache");
  // anchor: where a Shift range starts; cursor: the row the keyboard is on.
  // Tk's extended-select Treeview: Up/Down move and select one row, Shift
  // extends from the anchor, Ctrl-click toggles, Shift-click ranges.
  const anchor = useRef(null);
  const cursor = useRef(null);
  const wrap = useRef(null);
  const keepInView = (i) => {
    const el = wrap.current && wrap.current.querySelector(".scroller");
    if (!el) return;
    const rh = 34, y = i * rh;
    if (y < el.scrollTop) el.scrollTop = y;
    else if (y + rh > el.scrollTop + el.clientHeight - rh) el.scrollTop = y - el.clientHeight + rh * 2;
  };
  const pick = (r, i, e) => {
    if (!rows.length) return;
    let next;
    if (e && e.type === "keydown") {
      // the Table's own arrow handling cannot see a Set's cursor: move from
      // the row the keyboard (or the last click) left off at
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const from = cursor.current == null ? -1 : Math.min(cursor.current, rows.length - 1);
      i = e.key === "ArrowDown" ? Math.min(rows.length - 1, from + 1) : Math.max(0, from - 1);
      r = rows[i];
      cursor.current = i;
      if (e.shiftKey && anchor.current != null) {
        const [a, b] = [Math.min(anchor.current, i), Math.max(anchor.current, i)];
        next = new Set();
        for (let k = a; k <= b; k++) next.add(rows[k].label);
      } else {
        next = new Set([r.label]);
        anchor.current = i;
      }
      keepInView(i);
    } else if (e && e.shiftKey && anchor.current != null) {
      const [a, b] = [Math.min(anchor.current, i), Math.max(anchor.current, i)];
      next = new Set(e.ctrlKey || e.metaKey ? sel : []);
      for (let k = a; k <= b; k++) next.add(rows[k].label);
      cursor.current = i;
    } else if (e && (e.ctrlKey || e.metaKey)) {
      next = new Set(sel);
      if (next.has(r.label)) next.delete(r.label); else next.add(r.label);
      anchor.current = i;
      cursor.current = i;
    } else {
      next = new Set([r.label]);
      anchor.current = i;
      cursor.current = i;
    }
    call("emulate.cache_select", [...next]);
  };
  // a different set of rows (a refresh after a delete) starts the keyboard
  // over, as a fresh Treeview did
  const rowsKey = rows.map((x) => x.label).join("\n");
  useEffect(() => { anchor.current = null; cursor.current = null; }, [rowsKey]);
  const close = () => call("emulate.cache_close");
  return html`<${Modal} title="Card cache — Spike 2 emulator" icon="disk" xwide onClose=${close} cls="emu-cache"
    footer=${html`<span class="small muted grow emu-cache-hint">${c.hint}</span>
      <${Button} kind="danger" disabled=${c.busy || !sel.size} onClick=${() => call("emulate.cache_delete")}>Delete selected<//>
      <${Button} disabled=${c.busy} onClick=${() => call("emulate.cache_refresh")}>Refresh<//>
      <${Button} onClick=${close}>Close<//>`}>
    <div class="row">${c.busy ? html`<span class="spin"></span>` : null}<span>${c.head}</span></div>
    <div class="emu-cache-tbl" ref=${wrap}>
      <${Table} columns=${CACHE_COLS} rows=${rows} rowKey=${(r) => r.label} selected=${sel}
        onSelect=${pick} style="height:300px" resizable widths=${widths} onResize=${setWidths} />
    </div>
  <//>`;
}

// Tk's dialog renamed ONLY from its Rename button or Return; Cancel, Escape
// and the close box changed nothing.  So this is a plain input, not a Field
// (a Field commits on blur, and the click on Cancel or X blurs it first).
function RenameModal({ r }) {
  const [val, setVal] = useState(r.value || "");
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.focus(); }, []);
  const go = () => call("emulate.slot_rename", ref.current ? ref.current.value : val);
  const cancel = () => call("emulate.slot_rename_cancel");
  return html`<${Modal} title="Rename slot" onClose=${cancel}
    footer=${html`<${Button} kind="primary" onClick=${go}>Rename<//><${Button} onClick=${cancel}>Cancel<//>`}>
    <label class="lbl" for="emu-rename">Name for '${r.slot}':</label>
    <div class="field"><input id="emu-rename" ref=${ref} type="text" value=${val} spellcheck="false"
      onInput=${(e) => setVal(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); go(); } }} /></div>
  <//>`;
}

// --------------------------------------------------------------- page
export default function EmulateTab() {
  const s = useNs("emulate");
  const win = s.platform === "win32";
  return html`<div class="page emu">
    <${PageHead} title="Emulate" sub=${INTRO}>
      <${Button} disabled=${!s.check_enabled} busy=${!s.check_enabled}
        title="Re-checks what this PC needs to run the emulator and writes the full report to the log, including a machine with nothing wrong. It changes nothing."
        onClick=${() => call("emulate.check_setup")}>${s.check_label || "Check setup…"}<//>
      ${win ? html`<${Button} kind="ghost" disabled=${!s.fixaud_enabled} onClick=${() => call("emulate.restart_wsl")}
        title="The cure for an emulator window that will not close, or crackly sound. It closes everything running in WSL.">Restart WSL…<//>` : null}
      <${Button} kind="ghost" disabled=${!s.winreset_enabled} onClick=${() => call("emulate.reset_windows")}
        title="Forget where the emulator windows were, so they open at their default position and size next time.">Reset windows<//>
    <//>
    <${Notices} s=${s} />
    <div class="cols c75 emu-cols">
      <div class="stack emu-col">
        <${CardSource} s=${s} />
        <${SaveStates} s=${s} />
      </div>
      <div class="stack emu-col">
        <${Status} s=${s} />
        <${WindowsCard} s=${s} />
      </div>
    </div>
    ${s.cache ? html`<${CacheModal} c=${s.cache} />` : null}
    ${s.rename ? html`<${RenameModal} key=${s.rename.slot} r=${s.rename} />` : null}
  </div>`;
}
