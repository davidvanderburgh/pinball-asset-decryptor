// Extract tab: a card image / ISO / update file (or the physical card in a
// reader) into a project folder.  The Python half is webui/tabs/extract.py;
// every label, tooltip and message here is the Tk tab's wording.

import { html, useEffect, useLayoutEffect, useRef, useState, Button, Field, Select, Seg, Check, Card, Chip,
         Icon, InfoBadge, Modal, PageHead, Spinner, openMenu, menuOpen, tip, cx, fmtBytes, call } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const PROJECT_TIP = "The project folder — extraction lands here, and every other tab works out of it. "
  + "A folder that already holds a project loads that project when picked.";
const CANCEL_TIP = "Cancel the operation in progress — it stops as soon as it's safe to.";
const BUSY_TIP = "Another operation is running — cancel it or let it finish first.";
const TRANSCRIBE_TIP = "Transcribe each spoken WAV (faster-whisper) and rename it by what's said — "
  + "e.g. “Super jackpot!”. Also writes callouts.csv.";
const MUSIC_TIP = "Identify each full song online (AcoustID) and rename it by artist + title — "
  + "e.g. “Led Zeppelin - Kashmir”. Needs internet.";
const DURATION_TIP = "Lead each extracted sound's filename with its play length — e.g. "
  + "“01m22s235 - idx0001.wav” — so sorting by name lines the same sounds up across firmware "
  + "versions (slot numbers shift between releases; play lengths rarely do).";
const READ_CARD_TIP = "Copy the whole card into a .raw image file — a backup you can flash back later, "
  + "open on the Partitions tab, or compare against another image. Nothing on the card changes.";

const article = (noun) => (/^\.?[aeiou]/i.test(noun || "") ? "an" : "a");
// "a card image", "an .iso file", "a ROM zip", "a file"
function inputPhrase(label) {
  if (!label || label === "Input") return "a file";
  if (label.startsWith(".")) return article(label) + " " + label + " file";
  const noun = /^[A-Z][a-z]/.test(label) ? label.charAt(0).toLowerCase() + label.slice(1) : label;
  return article(noun) + " " + noun;
}

const CARD_INFO_TIP = "What game this card is, and everything else the app can read off it — straight from the card, nothing copied";
const IMAGE_INFO_TIP = "Technical details about this image";
const PROJECT_INFO_TIP = "Stats about this project folder";

// A path box with the recent-paths list (the Tk combobox's dropdown) and
// Browse….  Leaving the box rewrites a mapped drive letter to its UNC path.
function PathCombo({ k, value, history, placeholder, onBrowse, badge, title, browseTitle, id }) {
  const caret = history && history.length ? html`<button type="button" ...${tip("Recent paths")} class="x-caret" aria-label="Recent paths"
      onClick=${(e) => openMenu(e.currentTarget.closest(".field") || e.currentTarget,
        history.map((p) => ({ label: p, onClick: () => call("extract.use_recent", k, p) })))}>▾</button>` : null;
  return html`<div class="row x-pathrow">
    <${Field} id=${id} ns="extract" k=${k} value=${value} mono cls="grow" placeholder=${placeholder} title=${title}
      suffix=${caret} onCommit=${(v) => call("extract.unmap", k, v)} />
    ${badge}
    <${Button} onClick=${onBrowse} title=${browseTitle}>Browse…<//>
  </div>`;
}

// ------------------------------------------------------------ card panels
function AdminPanel({ s }) {
  const collapsed = !!s.admin_collapsed;
  return html`<div class="x-alert" role="alert">
    <button type="button" class="x-alert-hd" aria-expanded=${!collapsed} onClick=${() => call("extract.toggle_admin_warning")}>
      <${Icon} name="warn" /><span class="grow">ADMINISTRATOR PRIVILEGES REQUIRED</span><span aria-hidden="true">${collapsed ? "▼" : "▲"}</span>
    </button>
    ${collapsed ? null : html`<div class="x-alert-bd">${s.admin_body}</div>`}
  </div>`;
}

function FdaPanel({ s }) {
  return html`<div class="x-alert" role="alert">
    <div class="x-alert-hd static"><${Icon} name="warn" /><span class="grow">macOS FULL DISK ACCESS REQUIRED</span>
      <button type="button" class="x-link" onClick=${() => call("extract.dismiss_fda")}>Hide this notice ✕</button></div>
    <div class="x-alert-bd">${s.fda_body}</div>
  </div>`;
}

function DropZone({ s }) {
  const [over, setOver] = useState(false);
  const [msg, setMsg] = useState("");
  const onDrop = (e) => {
    e.preventDefault();
    setOver(false);
    const files = [...((e.dataTransfer && e.dataTransfer.files) || [])];
    const paths = files.map((f) => f.pywebviewFullPath || f.path || "").filter(Boolean);
    if (!files.length) return;
    if (!paths.length) { setMsg("This window can't see where a dropped file lives — use Browse… instead."); return; }
    setMsg("");
    call("extract.drop_paths", paths);
  };
  return html`<div class=${cx("drop x-drop", over && "over")}
      onDragOver=${(e) => { e.preventDefault(); setOver(true); }} onDragLeave=${() => setOver(false)} onDrop=${onDrop}>
    <${Icon} name="upload" />
    <span>Drop ${inputPhrase(s.input_label)} here</span>
    ${(s.extensions || []).length ? html`<span class="small muted mono">${s.extensions.join("  ")}</span>` : null}
    ${msg ? html`<span class="small warn-ink">${msg}</span>` : null}
  </div>`;
}

// The picked drive's whole name, under the list whenever the list is too
// narrow to show all of it: its size, drive letter and \\.\PHYSICALDRIVEn
// are what tell one card from another.
let measureCtx = null;
function textWidth(text, cs) {
  try {
    if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
    measureCtx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    return measureCtx.measureText(text).width;
  } catch (e) {
    return 0;
  }
}
function DriveFull({ text }) {
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const sel = document.getElementById("x-drive");
    const check = () => {
      if (!sel || !text) { setClipped(false); return; }
      const cs = getComputedStyle(sel);
      const room = sel.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
      setClipped(textWidth(text, cs) > room - 1);
    };
    check();
    let ro = null;
    if (sel && window.ResizeObserver) { ro = new ResizeObserver(check); ro.observe(sel); }
    else window.addEventListener("resize", check);
    return () => { if (ro) ro.disconnect(); else window.removeEventListener("resize", check); };
  }, [text]);
  return clipped ? html`<div class="small mono dim x-wrapany x-drvfull">${text}</div>` : null;
}

function SourceBody({ s, hist }) {
  if (s.ssd) {
    const opts = (s.drives || []).length ? s.drives.map((d) => ({ value: d.display, label: d.display }))
      : [{ value: s.drive_display || "", label: s.drive_display || "" }];
    // The drive list keeps the whole width (its text is how the user tells
    // one card from another); the buttons drop to their own line whenever
    // there isn't room for both, as Tk's combobox took the row's slack.
    return html`<div class="stack x-sec">
        <label class="lbl" for="x-drive">${s.drive_label}</label>
        <div class="row x-drvrow">
          <div class="stack x-drvsel">
            <div class="row x-drvpick">
              <${Select} id="x-drive" cls="grow" value=${s.drive_display} options=${opts} title=${s.drive_display}
                disabled=${s.drives_state !== "ok"} onChange=${(v) => call("extract.select_drive", v)} />
              ${s.identify ? html`<${InfoBadge} text=${CARD_INFO_TIP} onClick=${() => call("extract.open_image_info", "drive")} />` : null}
            </div>
            ${s.drives_state === "ok" ? html`<${DriveFull} text=${s.drive_display} />` : null}
          </div>
          <div class="row x-drvbtns">
            <${Button} icon="refresh" onClick=${() => call("extract.refresh_drives")}>Refresh<//>
            ${s.read_card ? html`<${Button} onClick=${() => call("extract.open_read_card")} title=${READ_CARD_TIP}>Save card as image…<//>` : null}
          </div>
        </div>
        ${s.drives_state === "detecting" ? html`<div class="row small muted"><${Spinner} />Detecting drives…</div>` : null}
        ${s.identify && s.card_line ? html`<div class="x-cardline">${s.card_line}</div>` : null}
      </div>
      <div class="x-safety">${s.safety}</div>
      ${s.admin_panel ? html`<${AdminPanel} s=${s} />` : null}
      ${s.fda_panel ? html`<${FdaPanel} s=${s} />` : null}`;
  }
  const det = s.detected;
  const badge = s.badge;
  return html`<div class="stack x-sec">
      <label class="lbl" for="x-input">${s.input_label}</label>
      <${PathCombo} id="x-input" k="input" value=${s.input} history=${hist.extract_input}
        onBrowse=${() => call("extract.browse_input")}
        badge=${html`<${InfoBadge} text=${IMAGE_INFO_TIP} onClick=${() => call("extract.open_image_info", "input")} />`} />
      ${det ? html`<div class="row wrap x-chips">
          ${det.caption ? html`<${Chip} kind="ok" dot>${det.caption}<//>` : null}
          ${det.size != null ? html`<${Chip}>${fmtBytes(det.size)}<//>` : null}
          ${det.era ? html`<${Chip}>${det.era}<//>` : null}
          <span class="small muted">read as it is, never written to</span>
        </div>` : null}
      ${badge ? (badge.switch
        ? html`<button type="button" class=${cx("x-badge link", badge.kind)} onClick=${() => call("extract.switch_suggested")}><${Icon} name="warn" /><span>${badge.text}</span></button>`
        : html`<div class=${cx("x-badge", badge.kind)}><${Icon} name=${badge.kind === "info" ? "info" : "warn"} /><span>${badge.text}</span></div>`) : null}
    </div>
    <${DropZone} s=${s} />`;
}

function projectHint(p) {
  if (!p) return "";
  if (!p.exists) return "A new folder: Extract creates it.";
  const d = p.details || {};
  if (d.archived) return "This project is archived: extracting into it is the hydrate — your edited files are set aside first and restored over the fresh extraction automatically.";
  if (d.baseline) return "Already holds an extract: extracting again overwrites your edits (after a confirmation). Use a fresh project folder per firmware version.";
  return "";
}

function Options({ s }) {
  const cats = s.categories || [];
  const showNaming = s.opt_transcribe || s.opt_music || s.opt_duration;
  const off = !s.autoname_enabled;
  const capturePrimary = s.capture_primary;
  return html`
    ${s.deltas_show ? html`<div class="stack x-sec">
        <span class="lbl">Optional: updates to merge on top</span>
        <div class="small dim x-pre">${s.deltas_help}</div>
        <div class="row wrap">
          <${Button} size="sm" icon="plus" onClick=${() => call("extract.add_deltas")}>Add updates...<//>
          <${Button} size="sm" onClick=${() => call("extract.clear_deltas")} disabled=${!(s.deltas || []).length}>Clear<//>
          <span class="small dim" title=${(s.deltas || []).join("\n")}>${s.deltas_summary}</span>
        </div>
      </div>` : null}
    ${s.asset_filters ? html`<div class="stack x-sec">
        <span class="lbl">Extract</span>
        <div class="row wrap x-checks">
          <${Check} ns="extract" k="graphics" checked=${s.graphics} label="Graphics" />
          <${Check} ns="extract" k="sounds" checked=${s.sounds} label="Sounds" />
          <${Check} ns="extract" k="filesystem" checked=${s.filesystem} label="File System" />
        </div>
      </div>` : null}
    ${s.dongle_cap ? html`<${Check} wrap ns="extract" k="dongle" checked=${s.dongle}
        label="Decrypt using the game's HASP dongle (advanced — for titles not yet supported dongle-free)" />` : null}
    ${s.capture_cap ? html`<div class="stack x-sec">
        <span class="lbl">Extract</span>
        ${capturePrimary ? null : html`<${Check} wrap ns="extract" k="static" checked=${s.static}
          label="Basic extract (raw ROM asset bitmaps + animation MP4s)" />`}
        <div class="row wrap x-checks">
          <${Check} wrap ns="extract" k="capture" checked=${s.capture}
            label="Use PinMAME runtime capture (composed cinematics + audio)" />
          <span class="row x-dur"><label class="small dim" for="x-dur">Duration (s):</label>
            <${Field} id="x-dur" ns="extract" k="capture_duration" value=${s.capture_duration} sm width=${72} /></span>
          ${capturePrimary ? null : html`<${Check} ns="extract" k="capture_gameplay" checked=${s.capture_gameplay} label="Simulate gameplay" />`}
        </div>
        ${s.capture_help ? html`<div class=${cx("x-help", s.capture_help_kind)}>${s.capture_help}</div>` : null}
      </div>` : null}
    ${s.decode_show ? html`<${Check} wrap ns="extract" k="decode_dmd" checked=${s.decode_dmd} label=${s.decode_label} />` : null}
    ${cats.length ? html`<div class="stack x-sec">
        <span class="lbl">Extract</span>
        <div class="row wrap x-checks">
          ${cats.map((c) => html`<${Check} ns="extract" k=${"cat_" + c.key} checked=${s["cat_" + c.key]} label=${c.label} title=${c.tip} />`)}
        </div>
      </div>` : null}
    ${showNaming ? html`<div class="stack x-sec">
        <span class="lbl">Naming</span>
        <div class="row wrap x-checks">
          ${s.opt_transcribe ? html`<${Check} ns="extract" k="transcribe" checked=${s.transcribe} disabled=${off} label="Auto-name call-outs" title=${TRANSCRIBE_TIP} />` : null}
          ${s.opt_music ? html`<${Check} ns="extract" k="music_id" checked=${s.music_id} disabled=${off} label="Auto-name music" title=${MUSIC_TIP} />` : null}
          ${s.opt_duration ? html`<${Check} ns="extract" k="duration_names" checked=${s.duration_names} disabled=${off} label="Length-prefix names" title=${DURATION_TIP} />` : null}
        </div>
      </div>` : null}`;
}

function RunButton({ s, shell }) {
  const running = !!shell.running;
  const mine = running && shell.run_mode === "extract";
  if (mine) {
    const cancelling = !!shell.cancelling;
    return html`<${Button} kind="danger" size="big" disabled=${cancelling} title=${cancelling ? "" : CANCEL_TIP}
        onClick=${() => call("extract.cancel")}>${cancelling ? "Cancelling…" : "Cancel"}<//>
      <span class="dim small grow">${cancelling ? "Stopping as soon as it's safe to." : CANCEL_TIP}</span>`;
  }
  const reason = running ? BUSY_TIP : (s.block_reason || "");
  return html`<${Button} kind="primary" size="big" icon="extract" disabled=${!!reason} title=${reason}
      onClick=${() => call("extract.start")}>Extract<//>
    ${reason ? html`<span class="dim small grow" role="note">${reason}</span>` : html`<span class="grow"></span>`}`;
}

function SourceCard({ s, shell }) {
  const hist = shell.path_history || {};
  const p = s.project;
  const hint = projectHint(p);
  return html`<${Card} cls="x-source" title="Source"
      extra=${s.direct ? html`<${Seg} value=${s.source} onChange=${(v) => call("extract.set_source", v)}
        options=${[{ value: "iso", label: s.iso_label }, { value: "ssd", label: s.ssd_label }]} />` : null}
      footer=${html`<${RunButton} s=${s} shell=${shell} />`}>
    <${SourceBody} s=${s} hist=${hist} />
    <div class="stack x-sec">
      <div class="row x-lblrow"><label class="lbl" for="x-proj" ...${tip(PROJECT_TIP)}>Project folder</label>
        <${InfoBadge} text=${PROJECT_INFO_TIP} onClick=${() => call("extract.open_project_info")} /></div>
      <${PathCombo} id="x-proj" k="output" value=${s.output} history=${hist.extract_output}
        onBrowse=${() => call("extract.browse_output")} browseTitle=${PROJECT_TIP} />
      ${hint ? html`<span class="small muted">${hint}</span>` : null}
    </div>
    <${Options} s=${s} />
  <//>`;
}

// ----------------------------------------------------- live DMD + matrix
function CaptureCard({ s, shell }) {
  const m = s.matrix;
  const running = !!shell.running;
  return html`<${Card} cls="x-capture" title="Live DMD (PinMAME)">
    <div class="x-dmd">
      ${s.dmd ? html`<img src=${s.dmd.src} alt="Live DMD frame" style=${`aspect-ratio:${s.dmd.w}/${s.dmd.h}`} />`
        : html`<span class="x-dmd-empty">${running ? "Waiting for the first frame…" : "Frames appear here while a PinMAME capture runs."}</span>`}
    </div>
    ${m ? html`<div class="stack x-matrix">
        <span class="lbl">${m.title}</span>
        ${(m.named || []).length ? html`<div class="x-mgrid">${m.named.map((b) => html`<${Button} size="xs" title=${b.tip}
            onClick=${() => call("extract.press_switch", b.sw, b.label)}>${b.text}<//>`)}</div>` : null}
        ${(m.unknown || []).length ? html`<div class="small dim x-msep">── Standard WPC playfield positions (not declared in this game's sim — try them to see what's wired here)</div>
          <div class="x-mgrid">${m.unknown.map((b) => html`<${Button} size="xs" title=${b.tip}
            onClick=${() => call("extract.press_switch", b.sw, b.label)}>${b.text}<//>`)}</div>` : null}
      </div>` : null}
  <//>`;
}

// ------------------------------------------------------ right column
// The project's own game (detected from the image it was extracted from),
// never what the input box above happens to hold.
export function projectGame(s) {
  const d = (s.project && s.project.details) || {};
  return d.game || "";
}

function ProjectCard({ s, shell }) {
  const p = s.project;
  const d = (p && p.details) || {};
  const tabs = (shell.tabs || []).filter((t) => t.visible);
  const has = (ns) => tabs.some((t) => t.ns === ns);
  const jumps = [["audio", "Replace audio"], ["video", "Replace video"], ["images", "Replace images"],
    ["text", "Replace text"], ["modes", "Modes"], ["write", "Write"]].filter(([ns]) => has(ns));
  const caption = projectGame(s);
  const head = html`<span class="h2">This project</span>
    ${p ? html`<${Chip} kind="acc" title=${p.folder}>${p.name}<//>` : null}
    ${d.archived ? html`<${Chip} kind="warn" sm>archived<//>` : null}
    <span class="sp"></span>
    ${p && p.exists ? html`<${Button} kind="ghost" size="sm" icon="refresh" title="Refresh" busy=${p.loading}
      onClick=${() => call("extract.refresh_project")} />` : null}`;
  let body;
  if (!p) {
    body = html`<div class="small muted">No project folder yet. Pick one on the left, or open a recent one from the project menu in the top bar. Extraction lands there, and every other tab works out of it.</div>`;
  } else if (!p.exists) {
    body = html`<div class="small muted">This folder doesn't exist yet; Extract creates it.</div>`;
  } else {
    const rows = p.rows || [];
    body = html`<div class="kv x-kv">
        ${caption ? html`<span class="k">Game</span><span>${caption}</span>` : null}
        ${d.extracted ? html`<span class="k">Extracted</span><span>${d.extracted}${d.source_name ? html` · from <span class="mono">${d.source_name}</span>` : null}</span>` : null}
        ${rows.map(([k, v]) => html`<span class="k">${k}</span><span class=${k === "Changed" && v !== "nothing changed yet" ? "acc-ink" : ""}>${v}</span>`)}
      </div>
      ${p.loading && !rows.length ? html`<div class="row small muted"><${Spinner} />Collecting…</div>` : null}
      <div class="note"><${Icon} name="info" /><div class="body-text">${PROJECT_TIP}</div></div>`;
  }
  return html`<${Card} cls="x-project" head=${head}
      footer=${html`${jumps.map(([ns, label]) => html`<${Button} size="sm" onClick=${() => call("ui.select_tab", ns)}>${label}<//>`)}
        <span class="grow"></span>
        <${Button} kind="ghost" size="sm" icon="folder" disabled=${!(p && p.exists)} onClick=${() => call("extract.open_project_folder")}>Open folder<//>`}>
    ${body}
  <//>`;
}

// ----------------------------------------------------------- windows
// Image Info and Project Info were Tk Toplevels with no grab: they sit
// beside the tab while you keep working (change the input, watch or cancel
// a run), and an i badge re-points the open one.  So they are floating
// windows here, not page modals: no scrim, dragged by the title bar,
// resized from the corner.  Where one was dragged to is remembered for this
// viewer (a convenience; the default spot works without it).
const floatSpot = {};
function loadSpot(id) {
  if (floatSpot[id]) return floatSpot[id];
  try {
    const v = JSON.parse(localStorage.getItem("pad.extract.float." + id) || "null");
    if (v && Number.isFinite(v.x) && Number.isFinite(v.y)) return v;
  } catch (e) { /* no storage: the default spot */ }
  return null;
}
function saveSpot(id, v) {
  floatSpot[id] = v;
  try { localStorage.setItem("pad.extract.float." + id, JSON.stringify(v)); } catch (e) { /* not kept */ }
}
// rendered px per CSS px (the app zooms <html>; event and rect coordinates
// are rendered, style.left / top are CSS)
function scaleOf(el) {
  const k = el && el.offsetWidth ? el.getBoundingClientRect().width / el.offsetWidth : 1;
  return Number.isFinite(k) && k > 0 ? k : 1;
}

const FLOAT_MIN_H = 180;
function FloatWin({ id, title, icon, onClose, children, footer, cls = "", dflt = 0 }) {
  const ref = useRef(null);
  const [spot, setSpot] = useState(() => loadSpot(id));
  const [vh, setVh] = useState(0);          // the viewport's height in CSS px
  const spotRef = useRef(spot);
  spotRef.current = spot;
  // keep it on screen (window resized or zoomed, or a spot remembered from
  // a bigger window); its height then ends above the viewport's bottom, so
  // the footer's buttons stay reachable wherever it is dragged
  const fit = () => {
    const el = ref.current;
    if (!el) return;
    const k = scaleOf(el);
    setVh(innerHeight / k);
    const cur = spotRef.current;
    if (!cur) return;
    const r = el.getBoundingClientRect();
    let dx = 0, dy = 0;
    if (r.width <= innerWidth - 16) {
      if (r.right > innerWidth - 8) dx = innerWidth - 8 - r.right;
      if (r.left + dx < 8) dx = 8 - r.left;
    } else dx = 8 - r.left;
    const maxTop = Math.max(8, innerHeight - FLOAT_MIN_H * k - 8);
    if (r.top > maxTop) dy = maxTop - r.top;
    if (r.top + dy < 8) dy = 8 - r.top;
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) setSpot({ x: cur.x + dx / k, y: cur.y + dy / k });
  };
  useLayoutEffect(fit, [spot]);
  useEffect(() => {
    window.addEventListener("resize", fit);
    if (ref.current) ref.current.focus({ preventScroll: true });
    return () => window.removeEventListener("resize", fit);
  }, []);
  const onDown = (e) => {
    if (e.button !== 0 || e.target.closest("button")) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const k = scaleOf(el);
    const start = { mx: e.clientX, my: e.clientY, x: r.left / k, y: r.top / k };
    let last = null;
    const move = (ev) => {
      last = { x: start.x + (ev.clientX - start.mx) / k, y: start.y + (ev.clientY - start.my) / k };
      setSpot(last);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (last) saveSpot(id, last);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    e.preventDefault();
  };
  const onKey = (e) => {
    if (e.key === "Escape" && !menuOpen()) { e.stopPropagation(); onClose(); }
  };
  // an object, not a string: a string would reset the size the user gave
  // it with the resize corner on every drag
  const top = spot ? spot.y : 96 + dflt;
  const style = {
    left: spot ? spot.x + "px" : "",
    right: spot ? "auto" : (24 + dflt) + "px",
    top: top + "px",
    maxHeight: vh ? Math.max(FLOAT_MIN_H, vh - top - 16) + "px" : "",
  };
  return html`<div class=${cx("x-float", cls)} ref=${ref} role="dialog" aria-modal="false" aria-label=${title}
      tabindex="-1" style=${style} onKeyDown=${onKey}>
    <div class="hd" onPointerDown=${onDown}>${icon ? html`<${Icon} name=${icon} cls="lg" />` : null}<span class="h2">${title}</span>
      <${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${onClose} /></div>
    <div class="bd">${children}</div>
    ${footer ? html`<div class="ft">${footer}</div>` : null}
  </div>`;
}

function ImageInfo({ info }) {
  const sections = info.sections || [];
  const close = () => call("extract.info_close");
  return html`<${FloatWin} id="info" title="Image Info" icon="info" cls="x-info" onClose=${close}
      footer=${html`<${Button} icon="refresh" onClick=${() => call("extract.info_refresh")}>Refresh<//>
        <${Button} icon="copy" disabled=${!sections.length || info.loading} onClick=${() => call("extract.info_copy")}>Copy Report<//>
        <span class="small dim grow">${info.loading ? "" : info.status}</span>
        <${Button} kind="primary" onClick=${close}>Close<//>`}>
    <div class="mono small dim x-wrapany">${info.path}</div>
    ${info.loading ? html`<div class="x-loading"><${Spinner} /><span>Reading image…</span></div>` : null}
    ${sections.map((sec) => html`<section class="x-isec">
        <div class="h2 x-isec-t">${sec.title}</div>
        <div class="kv x-ikv">${sec.rows.map(([k, v]) => html`<span class="k">${k}</span><span class="x-wrapany">${v}</span>`)}</div>
      </section>`)}
  <//>`;
}

function ProjectInfo({ s }) {
  const p = s.project || {};
  const close = () => call("extract.close_project_info");
  return html`<${FloatWin} id="pinfo" title="Project Info" icon="folder" cls="x-pinfo" dflt=${32} onClose=${close}
      footer=${html`<span class="grow"></span><${Button} kind="primary" onClick=${close}>Close<//>`}>
    <div class="x-wrapany"><b>${p.folder}</b></div>
    ${p.loading && !(p.rows || []).length ? html`<div class="row small muted"><${Spinner} />Collecting…</div>` : null}
    <div class="kv x-kv">${(p.rows || []).map(([k, v]) => html`<span class="k">${k}:</span><span>${v}</span>`)}</div>
  <//>`;
}

function ReadCard({ s }) {
  const rc = s.rc;
  const noun = rc.noun || "SD card";
  const opts = (rc.drives || []).length ? rc.drives.map((d) => ({ value: d, label: d }))
    : [{ value: rc.drive || "", label: rc.drive || "" }];
  const cancel = () => call("extract.rc_cancel");
  return html`<${Modal} title=${"Save " + noun + " to an image file"} icon="sd" wide onClose=${cancel}
      footer=${html`<${Button} kind="danger" onClick=${cancel}>Cancel<//><${Button} kind="primary" onClick=${() => call("extract.rc_start")}>Start<//>`}>
    <div class="h2">Save the ${noun} to a .raw image file</div>
    <div class="small dim">Copies the whole card, sector for sector, into one file — a backup you can flash back later, open on the Partitions tab, or compare against another image. The card itself is only read from; nothing on it changes.</div>
    <div class="x-rcgrid">
      <label class="lbl" for="x-rc-drive">Read from:</label>
      <div class="row"><${Select} id="x-rc-drive" cls="grow" value=${rc.drive} options=${opts} disabled=${rc.detecting || !(rc.drives || []).length}
          onChange=${(v) => call("extract.rc_select", v)} />
        <${Button} icon="refresh" onClick=${() => call("extract.rc_refresh")}>Refresh<//></div>
      <label class="lbl" for="x-rc-img">Save to:</label>
      <div class="row"><${Field} id="x-rc-img" ns="extract" k="rc_image" value=${s.rc_image} mono cls="grow" />
        <${Button} onClick=${() => call("extract.rc_browse")}>Browse…<//></div>
    </div>
    ${rc.detecting ? html`<div class="row small muted"><${Spinner} />Detecting drives…</div>` : null}
    ${rc.readout ? html`<div class=${cx("small x-readout", rc.readout_kind === "err" && "err-ink", rc.readout_kind === "ok" && "ok-ink", !rc.readout_kind && "dim")}>${rc.readout}</div>` : null}
    <div class="small muted">An image is the size of the WHOLE card, empty space included — an 8 GB card makes an 8 GB file, however little is on it.</div>
    ${rc.admin_note ? html`<div class="small muted">${rc.admin_note}</div>` : null}
  <//>`;
}

// ------------------------------------------------------------- the tab
export default function ExtractTab() {
  const s = useNs("extract");
  const shell = useNs("shell");
  // A file dropped anywhere but the drop zone must not navigate the window.
  useEffect(() => {
    const stop = (e) => { if (!e.defaultPrevented) e.preventDefault(); };
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  }, []);
  const tabs = (shell.tabs || []).filter((t) => t.visible);
  const editable = tabs.some((t) => t.group === "Replace");
  const sub = "Open " + inputPhrase(s.input_label) + (s.direct ? " or the " + (s.drive_label === "Game SSD" ? "game SSD" : s.drive_label) : "")
    + ", and the game's assets land in a project folder" + (editable ? " you can edit on the Replace tabs." : ".");
  const info = s.info && s.info.open ? s.info : null;
  return html`<div class="page x-page">
    <${PageHead} title="Extract" sub=${sub} />
    <div class="cols c75 x-cols">
      <div class="stack x-col">
        <${SourceCard} s=${s} shell=${shell} />
        ${s.capture_cap && (s.capture || s.dmd || s.matrix) ? html`<${CaptureCard} s=${s} shell=${shell} />` : null}
      </div>
      <div class="stack x-col">
        <${ProjectCard} s=${s} shell=${shell} />
      </div>
    </div>
    ${info ? html`<${ImageInfo} info=${info} />` : null}
    ${s.pinfo ? html`<${ProjectInfo} s=${s} />` : null}
    ${s.rc && s.rc.open ? html`<${ReadCard} s=${s} />` : null}
  </div>`;
}
