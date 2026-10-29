// The Scenes tab's Font bar (PAD-452, DragonRR: "font sizes, kerning, font type... and any
// other FEASIBLE normal font controls ... a TAB like the color profile one"): the selected line
// of text's font, size, spacing, wrapping and alignment, beside the scene.  A tab sticks out of
// the page's right edge under the Colors one; the two bars take turns (scenes.js).
// A Spike 2 scene carries its fonts baked at fixed sizes (each style - GameFont_Primary, a
// plain typeface - one picture of letters per size), so the Font list is the styles THIS
// scene carries, and a size it was not baked at is drawn by the game scaling the nearest one.
// The line's box stays where it is and its words re-flow in it; sizes and spacings are in
// pixels on the screen as the line is drawn now (webui/text_scenes_tree.py, tree_text_*).
// Round 2 (DragonRR): Italic (a slant of the line's own matrix: the fonts have no italic),
// the letters' width, and the drop shadow's Add / Remove, moved here from Selected.
// PAD-514 (DragonRR: "a facility to directly control text colour"): the line's own Color, a
// wheel and a Brightness slider, saved and loaded as files as the color profiles are.  A line
// with a color of its own is drawn in exactly it and the color profile no longer changes it
// (white is already full red: the profile's red sliders could never make white letters red).
// A score panel line the game paints as it plays shows those colors here instead (PAD-507).

import { html, useEffect, useRef, useState, Button, Check, Icon, Select, Seg, tip, call, cx } from "../core/ui.js";
import { GameColors } from "./text_scenes.js";

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

// colors: "#rrggbb" <-> hue (degrees) and saturation (0..1) at full value, the wheel's
const hexRgb = (h) => [1, 3, 5].map((i) => parseInt((h || "#ffffff").slice(i, i + 2), 16) / 255 || 0);
const rgbHex = (c) => "#" + c.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, "0")).join("");
function hexHs(h) {
  const [r, g, b] = hexRgb(h);
  const mx = Math.max(r, g, b), d = mx - Math.min(r, g, b);
  let hue = 0;
  if (d > 0) hue = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(hue * 60 + 360) % 360, mx > 0 ? d / mx : 0];
}
function hsHex(hue, sat) {
  const f = (n) => { const k = (n + hue / 60) % 6; return 1 - sat * Math.max(0, Math.min(k, 4 - k, 1)); };
  return rgbHex([f(5), f(3), f(1)]);
}
// the color a line is drawn in: the one picked at its brightness (text_colour.shade)
const shadeHex = (h, bright) => rgbHex(hexRgb(h).map((v) => v * Math.max(0, Math.min(100, bright)) / 100));

const px = (v) => `${Math.round(v * 10) / 10}`;
const pxList = (sizes) => (sizes.length < 2 ? px(sizes[0] || 0)
  : `${sizes.slice(0, -1).map(px).join(", ")} and ${px(sizes[sizes.length - 1])}`);

// a number (screen pixels unless *unit* says), sent when it is committed (Enter, leaving
// the box, the arrows)
function Num({ label, value, onCommit, title, step = 1, unit = "px" }) {
  return html`<label class="fnt-num" ...${tip(title)}>
    <span class="lbl">${label}</span>
    <div class="field sm"><input type="number" step=${step} value=${value ?? ""}
      onChange=${(e) => { if (e.target.value !== "") onCommit(e.target.value); }} /></div>
    <span class="small muted">${unit}</span>
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
        ...${tip({ head: "Font", lines: ["The selected line of text's color, font, size, italic, letter width, spacing, wrapping, alignment and drop shadow, beside the scene."] })}>
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
            : "Click a line of text in the preview, or a text row in Layers, to set its color, font, size and spacing."}</p>`}
      </div>
    </aside></div>
  </div>`;
}

// The color wheel: hue round it, white in the middle (saturation out to the rim).  A drag
// shows the color as it goes; letting go sets it.
function Wheel({ hex, onMove, onPick }) {
  const ref = useRef(null);
  const drag = useRef(false);
  const [hue, sat] = hexHs(hex);
  const at = (e) => {
    const r = ref.current.getBoundingClientRect();
    const x = e.clientX - (r.left + r.width / 2), y = e.clientY - (r.top + r.height / 2);
    return hsHex((Math.atan2(y, x) * 180 / Math.PI + 450) % 360, Math.min(1, Math.hypot(x, y) / (r.width / 2)));
  };
  const down = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    drag.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    onMove(at(e));
  };
  const move = (e) => { if (drag.current) onMove(at(e)); };
  const up = (e) => { if (!drag.current) return; drag.current = false; onPick(at(e)); };
  const a = hue * Math.PI / 180;
  return html`<div class="fnt-wheel" ref=${ref} role="slider" aria-label="Color wheel" aria-valuetext=${hex}
      onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${() => { drag.current = false; }}
      ...${tip({ head: "Color wheel", lines: ["Round the wheel: which color. Toward the middle: paler, to white in the middle.",
        ["Click or drag", "pick the line's color"], "Brightness below makes it darker."] })}>
    <span class="fnt-wheel-dot" style=${`left:${50 + Math.sin(a) * sat * 50}%;top:${50 - Math.cos(a) * sat * 50}%;background:${hex}`}></span>
  </div>`;
}

const COLOR_TIP = { head: "This line's color", lines: [
  "Gives this line of text a color of its own: it is drawn in exactly this color, in the preview and on the machine.",
  "The color profile no longer changes this line while it has a color of its own. Default puts back the game's color, and the color profile if the line has one.",
  "A color profile can only bend the colors a line already has: white is already full red, green and blue, so turning red up leaves white letters white. A color here sets it directly."] };

// PAD-514: the line's own color (c: the line's font.colour from text_scenes_tree.py)
function TextColor({ p, c }) {
  const id = p.id;
  const [pick, setPick] = useState(c.pick);
  const [bright, setBright] = useState(c.bright);
  useEffect(() => { setPick(c.pick); setBright(c.bright); }, [id, c.pick, c.bright, c.own]);
  const send = (h, b) => call("text_scenes.tree_text_colour", id, h, b);
  const drawn = c.own || pick !== c.pick || bright !== c.bright ? shadeHex(pick, bright) : c.hex;
  const saved = c.saved || [];
  return html`<div class="fnt-sec fnt-color">
    <div class="row fnt-row"><span class="eyebrow" ...${tip(COLOR_TIP)}>Color</span><span class="sp"></span>
      <span class=${cx("small nw", c.own ? "ok-ink" : "muted")}>${c.own ? "Its own color" : "Default"}</span></div>
    <div class="row fnt-row fnt-color-row">
      <${Wheel} hex=${pick} onMove=${setPick} onPick=${(h) => { setPick(h); send(h, bright); }} />
      <div class="fnt-color-side">
        <span class="fnt-swatch" style=${`background:${drawn}`} ...${tip(c.own ? "The color this line is drawn in" : "The color this line is drawn in now")}></span>
        <span class="mono small">${drawn}</span>
        <label class="fnt-exact-lbl small" ...${tip({ head: "Exact color", lines: ["Pick or type an exact color (#RRGGBB) instead of using the wheel."] })}>
          <input type="color" class="tree-color fnt-exact" value=${pick} aria-label="Exact color"
            onInput=${(e) => setPick(e.target.value)} onChange=${(e) => send(e.target.value, bright)} />
          <span>Exact…</span></label>
        <${Button} size="xs" icon="undo" disabled=${!c.own} onClick=${() => send(null)}
          title=${{ head: "Default", lines: ["Take this line's own color off: the game's color comes back, and the color profile if the line has one."] }}>Default<//>
      </div>
    </div>
    <label class="row fnt-row fnt-bright" ...${tip({ head: "Brightness", lines: ["100% is the color as picked; lower is darker, down to black at 0%."] })}>
      <span class="lbl">Brightness</span>
      <input type="range" min="0" max="100" step="1" value=${bright} aria-label="Brightness"
        onInput=${(e) => setBright(Number(e.target.value))} onChange=${(e) => send(pick, Number(e.target.value))} />
      <span class="small mono fnt-pct">${bright}%</span>
    </label>
    <div class="small muted fnt-note">${c.own
      ? "Drawn in its own color, so the color profile does not change this line."
      : "Picking a color here gives this line its own color and takes the color profile off it."}${c.art
      ? " Its font's letters carry colors of their own: they keep their light and shade, in this color (the line gets its own copy of the font)." : ""}</div>
    <div class="row fnt-row fnt-saved">
      <span class="lbl" ...${tip({ head: "Saved colors", lines: ["Colors kept with Save a copy, one file each, as saved color profiles are. Click one to give it to this line.",
        saved.length ? "" : "None yet: Save a copy keeps the color on show here."].filter(Boolean) })}>Saved</span>
      ${saved.length ? saved.map((s) => html`<button type="button" key=${s.path} class="fnt-saved-sw"
          style=${`background:${shadeHex(s.pick, s.bright)}`} aria-label=${s.name}
          ...${tip({ head: s.name, lines: [`${s.pick}${s.bright !== 100 ? ` at ${s.bright}% brightness` : ""}`, ["Click", "give this line that color"]] })}
          onClick=${() => call("text_scenes.tree_text_colour_use", id, s.path)}></button>`)
        : html`<span class="small muted">none yet</span>`}
    </div>
    <div class="row fnt-row">
      <span class="sp"></span>
      <${Button} size="xs" icon="save" onClick=${() => call("text_scenes.tree_text_colour_save", pick, bright)}
        title="Save this color as a file of its own, listed under Saved from then on (as Save a copy keeps a color profile)">Save a copy...<//>
      <${Button} drop size="xs" icon="upload" onClick=${() => call("text_scenes.tree_text_colour_load", id)}
        title="Load a text color saved earlier and give it to this line">Load...<//>
    </div>
    <div class="row fnt-row fnt-color-all">
      <span class="sp"></span>
      <${Button} size="xs" icon="copy" onClick=${() => call("text_scenes.tree_text_colour_all", id)}
        title=${ALL_TIP}>Apply to all lines of text…<//>
    </div>
  </div>`;
}

// PAD-528 (DragonRR: "make sure that this can also be done with font colour changes"):
// Apply to all for the line's own color, or Default, in the words of the Colors bar's
// Apply to all lines of text (PAD-471)
const ALL_TIP = "This will change all of your unlocked lines of text to the color you have selected in this tab, or back to Default if this line has no color of its own. This may mean that every single line of text, the game's own and the ones you added, in every scene will be affected. The score panel lines the game paints are left as they are. You can undo this function";

// PAD-507 / PAD-514: a score panel line is painted by the game as it plays, so its colors
// are the game's, picked here as under Selected
function GamePainted({ g }) {
  return html`<div class="fnt-sec fnt-color">
    <span class="eyebrow">Color</span>
    <${GameColors} g=${g} />
    <div class="small muted fnt-note">The game paints this line's color as it plays, so it is picked here: a color of its own would be painted over.</div>
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
    ${p.game_colors ? html`<${GamePainted} g=${p.game_colors} />`
      : f.colour ? html`<${TextColor} p=${p} c=${f.colour} />` : null}
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
      <span class="eyebrow">Style</span>
      <${Check} checked=${f.italic} label="Italic" cls="small"
        onChange=${(v) => call("text_scenes.tree_text_italic", id, v)}
        title=${{ head: "Italic", lines: ["Slants the letters, their tops to the right, the way a word processor slants a font that has no italic of its own (Stern's fonts have none).",
          "The game draws it slanted too. Slant sets how far."] }} />
      <div class="row fnt-row">
        <${Num} label="Slant" value=${f.slant} unit="°" onCommit=${(v) => call("text_scenes.tree_text_slant", id, v)}
          title=${{ head: "Slant", lines: ["How far the letters lean, in degrees: 0 = upright as shipped, 12 = Italic, below 0 leans them left."] }} />
        <${Num} label="Width" value=${f.width} unit="%" onCommit=${(v) => call("text_scenes.tree_text_width", id, v)}
          title=${{ head: "Letter width", lines: ["How wide the letters are, % of as shipped: below 100 is narrower (condensed), above wider. Their height stays.",
            "The box stays where it is: the words re-flow in it."] }} />
      </div>
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
          options=${[["left", "Left"], ["centre", "Center"], ["right", "Right"]].map(([v, l]) => ({ value: v, label: l,
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
      </div>
    </div>
    <div class="fnt-sec">
      <span class="eyebrow">Drop shadow</span>
      <div class="row fnt-row">
        <${Button} size="xs" disabled=${(f.shadow || {}).has || (f.shadow || {}).is}
          title=${(f.shadow || {}).is ? "This is a drop shadow." : (f.shadow || {}).has ? "This line has a drop shadow already."
            : "A dark copy of this text just beneath it, a few pixels down and right. It is selected after, to move, tint or remove."}
          onClick=${() => call("text_scenes.tree_shadow", id)}>Add a drop shadow<//>
        <${Button} size="xs" disabled=${!(f.shadow || {}).has && !(f.shadow || {}).is}
          title=${(f.shadow || {}).is ? "Take this drop shadow away; its line is selected after."
            : "Take this line's drop shadow away, with any move or tint you gave it."}
          onClick=${() => call("text_scenes.tree_shadow_remove", id)}>Remove drop shadow<//>
      </div>
    </div>
    <div class="row fnt-row fnt-foot">
      <span class="sp"></span>
      <${Button} size="xs" icon="undo" disabled=${!f.edited}
        title="Put this line's font, size, style, spacing, wrapping and alignment back as the game shipped them. Its box and place are kept, and so are a drop shadow and its color (Default under Color puts that back)."
        onClick=${() => call("text_scenes.tree_text_font_reset", id)}>Font as shipped<//>
    </div>`;
}
