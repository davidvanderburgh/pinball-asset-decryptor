// The app-wide windows (service ns "shellx"): Tips, Preview features, the
// disclaimer, Manage disk space, and the Project menu's windows (New
// project, Save as (fork), Properties, Change history, Projects, Relink
// moved files).  Python opens them with bus.publish("open_dialog", name=...);
// the menus in shell.js open them too.  State-driven windows (a project
// copy's progress, the update download) are ShellxOverlays, which shell.js
// renders once.
//
// Wording is the Tk windows' (gui/projects_ui.py, help_dialog.py,
// preview_dialog.py, disk_dialog.py, disclaimer.py).

import { html, useEffect, useRef, useState, Modal, Button, Field, Select, Icon, Note, Table,
         Progress, Spinner, cx, tip, menuOpen } from "./core/ui.js";
import { useNs, useEvent } from "./core/store.js";
import { call } from "./core/rpc.js";
import { registerDialog, openDialog } from "./core/dialogs.js";

// ------------------------------------------------------------ helpers
// Escape closes only the window on TOP, as in Tk, where each window had its
// own Escape binding and a message box was its window's child.  Core Modal
// calls onClose() with no argument for Escape (and for a click on its own
// scrim, which only the top one can get) and with the click for its ✕, and
// every open Modal hears the key (core request 9).  useWin gives a window a
// class to find it by and an onClose that ignores an Escape meant for a
// window above it: a nested window, a message box, a file picker.
let winSeq = 0;
function isTop(uid) {
  const mine = document.querySelector("." + uid);
  const scrims = document.querySelectorAll(".scrim");
  return !mine || !scrims.length || mine.closest(".scrim") === scrims[scrims.length - 1];
}
function useWin(close) {
  const [uid] = useState(() => "sxw" + (++winSeq));
  const onClose = (e) => { if (!e && !isTop(uid)) return; close(); };
  return [uid, onClose];
}

// Enter inside a text field runs `fn(value)` (Tk bound <Return> on the
// entry); Field's own onCommit also fires on blur, which must not.
const onEnter = (fn) => (e) => {
  if (e.key !== "Enter" || e.isComposing || !e.target || e.target.tagName !== "INPUT") return;
  e.preventDefault();
  fn(e.target.value);
};

// A free-floating window: Tk's plain Toplevel with no grab (the Projects
// and Relink windows).  No scrim, so the app stays usable behind it; drag it
// by its title bar, resize it from its corner; Escape closes it while focus
// is in it and no modal window is up.
function FloatWin({ title, icon, onClose, children, footer, cls = "" }) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);
  useEffect(() => {
    if (ref.current) ref.current.focus();
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented || menuOpen()) return;
      if (document.querySelector(".scrim")) return;
      if (!ref.current || !ref.current.contains(document.activeElement)) return;
      e.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, []);
  const drag = (e) => {
    if (e.button !== 0 || (e.target.closest && e.target.closest("button, input, select, textarea"))) return;
    const el = ref.current;
    if (!el) return;
    e.preventDefault();
    const r = el.getBoundingClientRect();
    const f = el.offsetWidth / (r.width || 1);            // CSS px per client px (zoom)
    const x0 = e.clientX, y0 = e.clientY;
    const move = (ev) => {
      const left = Math.max(80 - r.width, Math.min(window.innerWidth - 80, r.left + ev.clientX - x0));
      const top = Math.max(0, Math.min(window.innerHeight - 40, r.top + ev.clientY - y0));
      setPos({ left: left * f, top: top * f });
    };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  return html`<section class=${cx("sx-float", pos && "moved", cls)} ref=${ref} tabindex="-1" role="dialog" aria-modal="false" aria-label=${title}
      style=${pos ? `left:${pos.left}px;top:${pos.top}px` : undefined}>
    <div class="hd" onMouseDown=${drag}>${icon ? html`<${Icon} name=${icon} cls="lg" />` : null}<span class="h2">${title}</span>
      <${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${onClose} /></div>
    <div class="bd">${children}</div>
    ${footer ? html`<div class="ft">${footer}</div>` : null}
  </section>`;
}
const openNow = new Set();
// Tk's manager / relink / tips windows are single per app: a second open
// raises the first instead of stacking another.
function useSingleton(name, close) {
  const [dup] = useState(() => openNow.has(name));
  useEffect(() => {
    if (dup) { close(); return undefined; }
    openNow.add(name);
    return () => openNow.delete(name);
  }, []);
  return dup;
}

function Row({ label, children, top }) {
  return html`<div class="sx-row${top ? " top" : ""}"><span class="lbl">${label}</span><div class="sx-val">${children}</div></div>`;
}

function PathLink({ path }) {
  return html`<a class="sx-link mono" role="button" tabindex="0" onClick=${() => call("shellx.open_folder_link", path)}
    onKeyDown=${(e) => { if (e.key === "Enter") call("shellx.open_folder_link", path); }}>${path}</a>`;
}

function ErrorNote({ text }) {
  return text ? html`<${Note} kind="err">${text}<//>` : null;
}

// -------------------------------------------------------------- Tips
// The green ? window (help_dialog.TabHelpWindow): the tab's own sections,
// then "General".  Not modal, like Tk's: it floats beside the page and
// follows the tab that is showing.
function TipsPanel({ close }) {
  const dup = useSingleton("tips", close);
  const shell = useNs("shell");
  const railTab = (shell.tabs || []).find((t) => t.ns === shell.tab);
  const [picked, setPicked] = useState(null);
  const key = picked || (railTab && railTab.key) || "Extract";
  const [data, setData] = useState(null);
  const body = useRef(null);
  useEffect(() => { setPicked(null); }, [shell.tab]);
  useEffect(() => {
    let live = true;
    call("shellx.tips", key).then((d) => { if (live && d) { setData(d); if (body.current) body.current.scrollTop = 0; } });
    return () => { live = false; };
  }, [key]);
  useEffect(() => {
    // Escape is the Tips window's only while nothing is above it: an open
    // menu, a modal window or message box (a scrim), or a floating window
    // that took the key first
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented || menuOpen()) return;
      if (document.querySelector(".scrim")) return;
      close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  if (dup) return null;
  const jump = (id) => {
    const el = body.current && body.current.querySelector("#" + id);
    if (el) body.current.scrollTop = el.offsetTop - 8;
  };
  const sections = (data && data.sections) || [];
  const general = (data && data.general) || [];
  const tabs = (data && data.tabs) || [];
  return html`<aside class="sx-tips" role="dialog" aria-label=${data ? data.title : "Tips"}>
    <div class="hd">
      <span class="sx-tips-mark"><${Icon} name="help" /></span>
      <span class="h2 grow ellip">${data ? data.title : "Tips"}</span>
      ${tabs.length > 1 ? html`<${Select} sm value=${key} width=${170} title="Show the tips of another tab"
        options=${tabs.map((t) => ({ value: t.key, label: t.label }))} onChange=${setPicked} />` : null}
      <${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${close} />
    </div>
    <div class="sx-tips-body">
      <nav class="sx-toc" aria-label="Sections">
        ${sections.map(([t], i) => html`<button type="button" onClick=${() => jump("tip-" + i)}>${t}</button>`)}
        <div class="eyebrow">General</div>
        ${general.map(([t], i) => html`<button type="button" onClick=${() => jump("gen-" + i)}>${t}</button>`)}
      </nav>
      <div class="sx-tips-text" ref=${body}>
        ${!data ? html`<div class="row"><${Spinner} /><span class="muted">Loading…</span></div>` : null}
        ${data && !sections.length ? html`<p class="muted">No tips for this tab yet: the general ones are below.</p>` : null}
        ${sections.map(([t, b], i) => html`<section id=${"tip-" + i}><h3>${t}</h3><p>${b}</p></section>`)}
        ${data ? html`<div class="sx-rule eyebrow">General</div>` : null}
        ${general.map(([t, b], i) => html`<section id=${"gen-" + i}><h3>${t}</h3><p>${b}</p></section>`)}
      </div>
    </div>
  </aside>`;
}
registerDialog("tips", TipsPanel);

// -------------------------------------------------- Preview features
function PreviewFeaturesDialog({ close }) {
  const [uid, onClose] = useWin(close);
  const [st, setSt] = useState(null);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState(null);
  const [sel, setSel] = useState(null);
  useEffect(() => { call("shellx.preview_state").then(setSt); }, []);
  const unlock = async () => {
    const r = await call("shellx.preview_unlock", text);
    if (!r) return;
    setMsg({ ok: r.ok, text: r.message });
    setSt((s) => ({ ...s, rows: r.rows }));
    if (r.ok) setText("");
  };
  const remove = async () => {
    const r = await call("shellx.preview_remove", sel);
    if (!r) return;
    setMsg({ ok: r.ok, text: r.message });
    setSt((s) => ({ ...s, rows: r.rows }));
    if (r.ok) setSel(null);
  };
  const rows = (st && st.rows) || [];
  return html`<${Modal} title=${(st && st.title) || "Preview features"} onClose=${onClose} cls=${uid}
    footer=${html`<${Button} onClick=${remove}>Remove<//><${Button} onClick=${close}>Close<//>`}>
    <p class="sx-p">${st ? st.intro : ""}</p>
    <label class="lbl" for="sx-code"><b>Paste a code:</b></label>
    <textarea id="sx-code" class="area mono" rows="4" spellcheck="false" value=${text}
      onInput=${(e) => setText(e.target.value)}></textarea>
    <div class="row wrap">
      <${Button} kind="primary" onClick=${unlock} disabled=${!text.trim()}>Unlock<//>
      ${msg ? html`<span class=${cx("small", msg.ok ? "ok-ink" : "err-ink")}>${msg.text}</span>` : null}
    </div>
    <label class="lbl"><b>In this copy of the app:</b></label>
    <div class="card sx-list" role="listbox" aria-label="Preview codes">
      ${rows.length ? rows.map((r) => html`<button type="button" role="option" aria-selected=${sel === r.i}
          class=${cx("li", sel === r.i && "sel")} onClick=${() => setSel(r.i)}>
          <${Icon} name=${r.active ? "check" : "warn"} />
          <span class="stack" style="gap:0">${r.lines.map((ln) => html`<span>${ln}</span>`)}</span>
        </button>`)
        : html`<div class="muted small" style="padding:10px 12px">${(st && st.empty) || "No preview features are switched on."}</div>`}
    </div>
  <//>`;
}
registerDialog("preview_features", PreviewFeaturesDialog);

// ------------------------------------------------------- Disclaimer
// Settings > View disclaimer…: review mode, one Close button, focused; Enter,
// Escape and the ✕ all close it (gui/disclaimer.py review=True).
function DisclaimerDialog({ close }) {
  const shell = useNs("shell");
  const [uid, onClose] = useWin(close);
  useEffect(() => {
    const btn = document.querySelector("." + uid + " .sx-close");
    if (btn) btn.focus();
    const onKey = (e) => {
      if (e.key !== "Enter" || e.defaultPrevented || menuOpen() || !isTop(uid)) return;
      e.preventDefault();
      close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return html`<${Modal} title=${shell.disclaimer_title || "Important — Read Before Use"} icon="warn" wide onClose=${onClose} cls=${"sx-disc " + uid}
    footer=${html`<${Button} kind="primary" cls="sx-close" onClick=${close}>Close<//>`}>
    <div class="h2">${shell.disclaimer_header || ""}</div>
    <div class="msg sx-disclaimer">${shell.disclaimer_text || ""}</div>
  <//>`;
}
registerDialog("disclaimer", DisclaimerDialog);

// ------------------------------------------------ Manage disk space
function barKind(pct) { return pct == null ? "" : pct < 75 ? "ok" : pct < 90 ? "warn" : "err"; }

// disk_dialog's "Resize WSL disk" prompt: Return is Resize, Escape closes
// the prompt only (win.bind("<Return>") / ("<Escape>", win.destroy)).
function ResizePrompt({ spec, onDone }) {
  const [v, setV] = useState(String(spec.cur));
  const [err, setErr] = useState("");
  const [uid, onClose] = useWin(() => onDone(null));
  const ok = (text) => {
    const raw = (typeof text === "string" ? text : v).trim();
    const n = Number(raw);
    if (!raw || !isFinite(n)) { setErr("Enter a whole number of GB."); return; }
    const gib = Math.trunc(n);
    if (gib < spec.min) { setErr("Too small — WSL is using " + spec.used + ". Minimum " + spec.min + " GB."); return; }
    if (spec.max != null && gib > spec.max) { setErr("Larger than the host drive can back. Maximum " + spec.max + " GB."); return; }
    onDone(gib);
  };
  return html`<${Modal} title="Resize WSL disk" onClose=${onClose} cls=${uid}
    footer=${html`<${Button} onClick=${() => onDone(null)}>Cancel<//><${Button} kind="primary" onClick=${() => ok()}>Resize<//>`}>
    <div class="muted small wrap">${spec.info}</div>
    <div class="row" onKeyDown=${onEnter((t) => { setV(t); ok(t); })}><span>New size:</span>
      <${Field} value=${v} onChange=${setV} width=${110} autoFocus mono />
      <span>GB</span></div>
    <div class="muted small">${spec.bounds}</div>
    ${err ? html`<div class="err-ink small">${err}</div>` : null}
  <//>`;
}

function DiskSpaceDialog({ close }) {
  const dup = useSingleton("disk_space", close);
  const sx = useNs("shellx");
  const d = sx.disk;
  const [sel, setSel] = useState(new Set());
  const [resize, setResize] = useState(null);
  useEffect(() => { if (!dup) call("shellx.disk_open"); }, []);
  useEffect(() => { setSel(new Set()); }, [d && d.rows && d.rows.map((r) => r.id).join("|")]);
  const tryClose = async () => { const ok = await call("shellx.disk_close"); if (ok) close(); };
  const [uid, onClose] = useWin(tryClose);
  if (dup) return null;
  const rows = (d && d.rows) || [];
  const busy = !d || d.busy;
  const leaves = () => {
    const out = [];
    for (const r of rows) if (sel.has(r.id)) out.push(...r.leaves);
    return out;
  };
  const toggle = (id, e) => {
    const next = new Set(e && (e.ctrlKey || e.metaKey || e.shiftKey) ? sel : []);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSel(next);
  };
  const startResize = async () => {
    const spec = await call("shellx.disk_resize_prepare");
    if (spec) setResize(spec);
  };
  return html`<${Modal} title="Manage disk space" icon="disk" wide onClose=${onClose} cls=${uid}
    footer=${html`<span class="grow small dim ellip" title=${d ? d.status : ""}>${d ? d.status : ""}</span><${Button} onClick=${tryClose}>Close<//>`}>
    <p class="sx-p muted">${d ? d.intro : ""}</p>
    <div class="stack" style="gap:8px">
      ${((d && d.bars) || []).map((b) => html`<div class="sx-usage">
        <span class="small">${b.text}</span>
        <div class=${cx("sx-bar", barKind(b.pct))}><i style=${`width:${b.pct == null ? 0 : b.pct}%`}></i></div>
      </div>`)}
    </div>
    <div class="stack" style="gap:4px">
      <span class="h2">Leftover staging and caches</span>
      <span class="small muted">${d ? d.tree_note : ""}</span>
    </div>
    <div class="card sx-tree" role="tree" aria-label="Location / manufacturer / item">
      <div class="sx-tree-hd"><span>Location / manufacturer / item</span><span>Size</span></div>
      ${rows.length ? rows.map((r) => html`<button type="button" role="treeitem" aria-selected=${sel.has(r.id)}
          class=${cx("sx-tree-row", "lv" + r.level, sel.has(r.id) && "sel")} onClick=${(e) => toggle(r.id, e)}>
          <span class="ellip">${r.text}</span><span class="mono small">${r.size}</span></button>`)
        : html`<div class="muted small" style="padding:12px">${busy ? "Scanning…" : "Nothing to clean up."}</div>`}
    </div>
    <div class="row wrap">
      <${Button} onClick=${() => call("shellx.disk_refresh")} disabled=${busy}>Refresh<//>
      <${Button} onClick=${() => call("shellx.disk_clean", leaves(), "selected")} disabled=${busy || !sel.size}>Clean selected<//>
      <${Button} kind="danger" onClick=${() => call("shellx.disk_clean", null, "all")} disabled=${busy || !(d && d.can_clean_all)}>Clean all<//>
    </div>
    <hr class="sx-hr" />
    <div class="stack" style="gap:4px">
      <span class="h2">Reclaim WSL space to Windows</span>
      <span class="small muted wrap">${d ? d.reclaim_note : ""}</span>
      <div><${Button} onClick=${() => call("shellx.disk_reclaim")} disabled=${!(d && d.can_reclaim)}>Reclaim space to Windows…<//></div>
    </div>
    <hr class="sx-hr" />
    <div class="stack" style="gap:4px">
      <span class="h2">Resize WSL disk</span>
      <span class="small muted">${d ? d.resize_note : ""}</span>
      <div><${Button} onClick=${startResize} disabled=${!(d && d.can_resize)}>Resize WSL disk…<//></div>
    </div>
    ${resize ? html`<${ResizePrompt} spec=${resize} onDone=${(gib) => { setResize(null); if (gib) call("shellx.disk_resize", gib); }} />` : null}
  <//>`;
}
registerDialog("disk_space", DiskSpaceDialog);

// ------------------------------------------------------- New project
const BAD_NAME = /[<>:"/\\|?*]/;
function ell(path, keep = 52) {
  return path.length <= keep ? path : path.slice(0, 22) + "…" + path.slice(-(keep - 23));
}
// projects_ui.new_project_dialog's live folder-structure preview, line
// for line.
function newProjectPreview(parent, name, stock) {
  const example = !(parent && name);
  const p = parent || "D:\\pinball";
  const n = name || "TMNT 1.59 upscale";
  const s = stock || (p + "\\stock\\tmnt_1.59.raw");
  return {
    title: example ? "Example — the structure a project gets:" : "This will create:",
    text: [
      ell(p) + "\\",
      "└─ " + n + "\\               <- the project",
      "     ├─ audio\\ videos\\ …    extracted assets",
      "     ├─ build\\               the built card image",
      "     └─ .pinproj             project settings (hidden)",
      "",
      "stock image — stays OUTSIDE the project, shared:",
      "  " + ell(s),
    ].join("\n"),
  };
}

function NewProjectDialog({ close }) {
  const [form, setForm] = useState(null);
  const [parent, setParent] = useState("");
  const [name, setName] = useState("");
  const [mfr, setMfr] = useState("");
  const [stock, setStock] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [uid, onClose] = useWin(close);
  useEffect(() => {
    call("shellx.project_form").then((f) => {
      if (!f || f.running) { close(); return; }
      setForm(f); setParent(f.parent || ""); setMfr(f.mfr || "");
    });
  }, []);
  if (!form) return null;
  const prev = newProjectPreview(parent.trim(), name.trim(), stock.trim());
  const create = async () => {
    setBusy(true);
    const r = await call("shellx.project_new_create", parent, name, mfr, stock);
    setBusy(false);
    if (!r) return;
    if (r.error) { setErr(r.error); return; }
    close();
  };
  return html`<${Modal} title="New project" icon="plus" wide onClose=${onClose} cls=${uid}
    footer=${html`<${Button} onClick=${close}>Cancel<//><${Button} kind="primary" busy=${busy} disabled=${busy} onClick=${create}>Create<//>`}>
    <div class="sx-form">
      <${Row} label="Location:"><div class="row">
        <${Field} value=${parent} onChange=${(v) => { setParent(v); setErr(""); }} mono cls="grow" placeholder="The folder the project folder goes in" />
        <${Button} onClick=${async () => { const p = await call("shellx.browse_location", parent); if (p) setParent(p); }}>Browse...<//></div><//>
      <${Row} label="Folder name:"><${Field} value=${name} onChange=${(v) => { setName(v); setErr(""); }} autoFocus
        bad=${!!name && BAD_NAME.test(name)} placeholder="TMNT 1.59 upscale" /><//>
      <${Row} label="Manufacturer:"><${Select} value=${mfr} onChange=${setMfr}
        options=${form.mfrs.map((m) => ({ value: m.key, label: m.display }))} /><//>
      <${Row} label="Stock image:"><div class="row">
        <${Field} value=${stock} onChange=${(v) => { setStock(v); setErr(""); }} mono cls="grow" placeholder="Optional: the card image the project starts from" />
        <${Button} onClick=${async () => { const p = await call("shellx.browse_stock", mfr, stock); if (p) setStock(p); }}>Browse...<//></div><//>
    </div>
    <div class="stack" style="gap:4px">
      <span class="small muted">${prev.title}</span>
      <pre class="sx-tree-preview">${prev.text}</pre>
    </div>
    <${ErrorNote} text=${err} />
  <//>`;
}
registerDialog("project_new", NewProjectDialog);

// ------------------------------------------- Save project as (fork)
function SaveAsDialog({ close, folder }) {
  const [form, setForm] = useState(null);
  const [parent, setParent] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [uid, onClose] = useWin(close);
  useEffect(() => {
    call("shellx.fork_form", folder || null).then((f) => {
      if (!f) { close(); return; }
      setForm(f); setParent(f.parent || ""); setName(f.hint || "");
    });
  }, []);
  if (!form) return null;
  const p = parent.trim(), n = name.trim();
  const dest = p && n ? p + (p.endsWith(form.sep) ? "" : form.sep) + n : "";
  const ok = async () => {
    setBusy(true);
    const r = await call("shellx.fork_start", form.src, parent, name);
    setBusy(false);
    if (!r) return;
    if (r.error) { setErr(r.error); return; }
    close();
  };
  return html`<${Modal} title="Save project as (fork)" icon="copy" wide onClose=${onClose} cls=${uid}
    footer=${html`<${Button} onClick=${close}>Cancel<//><${Button} kind="primary" busy=${busy} disabled=${busy} onClick=${ok}>OK<//>`}>
    <div class="small muted">Copies <span class="mono">${form.src}</span> as it is now, edits included. The build output isn't copied — the fork rebuilds its own.</div>
    <div class="sx-form">
      <${Row} label="Location:"><div class="row">
        <${Field} value=${parent} onChange=${(v) => { setParent(v); setErr(""); }} mono cls="grow" />
        <${Button} onClick=${async () => { const x = await call("shellx.browse_location", parent); if (x) setParent(x); }}>Browse...<//></div><//>
      <${Row} label="Folder name:"><${Field} value=${name} onChange=${(v) => { setName(v); setErr(""); }} autoFocus bad=${!!name && BAD_NAME.test(name)} /><//>
    </div>
    <div class="small muted mono ellip" title=${dest}>${dest}</div>
    <${ErrorNote} text=${err} />
  <//>`;
}
registerDialog("project_save_as", SaveAsDialog);

// ------------------------------------------------ Project properties
function PropertiesDialog({ close, folder }) {
  const sx = useNs("shellx");
  const [p, setP] = useState(null);
  const [notes, setNotes] = useState("");
  const closer = useRef(close);
  const [uid, onClose] = useWin(() => closer.current());
  const load = () => call("shellx.properties_state", folder || null).then((r) => {
    if (!r) { close(); return; }
    setP(r); setNotes(r.notes || "");
  });
  useEffect(() => { load(); }, []);
  if (!p) return null;
  const sizes = sx.props && sx.props.folder === p.folder ? sx.props.sizes : "Measuring sizes…";
  const saveAndClose = async () => {
    if (p.anchored) await call("shellx.properties_save_notes", p.folder, notes);
    close();
  };
  closer.current = saveAndClose;
  const archive = async () => {
    if (p.anchored) await call("shellx.properties_save_notes", p.folder, notes);
    const started = await call("shellx.project_archive", p.folder);
    if (started) close();
  };
  const changeBuild = async () => {
    if (await call("shellx.properties_change_build", p.folder)) load();
  };
  return html`<${Modal} title="Project properties" icon="folder" wide onClose=${onClose} cls=${uid}
    footer=${html`<${Button} onClick=${() => call("shellx.properties_delete_build", p.folder)}>Delete build<//>
      ${p.anchored ? html`<${Button} onClick=${changeBuild}>Change build location...<//>` : null}
      ${p.anchored && !p.archived ? html`<${Button} kind="danger" onClick=${archive}>Archive...<//>` : null}
      <span class="grow"></span>
      <${Button} kind="primary" onClick=${saveAndClose}>Close<//>`}>
    <div class="sx-form kvs">
      <${Row} label="Location:"><${PathLink} path=${p.folder} /><//>
      <${Row} label="Manufacturer:">${p.game}<//>
      <${Row} label="Stock image:"><span class="mono small sx-wrap">${p.stock}</span><//>
      <${Row} label="Build location:"><${PathLink} path=${p.build_dir} /><//>
      <${Row} label="Saved with:">${p.saved_with}<//>
    </div>
    <div class="small muted">${sizes}</div>
    <label class="lbl" for="sx-notes">Notes:</label>
    <textarea id="sx-notes" class="area" rows="5" value=${notes} disabled=${!p.anchored}
      onInput=${(e) => setNotes(e.target.value)}></textarea>
    ${!p.anchored ? html`<div class="small muted">(notes are stored in the project anchor — extract or stage a change first)</div>` : null}
  <//>`;
}
registerDialog("project_properties", PropertiesDialog);

// --------------------------------------------------- Change history
function HistoryDialog({ close, path }) {
  const [r, setR] = useState(null);
  const box = useRef(null);
  const [uid, onClose] = useWin(close);
  useEffect(() => { call("shellx.read_text_tail", path, 4000).then(setR); }, [path]);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [r]);
  return html`<${Modal} title="Change history" icon="list" xwide onClose=${onClose} cls=${uid}
    footer=${html`<${Button} icon="external" onClick=${() => call("shellx.open_in_viewer", path)}>Open in text viewer<//>
      <${Button} kind="primary" onClick=${close}>Close<//>`}>
    <div class="small muted mono sx-wrap">${path}</div>
    ${!r ? html`<div class="row"><${Spinner} /><span class="muted">Loading…</span></div>`
      : r.error ? html`<${Note} kind="err">${r.error}<//>`
      : html`${r.total > r.lines.length ? html`<div class="small muted">The last ${r.lines.length} of ${r.total} lines; the whole file opens in the text viewer.</div>` : null}
        <pre class="sx-logview mono" ref=${box}>${r.lines.join("\n")}</pre>`}
  <//>`;
}
registerDialog("project_history", HistoryDialog);

// ------------------------------------------------------- Projects…
// projects_ui.open_manager: a plain Toplevel (no grab), so it floats and the
// app stays usable behind it (Open a project and watch its tabs load with
// the list still up); the columns drag wider, like the Treeview's.
function ManagerDialog({ close }) {
  const dup = useSingleton("project_manager", close);
  const sx = useNs("shellx");
  const shell = useNs("shell");
  const [sel, setSel] = useState(null);
  const [widths, setWidths] = useState(null);
  useEffect(() => { if (!dup) call("shellx.manager_refresh"); }, []);
  useEvent("shellx_projects_changed", () => call("shellx.manager_refresh"), []);
  if (dup) return null;
  const rows = sx.pm_rows || [];
  const sizes = sx.pm_sizes || {};
  const ent = rows.find((r) => r.folder === sel) || null;
  const live = ent && !ent.missing;
  const running = !!shell.running;
  const cols = [
    { key: "folder", label: "Project", width: "minmax(0,3fr)", render: (r) => html`<span class="mono small ellip sx-cell" title=${r.folder}>${r.folder}</span>` },
    { key: "game", label: "Game", width: "minmax(0,1.3fr)", render: (r) => html`<span class="ellip sx-cell" title=${r.game}>${r.game}</span>` },
    { key: "size", label: "Size on disk", width: "110px", num: true, render: (r) => sizes[r.folder] || r.size },
    { key: "opened", label: "Last opened", width: "130px", render: (r) => html`<span class="mono small ellip sx-cell">${r.opened}</span>` },
    { key: "state", label: "State", width: "90px", render: (r) => r.state ? html`<span class=${r.state === "missing" ? "err-ink" : r.state === "archived" ? "info-ink" : "warn-ink"}>${r.state}</span>` : "" },
  ];
  return html`<${FloatWin} title="Projects" icon="list" onClose=${close} cls="sx-manager"
    footer=${html`<${Button} kind="primary" disabled=${!live || running} onClick=${() => call("shellx.manager_open", sel)}>Open<//>
      <${Button} disabled=${!live} onClick=${() => openDialog("project_properties", { folder: sel })}>Properties...<//>
      <${Button} disabled=${!live || running} onClick=${() => openDialog("project_save_as", { folder: sel })}>Save As (fork)...<//>
      <${Button} disabled=${!live || !ent.anchored || running} onClick=${() => call("shellx.project_archive", sel)}>Archive...<//>
      <${Button} disabled=${!live} onClick=${() => call("shellx.manager_reveal", sel)}>Reveal<//>
      <${Button} disabled=${!ent} onClick=${() => call("shellx.manager_remove", sel).then(() => setSel(null))}>Remove from list<//>
      <${Button} disabled=${!ent} onClick=${() => call("shellx.manager_locate", sel)}>Locate...<//>
      <span class="grow"></span><${Button} onClick=${close}>Close<//>`}>
    <${Table} columns=${cols} rows=${rows} rowKey=${(r) => r.folder} selected=${sel}
      onSelect=${(r) => setSel(r.folder)} onActivate=${(r) => { setSel(r.folder); if (!r.missing && !running) call("shellx.manager_open", r.folder); }}
      cls="card sx-fill" resizable widths=${widths} onResize=${setWidths}
      empty=${html`<div class="empty small">No projects yet: every folder the app opens or anchors lands here.</div>`} />
    <div class="small muted">${sx.pm_note || ""}</div>
  <//>`;
}
registerDialog("project_manager", ManagerDialog);

// --------------------------------------------- Relink moved files
// projects_ui.open_relink: floating and non-modal like the manager; Return
// in "Where are those files now?" is Search (entry.bind("<Return>")).
function RelinkDialog({ close, folder }) {
  const dup = useSingleton("project_relink", close);
  const sx = useNs("shellx");
  const [ready, setReady] = useState(false);
  const [root, setRoot] = useState(null);
  const [widths, setWidths] = useState(null);
  const rl = sx.relink;
  useEffect(() => {
    if (dup) return;
    call("shellx.relink_open", folder || null).then((r) => { if (!r) close(); else setReady(true); });
    return () => { call("shellx.relink_close"); };
  }, []);
  if (dup || !ready || !rl) return null;
  const rootShown = root == null ? rl.root || "" : root;
  const search = (text) => call("shellx.relink_search", typeof text === "string" ? text : rootShown);
  const browse = async () => { const p = await call("shellx.relink_browse"); if (p) setRoot(p); };
  const cols = [
    { key: "file", label: "Replacement file", width: "minmax(0,1.3fr)", render: (r) => html`<span class="ellip sx-cell" title=${r.path}>${r.file}</span>` },
    { key: "slots", label: "Used by", width: "80px", num: true },
    { key: "found", label: "Found at", width: "minmax(0,2.4fr)", render: (r) => html`<span class=${cx("mono small ellip sx-cell", r.hit && "ok-ink")} title=${r.found}>${r.found}</span>` },
  ];
  return html`<${FloatWin} title="Relink moved files" icon="refresh" onClose=${close} cls="sx-relink"
    footer=${html`<${Button} onClick=${() => search()} disabled=${rl.done}>${rl.busy ? "Stop" : "Search"}<//>
      <${Button} kind="primary" disabled=${!rl.can_apply || rl.busy} onClick=${() => call("shellx.relink_apply")}>${rl.apply_label || "Relink"}<//>
      <span class="grow"></span><${Button} onClick=${close}>Close<//>`}>
    <div class="sx-p">${rl.head}</div>
    <div class="row" onKeyDown=${onEnter((t) => { if (rl.busy || rl.done) return; setRoot(t); search(t); })}>
      <span class="lbl nw">Where are those files now?</span>
      <${Field} value=${rootShown} onChange=${setRoot} mono cls="grow" disabled=${rl.busy} />
      <${Button} onClick=${browse} disabled=${rl.busy}>Browse...<//>
    </div>
    <${Table} columns=${cols} rows=${rl.rows || []} rowKey=${(r) => r.path} cls="card sx-fill"
      resizable widths=${widths} onResize=${setWidths}
      empty=${html`<div class="empty small">Nothing to re-point.</div>`} />
    <div class="small muted sx-wrap">${rl.status}</div>
  <//>`;
}
registerDialog("project_relink", RelinkDialog);

// ------------------------------------------- state-driven windows
// A project copy / archive in progress (projects_ui._ProgressDialog) and
// the update download (MainWindow.open_update_download_dialog).
export function ShellxOverlays() {
  const sx = useNs("shellx");
  const job = sx.job;
  const dl = sx.download;
  return html`
    ${job ? html`<div class="scrim"><div class="modal" role="dialog" aria-modal="true" aria-label=${job.title}>
      <div class="hd"><span class="h2">${job.title}</span></div>
      <div class="bd"><div class="msg">${job.text}</div>
        <${Progress} pct=${Math.round((job.frac || 0) * 100)} />
        <div class="small muted ellip" title=${job.detail}>${job.cancelling ? "Cancelling…" : job.detail || " "}</div></div>
      <div class="ft"><${Button} disabled=${job.cancelling} onClick=${() => call("shellx.job_cancel", job.id)}>Cancel<//></div>
    </div></div>` : null}
    ${dl ? html`<div class="scrim"><div class="modal" role="dialog" aria-modal="true" aria-label="Downloading update">
      <div class="hd"><${Icon} name="download" cls="lg" /><span class="h2">Downloading update</span></div>
      <div class="bd"><div class="msg">${dl.text}</div>
        <${Progress} pct=${dl.pct || 0} busy=${dl.pct == null} />
        <div class="small muted">${dl.detail}</div></div>
      <div class="ft"><${Button} kind="danger" disabled=${dl.cancelling} onClick=${() => call("shellx.download_cancel")}>Cancel<//></div>
    </div></div>` : null}`;
}

export { TipsPanel };
