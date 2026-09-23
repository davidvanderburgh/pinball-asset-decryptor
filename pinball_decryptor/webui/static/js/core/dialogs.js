// Modals.  Two kinds:
//
// 1. Python's questions (messagebox / file pickers without a native panel):
//    they live in state.modals.open and are answered with reply(id, value).
// 2. Dialogs the page owns (the project menu's windows, a tab's editor):
//    registerDialog("project_new", Component); Python opens one with
//    bus.publish("open_dialog", name=...), a tab with openDialog(name, props).
//    The component gets {close, ...props}.

import { html, useEffect, useRef, useState, Modal, Button, Icon, Field, fmtBytes, cx, isTopScrim } from "./ui.js";
import { useNs, useEvent } from "./store.js";
import { call, reply } from "./rpc.js";

const registry = new Map();
let openHook = null;
export function registerDialog(name, component) { registry.set(name, component); }
export function openDialog(name, props = {}) { if (openHook) openHook(name, props); }

const ICON = { warning: ["warn", "icon-w"], error: ["error", "icon-e"], question: ["question", "icon-q"], info: ["info", "icon-i"] };

function MessageModal({ spec }) {
  const [icon, iconCls] = ICON[spec.icon] || ICON.info;
  const answer = (id) => reply(spec.id, id);
  const buttons = spec.buttons || [{ id: "ok", label: "OK", style: "primary" }];
  const deflt = spec.default || (buttons.find((b) => b.style === "primary") || buttons[0]).id;
  const cancelId = (buttons.find((b) => b.id === "cancel" || b.id === "no") || buttons[buttons.length - 1]).id;
  const scrim = useRef(null);
  useEffect(() => {
    const onKey = (e) => {
      if (!isTopScrim(scrim.current)) return;
      if (e.key === "Escape") { e.preventDefault(); answer(buttons.length === 1 ? buttons[0].id : cancelId); }
      else if (e.key === "Enter" && !(e.target && e.target.tagName === "BUTTON")) { e.preventDefault(); answer(deflt); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [spec.id]);
  return html`<div class="scrim" ref=${scrim}>
    <div class="modal" role="alertdialog" aria-modal="true" aria-label=${spec.title}>
      <div class="hd"><span class=${iconCls}><${Icon} name=${icon} cls="lg" /></span><span class="h2">${spec.title || "Pinball Asset Decryptor"}</span></div>
      <div class="bd"><div class="msg">${spec.message}</div>${spec.detail ? html`<div class="msg muted small">${spec.detail}</div>` : null}</div>
      <div class="ft">${buttons.map((b) => html`<${Button} kind=${b.id === deflt ? (spec.icon === "warning" && b.id === "yes" ? "primary" : "primary") : ""}
        autoFocus=${b.id === deflt} onClick=${() => answer(b.id)}>${b.label}<//>`)}</div>
    </div></div>`;
}

// The page's own folder browser, for platforms with no native picker.
export function FileBrowser({ spec, onDone }) {
  const mode = spec.mode;                 // open | save | folder
  const [dir, setDir] = useState(spec.initialdir || "");
  const [listing, setListing] = useState(null);
  const [name, setName] = useState(spec.initialfile || "");
  const [picked, setPicked] = useState(new Set());
  const [ft, setFt] = useState(0);
  const types = spec.filetypes && spec.filetypes.length ? spec.filetypes : [["All files", "*.*"]];
  const patterns = String(types[ft][1] || "*.*").split(/\s+/).filter(Boolean);
  const load = async (d) => {
    const r = await call("fs.list", d, mode === "folder" ? ["__none__"] : patterns);
    if (r) { setListing(r); setDir(r.path); }
  };
  useEffect(() => { load(dir); }, [ft]);
  const entries = (listing && listing.entries) || [];
  const shown = mode === "folder" ? entries.filter((e) => e.dir) : entries;
  const join = (d, n) => (d.endsWith("/") || d.endsWith("\\") ? d + n : d + (d.includes("\\") ? "\\" : "/") + n);
  const ok = () => {
    if (mode === "folder") return onDone(dir);
    if (mode === "save") return name ? onDone(join(dir, name)) : null;
    if (spec.multiple) return onDone([...picked]);
    return onDone(picked.size ? [...picked][0] : name ? join(dir, name) : "");
  };
  return html`<${Modal} title=${spec.title || (mode === "folder" ? "Choose a folder" : mode === "save" ? "Save as" : "Open")} wide onClose=${() => onDone(mode === "open" && spec.multiple ? [] : "")}
    footer=${html`${mode !== "folder" ? html`<${Field} value=${name} onChange=${setName} placeholder=${mode === "save" ? "File name" : "File name or pick one above"} cls="grow" />` : html`<span class="grow mono small ellip">${dir}</span>`}
      ${types.length > 1 ? html`<select class="field" onChange=${(e) => setFt(Number(e.target.value))}>${types.map((t, i) => html`<option value=${i}>${t[0]}</option>`)}</select>` : null}
      <${Button} onClick=${() => onDone(mode === "open" && spec.multiple ? [] : "")}>Cancel<//>
      <${Button} kind="primary" onClick=${ok}>${mode === "folder" ? "Choose this folder" : mode === "save" ? "Save" : "Open"}<//>`}>
    <div class="row">
      <${Button} size="sm" icon="up" disabled=${!listing || !listing.parent} onClick=${() => load(listing.parent)}>Up<//>
      <${Button} size="sm" kind="ghost" onClick=${() => load("")}>Drives<//>
      <${Field} value=${dir} mono sm cls="grow" onCommit=${(v) => load(v)} onChange=${() => {}} />
    </div>
    ${listing && listing.error ? html`<div class="note err"><${Icon} name="error" /><div class="body-text">${listing.error}</div></div>` : null}
    <div class="card" style="height:380px;overflow:auto">
      <div class="list" style="padding:4px">
        ${shown.map((e) => html`<button type="button" class=${cx("li", picked.has(e.path) && "sel")}
            onClick=${() => {
              if (e.dir) return;
              const next = new Set(spec.multiple ? picked : []);
              if (next.has(e.path)) next.delete(e.path); else next.add(e.path);
              setPicked(next); setName(e.name);
            }}
            onDblClick=${() => (e.dir ? load(e.path) : mode === "open" ? onDone(spec.multiple ? [e.path] : e.path) : setName(e.name))}>
            <${Icon} name=${e.dir ? "folder" : "file"} /><span class="ellip">${e.name}</span>
            ${e.size != null ? html`<span class="r muted small mono">${fmtBytes(e.size)}</span>` : null}
          </button>`)}
        ${listing && !shown.length ? html`<div class="empty small">Nothing here.</div>` : null}
      </div>
    </div>
  <//>`;
}

function PromptModal({ spec }) {
  const [text, setText] = useState(spec.initial || "");
  const ok = () => reply(spec.id, text);
  const cancel = () => reply(spec.id, "cancel");
  const scrim = useRef(null);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && isTopScrim(scrim.current)) { e.preventDefault(); cancel(); } };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [spec.id]);
  return html`<div class="scrim" ref=${scrim}><div class="modal" role="dialog" aria-modal="true" aria-label=${spec.title}>
    <div class="hd"><span class="h2">${spec.title || "Pinball Asset Decryptor"}</span></div>
    <div class="bd" onKeyDown=${(e) => {
        // Enter answers OK with what is in the box NOW (Tk's simpledialog).
        // Not the Field's onCommit: that also fires on blur, i.e. on the
        // mousedown of Cancel, which then answered with the text.
        if (e.key === "Enter" && !e.isComposing && e.target.tagName === "INPUT") {
          e.preventDefault(); reply(spec.id, e.target.value);
        }
      }}>${spec.message ? html`<div class="msg">${spec.message}</div>` : null}
      <${Field} value=${text} onChange=${setText} autoFocus selectAll
        type=${spec.input === "str" ? "text" : "number"} bad=${!!spec.error} />
      ${spec.error ? html`<div class="small err-ink">${spec.error}</div>` : null}</div>
    <div class="ft"><${Button} onClick=${cancel}>Cancel<//><${Button} kind="primary" onClick=${ok}>OK<//></div>
  </div></div>`;
}

function DetailsModal({ spec }) {
  const [open, setOpen] = useState(false);
  const cols = spec.columns && spec.columns.length ? spec.columns : ["File", "Why"];
  return html`<div class="scrim"><div class=${cx("modal", open && "wide")} role="alertdialog" aria-modal="true">
    <div class="hd"><span class="icon-q"><${Icon} name="question" cls="lg" /></span><span class="h2">${spec.title}</span></div>
    <div class="bd"><div class="msg">${spec.message}</div>
      <div><${Button} size="sm" kind="ghost" icon=${open ? "down" : "right"} onClick=${() => setOpen(!open)}>${spec.details_label} (${(spec.rows || []).length})<//></div>
      ${open ? html`<div class="card" style="max-height:320px;overflow:auto"><table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr>${cols.map((c) => html`<th style="text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)" class="eyebrow">${c}</th>`)}</tr></thead>
        <tbody>${(spec.rows || []).map((r) => html`<tr>${r.map((c) => html`<td style="padding:5px 10px;border-bottom:1px solid var(--line);vertical-align:top" class="mono small">${c}</td>`)}</tr>`)}</tbody></table></div>` : null}
    </div>
    <div class="ft"><${Button} onClick=${() => reply(spec.id, "no")}>No<//><${Button} kind="primary" onClick=${() => reply(spec.id, "yes")}>Yes<//></div>
  </div></div>`;
}

export function DialogHost() {
  const modals = useNs("modals");
  const [local, setLocal] = useState([]);
  openHook = (name, props) => setLocal((l) => [...l, { name, props, id: Math.random() }]);
  useEvent("open_dialog", (e) => openHook(e.name, e.props || {}), []);
  const open = modals.open || [];
  const top = open.length ? open[open.length - 1] : null;
  return html`
    ${local.map((d) => {
      const C = registry.get(d.name);
      const close = () => setLocal((l) => l.filter((x) => x.id !== d.id));
      if (!C) return html`<${Modal} title="Not available" onClose=${close}>This window is not built yet (${d.name}).<//>`;
      return html`<${C} key=${d.id} close=${close} ...${d.props} />`;
    })}
    ${top ? (top.kind === "file"
      ? html`<${FileBrowser} key=${top.id} spec=${top} onDone=${(v) => reply(top.id, v)} />`
      : top.kind === "details" ? html`<${DetailsModal} key=${top.id} spec=${top} />`
      : top.kind === "prompt" ? html`<${PromptModal} key=${top.id + (top.error || "")} spec=${top} />`
      : html`<${MessageModal} key=${top.id} spec=${top} />`) : null}`;
}
