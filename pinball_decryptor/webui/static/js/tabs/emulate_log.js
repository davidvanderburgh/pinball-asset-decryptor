// The Emulate tab's Sound and video log (PAD-1071), in a window of its own
// (emulate_log.html): every sound and clip the game started during a run, in
// order, with filters.  A sound plays here from its row; Open takes a row to
// the Audio or Video tab, selected and playing.  Python half:
// webui/emulate_log.py (the rows: plugins/stern/emulator_log.py).

import { html, useEffect, useRef, useState, Button, Field, Check, Chip, Note, Table, Empty, tip, cx }
  from "../core/ui.js";
import { render } from "../vendor/preact-htm.js";
import { raw } from "../core/rpc.js";
import { useNs, loadAll, connect, TOKEN } from "../core/store.js";

const POLL_MS = 700;

function applyTheme(theme) {
  let t = theme || "dark";
  if (t === "system") t = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.classList.toggle("light", t === "light");
}

// The rows the app has sent, kept here: each poll asks only for the ones
// past the last (a long session holds thousands).
function useLogRows() {
  const [got, setGot] = useState({ rows: [], first: 0, status: "", why: "", counts: {}, project: "",
    root: "", running: false, ok: true });
  const last = useRef(-1);
  useEffect(() => {
    let alive = true;
    let timer = null;
    const tick = async () => {
      let j = null;
      try { j = await raw("emulate.log_rows", [last.current]); } catch (err) { j = null; }
      if (!alive) return;
      if (j && j.ok && j.r) {
        const r = j.r;
        setGot((prev) => {
          let rows = prev.rows;
          if (rows.length && rows[0].i < r.first) rows = rows.filter((x) => x.i >= r.first);
          if (r.rows.length) rows = rows.concat(r.rows.filter((x) => x.i > last.current));
          last.current = rows.length ? rows[rows.length - 1].i : r.first - 1;
          return { ...r, rows, ok: true };
        });
      } else {
        setGot((prev) => ({ ...prev, ok: false }));
      }
      timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  return got;
}

// One sound at a time plays here; `onChange(i)` tells the page which row's is playing (null: none),
// so that row's button is Stop while it plays (round 2: Jim-Beam asked for a Stop).
let player = null;
let playingChange = () => {};
function stopHere() {
  if (player) { player.pause(); player = null; }
  playingChange(null);
}
function playHere(root, r) {
  stopHere();
  if (!root || !r.rel) return;
  const a = new Audio("/media?p=" + encodeURIComponent(root + "/" + r.rel) + "&t=" + encodeURIComponent(TOKEN));
  player = a;
  const done = () => { if (player === a) { player = null; playingChange(null); } };
  a.addEventListener("ended", done);
  a.addEventListener("error", done);
  playingChange(r.i);
  a.play().catch(done);
}

function open(r) {
  if (r.rel) raw("emulate.log_show", [r.kind, r.rel]);
}

function LogApp() {
  const shell = useNs("shell");
  useEffect(() => applyTheme(shell.theme), [shell.theme]);
  useEffect(() => {
    const z = Math.max(0.6, Math.min(2, Number(shell.zoom) || 1));
    document.documentElement.style.zoom = String(z);
  }, [shell.zoom]);
  const got = useLogRows();
  const [sounds, setSounds] = useState(true);
  const [clips, setClips] = useState(true);
  const [text, setText] = useState("");
  const [follow, setFollow] = useState(true);
  const [sel, setSel] = useState(null);
  const [playing, setPlaying] = useState(null);
  useEffect(() => {
    playingChange = setPlaying;
    const esc = (e) => { if (e.key === "Escape") stopHere(); };
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("keydown", esc); stopHere(); };
  }, []);
  const wrap = useRef(null);
  const q = text.trim().toLowerCase();
  const rows = got.rows.filter((r) => (r.kind === "sound" ? sounds : clips)
    && (!q || r.name.toLowerCase().includes(q) || r.what.toLowerCase().includes(q)));
  // follow the newest row as it arrives, unless the user scrolled up to look
  useEffect(() => {
    if (!follow || !wrap.current) return;
    const sc = wrap.current.querySelector(".scroller");
    if (sc) sc.scrollTop = sc.scrollHeight;
  }, [rows.length, follow]);
  const cols = [
    { key: "at", label: "Time", width: "74px", cls: "mono dim" },
    { key: "kind", label: "", width: "58px",
      render: (r) => html`<${Chip} sm kind=${r.kind === "sound" ? "info" : "acc"}>${r.kind === "sound" ? "Sound" : "Clip"}<//>` },
    { key: "name", label: "Name", width: "minmax(0,1fr)",
      render: (r) => html`<span class="elog-name" ...${tip({ head: r.name, lines: r.tip })}>${r.name}</span>` },
    { key: "what", label: "Request / started by", width: "minmax(0,0.8fr)", cls: "dim elog-what" },
    { key: "len", label: "Length", width: "62px", num: true, cls: "mono dim" },
    { key: "act", label: "", width: "118px",
      render: (r) => html`<span class="row elog-act">
        ${r.kind === "sound" ? (playing === r.i
          ? html`<${Button} size="sm" kind="ghost" icon="stop" title="Stop this sound (Esc)"
              onClick=${(e) => { e.stopPropagation(); stopHere(); }} />`
          : html`<${Button} size="sm" kind="ghost" icon="play" disabled=${!r.rel}
              title=${r.rel ? "Play this sound here" : "No Audio tab file plays this request"}
              onClick=${(e) => { e.stopPropagation(); playHere(got.root, r); }} />`) : null}
        <${Button} size="sm" disabled=${!r.rel}
          title=${r.rel ? (r.kind === "sound" ? "Show it on the Audio tab, selected and playing"
            : "Show it on the Video tab, selected and playing") : "It is not one of this project's files"}
          onClick=${(e) => { e.stopPropagation(); open(r); }}>Open<//>
      </span>` },
  ];
  const n = got.counts || {};
  let notice = null;
  if (!got.ok) {
    notice = html`<${Note} kind="warn">The app is not answering. The list goes on when it does.<//>`;
  } else if (got.status === "off") {
    notice = html`<${Note} kind="warn">This run's sounds are not listed: ${got.why}. Its clips are.<//>`;
  }
  const empty = html`<${Empty} icon="emulate" title=${got.running ? "Nothing played yet" : "No run listed yet"}>
    ${got.running ? "Every sound and clip the game starts is listed here as it starts."
      : "Start the emulator on the Emulate tab: every sound and clip the game starts is listed here as it "
        + "starts, and stays here until the next Start."}<//>`;
  return html`<div class="elog">
    <div class="elog-bar row wrap">
      <span class="h2">Sound and video log</span>
      ${got.project ? html`<${Chip} sm title="The project the sounds and clips are named from">${got.project}<//>` : null}
      <${Chip} sm dot kind=${got.running ? "ok" : ""}>${got.running ? "Running" : "Last run"}<//>
      <span class="sp"></span>
      <${Check} label=${"Sounds (" + (n.sound || 0) + ")"} checked=${sounds} onChange=${setSounds}
        title="List the sounds the game played" />
      <${Check} label=${"Clips (" + (n.video || 0) + ")"} checked=${clips} onChange=${setClips}
        title="List the video clips the game played" />
      <${Field} sm width=${170} value=${text} onChange=${setText} placeholder="Filter by name or number" />
      <${Check} label="Follow" checked=${follow} onChange=${setFollow}
        title="Keep the newest row in view as the game plays" />
      <${Button} size="sm" icon="stop" disabled=${playing == null} onClick=${stopHere}
        title="Stop the sound playing here (Esc)">Stop<//>
    </div>
    ${notice}
    <div class="elog-table" ref=${wrap}>
      <${Table} columns=${cols} rows=${rows} rowKey=${(r) => r.i} selected=${sel} rowHeight=${32}
        rowClass=${(r) => cx("elog-row", "elog-" + r.kind, r.unplayed && "elog-unplayed")}
        onSelect=${(r) => { setSel(r.i); if (follow) setFollow(false); }}
        onActivate=${(r) => open(r)} empty=${empty} />
    </div>
    <span class="small muted elog-foot">Double-click a row, or Open, to show it on its tab. ▶ plays a sound here, ■ or Esc stops it.</span>
  </div>`;
}

export async function mountLog(root) {
  document.body.classList.add("elog-view");
  try {
    await loadAll();
  } catch (err) {
    root.textContent = "The app did not answer (" + String(err.message || err) + ").";
    return;
  }
  render(html`<${LogApp} />`, root);
  connect();
}
