// Select card tab (PAD-224): pick the card image (or the card in a reader)
// the app works on, see it (its boot screen, or a multi-boot card's menu)
// and what it says about itself, and see which tabs work on it straight away
// and which need it extracted first.  The picker is the Extract tab's input,
// so the page renders the extract namespace and calls extract.* for it; the
// preview and the details are the card namespace.  The Python half is
// webui/tabs/card.py.

import { html, useEffect, useState, Button, Card, Chip, Icon, PageHead, Seg, call, cx, mediaUrl } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { WHAT, needOf, tabLock } from "../core/locks.js";
import { Booting } from "../core/booting.js";
import { SourceBody, ExtractOverlays, inputPhrase, useNoStrayDrops } from "./extract.js";

export const css = true;

const HIDE = new Set(["card", "extract"]);

function TabRow({ t, lock }) {
  return html`<button type="button" class=${cx("c-row", lock && "locked")} onClick=${() => call("ui.select_tab", t.ns)}
      title=${lock ? lock.long : "Open the " + t.label + " tab"}>
    <${Icon} name=${t.icon} />
    <span class="c-name">${t.label}</span>
    <span class="c-what">${(t.ns === "write" && t.needs === "none" ? WHAT.write_flash : WHAT[t.ns]) || ""}</span>
    ${lock ? html`<${Icon} name="lock" cls="c-state" />` : html`<${Icon} name="check" cls="c-state ok-ink" />`}
  </button>`;
}

// PAD-435 (David): a James Bond card picked over an open Godzilla project read "Project
// Godzilla holds an extract, so every tab is ready".  The open project is another card's:
// say so, and offer the card a project of its own (or the one it already has, PAD-421).
function OtherCardNote({ ps, d }) {
  const own = d.card_project ? d.card_project.split(/[\\/]/).filter(Boolean).pop() : "";
  return html`<div class="note warn"><${Icon} name="warn" /><div class="body-text stack c-other">
    <span>Project <${Chip} kind="acc" title=${ps.folder}>${ps.name}<//> was extracted from another card, ${d.game || d.source_name}, so the tabs that read the project show that card's files, not this one's.${own ? ` This card has its own project, ${own}.` : ""}</span>
    <div class="row wrap">${own
      ? html`<${Button} size="sm" kind="primary" icon="folder" title=${d.card_project} onClick=${() => call("extract.use_card_project")}>Open its project<//>`
      : html`<${Button} size="sm" kind="primary" icon="plus" title="Make a project folder for this card and switch to it"
          onClick=${() => call("extract.new_card_project")}>New project for this card…<//>`}</div>
  </div></div>`;
}

function WhatCard({ shell, s }) {
  const ps = shell.project_state;
  const tabs = (shell.tabs || []).filter((t) => t.visible && !HIDE.has(t.ns));
  const direct = tabs.filter((t) => !needOf(t));
  const folder = tabs.filter((t) => needOf(t) === "project");
  const needs = tabs.filter((t) => needOf(t) === "extract");
  const anyLocked = folder.concat(needs).some((t) => tabLock(t, ps));
  const project = ps ? html`<${Chip} kind="acc" title=${ps.folder}>${ps.name}<//>` : null;
  const d = (s.project && s.project.details) || {};
  return html`<${Card} cls="c-what-card" title="What you can do with it">
    ${ps && d.card_kind === "other" ? html`<${OtherCardNote} ps=${ps} d=${d} />` : html`<div class="note"><${Icon} name=${anyLocked ? "lock" : "info"} /><div class="body-text">
      ${!ps ? html`There is no project folder yet. Extract the card into one to unlock the tabs marked with a lock; until then they are greyed out in the list on the left.`
        : anyLocked && ps.archived ? html`Project ${project} is archived. Extract into it again to unlock the tabs marked with a lock; until then they are greyed out in the list on the left.`
        : anyLocked ? html`Project ${project} has no extract yet. Extract the card into it to unlock the tabs marked with a lock; until then they are greyed out in the list on the left.`
        : html`Project ${project} holds an extract, so every tab is ready.`}
    </div></div>`}
    ${direct.length ? html`<div class="stack c-sec">
        <span class="lbl">Works straight from the card, no extract needed</span>
        ${direct.map((t) => html`<${TabRow} t=${t} lock=${null} />`)}
      </div>` : null}
    ${folder.length ? html`<div class="stack c-sec">
        <span class="lbl">Needs a project folder to save into, no extract needed</span>
        ${folder.map((t) => html`<${TabRow} t=${t} lock=${tabLock(t, ps)} />`)}
      </div>` : null}
    ${needs.length ? html`<div class="stack c-sec">
        <span class="lbl">Needs the card extracted into a project folder</span>
        ${needs.map((t) => html`<${TabRow} t=${t} lock=${tabLock(t, ps)} />`)}
      </div>` : null}
  <//>`;
}

// ------------------------------------------------------------ the glass
// The machine's own picture of the card, under the picker.
function Glass({ p }) {
  const [lit, setLit] = useState("");
  const ready = p.state === "ready" && p.src;
  const src = ready ? mediaUrl(p.src) : "";
  const on = !!src && lit === src;
  const ratio = ready && p.w && p.h ? `${p.w} / ${p.h}` : "16 / 9";
  const [what, about] = {
    menu: ["Boot menu", "what the machine shows at power-up, the default game highlighted"],
    splash: ["Loading screen", "what the game shows while it starts up"],
    boot: ["Boot screen", "the Stern logo the machine shows while it starts; this game has no splash of its own"],
  }[p.kind] || ["", ""];
  return html`<figure class="c-figure">
    <div class=${cx("c-glass", on && "on")} style=${`aspect-ratio: ${ratio}`}>
      ${src ? html`<img key=${src} src=${src} alt=${"The card's " + what.toLowerCase()} onLoad=${() => setLit(src)} />` : null}
      ${on ? null : html`<${Booting} stage=${p.stage} sub=${p.games ? `Multi-boot card · ${p.games} games` : ""} />`}
    </div>
    ${on ? html`<figcaption class="small">
        <span class="c-cap-t">${what}</span><span class="dim"> · ${about}</span>
        ${p.note ? html`<div class="warn-ink c-cap-note">${p.note}</div>` : null}
      </figcaption>` : null}
  </figure>`;
}

// ------------------------------------------------------ the card details
// The Image Info report, under the card tile.  While it is read the rows it
// will fill shimmer in place.
const SKELETON = [[38, 62], [30, 48], [44, 70], [26, 40], [34, 56]];
function Details({ info }) {
  const loading = info.state === "loading";
  const sections = info.sections || [];
  return html`<${Card} cls="c-info" title="Card details"
      extra=${html`<span class="small dim">${loading ? "" : info.status}</span>
        <${Button} kind="ghost" size="sm" icon="copy" disabled=${loading || !sections.length}
          onClick=${() => call("card.info_copy")} title="Copy the report">Copy<//>
        <${Button} kind="ghost" size="sm" icon="refresh" disabled=${loading}
          onClick=${() => call("card.refresh")} title="Read the card again" />`}>
    ${loading ? html`<div class="c-skel" role="status" aria-label="Reading the card">
        <div class="c-skel-t"></div>
        ${SKELETON.map(([k, v]) => html`<div class="c-skel-row"><i style=${`width:${k}%`}></i><i style=${`width:${v}%`}></i></div>`)}
        <div class="c-skel-t"></div>
        ${SKELETON.slice(0, 3).map(([k, v]) => html`<div class="c-skel-row"><i style=${`width:${v - 10}%`}></i><i style=${`width:${k + 12}%`}></i></div>`)}
      </div>`
      : sections.map((sec) => html`<section class="c-isec">
          <div class="c-isec-t">${sec.title}</div>
          <div class="kv c-ikv">${sec.rows.map(([k, v]) => html`<span class="k">${k}</span><span class="c-wrap">${v}</span>`)}</div>
        </section>`)}
  <//>`;
}

export default function CardTab() {
  const s = useNs("extract");
  const c = useNs("card");
  const shell = useNs("shell");
  useNoStrayDrops();
  const hist = shell.path_history || {};
  const drive = s.drive_label === "Game SSD" ? "game SSD" : (s.drive_label || "card");
  const path = s.ssd ? (s.drive || "") : (s.input || "");
  const have = !!path;
  // The card on the page is the one the preview and the details describe;
  // a path typed a letter at a time settles before it is read.
  useEffect(() => {
    const t = setTimeout(() => call("card.look", path), 250);
    return () => clearTimeout(t);
  }, [path, s.mfr_key]);
  const p = c.preview;
  const showGlass = have && p && (p.state !== "none");
  const sub = "Pick " + inputPhrase(s.input_label) + (s.direct ? " or the " + drive + " in a reader" : "")
    + ". Some tabs work on it straight away; the rest need its files extracted into a project folder first.";
  return html`<div class="page x-page c-page">
    <${PageHead} title="Select card" sub=${sub} />
    <div class="cols c75 x-cols">
      <div class="stack x-col">
        <${Card} cls="x-source" title="Card"
            extra=${s.direct ? html`<${Seg} value=${s.source} onChange=${(v) => call("extract.set_source", v)}
              options=${[{ value: "iso", label: s.iso_label }, { value: "ssd", label: s.ssd_label }]} />` : null}
            footer=${html`<${Button} kind="primary" size="big" iconRight="right" disabled=${!have}
                title=${have ? "Open the Extract tab to pick a project folder and extract this card" : "Pick a card first"}
                onClick=${() => call("ui.select_tab", "extract")}>Go to Extract<//>
              <span class="dim small grow">Only the tabs that need an extract wait for this step.</span>`}>
          <${SourceBody} s=${s} hist=${hist} />
          ${showGlass ? html`<${Glass} p=${p} />` : null}
          ${have && p && p.state === "none" && p.note ? html`<div class="small warn-ink">${p.note}</div>` : null}
        <//>
        ${have && c.info ? html`<${Details} info=${c.info} />` : null}
      </div>
      <div class="stack x-col">
        <${WhatCard} shell=${shell} s=${s} />
      </div>
    </div>
    <${ExtractOverlays} s=${s} />
  </div>`;
}
