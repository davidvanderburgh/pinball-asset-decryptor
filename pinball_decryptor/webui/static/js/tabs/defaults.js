// Defaults tab (the Tk "Default Settings" tab): presets, the curated
// settings form, the High Scores block, every setting on the image, and
// opening the machine's own menu up to the hidden ones.  Python owns the
// rows and does the staging (webui/tabs/defaults.py); this draws them and
// sends edits (ui.set "val:<AD name>" / "hs:<slot>:<field>", debounced).

import { html, useEffect, useRef, useState, Button, Card, Check, Field, Select, Note, Empty, Table,
         Modal, PageHead, InfoBadge, Spinner, Icon, tip, call, setField, openMenu, menuOpen, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;
const NS = "defaults";

const CARD_TIP = "The master card image these defaults are read from — it is set on the Extract tab.";
const AUTO_TIP = "When on, the selected preset's defaults are baked into every card you build on the Write "
  + "tab automatically — only the settings a given game actually has are applied, so one preset works "
  + "across titles. Save a preset first to enable this.";
const RESET_TIP = "Put every field back to the image's current defaults and clear anything staged for the next Build.";
const ONCARD_TIP = "The default currently baked into this image — Stern's factory value unless it was changed here before.";
const NEWDEF_TIP = "What the machine will use on a fresh flash or after a factory reset, once saved to the image.";
const HS_TIP = "The board the machine starts with on a fresh flash or after a factory reset — Stern ships it "
  + "filled with the design team's initials. A machine that already has scores stored keeps them and ignores these.";
const HS_ONCARD_TIP = "The default score currently baked into this image — Stern's factory value unless it was changed here before.";
const HS_SCORE_TIP = "What the machine will seed this place with on a fresh flash or after a factory reset.";
const ALL_TIP = "Every adjustment the firmware carries, with the caption the machine itself prints. Double-click "
  + "one to set the default it ships with — including the ones the machine's menus never show. Click a column "
  + "header to sort by it (values sort as numbers, biggest first); click the same header a third time for the "
  + "firmware's own order back.";
const HIDDEN_TIP = "Leaves the settings the machine's Adjustments menu can't reach: the ones it edits on another "
  + "service screen, and the factory/debug ones it never shows at all.";
const MENU_TIP = "Extends the machine's Feature Adjustments page so the settings below can be found and changed "
  + "on the machine itself, instead of only being preset from here.";
const FRESH_TIP = "A machine uses these defaults on a fresh flash or after a factory reset. A machine that has "
  + "already been set up keeps its own settings — Stern stores those on the board, not on the card, so the app "
  + "cannot change a machine that's already configured.";

// ------------------------------------------------------------ edits
function sendVal(name, v) {
  return setField(NS, "val:" + name, v, { delay: 200, flush: true });
}
function commit() { return call(NS + ".commit"); }

// Tk sized a spinner from the adjustment's widest value (feedback batch 22).
const spinWidth = (chars) => `calc(${Math.min(chars || 8, 16)}ch + 40px)`;
const fieldId = (name) => "dflt-v-" + name;

// One setting's "New default" editor: a tick, a dropdown or a spinner.
function Editor({ row, value }) {
  const name = row.name;
  if (row.ui === "toggle") {
    return html`<label class="chk dflt-tog" ...${tip(row.help || undefined)}>
      <input type="checkbox" checked=${!!value}
        onChange=${(e) => sendVal(name, e.target.checked ? 1 : 0)}
        onBlur=${commit} aria-label=${row.label} />
      <span>On</span></label>`;
  }
  if (row.ui === "enum") {
    const opts = row.options || [];
    const inRange = opts.some((o) => o.value === value);
    // a shipped default outside the range has no option: the box shows blank
    // (Tk left its combobox empty rather than pick the wrong end)
    const list = inRange ? opts : [{ value: "", label: "", disabled: true }, ...opts];
    return html`<div class="dflt-sel" onFocusOut=${commit}>
      <${Select} sm id=${fieldId(name)} value=${inRange ? value : ""} options=${list}
        onChange=${(v) => { if (v !== "") sendVal(name, Number(v)); }} /></div>`;
  }
  return html`<${Field} ns=${NS} k=${"val:" + name} id=${fieldId(name)} type="number" mono sm cls="dflt-in"
    value=${value} min=${row.lo} max=${row.hi} step=${row.step} width=${spinWidth(row.chars)}
    delay=${200} onCommit=${commit} />`;
}

// ---------------------------------------------------------- form
function Dot({ on }) {
  return html`<span class=${cx("dflt-dot", on && "on")} aria-label=${on ? "changed" : undefined}>${on ? "●" : ""}</span>`;
}

function changed(values, name, dflt) {
  const v = values ? values[name] : undefined;
  return v != null && v !== dflt;
}

function SettingsForm({ s }) {
  const values = s.values || {};
  return html`<div class="dflt-grid dflt-form" role="table" aria-label="Settings">
    <div class="dflt-tr dflt-th" role="row">
      <span role="columnheader">Setting</span>
      <span role="columnheader" ...${tip(ONCARD_TIP)}>On card</span>
      <span role="columnheader" ...${tip(NEWDEF_TIP)}>New default</span>
      <span></span>
      <span role="columnheader">Range</span>
    </div>
    ${(s.form || []).map((it, i) => {
      if (it.type === "group") return html`<div key=${"g" + i} class="dflt-group eyebrow" role="row">${it.label}</div>`;
      const st = it.status === "service" ? html`<span class="dflt-st info-ink">Service menu</span>`
        : it.status === "debug" ? html`<span class="dflt-st warn-ink">Debug</span>` : null;
      // the name labels its box (a tick labels itself: clicking the name must not toggle it)
      const lbl = it.ui === "toggle"
        ? html`<span class=${cx("dflt-lbl", it.help && "has-tip")} ...${tip(it.help)}>${it.label}${st}</span>`
        : html`<label for=${fieldId(it.name)} class=${cx("dflt-lbl", it.help && "has-tip")} ...${tip(it.help)}>${it.label}${st}</label>`;
      return html`<div key=${it.name} class=${cx("dflt-tr", changed(values, it.name, it.default) && "chg")} role="row">
          ${lbl}
          <span class="dflt-card">${it.on_card}</span>
          <span class="dflt-ed"><${Editor} row=${it} value=${values[it.name]} /></span>
          <${Dot} on=${changed(values, it.name, it.default)} />
          <span class="dflt-rng">${it.range}</span>
        </div>`;
    })}
  </div>`;
}

function HighScores({ s }) {
  const values = s.values || {};
  const hv = s.hs_values || [];
  // the cells a slot without a score keeps empty (the Range one hides in a narrow window)
  const noScore = [html`<span class="dflt-card"></span>`, html`<span class="dflt-ed"></span>`,
    html`<span></span>`, html`<span class="dflt-rng"></span>`];
  const score = (sc, display) => sc ? [
    html`<span class="dflt-card">${sc.on_card}</span>`,
    html`<label class="dflt-ed"><span class="sr">${display} default score</span>
      <${Field} ns=${NS} k=${"val:" + sc.name} type="number" mono sm cls="dflt-in" value=${values[sc.name]}
        min=${sc.lo} max=${sc.hi} step=${sc.step} width=${spinWidth(sc.chars)} delay=${200} onCommit=${commit} /></label>`,
    html`<${Dot} on=${changed(values, sc.name, sc.default)} />`,
    html`<span class="dflt-rng">${sc.range}</span>`,
  ] : noScore;
  const text = (it, field, cur, cls, width) => {
    const cap = it[field + "_max"];
    return html`<label class="dflt-hsf"><span class="sr">${it.display + (field === "initials" ? " initials" : " player name")}</span>
      <${Field} ns=${NS} k=${"hs:" + it.index + ":" + field} value=${cur} sm cls=${cls} width=${width}
        maxLength=${Math.max(0, cap)} disabled=${cap <= 0} title=${it[field + "_tip"]} delay=${200}
        onCommit=${commit} /></label>`;
  };
  return html`<div class="dflt-grid dflt-hs" role="table" aria-label="High Scores">
    <div class="dflt-tr dflt-th" role="row">
      <span role="columnheader">Slot</span>
      <span role="columnheader">Initials</span>
      <span role="columnheader">Player name</span>
      <span role="columnheader" ...${tip(HS_ONCARD_TIP)}>On card</span>
      <span role="columnheader" ...${tip(HS_SCORE_TIP)}>Default score</span>
      <span></span>
      <span role="columnheader" class="dflt-h-rng">Range</span>
    </div>
    ${(s.hs || []).map((it, i) => {
      if (it.type === "score") {
        return html`<div key=${"x" + i} class=${cx("dflt-tr", it.score && changed(values, it.score.name, it.score.default) && "chg")} role="row">
          <span class="dflt-lbl">${it.display}</span><span></span><span></span>${score(it.score, it.display)}</div>`;
      }
      const cur = hv[it.index] || {};
      const ch = (cur.initials != null && cur.initials !== it.card_initials)
        || (cur.name != null && cur.name !== it.card_name)
        || (it.score && changed(values, it.score.name, it.score.default));
      return html`<div key=${"s" + i} class=${cx("dflt-tr", ch && "chg")} role="row">
        <span class="dflt-lbl">${it.display}</span>
        ${text(it, "initials", cur.initials, "dflt-in",
               `calc(${Math.max(3, Math.min(5, it.initials_max + 1))}ch + 40px)`)}
        ${text(it, "name", cur.name, "dflt-in dflt-name")}
        ${score(it.score, it.display)}
      </div>`;
    })}
  </div>`;
}

// ------------------------------------------------------- all settings
const MENU_CLS = { "Service menu": "info-ink", "Debug": "warn-ink", "Adjustments": "muted" };

// Dragged column widths live for the session, as a Tk Treeview's did (Tk
// never saved these).
let allWidths = null;

function AllSettings({ s, onEdit, blocked }) {
  const [sel, setSel] = useState(null);
  const [widths, setWidths] = useState(allWidths);
  const cols = [
    { key: "caption", label: "Setting", width: "minmax(220px, 2.4fr)", sort: "setting",
      titleOf: (r) => r.caption },
    { key: "value", label: "On card", width: "minmax(90px, 1fr)", sort: "value", titleOf: (r) => r.value },
    { key: "new", label: "New default", width: "minmax(90px, 1fr)", sort: "new",
      render: (r) => r.new ? html`<span class="acc-ink">${r.new}</span>` : "", titleOf: (r) => r.new || undefined },
    { key: "range", label: "Range", width: "minmax(110px, 1.3fr)", sort: "range", titleOf: (r) => r.range },
    { key: "menu", label: "Menu", width: "112px", sort: "status",
      render: (r) => html`<span class=${MENU_CLS[r.menu] || ""}>${r.menu}</span>` },
  ];
  // While a dialog is up the list behind it takes no keys (Tk's grab_set):
  // an arrow or Enter that reached it would swap the open editor's setting.
  return html`<${Table} cls="dflt-all" columns=${cols} rows=${s.all || []} rowKey=${(r) => r.name}
    selected=${sel} onSelect=${(r) => { if (!blocked) setSel(r.name); }}
    onActivate=${(r) => { if (!blocked) { setSel(r.name); onEdit(r.name); } }}
    sort=${s.sort && s.sort.key ? s.sort : null} onSort=${(k) => call(NS + ".sort_all", k)}
    rowClass=${(r) => r.new ? "dflt-staged" : ""}
    resizable widths=${widths} onResize=${(w) => { allWidths = w; setWidths(w); }}
    empty=${null} />`;
}

// ------------------------------------------------------------ dialogs
const FOCUSABLE = "button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])";

// A dialog owns the keyboard while it is open, as Tk's grab_set did: focus
// starts on its editor (*first*, a selector inside *box*), Tab stays inside
// it, Return presses its default action (Tk's dlg.bind("<Return>")) unless a
// focused button is pressing itself, and focus goes back where it was after.
function useDialogKeys(box, first, onEnter) {
  const enter = useRef(onEnter);
  enter.current = onEnter;
  useEffect(() => {
    const prev = document.activeElement;
    const root = box.current;
    const dlg = root ? root.closest(".modal") : null;
    const el = root && first ? root.querySelector(first) : null;
    if (el) {
      el.focus({ preventScroll: true });
      if (el.tagName === "INPUT" && el.type !== "checkbox" && typeof el.select === "function") el.select();
    }
    const onKey = (e) => {
      if (!dlg || menuOpen() || e.isComposing) return;
      if (e.key === "Enter" && enter.current) {
        const t = e.target;
        if (t && t.tagName === "BUTTON" && dlg.contains(t)) return;
        e.preventDefault();
        // after the field's own Enter (and a dropdown's change) has landed
        setTimeout(() => enter.current && enter.current(), 0);
      } else if (e.key === "Tab") {
        const f = [...dlg.querySelectorAll(FOCUSABLE)];
        if (!f.length) return;
        const i = f.indexOf(document.activeElement);
        if (i < 0 || (!e.shiftKey && i === f.length - 1) || (e.shiftKey && i === 0)) {
          e.preventDefault();
          (e.shiftKey ? f[f.length - 1] : f[0]).focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (prev && prev.isConnected && typeof prev.focus === "function") prev.focus({ preventScroll: true });
    };
  }, []);
}

function EditModal({ info, onClose }) {
  const [v, setV] = useState(info.cur);
  const [bad, setBad] = useState(false);
  const cur = useRef(info.cur);
  const box = useRef(null);
  const put = (x) => { cur.current = x; setV(x); setBad(false); };
  const ok = async () => {
    const r = await call(NS + ".edit_apply", info.name, cur.current, false);
    // Tk's OK did nothing on a value that is no number at all; the box says so
    if (r) onClose(); else setBad(true);
  };
  const back = async () => { await call(NS + ".edit_apply", info.name, null, true); onClose(); };
  useDialogKeys(box, "input:not(:disabled), select:not(:disabled)", ok);
  let editor;
  if (info.ui === "toggle") {
    editor = html`<${Check} checked=${!!Number(v)} label="On" onChange=${(c) => put(c ? 1 : 0)} />`;
  } else if (info.ui === "enum") {
    const opts = info.options || [];
    const inRange = opts.some((o) => o.value === Number(v));
    editor = html`<${Select} value=${inRange ? Number(v) : ""} width=${260}
      options=${inRange ? opts : [{ value: "", label: "", disabled: true }, ...opts]}
      onChange=${(x) => { if (x !== "") put(Number(x)); }} />`;
  } else {
    editor = html`<${Field} type="number" mono value=${v} min=${info.lo} max=${info.hi} step=${info.step}
      width=${spinWidth(info.chars)} bad=${bad} onChange=${put} />`;
  }
  return html`<${Modal} title="Default setting" onClose=${onClose}
    footer=${html`<${Button} onClick=${back}>Back to card value<//><span class="grow"></span>
      <${Button} onClick=${onClose}>Cancel<//><${Button} kind="primary" onClick=${ok}>OK<//>`}>
    <div class="stack dflt-edit" ref=${box}>
      <div class="h2">${info.caption}</div>
      <div class="muted small mono">${info.name}</div>
      <div class="small dflt-ws">${info.on_card}</div>
      <div class="muted small">${info.fresh}</div>
      ${info.note ? html`<div class="muted small">${info.note}</div>` : null}
      ${info.ui === "toggle"
        ? html`<div class="row" style="margin-top:6px"><span>New default:</span>${editor}</div>`
        : html`<label class="row" style="margin-top:6px"><span>New default:</span>${editor}</label>`}
    </div>
  <//>`;
}

function MenuModal({ info, onClose }) {
  const [sel, setSel] = useState(info.pre);
  const [widths, setWidths] = useState(null);
  const box = useRef(null);
  const item = (info.items || []).find((c) => c.name === sel);
  const apply = async () => { if (!sel) return; await call(NS + ".menu_apply", sel); onClose(); };
  const clear = async () => { await call(NS + ".menu_clear"); onClose(); };
  // Tk's dialog had no Return binding: keys move the list, buttons act
  useDialogKeys(box, ".dflt-menu-tbl .scroller", null);
  const rows = info.items || [];
  const h = Math.min(10, Math.max(1, rows.length)) * 34 + 34;
  return html`<${Modal} title="Show hidden settings in the machine's menu" wide onClose=${onClose}
    footer=${html`<${Button} onClick=${clear}>Leave the menu alone<//><span class="grow"></span>
      <${Button} onClick=${onClose}>Cancel<//><${Button} kind="primary" disabled=${!sel} onClick=${apply}>Show them<//>`}>
    <div class="stack" style="gap:10px" ref=${box}>
      <div class="dflt-pre">${info.text}</div>
      <${Note} kind="warn">${info.caveat}<//>
      <${Table} columns=${[
        { key: "label", label: "Show through this setting", width: "minmax(0,1fr)", titleOf: (r) => r.label },
        { key: "id", label: "Id", width: "minmax(56px, 80px)", cls: "mono" }]}
        rows=${rows} rowKey=${(r) => r.name} selected=${sel} onSelect=${(r) => setSel(r.name)}
        onActivate=${(r) => { setSel(r.name); }} style=${`height:${h}px`} cls="dflt-menu-tbl"
        resizable widths=${widths} onResize=${setWidths} />
      <div class="muted small">${item ? `The machine will show ${item.n} setting(s) it normally hides, ending at "${item.label}".` : ""}</div>
    </div>
  <//>`;
}

// The Preset picker: Tk's read-only combobox lists only the saved names and
// loads the one picked EVERY time, the current one included (a native
// <select> reports only a change of value, so it could not reload it).
function PresetPicker({ presets, value }) {
  const has = presets.includes(value);
  const open = (e) => {
    const at = e.currentTarget;
    openMenu(at, presets.map((p) => ({
      label: p, checked: p === value,
      onClick: () => { at.focus({ preventScroll: true }); call(NS + ".pick_preset", p); } })));
  };
  return html`<button type="button" class=${cx("field dflt-pick", !presets.length && "disabled")}
      disabled=${!presets.length} aria-haspopup="menu" aria-label=${"Preset" + (has ? ": " + value : "")}
      onClick=${open} onKeyDown=${(e) => { if (e.key === "ArrowDown") { e.preventDefault(); open(e); } }}>
    <span class="grow ellip">${has ? value : ""}</span><span class="caret">▾</span>
  </button>`;
}

// --------------------------------------------------------------- page
function StateBody({ s }) {
  if (s.phase === "loading") {
    return html`<div class="empty dflt-loading"><${Spinner} /><div class="h2">${s.message}</div></div>`;
  }
  if (s.phase === "error") {
    return html`<${Note} kind="err">${s.message}<//>`;
  }
  if (s.phase === "ready" && !(s.form || []).length) {
    return html`<div class="muted dflt-msg">${s.message}</div>`;
  }
  if (s.phase !== "ready") {
    return html`<${Empty} icon="defaults">${s.message}<//>`;
  }
  return html`<${SettingsForm} s=${s} />`;
}

export default function DefaultsTab() {
  const s = useNs(NS);
  const [modal, setModal] = useState(null);
  const presets = s.presets || [];
  const hasPreset = presets.includes(s.preset);
  const openEdit = async (name) => {
    const info = await call(NS + ".edit_info", name);
    if (info) setModal({ kind: "edit", info });
  };
  const openMenuDialog = async () => {
    const info = await call(NS + ".menu_info");
    if (info) setModal({ kind: "menu", info });
  };
  const close = () => setModal(null);
  const showAll = (s.all_total || 0) > 0;
  const showHs = (s.hs || []).length > 0;
  return html`<div class="page dflt">
    <${PageHead} title="Defaults"
      sub="Preset the operator-adjustment defaults baked into a card image. A machine uses them on a fresh flash or after a factory reset.">
      <${InfoBadge} text=${FRESH_TIP} />
      <${Button} icon="undo" disabled=${!s.reset_enabled} title=${RESET_TIP} onClick=${() => call(NS + ".reset")}>Reset Fields<//>
    <//>

    <${Card} cls="dflt-top">
      <div class="kv dflt-kv">
        <span class="k">Card Image</span>
        <span class="mono ellip dflt-path" ...${tip(CARD_TIP)}>${s.image || html`<span class="muted">—</span>`}</span>
        <span class="k">Preset</span>
        <div class="row wrap dflt-presets">
          <${PresetPicker} presets=${presets} value=${s.preset} />
          <${Button} onClick=${() => call(NS + ".save_preset")}>Save As…<//>
          <${Button} kind="ghost" icon="trash" disabled=${!hasPreset} onClick=${() => call(NS + ".delete_preset")}>Delete<//>
          <${Check} checked=${!!s.autoapply} disabled=${!s.auto_enabled} title=${AUTO_TIP} wrap
            label="Apply this preset automatically to every card I build"
            onChange=${(v) => call(NS + ".toggle_auto", v)} />
        </div>
      </div>
      ${s.status ? html`<div class="dflt-status" role="status"><${Icon} name="info" /><span>${s.status}</span></div>` : null}
    <//>

    <${Card} title="Settings" cls="dflt-card-form">
      <${StateBody} s=${s} />
    <//>

    ${showHs ? html`<${Card} cls="dflt-card-hs" head=${html`<span class="h2" ...${tip(HS_TIP)}>High Scores</span>
        <${InfoBadge} text=${HS_TIP} />`}>
      <${HighScores} s=${s} />
    <//>` : null}

    ${showAll ? html`<${Card} cls="dflt-card-all" bodyCls="flush"
        head=${html`<span class="h2" ...${tip(ALL_TIP)}>All settings on this image</span>
          <${Check} ns=${NS} k="hidden_only" checked=${!!s.hidden_only} title=${HIDDEN_TIP}
            label="Only settings not in the Adjustments menu" />
          <span class="sp"></span>
          <${Button} disabled=${!s.menu_enabled} title=${MENU_TIP} onClick=${openMenuDialog}>Show hidden settings in the machine's menu…<//>`}
        footer=${s.all_legend ? html`<span class="muted small">${s.all_legend}</span>` : null}>
      <${AllSettings} s=${s} onEdit=${openEdit} blocked=${!!modal} />
    <//>` : null}

    ${modal && modal.kind === "edit" ? html`<${EditModal} key=${modal.info.name} info=${modal.info} onClose=${close} />` : null}
    ${modal && modal.kind === "menu" ? html`<${MenuModal} info=${modal.info} onClose=${close} />` : null}
  </div>`;
}
