// PAD-664: Rules sheet… - the printable rules sheet of the project's modes, made from the mode files
// (webui/modes_sheet.py; the words from plugins/stern/rules_sheet.py). On the left every mode with
// what the sheet says of it; Edit words opens its fields, each showing the app's words until you
// write your own (yours win; empty gives the app's back). On the right the sheet as it prints.
// PAD-695: Print… prints that preview page through the system's print dialog.

import { html, useEffect, useRef, useState, Button, Check, Note, Seg, Modal, Icon, tip, cx, call } from "../core/ui.js";

const T = {
  dialog: "The rules sheet for the cabinet: one row per mode on the card (its name as the game shows it, how it starts, its stages, whether it cashes out), the rules every mode shares, and the game and version from the project. Made from the mode files each time, so it is always current.",
  edit: "Write this mode's words yourself, field by field. Until you do, the sheet says what the app works out from the mode itself.",
  on: "Put this mode on the sheet. Untick to leave it off (a mode that is not on the card, say).",
  up: "Move this mode up the sheet",
  down: "Move this mode down the sheet",
  start: "How the mode starts: the shot, and what the 1st / 2nd / 3rd start take.",
  stages: "One stage a line: what to shoot, and the clock.",
  cash: "The shot that cashes out between stages, or empty for none.",
  tag: "A short word under the mode's name, such as NEW or REWORKED.",
  title: "The sheet's title. Empty uses the game's name and Custom Modes.",
  intro: "The line under the title. Empty says how many modes the card adds to which game and version.",
  foot: "The rules every mode shares, under the table. Empty uses what the app works out from the modes.",
  pdf: "Save the sheet as a PDF to print: one page when it fits.",
  print: "Print the sheet: the system's print dialog, with the sheet laid out on the paper chosen here, landscape.",
  htmlSave: "Save the sheet as a web page.",
  paper: "The paper the PDF is laid out for, landscape.",
};

// PAD-695: the page in the preview prints itself (its @page rule sets the paper, landscape) where the window is
// Chromium (WebView2, the browser) or a plain browser. Other native windows (macOS, Qt) do not answer print() from a
// page, so there the sheet's PDF opens in the system's viewer to print from.
function printsInPage() {
  const ua = navigator.userAgent || "";
  return !window.pywebview || (/Chrome\//.test(ua) && !/QtWebEngine/.test(ua));
}

function printSheet(frame) {
  const w = frame && frame.contentWindow;
  if (w && printsInPage()) {
    try { if (w.padFitPage) w.padFitPage(); w.focus(); w.print(); return; } catch (e) { /* the PDF instead, below */ }
  }
  call("modes.sheet_print");
}

// A text box that keeps what is typed and hands it over when it is left (or Enter, on one line).
function Words({ value, placeholder, onCommit, lines, title }) {
  const [v, setV] = useState(value || "");
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setV(value || ""); }, [value]);
  const commit = () => { focused.current = false; if ((v || "") !== (value || "")) onCommit(v); };
  // the tooltip's own focus and blur handlers run too (a spread of tip() alone would replace ours)
  const t = tip(title);
  const common = Object.assign({}, t, {
    value: v, placeholder, spellcheck: false,
    onFocus: (e) => { focused.current = true; if (t.onFocus) t.onFocus(e); },
    onInput: (e) => setV(e.currentTarget.value),
    onBlur: (e) => { commit(); if (t.onBlur) t.onBlur(e); },
  });
  return lines
    ? html`<textarea class="rs-words" rows=${lines} ...${common}></textarea>`
    : html`<input class="rs-words" type="text" ...${common}
        onKeyDown=${(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />`;
}

function ModeRow({ r, i, n, open, onOpen }) {
  const own = r.own || {};
  const mine = Object.keys(own).length;
  const set = (field) => (v) => call("modes.sheet_words", r.slug, field, v);
  return html`<div class=${cx("rs-mode", !r.on && "off", open && "open")}>
    <div class="rs-mode-hd">
      <${Check} checked=${r.on} onChange=${(v) => call("modes.sheet_on", r.slug, v)} title=${T.on} />
      <button type="button" class="rs-name" onClick=${onOpen} ...${tip(T.edit)}>
        <b>${r.name}</b>${r.tag ? html` <span class="rs-tag">${r.tag}</span>` : null}
        ${mine ? html` <span class="chip sm acc">your words</span>` : null}
      </button>
      <span class="grow"></span>
      <${Button} size="sm" kind="ghost" icon="up" title=${T.up} disabled=${i === 0} onClick=${() => call("modes.sheet_move", r.slug, -1)} />
      <${Button} size="sm" kind="ghost" icon="down" title=${T.down} disabled=${i === n - 1} onClick=${() => call("modes.sheet_move", r.slug, 1)} />
      <${Button} size="sm" kind="ghost" icon="edit" title=${T.edit} onClick=${onOpen} />
    </div>
    ${open ? html`<div class="rs-fields">
      <label class="lbl">Start</label>
      <${Words} value=${own.start} placeholder=${r.gen.start || "(say how it starts)"} title=${T.start} onCommit=${set("start")} />
      <label class="lbl">Stages</label>
      <${Words} lines=${Math.max(3, (own.stages || r.gen.stages || []).length + 1)} value=${(own.stages || []).join("\n")}
        placeholder=${(r.gen.stages || []).join("\n") || "(one stage a line)"} title=${T.stages} onCommit=${set("stages")} />
      <label class="lbl">Cash out</label>
      <${Words} value=${own.cash} placeholder=${r.gen.cash || "(none)"} title=${T.cash} onCommit=${set("cash")} />
      <label class="lbl">Tag</label>
      <${Words} value=${own.tag} placeholder="(none)" title=${T.tag} onCommit=${set("tag")} />
      ${mine ? html`<div class="row"><span class="grow"></span>
        <${Button} size="sm" kind="ghost" icon="undo" onClick=${() => { for (const k of Object.keys(own)) call("modes.sheet_words", r.slug, k, ""); }}
          title="Forget your words for this mode: the sheet says the app's again">Use the app's words<//></div>` : null}
    </div>` : null}
  </div>`;
}

export function RulesSheetDialog({ s, onClose }) {
  const sh = s.sheet || {};
  const [open, setOpen] = useState("");
  const close = () => { call("modes.sheet_close"); onClose(); };
  const rows = sh.rows || [];
  const own = sh.own || {};
  const setting = (k) => (v) => call("modes.sheet_setting", k, v);
  const busy = !!sh.busy;
  const frame = useRef(null);
  return html`<${Modal} title="Rules sheet" icon="file" xwide cls="rs-modal" onClose=${close}
    footer=${html`<span class="lbl" ...${tip(T.paper)}>Paper</span>
      <${Seg} value=${sh.paper || "letter"} options=${[{ value: "letter", label: "Letter" }, { value: "a4", label: "A4" }]}
        onChange=${setting("paper")} disabled=${busy} />
      <span class="grow"></span>
      <${Button} icon="download" disabled=${busy || !sh.n_on} title=${T.htmlSave} onClick=${() => call("modes.sheet_save", "html")}>Save as HTML…<//>
      <${Button} icon="download" disabled=${busy || !sh.n_on} title=${T.pdf} onClick=${() => call("modes.sheet_save", "pdf")}>Save as PDF…<//>
      <${Button} kind="primary" icon="print" disabled=${busy || !sh.n_on} title=${T.print} onClick=${() => printSheet(frame.current)}>Print…<//>
      <${Button} onClick=${close}>Close<//>`}>
    <div class="small dim wrap rs-about">${T.dialog}</div>
    ${sh.error ? html`<${Note} kind="err">${sh.error}<//>` : null}
    ${busy ? html`<div class="rs-busy"><span class="spin"></span> Playing each mode to word its rules…</div>` : html`
    <div class="rs-body">
      <div class="rs-side">
        <div class="rs-sheet-fields">
          <label class="lbl">Title</label>
          <${Words} value=${own.title} placeholder=${sh.title} title=${T.title} onCommit=${setting("title")} />
          <label class="lbl">Under it</label>
          <${Words} lines=${2} value=${own.intro} placeholder=${sh.intro} title=${T.intro} onCommit=${setting("intro")} />
          <label class="lbl">Foot</label>
          <${Words} lines=${3} value=${own.foot} placeholder=${sh.foot} title=${T.foot} onCommit=${setting("foot")} />
        </div>
        <div class="rs-modes">
          ${rows.map((r, i) => html`<${ModeRow} key=${r.slug} r=${r} i=${i} n=${rows.length} open=${open === r.slug}
            onOpen=${() => setOpen(open === r.slug ? "" : r.slug)} />`)}
          ${(sh.left || []).length ? html`<div class="small muted rs-left">Not on the sheet, as they would not go on the card:
            ${sh.left.map((x) => html`<div key=${x.name}><b>${x.name}</b>: ${x.why}</div>`)}</div>` : null}
        </div>
      </div>
      <div class="rs-preview">
        <div class="rs-page"><iframe ref=${frame} title="The rules sheet" class=${cx("rs-frame", sh.paper === "a4" && "a4")} srcdoc=${sh.html || ""}></iframe></div>
        <div class="small muted rs-count"><${Icon} name="info" /> ${sh.n_on || 0} of ${rows.length} modes on the sheet.</div>
      </div>
    </div>`}
  <//>`;
}
