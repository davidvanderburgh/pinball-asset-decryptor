// The Scenes tab's Font bar (PAD-452, DragonRR: "font sizes, kerning, font type... and any
// other FEASIBLE normal font controls ... a TAB like the color profile one"): the selected line
// of text's font, size, spacing, wrapping and alignment, beside the scene.  A tab sticks out of
// the page's right edge under the Colors one; the two bars take turns (scenes.js).
// A Spike 2 scene carries its fonts baked at fixed sizes (each style - GameFont_Primary, a
// plain typeface - one picture of letters per size), so the Font list is the styles THIS
// scene carries, and a size it was not baked at is drawn by the game scaling the nearest one.
// The line's box stays where it is and its words re-flow in it; sizes and spacings are in
// pixels on the screen as the line is drawn now (webui/text_scenes_tree.py, tree_text_*).

import { html, Button, Check, Icon, Select, Seg, tip, call, cx } from "../core/ui.js";

const CSS_HREF = "/static/css/tabs/scene_fonts.css";
if (typeof document !== "undefined" && !document.querySelector(`link[href="${CSS_HREF}"]`)) {
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = CSS_HREF;
  document.head.appendChild(l);
}

const OPEN_KEY = "pad.fontbar.open";

export function fontBarOpenAtStart() {
  try { return localStorage.getItem(OPEN_KEY) === "1"; } catch (e) { return false; }
}

export function rememberFontBarOpen(open) {
  try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch (e) { /* private mode */ }
}

const px = (v) => `${Math.round(v * 10) / 10}`;
const pxList = (sizes) => (sizes.length < 2 ? px(sizes[0] || 0)
  : `${sizes.slice(0, -1).map(px).join(", ")} and ${px(sizes[sizes.length - 1])}`);

// a number in screen pixels, sent when it is committed (Enter, leaving the box, the arrows)
function Num({ label, value, onCommit, title, step = 1 }) {
  return html`<label class="fnt-num" ...${tip(title)}>
    <span class="lbl">${label}</span>
    <div class="field sm"><input type="number" step=${step} value=${value ?? ""}
      onChange=${(e) => { if (e.target.value !== "") onCommit(e.target.value); }} /></div>
    <span class="small muted">px</span>
  </label>`;
}

// t: the scene editor's tree_view (its props are the selected layer's)
export function FontBar({ open, setOpen, t }) {
  const p = t && t.props;
  const multi = !!t && (t.sels || []).length > 1;
  const f = p && !multi && p.kind === "Text" ? p.font : null;
  return html`<div class=${cx("cpd fnt", open && "open")}>
    <button type="button" class="cpd-handle fnt-handle" aria-expanded=${open ? "true" : "false"} aria-controls="fnt-panel"
        aria-label="Font" onClick=${() => setOpen(!open)}
        ...${tip({ head: "Font", lines: ["The selected line of text's font, size, letter and line spacing, wrapping and alignment, beside the scene."] })}>
      <span class="cpd-handle-ico"><${Icon} name="text" /></span>
      <span class="cpd-handle-txt">Font</span>
    </button>
    <div class="cpd-clip"><aside class="cpd-panel fnt-panel" id="fnt-panel" aria-label="Font"
        aria-hidden=${open ? "false" : "true"} inert=${open ? undefined : ""}>
      <div class="cpd-hd">
        <span class="cpd-title">Font</span>
        <span class="sp"></span>
        <${Button} size="xs" kind="ghost" icon="x" onClick=${() => setOpen(false)} title="Close the Font bar" />
      </div>
      <div class="cpd-body fnt-body">
        ${f ? html`<${FontControls} p=${p} f=${f} />`
          : html`<p class="small muted cpd-words">${multi
            ? "Several layers are selected: click one line of text on its own to set its font."
            : "Click a line of text in the preview, or a text row in Layers, to set its font, size and spacing."}</p>`}
      </div>
    </aside></div>
  </div>`;
}

function FontControls({ p, f }) {
  const id = p.id;
  const style = (f.styles || []).find((s) => s.value === f.style);
  const sizes = style ? style.sizes : [];
  const many = (f.styles || []).length > 1;
  return html`
    <div class="cpd-file">
      <div class="row cpd-file-hd"><span class="eyebrow nw">This line of text</span>
        <span class="mono small ellip" title=${p.name}>${p.name}</span></div>
    </div>
    <div class="fnt-sec">
      <span class="eyebrow">Font</span>
      <${Select} sm value=${f.style} disabled=${!many}
        options=${(f.styles || []).map((s) => ({ value: s.value, label: s.label }))}
        onChange=${(v) => call("text_scenes.tree_text_font", id, v)}
        title=${{ head: "Font", lines: [many
          ? "The fonts this scene carries. A new one keeps the line's size; its box stays where it is and the words re-flow in it."
          : "This scene carries only this font.",
          "Stern bakes each font into each scene, so only these can be picked here."] }} />
      <div class="row fnt-row">
        <${Num} label="Size" value=${f.size} onCommit=${(v) => call("text_scenes.tree_text_size", id, v)}
          title=${{ head: "Size", lines: ["How tall the letters are on the screen, in pixels (the font's own height, as the line is drawn now).",
            "The box stays where it is: bigger words wrap sooner, or shrink to fit, as the box says."] }} />
      </div>
      ${sizes.length ? html`<div class="small muted fnt-note">Made for this scene at ${pxList(sizes)} px, which draw sharpest. The game draws any other size by scaling the nearest one.</div>` : null}
      ${f.fit || f.game_layout ? html`<div class="small muted fnt-note">The words shrink to fit their box, so they are never drawn bigger than it lets them: make the box bigger for bigger words.</div>` : null}
    </div>
    <div class="fnt-sec">
      <span class="eyebrow">Spacing</span>
      <div class="row fnt-row">
        <${Num} label="Letters" value=${f.letter} onCommit=${(v) => call("text_scenes.tree_text_spacing", id, v, null)}
          title=${{ head: "Letter spacing", lines: ["How much more room after each letter, in pixels on the screen. 0 = the font's own spacing; below 0 draws the letters closer together.",
            "It is the line's own number in the scene, so the game spaces it the same way."] }} />
        <${Num} label="Lines" value=${f.line} onCommit=${(v) => call("text_scenes.tree_text_spacing", id, null, v)}
          title=${{ head: "Line spacing", lines: ["How much more room between the lines of the text, in pixels on the screen, on top of the font's own line height."] }} />
      </div>
    </div>
    <div class="fnt-sec">
      <span class="eyebrow">In its box</span>
      ${p.align ? html`<div class="row fnt-row">
        <span class="lbl">Across</span>
        <${Seg} value=${p.align} onChange=${(v) => call("text_scenes.tree_text_align", id, v, null)}
          options=${[["left", "Left"], ["centre", "Centre"], ["right", "Right"]].map(([v, l]) => ({ value: v, label: l,
            title: `The words sit on the ${v === "centre" ? "middle" : v + " edge"} of the box, here and in the game` }))} />
      </div>
      <div class="row fnt-row">
        <span class="lbl">Up/down</span>
        <${Seg} value=${p.valign} onChange=${(v) => call("text_scenes.tree_text_align", id, null, v)}
          options=${[["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]].map(([v, l]) => ({ value: v, label: l,
            disabled: p.game_layout && v !== p.valign,
            title: p.game_layout
              ? "The game always puts this line in the middle of its box, and shrinks it to fit. To move it up or down, move or resize the box"
              : `The words sit at the ${v} of the box, here and in the game` }))} />
      </div>` : null}
      <${Check} checked=${f.wrap} label="Wrap the words at the box's width" cls="small"
        onChange=${(v) => call("text_scenes.tree_text_flow", id, null, v, null)}
        title="On: a line too long for its box breaks between words onto the next line. Off: it runs on past the box." />
      <${Check} checked=${f.fit || f.game_layout} disabled=${f.game_layout} label="Shrink the words to fit the box" cls="small"
        onChange=${(v) => call("text_scenes.tree_text_flow", id, null, null, v)}
        title=${f.game_layout ? "The game always shrinks this line to fit its box."
          : "On: words too big for the box are drawn smaller until they fit it, across and up and down. They are never drawn bigger."} />
      <${Check} checked=${f.multiline} label="Keep the line breaks" cls="small"
        onChange=${(v) => call("text_scenes.tree_text_flow", id, v, null, null)}
        title="On: each new line in the words starts a new line on the screen. Off: the game runs them together on one line." />
      <div class="row fnt-row">
        <${Button} size="xs" disabled=${p.x == null}
          title="Shrink or grow this text's box to go round its words, with a small border. The words stay where they are."
          onClick=${() => call("text_scenes.tree_fit_text", id)}>Fit box to text<//>
        <span class="sp"></span>
        <${Button} size="xs" icon="undo" disabled=${!f.edited}
          title="Put this line's font, size, spacing, wrapping and alignment back as the game shipped them. Its box and place are kept."
          onClick=${() => call("text_scenes.tree_text_font_reset", id)}>Font as shipped<//>
      </div>
    </div>`;
}
