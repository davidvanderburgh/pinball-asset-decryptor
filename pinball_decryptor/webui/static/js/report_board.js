// The board of a user's own problem reports (PAD-914): every report this
// app sent, in the column of where it is in the developer's queue, with the
// ticket's number, how far through the work it is and, once it is done, the
// release that addressed it and the developer's message.
//
// ONE script draws it in two places, so they cannot drift apart: the app's
// Your reports window (shellx_dialogs.js imports this file) and the ticket
// in the developer's tracker, pad-triage, which serves this very file from
// its checkout of the app and loads it as a plain <script>.  So no import,
// no export and nothing from the app's UI kit: it sets window.PADReportBoard
// and returns HTML.  Its colours are the app's tokens (--ink, --panel,
// --ok...); a page with other names maps them on a wrapper.
//
// An entry is core/problem_report.py's board_entry(): id, title, at
// (seconds), stage (received | queued | working | ready | done |
// question), state, ticket, progress (0-100, -1 for none), version,
// message, new, and (PAD-972) question, waiting, answer_sent.  A report
// whose question waits on the user is drawn in Being worked on with a look
// of its own, "Needs your answer"; a stage this script does not know goes
// in Received rather than nowhere.
(function () {
  const STAGES = [
    { key: "received", label: "Received", hint: "On its way to the developer" },
    { key: "queued", label: "In the queue", hint: "Read, waiting its turn" },
    { key: "working", label: "Being worked on", hint: "A fix is under way" },
    { key: "ready", label: "Fix ready", hint: "Goes out with the next release" },
    { key: "done", label: "Done", hint: "Released, or closed" },
  ];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
    "Sep", "Oct", "Nov", "Dec"];

  const CSS = `
.prb-wrap { container-type: inline-size; }
.prb { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; align-items: start; }
.prb-col { background: var(--bg-2, rgba(127,127,127,.06)); border: 1px solid var(--line, rgba(127,127,127,.25)); border-radius: 8px; padding: 8px; min-height: 120px; }
.prb-head { display: flex; align-items: baseline; gap: 6px; font-weight: 600; font-size: 12.5px; color: var(--ink, inherit); }
.prb-n { font-weight: 500; color: var(--ink-3, #888); font-size: 12px; }
.prb-hint { font-size: 11.5px; color: var(--ink-3, #888); margin: 2px 0 8px; line-height: 1.3; }
.prb-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; align-self: center; background: var(--ink-3, #888); }
.prb-col[data-stage="queued"] .prb-dot { background: var(--info, #6aa0d8); }
.prb-col[data-stage="working"] .prb-dot { background: var(--accent, #e8a33d); }
.prb-col[data-stage="ready"] .prb-dot { background: var(--cp-ink, #b98ae0); }
.prb-col[data-stage="done"] .prb-dot { background: var(--ok, #6fc07a); }
.prb-card { background: var(--panel, rgba(127,127,127,.12)); border: 1px solid var(--line-2, rgba(127,127,127,.35)); border-radius: 6px; padding: 7px 8px; margin-top: 6px; font-size: 12.5px; line-height: 1.35; color: var(--ink, inherit); }
.prb-card.prb-new { border-color: var(--info, #6aa0d8); box-shadow: inset 3px 0 0 var(--info, #6aa0d8); }
.prb-card.prb-cur { border-color: var(--accent, #e8a33d); box-shadow: inset 3px 0 0 var(--accent, #e8a33d); }
.prb-card.prb-ask { border-color: var(--warn, #e0b34a); box-shadow: inset 3px 0 0 var(--warn, #e0b34a); }
.prb-title { font-weight: 500; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; word-break: break-word; }
.prb-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin-top: 4px; color: var(--ink-3, #888); font-size: 11.5px; }
.prb-chip { font-family: var(--mono, ui-monospace, monospace); font-size: 11px; padding: 0 5px; border-radius: 4px; border: 1px solid var(--line-2, rgba(127,127,127,.35)); color: var(--ink-2, inherit); }
.prb-tag { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; padding: 0 5px; border-radius: 4px; }
.prb-tag.new { background: var(--info-soft, rgba(106,160,216,.18)); color: var(--info, #6aa0d8); }
.prb-tag.cur { background: var(--accent-soft, rgba(232,163,61,.18)); color: var(--accent, #e8a33d); }
.prb-tag.ask { background: var(--warn-soft, rgba(224,179,74,.18)); color: var(--warn, #e0b34a); }
.prb-q { margin-top: 5px; padding: 5px 7px; border-radius: 5px; background: var(--warn-soft, rgba(224,179,74,.12)); color: var(--ink, inherit); white-space: pre-line; word-break: break-word; }
.prb-q-hint { margin-top: 4px; font-size: 11.5px; color: var(--ink-3, #888); }
.prb-bar { height: 5px; border-radius: 3px; background: var(--line, rgba(127,127,127,.25)); margin-top: 6px; overflow: hidden; }
.prb-bar > i { display: block; height: 100%; background: var(--accent, #e8a33d); }
.prb-pct { font-size: 11px; color: var(--ink-3, #888); margin-top: 2px; }
.prb-out { margin-top: 5px; font-weight: 600; font-size: 12px; color: var(--ink-2, inherit); }
.prb-out.ok { color: var(--ok, #6fc07a); }
.prb-msg { margin-top: 4px; padding-left: 7px; border-left: 2px solid var(--line-2, rgba(127,127,127,.35)); color: var(--ink-2, inherit); white-space: pre-line; word-break: break-word; }
.prb-none { color: var(--ink-3, #888); font-size: 12px; padding: 4px 2px; }
.prb-empty { color: var(--ink-3, #888); font-size: 13px; padding: 12px 2px; }
@container (max-width: 640px) {
  .prb { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .prb-col { min-height: 0; }
  .prb-col.prb-blank .prb-hint, .prb-col.prb-blank .prb-none { display: none; }
}`;

  function addStyle(doc) {
    doc = doc || (typeof document !== "undefined" ? document : null);
    if (!doc || doc.getElementById("pad-report-board-css")) return;
    const el = doc.createElement("style");
    el.id = "pad-report-board-css";
    el.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(el);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function when(at) {
    const n = Number(at);
    if (!n) return "";
    const d = new Date(n * 1000);
    return d.getDate() + " " + MONTHS[d.getMonth()] + " " + d.getFullYear();
  }

  function outcome(e) {
    if (e.state === "released") return { cls: "ok", text: "Fixed in v" + (e.version || "?") };
    if (e.state === "closed") return { cls: "", text: "Looked at and closed" };
    if (e.state === "unknown") return { cls: "", text: "No longer on record" };
    return null;
  }

  // the column a report is drawn in: a question is still being worked on
  const KEYS = STAGES.map((s) => s.key);
  function column(e) {
    const s = e.stage || "received";
    if (s === "question") return "working";
    return KEYS.includes(s) ? s : "received";
  }
  // waiting on the user: the app says so outright; the tracker's copy
  // knows it from the stage it pushed
  function asking(e) {
    return e.waiting === undefined ? e.stage === "question" : !!e.waiting;
  }

  function card(e, cur, opts) {
    const isCur = cur && e.id === cur;
    const ask = asking(e);
    const cls = "prb-card" + (isCur ? " prb-cur" : ask ? " prb-ask" : e.new ? " prb-new" : "");
    let out = '<div class="' + cls + '" data-id="' + esc(e.id) + '">';
    out += '<div class="prb-title" title="' + esc(e.title) + '">' +
      esc(e.title || "A problem report") + "</div>";
    out += '<div class="prb-meta"><span>' + esc(when(e.at)) + "</span>";
    if (e.ticket) out += '<span class="prb-chip">' + esc(e.ticket) + "</span>";
    if (isCur) out += '<span class="prb-tag cur">This ticket</span>';
    if (ask) out += '<span class="prb-tag ask">Needs your answer</span>';
    else if (e.new && !isCur) out += '<span class="prb-tag new">New</span>';
    out += "</div>";
    if (ask) {
      if (e.question) out += '<div class="prb-q">' + esc(e.question) + "</div>";
      if (opts.askHint) out += '<div class="prb-q-hint">' + esc(opts.askHint) + "</div>";
    } else if (e.answer_sent && e.stage !== "done") {
      out += '<div class="prb-out ok">Answer sent</div>';
    }
    const p = Number(e.progress);
    if (e.stage === "working" && p >= 0 && p <= 100) {
      out += '<div class="prb-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' +
        p + '"><i style="width:' + p + '%"></i></div><div class="prb-pct">' + p + "% through the work</div>";
    }
    if (e.stage === "done") {
      const o = outcome(e);
      if (o) out += '<div class="prb-out ' + o.cls + '">' + esc(o.text) + "</div>";
      if (e.message) out += '<div class="prb-msg">' + esc(e.message) + "</div>";
    }
    return out + "</div>";
  }

  // The board as HTML.  `entries` newest first or not: each column lists
  // its reports newest first.  opts.current: the id to mark "This ticket"
  // (the tracker's view of one ticket).  opts.empty: words for no reports.
  // opts.askHint: a line under a question saying where to answer it.
  function html(entries, opts) {
    opts = opts || {};
    addStyle();
    const list = (entries || []).slice().sort((a, b) => (Number(b.at) || 0) - (Number(a.at) || 0));
    if (!list.length) {
      return '<div class="prb-wrap"><div class="prb-empty">' +
        esc(opts.empty || "No reports sent from this app yet.") + "</div></div>";
    }
    let out = '<div class="prb-wrap"><div class="prb">';
    for (const s of STAGES) {
      const here = list.filter((e) => column(e) === s.key);
      out += '<section class="prb-col' + (here.length ? "" : " prb-blank") +
        '" data-stage="' + s.key + '"><div class="prb-head"><span class="prb-dot"></span>' +
        esc(s.label) + ' <span class="prb-n">' + here.length + "</span></div>" +
        '<div class="prb-hint">' + esc(s.hint) + "</div>";
      out += here.length ? here.map((e) => card(e, opts.current, opts)).join("")
        : '<div class="prb-none">Nothing here</div>';
      out += "</section>";
    }
    return out + "</div></div>";
  }

  const api = { STAGES, html, addStyle, when };
  if (typeof window !== "undefined") window.PADReportBoard = api;
})();
