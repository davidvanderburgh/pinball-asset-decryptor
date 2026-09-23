// Mod Pack tab: export / import a mod pack zip and (Stern Spike 2:
// capabilities.mod_transfer) "Move Your Mods to Another Card" - the one-click
// port and the step-by-step transfer form.  The "Optional: Apply Delta on
// Top" box is the Write tab's, as in Tk.
// Python half: webui/tabs/modpack.py.  Every question, picker and
// confirmation comes from the run logic (app.py) through the dialog host.

import { html, PageHead, Card, Button, Field, Chip, Note, Icon, tip, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

// Word for word from the Tk tab (gui/main_window.py _build_modpack_tab).
const T = {
  intro: "Share your changes as a zip, or apply someone else's.",
  project: "Shared by every tab — it is set on the Extract tab. Click to open it.",
  noProject: "No project folder yet — set it on the Extract tab.",
  exportTip: "Create a zip holding only your modified files, small enough to share.",
  importTip: "Apply a mod pack zip from another user onto this project's extracted assets.",
  moveTitle: "Move Your Mods to Another Card",
  routeA: "New game version, or the other model (Pro ↔ Premium) — build my modded card(s) automatically",
  routeB: "Advanced — do each step myself (also the route for cards modded outside this app)",
  portTip: "Pick one or more stock card images (the new version, the other model, or both) and everything else is automatic: each card is extracted, this project's mods are transferred onto it, and its modded card is built — unattended, one after another.\n\nEach card's extract lands beside the builds and is reused next time, so re-shipping after a change is fast. Audio slots whose index now holds a different sound are skipped (the safe default); everything skipped is named in the log.",
  transferTip: "The same move as the one-click port, with you driving each stage: pick the two extract folders above, run the transfer, then build the card on the Write tab (the output-name preview on the left shows what it will build).\n\nThis is also the route for a card that was modded OUTSIDE this app: extract the modded card as field 1 and fill field 3 with a stock extract of that same version, so your mods can be told apart from the factory's own changes.",
  verTip: "The build this item really is, read from the card's own update index (it survives renamed files). A ~ marks a filename guess — an older extract, or a card whose index can't be read. Fields 1 and 3 should show the SAME old version, and fields 2 and 4 the SAME new one; a card modded outside this app often reports no version at all, which is normal.",
};

const ROWS = [
  { k: "src", ver: "src_ver", n: "1", label: "Old extract (has your mods):" },
  { k: "dst", ver: "dst_ver", n: "2", label: "New extract (stock, new version):",
    tip: "A fresh, unmodified extract of the code your mods are moving ONTO. It can be the other model of the same title as well as a newer version — a Pro extract's mods transfer onto the Premium/LE code, and the reverse." },
  { k: "oldstock", ver: "oldstock_ver", n: "3", label: "Stock extract of the OLD version (optional):",
    tip: "Not an alternative to field 1, and never in conflict with it: field 1 is where your mods come FROM; this is an unmodified twin of that same version, used only as the reference your old extract is compared against.",
    browseTip: "A clean, unmodified extract of the SAME old version as field 1 — used only as a reference to compare field 1 against, so the factory's own between-version changes aren't mistaken for your mods, and AUDIO and TEXT mods can be carried too.\n\nLeave empty to compare your old extract straight against the new one (finds image + video mods)." },
  { k: "newimg", ver: "img_ver", n: "4", label: "New version card image (.raw) to build onto:",
    tip: "The stock image the new extract came from — the base the build patches your transferred mods onto. Auto-filled from field 2's extract; it is needed as well as field 2, not instead of it.",
    browseTip: "Auto-filled from field 2 (the new extract records the image it came from). Both fields are required: the folder is where your mods land, this image is what the build patches them onto." },
];

// The little what-goes-in / what-comes-out diagrams (Tk _draw_flow): plain
// boxes, the final box picked out by an accent outline, verbs on the arrows.
function Flow({ boxes, arrows }) {
  const parts = [];
  boxes.forEach((b, i) => {
    if (i) {
      const verb = arrows[i - 1] || "";
      parts.push(html`<span class="mp-arrow" aria-hidden="true"><span class="ln"></span><span class="al">${verb}</span></span>`);
    }
    const m = /^(\d+)\s+(.*)$/.exec(b);
    parts.push(html`<span class=${cx("mp-box", i === boxes.length - 1 && "last")}>
      ${m ? html`<b class="mp-num">${m[1]}</b><span>${m[2]}</span>` : b}</span>`);
  });
  const said = boxes.map((b, i) => (i && arrows[i - 1] ? arrows[i - 1] + " → " : i ? "→ " : "") + b).join(" ");
  return html`<div class="mp-flow" role="img" aria-label=${said}>${parts}</div>`;
}

function ProjectLink({ folder }) {
  if (!folder) return html`<span class="muted small">${T.noProject}</span>`;
  return html`<button type="button" class="mp-link mono small" onClick=${() => call("modpack.open_project")}
    ...${tip(T.project)}>${folder}</button>`;
}

function PackCard({ s }) {
  return html`<${Card} cls="mp-pack" head=${html`<span class="k lbl">Project Folder</span><${ProjectLink} folder=${s.project} />`}>
    <div class="mp-actions">
      <div class="mp-action">
        <span class="ic"><${Icon} name="upload" /></span>
        <div class="stack grow" style="gap:2px">
          <span class="t">Export</span>
          <span class="small muted">${T.exportTip}</span>
        </div>
        <${Button} kind="primary" icon="upload" title=${T.exportTip} onClick=${() => call("modpack.export_pack")}>Export Mod Pack…<//>
      </div>
      <div class="mp-action">
        <span class="ic"><${Icon} name="download" /></span>
        <div class="stack grow" style="gap:2px">
          <span class="t">Import</span>
          <span class="small muted">${T.importTip}</span>
        </div>
        <${Button} kind="primary" icon="download" title=${T.importTip} onClick=${() => call("modpack.import_pack")}>Import Mod Pack…<//>
      </div>
    </div>
  <//>`;
}

function TransferRow({ s, row }) {
  const ver = s[row.ver] || "";
  return html`<div class="mp-frow">
    <label class=${cx("mp-flabel", row.tip && "tipped")} for=${"mp-" + row.k} ...${tip(row.tip)}>
      <b class="mp-num">${row.n}</b><span class="tx">${row.label}</span>
    </label>
    <div class="mp-fctl">
      <${Field} ns="modpack" k=${row.k} value=${s[row.k]} mono id=${"mp-" + row.k} cls="grow" title=${s[row.k] || ""} />
      <${Button} title=${row.browseTip} onClick=${() => call("modpack.browse", row.k)}>Browse…<//>
      <span class="mp-ver">${ver ? html`<${Chip} kind="info" sm title=${ver + "\n\n" + T.verTip}>${ver}<//>` : null}</span>
    </div>
  </div>`;
}

function TransferCard({ s }) {
  const next = (s.next || "").replace(/^✓\s*/, "");
  return html`<${Card} title=${T.moveTitle}>
    <section class="mp-route">
      <div class="mp-rhd">${T.routeA}</div>
      <div class="mp-rrow">
        <${Flow} boxes=${["This project's mods", "Stock card image(s) you pick", "Finished modded card(s)"]}
          arrows=${["transfer", "build"]} />
        <span class="grow"></span>
        <${Button} kind="primary" icon="modpack" title=${T.portTip} onClick=${() => call("modpack.port")}>Port + build onto card image(s)…<//>
      </div>
    </section>
    <section class="mp-route">
      <div class="mp-rhd">${T.routeB}</div>
      <${Flow} boxes=${["1  Old extract (your mods)", "2  New stock extract", "Write tab", "Modded card"]}
        arrows=${["transfer", "", "build"]} />
      <div class="mp-form">
        ${ROWS.map((row) => html`<${TransferRow} key=${row.k} s=${s} row=${row} />`)}
      </div>
      <div class="mp-arow">
        <span class="mp-out">${s.output || ""}</span>
        <${Button} kind="primary" title=${T.transferTip} onClick=${() => call("modpack.transfer")}>Transfer mods → new version…<//>
      </div>
      ${next ? html`<${Note} kind="ok">${next}<//>` : null}
    </section>
  <//>`;
}

export default function ModPackTab() {
  const s = useNs("modpack");
  return html`<div class="page mp-page">
    <${PageHead} title="Mod Pack" sub=${T.intro} />
    <${PackCard} s=${s} />
    ${s.transfer_cap ? html`<${TransferCard} s=${s} />` : null}
  </div>`;
}
