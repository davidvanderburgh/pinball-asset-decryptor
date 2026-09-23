// Replace Text: the editable on-screen strings (text/strings.tsv) with an
// in-place editor.  Python owns the rows, the filters, the sort and every
// rule (webui/tabs/text.py, webui/text_rules.py); this draws them.

import { html, useState, useEffect, useRef, useMemo, PageHead, Card, Button, Field, Select, Seg,
         Check, Chip, Table, Empty, Modal, openMenu, InfoBadge, tip, Spinner, call, cx }
  from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

// Wording from the Tk tab (gui/main_window.py _build_text_tab).
const INTRO_HEAD = "Edit the words shown on the machine's display — high scores, menu labels, status text, "
  + "and the game program's own strings.";
const INTRO = "Edit the words shown on the machine's display — high scores, menu labels, status text, and the "
  + "game program's own strings (mode titles, battle names — Scene column: \"game program\"). Pick your extracted folder, click a string, type the new text, and Apply. Each "
  + "replacement must fit its byte budget (the Max column; a game-program row marked \"96 (grows)\" may take "
  + "longer text — it is placed in a new area of the game program when you build an image). Some names are "
  + "the tail end of a longer line (EBIRAH inside GODZILLA VS EBIRAH) — edit both rows so the line ends with "
  + "the new name, or use Replace everywhere… to change a word in every row at once. Build the update on the "
  + "Write tab when you're done.";
const TIP_REPLACE = "Find / Replace across the whole list: every row whose ORIGINAL text contains the word gets "
  + "the replacement (EBIRAH → BIOLLANTE reaches the battle title, its tail row and the settings caption in one "
  + "go). Rows whose new text would not fit their Max are listed and skipped, not applied. Opened from a row you "
  + "have already edited, Find and Replace are pre-filled with the one word you changed.";
const TIP_SCENES = "Open the Scenes window on the scene that draws the selected line, with the line picked out — "
  + "so you can see it in place, and recolour it there. Stern Spike 2.";
const TIP_SHOW = "Narrow the list by what you've already done to it. Changed = the lines you have edited (they "
  + "show your new text and are written on the next build). Unchanged = everything you haven't touched yet, so a "
  + "part-finished pass is what's left in front of you instead of something to scroll past.";
const TIP_SCENE = "Narrow the list to one screen's worth of text. \"Game program\" is the text the game code draws "
  + "itself (mode titles, battle names) — everything else is one scene file, listed with how many strings it "
  + "holds. A scene's folder name never changes, so a name you give it (right-click a row → Name this scene…) "
  + "sticks, and it's the same name the Images tab shows for that scene.";
const TIP_APPLY_ALL = "Matches scenes by the selected row's ORIGINAL (as-extracted) text, not its current edited "
  + "value. Rows you've already changed to read the same thing keep their own original and aren't affected.";
const TIP_FOLDER = "The project folder — shared by every tab. It is set on the Extract tab. Click to open it.";
const SAVED_NOTE = "Your edits are saved to text/strings.tsv as you Apply them and are written to the card "
  + "automatically when you build the update on the Write tab — no extra step.";
const REPLACE_NOTE = "Every row whose ORIGINAL text contains the word gets the replacement — a battle title, its "
  + "bare-name tail row and its settings caption in one go. Rows whose new text would not fit their Max are "
  + "listed below and skipped.";

const COLUMNS = [
  { key: "o", label: "On-Screen Text", width: "minmax(0,1.25fr)", sort: "#0", cls: "pre",
    titleOf: (r) => r.o },
  { key: "n", label: "New Text", width: "minmax(0,1fr)", sort: "new", cls: "pre",
    render: (r) => (r.ed ? html`<span class="acc-ink">${r.n}</span>` : r.n), titleOf: (r) => r.n || undefined },
  { key: "mx", label: "Max", width: "92px", sort: "max", cls: "mono small" },
  // wide enough for "49ac2…71dd/scene.radium" (Tk: 170 px of a smaller font)
  { key: "sc", label: "Scene", width: "212px", sort: "scene", cls: "mono small dim", titleOf: (r) => r.sc },
  { key: "nm", label: "Name", width: "minmax(0,.7fr)", sort: "name", titleOf: (r) => r.nm || undefined },
];

function editorValue(wrap) {
  const el = wrap && wrap.querySelector("input");
  return el ? el.value : null;
}

export default function TextTab() {
  const s = useNs("text");
  const editRef = useRef(null);
  const [replace, setReplace] = useState(null);     // {find, repl}
  const [rename, setRename] = useState(null);       // {index, prompt, value}

  const rows = s.rows || [];
  const view = s.view || [];
  const shown = useMemo(() => view.map((i) => rows[i]).map((r, n) => (r ? { ...r, i: view[n] } : null))
    .filter(Boolean), [rows, view]);

  const focusEditor = () => {
    const el = editRef.current && editRef.current.querySelector("input");
    if (el && !el.disabled) { el.focus(); el.select(); }
  };
  const apply = () => {
    if (!s.can_edit) return;
    const v = editorValue(editRef.current);
    call("text.apply", v == null ? s.new : v);
  };
  const openReplace = async (index) => {
    const init = await call("text.replace_open", index ?? null);
    if (init) setReplace(init);
  };
  const openRename = async (index) => {
    const p = await call("text.rename_prompt", index ?? null);
    if (p) setRename(p);
  };
  const rowMenu = (r, i, e) => {
    call("text.select", r.i);
    openMenu({ x: e.clientX, y: e.clientY }, [
      { label: "Edit…", icon: "edit", onClick: () => setTimeout(focusEditor, 60) },
      { label: "Replace everywhere…", onClick: () => openReplace(r.i) },
      { label: "Show in Scenes…", onClick: () => call("text.show_in_scene", r.i) },
      { label: "Name this scene…", onClick: () => openRename(r.i) },
      ...(r.ed ? [{ sep: true }, { label: "Revert this string", icon: "undo",
        onClick: () => call("text.select", r.i).then(() => call("text.revert")) }] : []),
    ]);
  };

  const total = s.total || 0;
  // s.empty is set for every "nothing to list" state Python knows about (no
  // folder, none found, cancelled — the last one even with rows loaded, as
  // Tk's list went blank); otherwise the filters hid everything.
  const empty = s.scanning
    ? html`<${Empty} icon="search" title=${s.empty}><${Spinner} /><//>`
    : s.empty || total === 0
      ? html`<${Empty} icon="text">${s.empty}<//>`
      : html`<${Empty} icon="search">${s.status}<//>`;

  return html`<div class="page text-page">
    <${PageHead} title="Text" sub=${html`${INTRO_HEAD} <${InfoBadge} text=${INTRO} />`}>
      ${total ? html`<${Chip} kind=${s.edited ? "acc" : ""}>${s.status}<//>` : null}
      <${Button} onClick=${() => call(s.scanning ? "text.cancel_scan" : "text.scan")}
        icon=${s.scanning ? "x" : "refresh"}>${s.scanning ? "Cancel scan" : "Scan"}<//>
      <${Button} kind="ghost" title=${TIP_REPLACE} onClick=${() => openReplace(null)}>Replace everywhere…<//>
      <${Button} kind="ghost" title=${TIP_SCENES} onClick=${() => call("text.show_in_scene", null)}>Show in Scenes…<//>
      <${Button} kind="ghost" onClick=${() => call("text.clear_all")}>Clear all edits<//>
    <//>

    <div class="row text-folder">
      <span class="lbl nw">Project Folder:</span>
      ${s.folder
        ? html`<button type="button" class="linkish mono" onClick=${() => call("text.open_folder")} ...${tip(TIP_FOLDER + "\n" + s.folder)}>${s.folder}</button>`
        : html`<span class="muted small" ...${tip(TIP_FOLDER)}>(no project yet — extract into one on the Extract tab)</span>`}
    </div>

    <${Card} cls="text-card" bodyCls="flush text-body" footer=${html`<${Editor} s=${s} editRef=${editRef} apply=${apply} />`}>
      <div class="toolbar">
        <${Field} cls="search" ns="text" k="search" value=${s.search} placeholder="Search"
          prefix=${html`<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5" /></svg>`} />
        <span class="lbl" ...${tip(TIP_SHOW)}>Show</span>
        <${Seg} value=${s.change_filter || "All"} options=${["All", "Changed", "Unchanged"]}
          onChange=${(v) => call("text.set_show", v)} />
        <span class="lbl">Scene</span>
        <${Select} cls="text-scene" value=${s.scene_filter} options=${s.scene_options || []} title=${TIP_SCENE}
          onChange=${(v) => call("text.set_scene", v)} />
        <span class="sp"></span>
      </div>
      <${Table} cls="text-table" columns=${COLUMNS} rows=${shown} rowKey=${(r) => r.i} selected=${s.sel}
        onSelect=${(r) => call("text.select", r.i)} onActivate=${(r) => call("text.select", r.i).then(() => setTimeout(focusEditor, 30))}
        onContext=${rowMenu} sort=${{ key: (s.sort || {}).col, desc: (s.sort || {}).desc }}
        onSort=${(k) => call("text.sort_by", k)} empty=${empty}
        resizable widths=${s.col_widths} onResize=${(w) => call("text.save_widths", w)} />
    <//>

    ${replace ? html`<${ReplaceDialog} init=${replace} onClose=${() => setReplace(null)} />` : null}
    ${rename ? html`<${RenameDialog} p=${rename} onClose=${() => setRename(null)} />` : null}
    ${/* the Fonts and Scenes windows are hosted by the shell (shell.js) */ null}
  </div>`;
}

// ------------------------------------------------------------- the editor
function Editor({ s, editRef, apply }) {
  const on = !!s.can_edit;
  return html`<div class="text-editor">
    <div class="text-edit-grid">
      <label class="lbl nw">Original:</label>
      <${Field} value=${s.orig} readOnly mono cls="pre-field" />
      <label class="lbl nw" for="text-new">New text:</label>
      <div ref=${editRef} class="grow" onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); apply(); } }}>
        <${Field} id="text-new" ns="text" k="new" value=${s.new} disabled=${!on} mono delay=${120}
          bad=${on && s.budget_over} cls="pre-field" />
      </div>
    </div>
    <div class="row wrap text-edit-actions">
      <span class=${cx("small mono", s.budget_over ? "err-ink" : "dim")}>${s.budget || ""}</span>
      <span class="text-saved-i"><${InfoBadge} text=${SAVED_NOTE} /></span>
      <${Check} ns="text" k="apply_all" checked=${s.apply_all} title=${TIP_APPLY_ALL}
        label="Apply to every scene with the same original text" />
      <span class="grow"></span>
      <${Button} icon="undo" disabled=${!on} onClick=${() => call("text.revert")}>Revert<//>
      <${Button} kind="primary" disabled=${!on || s.budget_over} onClick=${apply}>Apply<//>
    </div>
    ${s.scene_note ? html`<div class="small muted text-scene-note">${s.scene_note}</div>` : null}
    <p class="muted small text-saved">${SAVED_NOTE}</p>
  </div>`;
}

// ------------------------------------------------ Replace everywhere… dialog
function ReplaceDialog({ init, onClose }) {
  const [find, setFind] = useState(init.find || "");
  const [repl, setRepl] = useState(init.repl || "");
  const [matchCase, setCase] = useState(true);
  const [plan, setPlan] = useState(null);
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      call("text.replace_plan", find, repl, matchCase).then((p) => { if (live) setPlan(p); });
    }, 90);
    return () => { live = false; clearTimeout(t); };
  }, [find, repl, matchCase]);
  const apply = () => {
    if (!plan || !plan.can_apply) return;
    onClose();
    call("text.replace_apply", find, repl, matchCase);
  };
  const misfits = (plan && plan.misfits) || [];
  const cols = [
    { key: "o", label: "Won't fit — original", width: "minmax(0,1fr)", cls: "pre", titleOf: (r) => r.o },
    { key: "n", label: "Would become", width: "minmax(0,1fr)", cls: "pre", titleOf: (r) => r.n },
    { key: "b", label: "Bytes", width: "56px", num: true },
    { key: "mx", label: "Max", width: "88px", cls: "mono small" },
    { key: "sc", label: "Scene", width: "150px", cls: "mono small dim" },
  ];
  const rows = plan && plan.more ? [...misfits, { o: "… and " + plan.more + " more", n: "", b: "", mx: "", sc: "" }] : misfits;
  return html`<${Modal} title="Replace everywhere" wide onClose=${onClose}
      footer=${html`<${Button} onClick=${onClose}>Cancel<//><${Button} kind="primary" disabled=${!plan || !plan.can_apply} onClick=${apply}>Apply<//>`}>
    <div onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); apply(); } }} class="stack" style="gap:10px">
      <p class="small dim text-italic" style="margin:0">${REPLACE_NOTE}</p>
      <div class="text-find-grid">
        <label class="lbl nw" for="tr-find" style="grid-area:fl">Find:</label>
        <div style="grid-area:ff;min-width:0"><${Field} id="tr-find" value=${find} onChange=${setFind} autoFocus=${!init.find} /></div>
        <div style="grid-area:mc"><${Check} checked=${matchCase} onChange=${setCase} label="Match case" /></div>
        <label class="lbl nw" for="tr-repl" style="grid-area:rl">Replace with:</label>
        <div style="grid-area:rf;min-width:0"><${Field} id="tr-repl" value=${repl} onChange=${setRepl} autoFocus=${!!init.find} /></div>
      </div>
      <div class="small">${plan ? plan.text : ""}</div>
      <${Table} cls="text-misfits" columns=${cols} rows=${rows} rowKey=${(r, i) => i} rowHeight=${30} />
    </div>
  <//>`;
}

// ----------------------------------------------------- Name this scene…
function RenameDialog({ p, onClose }) {
  const [name, setName] = useState(p.value || "");
  const ok = () => { onClose(); call("text.set_scene_name", p.index, name); };
  return html`<${Modal} title="Name this scene" onClose=${onClose}
      footer=${html`<${Button} onClick=${onClose}>Cancel<//><${Button} kind="primary" onClick=${ok}>OK<//>`}>
    <div class="stack" onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); ok(); } }}>
      <div class="msg">${p.prompt}</div>
      <${Field} value=${name} onChange=${setName} autoFocus />
    </div>
  <//>`;
}

