// Write tab: build an image from the project, write the changes straight
// onto the card (direct_ssd plugins), or build and/or flash through the
// Build / flash dialog (flash_image plugins).  Python half:
// webui/tabs/write.py; the dialogs: ./write_dialogs.js.  Wording is the Tk
// tab's (gui/main_window.py _build_write_tab and its methods).

import { html, useState, useEffect, PageHead, Card, Button, Field, Select, Seg, Check, Chip, Note, Table, Empty,
         Icon, InfoBadge, tip, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { FlashDialog, DiagDialog, InfoDialog, flashDialogHosted } from "./write_dialogs.js";

export const css = true;

const T = {
  legend: "Pending = staged this session, applied when you Build · Modified = file on disk already differs from the extract",
  origTip: "The master card image — it is set on the Extract tab.",
  projTip: "Shared by every tab — it is set on the Extract tab. Click to open it.",
  cancelTip: "Cancel the operation in progress — it stops as soon as it's safe to.",
  busyTip: "Another operation is running — cancel it or let it finish first.",
  infoTip: "Technical details about this image",
};

const plural = (n, one, many) => (n === 1 ? one : many);
const unwarn = (text) => (text || "").replace(/^⚠\s*/, "");

// What Build makes comes from the plugin: the flash plugins build a whole
// image, the others an update package (their button reads "Build update").
function subtitle(s) {
  const tail = " The original is never touched.";
  const what = "Build " + (s.build_noun || "an image") + " from this project";
  if (s.direct) return what + ", or write your changes straight onto the " + (s.medium || "card") + "." + tail;
  return what + "." + tail;
}

// A Modified Files row's first cell: a mode line reads "NAME: what a build
// adds" (bold name), a text edit is plain words, a file is a path.
function FileCell({ r }) {
  if (r.type === "mode") {
    const at = r.file.indexOf(": ");
    const dash = r.file.indexOf(" — ");
    const cut = at > 0 && (dash < 0 || at < dash) ? at : dash;
    if (cut > 0) {
      return html`<span class="wr-file"><b>${r.file.slice(0, cut)}</b><span class="dim">${r.file.slice(cut)}</span></span>`;
    }
    return html`<span class="wr-file">${r.file}</span>`;
  }
  if (r.type === "text" || r.type === "setting" || r.type === "program") return html`<span class="wr-file">${r.file}</span>`;
  return html`<span class="wr-file mono">${r.file}</span>`;
}

function StatusChip({ r }) {
  const pending = r.tag === "pending";
  return html`<span class=${cx("chip sm wr-chip", pending ? "warn" : "info")}><span class="dot"></span>${r.status}</span>`;
}

// The columns the user drags keep their width (Tk saved them in
// settings.json, column_widths.write_preview).  A dragged File width is a
// ceiling it gives way from, so Status never drops below its minimum; Status
// (the last column) takes whatever is left.
function columns(w) {
  return [
    { key: "file", label: "File", sort: "file", width: w.file ? `minmax(120px,${w.file}px)` : "minmax(0,3fr)",
      render: (r) => html`<${FileCell} r=${r} />`, titleOf: (r) => r.file },
    { key: "type", label: "Type", sort: "type", width: w.type ? `${Math.max(40, w.type)}px` : "72px" },
    { key: "status", label: "Status", sort: "status", width: "minmax(170px,2fr)",
      render: (r) => html`<${StatusChip} r=${r} />`, titleOf: (r) => r.status, cls: "wr-status" },
  ];
}

function ModifiedFiles({ s }) {
  const rows = s.rows || [];
  const scanning = !!s.scanning;
  // the widths just dragged, until the saved ones come back from Python
  const saved = s.widths || {};
  const savedKey = JSON.stringify(saved);
  const [dragged, setDragged] = useState(null);
  useEffect(() => { setDragged(null); }, [savedKey]);
  const onResize = (w) => { setDragged(w); call("write.save_widths", w); };
  const extra = html`<${Button} kind="ghost" size="sm" icon=${scanning ? "x" : "refresh"}
      disabled=${!!s.refresh_disabled && !scanning} onClick=${() => call("write.refresh")}
      title=${s.running && !scanning ? T.busyTip : undefined}>${scanning ? "Cancel scan" : "Refresh"}<//>`;
  const head = html`<span class="h2">Modified Files</span><span class="muted small wr-legend">${T.legend}</span><span class="sp"></span>${extra}`;
  const count = s.count || 0;
  const modes = s.direct && rows.some((r) => r.type === "mode")
    ? " · modes go on an image build and are left out of a direct " + (s.medium === "SD card" || !s.medium ? "SD" : s.medium) + " write"
    : "";
  const footer = count
    ? html`<span class="small muted">Total changes: ${count} · click a column header to sort${modes}</span>`
    : null;
  return html`<${Card} cls="wr-files" head=${head} bodyCls="flush wr-files-bd" footer=${footer}>
    ${scanning
      ? html`<div class="wr-scan" role="status"><span class="spin"></span><div class="msg">${s.scan_msg || "Scanning for modified files…"}</div></div>`
      : html`<${Table} columns=${columns(dragged || saved)} rows=${rows} rowKey=${(r, i) => i + ":" + r.file}
          sort=${s.sort || null} onSort=${(k) => call("write.sort", k)} resizable onResize=${onResize}
          rowClass=${(r) => (r.tag === "pending" ? "wr-pending" : "wr-modified")}
          empty=${html`<${Empty} icon=${s.empty && s.empty.startsWith("Scan paused") ? "pause" : "list"}>${s.empty || ""}<//>`} />`}
  <//>`;
}

function PrimaryButton({ s }) {
  if (!s.write_cap) return null;
  if (s.cancel) {
    return html`<${Button} kind="danger solid" size="big" icon="stop" title=${T.cancelTip}
      onClick=${() => call("write.primary")}>Cancel<//>`;
  }
  const label = s.primary_label || (s.flash ? s.flash_label : "Build update");
  return html`<${Button} kind="primary" size="big" icon=${s.flash ? "sd" : "write"}
    disabled=${!!s.primary_disabled}
    title=${s.running ? T.busyTip : s.flash ? s.flash_tip : undefined}
    onClick=${() => call("write.primary")}>${label}<//>`;
}

function primaryNote(s) {
  if (s.cancel) return T.cancelTip;
  if (s.flash) return "One dialog: build an image, write it onto the " + (s.flash_noun || "card") + ", or both. It reads Cancel while it runs.";
  if (s.primary_disabled && !s.running && s.direct_mode && s.show_admin) return "Administrator privileges are required to write the " + (s.medium || "SSD") + " directly — see the warning above.";
  return "";
}

function DriveRow({ s }) {
  const drives = s.drives || [];
  const opts = drives.length
    ? drives.map((d) => ({ value: d, label: d }))
    : [{ value: s.drive_display || "", label: s.drive_text || s.drive_display || "" }];
  return html`<div class="row wr-drive">
    <${Select} ns="write" k="drive_display" value=${s.drive_display} options=${opts} cls="grow"
      disabled=${!drives.length || s.running} />
    <${Button} onClick=${() => call("write.refresh_drives")} disabled=${s.running}>Refresh<//>
  </div>`;
}

// The Original path with its ⓘ kept on the line of the path's last
// characters (the path itself may wrap anywhere before them).
function OriginalPath({ s }) {
  const p = s.upd || "";
  if (!p) return html`<span class="wr-orig"><span class="mono small muted">—</span></span>`;
  const cut = Math.max(0, p.length - 8);
  return html`<span class="wr-orig"><span class="mono small wr-path" ...${tip(T.origTip)}>${p.slice(0, cut)}</span><span class="wr-tail"><span class="mono small" ...${tip(T.origTip)}>${p.slice(cut)}</span><span class="wr-info"><${InfoBadge}
      text=${T.infoTip} onClick=${() => call("write.image_info")} /></span></span></span>`;
}

// Direct mode's notes sit right under the Game SSD row, as Tk packed them:
// the red safety line, the Administrator panel (Windows, not elevated), the
// Full Disk Access panel (macOS) and the network-drive hint (elevated).
function DirectNotes({ s }) {
  const out = [];
  if (s.safety) out.push(html`<div class="wr-wide"><${Note} kind="err" icon="warn">${unwarn(s.safety)}<//></div>`);
  if (s.show_admin) {
    out.push(html`<div class="wr-wide"><div class="note err wr-panel">
      <${Icon} name="lock" />
      <div class="body-text">
        <button type="button" class="wr-panel-hd" onClick=${() => call("write.toggle_admin_warning")}
          aria-expanded=${!s.admin_collapsed}>
          <b>${unwarn(s.admin_title)}</b><span class="muted">${s.admin_collapsed ? "▼" : "▲"}</span>
        </button>
        ${s.admin_collapsed ? null : html`<div class="wr-panel-bd">${s.admin_body}</div>`}
      </div></div></div>`);
  }
  if (s.show_fda) {
    out.push(html`<div class="wr-wide"><div class="note err wr-panel">
      <${Icon} name="lock" />
      <div class="body-text">
        <div class="row"><b class="grow">${unwarn(s.fda_title)}</b>
          <${Button} kind="ghost" size="xs" onClick=${() => call("write.dismiss_fda")}>Hide this notice ✕<//></div>
        <div class="wr-panel-bd">${s.fda_text}</div>
      </div></div></div>`);
  }
  if (s.show_unc) out.push(html`<div class="wr-wide"><${Note} kind="warn">${s.unc_hint}<//></div>`);
  return out;
}

function Destination({ s }) {
  const direct = !!s.direct_mode;
  const head = html`<span class="h2">Destination</span><span class="sp"></span>
    ${s.direct ? html`<${Seg} value=${s.source} disabled=${s.running}
      options=${[{ value: "iso", label: s.iso_label, title: s.iso_tip }, { value: "ssd", label: s.ssd_label, title: s.ssd_tip }]}
      onChange=${(v) => call("write.set_source", v)} />` : null}`;
  const note = primaryNote(s);
  const footer = html`<${PrimaryButton} s=${s} />
    ${note ? html`<span class="dim small grow wr-note">${note}</span>` : html`<span class="grow"></span>`}
    ${s.diagnose ? html`<${Button} onClick=${() => call("write.diag_open")} disabled=${s.running}>Card diagnostics…<//>` : null}`;
  return html`<${Card} head=${head} bodyCls="wr-dest" footer=${footer}>
    <div class="kv wr-kv">
      ${!direct ? html`
        <span class="k">${s.original_label}</span>
        <${OriginalPath} s=${s} />
        ${s.badge_shown ? html`<span class="k"></span>
          ${s.badge_switch
            ? html`<button type="button" class="wr-badge wr-badge-link" onClick=${() => call("write.switch_suggested")}>${s.badge}</button>`
            : html`<span class="wr-badge">${s.badge}</span>`}` : null}` : null}
      <span class="k">Project Folder</span>
      ${s.project_set
        ? html`<button type="button" class="wr-link" onClick=${() => call("write.open_project")} ...${tip(T.projTip)}>${s.project}</button>`
        : html`<span class="muted small">${s.project}</span>`}
      ${s.assets_warning ? html`<span class="k"></span>
        <div class="wr-under"><${Note} kind="err" icon="warn">${unwarn(s.assets_warning)}<//></div>` : null}
      ${s.editable_hint ? html`<span class="k"></span><span class="small muted wr-hint">${s.editable_hint}</span>` : null}
      ${direct ? html`<span class="k">Game SSD</span><${DriveRow} s=${s} /><${DirectNotes} s=${s} />` : null}
      ${s.version_cap ? html`<span class="k">Update version</span>
        <div class="stack wr-version">
          <div class="row">
            <${Check} ns="write" k="version_auto" checked=${s.version_auto} label="Auto" disabled=${s.running} />
            <${Field} ns="write" k="version_date" value=${s.version_date} mono readOnly=${!!s.version_auto} width=${130} />
          </div>
          ${s.version_hint ? html`<span class="small muted">${s.version_hint}</span>` : null}
        </div>` : null}
    </div>
    ${!direct ? html`<div class="stack wr-build">
      <label class="lbl" for="wr-out">Build Image</label>
      <div class="row">
        <div id="wr-out" class=${cx("field mono ro grow wr-buildpath", !s.build_path && "muted")} role="textbox" aria-readonly="true"
          aria-label="Build Image">${s.build_path || "—"}</div>
        <${Button} onClick=${() => call("write.change_build_location")} disabled=${s.running}>Change...<//>
      </div>
      ${s.filename_hint ? html`<span class=${cx("small", s.filename_hint_kind === "err" ? "err-ink" : "muted")}>${s.filename_hint}</span>` : null}
    </div>` : null}
    ${s.text_grow_cap ? html`<${Check} ns="write" k="text_grow" checked=${s.text_grow} wrap
        label=${s.text_grow_label} title=${s.text_grow_tip} disabled=${s.running} />` : null}
  <//>`;
}

// The design's "Before you build": what the run logic and the Replace tabs
// already find wrong before a build (a clip the machine can't play,
// assignments made for another folder, files this extract never produced).
function BeforeYouBuild({ s }) {
  const notes = s.prebuild || [];
  if (!notes.length) return null;
  return html`<${Card} title="Before you build" bodyCls="wr-notes">
    ${notes.map((n) => html`<${Note} kind=${n.kind || ""} icon=${n.kind === "err" ? "warn" : undefined}>${n.text}<//>`)}
  <//>`;
}

export default function WriteTab() {
  const s = useNs("write");
  const count = s.count || 0;
  return html`<div class="page wr-page">
    <${PageHead} title="Write" sub=${subtitle(s)}>
      ${count ? html`<${Chip} kind="acc">${count} ${plural(count, "change", "changes")} for the next build<//>` : null}
      <${Button} kind="ghost" onClick=${() => call("write.export_csv")} title=${s.export_tip}>Export CSV<//>
      ${s.revert_cap ? html`<${Button} kind="danger" disabled=${!s.revert_enabled}
        onClick=${() => call("write.revert_all")}>Revert all changes…<//>` : null}
    <//>
    <div class="wr-body"><div class="wr-cols">
      <div class="wr-left">
        <${Destination} s=${s} />
        <${BeforeYouBuild} s=${s} />
        ${s.delta_cap ? html`<${Card} title="Optional: Apply Delta on Top">
          <span class="small dim">${s.delta_text}</span>
          <div><${Button} onClick=${() => call("write.apply_delta")} disabled=${s.running}>Apply Delta...<//></div>
        <//>` : null}
        ${s.install_help ? html`<${Card} title="How to Install"><div class="small dim wrap wr-install">${s.install_help}</div><//>` : null}
      </div>
      <${ModifiedFiles} s=${s} />
    </div></div>
    ${s.flash_dlg && !s.flash_hosted && !flashDialogHosted() ? html`<${FlashDialog} f=${s.flash_dlg} />` : null}
    ${s.diag ? html`<${DiagDialog} d=${s.diag} />` : null}
    ${s.info ? html`<${InfoDialog} info=${s.info} />` : null}
  </div>`;
}
