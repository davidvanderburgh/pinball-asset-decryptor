// "Find originals…" on the Audio and Images tabs (PAD-443, DoomWalrus666): the files the
// picks on the tab were made from, found in a folder by how they sound or look
// (webui/find_originals.py, core/original_match.py).  For a project whose picks are copies
// off a built card, so the next Write converts the user's own files instead.  A window over
// the tab like the Video tab's "Best quality…": a search can take minutes and the tab stays
// usable.  One component for both tabs; *ns* says which tab's service it calls.

import { html, useEffect, useRef, useState, Button, Field, Table, Icon, Spinner, menuOpen, call, mediaUrl }
  from "../core/ui.js";

for (const href of ["/static/css/tabs/originals.css"]) {
  if (typeof document !== "undefined" && !document.querySelector(`link[href="${href}"]`)) {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    document.head.appendChild(l);
  }
}

const zoomOf = () => parseFloat(document.documentElement.style.zoom) || 1;

// One player for the window's ▶ buttons: the copy picked now and the file found, one at a time.
let player = null;
const stopPlayer = () => { if (player) { player.pause(); player = null; } };
function playFile(path) {
  stopPlayer();
  player = new Audio(mediaUrl(path));
  player.play().catch(() => {});
}

// a file's cell: a ▶ for a sound, a small picture for a picture, then its name
function FileCell({ sound, path, name, missing }) {
  if (!path) return html`<span class="muted">${missing || name}</span>`;
  return html`<span class="org-file">
    ${sound
      ? html`<button type="button" class="org-play" aria-label=${"Play " + name} title="Play"
          onClick=${(e) => { e.stopPropagation(); playFile(path); }}><${Icon} name="play" /></button>`
      : html`<span class="org-th"><img src=${mediaUrl(path)} alt="" loading="lazy" /></span>`}
    <span class="ellip">${name}</span>
  </span>`;
}

export function OriginalsWindow({ ns, o }) {
  const ref = useRef(null);
  // what is typed in the folder field, sent when Find is pressed
  const folder = useRef(o.folder || "");
  useEffect(() => { folder.current = o.folder || ""; }, [o.folder]);
  const [off, setOff] = useState({ x: 0, y: 0 });
  useEffect(() => { if (ref.current) ref.current.focus({ preventScroll: true }); }, []);
  useEffect(() => stopPlayer, []);
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
  const fn = (name) => ns + ".originals_" + name;
  function close() { call(fn("close")); }
  const onKey = (e) => { if (e.key === "Escape" && !menuOpen()) { e.stopPropagation(); close(); } };
  const sound = o.kind === "sound";
  const rows = o.rows || [];
  const cols = [
    { key: "use", label: "", width: "34px",
      render: (r) => (r.path ? html`<input type="checkbox" checked=${!!r.use} aria-label=${"Use the file found for " + r.name}
        onClick=${(e) => e.stopPropagation()} onChange=${(e) => call(fn("use_row"), r.rel, e.target.checked)} />` : null) },
    { key: "name", label: sound ? "Sound" : "Picture", width: "minmax(0,1fr)", titleOf: (r) => r.rel },
    { key: "now", label: "Picked now", width: "minmax(0,1fr)", titleOf: (r) => r.ref || r.now || undefined,
      render: (r) => html`<${FileCell} sound=${sound} path=${r.ref} name=${r.now} />` },
    { key: "file", label: "Your file", width: "minmax(0,1.2fr)", titleOf: (r) => r.path || undefined,
      render: (r) => html`<${FileCell} sound=${sound} path=${r.path} name=${r.file} missing="not found" />` },
    { key: "match", label: "Match", width: "64px" },
    { key: "info", label: sound ? "Format" : "Size", width: sound ? "128px" : "112px" },
    ...(sound ? [{ key: "len", label: "Length", width: "64px" }] : []),
    { key: "note", label: "", width: "minmax(0,.9fr)", titleOf: (r) => r.note || undefined,
      render: (r) => html`<span class="small muted">${r.note}</span>` },
  ];
  // a typed path counts even if the field never lost focus
  const find = async () => {
    if (!o.busy) await call(fn("set"), "folder", folder.current);
    call(fn("find"));
  };
  return html`<div class="modal wide org-win" ref=${ref} role="dialog" aria-modal="false"
      aria-label=${o.title} tabindex="-1" onKeyDown=${onKey}
      style=${`transform:translate(calc(-50% + ${off.x}px), calc(-50% + ${off.y}px))`}>
    <div class="hd org-hd" onMouseDown=${startDrag}><${Icon} name=${sound ? "audio" : "images"} cls="lg" /><span class="h2">${o.title}</span>
      <${Button} kind="ghost" size="sm" icon="x" title="Close" onClick=${close} /></div>
    <div class="bd">
      <p class="muted small" style="margin:0">${o.intro}</p>
      <div class="small">${o.summary}</div>
      <div class="row" style="gap:8px">
        <label class="lbl nw" for=${ns + "-org-folder"}>Your files:</label>
        <${Field} id=${ns + "-org-folder"} value=${o.folder} mono cls="grow" disabled=${o.busy}
          onChange=${(v) => { folder.current = v; }} onCommit=${(v) => call(fn("set"), "folder", v)} />
        <${Button} onClick=${() => call(fn("browse"))} disabled=${o.busy}>Browse…<//>
        <${Button} onClick=${find}>${o.busy ? "Stop" : "Find"}<//>
      </div>
      <div class="row small" style="gap:8px">${o.busy ? html`<${Spinner} />` : null}<span>${o.status}</span></div>
      <${Table} cls=${"org-tbl" + (sound ? "" : " org-pics")} columns=${cols} rows=${rows} rowKey=${(r) => r.rel}
        rowHeight=${sound ? 30 : 44}
        rowClass=${(r) => (!r.path ? "muted" : !r.sure ? "warn" : "")}
        onActivate=${(r) => r.path && call(fn("reveal"), r.rel)}
        empty=${html`<div class="small muted" style="padding:14px">${o.busy ? "" : "Nothing searched yet."}</div>`} />
    </div>
    <div class="ft">
      ${rows.length ? html`<${Button} kind="ghost" size="sm" onClick=${() => call(fn("use_all"), true)} disabled=${o.busy}>Tick all<//>
        <${Button} kind="ghost" size="sm" onClick=${() => call(fn("use_all"), false)} disabled=${o.busy}>Untick all<//>` : null}
      <span class="grow"></span>
      <${Button} onClick=${close}>Close<//>
      <${Button} kind="primary" onClick=${() => call(fn("apply"))} disabled=${o.busy || !o.can_apply}
        title="Use every ticked file as its slot's replacement. The next Write converts from it.">Use these files<//>
    </div>
  </div>`;
}
