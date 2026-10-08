// Replace Video tab: scan the project folder's clips, pick a replacement per
// slot (or a whole folder of them), compare Original and Replacement side by
// side, and decide per clip whether Write converts it.  Python half:
// webui/tabs/video.py (every rule, message and file operation lives there).

import { html, useEffect, useMemo, useRef, useState, PageHead, Button, Field, Check, Seg, Chip,
         Note, Table, Empty, Modal, Icon, Spinner, Select, openMenu, menuOpen, tip, call, cx, mediaUrl }
  from "../core/ui.js";
import { useNs } from "../core/store.js";
import { LookRow } from "../core/look.js";
import { ColorBar, barOpenAtStart, rememberBarOpen } from "./color_pane.js";
import { LookGL } from "./video_gl.js";

export const css = true;

// Word for word from the Tk tab (gui/main_window.py _build_video_tab).
const T = {
  intro: "Assign a replacement clip to any slot — a matching clip is used as-is, anything else is auto-re-encoded — then build the update on the Write tab.",
  ffmpeg: "ffmpeg not found — replacing video needs ffmpeg to re-encode + preview clips. Install it with “Install Missing” above the tabs.",
  project: "The project folder — shared by every tab. It is set on the Extract tab. Click to open it.",
  csv: "Save the whole video table (every slot, not just the filtered view) as a CSV — name, length, resolution, format, audio, replacement and changed-on-disk status — for tracking a big replacement project in a spreadsheet.",
  check: "Measure every clip already written to a card image and list the ones low enough in bitrate to look blocky — the Write-time \"it will look very blocky\" check, asked of a finished card. Reads the image only; nothing is written.",
  folder: "Pick a folder of your own files and each one becomes the replacement for the slot with the same name — for a whole set you reworked outside the app, like every clip made black and white. The file type and capital letters don't have to match (Intro.mp4 is used for Intro.mov and converted to suit it), and subfolders are fine. Nothing changes until you confirm, and every file left out is named in the log.\n\nKeep the extract's own files where they are: files dropped into the project folder only count under the card's exact name.",
  clear: "Drop every replacement picked on this tab in one go — for starting a project over without clearing 48 rows one at a time. It only drops the picks: your own files are untouched, and a slot already built into the project folder keeps the bytes it has (use “Revert all changes…” on the Write tab for those). To clear only some, select the rows — click, then Shift-click or Ctrl-click — and right-click the selection.",
  show: "Narrow the list by what you've already done to it. Changed = the slots with a pending replacement or already changed on disk by a previous build. Unchanged = everything you haven't touched yet, so a part-finished pass is what's left in front of you instead of something to scroll past.",
  noconv: "Use my files as-is — never re-encode (all slots)",
  noconvTip: "Applies to every replacement you have picked, not just the selected one — tick or untick it any time and the Convert column re-answers for the whole list. Nothing has to be picked again.\n\nOn: replacements are copied in byte-for-byte, so each one has to already be the clip's container, codec, resolution and frame rate. Lossless and fast, but the file has to be game-ready — a clip the machine can't decode plays its sound over a black picture, and the Convert column says \"✗ wrong format\" when it can see that coming.\n\nOff: anything that isn't already a match is converted to suit the slot, at full size — and a clip that is already this slot's video in the wrong container is repackaged rather than re-encoded, so it loses nothing either.\n\nFor a single clip, right-click its row and use \"This clip's conversion\" — that setting wins over this box, either way, so one hand-encoded clip can go on untouched in a project that converts everything else.",
  trim: "Trim / pad to the original clip length",
  specIntro: "A replacement matching this goes onto the card untouched, at full quality. Anything else has to be converted first — untick \"Use my files as-is\" and the app will do it.",
  specCmd: "To encode your own, start from this and tune whatever you like around it (bitrate, preset, and the key-frame interval unless Key frames is listed above) — the flags below are the parts that have to match:",
  specAn: "The -an is deliberate: this slot's clip has no audio track, and one you add will be played.",
  best: "Convert every replaced clip at full quality from your own files, for a card built with room to spare (Write tab → SD card size). If this project doesn't know which files your clips came from, it finds them: point it at a card built with your videos and the folder they are in.",
  compare: "Play the selected clips side by side, big, beside the Color profiles bar: up to 4 (Ctrl-click or Shift-click rows to select them). One clip shows its Original beside its Replacement.\n\nClick a clip there and the bar changes its colors, so you see a profile or a slider on it against the others as you go.",
  // PAD-444: which of the game's modes plays each clip, read off the card's game program
  modes: "Which of the game's battles, multiballs and other modes play this clip, read from the card's game program. A clip two modes share has a row for each: choose a replacement in one mode's row to change it for that mode only. Not played: nothing in the game asks for the clip, so the machine never shows it.",
  modeFilter: "List only the clips one mode of the game plays.",
  modesBusy: "Reading which mode plays each clip…",
  // PAD-453 (DragonRR)
  undoNone: "Nothing to undo yet: choosing or clearing a replacement, Replace from folder, a clip's conversion, length, colors or random clips, and the boxes over the list each make a step.",
  redoNone: "Nothing to redo: Redo does again what Undo just took back, until the next change.",
  qTitle: "Check the videos already on a card",
  qIntro: "Measures every clip on a built card image and lists the ones whose bitrate is low enough to look blocky — the same test a Write applies to a replacement, applied after the fact to what is actually on the card. This reads the card image only; nothing is written and nothing is extracted.",
};

// ------------------------------------------------------------ playback
// The page's two players.  Starting one pauses the other so the soundtracks
// never overlap (the Tk panes' sibling rule).
const players = { orig: null, rep: null };
function playingSide() {
  for (const side of ["orig", "rep"]) {
    const v = players[side];
    if (v && !v.paused && !v.ended) return side;
  }
  return null;
}
function pauseAll() {
  for (const side of ["orig", "rep"]) {
    const v = players[side];
    if (v && !v.paused) v.pause();
  }
}

const probe = typeof document !== "undefined" ? document.createElement("video") : null;
const can = (t) => { try { return !!(probe && probe.canPlayType(t)); } catch (e) { return false; } };
const H264 = 'video/mp4; codecs="avc1.42E01E"';
const OK_PIX = ["", "yuv420p", "yuvj420p", "yuva420p"];
// Whether this engine plays the clip as it is (Qt WebEngine has no H.264,
// no engine has ProRes or a custom .cdmd); if not, Python makes a copy.
function enginePlays(f) {
  if (!f || f.backend) return false;
  if (!OK_PIX.includes(f.pix_fmt || "")) return false;
  const c = f.codec || "";
  if (["mp4", "m4v", "mov"].includes(f.ext)) {
    if (c === "h264") return can(H264);
    if (c === "hevc") return can('video/mp4; codecs="hvc1.1.6.L93.B0"');
    if (c === "av1") return can('video/mp4; codecs="av01.0.05M.08"');
    return false;
  }
  if (f.ext === "webm") {
    if (c === "vp9") return can('video/webm; codecs="vp9"');
    if (c === "vp8") return can('video/webm; codecs="vp8"');
    if (c === "av1") return can('video/webm; codecs="av01.0.05M.08"');
    return false;
  }
  if (f.ext === "ogv") return c === "theora" && can('video/ogg; codecs="theora"');
  return false;
}
const proxyFormat = () => (can(H264) ? "mp4" : "webm");

// _VideoPreviewPane._update_time: m:ss, or 0:00.mmm for a sub-second clip.
function clock(pos, dur) {
  if (!(dur > 0)) return "0:00 / 0:00";
  const fine = dur < 1;
  const f = (s) => {
    s = Math.max(0, Number(s) || 0);
    if (fine) return "0:00." + String(Math.floor(Math.min(s, dur) * 1000)).padStart(3, "0");
    s = Math.floor(s);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  };
  return f(pos) + " / " + f(dur);
}

// ------------------------------------------------------------ column fit
// MainWindow._autosize_tree_columns: a column the user hasn't dragged fits
// its widest cell (the header included), capped at 480 px, never under the
// Tk tree's minwidth.  Measured over every slot, not only the filtered view,
// so typing in Search doesn't make the columns jump.
const FIT_MAX = 480;
const COL_MIN = { rel: 160, len: 46, res: 70, fmt: 80, aud: 70, rep: 110, col: 56, conv: 60, modes: 110 };
const HEADS = { rel: "Original Video", len: "Length", res: "Resolution", fmt: "Format",
                aud: "Audio", rep: "Replacement", col: "Color", conv: "Convert", modes: "Played in" };
// PAD-444: a row's Played in cell, in words
const modesText = (r) => (r.unplayed ? "Not played" : r.other ? "Other parts of the game"
  : (r.modes || []).join(", "));
// PAD-312: the chosen-files color profile, baked into this clip as it is converted
const COLOR_TIP = "Green: a color profile is attached to this file. The Color profile tab's individual files profile is baked into it when you build (it is re-encoded for that). Red: no color profile is attached; it goes on the card as it is. Blue lock: the game's own clip, never touched (tick Advanced to unlock it). A palette you click is this clip's own setting; the Color profile tab's Every replaced video box sets the rest.";
// PAD-336: the Advanced box unlocks the game's own clips on this tab only
const ADV_TIP = { head: "Advanced: unlock the game's own clips", lines: [
  "Gives the game's own clips a Color palette too, on this tab only (the Images tab has its own box for pictures, and Scenes keeps its locks).",
  "A clip you attach the color profile to is re-encoded from its original with the Color profile tab's individual files profile when you build.",
  "Untick it to lock them again; any clip already built that way gets its original back."] };
// PAD-368: the profile a clip has, for its tooltips (null where the Color column is not offered);
// PAD-369: a {profile} line, drawn in the one color every tooltip gives it (core/ui.js)
const profileLine = (r, cs) => (r.col_lock ? { profile: "None" } : r.col == null ? null
  : { profile: r.col ? ((cs.own_names || {}).videos || {})[r.rel] || cs.asset_name || "Recommended" : "None" });
// PAD-334: the same blue lock / red / green palette as a picture's switch in Scenes
const colorTip = (r, cs) => (r.col_lock
  ? { head: "Color: the game's own clip", lines: [
      profileLine(r, cs),
      "Stern made it for the machine's screen, so the individual files profile is not offered on it.",
      "Choose a replacement to correct a clip of your own, or tick Advanced to unlock it."] }
  : r.col_stock
  ? { head: r.col ? "Color profile attached to this file" : "No color profile attached to this file", lines: [
      profileLine(r, cs),
      ["Click", r.col ? "detach the color profile" : "attach the color profile"],
      r.col ? "It is re-encoded from its original with its color profile when you build."
        : "Unlocked by Advanced. It stays as the game shipped it.",
      "Set for this clip only: the Every replaced video box never reaches the game's own clips."] }
  : { head: r.col ? "Color profile attached to this file" : "No color profile attached to this file", lines: [
      profileLine(r, cs),
      ["Click", r.col ? "detach the color profile" : "attach the color profile"],
      r.col ? "Its color profile is baked into this clip when you build (it is re-encoded for that). Open Colors with it selected to give it one of its own."
        : "It goes on the card as it is.",
      r.col_own ? "Set for this clip." : "Follows the Color profile tab's box for every replaced video."] });
// The long-named columns share the width that is left over (more or less
// of it); the others keep the width that fits them, so a narrow window
// shortens names, never "MP4 h264 30fps" or a length.
const FLEX = ["rel", "rep", "modes"];
const ROW_H = 34;
let measurer = null;
const textCache = new Map();
function textWidth(text, font) {
  if (!text) return 0;
  const k = font + "|" + text;
  let w = textCache.get(k);
  if (w == null) {
    if (!measurer) measurer = document.createElement("canvas").getContext("2d");
    measurer.font = font;
    w = measurer.measureText(text).width;
    if (textCache.size > 50000) textCache.clear();
    textCache.set(k, w);
  }
  return w;
}
function tableFonts() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n, d) => (cs.getPropertyValue(n) || "").trim() || d;
  return { body: "13.5px " + v("--sans", "sans-serif"), mono: "12.5px " + v("--mono", "monospace"),
           head: "600 12px " + v("--cond", "sans-serif"), headNum: "600 12.5px " + v("--mono", "monospace") };
}
let rowFits = new WeakMap();
function rowFit(r, f) {
  let w = rowFits.get(r);
  if (!w) {
    w = { rel: textWidth(r.dir, f.mono) + textWidth(r.name, f.body), len: textWidth(r.len, f.mono),
          res: textWidth(r.res, f.body), fmt: textWidth(r.fmt, f.body), aud: textWidth(r.aud, f.body),
          rep: textWidth(r.rep, f.body), col: 0, conv: textWidth(r.conv, f.body),
          modes: textWidth(modesText(r), f.body) };
    rowFits.set(r, w);
  }
  return w;
}
function fitColumns(rows) {
  const f = tableFonts();
  const out = {};
  for (const k in HEADS) {
    const label = HEADS[k].toUpperCase();
    // the header's letters, its .06em tracking, and room for the ▲ / ▼
    // (Length's header is set in the numbers' mono face)
    out[k] = textWidth(label, k === "len" ? f.headNum : f.head) + label.length * 0.72 + 18;
  }
  for (const r of rows) {
    const w = rowFit(r, f);
    for (const k in w) if (w[k] + 6 > out[k]) out[k] = w[k] + 6;
  }
  for (const k in out) out[k] = Math.round(Math.max(COL_MIN[k], Math.min(out[k], FIT_MAX)));
  return out;
}
const zoomOf = () => parseFloat(document.documentElement.style.zoom) || 1;

// PAD-329/330: the preview's colour switches.  The service hands each player its colour
// steps (core/colour_profile.py filter_step: a saturation matrix, a gamma
// curve per channel, and a machine screen's curves as tables); they become one SVG filter the <video> is drawn
// through, live on the GPU, in sRGB as the profile's maths is.
function LookFilter({ id, steps }) {
  if (!steps || !steps.length) return null;
  const prims = [];
  steps.forEach((st, i) => {
    if (st.m) prims.push(html`<feColorMatrix key=${"m" + i} type="matrix" values=${st.m.join(" ")} />`);
    if (st.f) prims.push(html`<feComponentTransfer key=${"f" + i}>
      <feFuncR type="gamma" amplitude=${st.f[0][0]} exponent=${st.f[0][1]} offset=${st.f[0][2]} />
      <feFuncG type="gamma" amplitude=${st.f[1][0]} exponent=${st.f[1][1]} offset=${st.f[1][2]} />
      <feFuncB type="gamma" amplitude=${st.f[2][0]} exponent=${st.f[2][1]} offset=${st.f[2][2]} />
    </feComponentTransfer>`);
    // PAD-339: a machine screen's curves, as tables
    if (st.t) prims.push(html`<feComponentTransfer key=${"t" + i}>
      <feFuncR type="table" tableValues=${st.t[0].join(" ")} />
      <feFuncG type="table" tableValues=${st.t[1].join(" ")} />
      <feFuncB type="table" tableValues=${st.t[2].join(" ")} />
    </feComponentTransfer>`);
  });
  return html`<svg class="vid-lookdefs" width="0" height="0" aria-hidden="true" focusable="false">
    <filter id=${id} color-interpolation-filters="sRGB">${prims}</filter>
  </svg>`;
}

// PAD-454 (DragonRR): Compare's Original / With its color profile switch, on each of the two
// players: the clip as it is, or drawn through its color profile, attached or not.  Only the
// player changes (video.py set_pane_view); the palette is what attaches it.
const PROFILE_WORDS = "With its color profile";
function PaneView({ side, view, look }) {
  if (!view) return null;
  const filesOn = !!(look.on && (look.sw || {}).files);
  const plainTip = side === "orig" ? "The game's clip without its color profile."
    : view.stock ? "The game's clip as it shipped, without its color profile."
    : "Your replacement as you made it, without its color profile.";
  const options = [
    { value: "plain", label: view.plain, title: { head: view.plain, lines: [plainTip,
      "The other Preview colors switches still apply."] } },
    { value: "profile", label: PROFILE_WORDS, disabled: !filesOn, title: { head: PROFILE_WORDS, lines: [
      { profile: view.name },
      filesOn ? (view.on ? "The clip drawn through the color profile attached to it, as the card gets it."
        : "The clip drawn through its color profile as it would be attached. It is not attached: click its palette for that.")
        : "Tick Individual files under Preview colors to see it.",
      "Only this player changes: nothing is attached or changed."] } },
  ];
  return html`<div class="row vid-view">
    <${Seg} value=${view.view} options=${options} onChange=${(v) => call("video.set_pane_view", side, v)} />
    <span class="small ellip">${!filesOn ? html`<span class="muted">Individual files is off under Preview colors.</span>`
      : html`Color profile: <span class="vcm-cp">${view.name}</span>${view.on ? null
        : html`<span class="muted">, not attached</span>`}`}</span>
  </div>`;
}

function Pane({ pane, side, play, stopSeq, onEmptyPlay, head, look }) {
  const vref = useRef(null);
  const [glLive, setGlLive] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [failed, setFailed] = useState(false);
  const wantPlay = useRef(0);
  const asked = useRef(0);
  const facts = pane.facts;
  const dur = (facts && facts.dur) || 0;
  const direct = !!(pane.path && facts && enginePlays(facts) && !failed);
  const src = pane.proxy || (direct ? pane.path : null);

  useEffect(() => { setFailed(false); setPos(0); setPlaying(false); wantPlay.current = 0; }, [pane.seq]);
  // Ask Python for a playable copy when the engine can't take the file.
  useEffect(() => {
    if (!pane.path || !facts || pane.proxy || pane.proxy_busy || pane.proxy_err) return;
    if (direct) return;
    if (asked.current === pane.seq) return;
    asked.current = pane.seq;
    call("video.make_proxy", side, pane.seq, proxyFormat());
  }, [pane.seq, !!facts, direct, pane.proxy, pane.proxy_busy]);
  useEffect(() => { players[side] = vref.current; return () => { if (players[side] === vref.current) players[side] = null; }; });
  // autoplay: a row change while playing resumes on the same pane
  useEffect(() => {
    if (!play || play.side !== side || !play.seq) return;
    wantPlay.current = play.seq;
    const v = vref.current;
    if (v && src && v.readyState >= 2) { wantPlay.current = 0; start(); }
  }, [play && play.seq]);
  useEffect(() => { const v = vref.current; if (v && !v.paused) v.pause(); }, [stopSeq]);

  function start() {
    const v = vref.current;
    if (!v) return;
    const other = players[side === "orig" ? "rep" : "orig"];
    if (other && !other.paused) other.pause();
    if (v.ended || (dur > 0 && v.currentTime >= dur - 0.05)) v.currentTime = 0;
    const p = v.play();
    if (p && p.catch) p.catch(() => {});
  }
  function toggle() {
    const v = vref.current;
    if (!pane.path) { onEmptyPlay && onEmptyPlay(side); return; }
    if (!v || !src) { wantPlay.current = -1; return; }
    if (v.paused) start(); else v.pause();
  }
  function stop() {
    // ■ stops the sibling too (it keeps its playhead); this pane goes back
    // to the still it opened with and its button to ▶ (Tk stop_to_start).
    const other = players[side === "orig" ? "rep" : "orig"];
    if (other && !other.paused) other.pause();
    const v = vref.current;
    wantPlay.current = 0;
    setPlaying(false);
    setPos(0);
    if (!v) return;
    v.pause();
    // load() drops the queued "pause" event, so the state is set above
    if (src) v.load();
  }
  const onEnded = (e) => {
    // played to the end: back to 0:00 and the still, as ■ does (Tk _tick)
    setPlaying(false);
    setPos(0);
    const v = e.currentTarget;
    if (v && src) v.load();
  };
  const onError = () => {
    if (!pane.proxy && src) { setFailed(true); asked.current = 0; }
  };
  const onReady = () => {
    if (wantPlay.current) { wantPlay.current = 0; start(); }
  };

  let overlay = null;
  if (!pane.path) overlay = html`<div class="hint">${pane.hint || ""}</div>`;
  else if (pane.proxy_busy && !src) overlay = html`<div class="hint"><${Spinner} /><span>Preparing a preview copy…</span></div>`;
  else if (pane.proxy_err && !src) overlay = html`<div class="hint err-ink">${pane.proxy_err}</div>`;
  else if (!facts) overlay = html`<div class="hint">loading frame…</div>`;
  else if (!playing && pos === 0 && pane.poster_note && !pane.poster) overlay = html`<div class="hint">${pane.poster_note}</div>`;

  const steps = look && look.on ? look[side] : null;
  // PAD-448: the exact colour table where WebGL draws it, else the SVG filter
  const lut = look && look.on && look.lut ? look.lut[side] : null;
  const fid = "vid-look-" + side;
  const fstyle = steps && steps.length && !glLive ? `filter: url(#${fid})` : undefined;
  const mediaKey = pane.path && src ? pane.seq + ":" + src : "";
  return html`<div class="vid-pane">
    ${head}
    <${LookFilter} id=${fid} steps=${steps} />
    <div class="vid-screen">
      ${mediaKey ? html`<video key=${mediaKey} ref=${vref} src=${mediaUrl(src)} style=${fstyle}
          poster=${pane.poster ? mediaUrl(pane.poster) : undefined} preload="metadata" playsinline
          onPlay=${() => setPlaying(true)} onPause=${() => setPlaying(false)} onEnded=${onEnded}
          onTimeUpdate=${(e) => { if (!e.currentTarget.paused) setPos(e.currentTarget.currentTime); }} onError=${onError}
          onLoadedData=${onReady} onCanPlay=${onReady}></video>`
        : pane.poster ? html`<img src=${mediaUrl(pane.poster)} alt="" style=${fstyle} />` : null}
      ${look && look.offered && pane.path ? html`<${LookGL} media=${vref} mediaKey=${mediaKey} poster=${pane.poster}
        lut=${lut} onLive=${setGlLive} />` : null}
      ${overlay}
    </div>
    <div class="row vid-transport">
      <${Button} size="sm" icon=${playing ? "pause" : "play"} onClick=${toggle}
        disabled=${!!pane.path && !src && !pane.proxy_busy && !!facts && !!pane.proxy_err}>${playing ? "Pause" : "Play"}<//>
      <${Button} size="sm" kind="ghost" icon="stop" title="Stop" onClick=${stop} disabled=${!pane.path} />
      <input type="range" class="vid-seek" min="0" max=${dur || 0} step="0.01" value=${Math.min(pos, dur || 0)}
        disabled=${!src || !(dur > 0)} aria-label=${"Seek " + (pane.title || "")}
        onInput=${(e) => { const v = vref.current; const t = Number(e.target.value); setPos(t); if (v) v.currentTime = t; }} />
      <span class="mono small muted nw">${clock(pos, pane.path ? dur : 0)}</span>
    </div>
    ${look && look.offered && pane.path ? html`<${PaneView} side=${side} view=${(look.views || {})[side]} look=${look} />` : null}
  </div>`;
}

// ----------------------------------------------------------------- Compare
// PAD-440 (DragonRR): up to four clips side by side, big, beside the Color profiles bar.
// Each player draws through its own clip's colour steps (video.py _cmp_steps), so a
// profile picked or a slider moved shows on the clip clicked, against the others, as it
// is made.  The clip clicked is the one the bar changes and the one heard.
const cmpPlayers = new Map();          // tile id -> <video>
const LOOP_KEY = "pad.video.compare.loop";
const loopAtStart = () => { try { return localStorage.getItem(LOOP_KEY) !== "0"; } catch (e) { return true; } };

// PAD-448: a game's own clip says so under its player: locked, or (Advanced) its palette,
// so its color profile is attached from here as from the list
function CmpColor({ t, row, cs }) {
  if (!row || (row.col == null && !row.col_lock)) return null;
  if (row.col_lock) return html`<div class="row vcm-color">
    <span class="vid-color locked" ...${tip(colorTip(row, cs))}><${Icon} name="lock" /></span>
    <span class="small ellip muted">The game's own clip, locked: tick Advanced to give it a color profile.</span>
  </div>`;
  if (t.side !== "rep" && !row.col_stock) return html`<div class="row vcm-color"><span class="small muted">The original, as it is now.</span></div>`;
  const line = profileLine(row, cs);
  return html`<div class="row vcm-color">
    <button type="button" class=${cx("vid-color", row.col ? "on" : "off", row.col_own && "own")}
      aria-pressed=${row.col ? "true" : "false"} aria-label="Attach or detach this clip's color profile" ...${tip(colorTip(row, cs))}
      onClick=${(e) => { e.stopPropagation(); call("video.set_color", row.rel, !row.col); }}><${Icon} name="palette" /></button>
    <span class="small ellip">${!row.col ? "No color profile attached"
      : t.side !== "rep" ? "The original, as it is now."
      : html`Color profile: <span class="vcm-cp">${line ? line.profile : ""}</span>`}</span>
  </div>`;
}

// PAD-448 (DragonRR): a clear mark on each clip in Compare that is the game's own, locked or not
function CmpBadge({ row, cs }) {
  if (!row) return null;
  if (row.col_lock) return html`<span class="vcm-badge locked" ...${tip(colorTip(row, cs))}><${Icon} name="lock" />Locked</span>`;
  if (row.col_stock) return html`<span class="vcm-badge unlocked" ...${tip(colorTip(row, cs))}><${Icon} name="unlock" />Game's own clip</span>`;
  return null;
}

function CmpTile({ t, row, cs, offered, active, onPick, stopSeq, loop, canRemove, onState }) {
  const vref = useRef(null);
  const [glLive, setGlLive] = useState(false);
  const pane = t.pane || {};
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [failed, setFailed] = useState(false);
  const asked = useRef(0);
  const facts = pane.facts;
  const dur = (facts && facts.dur) || 0;
  const direct = !!(pane.path && facts && enginePlays(facts) && !failed);
  const src = pane.proxy || (direct ? pane.path : null);

  useEffect(() => { setFailed(false); setPos(0); setPlaying(false); }, [pane.seq]);
  useEffect(() => {
    if (!pane.path || !facts || pane.proxy || pane.proxy_busy || pane.proxy_err || direct) return;
    if (asked.current === pane.seq) return;
    asked.current = pane.seq;
    call("video.compare_make_proxy", t.id, pane.seq, proxyFormat());
  }, [pane.seq, !!facts, direct, pane.proxy, pane.proxy_busy]);
  useEffect(() => {
    const v = vref.current;
    if (v) cmpPlayers.set(t.id, v);
    return () => { if (cmpPlayers.get(t.id) === v) cmpPlayers.delete(t.id); };
  });
  useEffect(() => { const v = vref.current; if (v && !v.paused) v.pause(); }, [stopSeq]);

  const toggle = (e) => {
    e.stopPropagation();
    onPick();
    const v = vref.current;
    if (!v || !src) return;
    if (v.paused) { const p = v.play(); if (p && p.catch) p.catch(() => {}); } else v.pause();
  };
  const seen = (on) => { setPlaying(on); onState(); };

  let overlay = null;
  if (!pane.path) overlay = html`<div class="hint">${pane.hint || "nothing to show"}</div>`;
  else if (pane.proxy_busy && !src) overlay = html`<div class="hint"><${Spinner} /><span>Preparing a preview copy…</span></div>`;
  else if (pane.proxy_err && !src) overlay = html`<div class="hint err-ink">${pane.proxy_err}</div>`;
  else if (!facts) overlay = html`<div class="hint">loading frame…</div>`;

  const steps = t.look || [];
  const fid = "vcm-look-" + t.id;
  const fstyle = steps.length && !glLive ? `filter: url(#${fid})` : undefined;
  const mediaKey = pane.path && src ? pane.seq + ":" + src : "";
  const sides = (t.sides || []).map(([value, label]) => ({ value, label }));
  const name = (row && row.name) || t.rel.split("/").pop();
  return html`<div class=${cx("vcm-tile", active && "on")}>
    <div class="row vcm-tilehd">
      <span class="mono small ellip vcm-name" ...${tip({ head: t.rel, lines: [pane.label ? `${pane.title}: ${pane.label}` : pane.title] })}>${name}</span>
      <span class="grow"></span>
      ${sides.length > 1 ? html`<${Seg} value=${t.side} options=${sides} onChange=${(v) => call("video.compare_side", t.id, v)} />`
        : html`<span class="small muted nw">${pane.title || "Original"}</span>`}
      <${Button} size="xs" kind="ghost" icon="x" title="Take this clip out of Compare" disabled=${!canRemove}
        onClick=${() => call("video.compare_remove", t.id)} />
    </div>
    <${LookFilter} id=${fid} steps=${steps} />
    <div class="vid-screen vcm-screen" role="button" tabindex="0" aria-pressed=${active ? "true" : "false"}
        aria-label=${"Pick " + name + " for the Color profiles bar"}
        onClick=${onPick} onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(); } }}
        ...${tip(active ? "The clip the Color profiles bar changes, and the one you hear." : "Click: the Color profiles bar changes this clip's colors, and it is the one you hear.")}>
      ${mediaKey ? html`<video key=${mediaKey} ref=${vref} src=${mediaUrl(src)} style=${fstyle}
          poster=${pane.poster ? mediaUrl(pane.poster) : undefined} preload="auto" playsinline loop=${loop} muted=${!active}
          onPlay=${() => seen(true)} onPause=${() => seen(false)} onEnded=${() => seen(false)}
          onTimeUpdate=${(e) => setPos(e.currentTarget.currentTime)} onSeeked=${(e) => setPos(e.currentTarget.currentTime)}
          onError=${() => { if (!pane.proxy && src) { setFailed(true); asked.current = 0; } }}></video>`
        : pane.poster ? html`<img src=${mediaUrl(pane.poster)} alt="" style=${fstyle} />` : null}
      ${offered && pane.path ? html`<${LookGL} media=${vref} mediaKey=${mediaKey} poster=${pane.poster}
        lut=${t.lut || null} onLive=${setGlLive} />` : null}
      <${CmpBadge} row=${row} cs=${cs} />
      ${overlay}
    </div>
    <div class="row vid-transport">
      <${Button} size="sm" icon=${playing ? "pause" : "play"} onClick=${toggle} disabled=${!src}>${playing ? "Pause" : "Play"}<//>
      <input type="range" class="vid-seek" min="0" max=${dur || 0} step="0.01" value=${Math.min(pos, dur || 0)}
        disabled=${!src || !(dur > 0)} aria-label=${"Seek " + name}
        onInput=${(e) => { const v = vref.current; const x = Number(e.target.value); setPos(x); if (v) v.currentTime = x; }} />
      <span class="mono small muted nw">${clock(pos, pane.path ? dur : 0)}</span>
    </div>
    <${CmpColor} t=${t} row=${row} cs=${cs} />
  </div>`;
}

function CompareView({ cmp, byRel, cs, look, active, setActive, stopSeq, onOpenColors, colorOffered, colorStock }) {
  const tiles = cmp.tiles || [];
  const [loop, setLoopState] = useState(loopAtStart);
  const [anyPlaying, setAnyPlaying] = useState(false);
  const ref = useRef(null);
  const setLoop = (v) => { setLoopState(v); try { localStorage.setItem(LOOP_KEY, v ? "1" : "0"); } catch (e) { /* kept for this page */ } };
  const onState = () => setAnyPlaying([...cmpPlayers.values()].some((v) => v && !v.paused && !v.ended));
  useEffect(() => { if (ref.current) ref.current.focus({ preventScroll: true }); }, []);
  useEffect(() => () => { for (const v of cmpPlayers.values()) if (v && !v.paused) v.pause(); }, []);
  const each = (fn) => { for (const t of tiles) { const v = cmpPlayers.get(t.id); if (v) fn(v); } };
  const play = (v) => { const p = v.play(); if (p && p.catch) p.catch(() => {}); };
  const playAll = () => (anyPlaying ? each((v) => v.pause()) : each(play));
  // every clip from its first frame at once, so they keep in step
  const fromStart = () => each((v) => { v.currentTime = 0; play(v); });
  const close = () => call("video.compare_close");
  const onKey = (e) => { if (e.key === "Escape" && !menuOpen()) { e.stopPropagation(); close(); } };
  const n = tiles.length;
  return html`<div class="page fill vid-page vcm-page" ref=${ref} tabindex="-1" onKeyDown=${onKey}>
    <section class="card vcm" aria-label="Compare clips">
      <div class="vcm-hd">
        <div class="row vcm-hdrow">
          <${Icon} name="compare" cls="lg" />
          <span class="h2">Compare</span>
          <span class="grow"></span>
          <${Button} icon=${anyPlaying ? "pause" : "play"} onClick=${playAll}>${anyPlaying ? "Pause all" : "Play all"}<//>
          <${Button} icon="refresh" onClick=${fromStart} title="Play every clip from its first frame at once, so they keep in step">From the start<//>
          <${Check} checked=${loop} label="Loop" cls="small" title="Play each clip over and over" onChange=${setLoop} />
          ${colorOffered ? html`<span class="vcm-adv" ...${tip(ADV_TIP)}><${Check} checked=${colorStock} label="Advanced" cls="small"
            onChange=${(v) => call("video.set_color_stock", v)} /></span>` : null}
          <${Button} kind="ghost" icon="x" onClick=${close} title="Back to the list (Esc)">Close<//>
        </div>
        <div class="small muted">${look.offered
          ? "Click a clip: the Color profiles bar changes its colors while you watch the others. It is the one you hear."
          : "Click a clip to hear it."}</div>
      </div>
      ${look.offered ? html`<div class="vcm-look"><${LookRow} look=${look} ns="video" onOpen=${onOpenColors} /></div>` : null}
      <div class=${cx("vcm-grid", "n" + Math.min(n, 4))}>
        ${tiles.map((t) => html`<${CmpTile} key=${t.id} t=${t} row=${byRel.get(t.rel)} cs=${cs} offered=${!!look.offered} active=${t.id === active}
          onPick=${() => setActive(t.id)} stopSeq=${stopSeq} loop=${loop} canRemove=${n > 1} onState=${onState} />`)}
      </div>
    </section>
  </div>`;
}

// ----------------------------------------------------------------- dialogs
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

function SpecDialog({ spec, onClose }) {
  const copy = async () => { if (await copyText(spec.cmd)) call("video.copied_command", spec.rel); };
  return html`<${Modal} title="What this slot needs" icon="info" wide onClose=${onClose}
    footer=${html`${spec.cmd ? html`<${Button} icon="copy" onClick=${copy}>Copy command<//>` : null}<span class="grow"></span>
      <${Button} kind="primary" onClick=${onClose}>Close<//>`}>
    <div class="stack" style="gap:10px">
      <div class="mono" style="font-weight:600">${spec.rel}</div>
      <p class="msg" style="margin:0">${T.specIntro}</p>
      <div class="kv">${(spec.spec || []).map(([k, v]) => html`<span class="k">${k}:</span><span>${v}</span>`)}</div>
      ${spec.cmd ? html`<p style="margin:6px 0 0">${T.specCmd}</p>
        <textarea class="area mono vid-cmd" readonly rows="3" value=${spec.cmd}
          onFocus=${(e) => e.target.select()}></textarea>
        ${spec.silent ? html`<div class="small muted">${T.specAn}</div>` : null}` : null}
    </div>
  <//>`;
}

// The report is a window of its own over the tab, not a modal: the tab stays
// usable while a check runs, a click elsewhere never closes it, and only
// Close, its × and Escape do (Tk: a non-modal transient Toplevel).  Drag it
// by its title bar.
function QualityWindow({ q }) {
  const card = useRef(q.card || "");
  useEffect(() => { card.current = q.card || ""; }, [q.card]);
  const ref = useRef(null);
  const [off, setOff] = useState({ x: 0, y: 0 });
  useEffect(() => { if (ref.current) ref.current.focus({ preventScroll: true }); }, []);
  const startDrag = (e) => {
    if (e.button !== 0 || e.target.closest("button")) return;
    e.preventDefault();
    const z = zoomOf();
    const x0 = e.clientX, y0 = e.clientY, o0 = off;
    const lim = (v, m) => Math.max(-m, Math.min(m, v));
    const move = (ev) => {
      // keep the title bar on screen
      const mx = Math.max(0, (window.innerWidth / z) / 2 - 80), my = Math.max(0, (window.innerHeight / z) / 2 - 40);
      setOff({ x: lim(o0.x + (ev.clientX - x0) / z, mx), y: lim(o0.y + (ev.clientY - y0) / z, my) });
    };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  const onKey = (e) => { if (e.key === "Escape" && !menuOpen()) { e.stopPropagation(); close(); } };
  const rows = q.rows || [];
  const cols = [
    { key: "name", label: "Clip", width: "minmax(0,1fr)" },
    { key: "len", label: "Length", width: "80px" },
    { key: "res", label: "Resolution", width: "100px" },
    { key: "rate", label: "Bitrate", width: "100px" },
    { key: "quality", label: "Quality", width: "190px" },
  ];
  const copy = async () => {
    const text = await call("video.quality_report_text");
    if (text && await copyText(text)) call("video.quality_copied");
  };
  function close() { call("video.quality_close"); }
  return html`<div class="modal wide vid-qwin" ref=${ref} role="dialog" aria-modal="false"
      aria-label="Check the videos on a card" tabindex="-1" onKeyDown=${onKey}
      style=${`transform:translate(calc(-50% + ${off.x}px), calc(-50% + ${off.y}px))`}>
    <div class="hd vid-qwin-hd" onMouseDown=${startDrag}><${Icon} name="film" cls="lg" /><span class="h2">Check the videos on a card</span>
      <${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${close} /></div>
    <div class="bd">
      <div><div class="h2">${T.qTitle}</div><p class="muted small" style="margin:4px 0 0">${T.qIntro}</p></div>
      <div class="row" style="gap:8px">
        <label class="lbl nw" for="vid-q-card">Card image:</label>
        <${Field} id="vid-q-card" value=${q.card} mono cls="grow" disabled=${q.busy}
          onChange=${(v) => { card.current = v; }} onCommit=${(v) => call("video.quality_set_card", v)} />
        <${Button} onClick=${() => call("video.quality_browse")} disabled=${q.busy}>Browse…<//>
        <${Button} kind="primary" onClick=${() => call("video.quality_check", card.current)}>${q.busy ? "Stop" : "Check"}<//>
      </div>
      <div class="row small" style="gap:8px">${q.busy ? html`<${Spinner} />` : null}<span>${q.summary}</span></div>
      <${Table} cls="vid-qtbl" columns=${cols} rows=${rows} rowKey=${(r, i) => i}
        rowClass=${(r) => (r.verdict === "blocky" ? "bad" : r.verdict === "unknown" ? "muted" : "")}
        empty=${html`<div class="small muted" style="padding:14px">${q.busy ? "" : "No clips listed yet."}</div>`} />
    </div>
    <div class="ft">
      <${Check} checked=${q.only_bad} label="Show only the clips below the bar"
        onChange=${(v) => call("video.quality_only_bad", v)} />
      <span class="grow"></span>
      <${Button} onClick=${close}>Close<//>
      <${Button} icon="copy" onClick=${copy} disabled=${!q.can_copy}>Copy report<//>
    </div>
  </div>`;
}

// "Best quality…": the option, and finding the files a built card's clips
// were made from (webui/video_best.py).  A window over the tab like the
// quality report: a search can run for minutes and the tab stays usable.
function BestWindow({ b }) {
  const ref = useRef(null);
  // what is typed in each field, sent when Find is pressed; each follows the
  // store only when ITS value changes there (one field's commit must not
  // put the others back to what they were)
  const fields = useRef({ card: b.card || "", stock: b.stock || "", folder: b.folder || "" });
  useEffect(() => { fields.current.card = b.card || ""; }, [b.card]);
  useEffect(() => { fields.current.stock = b.stock || ""; }, [b.stock]);
  useEffect(() => { fields.current.folder = b.folder || ""; }, [b.folder]);
  const [off, setOff] = useState({ x: 0, y: 0 });
  useEffect(() => { if (ref.current) ref.current.focus({ preventScroll: true }); }, []);
  const startDrag = (e) => {
    if (e.button !== 0 || e.target.closest("button")) return;
    e.preventDefault();
    const z = zoomOf();
    const x0 = e.clientX, y0 = e.clientY, o0 = off;
    const lim = (v, m) => Math.max(-m, Math.min(m, v));
    const move = (ev) => {
      const mx = Math.max(0, (window.innerWidth / z) / 2 - 80), my = Math.max(0, (window.innerHeight / z) / 2 - 40);
      setOff({ x: lim(o0.x + (ev.clientX - x0) / z, mx), y: lim(o0.y + (ev.clientY - y0) / z, my) });
    };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  function close() { call("video.best_close"); }
  const onKey = (e) => { if (e.key === "Escape" && !menuOpen()) { e.stopPropagation(); close(); } };
  const rows = b.rows || [];
  const cols = [
    { key: "use", label: "", width: "34px",
      render: (r) => (r.path ? html`<input type="checkbox" checked=${!!r.use} aria-label=${"Use the file found for " + r.name}
        onClick=${(e) => e.stopPropagation()} onChange=${(e) => call("video.best_use_row", r.rel, e.target.checked)} />` : null) },
    { key: "name", label: "Clip", width: "minmax(0,1fr)" },
    { key: "file", label: "Your file", width: "minmax(0,1.2fr)", titleOf: (r) => r.path || undefined,
      render: (r) => (r.path ? r.file : html`<span class="muted">not found</span>`) },
    { key: "match", label: "Match", width: "70px" },
    { key: "res", label: "Resolution", width: "96px" },
    { key: "rate", label: "Bitrate", width: "86px" },
    { key: "note", label: "", width: "minmax(0,.9fr)", titleOf: (r) => r.note || undefined,
      render: (r) => html`<span class="small muted">${r.note}</span>` },
  ];
  const field = (id, k, label) => html`<div class="row" style="gap:8px">
    <label class="lbl nw vid-blbl" for=${id}>${label}</label>
    <${Field} id=${id} value=${b[k]} mono cls="grow" disabled=${b.busy}
      onChange=${(v) => { fields.current[k] = v; }} onCommit=${(v) => call("video.best_set", k, v)} />
    <${Button} onClick=${() => call("video.best_browse", k)} disabled=${b.busy}>Browse…<//>
  </div>`;
  // a typed path counts even if the field never lost focus
  const find = async () => {
    if (!b.busy) {
      const f = { ...fields.current };
      await call("video.best_set", "card", f.card);
      await call("video.best_set", "stock", f.stock);
      await call("video.best_set", "folder", f.folder);
    }
    call("video.best_find");
  };
  return html`<div class="modal wide vid-qwin vid-bwin" ref=${ref} role="dialog" aria-modal="false"
      aria-label="Best quality" tabindex="-1" onKeyDown=${onKey}
      style=${`transform:translate(calc(-50% + ${off.x}px), calc(-50% + ${off.y}px))`}>
    <div class="hd vid-qwin-hd" onMouseDown=${startDrag}><${Icon} name="film" cls="lg" /><span class="h2">Best quality from your own files</span>
      <${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${close} /></div>
    <div class="bd">
      <p class="muted small" style="margin:0">${b.intro}</p>
      <div class="row" style="gap:12px">
        <${Check} checked=${b.on} label="Convert replacements at best quality" onChange=${(v) => call("video.set_best_quality", v)} />
        <span class="small muted grow">${b.summary}</span>
      </div>
      <div class="vid-bfind">
        <div class="eyebrow">Find your source files</div>
        <p class="muted small" style="margin:2px 0 6px">${b.find_intro}</p>
        ${field("vid-b-card", "card", "Built card:")}
        ${field("vid-b-stock", "stock", "Stock card:")}
        <div class="row" style="gap:8px">
          <label class="lbl nw vid-blbl" for="vid-b-folder">Your videos:</label>
          <${Field} id="vid-b-folder" value=${b.folder} mono cls="grow" disabled=${b.busy}
            onChange=${(v) => { fields.current.folder = v; }} onCommit=${(v) => call("video.best_set", "folder", v)} />
          <${Button} onClick=${() => call("video.best_browse", "folder")} disabled=${b.busy}>Browse…<//>
          <${Button} onClick=${find}>${b.busy ? "Stop" : "Find"}<//>
        </div>
      </div>
      <div class="row small" style="gap:8px">${b.busy ? html`<${Spinner} />` : null}<span>${b.status}</span></div>
      <${Table} cls="vid-qtbl vid-btbl" columns=${cols} rows=${rows} rowKey=${(r) => r.rel}
        rowClass=${(r) => (!r.path ? "muted" : !r.sure ? "warn" : "")}
        onActivate=${(r) => r.path && call("video.best_reveal", r.rel)}
        empty=${html`<div class="small muted" style="padding:14px">${b.busy ? "" : "Nothing searched yet."}</div>`} />
    </div>
    <div class="ft">
      ${rows.length ? html`<${Button} kind="ghost" size="sm" onClick=${() => call("video.best_use_all", true)} disabled=${b.busy}>Tick all<//>
        <${Button} kind="ghost" size="sm" onClick=${() => call("video.best_use_all", false)} disabled=${b.busy}>Untick all<//>` : null}
      <span class="grow"></span>
      <${Button} onClick=${close}>Close<//>
      <${Button} kind="primary" onClick=${() => call("video.best_apply")} disabled=${b.busy}
        title="Turn best quality on, and use every ticked file as its clip's replacement.">${b.can_apply ? "Use these files at best quality" : "Use best quality"}<//>
    </div>
  </div>`;
}

// -------------------------------------------------------------------- tab
export default function VideoTab() {
  const s = useNs("video");
  const shell = useNs("shell");
  const running = !!shell.running;
  const allRows = s.rows || [];
  const view = s.view || [];
  const rows = useMemo(() => view.map((i) => allRows[i]).filter(Boolean), [s.rows, s.view]);
  const pv = s.preview || {};
  const look = s.look || {};
  const orig = pv.orig || {};
  const rep = pv.rep || {};
  const q = s.quality || {};
  const best = s.best || {};
  const undo = s.undo || {};
  const [sel, setSel] = useState(() => new Set());
  const anchor = useRef(null);
  const selectJob = useRef(null);
  const [spec, setSpec] = useState(null);
  const cardRef = useRef(null);
  // PAD-364 (DragonRR): the Color profiles bar on the right edge, as on the Scenes tab,
  // so a profile is picked from the Saved profiles list with each clip's Color switch in
  // view; the players draw through it.  It opens on Files the first time: the profile
  // that column attaches.  A name under Preview colors opens the bar on that profile.
  const colorNs = useNs("color");
  const cmp = s.compare || {};
  const cmpOpen = !!cmp.open;
  const byRel = useMemo(() => new Map(allRows.map((r) => [r.rel, r])), [s.rows]);
  const [cmpActive, setCmpActive] = useState(null);
  const cmpTiles = cmp.tiles || [];
  const activeTile = cmpTiles.find((t) => t.id === cmpActive) || cmpTiles[0] || null;
  const [colors, setColorsState] = useState(() => barOpenAtStart("video"));
  const setColors = (v) => { setColorsState(v); rememberBarOpen(v, "video"); };
  const openColors = async (mode) => { await call("color.set_mode", mode); setColors(true); };
  // the first highlighted row in list order (Tk: tree.selection()[0])
  const firstOf = (set) => { const f = rows.find((x) => set.has(x.rel)); return f ? f.rel : null; };
  const firstSel = useMemo(() => firstOf(sel), [rows, sel]);
  // PAD-368: the clip clicked, whose own profile the Color profiles bar shows (PAD-440: in
  // Compare, the clip clicked there)
  const selRow = cmpOpen ? (activeTile ? byRel.get(activeTile.rel) : null)
    : firstSel ? rows.find((x) => x.rel === firstSel) : null;
  const colorFile = selRow && selRow.col != null
    ? { kind: "videos", rel: selRow.rel, label: selRow.name, on: !!selRow.col, attach: { ns: "video" } } : null;

  const loadRow = (rel, delay = 200) => {
    clearTimeout(selectJob.current);
    if (!rel) return;
    selectJob.current = setTimeout(() => call("video.select", rel, playingSide()), delay);
  };
  // Python (re)selects rows: after a scan, a pick, a clear.  As Tk's
  // selection_set did (through <<TreeviewSelect>>), the first of them is
  // the row the panes show.
  useEffect(() => {
    const r = (s.select && s.select.rels) || [];
    if (!s.select || !s.select.seq) return;
    const next = new Set(r);
    setSel(next);
    const first = firstOf(next);
    anchor.current = first || r[0] || null;
    if (first) loadRow(first);
  }, [s.select && s.select.seq]);
  useEffect(() => () => { clearTimeout(selectJob.current); pauseAll(); }, []);
  // PAD-453: Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z anywhere on the tab undo or redo a change to the
  // picks.  A text box keeps its own undo, the Colors bar its profile's, and a dialog or
  // another tab is left alone.
  const shellRef = useRef(null);
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const k = (e.key || "").toLowerCase();
      const redo = k === "y" || (k === "z" && e.shiftKey);
      if (k !== "z" && !redo) return;
      const el = e.target;
      if (el && (el.isContentEditable || el.tagName === "TEXTAREA" || el.tagName === "SELECT"
          || (el.tagName === "INPUT" && !/^(range|checkbox|radio|button)$/.test(el.type)))) return;
      if (el && el.closest && el.closest(".cpd")) return;
      const box = shellRef.current;
      if (!box || !box.getClientRects().length || document.querySelector(".scrim")) return;
      e.preventDefault();
      call("video.undo", redo);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onSelect = (r, i, e) => {
    if (!r) return;
    const rel = r.rel;
    let next = null;
    if (e && (e.ctrlKey || e.metaKey)) {
      next = new Set(sel);
      if (next.has(rel)) next.delete(rel); else next.add(rel);
      anchor.current = rel;
    } else if (e && e.shiftKey && anchor.current) {
      const a = rows.findIndex((x) => x.rel === anchor.current);
      const b = rows.findIndex((x) => x.rel === rel);
      if (a >= 0 && b >= 0) {
        const [lo, hi] = a < b ? [a, b] : [b, a];
        next = new Set(rows.slice(lo, hi + 1).map((x) => x.rel));
      }
    }
    if (!next) { next = new Set([rel]); anchor.current = rel; }
    setSel(next);
    // every selection change previews the first selected row (Tk's 250 ms
    // job); the row already on show is left playing
    loadRow(firstOf(next));
  };
  // Python loads the row into the panes before the picker opens
  const choose = (rel) => { clearTimeout(selectJob.current); pauseAll(); call("video.choose", rel); };
  const playRow = (rel, side = "orig") => {
    setSel(new Set([rel])); anchor.current = rel;
    clearTimeout(selectJob.current);
    call("video.play", rel, side);
  };
  // the row the panes' buttons act on: the highlighted one, as Tk's did
  const currentRel = firstSel || pv.rel || null;
  // PAD-440: the selected rows, in list order, side by side; the Colors bar opens beside them
  const openCompare = async (rels) => {
    clearTimeout(selectJob.current);
    pauseAll();
    const n = await call("video.compare_open", rels);
    if (!n) return;
    setCmpActive(null);
    if (look.offered && colorNs.has_project && !colors) setColors(true);
  };
  const compareRels = () => {
    const picked = rows.filter((x) => sel.has(x.rel)).map((x) => x.rel);
    return picked.length ? picked : currentRel ? [currentRel] : [];
  };

  const onContext = async (r, i, e) => {
    let rels;
    if (sel.has(r.rel) && sel.size >= 2) rels = rows.filter((x) => sel.has(x.rel)).map((x) => x.rel);
    else {
      // Tk _right_click_selection: outside a multi-row selection the click
      // selects just that row, and the panes follow it
      setSel(new Set([r.rel])); anchor.current = r.rel; rels = [r.rel];
      loadRow(r.rel);
    }
    const at = { x: e.clientX, y: e.clientY };
    const info = await call("video.row_menu", rels);
    if (!info) return;
    if (info.multi) {
      openMenu(at, [
        { label: `${info.rows} slot${info.rows === 1 ? "" : "s"} selected`, disabled: true },
        { sep: true },
        { label: `Compare ${Math.min(info.rows, cmp.max || 4)} clips side by side`, onClick: () => openCompare(rels) },
        { sep: true },
        info.targets
          ? { label: `Clear ${info.targets} replacement${info.targets === 1 ? "" : "s"} in this selection`, onClick: () => call("video.clear", rels) }
          : { label: "No replacements in this selection", disabled: true },
      ]);
      return;
    }
    const rel = info.rel;
    openMenu(at, [
      { label: "▶  Play original", onClick: () => playRow(rel, "orig") },
      { label: "Choose replacement…", onClick: () => choose(rel) },
      info.has_pick && { label: "▶  Play replacement", onClick: () => playRow(rel, "rep") },
      { label: "Compare side by side", onClick: () => openCompare([rel]) },
      info.can_clear && { sep: true },
      info.can_clear && { label: "Clear replacement", onClick: () => call("video.clear", [rel]) },
      info.stern && info.scenes && { sep: true },
      info.stern && info.scenes && { label: "Show scene contents…", onClick: () => call("video.scene_contents", rel) },
      info.back && { sep: true },
      info.back && { label: `Use the same clip as ${info.back} again…`, onClick: () => call("video.shared_again", rel) },
      { sep: true },
      { label: "This clip's conversion", submenu: [
        { label: `Follow the box below (${info.follow})`, checked: info.asis === "box", onClick: () => call("video.set_asis", rel, null) },
        { label: "Always use my file as-is", checked: info.asis === "asis", onClick: () => call("video.set_asis", rel, true) },
        { label: "Always convert this clip", checked: info.asis === "convert", onClick: () => call("video.set_asis", rel, false) },
      ] },
      info.color && { label: "This clip's colors", submenu: [
        { label: `Follow the Color profile tab's box (${info.color_follow})`, checked: info.color === "box", onClick: () => call("video.set_color", rel, null) },
        { label: "Attach the color profile", checked: info.color === "on", onClick: () => call("video.set_color", rel, true) },
        { label: "No color profile attached", checked: info.color === "off", onClick: () => call("video.set_color", rel, false) },
      ] },
      // PAD-446: more clips for this slot, one of them played at random each time
      info.variants && { label: info.variants.n ? `Random clips (${info.variants.n + 1} in turn)` : "Random clips", submenu: info.variants.why
        ? [{ label: "Why not this clip?", onClick: () => call("video.variants_why", rel) },
           ...info.variants.files.map((f) => ({ label: `Take off ${f.name}`, onClick: () => call("video.remove_variant", rel, f.i) }))]
        : [
          { label: info.variants.n ? "Add more clips to play at random…" : "Add clips to play at random…",
            disabled: info.variants.n >= info.variants.max, onClick: () => call("video.add_variants", rel) },
          ...(info.variants.n ? [{ sep: true }] : []),
          ...info.variants.files.map((f) => ({ label: `Take off ${f.name}`, onClick: () => call("video.remove_variant", rel, f.i) })),
          ...(info.variants.n > 1 ? [{ label: "Take them all off", onClick: () => call("video.clear_variants", rel) }] : []),
        ] },
      { label: "This clip's length", submenu: [
        { label: `Follow the Trim / pad box (${info.length_follow})`, checked: info.length === "box", onClick: () => call("video.set_length", rel, null) },
        { label: "Match the stock clip", checked: info.length === "stock", onClick: () => call("video.set_length", rel, "stock") },
        { label: "Keep my file's full length", checked: info.length === "full", onClick: () => call("video.set_length", rel, "full") },
        { label: info.length === "custom" ? `Set a length… (${info.length_secs} s)` : "Set a length…", checked: info.length === "custom", onClick: () => call("video.set_length", rel, "custom") },
      ] },
      { sep: true },
      { label: "What this slot needs…", onClick: async () => { const d = await call("video.target_spec", rel); if (d) setSpec(d); } },
      { label: "Open in default app", onClick: () => call("video.open_default", rel, "orig") },
      info.open_rep && { label: "Open replacement in default app", onClick: () => call("video.open_default", rel, "rep") },
      { label: info.reveal, onClick: () => call("video.reveal", rel) },
      info.partition && { label: "Find in Partition Explorer", onClick: () => call("video.find_in_partition", rel) },
    ]);
  };

  // ---- column widths: the dragged ones are kept (settings.json), the
  // others fit their content (MainWindow._persist_tree_columns +
  // _autosize_tree_columns)
  const savedKey = JSON.stringify(s.widths || {});
  const [tuned, setTuned] = useState(() => ({ ...(s.widths || {}) }));
  useEffect(() => { setTuned({ ...(s.widths || {}) }); }, [savedKey]);
  const [fontTick, setFontTick] = useState(0);
  useEffect(() => {
    const fs = document.fonts;
    if (!fs) return undefined;
    const again = () => { textCache.clear(); rowFits = new WeakMap(); setFontTick((n) => n + 1); };
    if (fs.ready) fs.ready.then(again);
    if (fs.addEventListener) fs.addEventListener("loadingdone", again);
    return () => { if (fs.removeEventListener) fs.removeEventListener("loadingdone", again); };
  }, []);
  const fit = useMemo(() => fitColumns(allRows), [s.rows, fontTick]);
  const flexLeft = FLEX.some((k) => !tuned[k]);
  const width = (k) => (FLEX.includes(k) ? `minmax(${COL_MIN[k]}px,${fit[k]}fr)` : `${fit[k]}px`);
  // the last column never takes a drag; it only stretches once every
  // stretching column is one the user sized (Tk _pin_tree_columns)
  const convWidth = flexLeft ? `calc(${fit.conv}px)` : `minmax(${fit.conv}px,1fr)`;
  const colorCol = allRows.some((r) => r.col != null || r.col_lock);
  // PAD-444: Played in, once the card's program has been read and names a mode
  const md = s.modes || {};
  const modesCol = !!(md.ready && (md.list || []).length);
  const minWidth = 30 + ["rel", "len", "res", "fmt", "aud", "rep"].concat(modesCol ? ["modes"] : []).reduce((a, k) =>
    a + (tuned[k] ? Math.max(36, tuned[k]) : FLEX.includes(k) ? COL_MIN[k] : fit[k]), 0) + fit.conv
    + (colorCol ? fit.col + 10 : 0) + (modesCol ? 8 : 7) * 10 + 20;
  const dragFrom = useRef(null);
  const onGripDown = (e) => {
    const t = e.target;
    if (!t || !t.classList || !t.classList.contains("col-grip")) return;
    const hdr = t.closest(".th");
    if (!hdr) return;
    const m = {};
    [...hdr.children].forEach((c, n) => { if (columns[n]) m[columns[n].key] = Math.round(c.getBoundingClientRect().width); });
    dragFrom.current = m;
  };
  const onResize = (out) => {
    // save only the column the drag changed (Tk _save_tree_columns); the
    // table measures on-screen pixels, the page lays out in zoom-free ones
    const before = dragFrom.current || {};
    dragFrom.current = null;
    const z = zoomOf();
    const changed = {};
    for (const k in out) {
      if (k === "play" || before[k] == null || Math.abs(out[k] - before[k]) < 1) continue;
      changed[k] = Math.max(COL_MIN[k] || 36, Math.round(out[k] / z));
    }
    if (!Object.keys(changed).length) return;
    setTuned((t) => ({ ...t, ...changed }));
    call("video.save_widths", changed);
  };

  const columns = [
    { key: "play", label: "", width: "30px", cls: "playc",
      render: (r) => html`<button type="button" class="btn sm ghost vid-rowplay" aria-label=${"Play " + r.rel}
        onClick=${(e) => { e.stopPropagation(); playRow(r.rel, "orig"); }}><${Icon} name="play" /></button>` },
    { key: "rel", label: "Original Video", width: width("rel"), sort: "#0",
      render: (r) => html`<span class=${cx("vid-name", (r.follow || r.copy) && "vid-pairrow")} ...${tip({ head: r.rel, lines: [profileLine(r, colorNs)] })}>${r.follow || r.copy
        ? html`<span class="vid-pairmark" aria-hidden="true">↳</span>` : null}${r.dir
        ? html`<span class="mono muted">${r.dir}</span>` : null}${r.name}</span>` },
    { key: "len", label: "Length", width: width("len"), num: true, sort: "len" },
    { key: "res", label: "Resolution", width: width("res"), sort: "res" },
    { key: "fmt", label: "Format", width: width("fmt"), sort: "fmt", titleOf: (r) => r.fmt,
      render: (r) => html`<span class=${r.fmt_bad ? "err-ink" : "dim"}>${r.fmt}</span>` },
    { key: "aud", label: "Audio", width: width("aud"), sort: "aud", render: (r) => html`<span class="dim">${r.aud}</span>` },
    // PAD-369 (DragonRR): the chosen file's name tells its color profile too
    { key: "rep", label: "Replacement", width: width("rep"), sort: "rep",
      render: (r) => html`<span class="vid-repcell"><button type="button" class=${cx("vid-rep", r.rep_cls || "muted")}
        ...${tip(r.rep_cls && profileLine(r, colorNs) ? { head: r.rep, lines: [profileLine(r, colorNs)] } : r.rep)}
        onClick=${(e) => { e.stopPropagation(); setSel(new Set([r.rel])); anchor.current = r.rel; choose(r.rel); }}>${r.rep}</button>${r.var
        ? html`<span class="vid-var" aria-label=${`${r.var} more clips play at random`} ...${tip({ head: "Random clips", lines: [r.var_tip] })}><${Icon} name="shuffle" />+${r.var}</span>`
        : null}</span>` },
    modesCol && { key: "modes", label: "Played in", width: width("modes"), title: T.modes,
      render: (r) => (r.unplayed
        ? html`<span class="vid-modes-cell unplayed" ...${tip({ head: "Not played", lines: [
            "Nothing in the game's program asks for this clip, so the machine never shows it."] })}>${modesText(r)}</span>`
        : (r.modes || []).length || r.other
          ? html`<span class=${cx("vid-modes-cell", r.pair && "pair", r.other && "other")} ...${tip(r.follow
            ? { head: r.modes[0], lines: ["Plays the same clip as " + r.follow + " until you choose a replacement in this row."] }
            : r.copy ? { head: r.modes[0], lines: ["Plays a clip of its own: a new clip on the card after the next image build."] }
            : r.pair ? { head: r.modes[0], lines: ["Another mode plays this clip too: it has its own row below."] }
            : modesText(r))}>${modesText(r)}</span>`
          : "") },
    colorCol && { key: "col", label: "Color", width: width("col"), cls: "vid-colorcell", title: COLOR_TIP,
      render: (r) => (r.col_lock
        ? html`<span class="vid-color locked" aria-label="The game's own clip: no color profile can be attached" ...${tip(colorTip(r, colorNs))}><${Icon} name="lock" /></span>`
        : r.col == null ? "" : html`<button type="button" class=${cx("vid-color", r.col ? "on" : "off", r.col_own && "own")}
        aria-label=${r.col_stock ? "Correct the game's own clip's colors for the machine" : "Correct this clip's colors for the machine"} aria-pressed=${r.col ? "true" : "false"} ...${tip(colorTip(r, colorNs))}
        onClick=${(e) => { e.stopPropagation(); if (e.detail > 1) { e.preventDefault(); return; } call("video.set_color", r.rel, !r.col); }}>
        <${Icon} name="palette" /></button>`) },
    { key: "conv", label: "Convert", width: convWidth, sort: "conv", titleOf: (r) => r.conv,
      render: (r) => html`<span class=${r.conv_cls === "bad" ? "err-ink" : r.conv_cls === "stray" ? "warn-ink" : ""}>${r.conv}</span>` },
  ].filter(Boolean);
  const selected = sel.size === 1 ? [...sel][0] : sel;
  const emptyNode = s.scanning
    ? html`<${Empty} icon="film" title=${html`<span class="row" style="gap:10px;justify-content:center"><${Spinner} />${s.empty || "Scanning for video files…"}</span>`} />`
    : s.empty ? html`<${Empty} icon="film">${s.empty}<//>` : null;

  // The table gives up height when the WRONG FORMAT callout (or anything
  // else) takes some: a selected row that was in view stays in view.
  const keepRel = useRef(null);
  keepRel.current = firstSel;
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  useEffect(() => {
    const el = cardRef.current && cardRef.current.querySelector(".vid-tbl .scroller");
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    let prevH = el.clientHeight;
    const ro = new ResizeObserver(() => {
      const h = el.clientHeight, oldH = prevH;
      prevH = h;
      if (h >= oldH || !keepRel.current) return;
      const idx = rowsRef.current.findIndex((x) => x.rel === keepRel.current);
      if (idx < 0) return;
      const head = el.querySelector(".th");
      const hh = head ? head.offsetHeight : 0;
      const y = idx * ROW_H, st = el.scrollTop;
      const wasIn = y >= st && hh + y + ROW_H <= st + oldH + 1;
      if (wasIn && hh + y + ROW_H > st + h) el.scrollTop = hh + y + ROW_H - h;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [cmpOpen]);

  // PAD-369: the replacement's name over its player tells its color profile too
  const curRow = currentRel ? rows.find((x) => x.rel === currentRel) : null;
  const repLine = curRow ? profileLine(curRow, colorNs) : null;
  // PAD-454: a game's own clip turned to Original on this player says so
  const repView = look.offered && rep.path ? (look.views || {}).rep : null;
  const repTitle = repView && repView.stock && repView.view === "plain" ? repView.plain : rep.title;
  const repHead = html`<div class="row vid-panehead">
    <span class="eyebrow">${repTitle || "Replacement"}</span>
    ${rep.path ? html`<span class="mono small nw ellip acc-ink" ...${tip(repLine
      ? { head: rep.path, lines: [repLine] } : rep.path)}>— ${rep.label}</span>` : null}
    <span class="grow"></span>
    <${Button} size="sm" onClick=${() => currentRel && choose(currentRel)} disabled=${!currentRel}>Choose…<//>
    ${pv.can_clear ? html`<${Button} size="sm" kind="ghost" onClick=${() => call("video.clear", [pv.rel])}>Clear replacement<//>` : null}
  </div>`;
  const origHead = html`<div class="row vid-panehead">
    <span class="eyebrow">${orig.title || "Original"}</span>
    ${orig.path ? html`<span class="mono small muted nw ellip" title=${orig.path}>— ${orig.label}</span>` : null}
  </div>`;
  // ▶ on an empty pane: load the highlighted row and play that pane
  const emptyPlay = (side) => { if (currentRel) call("video.activate_pane", currentRel, side); };

  const withBar = (page) => html`<div class="cpd-shell" ref=${shellRef}>${page}${colorNs.has_project ? html`<${ColorBar} host="video" startMode="assets"
    open=${colors} setOpen=${setColors} file=${colorFile} />` : null}</div>`;
  if (cmpOpen) {
    return withBar(html`<${CompareView} cmp=${cmp} byRel=${byRel} cs=${colorNs} look=${look}
      active=${activeTile ? activeTile.id : null} setActive=${setCmpActive} stopSeq=${s.stop_seq}
      onOpenColors=${colorNs.has_project ? openColors : undefined} colorOffered=${!!s.color_offered} colorStock=${!!s.color_stock} />`);
  }
  return withBar(html`<div class="page vid-page">
    <${PageHead} title="Video" sub=${html`${T.intro}<span class="vid-project small"><span class="lbl0">Project folder:</span>
        <button type="button" class=${cx("vid-link", !s.project && "none")} onClick=${() => call("video.open_project_folder")}
          ...${tip(T.project)}>${s.project_text}</button></span>`}>
      ${s.status ? html`<${Chip} kind="acc">${s.status}<//>` : null}
      <${Button} kind="ghost" icon="undo" cls="vid-undo" disabled=${!undo.undo || running} onClick=${() => call("video.undo")}
        title=${{ head: "Undo", lines: [["Ctrl+Z", undo.undo ? "Undo " + undo.undo : T.undoNone]] }}>Undo<//>
      <${Button} kind="ghost" icon="redo" cls="vid-redo" disabled=${!undo.redo || running} onClick=${() => call("video.undo", true)}
        title=${{ head: "Redo", lines: [["Ctrl+Y", undo.redo ? "Redo " + undo.redo : T.redoNone], ["Ctrl+Shift+Z", "Redo as well"]] }}>Redo<//>
      <${Button} icon=${s.scanning ? "x" : "refresh"} onClick=${() => call(s.scanning ? "video.cancel_scan" : "video.scan")}>${s.scanning ? "Cancel scan" : "Scan"}<//>
      <${Button} icon="compare" cls="vid-cmp-open" onClick=${() => openCompare(compareRels())} disabled=${!currentRel}
        title=${T.compare}>Compare<//>
      <${Button} icon="folder" onClick=${() => call("video.replace_from_folder")} disabled=${running} title=${T.folder}>Replace from folder…<//>
      ${s.best_supported ? html`<${Button} kind="ghost" icon="star" onClick=${() => call("video.best_open")} title=${T.best}>Best quality…<//>` : null}
      <${Button} kind="ghost" icon="more" label="More"
        title=${s.quality_report ? "More: Export CSV, Clear replacements…, Save / load settings, Check card…" : "More: Export CSV, Clear replacements…, Save / load settings"}
        onClick=${(e) => openMenu(e.currentTarget, [
          { label: "Export CSV", icon: "download", title: T.csv, onClick: () => call("video.export_csv") },
          { label: "Clear replacements…", icon: "trash", title: T.clear, disabled: !s.can_clear || running,
            onClick: () => call("video.clear_all") },
          { sep: true },
          { label: "Save settings to a file…", icon: "download", title: "Which file replaces which slot, and this tab's ticks and options, in one small file to keep or to send. The clips themselves are not in it.",
            onClick: () => call("video.settings_save") },
          { label: "Load settings from a file…", icon: "upload", disabled: running,
            title: "Put the settings in a file saved here or by someone else onto the same slots of this card. A slot this card does not have is left out.",
            onClick: () => call("video.settings_load") },
          s.quality_report ? { sep: true } : null,
          s.quality_report ? { label: "Check card…", icon: "check", title: T.check,
            onClick: () => call("video.quality_open") } : null,
        ], { align: "right" })} />
    <//>
    ${s.ffmpeg_missing ? html`<${Note} kind="err">${T.ffmpeg}<//>` : null}
    <section class="card vid-card" ref=${cardRef}>
      <div class="toolbar">
        <${Field} ns="video" k="search" value=${s.search} placeholder="Search" cls="search"
          prefix=${html`<${Icon} name="search" />`} />
        <span class="vid-show" ...${tip(T.show)}><${Seg} value=${s.change_filter || "All"} options=${["All", "Changed", "Unchanged"]}
          onChange=${(v) => call("video.set_change_filter", v)} /></span>
        ${modesCol ? html`<${Select} cls="vid-modefilter" sm value=${md.filter || ""} title=${T.modeFilter}
          options=${[{ value: "", label: "Every mode" }].concat((md.list || []).map((m) => ({ value: m.id, label: `${m.label} (${m.n})` })))}
          onChange=${(v) => call("video.set_mode_filter", v)} />`
          : md.busy ? html`<span class="small muted nw vid-modes-busy"><${Spinner} /> ${T.modesBusy}</span>` : null}
        <span class="sp"></span>
        <span class="vid-opts">
          <${Check} checked=${s.no_conversion} label=${T.noconv} title=${T.noconvTip} cls="small"
            onChange=${(v) => call("video.set_no_conversion", v)} />
          <${Check} checked=${s.trim} label=${T.trim} title=${s.trim_tip} cls="small" disabled=${!s.trim_enabled}
            onChange=${(v) => call("video.set_trim", v)} />
          ${s.best_supported ? html`<${Check} checked=${s.best_quality} label="Best quality" title=${s.best_tip} cls="small"
            onChange=${(v) => call("video.set_best_quality", v)} />` : null}
          ${s.color_offered ? html`<span ...${tip(ADV_TIP)}><${Check} checked=${s.color_stock} label="Advanced" cls="small"
            onChange=${(v) => call("video.set_color_stock", v)} /></span>` : null}
        </span>
      </div>
      <div class="vid-tblwrap" onMouseDownCapture=${onGripDown}>
        <${Table} cls="vid-tbl" columns=${columns} rows=${rows} rowKey=${(r) => r.rel} rowHeight=${ROW_H}
          selected=${selected} onSelect=${onSelect} onActivate=${(r) => choose(r.rel)} onContext=${onContext}
          sort=${s.sort} onSort=${(k) => call("video.sort", k)}
          resizable widths=${tuned} onResize=${onResize} style=${`--vid-minw:${Math.round(minWidth)}px`}
          rowClass=${(r) => cx(r.rep_cls === "stray" && "vid-foreign")}
          empty=${emptyNode} />
      </div>
      <div class="vid-preview">
        ${pv.note ? html`<${Note} kind=${pv.note.kind}><b>${pv.note.text.replace(/^[⚠✗]\s*/, "")}</b><//>` : null}
        ${pv.modes && pv.modes.rel === currentRel ? html`<div class="vid-modes">
          <${Note} kind="info" action=${pv.modes.back ? html`<${Button} size="sm" onClick=${() => call("video.shared_again", pv.modes.rel)}
            disabled=${running}>Use the same clip as ${pv.modes.back} again…<//>` : null}>${pv.modes.text}<//>
        </div>` : null}
        ${pv.sounds && pv.sounds.rel === currentRel ? html`<div class="vid-sounds">
          <${Note} kind="info"><span>${pv.sounds.head}</span>
            ${(pv.sounds.items || []).length ? html`<ul class="vid-sound-list">${pv.sounds.items.map((it) => html`
              <li ...${tip(it.tip)}><b>${it.text}</b> <span class="muted">${it.how}</span></li>`)}</ul>` : null}
            ${pv.sounds.more ? html`<div class="small muted">${pv.sounds.more}</div>` : null}
            ${pv.sounds.foot ? html`<div class="small muted">${pv.sounds.foot}</div>` : null}<//>
        </div>` : null}
        ${look.offered ? html`<${LookRow} look=${look} ns="video" onOpen=${colorNs.has_project ? openColors : undefined} />` : null}
        <div class="vid-panes">
          <${Pane} pane=${orig} side="orig" play=${s.play} stopSeq=${s.stop_seq} onEmptyPlay=${emptyPlay} head=${origHead} look=${look} />
          <span class="vid-vsep"></span>
          <${Pane} pane=${rep} side="rep" play=${s.play} stopSeq=${s.stop_seq} onEmptyPlay=${emptyPlay} head=${repHead} look=${look} />
        </div>
      </div>
    </section>
    ${spec ? html`<${SpecDialog} spec=${spec} onClose=${() => setSpec(null)} />` : null}
    ${q.open ? html`<${QualityWindow} q=${q} />` : null}
    ${best.open ? html`<${BestWindow} b=${best} />` : null}
  </div>`);
}
