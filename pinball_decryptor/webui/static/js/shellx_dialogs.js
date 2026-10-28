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
         Progress, Spinner, Check, cx, tip, menuOpen } from "./core/ui.js";
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
// A section is [title, blocks, anchor]; webui/tips_render.py makes the blocks (PAD-386, the
// end of the wall of text): p / h (runs), ul / ol, table (cells may carry a yes / no /
// not-yet chip), note (a callout), cards (a row of coloured cards) and flow (steps joined
// by arrows).  A run is [kind, text] (t, b, i, c) or ["a", text, anchor], a jump inside
// the window.
function Runs({ r, go }) {
  return (r || []).map((x) => {
    const [k, s] = x;
    if (k === "b") return html`<b>${s}</b>`;
    if (k === "i") return html`<i>${s}</i>`;
    if (k === "c") return html`<code>${s}</code>`;
    if (k === "a") return html`<a class="sx-tips-a" role="button" tabindex="0" onClick=${() => go(x[2])}
      onKeyDown=${(e) => { if (e.key === "Enter") go(x[2]); }}>${s}</a>`;
    return s;
  });
}

const CHIP_ICON = { yes: "check", no: "x", part: "minus" };
function Cell({ c, go }) {
  if (!c.chip) return html`<${Runs} r=${c.r} go=${go} />`;
  const rest = c.r && c.r.length;
  return html`<span class=${cx("sx-chip", c.chip, !c.label && "solo")}><${Icon} name=${CHIP_ICON[c.chip]} />${c.label}</span>${rest ? " " : null}${rest ? html`<${Runs} r=${c.r} go=${go} />` : null}`;
}

function Blocks({ bs, go }) {
  return (bs || []).map((b) => html`<${Block} b=${b} go=${go} />`);
}

function Block({ b, go }) {
  switch (b.t) {
    case "p": return html`<p><${Runs} r=${b.r} go=${go} /></p>`;
    case "h": return html`<h4 id=${"tipa-" + b.id}><${Runs} r=${b.r} go=${go} /></h4>`;
    case "ul": return html`<ul class="sx-tips-list">${b.items.map((r) => html`<li><${Runs} r=${r} go=${go} /></li>`)}</ul>`;
    case "ol": return html`<ol class="sx-tips-list sx-tips-steps">${b.items.map((r) => html`<li><${Runs} r=${r} go=${go} /></li>`)}</ol>`;
    case "table": return html`<div class="sx-tips-tablewrap"><table class="sx-tips-table">
      <thead><tr>${b.head.map((h) => html`<th><${Runs} r=${h} go=${go} /></th>`)}</tr></thead>
      <tbody>${b.rows.map((row) => html`<tr>${row.map((c) => html`<td><${Cell} c=${c} go=${go} /></td>`)}</tr>`)}</tbody>
    </table></div>`;
    case "note": return html`<div class=${cx("sx-tips-note", b.kind === "warn" && "warn")}>
      <${Icon} name=${b.kind === "warn" ? "warn" : "info"} /><div class="grow"><${Blocks} bs=${b.b} go=${go} /></div></div>`;
    case "cards": return html`<div class="sx-tips-cards">${b.items.map((c) => html`<div class=${cx("sx-tips-card", c.tone)}>
      <span class="sx-tips-ic"><${Icon} name=${c.icon} /></span>
      <div class="grow"><span class="sx-tips-card-t">${c.title}</span><div><${Runs} r=${c.r} go=${go} /></div></div></div>`)}</div>`;
    case "flow": return html`<ol class="sx-tips-flow">${b.items.map((c, i) => html`<li>
      ${i ? html`<span class="sx-tips-arrow" aria-hidden="true"><${Icon} name="right" /></span>` : null}
      <div class="sx-tips-step"><span class="sx-tips-ic">${c.icon ? html`<${Icon} name=${c.icon} />` : i + 1}</span>
        <b>${c.title}</b><span><${Runs} r=${c.r} go=${go} /></span></div></li>`)}</ol>`;
    default: return null;
  }
}

// the open Tips window's "show this tab, at this anchor" (a second open hands it over)
let tipsGo = null;

// The green ? window (help_dialog.TabHelpWindow): the tab's own sections,
// then "General".  Not modal, like Tk's: it floats beside the page and
// follows the tab that is showing.  *tab* and *anchor* open it on a tab at a
// section or heading (the Modes tab's "What a mode can and can't do").
function TipsPanel({ close, tab, anchor }) {
  const dup = useSingleton("tips", close);
  const shell = useNs("shell");
  const railTab = (shell.tabs || []).find((t) => t.ns === shell.tab);
  const [picked, setPicked] = useState(tab || null);
  const [want, setWant] = useState(anchor || null);
  const key = picked || (railTab && railTab.key) || "Extract";
  const [data, setData] = useState(null);
  const body = useRef(null);
  const seenTab = useRef(shell.tab);
  useEffect(() => {
    if (shell.tab !== seenTab.current) { seenTab.current = shell.tab; setPicked(null); }
  }, [shell.tab]);
  useEffect(() => {
    if (dup) { if (tipsGo && (tab || anchor)) tipsGo(tab, anchor); return undefined; }
    const mine = (t, a) => { if (t) setPicked(t); if (a) setWant(a); };
    tipsGo = mine;
    return () => { if (tipsGo === mine) tipsGo = null; };
  }, []);
  useEffect(() => {
    let live = true;
    call("shellx.tips", key).then((d) => { if (live && d) { setData(d); if (body.current) body.current.scrollTop = 0; } });
    return () => { live = false; };
  }, [key, shell.lang]);
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
  const scrollTo = (el) => { if (el && body.current) body.current.scrollTop = el.offsetTop - 8; };
  const jump = (id) => scrollTo(body.current && body.current.querySelector("#" + id));
  const go = (a) => scrollTo(body.current && body.current.querySelector("#tipa-" + CSS.escape(a)));
  useEffect(() => {
    if (!want || !data || data.tab !== key) return;
    go(want);
    setWant(null);
  }, [data, want]);
  if (dup) return null;
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
        ${sections.map(([t, b, a], i) => html`<section id=${"tip-" + i}><h3 id=${"tipa-" + a}>${t}</h3><${Blocks} bs=${b} go=${go} /></section>`)}
        ${data ? html`<div class="sx-rule eyebrow">General</div>` : null}
        ${general.map(([t, b, a], i) => html`<section id=${"gen-" + i}><h3 id=${"tipg-" + a}>${t}</h3><${Blocks} bs=${b} go=${go} /></section>`)}
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
      <span class="h2">Automatic clean-up</span>
      <${Check} checked=${!d || d.auto_on !== false} disabled=${!d} label="Clean up automatically"
        onChange=${(v) => call("shellx.disk_set_auto", v)} />
      <span class="small muted wrap">${d ? d.auto_note : ""}</span>
      <div class="row wrap"><span class="small grow">${d ? d.auto_summary : ""}</span>
        <${Button} onClick=${() => call("shellx.disk_tidy_now")} disabled=${!(d && d.can_tidy)}>Clean up now<//></div>
    </div>
    <hr class="sx-hr" />
    <div class="stack" style="gap:4px">
      <span class="h2">Leftover staging, caches and emulator files</span>
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

// ------------------------------------------------------- Reset…
// PAD-569 (DragonRR): the project menu's Reset… (PAD-576) — the kinds of change in the open project,
// ticked, put back the way they were extracted (shellx_reset.py).  The Write tab's "Revert
// all changes…" opens it with every kind ticked (`all`).
function ResetDialog({ close, all = false }) {
  const dup = useSingleton("reset", close);
  const r = useNs("shellx").reset;
  const [ticked, setTicked] = useState(() => new Set());
  useEffect(() => { if (!dup) call("shellx.reset_open"); }, []);
  useEffect(() => {
    if (all && r && r.rows) setTicked(new Set(r.rows.map((x) => x.key)));
  }, [all, !!(r && r.rows)]);
  const shut = () => { call("shellx.reset_close"); close(); };
  const [uid, onClose] = useWin(shut);
  if (dup) return null;
  const rows = (r && r.rows) || [];
  const every = rows.length > 0 && rows.every((x) => ticked.has(x.key));
  const flip = (key, on) => {
    const next = new Set(ticked);
    if (on) next.add(key); else next.delete(key);
    setTicked(next);
  };
  const go = async () => {
    const ok = await call("shellx.reset_run", rows.filter((x) => ticked.has(x.key)).map((x) => x.key));
    if (ok) close();
  };
  const count = (x) => r && r.busy && !x.n ? "counting…" : x.n ? `${x.n} change${x.n === 1 ? "" : "s"}` : "nothing to reset";
  return html`<${Modal} title=${"Reset " + ((r && r.name) || "project") + "…"} icon="refresh" wide onClose=${onClose} cls=${cx(uid, "sx-reset")}
    footer=${html`<span class="grow small dim ellip" title=${r ? r.folder : ""}>${r ? r.folder : ""}</span>
      <${Button} onClick=${shut}>Cancel<//>
      <${Button} kind="danger" disabled=${!ticked.size || !(r && r.ok) || (r && r.running)} onClick=${go}>${every ? "Reset everything…" : "Reset…"}<//>`}>
    <p class="sx-p muted">${r ? r.intro : ""}</p>
    <${Note} kind="warn">${r ? r.warning : ""}<//>
    ${r && r.base_note ? html`<${Note} kind="info"><b>${r.base_note.head}.</b> ${r.base_note.lines.join(" ")}<//>` : null}
    ${r && !r.ok ? html`<${Note} kind="err">Open a project first: there is no project folder to reset.<//>` : null}
    <div class="stack sx-reset-list" style="gap:6px">
      <${Check} checked=${every} disabled=${!rows.length} onChange=${(v) => setTicked(new Set(v ? rows.map((x) => x.key) : []))}
        label=${html`<b>Everything</b><span class="small muted"> — the project as it was extracted</span>`} />
      <hr class="sx-hr" />
      ${rows.map((x) => html`<div class="sx-reset-row">
        <${Check} checked=${ticked.has(x.key)} onChange=${(v) => flip(x.key, v)} label=${x.label} />
        <span class=${cx("small", x.n ? "warn-ink" : "dim")}>${count(x)}</span>
        <div class="small muted sx-reset-detail">${x.detail}</div>
      </div>`)}
    </div>
  <//>`;
}
registerDialog("reset", ResetDialog);

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

// PAD-435: opened for the card just picked on Select card (extract.new_card_project), it
// comes filled in for that card and says why: the open project is another card's.
function NewProjectDialog({ close, stock: forCard = "", name: suggested = "", parent: near = "", mfr: cardMfr = "", why = null }) {
  const [form, setForm] = useState(null);
  const [parent, setParent] = useState("");
  const [name, setName] = useState(suggested);
  const [mfr, setMfr] = useState("");
  const [stock, setStock] = useState(forCard);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [uid, onClose] = useWin(close);
  useEffect(() => {
    call("shellx.project_form").then((f) => {
      if (!f || f.running) { close(); return; }
      setForm(f); setParent(near || f.parent || ""); setMfr(cardMfr || f.mfr || "");
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
  return html`<${Modal} title=${why ? "New project for this card" : "New project"} icon="plus" wide onClose=${onClose} cls=${uid}
    footer=${html`<${Button} onClick=${close}>${why && why.project ? "Stay in " + why.project : "Cancel"}<//><${Button} kind="primary" busy=${busy} disabled=${busy} onClick=${create}>Create<//>`}>
    ${why ? html`<${Note} kind="warn">The card you picked, <b>${why.card}</b>, is not the one ${why.project ? html`project <b>${why.project}</b>` : "this project"} was extracted from${why.project_card ? html` (${why.project_card})` : ""}. Make a project of its own for it, so the tabs work on this card's files.<//>` : null}
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
        <div class="small muted ellip" title=${job.detail}>${job.cancelling ? "Canceling…" : job.detail || " "}</div></div>
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

// ------------------------------------------------------- Animal shelters
// PAD-754: the paw chip's window.  The app takes no money; people report
// what they gave to an animal shelter near them and the total everyone sees
// grows (webui/shellx_donations.py, core/donations.py).  `auto` is the
// once-only opening after a user's first card write.  Where the shelter is
// (country, state or province, both optional) feeds the Top places board.
//
// The page, with a little casino in it: the total spins in on slot reels,
// marquee lamps chase around the hero band, a drawn thermometer fills
// toward the next milestone, the ladder's milestones are lit badges, the
// top three places stand on a podium that rises in, and an entry landing
// is a jackpot: the band flashes, the lamps race, paw prints float off the
// button.  An entry is confirmed before it goes ("Is that right?"), and
// the Yours list takes one back (the service keeps a token per entry for
// the app that added it) and refills the form with it.  Colours are the
// app's tokens, so both themes carry it; prefers-reduced-motion stills it.

// a name's hue for its initials circle: the same name, the same colour
function nameHue(name) {
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
function initials(name) {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}
const SYMBOL = { USD: "$", EUR: "€", GBP: "£", JPY: "¥", CAD: "CA$", AUD: "A$", NZD: "NZ$", BRL: "R$", MXN: "MX$" };
function money(amount, currency) {
  const n = Number(amount);
  const text = Number.isInteger(n) ? n.toLocaleString("en-US") : n.toFixed(2);
  return (SYMBOL[currency] || currency + " ") + text;
}

// one slot reel: a strip of digits that always spins forward at least a
// full turn to land on its digit
const REEL_LEN = 40;
const REEL_DIGITS = Array.from({ length: REEL_LEN }, (_, i) => i % 10);
function Reel({ digit, delay }) {
  const ref = useRef({ pos: 0 });
  const [pos, setPos] = useState(0);
  const [go, setGo] = useState(false);
  useEffect(() => {
    const cur = ref.current.pos;
    let step = ((digit - (cur % 10)) + 10) % 10;
    if (step === 0) step = 10;
    if (cur + step < REEL_LEN) {
      ref.current.pos = cur + step; setGo(true); setPos(cur + step);
    } else {                                 // wrap unseen, then spin
      ref.current.pos = cur % 10; setGo(false); setPos(cur % 10);
      requestAnimationFrame(() => requestAnimationFrame(() => {
        ref.current.pos = (cur % 10) + step; setGo(true); setPos((cur % 10) + step);
      }));
    }
  }, [digit]);
  return html`<span class="sx-don-reel"><span class=${"strip" + (go ? " go" : "")}
      style=${"transform:translateY(" + (-pos) + "em);transition-delay:" + delay + "ms"}>${REEL_DIGITS.map((n) => html`<span>${n}</span>`)}</span></span>`;
}
function Odometer({ text }) {
  let n = 0;
  return html`<span class="sx-don-total mono notr" aria-label=${text}>${[...String(text)].map((ch) =>
    /[0-9]/.test(ch) ? html`<${Reel} digit=${Number(ch)} delay=${90 * n++} />` : html`<span>${ch}</span>`)}</span>`;
}

function Thermometer({ pct }) {
  // the tube: x 31..49, y 14..234; the bulb sits on its foot
  const T = 14, H = 220, X = 31, W = 18;
  const inner = H - 8;
  const fill = Math.max(0, Math.min(100, pct || 0)) / 100;
  const mercH = inner * fill;
  const mercY = T + 4 + inner - mercH;
  return html`<svg class="sx-don-therm" viewBox="0 0 80 300" aria-hidden="true">
    ${[0.25, 0.5, 0.75].map((k) => html`<line class="tick" x1=${X + W + 4} x2=${X + W + 11} y1=${T + 4 + inner * (1 - k)} y2=${T + 4 + inner * (1 - k)} />`)}
    <rect class="tube" x=${X} y=${T} width=${W} height=${H} rx="9" />
    <rect class="merc" x=${X + 4} width=${W - 8} rx="5" style=${"y:" + mercY + "px;height:" + (mercH + 40) + "px"} />
    <circle class="bulb" cx=${X + W / 2} cy=${T + H + 20} r="24" />
    <circle class="bulb-shine" cx=${X + W / 2 - 8} cy=${T + H + 12} r="5" />
    <rect class="shine" x=${X + 3} y=${T + 8} width="3" height=${H - 30} rx="1.5" />
  </svg>`;
}

// the tile maps: a square per country (the list core/donations.py knows)
// and per US state, placed roughly where it sits, lit by what was given
// there.  [column, row].
const WORLD_TILES = {
  CA: [2, 1], US: [2, 2], MX: [2, 3], BR: [4, 5], AR: [4, 6],
  IE: [6, 1], GB: [7, 1], NL: [8, 1], DK: [9, 1], NO: [9, 0], SE: [10, 0], FI: [11, 0],
  FR: [7, 2], BE: [8, 2], DE: [9, 2], PL: [10, 2], CZ: [10, 3],
  PT: [6, 3], ES: [7, 3], CH: [8, 3], AT: [9, 3], HU: [11, 3], IT: [9, 4], GR: [11, 4],
  IL: [12, 4], AE: [13, 4], IN: [14, 4], ZA: [10, 7], KR: [15, 2], JP: [16, 2],
  SG: [15, 5], AU: [16, 6], NZ: [17, 7],
};
const WORLD_COLS = 18, WORLD_ROWS = 8;
const US_TILES = {
  AK: [0, 0], ME: [11, 0], WI: [6, 1], VT: [10, 1], NH: [11, 1],
  WA: [1, 2], ID: [2, 2], MT: [3, 2], ND: [4, 2], MN: [5, 2], IL: [6, 2], MI: [7, 2], NY: [9, 2], MA: [10, 2], RI: [11, 2],
  OR: [1, 3], NV: [2, 3], WY: [3, 3], SD: [4, 3], IA: [5, 3], IN: [6, 3], OH: [7, 3], PA: [8, 3], NJ: [9, 3], CT: [10, 3],
  CA: [1, 4], UT: [2, 4], CO: [3, 4], NE: [4, 4], MO: [5, 4], KY: [6, 4], WV: [7, 4], VA: [8, 4], MD: [9, 4], DE: [10, 4],
  AZ: [2, 5], NM: [3, 5], KS: [4, 5], AR: [5, 5], TN: [6, 5], NC: [7, 5], SC: [8, 5], DC: [9, 5],
  OK: [4, 6], LA: [5, 6], MS: [6, 6], AL: [7, 6], GA: [8, 6],
  HI: [0, 7], TX: [4, 7], FL: [8, 7],
};
const US_COLS = 12, US_ROWS = 8;
function TileMap({ tiles, cols, rows, data }) {
  const by = new Map((data || []).map((d) => [d.code, d]));
  const top = data && data.length ? data[0].usd : 0;
  return html`<div class="sx-don-map" style=${"grid-template-columns:repeat(" + cols + ",1fr);grid-template-rows:repeat(" + rows + ",1fr)"}>
    ${Object.keys(tiles).map((code) => {
      const d = by.get(code);
      const k = d && top ? Math.max(0.18, Math.sqrt(d.usd / top)) : 0;
      return html`<div class=${"sx-don-tile" + (d ? " lit" : "") + (k > 0.7 ? " hot" : "")} key=${code}
          style=${"grid-column:" + (tiles[code][0] + 1) + ";grid-row:" + (tiles[code][1] + 1) + ";--k:" + k.toFixed(2)}
          title=${d ? d.label + " · " + d.amount + " · " + d.count + (d.count === 1 ? " donation" : " donations") : ""}>
        <i></i><span class="notr">${code}</span></div>`;
    })}
  </div>`;
}

// the playground: a dog chasing a ball past a cat, in ASCII, because a
// window about animal shelters should have animals in it.  A tick every
// 170 ms; still under prefers-reduced-motion.
const PLAY_W = 62, PLAY_H = 3;
const DOG = [
  ["      ,_  ", " /\\__/ o\\ ", " \\_/\\_|\\_|"],
  ["      ,_  ", " /\\__/ o\\ ", " \\_//__// "],
];
const CAT = [
  [" /\\_/\\  ", "( o.o ) ", " > ^ <~ "],
  [" /\\_/\\  ", "( o.o ) ", " > ^ < ~"],
  [" /\\_/\\  ", "( O.O ) ", " > ^ <  "],
];
const BIRD = ["~v~", "-v-"];
function putSprite(grid, x, y, lines) {
  lines.forEach((ln, dy) => {
    const row = y + dy;
    if (row < 0 || row >= PLAY_H) return;
    for (let i = 0; i < ln.length; i++) {
      const col = x + i;
      if (col < 0 || col >= PLAY_W || ln[i] === " ") continue;
      grid[row][col] = ln[i];
    }
  });
}
function playFrame(t) {
  const grid = Array.from({ length: PLAY_H }, () => Array(PLAY_W).fill(" "));
  const lap = 70;                                     // ticks per run across
  const dogX = -12 + (t % lap);
  const catX = PLAY_W - 9;
  const near = dogX + 10 >= catX - 2 && dogX < catX + 4;
  const ballX = dogX + 13 + ((t >> 1) % 2);
  const ballY = [0, 1, 2, 1][t % 4];
  const birdX = PLAY_W - ((t * 2) % (PLAY_W + 30)) + 20;
  putSprite(grid, birdX, 0, [BIRD[(t >> 2) % 2]]);
  if (ballX < catX - 1) putSprite(grid, ballX, ballY, ["o"]);
  putSprite(grid, catX, 0, CAT[near ? 2 : (t >> 3) % 2]);
  putSprite(grid, dogX, 0, DOG[t % 2]);
  return grid.map((r) => r.join("")).join("\n");
}
function Playground() {
  const still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [t, setT] = useState(8);
  useEffect(() => {
    if (still) return undefined;
    const id = setInterval(() => setT((n) => n + 1), 170);
    return () => clearInterval(id);
  }, []);
  return html`<pre class="sx-don-play notr" aria-hidden="true">${playFrame(t)}</pre>`;
}

function Avatar({ name }) {
  if (!name || name === "Anonymous") {
    return html`<span class="sx-don-av anon"><${Icon} name="paw" /></span>`;
  }
  return html`<span class="sx-don-av notr" style=${"--h:" + nameHue(name)}>${initials(name)}</span>`;
}

function Podium({ places }) {
  const slots = [places[1], places[0], places[2]];
  const cls = ["p2", "p1", "p3"];
  const rank = [2, 1, 3];
  return html`<div class="sx-don-podium">
    ${slots.map((p, i) => html`<div class=${"sx-don-step " + cls[i] + (p ? "" : " empty")}>
      ${p ? html`<span class="who notr ellip" title=${p.where}>${p.where}</span>
        <span class="amt mono notr">${p.amount}</span>` : html`<span class="who dim">—</span>`}
      <div class="blk"><span class="mono">${rank[i]}</span></div>
    </div>`)}
  </div>`;
}

function DonationsDialog({ close, auto = false }) {
  const sx = useNs("shellx");
  const d = sx.donations || {};
  const [uid, onClose] = useWin(close);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState(d.currency || "USD");
  const [shelter, setShelter] = useState("");
  const [country, setCountry] = useState(d.country || "");
  const [region, setRegion] = useState(d.region || "");
  const [name, setName] = useState(d.name || "");
  const [showName, setShowName] = useState(true);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("form");    // form | confirm
  const [added, setAdded] = useState(0);
  const [hit, setHit] = useState(null);          // the jackpot: "+$30"
  const [mapOf, setMapOf] = useState("world");   // world | us
  const [hist, setHist] = useState(null);        // null, or {rows, total, next, busy, err}
  const loadHistory = async (offset) => {
    setHist((h) => ({ ...(h || { rows: [], total: 0, next: null }), busy: true, err: null }));
    const r = await call("shellx.donations_history", offset || 0);
    if (!r) { setHist((h) => ({ ...h, busy: false, err: "Couldn't reach the list just now." })); return; }
    setHist((h) => ({ rows: offset ? [...(h ? h.rows : []), ...r.rows] : r.rows, total: r.total, next: r.next, busy: false, err: null }));
  };
  useEffect(() => { call("shellx.donations_open", auto); }, []);
  useEffect(() => {
    if (!hit) return undefined;
    const id = setTimeout(() => setHit(null), 2200);
    return () => clearTimeout(id);
  }, [hit]);
  const review = () => {
    setErr(null);
    const n = Number(String(amount).replace(/[^0-9.]/g, ""));
    if (!String(amount).trim() || !isFinite(n) || n <= 0) { setErr("Enter the amount you gave."); return; }
    setStage("confirm");
  };
  const submit = async () => {
    setBusy(true);
    const r = await call("shellx.donations_submit", amount, currency, shelter, name, showName, country, region);
    setBusy(false);
    setStage("form");
    if (!r) return;                       // the toast said what was wrong
    const n = Number(String(amount).replace(/[^0-9.]/g, ""));
    setHit("+" + money(n, currency));
    setAdded((k) => k + 1); setAmount(""); setShelter("");
  };
  const takeBack = async (row) => {
    const e = await call("shellx.donations_remove", row.key);
    if (!e) return;
    setAmount(String(e.amount || "")); setCurrency(e.currency || "USD");
    setShelter(e.shelter || ""); setCountry(e.country || ""); setRegion(e.region || "");
    setName(e.name || ""); setShowName(e.show_name !== false);
    setStage("form"); setErr(null);
  };
  const recent = d.recent || [];
  const places = d.places || [];
  const mine = d.mine || [];
  const map = d.map || { world: [], us: [], elsewhere: null };
  const rest = places.slice(3, 10);
  const top = places.length ? places[0].usd : 0;
  const n = Number(String(amount).replace(/[^0-9.]/g, ""));
  const big = n * ((d.rates || {})[currency] || 1) > (d.hold_over || 299);   // checked by hand first
  const countryName = ((d.countries || []).find((c) => c.value === country) || {}).label || "";
  const where = country ? (region ? region + ", " + (country === "US" ? "US" : countryName) : countryName) : "";
  if (hist) {
    // every donation, newest first, a page at a time
    return html`<${Modal} title="All donations" icon="paw" wide onClose=${onClose} cls=${"sx-don " + uid}
      footer=${html`<span class="grow small dim notr">${hist.total ? hist.rows.length + " of " + hist.total : ""}</span>
        <${Button} onClick=${() => setHist(null)}>Back<//><${Button} kind="primary" onClick=${close}>Close<//>`}>
      <div class="sx-don-hist">
        <table class="sx-don-list sx-don-hist-table"><thead><tr><th>When</th><th>Who</th><th>Shelter</th><th></th></tr></thead><tbody>
          ${hist.rows.map((r, i) => html`<tr key=${i}>
            <td class="muted notr">${r.date}</td>
            <td><${Avatar} name=${r.name} /><span class="notr ellip">${r.name}</span></td>
            <td class="muted notr ellip" title=${r.where ? r.shelter + " (" + r.where + ")" : r.shelter}>${r.shelter}${r.where ? html` <span class="dim">· ${r.where}</span>` : null}</td>
            <td class="mono notr">${r.amount}</td></tr>`)}
          ${!hist.rows.length && !hist.busy ? html`<tr><td class="muted" colspan="4">${hist.err || "Nothing reported yet."}</td></tr>` : null}
        </tbody></table>
        ${hist.err && hist.rows.length ? html`<span class="small err-ink">${hist.err}</span>` : null}
        ${hist.busy ? html`<span class="small muted">Loading…</span>`
          : hist.next != null ? html`<div><${Button} onClick=${() => loadHistory(hist.next)}>Load more<//></div>` : null}
      </div>
    <//>`;
  }
  return html`<${Modal} title="Donate to an animal shelter" icon="paw" wide onClose=${onClose} cls=${"sx-don " + uid}
    footer=${html`<${Button} kind="ghost" onClick=${() => loadHistory(0)} disabled=${!d.known}>All donations<//>
      <span class="grow small dim wrap">${d.offline ? "The total can't be reached right now; this is the last it answered." : ""}</span>
      <${Button} onClick=${() => call("shellx.donations_refresh")}>Refresh<//><${Button} kind="primary" onClick=${close}>Close<//>`}>
    <div class="sx-don-nomoney" role="note">
      <${Icon} name="info" />
      <div><b>No money changes hands here.</b> PAD doesn't take donations, and nothing is charged or processed. You give directly to any animal shelter you choose, on your own terms. This window only keeps a running tally of what people say they gave.</div>
    </div>
    <p class="sx-p">${auto ? "Your card is written. " : ""}If PAD saved you money or time, give some of it to an animal shelter near you, then tell me here so it counts toward the tally.</p>
    <div class="sx-don-layout">
      <div class="sx-don-therm-col">
        <span class="small muted notr">${d.next_short || ""}</span>
        <${Thermometer} pct=${d.pct || 0} />
        <span class="small muted notr">${d.known ? d.last_text : ""}</span>
      </div>
      <div class="sx-don-main stack" style="gap:10px">
        <${Playground} />
        <div class=${"sx-don-hero" + (hit ? " hit" : "")}>
          <${Odometer} text=${d.known ? d.total_text : "—"} />
          <span class="stack" style="gap:2px">
            <span class="small muted">${d.known ? "raised by PAD users" : "No total yet."}</span>
            ${d.known ? html`<span class="chip acc sm notr" style="align-self:flex-start">${d.count_text}</span>` : null}
          </span>
          ${hit ? html`<span class="sx-don-plus mono notr" key=${added}>${hit}</span>` : null}
          <span class="sx-don-paw" aria-hidden="true"><${Icon} name="paw" /></span>
        </div>
        <span class="small muted sx-don-h">Milestones for the tally</span>
        <div class="sx-don-steps" role="list" aria-label="Milestones">
          ${(d.ladder || []).map((c, i) => html`<div class=${"sx-don-step-m " + c.state} role="listitem">
            ${i ? html`<i class="ln"></i>` : null}
            <span class="sx-don-dot">${c.state === "reached" ? html`<${Icon} name="check" />` : c.state === "next" ? html`<${Icon} name="paw" />` : html`<b></b>`}</span>
            <span class="lbl mono notr">${c.text}</span>
            <span class="sub">${c.state === "reached" ? (c.date ? html`reached <span class="notr">${c.date}</span>` : "reached") : c.state === "next" ? "next up" : "later"}</span>
          </div>`)}
        </div>
        <span class="small muted sx-don-h">Recent</span>
        <table class="sx-don-list"><tbody>
          ${recent.length ? recent.map((r) => html`<tr>
              <td><${Avatar} name=${r.name} /><span class="notr ellip">${r.name}</span></td>
              <td class="muted notr ellip" title=${r.where ? r.shelter + " (" + r.where + ")" : r.shelter}>${r.shelter}${r.where ? html` <span class="dim">· ${r.where}</span>` : null}</td>
              <td class="mono notr">${r.amount}</td></tr>`)
            : html`<tr><td class="muted" colspan="3">${d.known ? "Nothing reported yet. Be the first." : "No entries yet."}</td></tr>`}
        </tbody></table>
      </div>
      <div class="sx-don-side stack" style="gap:10px">
        ${places.length ? html`<span class="small muted sx-don-h">Top places</span>
          <${Podium} places=${places} />
          ${rest.length ? html`<div class="sx-don-places">
            ${rest.map((p, i) => html`<div class="sx-don-place">
              <span class="mono dim">${i + 4}</span>
              <span class="notr ellip" title=${p.where}>${p.where}</span>
              <div class="sx-bar"><i style=${"width:" + (top ? Math.max(4, Math.round(100 * p.usd / top)) : 0) + "%"}></i></div>
              <span class="mono notr">${p.amount}</span>
            </div>`)}
          </div>` : null}` : null}
        ${map.world.length ? html`<div class="row sx-don-map-head">
            <span class="small muted sx-don-h">Map</span>
            <span class="grow"></span>
            ${map.us.length ? html`<span class="sx-don-map-pick">
              <${Button} size="sm" kind=${mapOf === "world" ? "primary" : ""} onClick=${() => setMapOf("world")}>World<//>
              <${Button} size="sm" kind=${mapOf === "us" ? "primary" : ""} onClick=${() => setMapOf("us")}>United States<//>
            </span>` : null}
          </div>
          ${mapOf === "us" && map.us.length
            ? html`<${TileMap} tiles=${US_TILES} cols=${US_COLS} rows=${US_ROWS} data=${map.us} />`
            : html`<${TileMap} tiles=${WORLD_TILES} cols=${WORLD_COLS} rows=${WORLD_ROWS} data=${map.world} />`}
          <span class="small muted">${mapOf === "us" && map.us.length
            ? (map.us.length + (map.us.length === 1 ? " state" : " states") + " so far. Brighter is more.")
            : (map.world.length + (map.world.length === 1 ? " country" : " countries") + " so far. Brighter is more.")}${map.elsewhere ? html` <span class="notr">${map.elsewhere.amount}</span> from somewhere else.` : null}</span>` : null}
      </div>
      <div class="stack" style="gap:10px;min-width:0">
        <div class="card sx-don-form stack" style="gap:8px">
          ${stage === "confirm" ? html`
            <span class="h2">Is that right?</span>
            <div class="sx-don-confirm stack" style="gap:4px">
              <span class="sx-don-confirm-amt mono notr">${money(n, currency)}</span>
              <span class="small">${shelter.trim() ? html`to <b class="notr">${shelter.trim()}</b>` : "to an animal shelter"}${where ? html` in <span class="notr">${where}</span>` : null}</span>
              <span class="small muted">${name.trim() && showName ? html`listed as <span class="notr">${name.trim()}</span>` : "listed as Anonymous"}</span>
            </div>
            ${big ? html`<span class="small warn-ink wrap">An entry over $${(d.hold_over || 299).toLocaleString("en-US")} is checked by hand before it counts, so the total moves later.</span>` : null}
            <span class="small muted wrap">Nothing is charged. This only adds what you already gave to the tally everyone sees. You can take it back from the Yours list below.</span>
            <${Button} kind="primary" cls="sx-don-cta" onClick=${submit} disabled=${busy}>Yes, add it<//>
            <${Button} kind="ghost" onClick=${() => setStage("form")} disabled=${busy}>Edit<//>`
          : html`
            <span class="h2">I gave, on my own</span>
            <div class="row" style="gap:6px">
              <${Select} value=${currency} options=${d.currencies || ["USD"]} onChange=${setCurrency} width=${84} />
              <${Field} value=${amount} onChange=${setAmount} placeholder="25" mono width=${96} autoFocus bad=${!!err} />
            </div>
            <${Field} value=${shelter} onChange=${setShelter} placeholder="Shelter (optional)" maxLength=${80} />
            <${Select} value=${country} options=${d.countries || [{ value: "", label: "Country (optional)" }]} onChange=${setCountry} cls="sx-don-country" />
            <${Field} value=${region} onChange=${setRegion} placeholder="State or province (optional)" maxLength=${40} disabled=${!country} />
            <${Field} value=${name} onChange=${setName} placeholder="Your name (optional)" maxLength=${40} />
            <${Check} checked=${showName} onChange=${setShowName} label="Show my name in the list" />
            ${err ? html`<span class="small err-ink">${err}</span>` : null}
            <${Button} kind="primary" cls="sx-don-cta" onClick=${review} disabled=${busy}>Add to the tally<//>
            ${added ? html`<span class="small ok-ink">Thank you.</span>` : null}
            <span class="small muted wrap">Honor system. No payment here, and nothing else about you is sent.</span>`}
          ${added ? html`<div class="sx-don-burst" key=${added} aria-hidden="true">
            ${[0, 1, 2, 3, 4, 5, 6].map((i) => html`<i style=${"left:" + (8 + i * 13) + "%;animation-delay:" + (i * 70) + "ms;--r:" + ((i % 2 ? 1 : -1) * (10 + i * 7)) + "deg"}><${Icon} name="paw" /></i>`)}
          </div>` : null}
        </div>
        ${mine.length ? html`<span class="small muted sx-don-h">Yours</span>
          <div class="sx-don-mine">
            ${mine.map((m) => html`<div class="sx-don-mine-row" key=${m.key}>
              <span class="mono notr">${m.amount}</span>
              <span class="small muted ellip notr" title=${m.shelter + (m.where ? " (" + m.where + ")" : "")}>${m.shelter || "an animal shelter"}${m.where ? " · " + m.where : ""}</span>
              ${m.pending ? html`<span class="chip warn sm">waiting</span>` : m.held ? html`<span class="chip info sm" title="Checked by hand before it counts">in review</span>` : html`<span></span>`}
              <${Button} kind="ghost" size="sm" icon="x" title="Take it back and fix it" onClick=${() => takeBack(m)} />
            </div>`)}
          </div>` : null}
      </div>
    </div>
  <//>`;
}
registerDialog("donations", DonationsDialog);

// ------------------------------------------------------------ report a problem
// PAD-780: what happened in the user's words, the facts the developer
// always asks for next, an optional picture, the whole record to read
// before it goes, then Send (the app's service) or Save as a file
// (webui/shellx_report.py, core/problem_report.py).  `prefill` is the
// error box's words when its own link opened this.
function ReportDialog({ close, prefill = "" }) {
  const sx = useNs("shellx");
  const r = sx.report || {};
  const [uid, onClose] = useWin(close);
  const [info, setInfo] = useState(null);           // facts, log size, memory
  const [text, setText] = useState(prefill || "");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [hidePaths, setHidePaths] = useState(true);
  const [preview, setPreview] = useState(null);     // null, or the record's text
  const [showPreview, setShowPreview] = useState(false);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(false);      // while the window is being shot
  const [sentId, setSentId] = useState(null);
  useEffect(() => {
    (async () => {
      const i = await call("shellx.report_open", prefill || "");
      if (!i) return;
      setInfo(i);
      setName(i.name || ""); setEmail(i.email || ""); setHidePaths(i.hide_paths !== false);
      if (i.prefill && !text) setText(i.prefill);
    })();
  }, []);
  useEffect(() => {
    if (!showPreview) return undefined;
    const id = setTimeout(async () => {
      const p = await call("shellx.report_preview", text, name, email, hidePaths);
      if (p) setPreview(p.text);
    }, 300);
    return () => clearTimeout(id);
  }, [showPreview, text, name, email, hidePaths]);
  useEffect(() => {
    // the send finished off the loop: the service's answer, or why not
    if (!r.last || busy === false) return;
    setBusy(false);
    if (r.last.ok) setSentId(r.last.id || "sent");
    else setErr(r.last.error || "The report could not be sent.");
  }, [r.last, r.busy]);
  const picture = r.picture;
  const act = async (fn) => {
    setErr(null);
    try { return await fn(); } catch (e) { setErr(e && e.message ? e.message : String(e)); return null; }
  };
  const pick = () => act(() => call("shellx.report_picture", "pick"));
  const clearPic = () => act(() => call("shellx.report_picture", "clear"));
  const shoot = async () => {
    setHidden(true);
    await act(() => call("shellx.report_capture"));
    setHidden(false);
  };
  const send = async () => {
    setErr(null); setBusy(true);
    const ok = await act(() => call("shellx.report_send", text, name, email, hidePaths));
    if (!ok) setBusy(false);
  };
  const save = () => act(() => call("shellx.report_save", text, name, email, hidePaths));
  if (hidden) return null;
  if (sentId) {
    return html`<${Modal} title="Report a problem" icon="flag" onClose=${onClose} cls=${"sx-report " + uid}
      footer=${html`<${Button} kind="primary" onClick=${close}>Close<//>`}>
      <${Note} kind="ok">Sent. Thank you: it goes straight into the developer's queue, with the log and the card's details attached.${email ? " You'll hear back at " + email + " if a reply is needed." : ""}<//>
    <//>`;
  }
  const facts = (info && info.facts) || [];
  return html`<${Modal} title="Report a problem" icon="flag" wide onClose=${onClose} cls=${"sx-report " + uid}
    footer=${html`<${Button} kind="ghost" onClick=${save} disabled=${busy}>Save as a file…<//>
      <span class="grow"></span>
      <${Button} onClick=${close} disabled=${busy}>Cancel<//>
      <${Button} kind="primary" onClick=${send} busy=${busy} disabled=${busy || !r.available}>${busy ? "Sending…" : "Send"}<//>`}>
    <div class="stack" style="gap:10px">
      <p class="sx-p">Say what went wrong and what you expected. The app adds its version, your system, the card and project it has open, and the last ${(info && info.log_lines) || 0} lines of its log, so you don't have to.</p>
      <label class="lbl" for="sx-rep-text">What happened</label>
      <textarea id="sx-rep-text" class="area" rows="5" value=${text} autoFocus
        placeholder="I pressed Write on the Godzilla card and it stopped at 40% with…"
        onInput=${(e) => setText(e.target.value)}></textarea>
      <div class="row wrap" style="gap:14px">
        <span class="stack" style="gap:4px"><span class="lbl">Your name (optional)</span>
          <${Field} value=${name} onChange=${setName} width=${200} /></span>
        <span class="stack" style="gap:4px"><span class="lbl">Email, if you'd like an answer (optional)</span>
          <${Field} value=${email} onChange=${setEmail} width=${260} type="email" /></span>
      </div>
      <div class="row wrap" style="gap:10px">
        <span class="lbl">Picture</span>
        ${picture ? html`<span class="chip acc sm notr" title=${picture.name}>${picture.name} · ${picture.kb} KB</span>
            <${Button} size="sm" kind="ghost" onClick=${clearPic}>Remove<//>`
          : html`<${Button} size="sm" onClick=${pick}>Add a picture…<//>
            ${r.capture ? html`<${Button} size="sm" onClick=${shoot} title="Hides this window for a moment and takes a picture of the app">Take a picture of the app<//>` : null}`}
      </div>
      <${Check} checked=${hidePaths} onChange=${setHidePaths} label="Leave file paths and my account name out of the report" />
      <details class="sx-rep-facts" open=${showPreview} onToggle=${(e) => setShowPreview(e.target.open)}>
        <summary class="small">What will be sent</summary>
        ${preview === null ? html`<span class="small muted">Reading…</span>`
          : html`<pre class="sx-rep-pre mono small">${preview}</pre>`}
      </details>
      ${!showPreview && facts.length ? html`<table class="sx-rep-tab small"><tbody>
        ${facts.filter((f) => f[0] !== "History").map((f) => html`<tr><td class="muted">${f[0]}</td><td class="notr ellip" title=${f[1]}>${f[1]}</td></tr>`)}
      </tbody></table>` : null}
      ${!r.available ? html`<${Note} kind="warn">This copy of the app has no report service configured. Save the report as a file and attach it to a message instead.<//>` : null}
      <${ErrorNote} text=${err} />
      ${err && r.last && r.last.offline ? html`<${Note} kind="info">Save as a file writes the same report as a .zip you can attach to a Discord post or a mail.<//>` : null}
    </div>
  <//>`;
}
registerDialog("report", ReportDialog);

export { TipsPanel };
