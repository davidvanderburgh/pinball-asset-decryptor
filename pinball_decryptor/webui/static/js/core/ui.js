// Shared components.  Every tab builds from these so the whole app looks
// like one design (docs/plans/web_ui.md, "Writing a tab").
//
//   import { html, Button, Field, PathField, Check, Seg, Select, Card, Chip,
//            Note, Table, Icon, Empty, Modal, openMenu, InfoBadge } from "../core/ui.js";

import { h, html, render, useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback }
  from "../vendor/preact-htm.js";
import { call, setField } from "./rpc.js";

export { h, html, render, useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback };

export const cx = (...parts) => parts.filter(Boolean).join(" ");

// ---------------------------------------------------------------- icons
const P = {
  extract: "M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3M12 4v11M8 11l4 4 4-4",
  audio: "M3 10v4h4l5 4V6L7 10zM16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12",
  video: "M3 7a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM16 10l5-3v10l-5-3z",
  images: "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM9 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM21 16l-5-5-9 9",
  text: "M5 6h14M12 6v13M8 19h8",
  modes: "M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z",
  defaults: "M4 7h10M4 12h16M4 17h7M17 5a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM14 15a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  write: "M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM9 3v4h6V3M8 14h8M8 17h5",
  multiboot: "M4.5 4h15A1.5 1.5 0 0 1 21 5.5v3A1.5 1.5 0 0 1 19.5 10h-15A1.5 1.5 0 0 1 3 8.5v-3A1.5 1.5 0 0 1 4.5 4zM4.5 14h15a1.5 1.5 0 0 1 1.5 1.5v3a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5v-3A1.5 1.5 0 0 1 4.5 14zM7 7h.01M7 17h.01",
  modpack: "M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8",
  partitions: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 3v9l6.5 5",
  compare: "M4.5 4h4A1.5 1.5 0 0 1 10 5.5v13A1.5 1.5 0 0 1 8.5 20h-4A1.5 1.5 0 0 1 3 18.5v-13A1.5 1.5 0 0 1 4.5 4zM15.5 4h4A1.5 1.5 0 0 1 21 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-4a1.5 1.5 0 0 1-1.5-1.5v-13A1.5 1.5 0 0 1 15.5 4zM10 12h4",
  emulate: "M6 4l14 8-14 8z",
  play: "M6 4l14 8-14 8z",
  pause: "M7 5h3v14H7zM14 5h3v14h-3z",
  stop: "M7 6h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 8h.01",
  warn: "M12 3l10 18H2zM12 10v4M12 18h.01",
  error: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9 9l6 6M15 9l-6 6",
  question: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01",
  check: "M5 12l5 5L20 7",
  x: "M6 6l12 12M18 6L6 18",
  down: "M6 9l6 6 6-6",
  up: "M6 15l6-6 6 6",
  right: "M9 6l6 6-6 6",
  left: "M15 6l-6 6 6 6",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  help: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01",
  gear: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  home: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  log: "M4 6h16M4 10h16M4 14h10M4 18h7",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  copy: "M9 9h10v10H9zM5 15V5h10",
  grip: "M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01",
  zoomin: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5M11 8v6M8 11h6",
  zoomout: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5M8 11h6",
  sd: "M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM10 3v4M13 3v4",
  disk: "M4 5h16v14H4zM4 15h16M8 18h.01",
  upload: "M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  download: "M12 4v12M7 11l5 5 5-5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  undo: "M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
  lock: "M6 11h12v9H6zM8 11V7a4 4 0 0 1 8 0v4",
  star: "M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  wave: "M2 12h2l2-6 3 12 3-9 2 6 2-3h6",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4",
  save: "M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM7 3v5h8V3M7 21v-7h10v7",
  flag: "M5 21V4M5 4h12l-2 4 2 4H5",
};

export function Icon({ name, cls = "", title }) {
  const d = P[name] || P.info;
  return html`<svg class=${cx("i", cls)} viewBox="0 0 24 24" aria-hidden=${title ? "false" : "true"}>${title ? html`<title>${title}</title>` : null}<path d=${d} /></svg>`;
}

// --------------------------------------------------------------- tooltip
let tipEl = null;
function showTip(target, text) {
  if (!text) return;
  if (!tipEl) {
    tipEl = document.createElement("div");
    tipEl.className = "tip";
    document.body.appendChild(tipEl);
  }
  tipAnchor = target;
  tipEl.textContent = text;
  tipEl.style.display = "block";
  const z = pageZoom();
  const rr = target.getBoundingClientRect();
  const r = { left: rr.left / z, top: rr.top / z, bottom: rr.bottom / z, right: rr.right / z };
  const tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
  const vw = window.innerWidth / z, vh = window.innerHeight / z;
  let x = Math.min(vw - tw - 8, Math.max(8, r.left));
  let y = r.bottom + 6;
  if (y + th > vh - 8) y = r.top - th - 6;
  tipEl.style.left = x + "px";
  tipEl.style.top = y + "px";
}
let tipAnchor = null;
function hideTip() { tipAnchor = null; if (tipEl) tipEl.style.display = "none"; }
for (const ev of ["pointerdown", "keydown", "wheel"]) window.addEventListener(ev, () => hideTip(), true);
setInterval(() => { if (tipAnchor && !tipAnchor.isConnected) hideTip(); }, 500);
// The page's zoom (CSS zoom on <html>): rectangles are measured in screen
// pixels, styles are laid out in page pixels.
export function pageZoom() { return Number(document.documentElement.style.zoom) || 1; }
// Long help text: <span ...${tip("text")}> shows it on hover.
export function tip(text) {
  if (!text) return {};
  return {
    onMouseEnter: (e) => showTip(e.currentTarget, text),
    onMouseLeave: hideTip,
    onFocus: (e) => showTip(e.currentTarget, text),
    onBlur: hideTip,
  };
}

// A round "i": hover shows the text; with onClick it opens a window too.
export function InfoBadge({ text, label = "i", onClick }) {
  return html`<button type="button" class="badge-i" aria-label=${text} onClick=${onClick}
    style=${onClick ? "cursor:pointer" : undefined} ...${tip(text)}>${label}</button>`;
}

// --------------------------------------------------------------- controls
export function Button({ kind = "", size = "", icon, iconRight, onClick, disabled, title,
                         children, busy, type = "button", cls = "", label, autoFocus }) {
  const ref = useRef(null);
  useEffect(() => { if (autoFocus && ref.current) ref.current.focus(); }, []);
  return html`<button type=${type} ref=${ref} class=${cx("btn", kind, size, !children && icon && "icon", cls)}
    disabled=${!!disabled} onClick=${onClick} aria-label=${label || (typeof title === "string" && !children ? title : undefined)}
    ...${tip(title)}>
    ${busy ? html`<span class="spin"></span>` : icon ? html`<${Icon} name=${icon} />` : null}
    ${children}
    ${iconRight ? html`<${Icon} name=${iconRight} />` : null}
  </button>`;
}

// A text input that keeps its own value while focused and follows the
// store otherwise.  With ns+k it sends edits to Python (ui.set, debounced);
// with onChange it just reports them.  onCommit fires on Enter / blur.
export function Field({ ns, k, value, onChange, onCommit, placeholder, mono, sm, readOnly,
                        type = "text", cls = "", id, disabled, prefix, suffix, list,
                        width, delay = 250, title, autoFocus, bad, inputCls = "",
                        maxLength, min, max, step, selectAll }) {
  const [local, setLocal] = useState(value ?? "");
  const focused = useRef(false);
  const ref = useRef(null);
  useEffect(() => { if (!focused.current) setLocal(value ?? ""); }, [value]);
  useEffect(() => {
    if (autoFocus && ref.current) { ref.current.focus(); if (selectAll) ref.current.select(); }
  }, []);
  const send = (v, flush) => {
    if (onChange) { onChange(v); return Promise.resolve(true); }
    if (ns && k) return setField(ns, k, v, { delay, flush });
    return Promise.resolve(true);
  };
  // the edit reaches Python BEFORE onCommit's call, so the two never race
  const commit = async (v) => {
    await send(v, true);
    if (onCommit) onCommit(v);
  };
  return html`<div class=${cx("field", mono && "mono", sm && "sm", readOnly && "ro", disabled && "disabled", bad && "bad", cls)}
      style=${width ? `width:${typeof width === "number" ? width + "px" : width}` : undefined} ...${tip(title)}>
    ${prefix}
    <input id=${id} ref=${ref} type=${type} class=${inputCls} value=${local} placeholder=${placeholder} readOnly=${!!readOnly}
      disabled=${!!disabled} list=${list} spellcheck="false" maxLength=${maxLength} min=${min} max=${max} step=${step}
      onFocus=${() => { focused.current = true; }}
      onBlur=${(e) => { focused.current = false; if (!readOnly) commit(e.target.value); }}
      onInput=${(e) => { setLocal(e.target.value); if (!readOnly) send(e.target.value, false); }}
      onKeyDown=${(e) => { if (e.key === "Enter" && !readOnly) commit(e.target.value); }} />
    ${suffix}
  </div>`;
}

// A path with Browse… (and an optional history dropdown of recent paths).
export function PathField({ ns, k, value, onBrowse, browseLabel = "Browse…", placeholder,
                            history, readOnly, disabled, onCommit, title, extra, bad }) {
  const listId = history && history.length ? `hist-${ns}-${k}` : undefined;
  return html`<div class="row" style="gap:8px">
    <${Field} ns=${ns} k=${k} value=${value} mono readOnly=${readOnly} disabled=${disabled}
      placeholder=${placeholder} cls="grow" list=${listId} onCommit=${onCommit} title=${title} bad=${bad} />
    ${listId ? html`<datalist id=${listId}>${history.map((p) => html`<option value=${p} />`)}</datalist>` : null}
    ${onBrowse ? html`<${Button} onClick=${onBrowse} disabled=${disabled}>${browseLabel}<//>` : null}
    ${extra}
  </div>`;
}

export function Select({ value, options, onChange, ns, k, sm, disabled, width, cls = "", title, id }) {
  const opts = (options || []).map((o) => (typeof o === "object" ? o : { value: o, label: String(o) }));
  const change = (e) => {
    const v = e.target.value;
    if (onChange) onChange(v);
    else if (ns && k) setField(ns, k, v, { flush: true });
  };
  return html`<div class=${cx("field", sm && "sm", disabled && "disabled", cls)}
      style=${width ? `width:${typeof width === "number" ? width + "px" : width}` : undefined} ...${tip(title)}>
    <select id=${id} value=${value ?? ""} onChange=${change} disabled=${!!disabled}>
      ${opts.map((o) => html`<option value=${o.value} disabled=${o.disabled}>${o.label}</option>`)}
    </select>
    <span class="caret">▾</span>
  </div>`;
}

export function Seg({ value, options, onChange, ns, k, disabled }) {
  const opts = (options || []).map((o) => (typeof o === "object" ? o : { value: o, label: String(o) }));
  const pick = (v) => {
    if (onChange) onChange(v);
    else if (ns && k) setField(ns, k, v, { flush: true });
  };
  return html`<div class="seg" role="radiogroup">
    ${opts.map((o) => html`<button type="button" role="radio" aria-checked=${o.value === value}
      class=${o.value === value ? "on" : ""} disabled=${disabled || o.disabled}
      onClick=${() => pick(o.value)} ...${tip(o.title)}>${o.label}</button>`)}
  </div>`;
}

export function Check({ checked, onChange, ns, k, label, disabled, title, wrap, cls = "", children }) {
  const change = (e) => {
    const v = e.target.checked;
    if (onChange) onChange(v);
    else if (ns && k) setField(ns, k, v, { flush: true });
  };
  return html`<label class=${cx("chk", wrap && "wrap-ok", disabled && "disabled", cls)} ...${tip(title)}>
    <input type="checkbox" checked=${!!checked} disabled=${!!disabled} onChange=${change} />
    <span>${label}${children}</span>
  </label>`;
}

export function Radio({ checked, onChange, name, label, disabled, title, value }) {
  return html`<label class=${cx("chk", disabled && "disabled")} ...${tip(title)}>
    <input type="radio" name=${name} value=${value} checked=${!!checked} disabled=${!!disabled}
      onChange=${(e) => e.target.checked && onChange && onChange(value)} />
    <span>${label}</span>
  </label>`;
}

export function Chip({ kind = "", dot, children, title, sm, onClick }) {
  if (onClick) {
    return html`<button type="button" class=${cx("chip", kind, sm && "sm")} style="cursor:pointer;background:none" onClick=${onClick} ...${tip(title)}>${dot ? html`<span class="dot"></span>` : null}${children}</button>`;
  }
  return html`<span class=${cx("chip", kind, sm && "sm")} ...${tip(title)}>${dot ? html`<span class="dot"></span>` : null}${children}</span>`;
}

export function Card({ title, sub, extra, children, footer, cls = "", bodyCls = "", style, bodyStyle, head }) {
  return html`<section class=${cx("card", cls)} style=${style}>
    ${title || extra || head ? html`<div class="hd">${head || html`<span class="h2">${title}</span>${sub ? html`<span class="muted small">${sub}</span>` : null}<span class="sp"></span>${extra}`}</div>` : null}
    <div class=${cx("bd", bodyCls)} style=${bodyStyle}>${children}</div>
    ${footer ? html`<div class="ft">${footer}</div>` : null}
  </section>`;
}

const NOTE_ICON = { warn: "warn", err: "error", ok: "check", info: "info", "": "info" };
export function Note({ kind = "", children, icon, action }) {
  return html`<div class=${cx("note", kind)}><${Icon} name=${icon || NOTE_ICON[kind] || "info"} />
    <div class="body-text">${children}</div>${action}</div>`;
}

export function Empty({ icon = "info", title, children, action }) {
  return html`<div class="empty"><${Icon} name=${icon} cls="xl" />${title ? html`<div class="h2">${title}</div>` : null}
    ${children ? html`<div class="small" style="max-width:520px">${children}</div>` : null}${action}</div>`;
}

export function Progress({ pct, busy }) {
  return html`<div class=${cx("prog", busy && "busy")}><i style=${`width:${busy ? 30 : Math.max(0, Math.min(100, pct || 0))}%`}></i></div>`;
}

export function Spinner() { return html`<span class="spin" role="status" aria-label="Working"></span>`; }

export function PageHead({ title, sub, children }) {
  return html`<div class="pagehead"><div class="grow"><h1 class="h1">${title}</h1>${sub ? html`<p>${sub}</p>` : null}</div>
    ${children ? html`<div class="actions">${children}</div>` : null}</div>`;
}

// ----------------------------------------------------------------- table
// columns: [{key, label, width: "120px" | "minmax(0,1fr)", num, render(row), sort, title}]
// A virtual list: only the rows in view are in the DOM, so 3 000 rows scroll
// smoothly.  rowKey(row) -> stable id; selected: id or Set of ids.
// resizable: drag a header's right edge; widths = {key: px} saved widths;
// onResize(widths) gets every column's px after a drag (Tk saved the dragged
// widths under column_widths).  The last column always takes what is left.
export function Table({ columns, rows, rowKey = (r, i) => i, selected, onSelect, onActivate,
                        rowClass, sort, onSort, empty, rowHeight = 34, cls = "", style,
                        onContext, header = true, multi, resizable, widths, onResize }) {
  const scroller = useRef(null);
  const headRef = useRef(null);
  const [view, setView] = useState({ top: 0, h: 600 });
  const [live, setLive] = useState(null);
  const wmap = live || widths || null;
  const template = columns.map((c, i) => (i === columns.length - 1 ? (c.width && !/px$/.test(c.width) ? c.width : "minmax(0,1fr)")
    : wmap && wmap[c.key] ? Math.max(36, wmap[c.key]) + "px" : (c.width || "minmax(0,1fr)"))).join(" ");
  const startResize = (e, idx) => {
    e.preventDefault(); e.stopPropagation();
    const z = pageZoom();
    const cells = headRef.current ? [...headRef.current.children] : [];
    const start = {};
    columns.forEach((c, i) => { if (cells[i]) start[c.key] = cells[i].getBoundingClientRect().width / z; });
    const x0 = e.clientX, key = columns[idx].key, w0 = start[key] || 80;
    let cur = { ...start };
    const move = (ev) => { cur = { ...start, [key]: Math.max(36, Math.round(w0 + (ev.clientX - x0) / z)) }; setLive(cur); };
    const up = () => {
      window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up);
      setLive(null);
      const out = {};
      columns.slice(0, -1).forEach((c) => { if (cur[c.key]) out[c.key] = Math.round(cur[c.key]); });
      if (onResize) onResize(out);
    };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  const onScroll = () => {
    const el = scroller.current;
    if (el) setView({ top: el.scrollTop, h: el.clientHeight });
  };
  useLayoutEffect(() => {
    onScroll();
    const el = scroller.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(onScroll);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const isSel = (id) => (selected instanceof Set ? selected.has(id) : selected === id);
  const n = rows ? rows.length : 0;
  const first = Math.max(0, Math.floor(view.top / rowHeight) - 10);
  const last = Math.min(n, Math.ceil((view.top + view.h) / rowHeight) + 10);
  const slice = [];
  for (let i = first; i < last; i++) slice.push(i);
  // keep the selected row in view when it changes from outside
  const selKey = selected instanceof Set ? null : selected;
  useEffect(() => {
    if (selKey == null || !scroller.current || !rows) return;
    const idx = rows.findIndex((r, i) => rowKey(r, i) === selKey);
    if (idx < 0) return;
    const el = scroller.current;
    const y = idx * rowHeight;
    if (y < el.scrollTop) el.scrollTop = y;
    else if (y + rowHeight > el.scrollTop + el.clientHeight - rowHeight) el.scrollTop = y - el.clientHeight + rowHeight * 2;
  }, [selKey]);
  const onKey = (e) => {
    if (!rows || !n || !onSelect) return;
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Enter") return;
    e.preventDefault();
    let idx = rows.findIndex((r, i) => rowKey(r, i) === selKey);
    if (e.key === "Enter") { if (idx >= 0 && onActivate) onActivate(rows[idx], idx); return; }
    idx = e.key === "ArrowDown" ? Math.min(n - 1, idx + 1) : Math.max(0, idx - 1);
    onSelect(rows[idx], idx, e);
  };
  return html`<div class=${cx("tbl", cls)} style=${style}>
    <div class="scroller" ref=${scroller} onScroll=${onScroll} tabindex="0" onKeyDown=${onKey}>
      ${header ? html`<div class="tr th" ref=${headRef} style=${`grid-template-columns:${template}`}>
        ${columns.map((c, ci) => html`<span class=${cx("c", c.num && "num")} style="position:relative;overflow:visible" ...${tip(c.title)}>${c.sort && onSort
          ? html`<button type="button" onClick=${() => onSort(c.sort)}>${c.label}${sort && sort.key === c.sort ? (sort.desc ? " ▼" : " ▲") : ""}</button>`
          : c.label}${resizable && ci < columns.length - 1 ? html`<span class="col-grip" aria-hidden="true" onMouseDown=${(e) => startResize(e, ci)}></span>` : null}</span>`)}
      </div>` : null}
      ${n === 0 ? (empty || null) : html`<div style=${`height:${n * rowHeight}px;position:relative`}>
        ${slice.map((i) => {
          const r = rows[i];
          const id = rowKey(r, i);
          return html`<div key=${id} class=${cx("tr", (onSelect || onActivate) && "click", isSel(id) && "sel", rowClass && rowClass(r, i))}
            style=${`grid-template-columns:${template};position:absolute;left:0;right:0;top:${i * rowHeight}px;height:${rowHeight}px`}
            onClick=${(e) => onSelect && onSelect(r, i, e)}
            onDblClick=${() => onActivate && onActivate(r, i)}
            onContextMenu=${onContext ? (e) => { e.preventDefault(); onContext(r, i, e); } : undefined}>
            ${columns.map((c) => html`<span class=${cx("c", c.num && "num", c.cls)} title=${c.titleOf ? c.titleOf(r) : undefined}>${c.render ? c.render(r, i) : r[c.key]}</span>`)}
          </div>`;
        })}
      </div>`}
    </div>
  </div>`;
}

// ------------------------------------------------------------------ menus
let menuHost = null;
export function openMenu(anchor, items, { align = "left" } = {}) {
  closeMenu();
  menuHost = document.createElement("div");
  document.body.appendChild(menuHost);
  const r = anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : { left: anchor.x, bottom: anchor.y, right: anchor.x, top: anchor.y };
  const close = () => closeMenu();
  const onDoc = (e) => { if (menuHost && !menuHost.contains(e.target)) close(); };
  const onEsc = (e) => { if (e.key === "Escape") close(); };
  setTimeout(() => { document.addEventListener("mousedown", onDoc); document.addEventListener("keydown", onEsc); }, 0);
  menuHost._cleanup = () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onEsc); };
  const Menu = () => {
    const ref = useRef(null);
    useLayoutEffect(() => {
      const el = ref.current;
      if (!el) return;
      const z = pageZoom();
      const R = { left: r.left / z, right: r.right / z, top: r.top / z, bottom: r.bottom / z };
      const vw = window.innerWidth / z, vh = window.innerHeight / z;
      let x = align === "right" ? R.right - el.offsetWidth : R.left;
      let y = R.bottom + 4;
      x = Math.max(8, Math.min(vw - el.offsetWidth - 8, x));
      if (y + el.offsetHeight > vh - 8) y = Math.max(8, R.top - el.offsetHeight - 4);
      el.style.left = x + "px"; el.style.top = y + "px";
      const first = el.querySelector("button:not(:disabled)");
      if (first) first.focus();
    }, []);
    const [sub, setSub] = useState(null);           // {items, top, left}
    const openSub = (e, it) => {
      const z = pageZoom();
      const r2 = e.currentTarget.getBoundingClientRect();
      const vw = window.innerWidth / z;
      // flip to the left when there is no room on the right
      const right = r2.right / z + 2, left = r2.left / z - 242;
      setSub({ items: it.submenu, top: r2.top / z - 6, left: right + 240 > vw && left > 8 ? left : right, key: it.label });
    };
    return html`<div class="menu" ref=${ref} role="menu" style="left:-9999px;top:0">
      ${items.filter(Boolean).map((it) => it.sep ? html`<div class="msep"></div>`
        : it.header ? html`<div class="mh eyebrow">${it.header}</div>`
        : it.submenu ? html`<button type="button" role="menuitem" aria-haspopup="true" class="mi" disabled=${!!it.disabled}
            onMouseEnter=${(e) => openSub(e, it)} onClick=${(e) => openSub(e, it)}
            onKeyDown=${(e) => { if (e.key === "ArrowRight") openSub(e, it); }}>
            ${it.icon ? html`<${Icon} name=${it.icon} />` : null}<span>${it.label}</span><span class="k">▸</span></button>`
        : html`<button type="button" role="menuitem" class="mi" disabled=${!!it.disabled} onMouseEnter=${() => setSub(null)}
            onClick=${() => { close(); it.onClick && it.onClick(); }} ...${tip(it.title)}>
            ${it.checked != null ? html`<span style="width:14px">${it.checked ? "✓" : ""}</span>` : it.icon ? html`<${Icon} name=${it.icon} />` : null}
            <span>${it.label}</span>${it.kbd ? html`<span class="k">${it.kbd}</span>` : null}</button>`)}
      ${sub ? html`<div class="menu" role="menu" key=${sub.key}
          style=${`left:${Math.min(sub.left, window.innerWidth / pageZoom() - 240)}px;top:${Math.max(8, Math.min(sub.top, window.innerHeight / pageZoom() - 40 - 32 * sub.items.length))}px`}>
        ${sub.items.filter(Boolean).map((it) => it.sep ? html`<div class="msep"></div>`
          : it.header ? html`<div class="mh eyebrow">${it.header}</div>`
          : html`<button type="button" role="menuitem" class="mi" disabled=${!!it.disabled}
              onClick=${() => { close(); it.onClick && it.onClick(); }} ...${tip(it.title)}>
              ${it.checked != null ? html`<span style="width:14px">${it.checked ? "✓" : ""}</span>` : it.icon ? html`<${Icon} name=${it.icon} />` : null}
              <span>${it.label}</span>${it.kbd ? html`<span class="k">${it.kbd}</span>` : null}</button>`)}
      </div>` : null}
    </div>`;
  };
  render(html`<${Menu} />`, menuHost);
}
export function closeMenu() {
  if (menuHost) {
    if (menuHost._cleanup) menuHost._cleanup();
    render(null, menuHost);
    menuHost.remove();
    menuHost = null;
  }
}

// ----------------------------------------------------------------- modal
// A page-local dialog (the tab owns its open/closed state).
export function menuOpen() { return !!menuHost; }
// Escape and Enter belong to the dialog on top: the last .scrim in the page.
export function isTopScrim(el) {
  if (!el) return false;
  const all = document.querySelectorAll(".scrim");
  return all.length > 0 && all[all.length - 1] === el;
}

export function Modal({ title, icon, onClose, wide, xwide, children, footer, cls = "" }) {
  const scrimRef = useRef(null);
  useEffect(() => {
    // Escape closes an open menu first, not the dialog under it
    const onKey = (e) => {
      if (e.key !== "Escape" || !onClose || menuHost || !isTopScrim(scrimRef.current)) return;
      e.preventDefault(); onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return html`<div class="scrim" ref=${scrimRef} onMouseDown=${(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
    <div class=${cx("modal", wide && "wide", xwide && "xwide", cls)} role="dialog" aria-modal="true" aria-label=${title}>
      <div class="hd">${icon ? html`<${Icon} name=${icon} cls="lg" />` : null}<span class="h2">${title}</span>
        ${onClose ? html`<${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${onClose} />` : null}</div>
      <div class="bd">${children}</div>
      ${footer ? html`<div class="ft">${footer}</div>` : null}
    </div>
  </div>`;
}

// ---------------------------------------------------------------- helpers
export function fmtBytes(n) {
  if (n == null || isNaN(n)) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0; let v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i === 0 ? v : v.toFixed(v < 10 ? 1 : 0)) + " " + u[i];
}
export function fmtClock(sec) {
  if (sec == null || isNaN(sec)) return "";
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}
export function mediaUrl(path) {
  const t = new URLSearchParams(location.search).get("t") || "";
  return "/media?t=" + encodeURIComponent(t) + "&p=" + encodeURIComponent(path);
}
export { call, setField };
