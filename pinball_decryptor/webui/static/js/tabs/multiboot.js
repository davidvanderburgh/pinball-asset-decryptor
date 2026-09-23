// Multi-boot: several game images on one SD card (Stern Spike 2) or one
// install ISO (JJP), with a boot menu the machine shows at power-up.
//
// Everything this page shows is published by the Tk tab's own panel, run
// headless (webui/multiboot_panel.py); every button calls the same panel
// method its Tk widget did.  Status: docs/plans/web_ui_tabs/multiboot.md.

import { html, useEffect, useRef, useState, PageHead, Card, Button, Field, Select, Check, Table, Modal, Note, openMenu,
         menuOpen, InfoBadge, tip, Icon, mediaUrl, call, setField, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

export const css = true;

const NS = "multiboot";
const hex = (colors, k, dflt = "000000") => "#" + String((colors || {})[k] || dflt).replace(/^#/, "");
const noColon = (t) => String(t || "").replace(/:\s*$/, "");
// A dialog field's id names its store key, so Enter can send what is in the
// box before it presses OK (see okOnEnter).
const FID = "mb-f-";
const fid = (k) => FID + k;

// ------------------------------------------------- Tk's _Modal, on the page
// The dialogs take the GRAB, as Tk's did: a click on the dim area around one
// does nothing, and Escape belongs to the window on top (a message box or a
// file picker over the dialog answers its own).  Core Modal calls onClose()
// with no argument for Escape and for a click on the dim area, and with the
// click for its ✕.
function grabbed(cls, fn) {
  return (e) => {
    if (e) { fn(); return; }
    const ev = typeof window !== "undefined" ? window.event : null;
    if (ev && ev.type === "mousedown") return;
    const mine = document.querySelector(".modal." + cls);
    const scrims = document.querySelectorAll(".scrim");
    if (mine && scrims.length && mine.closest(".scrim") !== scrims[scrims.length - 1]) return;
    fn();
  };
}

// Return anywhere in the dialog is OK (Tk's top.bind("<Return>", ok)), and
// Start in Build / flash card.  A text box's value is sent first and OK
// waits for it, so what was just typed is what OK keeps.  Not on a button
// (Enter presses the button itself), a list, a colour well, or while one of
// the ▾ menus is open.
function okOnEnter(ok) {
  return async (e) => {
    if (e.key !== "Enter" || e.defaultPrevented || e.isComposing || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (menuOpen()) return;
    const t = e.target;
    if (!t || t.tagName !== "INPUT" || /^(color|file|button|submit|reset|image)$/i.test(t.type || "")) return;
    e.preventDefault();
    if (t.id && t.id.startsWith(FID) && !/^(checkbox|radio)$/i.test(t.type || "")) {
      await setField(NS, t.id.slice(FID.length), t.value, { flush: true });
    }
    ok();
  };
}

export default function MultibootTab() {
  const s = useNs(NS);
  const w = s.w || {};
  const busy = !!s.busy;

  // Tk's <Map> / <Unmap>: the preview's sound plays only while this tab is
  // on screen (and not while the window is minimised).
  useEffect(() => {
    const say = () => call("multiboot.visible", !document.hidden);
    say();
    document.addEventListener("visibilitychange", say);
    return () => {
      document.removeEventListener("visibilitychange", say);
      call("multiboot.visible", false);
    };
  }, []);

  const jjp = w.platform === "jjp";
  const sub = jjp
    ? "Two game installs on one USB install stick, with a boot menu the machine shows on power-up."
    : "Several game images on one SD card, with a boot menu the machine shows on power-up.";

  if (s.broken) {
    return html`<div class="page mb-page">
      <${PageHead} title="Multi-boot" sub=${sub} />
      <${Note} kind="err">${s.broken}<//>
    </div>`;
  }

  return html`<div class="page mb-page">
    <${PageHead} title="Multi-boot" sub=${sub}>
      <div class="phases mb-checks" role="list" aria-label="Status">
        ${(s.checks || []).map((c) => html`<span role="listitem" tabindex="0"
          class=${cx("phase", c.state === "ok" && "done", c.state === "now" && "now", c.state === "bad" && "mb-bad")}
          ...${tip(c.detail)}>${c.label}</span>`)}
      </div>
      ${w.about ? html`<${InfoBadge} text=${w.about} />` : null}
    <//>
    ${s.alarm ? html`<div class="mb-alarm" role="alert" ...${tip(s.alarm.full)}>
      <span class="body-text">${s.alarm.head}</span></div>` : null}
    <div class="mb-cols">
      <${MenuCard} s=${s} w=${w} busy=${busy} />
      <div class="stack mb-right">
        <${ImagesCard} s=${s} w=${w} busy=${busy} />
        <${CardCard} s=${s} w=${w} busy=${busy} />
      </div>
    </div>
    ${s.dlg === "edit" && s.ed ? html`<${EditDialog} s=${s} w=${w} />` : null}
    ${s.dlg === "menu" && s.md ? html`<${MenuDialog} s=${s} w=${w} />` : null}
    ${s.dlg === "build" && s.bf ? html`<${BuildDialog} s=${s} w=${w} />` : null}
    ${s.dlg === "cardpick" && s.cp ? html`<${CardPickDialog} cp=${s.cp} />` : null}
  </div>`;
}

// ------------------------------------------------------------ boot menu
// THE PICTURE, FULL SIZE: the selector's own frame at its native size (or
// as large as the window allows), live - the flippers and Select below it
// drive the same menu - so what the machine will show can be checked at the
// size it will be shown.
function FullView({ s, w, busy, onClose }) {
  const pv = s.preview || {};
  const f = pv.frame;
  const note = f ? `The selector's own frame, ${f.w} x ${f.h}: this is what the machine shows.`
    : "This is a sketch drawn from the form. Draw it with the selector to see exactly what the machine shows.";
  const footer = html`<span class="small muted grow">${note}</span>
    ${f ? null : html`<${Button} kind="primary" disabled=${busy} onClick=${() => call("multiboot.redraw")}>Draw it with the selector<//>`}
    <${Button} onClick=${onClose}>Close<//>`;
  return html`<${Modal} title="Boot menu, full size" onClose=${onClose} xwide cls="mb-dlg mb-fullview" footer=${footer}>
    <div class="mb-fullbox"><${Screen} pv=${pv} tipText="" busy=${busy} openFull=${() => {}} full /></div>
    <div class="row mb-flips" onKeyDown=${flipKeys}>
      <${Button} size="sm" disabled=${!s.flippers} title=${w.flipper_tip} onClick=${() => call("multiboot.flip", -1)}>◂ Left flipper<//>
      <${Button} size="sm" title=${w.select_tip} onClick=${() => call("multiboot.press_select")}>Select<//>
      <${Button} size="sm" disabled=${!s.flippers} title=${w.flipper_tip} onClick=${() => call("multiboot.flip", 1)}>Right flipper ▸<//>
    </div>
  <//>`;
}

function MenuCard({ s, w, busy }) {
  const pv = s.preview || {};
  const [full, setFull] = useState(false);
  const groups = s.summary_groups;
  const footer = html`<${Button} onClick=${() => call("multiboot.menu_settings")} disabled=${busy}>Menu settings…<//>
    <span class="small muted grow mb-foot-hint">Select in the preview plays the confirm sound and holds the LOADING frame, as the machine will.</span>`;
  return html`<${Card} cls="mb-menu" title="Boot menu" sub="drawn by the selector itself, redrawn on every change" footer=${footer}>
    <${Screen} pv=${pv} tipText=${w.preview_tip} busy=${busy} openFull=${() => setFull(true)} />
    ${full ? html`<${FullView} s=${s} w=${w} busy=${busy} onClose=${() => setFull(false)} />` : null}
    <div class="row wrap mb-strip">
      <div class="row mb-flips" onKeyDown=${flipKeys}>
        <${Button} size="sm" disabled=${!s.flippers} title=${w.flipper_tip} onClick=${() => call("multiboot.flip", -1)}>◂ Left flipper<//>
        <${Button} size="sm" title=${w.select_tip} onClick=${() => call("multiboot.press_select")}>Select<//>
        <${Button} size="sm" disabled=${!s.flippers} title=${w.flipper_tip} onClick=${() => call("multiboot.flip", 1)}>Right flipper ▸<//>
      </div>
      <span class="grow"></span>
      <div class="row mb-vol" ...${tip(w.volume_tip)}>
        <label class="lbl" for="mb-vol">Volume</label>
        <input type="range" id="mb-vol" min="0" max="100" step="1" value=${Math.round(Number(s.pv_gain ?? 100))}
          onInput=${(e) => setField(NS, "pv_gain", Number(e.target.value), { delay: 120 })} />
        <${Check} ns=${NS} k="pv_mute" checked=${s.pv_mute} label="Mute" />
      </div>
    </div>
    ${pv.video || pv.audio || pv.caption ? html`<div class="row mb-readout small">
      ${pv.video ? html`<span class="muted nw" ...${tip(w.media_tip)}>Video: ${pv.video}</span>` : null}
      ${pv.audio ? html`<span class="muted nw" ...${tip(w.media_tip)}>Audio: ${pv.audio}</span>` : null}
      ${pv.caption ? html`<span class=${cx("ellip grow", pv.error ? "err-ink" : "dim")} ...${tip(pv.caption)}>${pv.caption}</span>` : null}
    </div>` : null}
    ${groups ? html`<div class="kv mb-kv" ...${tip(s.summary)}>
      ${groups.map(([k, v]) => html`<span class="k">${k}</span><span class="dim">${v}</span>`)}
    </div>` : html`<div class="small dim" ...${tip(s.summary)}>${s.summary}</div>`}
  <//>`;
}

// The arrow keys are the flippers on the picture and on the two flipper
// buttons, and nowhere else (Tk binds <Left>/<Right> on exactly those three:
// the table walks its rows with them, a text box its characters).
const arrowFlip = (e) => {
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); call("multiboot.flip", -1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); call("multiboot.flip", 1); }
};
function flipKeys(e) {
  const box = e.currentTarget;
  if (e.target === box.firstElementChild || e.target === box.lastElementChild) arrowFlip(e);
}

// The preview's right-click (David, 2026-09-23): draw it with the real
// selector now, see it full size, or save the selector's own picture.
function previewMenu(e, pv, busy, openFull) {
  e.preventDefault();
  openMenu({ x: e.clientX, y: e.clientY }, [
    { label: "Draw it with the selector now", disabled: busy, onClick: () => call("multiboot.redraw") },
    { label: "Full size…", onClick: openFull },
    { sep: true },
    { label: pv.frame ? "Save picture as…" : "Save picture as…  (the selector has not drawn it yet)",
      disabled: !pv.frame, onClick: () => call("multiboot.save_picture") },
  ]);
}

function Screen({ pv, tipText, busy, openFull, full }) {
  const onKey = arrowFlip;
  const f = pv.frame;
  const ar = f ? `${f.w} / ${f.h}` : "1360 / 768";
  let inner;
  if (f) {
    inner = html`<div class="mb-frame">
      <img src=${mediaUrl(f.src)} alt="The boot menu, as the selector drew it" draggable="false" />
      ${(pv.clips || []).map((c) => html`<img class="mb-clip" key=${c.i} alt="" draggable="false"
        src=${mediaUrl(c.src) + "&v=" + c.v}
        style=${`left:${(100 * c.x) / f.w}%;top:${(100 * c.y) / f.h}%;width:${(100 * c.w) / f.w}%;height:${(100 * c.h) / f.h}%`} />`)}
      ${pv.black ? html`<div class="mb-black">${pv.black.src ? html`<img src=${mediaUrl(pv.black.src)} alt="" />` : null}</div>` : null}
    </div>`;
  } else if (pv.sketch) {
    inner = html`<${Sketch} sk=${pv.sketch} hl=${pv.hl} black=${pv.black} />`;
  } else {
    inner = html`<div class="mb-placeholder">${pv.placeholder || ""}</div>`;
  }
  const size = full && f ? `;width:min(${f.w}px, 100%);max-width:calc((100vh - 240px) * ${f.w} / ${f.h})` : "";
  return html`<div class=${"thumb mb-screen" + (full ? " mb-full" : "")} style=${`aspect-ratio:${ar}${size}`} tabindex="0" onKeyDown=${onKey}
    aria-label="Boot menu preview" onContextMenu=${(e) => previewMenu(e, pv, busy, openFull)}
    onDblClick=${full ? null : openFull} ...${full ? {} : tip(tipText)}>${inner}</div>`;
}

// The menu drawn from the form, in its own colours, until the selector has
// drawn it (the design's picture of the machine's screen).
function Sketch({ sk, hl, black }) {
  const col = (k) => hex(sk.colors, k);
  const cards = sk.cards || [];
  return html`<div class="mb-sketch" style=${`background:${col("background")}`}>
    <div class="mb-sk-head" style=${`color:${col("heading")}`}>${sk.heading || " "}</div>
    <div class="mb-sk-cards" style=${`grid-template-columns:repeat(${Math.max(1, cards.length)},minmax(0,22cqi))`}>
      ${cards.map((cd) => {
        const on = cd.i === hl;
        return html`<div class="mb-sk-card" key=${cd.i}
          style=${`background:${col(on ? "card_hl" : "card")};border-color:${col(on ? "frame_hl" : "frame")}`}>
          <span class="t" style=${`color:${col(on ? "title_hl" : "title")}`}>${cd.title}</span>
          ${cd.sub ? html`<span class="s" style=${`color:${col(on ? "subtitle_hl" : "subtitle")}`}>${cd.sub}</span>` : null}
        </div>`;
      })}
    </div>
    <div class="mb-sk-foot" style=${`color:${col("footer")}`}>
      ${sk.counter ? html`<span>${sk.counter}</span>` : null}
      <span>${sk.footer}</span>
      <span style=${`color:${col("countdown")}`}>${sk.countdown}</span>
    </div>
    <span class="mb-sk-tag">sketch · right-click to draw it with the selector</span>
    ${black ? html`<div class="mb-black"></div>` : null}
  </div>`;
}

// --------------------------------------------------------------- images
function ImagesCard({ s, w, busy }) {
  const rows = s.rows || [];
  const locked = !!s.locked;
  const addMenu = (anchor) => openMenu(anchor, (s.add_choices || []).map((ch) => ({
    label: ch.label, disabled: !ch.enabled || locked,
    onClick: () => call("multiboot.add_choice", ch.attr),
  })));
  const rowMenu = (r, e, at) => {
    const hasRow = r != null;
    openMenu(at || { x: e.clientX, y: e.clientY }, (s.list_actions || []).map((a) => a.sep ? { sep: true } : {
      label: a.label, disabled: busy || (a.row && !hasRow),
      onClick: () => call("multiboot.list_action", a.attr, hasRow ? r.i : null),
    }));
  };
  // The menu key / Shift+F10 on the focused table, or a right-click on its
  // empty space, pops the same menu over the SELECTED row (ImageTable's
  // _canvas_context).  A row's own right-click got there first.
  const tableMenu = (e) => {
    if (e.defaultPrevented) return;
    e.preventDefault();
    const r = s.sel != null ? rows[s.sel] : null;
    const el = box.current && box.current.querySelector(".tr.sel:not(.th)");
    const sc = box.current && box.current.querySelector(".scroller");
    let at = null;
    if (e.button !== 2) {
      const rc = (el || sc) ? (el || sc).getBoundingClientRect() : null;
      if (rc) at = el ? { x: rc.left + 40, y: rc.bottom } : { x: rc.left + 20, y: rc.top + 20 };
    }
    rowMenu(r || null, e, at);
  };
  const act = (e, r, kind) => { e.stopPropagation(); call("multiboot.row_action", r.i, kind); };
  const tips = w.row_actions || {};
  // A narrow card (a small window, or zoomed in) keeps every fact in fewer
  // columns: the subtitle under the title, music and confirm in one cell.
  const box = useRef(null);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setNarrow(el.clientWidth < 640));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const mv = { key: "mv", label: "", width: "46px", render: (r) => html`<span class="mb-mv">
        <${Button} kind="ghost" size="xs" icon="up" cls="mb-ic mb-go" disabled=${!r.up || locked} title=${tips.up} label="Move up" onClick=${(e) => act(e, r, "up")} />
        <${Button} kind="ghost" size="xs" icon="down" cls="mb-ic mb-go" disabled=${!r.down || locked} title=${tips.down} label="Move down" onClick=${(e) => act(e, r, "down")} />
      </span>` };
  // (core's Table stretches a last column given in plain px; this one stays
  // the width of its two buttons and the title takes the room)
  const acts = { key: "act", label: "", width: "minmax(46px,46px)", render: (r) => html`<span class="mb-acts">
        <${Button} kind="ghost" size="xs" icon="edit" cls="mb-ic mb-go" title=${tips.edit} label="Edit" onClick=${(e) => act(e, r, "edit")} />
        <${Button} kind="ghost" size="xs" icon="x" cls="mb-ic mb-del" disabled=${locked} title=${tips.del} label="Remove" onClick=${(e) => act(e, r, "del")} />
      </span>` };
  const title = (r) => html`<b>${r.title}</b>${r.suffix ? html` <span class=${r.warn ? "warn-ink" : "dim"}>${r.suffix}</span>` : null}`;
  // The design's widths: the title takes what is left, the short facts keep
  // narrow fixed columns (each cell's tooltip has its whole text).
  const cols = narrow ? [
    mv,
    { key: "title", label: "Title / Subtitle", width: "minmax(0,1fr)", titleOf: (r) => r.full + (r.sub ? " · " + r.sub : ""),
      render: (r) => html`${title(r)}${r.sub ? html`<span class="dim"> · ${r.sub}</span>` : null}` },
    { key: "media", label: "Picture", width: "60px", cls: "dim", titleOf: (r) => r.media },
    { key: "music", label: "Sounds", title: "Music · Confirm sound", width: "84px", cls: "dim",
      titleOf: (r) => "Music: " + r.music + " · Confirm: " + r.sound, render: (r) => `${r.music} · ${r.sound}` },
    { key: "code", label: "Code", width: "52px", cls: "mono" },
    acts,
  ] : [
    mv,
    { key: "title", label: "Title", width: "minmax(0,1fr)", titleOf: (r) => r.full, render: title },
    { key: "sub", label: "Subtitle", width: "64px", cls: "dim", titleOf: (r) => r.sub },
    { key: "media", label: "Picture", width: "60px", cls: "dim", titleOf: (r) => r.media },
    { key: "music", label: "Music", width: "48px", cls: "dim", titleOf: (r) => r.music },
    { key: "sound", label: "Confirm", width: "56px", cls: "dim", titleOf: (r) => r.sound },
    { key: "code", label: "Code", width: "52px", cls: "mono" },
    acts,
  ];
  const n = rows.length;
  // room for every row and one more (up to eight), so a selected row is
  // never scrolled under the sticky header
  const h = 32 + 34 * Math.max(3, Math.min(n + 1, 9));
  const nouns = w.out_noun === "card" ? "card" : (w.out_noun || "card");
  const head = html`<span class="h2">Images on the ${nouns}</span>
    <span class="muted small mb-hint" ...${tip(w.list_tip)}>▲ ▼ reorder · the first is the primary the machine falls back to</span>
    <span class="sp"></span>
    <${Button} kind="primary" size="sm" iconRight="down" disabled=${locked} onClick=${(e) => addMenu(e.currentTarget)}>${w.add_text || "Add image or random…"}<//>`;
  const empty = html`<button type="button" class="mb-addrow" disabled=${locked} onClick=${(e) => addMenu(e.currentTarget)} ...${tip(w.list_tip)}>
    <${Icon} name="plus" /><span>${w.add_text || "Add image or random…"}</span></button>`;
  return html`<${Card} cls="mb-images" head=${head} bodyCls="flush mb-images-bd">
    <div ref=${box} class="mb-tablebox" onContextMenu=${tableMenu}>
    <${Table} key=${narrow ? "n" : "w"} cls="mb-table" columns=${cols} rows=${rows} rowKey=${(r) => r.i} selected=${s.sel}
      style=${`height:${h}px`} empty=${empty}
      onSelect=${(r, i, e) => (e && e.type === "keydown" ? call("multiboot.select", r.i) : call("multiboot.cell_clicked", r.i))}
      onActivate=${(r) => call("multiboot.edit", r.i)}
      onContext=${(r, i, e) => rowMenu(r, e)} />
    </div>
    <div class="mb-rowline small muted ellip" onContextMenu=${(e) => { e.preventDefault(); rowMenu(null, e); }} ...${tip(s.row_tip)}>${s.row_line}</div>
  <//>`;
}

// ----------------------------------------------------------------- card
function CardCard({ s, w, busy }) {
  const mode = s.build_mode || "build";
  const onKey = (e) => { if (e.key === "Enter" && e.target && e.target.tagName === "INPUT") call("multiboot.path_enter", e.target.value); };
  const footer = html`
    <${Button} kind=${mode === "build" ? "primary" : "danger solid"} size="big" icon=${mode === "build" ? "multiboot" : "stop"}
      disabled=${mode === "cancelling"} title=${mode === "build" ? w.build_tip : w.cancel_tip}
      onClick=${() => call("multiboot.build_flash")}>${mode === "build" ? (w.build_text || "Build / flash card…") : mode === "cancel" ? w.cancel_text : w.cancelling_text}<//>
    <${Button} disabled=${busy} onClick=${() => call("multiboot.run_emulator")}>Run in emulator<//>
    ${w.extract ? html`<${Button} kind="ghost" disabled=${!s.recover_live} title=${w.recover_tip} onClick=${() => call("multiboot.recover")}>Recover images…<//>` : null}`;
  const bad = s.card_state === "bad";
  const noun = String(w.out_noun || "card");
  return html`<${Card} cls="mb-card" title=${noun.charAt(0).toUpperCase() + noun.slice(1)} footer=${footer}>
    <div class="stack mb-pathbox">
      <label class="lbl" for="mb-card">${noColon(w.out_label)}</label>
      <div class="row wrap mb-pathrow">
        <div class="grow mb-path" onKeyDown=${onKey} onFocusIn=${() => call("multiboot.path_focus")}>
          <${Field} id="mb-card" ns=${NS} k="card" value=${s.card} mono title=${w.path_tip} bad=${bad} />
        </div>
        <div class="row mb-pathbtns">
          ${w.read_card ? html`<${Button} disabled=${busy} title=${w.from_card_tip} onClick=${() => call("multiboot.from_card")}>From SD card…<//>` : null}
          <${Button} disabled=${busy} onClick=${() => call("multiboot.browse")}>Browse…<//>
          <${Button} kind="ghost" disabled=${busy} title=${w.new_tip} onClick=${() => call("multiboot.new_card")}>New card<//>
        </div>
      </div>
      <span class=${cx("small", bad ? "err-ink" : "muted")}>${s.card_detail || "Enter reads a card at that path; a new name is where the card is written."}</span>
    </div>
    <${SizeStrip} s=${s} w=${w} />
  <//>`;
}

function SizeStrip({ s, w }) {
  const z = s.size || {};
  const again = () => call("multiboot.remeasure");
  return html`<div class="row wrap mb-size">
    <div class="row mb-size-head" onClick=${again} ...${tip(z.tip)}>
      <span class="lbl nw">${noColon(w.medium_needed)}</span>
      <b class=${cx("nw", z.over && "err-ink")}>${z.head}</b>
    </div>
    <div class=${cx("mb-bar", z.measuring && !z.frac && "thinking")} onClick=${again} role="img"
      aria-label=${z.known ? z.detail : "Not measured"} ...${tip(z.tip)}>
      ${z.known ? (z.bands || []).map((b, i) => html`<i key=${i} class=${"b-" + b.kind} style=${`width:${b.pct}%`}>
        ${b.saved_pct ? html`<em style=${`width:${b.saved_pct}%`}></em>` : null}</i>`) : null}
      ${z.known && z.cap_pct != null ? html`<i class="b-over" style=${`left:${z.cap_pct}%`}></i>` : null}
      ${z.measuring && z.frac ? html`<i class="b-prog" style=${`width:${z.frac * 100}%`}></i>` : null}
    </div>
    ${z.detail ? html`<span class=${cx("small mb-size-detail", z.over ? "err-ink" : "dim")} ...${tip(z.why)}>${z.detail}</span>` : null}
    ${w.compact ? html`<${Check} ns=${NS} k="compact" checked=${s.compact} disabled=${s.compact_locked} label="Compact build" title=${s.compact_tip} />` : null}
  </div>`;
}

// --------------------------------------------------------- shared pieces
function SoundRow({ label, field, value, words, used, playTip }) {
  const choose = (e) => openMenu(e.currentTarget, [
    ...(words || []).map((v) => ({ label: v, onClick: () => setField(NS, field, v, { flush: true }) })),
    ...((used || []).length ? [{ sep: true }, ...used.map((u) => ({ label: u.label, title: u.path,
      onClick: () => setField(NS, field, u.path, { flush: true }) }))] : []),
  ], { align: "right" });
  return html`<label class="k" for=${fid(field)}>${label}</label>
    <div class="row mb-sound">
      <${Field} id=${fid(field)} ns=${NS} k=${field} value=${value} cls="grow" mono
        suffix=${html`<button type="button" class="mb-drop" aria-label=${"Choose the " + noColon(label).toLowerCase()} onClick=${choose}>▾</button>`} />
      <${Button} onClick=${() => call("multiboot.sound_browse", field)}>Browse…<//>
      <${Button} icon="play" title=${playTip} onClick=${() => call("multiboot.play", field)}>Play<//>
    </div>`;
}

function Box({ legend, children, cls = "" }) {
  return html`<fieldset class=${cx("mb-box", cls)}><legend>${legend}</legend>${children}</fieldset>`;
}

// ----------------------------------------------------------- Edit image…
function EditDialog({ s, w }) {
  const ed = s.ed;
  const cancel = () => call("multiboot.edit_cancel");
  const ok = () => call("multiboot.edit_ok");
  const fileKey = ed.file_kind === "video" ? "ed_video" : "ed_picture";
  const footer = html`<${Button} kind="primary" onClick=${ok}>OK<//><${Button} onClick=${cancel}>Cancel<//>`;
  return html`<${Modal} title=${ed.title} onClose=${grabbed("mb-dlg-edit", cancel)} xwide cls="mb-dlg mb-dlg-edit" footer=${footer}>
    <div class="mb-ed" onKeyDown=${okOnEnter(ok)}>
      <div class="stack mb-ed-main">
        <span class="small muted mb-src">${ed.source}</span>
        <div class="kv mb-kv2">
          <label class="k" for=${fid("ed_title")}>Title:</label>
          <${Field} id=${fid("ed_title")} ns=${NS} k="ed_title" value=${s.ed_title} autoFocus />
          <label class="k" for=${fid("ed_sub")}>Subtitle:</label>
          <${Field} id=${fid("ed_sub")} ns=${NS} k="ed_sub" value=${s.ed_sub} />
        </div>
        <${Box} legend="Picture">
          <div class="kv mb-kv2">
            <span class="k">Shows:</span>
            <${Select} value=${ed.kind} options=${ed.kinds} ns=${NS} k="ed_media" />
            ${ed.file_kind ? html`<label class="k" for=${fid(fileKey)}>${ed.file_label}</label>
              <div class="row">
                <${Field} id=${fid(fileKey)} ns=${NS} k=${fileKey} value=${s[fileKey]} mono cls="grow" disabled=${!ed.file_live} />
                <${Button} onClick=${() => call("multiboot.edit_browse", ed.file_kind)}>Browse…<//>
              </div>` : null}
          </div>
          ${ed.note ? html`<span class="small muted">${ed.note}</span>` : null}
        <//>
        ${ed.group ? html`<${Box} legend="How it picks">
          <div class="stack mb-rolls">
            ${ed.rolls.map((r) => html`<label class="chk wrap-ok"><input type="radio" name="mb-roll" value=${r.value}
                checked=${s.ed_roll === r.value} onChange=${(e) => e.target.checked && setField(NS, "ed_roll", r.value, { flush: true })} />
              <span>${r.label}</span></label>`)}
            <div class="mb-indent"><${Check} ns=${NS} k="ed_roll_norepeat" checked=${s.ed_roll_norepeat} disabled=${ed.roll_locked} label=${ed.roll_repeat_label} /></div>
          </div>
          <span class="small muted">${ed.roll_note}</span>
        <//>` : null}
        <${Box} legend="Sounds">
          <div class="kv mb-kv2">
            <${SoundRow} label="Music:" field="ed_music" value=${s.ed_music} words=${ed.music_words} used=${ed.used} playTip=${w.play_tip} />
            <${SoundRow} label="Confirm sound:" field="ed_confirm" value=${s.ed_confirm} words=${ed.confirm_words} used=${ed.used} playTip=${w.play_tip} />
            <span></span><span class="small dim">${ed.confirm_note}</span>
          </div>
          <span class="small muted">${ed.sounds_note}</span>
        <//>
      </div>
      <${Box} legend="Preview" cls="mb-ed-pv"><${CardPreview} card=${ed.card} /><//>
    </div>
  <//>`;
}

function CardPreview({ card }) {
  const col = (k, d) => hex(card.colors, k, d);
  return html`<div class="mb-cardpv" style=${`background:${col("background", "0b0e13")}`}>
      <div class="mb-cardpv-card" style=${`background:${col("card_hl", "263041")};border-color:${col("frame_hl", "ffc42d")}`}>
        <div class="mb-cardpv-art" style=${card.img ? "" : `border:1px dashed ${col("label", "5d6673")}`}>
          ${card.img ? html`<img src=${mediaUrl(card.img)} alt="" />` : null}
        </div>
        <span class="t" style=${`color:${col("title_hl", "ffffff")}`}>${(card.title || "").trim() || "(no title)"}</span>
        <span class="s" style=${`color:${col("subtitle_hl", "d6dce4")}`}>${(card.sub || "").trim()}</span>
      </div>
    </div>
    <span class="small muted">${card.note}</span>`;
}

// --------------------------------------------------------- Menu settings…
function MenuDialog({ s, w }) {
  const md = s.md;
  const cancel = () => call("multiboot.menu_cancel");
  const ok = () => call("multiboot.menu_ok");
  const footer = html`<${Button} kind="primary" onClick=${ok}>OK<//><${Button} onClick=${cancel}>Cancel<//>`;
  // Tk's three Spinboxes: 0 to the platform's volume cap, 0-600 s, and 0 to
  // the last image (they step with the arrows; a typed value is kept as typed)
  const num = { type: "number", min: 0, step: 1, width: 90 };
  return html`<${Modal} title="Menu settings" onClose=${grabbed("mb-dlg-menu", cancel)} wide cls="mb-dlg mb-dlg-menu" footer=${footer}>
    <div class="stack mb-md" onKeyDown=${okOnEnter(ok)}>
    <${Box} legend="Sounds">
      <div class="kv mb-kv2">
        <${SoundRow} label="Move sound:" field="move" value=${s.move} words=${md.sound_words} used=${md.used} playTip=${w.play_tip} />
        <${SoundRow} label="Confirm sound:" field="confirm" value=${s.confirm} words=${md.sound_words} used=${md.used} playTip=${w.play_tip} />
        <label class="k" for=${fid("volume")}>Volume:</label>
        <div class="row"><${Field} id=${fid("volume")} ns=${NS} k="volume" value=${s.volume} ...${num} max=${w.volume_max} /><span class="small muted">0-${w.volume_max}</span></div>
      </div>
      ${w.machine_volume ? html`<${Check} ns=${NS} k="machine_vol" checked=${s.machine_vol} wrap
        label="On the machine, play at its own volume setting (recommended)" />` : null}
      <span class="small muted">${md.sounds_note}</span>
    <//>
    <${Box} legend="Look">
      <div class="kv mb-kv2">
        <label class="k" for=${fid("heading")}>Heading:</label>
        <${Field} id=${fid("heading")} ns=${NS} k="heading" value=${s.heading} />
        <span></span><span class="small muted">Across the top of the menu. Leave it empty for no heading at all.</span>
      </div>
      <${Check} ns=${NS} k="same_text" checked=${s.same_text} wrap label="Same text size on every card (a long name is not shrunk on its own)" />
      <${Check} ns=${NS} k="counter" checked=${s.counter} wrap label="Count the cards under them (the “<  3 / 7  >” line; five cards or more)" />
      <${Check} ns=${NS} k="footer_on" checked=${s.footer_on} wrap label="Show the instructions under the cards (the line naming the buttons)" />
      <div class="kv mb-kv2">
        <label class="k" for=${fid("footer")}>Instructions:</label>
        <${Field} id=${fid("footer")} ns=${NS} k="footer" value=${s.footer} disabled=${!s.footer_on} placeholder="the menu's own words" />
        <span></span><span class="small muted">${md.footer_example}</span>
      </div>
      <div class="kv mb-kv2">
        <span class="k">Theme:</span>
        <${Select} value=${md.theme} options=${md.themes} width=${220} title=${md.about} onChange=${(v) => call("multiboot.pick_theme", v)} />
      </div>
      <div class="mb-colors">
        ${md.colors.map((c) => html`<div class="mb-color">
          <label class=${cx("mb-swatch", !c.ok && "bad", !md.custom && "ro")} style=${`background:${c.ok ? "#" + c.hex : "var(--err)"}`}
            ...${tip(md.custom ? "Pick the " + c.label.toLowerCase() + " colour" : "")}>
            <input type="color" value=${"#" + (c.hex || "000000")} disabled=${!md.custom}
              aria-label=${c.label + " colour"}
              onInput=${(e) => call("multiboot.set_color", c.role, e.target.value)} />
          </label>
          <span class="small mb-color-lbl">${c.label}:</span>
          <${Field} id=${fid("color_" + c.role)} sm mono ns=${NS} k=${"color_" + c.role} value=${s["color_" + c.role]} width=${86} disabled=${!md.custom} bad=${!c.ok} />
        </div>`)}
      </div>
      <span class="small muted">${md.colors_note}</span>
    <//>
    <${Box} legend="At power-up">
      <div class="kv mb-kv2">
        <label class="k" for=${fid("timeout")}>Countdown (s):</label>
        <div class="row"><${Field} id=${fid("timeout")} ns=${NS} k="timeout" value=${s.timeout} ...${num} max=${600} /><span class="small muted">0 = wait for START</span></div>
        <label class="k" for=${fid("countdown_word")}>Countdown says:</label>
        <div class="row wrap"><${Field} id=${fid("countdown_word")} ns=${NS} k="countdown_word" value=${s.countdown_word} width=${180} /><span class="small muted">${md.example}</span></div>
        <label class="k" for=${fid("default")}>Default image:</label>
        <div class="row wrap"><${Field} id=${fid("default")} ns=${NS} k="default" value=${s.default} ...${num} max=${md.default_max} />
          <span class="small muted">highlighted at power-up (the last choice wins once one was made)</span></div>
      </div>
    <//>
    </div>
  <//>`;
}

// ------------------------------------------------------ Build / flash card
function BuildDialog({ s, w }) {
  const bf = s.bf;
  const cancel = () => call("multiboot.build_cancel");
  const canFlash = bf.can_write || bf.have_card;
  const start = () => call("multiboot.build_start");
  // Return is Start (Tk relabels the _Modal's OK), live only with a tick on
  const onEnter = okOnEnter(() => { if (bf.write || bf.flash) start(); });
  const footer = html`<${Button} kind="primary" disabled=${!(bf.write || bf.flash)} onClick=${start}>Start<//>
    <${Button} onClick=${cancel}>Cancel<//>`;
  return html`<${Modal} title="Build / flash card" onClose=${grabbed("mb-dlg-build", cancel)} cls="mb-dlg mb-dlg-build" footer=${footer}>
    <div class="stack mb-md" onKeyDown=${onEnter}>
    <${Box} legend=${"Write the " + (w.out_noun || "card")}>
      <${Check} checked=${bf.write} disabled=${!bf.can_write} wrap label=${bf.write_label}
        onChange=${(v) => call("multiboot.build_tick", "write", v)} />
      <p class="small muted mb-indent mb-p">${bf.write_detail}</p>
    <//>
    <${Box} legend=${w.flash_frame}>
      <${Check} checked=${bf.flash} disabled=${!canFlash} wrap label=${w.flash_tick}
        onChange=${(v) => call("multiboot.build_tick", "flash", v)} />
      <p class="small muted mb-indent mb-p wrap">${w.flash_detail}</p>
      ${!canFlash ? html`<p class="small muted mb-indent mb-p">There is no finished card to flash yet - build one first.</p>` : null}
    <//>
    </div>
  <//>`;
}

// ------------------------------------------------------ Read an SD card
function CardPickDialog({ cp }) {
  const cancel = () => call("multiboot.cardpick_cancel");
  const footer = html`<${Button} onClick=${() => call("multiboot.cardpick_refresh")}>Refresh<//>
    <${Button} kind="primary" disabled=${cp.looking || !cp.drives.length} onClick=${() => call("multiboot.cardpick_read")}>Read<//>
    <${Button} onClick=${cancel}>Cancel<//>`;
  return html`<${Modal} title="Read an SD card" onClose=${grabbed("mb-dlg-cardpick", cancel)} cls="mb-dlg mb-dlg-cardpick" footer=${footer}>
    <div class="kv mb-kv2">
      <span class="k">SD card:</span>
      ${cp.looking ? html`<span class="dim">Looking for cards…</span>`
        : cp.drives.length ? html`<${Select} value=${String(cp.picked ?? 0)}
            options=${cp.drives.map((d, i) => ({ value: String(i), label: d }))}
            onChange=${(v) => call("multiboot.cardpick_pick", Number(v))} />`
        : html`<span class="dim">No SD card found - connect the card and press Refresh</span>`}
      ${cp.why ? html`<span></span><span class="small muted">${cp.why}</span>` : null}
      <span class="k">Read:</span>
      <div class="stack">
        ${[["menu", cp.menu_text], ["whole", cp.whole_text]].map(([v, label]) => html`<label class="chk wrap-ok">
          <input type="radio" name="mb-cp-mode" value=${v} checked=${cp.mode === v}
            onChange=${(e) => e.target.checked && call("multiboot.cardpick_pick", null, v)} />
          <span>${label}</span></label>`)}
      </div>
    </div>
  <//>`;
}
