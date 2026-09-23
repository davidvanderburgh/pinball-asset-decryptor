// Partitions (Tk "Partition Explorer"): open a raw Stern card image, walk a
// partition's ext4 tree, preview, find, extract, and (right-click) replace a
// file on the card.  The tree model lives in tabs/partitions.py; this page
// renders its flat `rows` and sends the clicks back.

import { html, useRef, useEffect, PageHead, Card, Button, Field, Select, Seg, Table,
  Empty, Modal, openMenu, InfoBadge, tip, Icon, call, mediaUrl, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const ROW_H = 32;

// A hover tip left showing when the page goes away (a tab switch under the
// pointer) would float over the next tab: ui.js only hides it on mouseleave.
function hideTips() {
  document.querySelectorAll("body > .tip").forEach((el) => { el.style.display = "none"; });
}

// Keep the selected row WHOLLY in view below the sticky header, with a row
// of context under it (Tk tree.see()); the Table's own scroll-into-view
// leaves a revealed row flush against the bottom edge.
function keepInView(wrap, rows, sel) {
  const sc = wrap && wrap.querySelector(".scroller");
  if (!sc || !sel) return;
  const idx = rows.findIndex((r) => r.id === sel);
  if (idx < 0) return;
  const head = sc.querySelector(".tr.th");
  const hh = head ? head.offsetHeight : 0;
  const top = idx * ROW_H;                              // in the rows' own frame
  const viewH = sc.clientHeight - hh;
  if (viewH <= ROW_H) return;
  if (top < sc.scrollTop) sc.scrollTop = top;
  else if (top + ROW_H > sc.scrollTop + viewH) {
    sc.scrollTop = Math.max(0, top + ROW_H - viewH + (viewH > 3 * ROW_H ? ROW_H : 0));
  }
}

const SUB = "Browse a raw Stern card image (.raw / .img): view its partitions and files, preview images, fonts and text, extract any file or folder to disk, and (right-click) replace any file with one of your own.";

function inputValue(formEl) {
  const el = formEl && formEl.querySelector("input");
  return el ? el.value : "";
}

function recentMenu(anchor, paths, onPick) {
  openMenu(anchor, [
    { header: "Recent card images" },
    ...(paths.length ? paths.map((p) => ({ label: p, onClick: () => onPick(p) }))
      : [{ label: "No recent card images yet", disabled: true }]),
  ], { align: "right" });
}

function previewBox(ref) {
  const el = ref.current;
  if (!el) return [0, 0];
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  return [Math.min(1600, Math.round(el.clientWidth * dpr)), Math.min(1200, Math.round(el.clientHeight * dpr))];
}

function statusKind(text) {
  if (!text) return "";
  if (/^(Extract failed|Replace failed|Error:)/.test(text)) return "err-ink";
  if (/^(Extracted|Replaced)/.test(text)) return "ok-ink";
  return "";
}

function Properties({ props }) {
  const close = () => call("partitions.close_props");
  const copyable = new Set(["Path:", "Mounted at:"]);
  return html`<${Modal} title=${props.title} icon="info" onClose=${close}
      footer=${html`<${Button} kind="primary" onClick=${close}>OK<//>`}>
    <div class="kv pex-props">
      ${props.rows.map(([k, v]) => html`<span class="k">${k}</span>
        <span class="row" style="gap:6px"><span class=${cx("pex-pv", (k === "Path:" || k === "Mounted at:") && "mono")}>${v}</span>
          ${copyable.has(k) ? html`<${Button} kind="ghost" size="xs" icon="copy" title="Copy"
            onClick=${() => call("partitions.copy_path", v)} />` : null}</span>`)}
      ${(props.replaced || []).map((e) => html`<span class="k">Replaced:</span>
        <span class="stack" style="gap:2px"><span>${e.when}</span>
          ${e.source ? html`<span class="muted small mono">from ${e.source}</span>` : null}</span>`)}
    </div>
  <//>`;
}

export default function PartitionsTab() {
  const s = useNs("partitions");
  const prevRef = useRef(null);
  const wrapRef = useRef(null);
  const rows = s.rows || [];
  const busy = s.busy;
  const running = !!busy;
  const sel = s.sel;
  const selRow = sel ? rows.find((r) => r.id === sel) : null;
  const history = s.history || [];
  const preview = s.preview;

  useEffect(() => hideTips, []);
  // after the Table's own adjustment (child effects run first)
  useEffect(() => { keepInView(wrapRef.current, rows, sel); }, [sel]);

  const pick = (row) => {
    const [w, h] = previewBox(prevRef);
    call("partitions.select", row.id, w, h);
  };
  const toggle = (row, open) => call("partitions.toggle", row.id, open);

  const menuFor = (row, e) => {
    pick(row);
    const items = [
      { label: "Properties…", icon: "info", onClick: () => call("partitions.properties", row.id) },
      { label: "Copy path", icon: "copy", onClick: () => call("partitions.copy_path", row.id) },
    ];
    if (!running) {
      items.push({ sep: true });
      items.push({ label: "Extract…", icon: "download", onClick: () => call("partitions.extract_selected", row.id) });
      if (!row.dir) items.push({ label: "Replace with…", icon: "upload", onClick: () => call("partitions.replace", row.id) });
    }
    openMenu({ x: e.clientX, y: e.clientY }, items);
  };

  // The stock ttk.Treeview keys the Tk tree had (the Table does Up / Down /
  // Enter): Right opens a folder; Left closes an open folder with rows under
  // it, otherwise goes to the parent folder; Space opens / closes a folder.
  const onKey = (e) => {
    if (!selRow) return;
    const onButton = e.target && e.target.closest && e.target.closest("button");
    if (e.key === "ArrowRight") {
      if (selRow.dir && !selRow.open) { e.preventDefault(); toggle(selRow, true); }
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      const i = rows.indexOf(selRow);
      const hasKids = selRow.dir && selRow.open && i >= 0 && i + 1 < rows.length
        && rows[i + 1].depth > selRow.depth;
      if (hasKids) { toggle(selRow, false); return; }
      const cut = selRow.id.lastIndexOf("/");
      const parent = cut > 0 ? rows.find((r) => r.id === selRow.id.slice(0, cut)) : null;
      if (parent) pick(parent);
    } else if ((e.key === " " || e.key === "Spacebar") && !onButton) {
      e.preventDefault();
      if (selRow.dir) toggle(selRow);
    }
  };

  const columns = [
    { key: "name", label: "Name", width: "minmax(0,1fr)", render: (r) => html`<span class="pex-name" style=${`padding-left:${r.depth * 18}px`}>
        ${r.dir ? html`<button type="button" class="pex-tw" aria-label=${r.open ? "Collapse" : "Expand"}
            onClick=${(e) => { e.stopPropagation(); toggle(r); }}><${Icon} name=${r.open ? "down" : "right"} /></button>`
          : html`<span class="pex-tw"></span>`}
        <${Icon} name=${r.dir ? "folder" : "file"} cls=${r.dir ? "pex-ic-dir" : "pex-ic-file"} />
        <span class="ellip">${r.name}</span></span>`, titleOf: (r) => r.id },
    { key: "size", label: "Size", width: "96px", num: true },
    { key: "type", label: "Type", width: "minmax(70px,var(--pex-type-w))", cls: "pex-type", titleOf: (r) => r.type },
    // once a column has been dragged the last one takes what is left
    { key: "changed", label: "Changed", width: s.widths ? "minmax(70px,1fr)" : "minmax(70px,var(--pex-chg-w))", cls: "pex-changed" },
  ];

  const extractBtn = (id, label, fn, enabled, kind = "") => {
    if (running && s.busy_btn === id) {
      return html`<${Button} kind="danger" disabled=${s.cancelling} onClick=${() => call("partitions.cancel_extract")}>
        ${s.cancelling ? "Cancelling…" : "Cancel"}<//>`;
    }
    return html`<${Button} kind=${kind} icon="download" disabled=${running || !enabled} onClick=${fn}>${label}<//>`;
  };

  const footer = html`
    ${extractBtn("sel", "Extract Selected", () => call("partitions.extract_selected"), !!sel, "primary")}
    ${extractBtn("part", "Extract Whole Partition", () => call("partitions.extract_partition"), s.can_part)}
    ${extractBtn("all", "Extract All Partitions", () => call("partitions.extract_all"), s.can_all)}
    <span class=${cx("pex-status small", statusKind(s.status))} title=${s.status || undefined}>${s.status || ""}</span>`;

  const imageOpen = (s.parts || []).length > 0;
  const empty = html`<${Empty} icon="disk" title=${imageOpen ? "Nothing to list" : "No card image open"}>
    ${imageOpen ? (s.status || "") : "Pick a card image above: Browse…, a recent one, or type its path and press Enter."}<//>`;

  return html`<div class="page fill pex">
    <${PageHead} title=${html`<span class="row" style="gap:8px">Partitions <${InfoBadge} text=${s.intro} /></span>`} sub=${SUB} />

    <${Card} cls="pex-src">
      <div class="pex-grid">
        <label class="lbl" for="pex-image">Card Image</label>
        <form class="row" style="gap:8px" onSubmit=${(e) => { e.preventDefault(); call("partitions.open_image", inputValue(e.currentTarget)); }}>
          <${Field} id="pex-image" ns="partitions" k="image" value=${s.image} mono cls="grow" disabled=${running}
            placeholder="A card image: .raw, .img or .bin" />
          <${Button} icon="down" title="Recent card images" disabled=${running}
            onClick=${(e) => recentMenu(e.currentTarget, history, (p) => call("partitions.open_image", p))} />
          <${Button} disabled=${running} onClick=${() => call("partitions.browse")}>Browse…<//>
        </form>
        <label class="lbl" for="pex-part">Partition</label>
        <div class="row wrap pex-prow">
          <${Select} id="pex-part" cls="pex-part" value=${s.part} disabled=${!imageOpen}
            options=${(s.parts || []).length ? s.parts : [{ value: "", label: "Open a card image first" }]}
            onChange=${(v) => call("partitions.select_partition", v)} />
          <span class="row" style="gap:8px" ...${tip(s.show_tip)}>
            <span class="lbl">Show</span>
            <${Seg} value=${s.show || "All"} options=${s.show_choices || ["All", "Changed", "Unchanged"]}
              onChange=${(v) => call("partitions.set_show", v)} />
          </span>
          <span class="grow"></span>
          <form class="row pex-find" style="gap:8px" onSubmit=${(e) => { e.preventDefault(); call("partitions.find_next", inputValue(e.currentTarget)); }}>
            <${Field} ns="partitions" k="search" value=${s.search} placeholder="Find a path…" cls="grow"
              prefix=${html`<${Icon} name="search" cls="muted" />`} />
            <${Button} type="submit" disabled=${!s.can_find}>Find Next<//>
          </form>
        </div>
      </div>
    <//>

    <div class="cols pex-body">
      <${Card} cls="pex-tree" bodyCls="flush" footer=${footer}>
        <div class="pex-tablewrap" ref=${wrapRef} onKeyDown=${onKey}>
          <${Table} columns=${columns} rows=${rows} rowKey=${(r) => r.id} selected=${sel} rowHeight=${ROW_H}
            resizable widths=${s.widths || null} onResize=${(w) => call("partitions.set_widths", w)}
            onSelect=${(r) => pick(r)} onActivate=${(r) => (r.dir ? toggle(r) : null)}
            onContext=${(r, i, e) => menuFor(r, e)}
            rowClass=${(r) => cx(r.changed && "pex-row-changed", r.type === "not on the card now" && "pex-row-missing")}
            empty=${empty} />
          ${busy ? html`<div class="pex-busy" role="status"><span class="spin"></span><span>${busy.text}</span></div>` : null}
        </div>
      <//>

      <${Card} cls="pex-prev" title="Preview" sub=${preview && preview.caption ? preview.caption : ""}
          footer=${selRow ? html`
            <span class="mono small ellip grow" title=${selRow.id}>${selRow.id}</span>
            <${Button} size="sm" onClick=${() => call("partitions.properties", selRow.id)}>Properties…<//>
            ${!selRow.dir ? html`<${Button} size="sm" disabled=${running} onClick=${() => call("partitions.replace", selRow.id)}
                title="Write a file of your own over this one on the card">Replace with…<//>` : null}` : null}>
        <div class="pex-prevbox" ref=${prevRef}>
          ${!preview ? html`<div class="pex-noprev muted small">${sel ? "" : "Pick a file in the tree to preview it here."}</div>`
            : preview.kind === "image" ? html`<div class="thumb pex-img"><img src=${mediaUrl(preview.src)} alt=${preview.caption || "preview"} /></div>`
            : html`<pre class="pex-text">${preview.text}</pre>`}
        </div>
      <//>
    </div>

    ${s.props ? html`<${Properties} props=${s.props} />` : null}
  </div>`;
}
