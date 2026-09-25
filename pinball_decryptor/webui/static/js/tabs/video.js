// Replace Video tab: scan the project folder's clips, pick a replacement per
// slot (or a whole folder of them), compare Original and Replacement side by
// side, and decide per clip whether Write converts it.  Python half:
// webui/tabs/video.py (every rule, message and file operation lives there).

import { html, useEffect, useMemo, useRef, useState, PageHead, Button, Field, Check, Seg, Chip,
         Note, Table, Empty, Modal, Icon, Spinner, openMenu, menuOpen, tip, call, cx, mediaUrl }
  from "../core/ui.js";
import { useNs } from "../core/store.js";

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
  specCmd: "To encode your own, start from this and tune whatever you like around it (bitrate, key-frame interval, preset) — the flags below are the parts that have to match:",
  specAn: "The -an is deliberate: this slot's clip has no audio track, and one you add will be played.",
  best: "Convert every replaced clip at full quality from your own files, for a card built with room to spare (Write tab → SD card size). If this project doesn't know which files your clips came from, it finds them: point it at a card built with your videos and the folder they are in.",
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
const COL_MIN = { rel: 160, len: 46, res: 70, fmt: 80, aud: 70, rep: 110, conv: 60 };
const HEADS = { rel: "Original Video", len: "Length", res: "Resolution", fmt: "Format",
                aud: "Audio", rep: "Replacement", conv: "Convert" };
// The long-named columns share the width that is left over (more or less
// of it); the others keep the width that fits them, so a narrow window
// shortens names, never "MP4 h264 30fps" or a length.
const FLEX = ["rel", "rep"];
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
          rep: textWidth(r.rep, f.body), conv: textWidth(r.conv, f.body) };
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

function Pane({ pane, side, play, stopSeq, onEmptyPlay, head }) {
  const vref = useRef(null);
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

  return html`<div class="vid-pane">
    ${head}
    <div class="vid-screen">
      ${pane.path && src ? html`<video key=${pane.seq + ":" + src} ref=${vref} src=${mediaUrl(src)}
          poster=${pane.poster ? mediaUrl(pane.poster) : undefined} preload="metadata" playsinline
          onPlay=${() => setPlaying(true)} onPause=${() => setPlaying(false)} onEnded=${onEnded}
          onTimeUpdate=${(e) => { if (!e.currentTarget.paused) setPos(e.currentTarget.currentTime); }} onError=${onError}
          onLoadedData=${onReady} onCanPlay=${onReady}></video>`
        : pane.poster ? html`<img src=${mediaUrl(pane.poster)} alt="" />` : null}
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
  const orig = pv.orig || {};
  const rep = pv.rep || {};
  const q = s.quality || {};
  const best = s.best || {};
  const [sel, setSel] = useState(() => new Set());
  const anchor = useRef(null);
  const selectJob = useRef(null);
  const [spec, setSpec] = useState(null);
  const cardRef = useRef(null);
  // the first highlighted row in list order (Tk: tree.selection()[0])
  const firstOf = (set) => { const f = rows.find((x) => set.has(x.rel)); return f ? f.rel : null; };
  const firstSel = useMemo(() => firstOf(sel), [rows, sel]);

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
      info.can_clear && { sep: true },
      info.can_clear && { label: "Clear replacement", onClick: () => call("video.clear", [rel]) },
      info.stern && info.scenes && { sep: true },
      info.stern && info.scenes && { label: "Show scene contents…", onClick: () => call("video.scene_contents", rel) },
      { sep: true },
      { label: "This clip's conversion", submenu: [
        { label: `Follow the box below (${info.follow})`, checked: info.asis === "box", onClick: () => call("video.set_asis", rel, null) },
        { label: "Always use my file as-is", checked: info.asis === "asis", onClick: () => call("video.set_asis", rel, true) },
        { label: "Always convert this clip", checked: info.asis === "convert", onClick: () => call("video.set_asis", rel, false) },
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
  const minWidth = 30 + ["rel", "len", "res", "fmt", "aud", "rep"].reduce((a, k) =>
    a + (tuned[k] ? Math.max(36, tuned[k]) : FLEX.includes(k) ? COL_MIN[k] : fit[k]), 0) + fit.conv + 7 * 10 + 20;
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
    { key: "rel", label: "Original Video", width: width("rel"), sort: "#0", titleOf: (r) => r.rel,
      render: (r) => html`${r.dir ? html`<span class="mono muted">${r.dir}</span>` : null}${r.name}` },
    { key: "len", label: "Length", width: width("len"), num: true, sort: "len" },
    { key: "res", label: "Resolution", width: width("res"), sort: "res" },
    { key: "fmt", label: "Format", width: width("fmt"), sort: "fmt", titleOf: (r) => r.fmt,
      render: (r) => html`<span class=${r.fmt_bad ? "err-ink" : "dim"}>${r.fmt}</span>` },
    { key: "aud", label: "Audio", width: width("aud"), sort: "aud", render: (r) => html`<span class="dim">${r.aud}</span>` },
    { key: "rep", label: "Replacement", width: width("rep"), sort: "rep", titleOf: (r) => r.rep,
      render: (r) => html`<button type="button" class=${cx("vid-rep", r.rep_cls || "muted")}
        onClick=${(e) => { e.stopPropagation(); setSel(new Set([r.rel])); anchor.current = r.rel; choose(r.rel); }}>${r.rep}</button>` },
    { key: "conv", label: "Convert", width: convWidth, sort: "conv", titleOf: (r) => r.conv,
      render: (r) => html`<span class=${r.conv_cls === "bad" ? "err-ink" : r.conv_cls === "stray" ? "warn-ink" : ""}>${r.conv}</span>` },
  ];
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
  }, []);

  const repHead = html`<div class="row vid-panehead">
    <span class="eyebrow">${rep.title || "Replacement"}</span>
    ${rep.path ? html`<span class="mono small nw ellip acc-ink" title=${rep.path}>— ${rep.label}</span>` : null}
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

  return html`<div class="page vid-page">
    <${PageHead} title="Video" sub=${html`${T.intro}<span class="vid-project small"><span class="lbl0">Project folder:</span>
        <button type="button" class=${cx("vid-link", !s.project && "none")} onClick=${() => call("video.open_project_folder")}
          ...${tip(T.project)}>${s.project_text}</button></span>`}>
      ${s.status ? html`<${Chip} kind="acc">${s.status}<//>` : null}
      <${Button} onClick=${() => call(s.scanning ? "video.cancel_scan" : "video.scan")}>${s.scanning ? "Cancel scan" : "Scan"}<//>
      <${Button} onClick=${() => call("video.replace_from_folder")} disabled=${running} title=${T.folder}>Replace from folder…<//>
      <${Button} kind="ghost" onClick=${() => call("video.export_csv")} title=${T.csv}>Export CSV<//>
      <${Button} kind="ghost" onClick=${() => call("video.clear_all")} disabled=${!s.can_clear || running} title=${T.clear}>Clear replacements…<//>
      ${s.quality_report ? html`<${Button} kind="ghost" onClick=${() => call("video.quality_open")} title=${T.check}>Check card…<//>` : null}
      ${s.best_supported ? html`<${Button} kind="ghost" onClick=${() => call("video.best_open")} title=${T.best}>Best quality…<//>` : null}
    <//>
    ${s.ffmpeg_missing ? html`<${Note} kind="err">${T.ffmpeg}<//>` : null}
    <section class="card vid-card" ref=${cardRef}>
      <div class="toolbar">
        <${Field} ns="video" k="search" value=${s.search} placeholder="Search" cls="search"
          prefix=${html`<${Icon} name="search" />`} />
        <span class="vid-show" ...${tip(T.show)}><${Seg} value=${s.change_filter || "All"} options=${["All", "Changed", "Unchanged"]}
          onChange=${(v) => call("video.set_change_filter", v)} /></span>
        <span class="sp"></span>
        <span class="vid-opts">
          <${Check} checked=${s.no_conversion} label=${T.noconv} title=${T.noconvTip} cls="small"
            onChange=${(v) => call("video.set_no_conversion", v)} />
          <${Check} checked=${s.trim} label=${T.trim} title=${s.trim_tip} cls="small" disabled=${!s.trim_enabled}
            onChange=${(v) => call("video.set_trim", v)} />
          ${s.best_supported ? html`<${Check} checked=${s.best_quality} label="Best quality" title=${s.best_tip} cls="small"
            onChange=${(v) => call("video.set_best_quality", v)} />` : null}
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
        <div class="vid-panes">
          <${Pane} pane=${orig} side="orig" play=${s.play} stopSeq=${s.stop_seq} onEmptyPlay=${emptyPlay} head=${origHead} />
          <span class="vid-vsep"></span>
          <${Pane} pane=${rep} side="rep" play=${s.play} stopSeq=${s.stop_seq} onEmptyPlay=${emptyPlay} head=${repHead} />
        </div>
      </div>
    </section>
    ${spec ? html`<${SpecDialog} spec=${spec} onClose=${() => setSpec(null)} />` : null}
    ${q.open ? html`<${QualityWindow} q=${q} />` : null}
    ${best.open ? html`<${BestWindow} b=${best} />` : null}
  </div>`;
}
