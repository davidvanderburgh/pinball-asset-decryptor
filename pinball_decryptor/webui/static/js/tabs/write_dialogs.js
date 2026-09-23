// The Write tab's windows as page dialogs: Build / flash (gui/flash_dialog.py),
// Card diagnostics (gui/diagnose_dialog.py) and Image Info.  Their state and
// every check live in Python (webui/write_dialogs.py); these only draw it
// and send the edits back.

import { html, useRef, useEffect, useLayoutEffect, Modal, Button, Field, Select, Check, Radio, Spinner, call, cx }
  from "../core/ui.js";
import { useNs } from "../core/store.js";

// The Build / flash dialog over ANY tab.  Tk opened it over whatever tab was
// showing (the Multi-boot tab hands its card in from its own page), so the
// shell renders <WriteOverlays /> beside the Fonts / Scenes windows; it
// tells Python so nothing switches tabs.  Until the shell renders it, the
// Write page draws the dialog itself (flashDialogHosted() is false).
let hosted = false;
export function flashDialogHosted() { return hosted; }
const CSS_HREF = "/static/css/tabs/write.css";
export function WriteOverlays() {
  const s = useNs("write");
  hosted = true;
  useEffect(() => {
    if (typeof document !== "undefined" && !document.querySelector(`link[href="${CSS_HREF}"]`)) {
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = CSS_HREF;
      document.head.appendChild(l);
    }
    call("write.flash_host_ready");
  }, []);
  return s.flash_dlg ? html`<${FlashDialog} f=${s.flash_dlg} />` : null;
}

// Tk's Build / flash and Card diagnostics windows were grabbed modals: only
// their buttons, the window's close box or Escape closed them.  A click on
// the dimmed backdrop must not throw the dialog (and every edit in it) away,
// so the backdrop's mousedown stops here, before the Modal's scrim sees it.
function keepOnBackdrop(e) {
  const t = e.target;
  if (t && t.classList && t.classList.contains("scrim")) e.stopPropagation();
}

// While a question from Python is up (the dialog host's modal sits above
// this one), Escape and the scrim belong to the question, not to us.
function useCloser(fn) {
  const modals = useNs("modals");
  const busy = (modals.open || []).length > 0;
  return busy ? undefined : fn;
}

// Text boxes send after a pause, and at once on Enter / leaving the box.
function useDebounced(method, key) {
  const t = useRef(null);
  const send = (v, now) => {
    if (t.current) clearTimeout(t.current);
    if (now) call(method, key, v);
    else t.current = setTimeout(() => call(method, key, v), 300);
  };
  return { onChange: (v) => send(v, false), onCommit: (v) => send(v, true) };
}

function driveOptions(drives, text) {
  if (!drives || !drives.length) return [{ value: "", label: text || "" }];
  const opts = drives.map((d) => ({ value: String(d.i), label: d.display }));
  return opts;
}

// ------------------------------------------------------------ Build / flash
export function FlashDialog({ f }) {
  const close = useCloser(() => call("write.flash_close"));
  const buildPath = useDebounced("write.flash_set", "build_path");
  const imagePath = useDebounced("write.flash_set", "image_path");
  const fromPath = useDebounced("write.flash_set", "from_path");
  const set = (k, v) => call("write.flash_set", k, v);
  const drives = f.drives || [];
  const opts = driveOptions(drives, f.drive_text);
  const noSel = drives.length && (f.drive === null || f.drive === undefined);
  const driveOpts = noSel ? [{ value: "", label: f.drive_text || "—" }, ...opts] : opts;
  const kindCls = f.readout_kind === "err" ? "err-ink" : f.readout_kind === "ok" ? "ok-ink" : "muted";
  const footer = html`
    <${Button} kind="danger" onClick=${() => call("write.flash_close")}>Cancel<//>
    <${Button} kind="primary" disabled=${!f.start_enabled} onClick=${() => call("write.flash_start")}>${f.start_label}<//>`;
  return html`<div class="wr-modal-host" onMouseDownCapture=${keepOnBackdrop}><${Modal} title=${f.title} icon="sd" wide onClose=${close} footer=${footer} cls="wr-flash">
    <div class="stack" style="gap:2px">
      <div class="h2">${f.header}</div>
      <div class="small muted">${f.intro}</div>
    </div>
    ${!f.handed_in ? html`<section class="wr-sec">
      <${Check} checked=${f.build} disabled=${!f.can_build} label="Build a fresh image from your modifications"
        onChange=${(v) => set("build", v)} />
      ${f.cannot_build_reason ? html`<div class="small muted wr-ind">${f.cannot_build_reason}</div>` : null}
      <div class="wr-frow wr-ind">
        <span class="lbl">Build to:</span>
        <${Field} value=${f.build_path} mono cls="grow" disabled=${!f.building} ...${buildPath} />
        <${Button} disabled=${!f.building} onClick=${() => call("write.flash_browse", "build")}>Browse…<//>
      </div>
    </section>` : null}
    <section class="wr-sec">
      ${!f.handed_in ? html`<${Check} checked=${f.write} label=${f.section} onChange=${(v) => set("write", v)} />` : null}
      <div class=${cx("stack", !f.handed_in && "wr-ind")} style="gap:8px">
        <div class="wr-frow">
          <span class="lbl">Image file:</span>
          <${Field} value=${f.image_path} mono cls="grow" disabled=${!f.image_enabled} ...${imagePath} />
          <${Button} disabled=${!f.image_enabled} onClick=${() => call("write.flash_browse", "image")}>Browse…<//>
        </div>
        ${f.targets && f.targets.length ? html`<div class="wr-frow top">
          <span class="lbl">Onto:</span>
          <div class="stack" style="gap:0">
            ${f.targets.map((t) => html`<${Radio} name="wr-onto" value=${t.key} label=${t.label}
              checked=${f.target === t.key} disabled=${!f.write} onChange=${(v) => set("target", v)} />`)}
          </div>
        </div>` : null}
        ${f.show_disk_mode ? html`<div class="wr-frow">
          <span class="lbl">Write:</span>
          <${Select} value=${f.disk_mode} options=${f.disk_modes} cls="grow" onChange=${(v) => set("disk_mode", v)} />
        </div>` : null}
        ${f.show_from ? html`<div class="wr-frow">
          <span class="lbl">From ISO:</span>
          <${Field} value=${f.from_path} mono cls="grow" ...${fromPath} />
          <${Button} onClick=${() => call("write.flash_browse", "from")}>Browse…<//>
        </div>` : null}
        ${f.menu_offered ? html`<div class="stack" style="gap:2px">
          <${Check} checked=${f.menu} disabled=${!f.menu_enabled}
            label="Only the boot menu — fast, and the machine keeps its settings and scores"
            onChange=${(v) => set("menu", v)} />
          ${f.menu_note ? html`<div class="small muted wr-ind">${f.menu_note}</div>` : null}
        </div>` : null}
        <div class="wr-frow">
          <span class="lbl">${f.target_label}</span>
          <${Select} value=${f.drive === null || f.drive === undefined ? "" : String(f.drive)} options=${driveOpts}
            cls="grow" disabled=${!f.drives_enabled || !drives.length} onChange=${(v) => set("drive", v === "" ? -1 : Number(v))} />
          <${Button} disabled=${!f.drives_enabled} onClick=${() => call("write.flash_refresh_drives")}>Refresh<//>
        </div>
      </div>
    </section>
    ${f.readout ? html`<div class=${cx("small wr-readout", kindCls)}>${f.readout}</div>` : null}
    ${f.safety ? html`<div class="small err-ink">${f.safety}</div>` : null}
    ${f.unc_note ? html`<div class="small muted">${f.unc_note}</div>` : null}
    ${f.admin_note ? html`<div class="small muted">${f.admin_note}</div>` : null}
  <//></div>`;
}

// ------------------------------------------------------- Card diagnostics
export function DiagDialog({ d }) {
  const close = useCloser(() => call("write.diag_close"));
  // the streamed report follows its tail while the view is at the end, and
  // keeps the user's place once they scroll back (Tk DiagnoseCardDialog
  // ._append: at_end, then see("end"))
  const pre = useRef(null);
  const atEnd = useRef(true);
  const onScroll = () => {
    const el = pre.current;
    if (el) atEnd.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
  };
  useLayoutEffect(() => {
    const el = pre.current;
    if (el && atEnd.current) el.scrollTop = el.scrollHeight;
  }, [d.text]);
  const drives = d.drives || [];
  const opts = driveOptions(drives, d.drive_text);
  const footer = html`
    <${Button} disabled=${!d.can_save} onClick=${() => call("write.diag_save")}>Save report…<//>
    <${Button} onClick=${() => call("write.diag_close")}>Close<//>`;
  return html`<div class="wr-modal-host" onMouseDownCapture=${keepOnBackdrop}><${Modal} title="Card diagnostics" icon="sd" xwide onClose=${close} footer=${footer} cls="wr-diag">
    <div class="stack" style="gap:2px">
      <div class="h2">${d.header}</div>
      <div class="small muted wrap">${d.help}</div>
    </div>
    <div class="wr-frow">
      <span class="lbl">Card:</span>
      <${Select} value=${d.drive === null || d.drive === undefined ? "" : String(d.drive)} options=${opts} cls="grow"
        disabled=${!drives.length || d.running} onChange=${(v) => call("write.diag_select", Number(v))} />
      <${Button} disabled=${d.running} onClick=${() => call("write.diag_refresh")}>Refresh<//>
      <${Button} disabled=${d.running} onClick=${() => call("write.diag_read")}>Read card<//>
      <${Button} disabled=${d.running} onClick=${() => call("write.diag_read_file")}>Image file…<//>
    </div>
    ${d.admin_warn ? html`<div class="small err-ink">${d.admin_warn}</div>` : null}
    <pre class="wr-report mono" ref=${pre} onScroll=${onScroll}>${d.running && !d.text ? "…" : d.text}</pre>
  <//></div>`;
}

// ------------------------------------------------------------- Image Info
export function InfoDialog({ info }) {
  const close = useCloser(() => call("write.image_info_close"));
  const copy = async () => {
    const text = await call("write.image_info_copy");
    if (text && navigator.clipboard) {
      try { await navigator.clipboard.writeText(text); } catch (_e) { /* the app copied it too */ }
    }
  };
  const footer = html`
    <${Button} onClick=${() => call("write.image_info_refresh")}>Refresh<//>
    <${Button} disabled=${!(info.sections || []).length} onClick=${copy}>Copy Report<//>
    <span class="small muted grow">${info.busy ? "" : info.status}</span>
    <${Button} onClick=${() => call("write.image_info_close")}>Close<//>`;
  return html`<${Modal} title="Image Info" icon="info" wide onClose=${close} footer=${footer} cls="wr-infodlg">
    <div class="mono small dim wr-path">${info.path}</div>
    ${info.busy
      ? html`<div class="wr-scan" role="status"><${Spinner} /><div class="msg">Reading image…</div></div>`
      : html`<div class="wr-info-list">
        ${(info.sections || []).map((sec) => html`<div class="wr-info-sec">
          <div class="wr-info-hd">${sec.title}</div>
          ${(sec.rows || []).map((r) => html`<div class="wr-info-row"><span class="k">${r[0]}</span><span class="v">${r[1]}</span></div>`)}
        </div>`)}
      </div>`}
  <//>`;
}
