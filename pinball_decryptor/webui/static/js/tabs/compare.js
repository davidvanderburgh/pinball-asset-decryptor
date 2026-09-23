// Compare: two card images, the plugin's what-changed report, Rows per list,
// Copy Report, Extract Both, double-click a listed file to open it.  The
// report is painted in tabs/compare.py; this page renders its flat `rows`.

import { html, useState, useEffect, PageHead, Card, Button, Field, Select, Table, Empty, openMenu, InfoBadge, tip, Icon,
  call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const SUB = "Compare two card images of the same game — two releases, or a modded card against its stock base.";

const HEAD_KIND = {
  Added: "ok", "Added defaults": "ok",
  Modified: "warn", "Modified defaults": "warn", Changed: "warn", Moved: "warn",
  Deleted: "err", Removed: "err", Warning: "err", Error: "err", "Could not compare": "err",
  "No changes": "muted",
};

function recentMenu(anchor, paths, onPick) {
  openMenu(anchor, [
    { header: "Recent card images" },
    ...(paths.length ? paths.map((p) => ({ label: p, onClick: () => onPick(p) }))
      : [{ label: "No recent card images yet", disabled: true }]),
  ], { align: "right" });
}

// A hover tip left showing when the page goes away would float over the next
// tab (ui.js only hides it on mouseleave): Extract Both switches to the
// Extract tab under a still pointer (Tk sent <Leave> when the tab unmapped).
function hideTips() {
  document.querySelectorAll("body > .tip").forEach((el) => { el.style.display = "none"; });
}

function fieldValue(id) {
  const el = document.querySelector("#" + id);
  return el ? el.value : "";
}

// Send both boxes first so Compare / Extract Both read what is on screen.
function withPaths(method) {
  return Promise.all([call("ui.set", "compare", "a", fieldValue("cmp-a")), call("ui.set", "compare", "b", fieldValue("cmp-b"))])
    .then(() => call(method));
}

function ImageRow({ side, label, value, history, running }) {
  const id = "cmp-" + side;
  const run = () => withPaths("compare.run");
  return html`
    <label class="lbl" for=${id}>${label}</label>
    <form class="row" style="gap:8px" onSubmit=${(e) => { e.preventDefault(); if (!running) run(); }}>
      <${Field} id=${id} ns="compare" k=${side} value=${value} mono cls="grow" placeholder="A card image" />
      <${Button} icon="down" title="Recent card images"
        onClick=${(e) => recentMenu(e.currentTarget, history || [], (p) => call("ui.set", "compare", side, p))} />
      <${Button} onClick=${() => call("compare.browse", side)}>Browse…<//>
    </form>`;
}

export default function CompareTab() {
  const s = useNs("compare");
  const rows = s.rows || [];
  const [selId, setSel] = useState(null);
  // row ids are positional: a new report (or none) drops the selection
  useEffect(() => { setSel(null); }, [s.report]);
  useEffect(() => hideTips, []);
  const running = !!s.running;
  const nSections = rows.filter((r) => r.kind === "section").length;
  const anyShut = rows.some((r) => r.kind === "section" && r.shut);

  const columns = [
    { key: "change", label: "Change", width: "minmax(150px,230px)", render: (r) => {
      if (r.kind === "section") {
        return html`<span class="cmp-sec-title"><button type="button" class="cmp-tw" aria-label=${r.shut ? "Expand" : "Collapse"}
            onClick=${(e) => { e.stopPropagation(); call("compare.toggle_section", r.sec); }}><${Icon} name=${r.shut ? "right" : "down"} /></button>
          <span class="ellip">${r.change}</span></span>`;
      }
      if (r.kind === "head") {
        const k = HEAD_KIND[r.change] || "";
        return html`<span class=${cx("cmp-head", k && "cmp-" + k)}>${r.change}</span>`;
      }
      return html`<span class="cmp-item-gap"></span>`;
    }, titleOf: (r) => r.change || undefined },
    { key: "details", label: "Details", width: "minmax(0,1fr)", render: (r) => {
      if (r.kind === "more") {
        return html`<button type="button" class="cmp-more" onClick=${(e) => { e.stopPropagation(); call("compare.expand", r.id); }}>${r.details}</button>`;
      }
      if (r.open) {
        return html`<span class="cmp-file"><${Icon} name="external" /><span class="ellip">${r.details}</span></span>`;
      }
      return html`<span class=${cx(r.kind === "item" && "cmp-itemtxt")}>${r.details}</span>`;
    }, titleOf: (r) => (r.kind === "section" ? undefined : r.open ? r.details + "  (double-click to open)" : r.details) },
  ];

  const actions = html`
    <${Button} kind="primary" icon="compare" disabled=${running} onClick=${() => withPaths("compare.run")}>Compare<//>
    <span ...${tip(s.extract_both_tip)}><${Button} icon="extract"
      onClick=${() => { hideTips(); withPaths("compare.extract_both"); }}>Extract Both<//></span>
    <${Button} icon="copy" disabled=${running || !s.has_report} onClick=${() => call("compare.copy_report")}>Copy Report<//>
    <span class="row" style="gap:8px" ...${tip(s.limit_tip)}>
      <span class="lbl nw">Rows per list</span>
      <${Select} sm width=${86} value=${s.limit || "50"} options=${s.limit_choices || ["12", "25", "50", "100", "All"]}
        onChange=${(v) => call("compare.set_limit", v)} />
    </span>
    <span class="cmp-status small" title=${s.status || undefined}>${s.status || ""}</span>`;

  const empty = running ? null : html`<${Empty} icon="compare" title="No report yet">
    Pick Image A and Image B, then press Compare.<//>`;

  return html`<div class="page fill cmp">
    <${PageHead} title=${html`<span class="row" style="gap:8px">Compare <${InfoBadge} text=${s.intro} /></span>`} sub=${SUB} />

    <${Card} cls="cmp-src" footer=${actions}>
      <div class="cmp-grid">
        <${ImageRow} side="a" label="Image A" value=${s.a} history=${s.hist_a} running=${running} />
        <${ImageRow} side="b" label="Image B" value=${s.b} history=${s.hist_b} running=${running} />
      </div>
    <//>

    <${Card} cls="cmp-report" bodyCls="flush" head=${html`
        <span class="h2">Report</span>
        ${nSections ? html`<span class="muted small">${nSections} section${nSections === 1 ? "" : "s"} · double-click a file to open it</span>` : null}
        <span class="sp"></span>
        ${nSections ? html`<${Button} kind="ghost" size="sm" onClick=${() => call("compare.set_all_sections", !anyShut)}>
          ${anyShut ? "Expand all" : "Collapse all"}<//>` : null}`}>
      <div class="cmp-tablewrap">
        <${Table} columns=${columns} rows=${rows} rowKey=${(r) => r.id} rowHeight=${30}
          resizable widths=${s.widths || null} onResize=${(w) => call("compare.set_widths", w)}
          selected=${selId} onSelect=${(r) => setSel(r.id)}
          onActivate=${(r) => call("compare.activate", r.id)}
          rowClass=${(r) => cx("cmp-r-" + r.kind, r.open && "cmp-openable")}
          empty=${empty} />
        ${running ? html`<div class="cmp-busy" role="status"><span class="spin"></span><span>Comparing images…</span></div>` : null}
      </div>
    <//>
  </div>`;
}
