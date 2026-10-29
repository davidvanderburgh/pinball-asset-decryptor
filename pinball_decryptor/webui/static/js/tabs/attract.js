// Attract tab (PAD-782): the attract mode editor of a Stern Spike 2 game - the game's own attract screens in order,
// with the owner's photos, clips and text cards between them, each for as long as it is set; drag (or the arrows) to
// move one, the menu on a game screen to add after or before it. The modes' challenge champions and the attract
// flipper sounds (kept by the Audio tab) are set here too. Python half: webui/tabs/attract.py.

import { html, useState, PageHead, Card, Button, Field, Check, Chip, Note, Icon, Empty, Spinner, tip, call, cx,
         openMenu } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const T = {
  sometimes: "The game shows this screen only at times (after a game, or with one of its settings on). Your items "
    + "next to it show every time round.",
  drag: "Drag to move it between the game's screens, or use the arrows.",
  seconds: "How long it stays on the screen, in seconds. A clip at 0 plays to its end.",
  tryit: "Start the emulator with this project's changes, your attract items among them.",
  flipper: "Sounds the machine plays when a flipper button is pressed in attract mode. Kept with the project's "
    + "other sounds.",
};

const KIND_ICON = { photo: "image", clip: "film", text: "edit" };

function addMenu(e, g, running) {
  const add = (kind, where) => () => call("attract.add", kind, g.first, g.last, where);
  openMenu(e.currentTarget, [
    { label: "Add photos after it…", icon: "image", disabled: running, onClick: add("photo", "after") },
    { label: "Add a clip after it…", icon: "film", disabled: running, onClick: add("clip", "after") },
    { label: "Add a text card after it", icon: "edit", disabled: running, onClick: add("text", "after") },
    { sep: true },
    { label: "Add photos before it…", icon: "image", disabled: running, onClick: add("photo", "before") },
    { label: "Add a clip before it…", icon: "film", disabled: running, onClick: add("clip", "before") },
    { label: "Add a text card before it", icon: "edit", disabled: running, onClick: add("text", "before") },
  ], { align: "right" });
}

function GameRow({ g, running }) {
  const span = g.n > 1 ? `screens ${g.first + 1}–${g.last + 1}` : `screen ${g.first + 1}`;
  return html`<div class="at-row at-game">
    <span class="at-ic"><${Icon} name="sd" /></span>
    <span class="at-name">${g.name}${g.n > 1 ? html` <span class="muted">×${g.n}</span>` : null}</span>
    <span class="muted small">${span}</span>
    ${g.sometimes ? html`<span ...${tip(T.sometimes)}><${Chip}>at times<//></span>` : null}
    <span class="sp"></span>
    <${Button} size="sm" kind="ghost" icon="plus" disabled=${running} title="Add your own here"
      onClick=${(e) => addMenu(e, g, running)}>Add<//>
  </div>`;
}

function ItemRow({ it, running, onDragStart, onDrop, dragging }) {
  return html`<div class=${cx("at-row at-item", it.missing && "bad", dragging && "dragging")} draggable=${!running}
      onDragStart=${(e) => { e.dataTransfer.effectAllowed = "move"; onDragStart(); }}
      onDragOver=${(e) => e.preventDefault()} onDrop=${(e) => { e.preventDefault(); onDrop(); }}>
    <span class="at-grip" ...${tip(T.drag)}><${Icon} name="grip" /></span>
    <span class="at-ic"><${Icon} name=${KIND_ICON[it.kind] || "image"} /></span>
    ${it.kind === "text"
      ? html`<textarea class="at-text" rows=${Math.max(1, (it.text || "").split("\n").length)} disabled=${running}
          onChange=${(e) => call("attract.set_text", it.i, e.target.value)}>${it.text}</textarea>`
      : html`<span class="at-name">${it.file}${it.missing ? html` <span class="bad small">(not on this PC)</span>` : null}</span>`}
    <span class="sp"></span>
    <span class="small muted">seconds</span>
    <${Field} sm type="number" width="64px" min=${it.kind === "clip" ? 0 : 1} max=${120} value=${String(it.seconds)}
      title=${T.seconds} disabled=${running} onCommit=${(v) => call("attract.set_seconds", it.i, v)} />
    <${Button} size="sm" kind="ghost" icon="up" title="Earlier" disabled=${running} onClick=${() => call("attract.move", it.i, -1)} />
    <${Button} size="sm" kind="ghost" icon="down" title="Later" disabled=${running} onClick=${() => call("attract.move", it.i, 1)} />
    <${Button} size="sm" kind="ghost" icon="x" title="Take it off" disabled=${running} onClick=${() => call("attract.remove", it.i)} />
  </div>`;
}

function Sequence({ s }) {
  const [drag, setDrag] = useState(null);           // the sequence index of the item being dragged
  const seq = s.seq || [];
  const drop = (to) => {
    if (drag === null || drag === to) { setDrag(null); return; }
    call("attract.move_by", seq[drag].i, to - drag);
    setDrag(null);
  };
  return html`<div class="at-seq" onDragEnd=${() => setDrag(null)}>
    ${seq.map((row, n) => row.t === "game"
      ? html`<div onDragOver=${(e) => e.preventDefault()} onDrop=${(e) => { e.preventDefault(); drop(n); }}>
          <${GameRow} g=${row} running=${s.running} /></div>`
      : html`<${ItemRow} it=${row} running=${s.running} dragging=${drag === n}
          onDragStart=${() => setDrag(n)} onDrop=${() => drop(n)} />`)}
  </div>`;
}

function FlipperSounds() {
  const a = useNs("audio");
  const at = a && a.attract;
  if (!at) return html`<span class="muted small">Reading the project's sounds…</span>`;
  if (at.why) return html`<${Note}>${at.why}<//>`;
  const files = at.files || [];
  return html`<div class="stack" style="gap:6px">
    ${files.map((f, i) => html`<div class="at-row at-item">
      <span class="at-ic"><${Icon} name="audio" /></span><span class="at-name">${i + 1}. ${f}</span><span class="sp"></span>
      <${Button} size="sm" kind="ghost" icon="play" title="Play it" onClick=${() => call("audio.attract_action", `play:${i + 1}`)} />
      <${Button} size="sm" kind="ghost" icon="x" title="Take it off" onClick=${() => call("audio.attract_action", `off:${i + 1}`)} />
    </div>`)}
    <div class="row">
      <${Button} drop size="sm" icon="plus" disabled=${files.length >= at.max} onClick=${() => call("audio.attract_action", "add")}>Add a sound…<//>
      ${files.length ? html`<${Button} size="sm" kind="ghost" onClick=${(e) => openMenu(e.currentTarget,
        (at.gaps || []).map((g) => ({ label: g.label, checked: g.s === at.gap,
          onClick: () => call("audio.attract_action", `gap:${g.s}`) })))}>Time between sounds<//>` : null}
    </div>
  </div>`;
}

export default function AttractTab() {
  const s = useNs("attract");
  const head = html`<${PageHead} title="Attract" sub=${s.intro}>
    ${s.count ? html`<${Chip} kind="acc">${s.count} of ${s.max} items<//>` : null}
    <${Button} icon="refresh" disabled=${s.reading} onClick=${() => call("attract.refresh")}>Read again<//>
    <${Button} kind="primary" icon="play" disabled=${!s.available || s.running} title=${T.tryit}
      onClick=${() => call("attract.try_it")}>Run in emulator<//>
  <//>`;
  if (s.reading && !s.pages) {
    return html`<div class="page at-page">${head}<div class="row"><${Spinner} /><span class="muted">Reading the game's attract screens…</span></div></div>`;
  }
  if (!s.available) {
    return html`<div class="page at-page">${head}<${Empty} title="Nothing to edit here" icon="info">${s.why}<//></div>`;
  }
  return html`<div class="page at-page">
    ${head}
    <${Note} kind="warn">${s.insider}<//>
    <${Card} title="Attract, in order" sub="The game's own screens, and yours between them">
      <${Sequence} s=${s} />
    <//>
    ${s.champions_shown ? html`<${Card} title="Champions">
      <${Check} checked=${s.champions} disabled=${s.running} title=${s.champions_tip}
        onChange=${(v) => call("attract.set_champions", v)} label="Show the champion of each mode's challenge game" />
    <//>` : null}
    <${Card} title="Flipper sounds" sub=${T.flipper}>
      <${FlipperSounds} />
    <//>
  </div>`;
}
