// Expression Lights tab (PAD-1040): light shows of the card's own for the cabinet's expression lights - the blades
// down its sides and the backbox speaker lights - each played with the song it goes with (BEN: "if songs are swapped
// out, the expression lighting is no longer in sync with the replaced audio track"). David: "an expression light show
// creator just like the playfield light show creator", and no Insider Connected lost for it.
//
// The shows down the left; THIS game's cabinet in the middle (its lights read off the card's program) PLAYING the
// show with its song, painted by the runtime's own arithmetic (cabfx.js); on the right the show's song, its two lanes
// of steps over the song's waveform, and the step picked. Python half: webui/tabs/lights.py.
//
// PAD-1063 (BEN: "does the existing Stern expression lighting patterns show up?"): under the project's shows, the
// game's own - a show for each of its songs, Original and Remix, read off its program - played here from their frames
// as the game plays them; "Make it a show of mine" makes one a show of the project's (a step of the game's show a
// lane, to cut, move, start later or mix with patterns of your own).

import { html, useEffect, useRef, useState, PageHead, Card, Button, Field, Select, Check, Chip, Note, Empty, Spinner,
         tip, cx, call, openMenu, mediaUrl } from "../core/ui.js";
import { useNs } from "../core/store.js";
import { compileStep, showColours, gameColour, srcOf } from "./cabfx.js";

export const css = true;

const TIP = {
  newShow: "A new show: blank, or starting from one of the ready-made ones.",
  dup: "A copy of this show, to change.",
  del: "Take this show out of the project.",
  name: "The show's name, for you (the log names it too).",
  song: "The song this show plays with: the game starts the show whenever it plays this sound, from the song's start. A song you replaced plays here as you replaced it.",
  loop: "When its steps are over before the song is, start them again. Off: the game's own lights come back after the last step.",
  play: "Play the show with its song, as the machine will.",
  stop: "Stop, back to the start.",
  scrub: "Where in the show and the song you are: drag, or press the timeline.",
  lane: { 0: "The blades down the cabinet's sides: their steps, one bar each, as wide as the step is long.",
          1: "The backbox speaker lights: their steps. A lane with no steps leaves those lights to the game." },
  addStep: "A new step at the end of this lane (a copy of its last).",
  split: "Cut the step under the playhead in two at the playhead: the way to start a new step on a beat.",
  fx: "The pattern this step paints over the lane's lights.",
  ms: "How long this step lasts, ms.",
  blend: "The step blends in from the one before over its first ms (0: at once). The first step blends up from dark.",
  a: "Its first color: the band, the dots, the lit lights.",
  b: "Its second color: the ground, the trail, the lights the pattern is not on.",
  rate: "The pattern's pace, ms: how fast a strobe, pulse, chase or rainbow moves (0: its usual).",
  stepUp: "Move this step earlier", stepDown: "Move this step later", stepDup: "A copy of this step after it",
  stepDel: "Take this step out",
  auto: "Listen to the song and make the show from it: its beat, its bars and its loud and quiet parts, every step on a bar line and every pattern in time with the beat. This show's steps are replaced (Undo in the history brings them back).",
  tryit: "Start the emulator with this project's changes, these shows among them: play a game and watch the cabinet's lights.",
  game: "The game's own lights (this lane has no steps).",
  stock: "The game's own show for this song, as it plays on the machine: press to watch it with its song.",
  stockSet: { original: "The show the game plays with EXPRESSION LIGHTS MODE on ORIGINAL SHOWS (as shipped).",
              remix: "The other show the game has for this song: EXPRESSION LIGHTS MODE on REMIX SHOWS." },
  fromStock: "A show of your own that starts as this one: the game's show on both lanes, to cut, move, start later or mix with patterns of your own. Then pick the song it plays with.",
  gameSong: "Which of the game's shows this step plays: the game's show for that song.",
  gameSet: "The game's Original show for the song, or its Remix.",
  gameFrom: "Where in the game's show this step starts, ms: 0 from its start. The step then plays on from there for as long as it lasts.",
};
const SET_WORD = { original: "Original", remix: "Remix" };
const SWATCHES = ["#ffffff", "#ffd000", "#ffb000", "#ff7800", "#ff3000", "#ff0000", "#ff40a0", "#a040ff", "#4000a0",
  "#0050ff", "#00a0ff", "#00e0ff", "#00c040", "#00ff60", "#000000"];
const LANES = ["blades", "speakers"];
const LANE_WORD = ["Blades", "Speaker lights"];
const clone = (x) => JSON.parse(JSON.stringify(x));
const secs = (ms) => {
  const s = Math.max(0, ms) / 1000;
  return s >= 60 ? `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}` : `${s.toFixed(1)} s`;
};
const hexOf = (c) => "#" + (c >>> 0).toString(16).padStart(6, "0");
const laneLen = (steps) => (steps || []).reduce((a, s) => a + (Number(s.ms) || 0), 0);
const stockName = (s, x) => {
  const g = x && (s.songs || []).find((y) => y.slot === x.slot);
  if (g) return g.name;
  return !x ? "?" : x.slot != null ? `idx${String(x.slot).padStart(4, "0")}` : `Song ${x.req}`;   // the Audio tab's name
};

// ------------------------------------------------------------------ the game's own shows' frames (PAD-1063)
// Each show's frames are a file the app wrote beside its cache: fetched once, when a show plays it.
function useFrames(stock) {
  const got = useRef({});
  const [, bump] = useState(0);
  const get = (req, set) => {
    const key = `${req}:${set}`;
    const have = got.current[key];
    if (have !== undefined) return have;
    const x = (stock || []).find((y) => y.req === req);
    const path = x && x.files ? x.files[set] : "";
    got.current[key] = null;
    if (path) {
      fetch(mediaUrl(path)).then((r) => (r.ok ? r.arrayBuffer() : null)).then((b) => {
        if (b) { got.current[key] = new Uint8Array(b); bump((n) => n + 1); }
      }).catch(() => {});
    }
    return null;
  };
  return get;
}

// ------------------------------------------------------------------ the clock: the song's, or its own
function useClock(total, audioRef, src) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const ref = useRef({ t: 0, last: 0, raf: 0 });
  useEffect(() => {
    const a = audioRef.current;
    if (!playing) { if (a) a.pause(); return undefined; }
    if (a && src) { a.currentTime = ref.current.t / 1000; a.play().catch(() => {}); }
    ref.current.last = performance.now();
    const frame = (now) => {
      const st = ref.current, au = audioRef.current;
      if (au && src && !au.paused) st.t = au.currentTime * 1000;
      else st.t += Math.min(100, now - st.last);
      st.last = now;
      if (st.t >= total) { st.t = total; setT(total); setPlaying(false); return; }
      setT(st.t);
      st.raf = requestAnimationFrame(frame);
    };
    ref.current.raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(ref.current.raf);
  }, [playing, total, src]);
  const seek = (ms) => {
    ref.current.t = Math.max(0, Math.min(total, ms));
    setT(ref.current.t);
    const a = audioRef.current;
    if (a && src) a.currentTime = ref.current.t / 1000;
  };
  return { t, playing, seek, play: () => { if (ref.current.t >= total) seek(0); setPlaying(true); },
           pause: () => setPlaying(false), stop: () => { setPlaying(false); seek(0); } };
}

// ------------------------------------------------------------------ the cabinet, playing the show
function Cabinet({ lights, show, t, meta, frames }) {
  const lanes = LANES.map((k) => (show[k] || []).map(compileStep));
  const game = (st, L, at) => gameColour(st, srcOf(L.name), at, meta, frames(st.a, st.b ? "remix" : "original"));
  const cols = showColours(lights, lanes, !!show.loop, Math.floor(t), game);
  const ring = lights.filter((l) => l.lane === 1);
  const blade = lights.filter((l) => l.lane === 0);
  // the backbox's speakers: a grille under each ring of lights (left and right), centred on its lights
  const grilles = [-1, 0, 1].map((side) => {
    const r = ring.filter((l) => l.side === side);
    if (!r.length) return null;
    const x = r.reduce((a, l) => a + l.x, 0) / r.length, y = r.reduce((a, l) => a + l.y, 0) / r.length;
    return { side, x, y, r: Math.max(14, Math.max(...r.map((l) => Math.hypot(l.x - x, l.y - y))) - 7) };
  }).filter(Boolean);
  const pitch = blade.length > 1 ? Math.max(4, Math.min(12, (600 - 140) / (blade.length / 2) - 1.5)) : 9;
  return html`<svg class="xl-cab" viewBox="0 0 300 610" role="img" aria-label="The cabinet's expression lights, playing the show">
    <rect class="xl-box" x="40" y="2" width="220" height="132" rx="10" />
    <path class="xl-body" d="M28 150 L272 150 L262 606 L38 606 Z" />
    ${grilles.map((g) => html`<g key=${g.side}><circle class="xl-grille" cx=${g.x} cy=${g.y} r=${g.r} />
      <circle class="xl-cone" cx=${g.x} cy=${g.y} r=${g.r * 0.45} /></g>`)}
    ${lights.map((l, k) => {
      const c = cols[k];
      const style = c ? { fill: hexOf(c), color: hexOf(c) } : null;
      const cls = cx("xl-led", c === null && "game", c && "lit");
      return l.lane === 1
        ? html`<circle key=${k} class=${cls} cx=${l.x} cy=${l.y} r="5.5" style=${style} ...${tip({ head: l.name, lines: [c === null ? TIP.game : ""] })} />`
        : html`<rect key=${k} class=${cls} x=${l.x - 5} y=${l.y - pitch / 2} width="10" height=${pitch} rx="2" style=${style}
            ...${tip({ head: l.name, lines: [c === null ? TIP.game : ""] })} />`;
    })}
    ${!ring.length ? html`<text class="xl-none" x="150" y="72" text-anchor="middle">no speaker lights</text>` : null}
    ${!blade.length ? html`<text class="xl-none" x="150" y="380" text-anchor="middle">no blades on this game</text>` : null}
  </svg>`;
}

// ------------------------------------------------------------------ the timeline: two lanes over the song
function Wave({ peaks }) {
  if (!peaks || !peaks.length) return null;
  const n = peaks.length;
  const d = peaks.map((v, i) => `M${i} ${32 - (v / 255) * 30}V${32 + (v / 255) * 30}`).join("");
  return html`<svg class="xl-wave" viewBox=${`0 0 ${n} 64`} preserveAspectRatio="none" aria-hidden="true"><path d=${d} /></svg>`;
}

function Lane({ s, lane, steps, total, sel, onSel, onSeek, t }) {
  const ref = useRef(null);
  const seekAt = (e) => {
    if (!ref.current || e.target.closest(".xl-bar")) return;
    const r = ref.current.getBoundingClientRect();
    onSeek(((e.clientX - r.left) / r.width) * total);
  };
  let at = 0;
  return html`<div class="xl-lane" ref=${ref} onClick=${seekAt} ...${tip(TIP.lane[lane])}>
    ${steps.map((st, i) => {
      const left = (at / total) * 100, w = ((Number(st.ms) || 0) / total) * 100;
      at += Number(st.ms) || 0;
      const g = st.fx === "game";
      const head = g ? `${i + 1}. the game's show: ${stockName(s, (s.stock || []).find((x) => x.req === st.req))} (${SET_WORD[st.set] || ""})`
        : `${i + 1}. ${st.fx.replace(/_/g, " ")}`;
      return html`<button type="button" key=${i} class=${cx("xl-bar", g && "xl-bar-game", sel && sel.lane === lane && sel.i === i && "sel")}
        style=${{ left: `${left}%`, width: `${w}%`, background: g ? undefined : `linear-gradient(90deg, ${st.a}, ${st.b})` }}
        onClick=${() => onSel({ lane, i })} ...${tip({ head, lines: [g ? `${secs(st.ms)}, from ${secs(st.from || 0)} into it` : secs(st.ms)] })}>
        <span class="xl-bar-n">${i + 1}</span></button>`;
    })}
    ${!steps.length ? html`<span class="xl-lane-empty small muted">the game's own</span>` : null}
    <div class="xl-head" style=${{ left: `${Math.min(100, (t / total) * 100)}%` }}></div>
  </div>`;
}

function ColorBox({ value, onChange, title }) {
  return html`<span class="xl-color">
    <input type="color" value=${value || "#ffffff"} onInput=${(e) => onChange(e.target.value)} ...${tip(title)} />
    <span class="xl-swatches">${SWATCHES.map((c) => html`<button type="button" key=${c} class=${cx("xl-swatch", value === c && "on")}
      style=${{ background: c }} aria-label=${c} ...${tip(c)} onClick=${() => onChange(c)}></button>`)}</span>
  </span>`;
}

function NumBox({ value, onChange, title, min, max }) {
  return html`<${Field} sm mono width="76px" value=${String(value ?? "")} title=${title}
    onChange=${(v) => { const n = Number(String(v).replace(/,/g, "")); if (String(v).trim() !== "" && Number.isInteger(n)) onChange(Math.max(min, Math.min(max, n))); }} />`;
}

function StepCard({ s, show, sel, edit }) {
  const steps = show[LANES[sel.lane]] || [];
  const st = steps[sel.i];
  if (!st) return null;
  const n = steps.length, lim = s.limits || {};
  const groups = [...new Set((s.fx || []).map((f) => f.group))];
  const fxOpts = groups.flatMap((g) => (s.fx || []).filter((f) => f.group === g).map((f) => ({ value: f.key, label: f.label, group: g })));
  const uses = ((s.fx || []).find((f) => f.key === st.fx) || {}).uses ?? "a";
  const setK = (k, v) => edit((d) => { d[LANES[sel.lane]][sel.i][k] = v; });
  // PAD-1063: a step of the game's own show names its song, its set and where in it it starts
  const stock = s.stock || [];
  const setFx = (v) => edit((d) => {
    const x = d[LANES[sel.lane]][sel.i];
    x.fx = v;
    if (v === "game" && !stock.some((y) => y.req === x.req) && stock.length) {
      const own = stock.find((y) => y.slot === show.slot) || stock[0];
      Object.assign(x, { req: own.req, set: "original", from: 0 });
    }
  });
  const move = (dir) => edit((d) => { const l = d[LANES[sel.lane]]; const [x] = l.splice(sel.i, 1); l.splice(sel.i + dir, 0, x); }, { lane: sel.lane, i: sel.i + dir });
  return html`<div class="xl-step">
    <div class="row xl-step-hd">
      <span class="h3">${LANE_WORD[sel.lane]}: step ${sel.i + 1} of ${n}</span><span class="sp"></span>
      <button type="button" class="bk-x" disabled=${sel.i === 0} aria-label=${TIP.stepUp} ...${tip(TIP.stepUp)} onClick=${() => move(-1)}>↑</button>
      <button type="button" class="bk-x" disabled=${sel.i === n - 1} aria-label=${TIP.stepDown} ...${tip(TIP.stepDown)} onClick=${() => move(1)}>↓</button>
      <button type="button" class="bk-x" disabled=${n >= lim.steps} aria-label=${TIP.stepDup} ...${tip(TIP.stepDup)}
        onClick=${() => edit((d) => { d[LANES[sel.lane]].splice(sel.i + 1, 0, clone(st)); }, { lane: sel.lane, i: sel.i + 1 })}>⧉</button>
      <button type="button" class="bk-x" aria-label=${TIP.stepDel} ...${tip(TIP.stepDel)}
        onClick=${() => edit((d) => { d[LANES[sel.lane]].splice(sel.i, 1); }, n > 1 ? { lane: sel.lane, i: Math.max(0, sel.i - 1) } : null)}>×</button>
    </div>
    <div class="xl-grid">
      <span class="lbl" ...${tip(TIP.fx)}>Pattern</span>
      <${Select} sm value=${st.fx} options=${stock.length ? fxOpts : fxOpts.filter((o) => o.value !== "game")} width=${190} onChange=${setFx} />
      <span class="lbl" ...${tip(TIP.ms)}>Lasts</span>
      <span class="row xl-inl"><${NumBox} value=${st.ms} min=${(lim.ms || [20])[0]} max=${(lim.ms || [0, 600000])[1]} title=${TIP.ms} onChange=${(v) => setK("ms", v)} /><span class="small muted">ms</span>
        <span class="small muted" ...${tip(TIP.blend)}>· blends in over</span><${NumBox} value=${st.blend || 0} min=${0} max=${st.ms} title=${TIP.blend} onChange=${(v) => setK("blend", v)} /><span class="small muted">ms</span></span>
      ${st.fx === "game" ? html`<span class="lbl" ...${tip(TIP.gameSong)}>Song</span>
        <${Select} sm value=${String(st.req)} width=${260} title=${TIP.gameSong}
          options=${stock.map((x) => ({ value: String(x.req), label: `${stockName(s, x)} (${secs(x.ms)})` }))}
          onChange=${(v) => setK("req", Number(v))} />
        <span class="lbl" ...${tip(TIP.gameSet)}>Show</span>
        <${Select} sm value=${st.set || "original"} width=${140} title=${TIP.gameSet}
          options=${[{ value: "original", label: "Original" }, { value: "remix", label: "Remix" }]} onChange=${(v) => setK("set", v)} />
        <span class="lbl" ...${tip(TIP.gameFrom)}>Starts at</span>
        <span class="row xl-inl"><${NumBox} value=${st.from || 0} min=${0} max=${1200000} title=${TIP.gameFrom} onChange=${(v) => setK("from", v)} /><span class="small muted">ms into the game's show</span></span>` : null}
      ${uses.includes("a") ? html`<span class="lbl" ...${tip(TIP.a)}>Color</span><${ColorBox} value=${st.a} title=${TIP.a} onChange=${(v) => setK("a", v)} />` : null}
      ${uses.includes("b") ? html`<span class="lbl" ...${tip(TIP.b)}>Second color</span><${ColorBox} value=${st.b} title=${TIP.b} onChange=${(v) => setK("b", v)} />` : null}
      ${uses.includes("r") ? html`<span class="lbl" ...${tip(TIP.rate)}>Pace</span>
        <span class="row xl-inl"><${NumBox} value=${st.rate ?? 0} min=${0} max=${lim.rate || 5000} title=${TIP.rate} onChange=${(v) => setK("rate", v)} /><span class="small muted">ms</span></span>` : null}
    </div>
  </div>`;
}

// ------------------------------------------------------------------ the page
export default function LightsTab() {
  const s = useNs("lights");
  const shows = s.shows || [];
  const [pick, setPick] = useState(0);
  const [stockPick, setStockPick] = useState(null);   // PAD-1063: { req, set } - a show of the game's on the stage
  const frames = useFrames(s.stock);
  const [sel, setSel] = useState(null);
  const [draft, setDraft] = useState(null);           // the show being edited, saved a moment after each change
  const timer = useRef(0);
  const audioRef = useRef(null);
  const si = Math.min(pick, Math.max(0, shows.length - 1));
  const saved = shows[si] || null;
  const stockShow = stockPick && (s.stock || []).find((x) => x.req === stockPick.req);
  const gameShow = stockShow ? { name: stockName(s, stockShow), slot: stockShow.slot, loop: false,
    blades: [{ fx: "game", ms: stockShow.ms, req: stockShow.req, set: stockPick.set, from: 0, blend: 0 }],
    speakers: [{ fx: "game", ms: stockShow.ms, req: stockShow.req, set: stockPick.set, from: 0, blend: 0 }] } : null;
  const show = gameShow || (draft && draft.si === si ? draft.show : saved);
  useEffect(() => { setDraft(null); setSel(null); }, [si, shows.length]);
  const song = show && (s.songs || []).find((x) => x.slot === show.slot);
  useEffect(() => { if (song) call("lights.song_peaks", song.slot); }, [song && song.slot, song && song.path]);
  const songMs = song ? Math.round(song.seconds * 1000) : 0;
  const total = Math.max(1000, songMs, show ? Math.max(laneLen(show.blades), laneLen(show.speakers)) : 0);
  const src = song ? mediaUrl(song.path) : "";
  const clock = useClock(total, audioRef, src);

  const edit = (fn, nextSel) => {
    const d = clone(show);
    fn(d);
    setDraft({ si, show: d });
    if (nextSel !== undefined) setSel(nextSel);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => call("lights.save_show", si, d), 350);
  };
  const addStep = (lane) => edit((d) => {
    const l = d[LANES[lane]];
    l.push(l.length ? clone(l[l.length - 1]) : { fx: "solid", ms: 2000, a: "#ff3000", b: "#000000", rate: 0, blend: 0 });
  }, { lane, i: (show[LANES[lane]] || []).length });
  const split = () => {
    if (!sel) return;
    const l = show[LANES[sel.lane]] || [];
    let at = 0, i = 0;
    for (; i < l.length; i++) { if (clock.t < at + l[i].ms) break; at += l[i].ms; }
    if (i >= l.length) return;
    const cut = Math.round(clock.t - at);
    if (cut < 20 || l[i].ms - cut < 20) return;
    edit((d) => {
      const a = d[LANES[sel.lane]][i], b = clone(a);
      a.ms = cut; b.ms -= cut; a.blend = Math.min(a.blend || 0, a.ms); b.blend = Math.min(b.blend || 0, b.ms);
      d[LANES[sel.lane]].splice(i + 1, 0, b);
    }, { lane: sel.lane, i: i + 1 });
  };
  const newMenu = (e) => openMenu(e.currentTarget, (s.presets || []).map((p) => ({
    label: p.key === "blank" ? "Blank" : `From “${p.label}”`,
    onClick: () => call("lights.new_show", p.key, show ? show.slot : null).then((i) => { if (i >= 0) setPick(i); }) })));

  const head = html`<${PageHead} title="Expression lights" sub=${s.intro}>
    ${shows.length ? html`<${Chip} kind="acc">${shows.length} of ${s.max} shows<//>` : null}
    <${Button} icon="refresh" disabled=${s.reading} onClick=${() => call("lights.refresh")}>Read again<//>
    <${Button} kind="primary" icon="play" disabled=${!s.available || s.running || !shows.length} title=${TIP.tryit}
      onClick=${() => call("lights.try_it")}>Run in emulator<//>
  <//>`;
  if (s.reading && !(s.lights || []).length) {
    return html`<div class="page xl-page">${head}<div class="row"><${Spinner} /><span class="muted">Reading the cabinet's lights off the card…</span></div></div>`;
  }
  if (!s.available) {
    return html`<div class="page xl-page">${head}<${Empty} title="Nothing to light here" icon="info">${s.why}<//></div>`;
  }
  const probs = (s.problems || [])[si] || [];
  return html`<div class="page xl-page">
    ${head}
    <${Note}>${s.insider}<//>
    <div class="xl-cols">
      <${Card} title="Shows" cls="xl-list">
        <div class="list" role="listbox" aria-label="The project's expression light shows">
          ${shows.map((x, i) => {
            const sg = (s.songs || []).find((g) => g.slot === x.slot);
            return html`<button type="button" key=${i} role="option" aria-selected=${i === si} class=${cx("li xl-li", i === si && "sel")}
              onClick=${() => { setPick(i); setStockPick(null); clock.stop(); }}>
              <span class="xl-li-name ellip">${x.name}</span>
              <span class="small muted ellip">${sg ? sg.name : "no song"} · ${secs(x.length || 0)}</span>
              ${((s.problems || [])[i] || []).length ? html`<span class="warn-ink small">!</span>` : null}
            </button>`;
          })}
          ${!shows.length ? html`<div class="small muted">No shows yet. New show… makes one: pick its song, then its steps.</div>` : null}
        </div>
        ${(s.stock || []).length ? html`<div class="xl-stock-hd small muted">The game's own</div>
          <div class="list xl-stock" role="listbox" aria-label="The game's own expression light shows">
            ${s.stock.map((x) => html`<button type="button" key=${x.req} role="option" aria-selected=${!!stockPick && stockPick.req === x.req}
              class=${cx("li xl-li xl-li-game", stockPick && stockPick.req === x.req && "sel")} ...${tip(TIP.stock)}
              onClick=${() => { setStockPick({ req: x.req, set: (stockPick && stockPick.set) || "original" }); setSel(null); clock.stop(); }}>
              <span class="xl-li-name ellip">${stockName(s, x)}</span>
              <span class="small muted ellip">the game's · ${secs(x.ms)}</span>
            </button>`)}
          </div>` : s.stock_why ? html`<div class="small muted xl-stock-hd">${s.stock_why}</div>` : null}
        <div class="row xl-list-acts">
          <${Button} size="sm" kind="primary" icon="plus" iconRight="down" disabled=${shows.length >= s.max} title=${TIP.newShow} onClick=${newMenu}>New show<//>
          <${Button} size="sm" disabled=${!saved || !!gameShow} title=${TIP.dup} onClick=${() => call("lights.duplicate", si).then((i) => { if (i >= 0) setPick(i); })}>Duplicate<//>
          <${Button} size="sm" kind="ghost" icon="trash" disabled=${!saved || !!gameShow} title=${TIP.del} onClick=${() => call("lights.delete", si)} />
        </div>
      <//>
      ${show ? html`<${Card} title="The cabinet" cls="xl-stage">
        <${Cabinet} lights=${s.lights || []} show=${show} t=${clock.t} meta=${s.stock_meta} frames=${frames} />
        <audio ref=${audioRef} src=${src || undefined} preload="auto" />
        <div class="row xl-transport">
          <${Button} size="sm" kind="primary" icon=${clock.playing ? "pause" : "play"} title=${TIP.play}
            onClick=${() => (clock.playing ? clock.pause() : clock.play())}>${clock.playing ? "Pause" : "Play"}<//>
          <${Button} size="sm" kind="ghost" icon="stop" title=${TIP.stop} onClick=${clock.stop} />
          <input type="range" class="xl-scrub" min="0" max=${total} step="10" value=${Math.floor(clock.t)} ...${tip(TIP.scrub)}
            onInput=${(e) => clock.seek(Number(e.target.value))} />
          <span class="mono small xl-clock">${secs(clock.t)} / ${secs(total)}</span>
        </div>
        ${!song ? html`<span class="small muted">Pick the show's song to hear it with the lights.</span>` : null}
      <//>
      ${gameShow ? html`<${Card} title="The game's own show" cls="xl-edit">
        <div class="xl-grid">
          <span class="lbl">Song</span><span>${gameShow.name}${song ? "" : html` <span class="small muted">(not one of this project's songs)</span>`}</span>
          <span class="lbl">Show</span>
          <span class="row xl-inl">${["original", "remix"].map((k) => html`<${Button} key=${k} size="sm" kind=${stockPick.set === k ? "primary" : ""}
            title=${TIP.stockSet[k]} onClick=${() => setStockPick({ req: stockPick.req, set: k })}>${SET_WORD[k]}<//>`)}</span>
          <span class="lbl">Lasts</span><span>${secs(stockShow.ms)}</span>
          <span class="lbl"></span>
          <span class="row xl-inl"><${Button} size="sm" kind="primary" icon="plus" disabled=${shows.length >= s.max} title=${TIP.fromStock}
            onClick=${() => call("lights.from_stock", stockPick.req, stockPick.set).then((i) => { if (i >= 0) { setStockPick(null); setPick(i); clock.stop(); } })}>Make it a show of mine<//></span>
        </div>
        <${Note}>This is the game's own show, as the machine plays it with this song. It cannot be changed here: make it a show of yours to cut it, start it later, put it with another song or mix it with patterns of your own.<//>
        <div class="xl-tl">
          <div class="xl-tl-wave"><${Wave} peaks=${song && ((s.peaks || {})[String(song.slot)] || {}).v} /></div>
          ${LANES.map((k, lane) => html`<div key=${k} class="xl-tl-row">
            <span class="xl-tl-lbl small">${LANE_WORD[lane]}</span>
            <${Lane} s=${s} lane=${lane} steps=${show[k] || []} total=${total} sel=${null} t=${clock.t} onSel=${() => {}} onSeek=${clock.seek} />
          </div>`)}
        </div>
      <//>` : html`<${Card} title="Show" cls="xl-edit">
        <div class="xl-grid">
          <span class="lbl" ...${tip(TIP.name)}>Name</span>
          <${Field} sm value=${show.name} title=${TIP.name} onCommit=${(v) => edit((d) => { d.name = String(v).slice(0, (s.limits || {}).name || 31); })} />
          <span class="lbl" ...${tip(TIP.song)}>Plays with</span>
          <${Select} sm value=${show.slot == null ? "" : String(show.slot)} width=${320} title=${TIP.song}
            options=${[{ value: "", label: "(pick a song)" }, ...(s.songs || []).map((g) => ({ value: String(g.slot),
              label: `${g.name} (${secs(g.seconds * 1000)})${g.replaced ? " - replaced: " + g.file : ""}` }))]}
            onChange=${(v) => edit((d) => { d.slot = v === "" ? null : Number(v); })} />
          <span class="lbl"></span>
          <span class="row xl-inl">
            <${Button} size="sm" kind="primary" icon="music" iconRight="down" disabled=${!song || s.making} title=${TIP.auto}
              onClick=${(e) => openMenu(e.currentTarget, (s.styles || []).map((st) => ({ label: st.label,
                onClick: () => { clearTimeout(timer.current); setDraft(null); setSel(null); call("lights.auto_show", si, st.key); } })))}>
              ${s.making ? "Listening…" : "Make it from the song"}<//>
            ${s.making ? html`<${Spinner} />` : null}
          </span>
          ${s.auto_note ? html`<span class="lbl"></span><span class="small muted">${s.auto_note}</span>` : null}
          <span class="lbl"></span>
          <${Check} checked=${!!show.loop} label="Start again when its steps are over" title=${TIP.loop} onChange=${(v) => edit((d) => { d.loop = !!v; })} />
        </div>
        ${probs.map((p) => html`<${Note} kind="warn">${p}<//>`)}
        <div class="xl-tl">
          <div class="xl-tl-wave"><${Wave} peaks=${song && ((s.peaks || {})[String(song.slot)] || {}).v} /></div>
          ${LANES.map((k, lane) => html`<div key=${k} class="xl-tl-row">
            <span class="xl-tl-lbl small">${LANE_WORD[lane]}</span>
            <${Lane} s=${s} lane=${lane} steps=${show[k] || []} total=${total} sel=${sel} t=${clock.t}
              onSel=${(x) => { setSel(x); }} onSeek=${clock.seek} />
            <${Button} size="xs" kind="ghost" icon="plus" title=${TIP.addStep}
              disabled=${(show[k] || []).length >= (s.limits || {}).steps} onClick=${() => addStep(lane)} />
          </div>`)}
          <div class="row xl-tl-acts">
            <${Button} size="sm" icon="edit" disabled=${!sel} title=${TIP.split} onClick=${split}>Split at the playhead<//>
            <span class="small muted">${song ? `${song.name}: ${secs(songMs)}` : ""}</span>
          </div>
        </div>
        ${sel ? html`<${StepCard} s=${s} show=${show} sel=${sel} edit=${edit} />`
          : html`<span class="small muted">Press a step to change it, or + to add one.</span>`}
      <//>`}` : html`<${Card} title="The cabinet" cls="xl-stage"><${Cabinet} lights=${s.lights || []} show=${{ blades: [], speakers: [] }} t=${0} meta=${s.stock_meta} frames=${frames} /><//>`}
    </div>
  </div>`;
}
