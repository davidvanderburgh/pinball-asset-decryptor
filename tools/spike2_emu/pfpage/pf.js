// The virtual playfield page (and the villain vision page, ?page=lcd).
//
// playfield.py owns every decision; this draws what it is told and sends back
// what was pressed. Plain JavaScript on purpose: the page also runs in the
// macOS container's WebKit and a Linux desktop's browser, with nothing to
// build and nothing to fetch but this server.
//
// Node can require() this file for its tests (pfHit is exported at the end):
// the top-level code that touches the DOM, `location` or the window only runs
// where there is a document.
"use strict";

const Q = new URLSearchParams(typeof location === "undefined" ? "" : location.search);
const TOKEN = Q.get("t") || "";
const PAGE = Q.get("page") || "main";

// ---------------------------------------------------------------- transport
function api(m, ...a) {
  return fetch("/api?t=" + encodeURIComponent(TOKEN), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ m, a }),
  }).then((r) => r.json()).then((j) => (j.ok ? j.r : Promise.reject(new Error(j.error))))
    .catch((e) => { console.warn("api", m, e); return null; });
}
async function getState() {
  const r = await fetch("/state?t=" + encodeURIComponent(TOKEN) + "&page=" + PAGE);
  return r.json();
}
let seq = 0;
const handlers = {};
function on(type, fn) { handlers[type] = fn; }
function dispatch(ev) { const h = handlers[ev.type]; if (h) h(ev.data); }
function listen() {
  let opened = false;
  let es = null;
  try {
    es = new EventSource("/events?t=" + encodeURIComponent(TOKEN) + "&since=" + seq);
    es.onopen = () => { opened = true; };
    es.onmessage = (m) => { seq = Number(m.lastEventId) || seq; dispatch(JSON.parse(m.data)); };
  } catch (e) { es = null; }
  // an engine whose EventSource never opens gets long polling instead
  setTimeout(() => { if (!opened) { if (es) es.close(); poll(); } }, 4000);
}
async function poll() {
  for (;;) {
    try {
      const r = await fetch("/events?poll=1&wait=20&t=" + encodeURIComponent(TOKEN) + "&since=" + seq);
      const j = await r.json();
      for (const ev of j.events) { seq = ev.seq; dispatch(ev.e); }
    } catch (e) { await new Promise((ok) => setTimeout(ok, 1000)); }
  }
}
on("close", () => { try { window.close(); } catch (e) { /* the host closes it */ } });

// ---------------------------------------------------------------- helpers
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function btn(label, onClick, cls) {
  const b = el("button", "btn" + (cls ? " " + cls : ""), label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}
const tipEl = typeof document === "undefined" ? null : document.getElementById("tip");
function showTip(text, x, y) {
  if (!text) { hideTip(); return; }
  tipEl.textContent = text;
  tipEl.hidden = false;
  const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  let tx = x + 16, ty = y + 14;
  if (tx + w > innerWidth - 6) tx = Math.max(6, x - w - 12);
  if (ty + h > innerHeight - 6) ty = Math.max(6, y - h - 10);
  tipEl.style.left = tx + "px";
  tipEl.style.top = ty + "px";
}
function hideTip() { tipEl.hidden = true; }
// hold something for as long as the mouse button is down, wherever the
// pointer goes meanwhile (the release opens what was HELD)
function holdWith(target, ev, down, up) {
  ev.preventDefault();
  try { target.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
  down();
  const done = () => {
    target.removeEventListener("pointerup", done);
    target.removeEventListener("pointercancel", done);
    target.removeEventListener("lostpointercapture", done);
    up();
  };
  target.addEventListener("pointerup", done);
  target.addEventListener("pointercancel", done);
  target.addEventListener("lostpointercapture", done);
}

// ---------------------------------------------------------------- hit test
// The artwork's marker size, which the hit test and the drawing share.
const PF_LED_R = 5.5;

// Tk's hit test, kept: the topmost marker whose SHAPE overlaps a 6 px box
// round the pointer - an unfilled ring or square is hit on its outline
// only, a lit or dark insert on its disc - with switches over coils over
// inserts, so "which device does a click reach" is what it was (item 24).
// PURE, so Node can test it: `view` is the field spec (switches, coils,
// fixtures), `fx` the fixtures' drawn state, `scale` the artwork's, and the
// made-state dots are not an input at all - they are never a hit target.
function pfHit(view, fx, scale, px, py) {
  const LED_R = PF_LED_R;
  const x0 = px - 3, y0 = py - 3, x1 = px + 3, y1 = py + 3;
  const near = (cx, cy) => Math.hypot(Math.max(x0 - cx, 0, cx - x1), Math.max(y0 - cy, 0, cy - y1));
  const far = (cx, cy) => Math.hypot(Math.max(Math.abs(x0 - cx), Math.abs(x1 - cx)),
    Math.max(Math.abs(y0 - cy), Math.abs(y1 - cy)));
  const ring = (cx, cy, r, w) => near(cx, cy) <= r + w / 2 && far(cx, cy) >= r - w / 2;
  const sq = (cx, cy, h, w) => {
    const o = h + w / 2, i = h - w / 2;
    const overlaps = x1 >= cx - o && x0 <= cx + o && y1 >= cy - o && y0 <= cy + o;
    const inside = x0 > cx - i && x1 < cx + i && y0 > cy - i && y1 < cy + i;
    return overlaps && !inside;
  };
  for (let n = view.switches.length - 1; n >= 0; n--) {
    const [k, x, y] = view.switches[n];
    if (ring(x * scale, y * scale, 6, 2)) return ["switch", k];
  }
  for (let n = view.coils.length - 1; n >= 0; n--) {
    const [k, x, y] = view.coils[n];
    if (sq(x * scale, y * scale, 7, 2)) return ["coil", k];
  }
  for (let n = view.fixtures.length - 1; n >= 0; n--) {
    const [fid, x, y] = view.fixtures[n];
    const v = fx[fid];
    const r = v ? v[4] : LED_R;
    if (near(x * scale, y * scale) <= r + (v ? 0 : 0.5)) return ["led", fid];
  }
  return null;
}

// report where this window is, for the next open (the native host knows it
// itself; a browser window only knows it from here)
let lastGeom = "";
if (typeof document !== "undefined") {
  setInterval(() => {
    const g = [screenX, screenY].join(",");
    if (g !== lastGeom) { lastGeom = g; api("geom", PAGE, screenX, screenY); }
  }, 2000);

  if (PAGE === "lcd") startLcd(); else startMain();
}

// ============================================================ the main page
function startMain() {
  let S = null;              // the snapshot
  let view = null;           // the drawn view's live parts
  const app = document.getElementById("app");

  async function load() {
    S = await getState();
    seq = Math.max(seq, S._seq || 0);
    document.title = S.title || "virtual playfield";
    render();
  }
  on("layout", () => load());
  on("frame", (f) => view && view.frame(f));
  on("slots", (s) => { if (S) { S.slots = s.values; S.state_busy = s.busy; } if (view) view.slots(s); });
  on("run", (r) => { if (S) S.run = r; if (view) view.run(r); });

  function render() {
    app.textContent = "";
    hideTip();
    const body = el("div", "pf-body");
    const main = el("div", "pf-main");
    body.append(main);
    const status = el("div", "pf-status");
    const stxt = el("div", "txt", S.status || "");
    status.append(stxt);
    const run = runCluster(S.run);
    status.append(run.el);
    const states = S.savestates ? stateCluster() : null;
    if (states) status.append(states.el);
    let v;
    if (S.kind === "field") v = fieldView(main);
    else if (S.kind === "schematic") v = schematicView(main);
    else v = waitingView(main);
    let panel = null;
    if (S.panel) { panel = keyPanel(S.panel); body.append(panel.el); }
    app.append(body, status);
    view = {
      frame(f) {
        if (f.status != null) stxt.textContent = f.status;
        if (v.frame) v.frame(f);
        if (panel && f.panel) panel.update(f.panel);
      },
      slots(s) { if (states) states.update(s); },
      run(r) { run.update(r); },
    };
  }

  // ---- the run's own controls (PAD-204): Pause, and the PC-side volume -------
  // Pause freezes the whole game exactly as Pause / F9 does. The volume and
  // Mute are the Emulate tab's own (one control file, polled by the audio
  // player), shown only when the run was handed that file. Every control here
  // lets go of the keyboard the moment it is used: a focused slider would eat
  // the arrow keys and a focused box the space bar, which are the flippers
  // and the Action button.
  function runCluster(R) {
    const box = el("div", "pf-run");
    const pause = btn("Pause", () => { pause.blur(); api("pause"); }, "sm");
    pause.title = "Freeze the game where it is, and carry on from there (Pause or F9)";
    box.append(pause);
    let vol = null, pct = null, mute = null, sliding = false, sent = 0, timer = null;
    if (R && R.audio) {
      const lab = el("span", "lab", "VOL");
      vol = el("input", "vol");
      vol.type = "range"; vol.min = "0"; vol.max = "100"; vol.step = "1";
      pct = el("span", "pct mono", "");
      const send = () => { timer = null; sent = Date.now(); api("volume", Number(vol.value)); };
      vol.addEventListener("pointerdown", () => { sliding = true; });
      vol.addEventListener("input", () => {
        pct.textContent = vol.value + "%";
        if (!timer) timer = setTimeout(send, Math.max(0, 80 - (Date.now() - sent)));
      });
      vol.addEventListener("change", () => { sliding = false; vol.blur(); });
      const mbox = el("label", "mute");
      mute = el("input");
      mute.type = "checkbox";
      mute.addEventListener("change", () => { api("mute", mute.checked); mute.blur(); });
      mbox.append(mute, el("span", null, "Mute"));
      box.append(lab, vol, pct, mbox);
    }
    const update = (r) => {
      if (!r) return;
      pause.textContent = r.paused ? "Resume" : "Pause";
      pause.classList.toggle("primary", !!r.paused);
      box.classList.toggle("paused", !!r.paused);
      if (vol && r.audio) {
        if (!sliding) {
          vol.value = String(Math.round(r.audio.gain * 100));
          pct.textContent = vol.value + "%";
        }
        mute.checked = !!r.audio.muted;
      }
    };
    update(R || {});
    return { el: box, update };
  }

  // ---- the save-state cluster (item 13) --------------------------------------
  function stateCluster() {
    const box = el("div", "pf-states");
    const sel = el("select", "sel");
    const fill = (vals) => {
      const keep = sel.selectedIndex;
      sel.textContent = "";
      vals.forEach((t, i) => { const o = el("option", null, t); o.value = String(i); sel.append(o); });
      sel.selectedIndex = keep >= 0 ? keep : 0;
    };
    fill(S.slots || []);
    const save = btn("Save state", () => saveDialog(sel.selectedIndex));
    const loadB = btn("Load state", () => api("load", sel.selectedIndex));
    const setBusy = (b) => { save.disabled = loadB.disabled = !!b; };
    setBusy(S.state_busy);
    box.append(sel, save, loadB);
    return { el: box, update(s) { fill(s.values || []); setBusy(s.busy); } };
  }
  function saveDialog(idx) {
    const scrim = el("div", "pf-scrim");
    const m = el("div", "pf-modal");
    m.append(el("h2", null, "Save state"));
    m.append(el("div", null, "Save to slot " + (idx + 1) + " - name (optional):"));
    const inp = el("input");
    const cur = (S.slots[idx] || "").replace(/^\d+ · /, "");
    inp.value = cur === "(empty)" || cur === "unnamed" ? "" : cur;
    inp.maxLength = 40;
    m.append(inp);
    const ft = el("div", "ft");
    const close = () => scrim.remove();
    const go = () => { const label = inp.value; close(); api("save", idx, label); };
    ft.append(btn("Cancel", close), btn("Save", go, "primary"));
    m.append(ft);
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); go(); }
      if (e.key === "Escape") { e.preventDefault(); close(); }
    });
    scrim.addEventListener("pointerdown", (e) => { if (e.target === scrim) close(); });
    scrim.append(m);
    document.body.append(scrim);
    inp.focus();
    inp.select();
  }

  // ---- the action row (only without a key panel: PAD-134) ---------------------
  function actionRow() {
    if (!S.acts || !S.acts.length) return null;
    const row = el("div", "pf-acts");
    for (const [i, label] of S.acts) row.append(btn(label, () => api("action", i)));
    return row;
  }

  // ---- a trough strip that IS the control (the fallback) ----------------------
  function troughStrip(spec, dyn) {
    const box = el("div", "pf-trough" + (spec.clickable ? " click" : ""));
    const balls = el("div", "balls");
    const cells = spec.pos.map((p, i) => {
      const c = el("div", "cell");
      const b = el("div", "ball");
      c.append(b, el("div", "n", String(p)));
      if (spec.clickable) c.addEventListener("click", () => api("trough", i));
      balls.append(c);
      return b;
    });
    const cap = el("div", "cap");
    box.append(balls, cap);
    const update = (d) => {
      if (!d) return;
      (d.flags || []).forEach((on, i) => { if (cells[i]) cells[i].classList.toggle("on", !!on); });
      cap.textContent = d.text || "";
    };
    update(dyn);
    return { el: box, update };
  }

  // ================================================== the artwork view
  function fieldView(main) {
    const V = S.view, D = S.dyn || {};
    const wrap = el("div", "pf-stagewrap");
    const stage = el("div", "pf-stage" + (V.art ? "" : " noart"));
    if (V.art) {
      const img = el("img", "art");
      img.src = "/file/art?t=" + encodeURIComponent(TOKEN);
      img.draggable = false;
      stage.append(img);
    }
    const cv = el("canvas");
    stage.append(cv);
    const overlay = el("div", "pf-overlay");
    let trough = null;
    if (V.trough) { trough = troughStrip(V.trough, D.trough); overlay.append(trough.el); }
    const acts = actionRow();
    if (acts) overlay.append(acts);
    stage.append(overlay);
    wrap.append(stage);
    main.append(wrap);

    const [BW, BH] = V.base;
    const fx = {}; for (const k in (D.fx || {})) fx[k] = D.fx[k];
    const coilHot = Object.assign({}, D.coil || {});
    const made = Object.assign({}, D.sw || {});
    let held = null;      // ["switch"|"coil", k]
    let ripping = null;
    let scale = 1, dirty = true;

    function fit() {
      const r = wrap.getBoundingClientRect();
      const s = Math.max(0.2, Math.min((r.width - 16) / BW, (r.height - 16) / BH));
      scale = s;
      stage.style.width = Math.round(BW * s) + "px";
      stage.style.height = Math.round(BH * s) + "px";
      const dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(BW * s * dpr);
      cv.height = Math.round(BH * s * dpr);
      dirty = true;
    }
    new ResizeObserver(fit).observe(wrap);

    const LED_R = PF_LED_R, GLOW_R = 11;
    function draw() {
      if (!dirty) return;
      dirty = false;
      const dpr = window.devicePixelRatio || 1;
      const g = cv.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, cv.width, cv.height);
      // every glow before any core marker: fixtures overlap on this picture
      for (const [fid, x, y] of V.fixtures) {
        const v = fx[fid];
        if (!v) continue;
        const [r, gg, b, a, rad] = v;
        const cx = x * scale, cy = y * scale, gr = GLOW_R * (rad / LED_R);
        const grad = g.createRadialGradient(cx, cy, 0, cx, cy, gr);
        grad.addColorStop(0, `rgba(${r >> 1},${gg >> 1},${b >> 1},${a * 0.55})`);
        grad.addColorStop(1, `rgba(${r >> 1},${gg >> 1},${b >> 1},0)`);
        g.fillStyle = grad;
        g.beginPath(); g.arc(cx, cy, gr, 0, Math.PI * 2); g.fill();
      }
      for (const [fid, x, y] of V.fixtures) {
        const v = fx[fid];
        const cx = x * scale, cy = y * scale;
        g.beginPath();
        if (!v) {
          g.arc(cx, cy, LED_R, 0, Math.PI * 2);
          g.fillStyle = "#1a1a1a"; g.fill();
          g.lineWidth = 1; g.strokeStyle = "#3a3a3a"; g.stroke();
        } else {
          const [r, gg, b, a, rad] = v;
          g.arc(cx, cy, rad, 0, Math.PI * 2);
          g.fillStyle = `rgba(${r},${gg},${b},${a})`; g.fill();
        }
      }
      for (const [k, x, y, key] of V.coils) {
        const cx = x * scale, cy = y * scale, h = 7;
        const hot = !!coilHot[key];
        const isHeld = held && held[0] === "coil" && held[1] === k;
        if (hot) { g.fillStyle = "#ff00c0"; g.fillRect(cx - h, cy - h, 2 * h, 2 * h); }
        g.lineWidth = isHeld || hot ? 3 : 2;
        g.strokeStyle = isHeld ? "#ffd400" : hot ? "#ff80ff" : "#ff4040";
        g.strokeRect(cx - h, cy - h, 2 * h, 2 * h);
      }
      for (const [k, x, y, id] of V.switches) {
        const cx = x * scale, cy = y * scale;
        const isHeld = held && held[0] === "switch" && held[1] === k;
        const isRip = ripping === k;
        g.beginPath(); g.arc(cx, cy, 6, 0, Math.PI * 2);
        g.lineWidth = isHeld || isRip ? 3 : 2;
        g.strokeStyle = isHeld ? "#ffd400" : isRip ? "#ff9500" : "#2a8cff";
        g.stroke();
        if (made[String(id)]) {
          g.beginPath(); g.arc(cx, cy, 3, 0, Math.PI * 2);
          g.fillStyle = "#00c853"; g.fill();
        }
      }
    }
    (function loop() { draw(); requestAnimationFrame(loop); })();

    // Tk's hit test, kept - pfHit() above says how.
    function hit(px, py) { return pfHit(V, fx, scale, px, py); }
    const at = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    let tipFor = null, tipText = "", tipAt = 0;
    cv.addEventListener("pointermove", (e) => {
      const h = hit(...at(e));
      cv.style.cursor = h && h[0] !== "led" ? "pointer" : "default";
      if (!h) { tipFor = null; hideTip(); return; }
      const key = h.join(":");
      const now = performance.now();
      if (key !== tipFor || now - tipAt > 400) {
        const ask = key;
        tipFor = key; tipAt = now;
        api("tip", h[0], h[1]).then((t) => { if (tipFor === ask) { tipText = t || ""; showTip(tipText, e.clientX, e.clientY); } });
      }
      showTip(tipText, e.clientX, e.clientY);
    });
    cv.addEventListener("pointerleave", () => { tipFor = null; hideTip(); });
    cv.addEventListener("contextmenu", (e) => e.preventDefault());
    cv.addEventListener("pointerdown", (e) => {
      const h = hit(...at(e));
      if (!h) return;
      if (e.button === 0) {
        if (h[0] === "switch") {
          const id = V.switches.find((s) => s[0] === h[1])[3];
          holdWith(cv, e, () => { held = h; dirty = true; api("hold", id); },
            () => { held = null; dirty = true; api("unhold"); });
        } else if (h[0] === "coil") {
          holdWith(cv, e, () => {
            api("coil", h[1]).then((sw) => { if (sw != null) { held = h; dirty = true; } });
          }, () => { if (held) { held = null; dirty = true; } api("unhold"); });
        }
      } else if (e.button === 2 && h[0] === "switch") {
        const id = V.switches.find((s) => s[0] === h[1])[3];
        holdWith(cv, e, () => { ripping = h[1]; dirty = true; api("rip", id, true); },
          () => { ripping = null; dirty = true; api("rip", id, false); });
      }
    });

    return {
      frame(f) {
        if (f.fx) { for (const k in f.fx) fx[k] = f.fx[k]; dirty = true; }
        if (f.coil) { Object.assign(coilHot, f.coil); dirty = true; }
        if (f.sw) { Object.assign(made, f.sw); dirty = true; }
        if (f.trough && trough) trough.update(f.trough);
      },
    };
  }

  // ================================================== the schematic view
  function schematicView(main) {
    const V = S.view, D = S.dyn || {};
    const bar = el("div", "pf-bar");
    bar.append(el("div", "txt", V.bar));
    const acts = actionRow();
    if (acts) bar.append(acts);
    main.append(bar);
    let trough = null;
    if (V.trough) {
      const strip = el("div", "pf-strip");
      trough = troughStrip(V.trough, D.trough);
      strip.append(trough.el);
      main.append(strip);
    }
    const body = el("div", "pf-schem");
    const grid = el("div", "pf-grid");
    const rows = el("div", "pf-rows");
    body.append(grid, rows);
    main.append(body);

    // the LED swatch grid: every lamp the wire has shown, by node
    const cells = {};
    const gridData = Object.assign({}, D.grid || {});
    if (!V.grid.blocks.length) {
      grid.append(el("div", "note", "LEDs\n\nwaiting for the first\nLED write from the game"));
    }
    for (const blk of V.grid.blocks) {
      const b = el("div", "blk");
      b.append(el("div", "hdr", "node " + blk.node + "  (" + blk.cells.length + ")"));
      const cs = el("div", "cells");
      for (const c of blk.cells) {
        const d = el("div", "c");
        d.addEventListener("pointermove", (e) => showTip(c.tip, e.clientX, e.clientY));
        d.addEventListener("pointerleave", hideTip);
        cells[c.k] = d;
        cs.append(d);
      }
      b.append(cs);
      grid.append(b);
    }
    const paintCell = (k) => {
      const d = cells[k], v = gridData[k];
      if (!d) return;
      if (!v) { d.style.background = ""; d.style.borderColor = ""; return; }
      const [r, g, b, a] = v;
      d.style.background = `rgba(${r},${g},${b},${a})`;
      d.style.borderColor = `rgba(${r},${g},${b},${Math.min(1, a * 1.3)})`;
    };
    for (const k in cells) paintCell(k);

    // the switch rows, flowing into the columns the window's height has
    const dots = {};
    for (const e of V.entries) {
      if (e.hdr != null) { rows.append(el("div", "hdr", "node " + e.hdr)); continue; }
      const r = el("div", "r" + (e.live ? "" : " dead"));
      const d = el("span", "d");
      r.append(d, document.createTextNode(String(e.id).padStart(3, " ") + "  " + e.name));
      r.addEventListener("pointermove", (ev) => showTip(e.tip, ev.clientX, ev.clientY));
      r.addEventListener("pointerleave", hideTip);
      if (e.live) {
        (dots[String(e.id)] = dots[String(e.id)] || []).push(d);
        r.addEventListener("contextmenu", (ev) => ev.preventDefault());
        r.addEventListener("pointerdown", (ev) => {
          if (ev.button === 0) {
            holdWith(r, ev, () => { r.classList.add("held"); api("hold", e.id); },
              () => { r.classList.remove("held"); api("unhold"); });
          } else if (ev.button === 2) {
            holdWith(r, ev, () => { r.classList.add("rip"); api("rip", e.id, true); },
              () => { r.classList.remove("rip"); api("rip", e.id, false); });
          }
        });
      }
      rows.append(r);
    }
    const paintDots = (sw) => { for (const k in sw) for (const d of (dots[k] || [])) d.classList.toggle("on", !!sw[k]); };
    paintDots(D.sw || {});

    return {
      frame(f) {
        if (f.sw) paintDots(f.sw);
        if (f.grid) { for (const k in f.grid) { gridData[k] = f.grid[k]; paintCell(k); } }
        if (f.trough && trough) trough.update(f.trough);
      },
    };
  }

  // ================================================== waiting for tables
  function waitingView(main) {
    const w = el("div", "pf-wait");
    w.append(el("h1", null, "Waiting for this title's tables"));
    w.append(el("pre", null, S.waiting || ""));
    main.append(w);
    return {};
  }

  // ================================================== the key panel (item 39)
  function keyPanel(P) {
    const spec = P.spec;
    const root = el("aside", "pf-panel");
    const kb = el("div", "kp-sec");
    const head = el("div", "kp-head");
    head.append(el("span", "h", "KEYBOARD"), el("span", "s", "works here and in the game window"));
    kb.append(head);
    let section = null;
    const rowEls = spec.rows.map((r) => {
      if (r.cabinet !== section) {
        section = r.cabinet;
        kb.append(el("div", "kp-group", r.cabinet ? "CABINET" : "PLAYFIELD"));
      }
      const row = el("div", "kp-row" + (r.na ? " na" : "") + (r.click != null ? " click" : ""));
      const d = el("span", "d"), k = el("span", "k", r.keys), l = el("span", "l", r.label);
      const x = el("span", "x", r.na ? "n/a" : "");
      row.append(d, k, l, x);
      if (r.click != null) {
        row.addEventListener("pointerdown", (ev) => {
          if (ev.button !== 0) return;
          holdWith(row, ev, () => api("row", r.click, true), () => api("row", r.click, false));
        });
      }
      kb.append(row);
      return { row, d, x };
    });
    kb.append(el("div", "kp-hint", "green dot = switch made"));
    kb.append(el("div", "kp-hint", "Pause or F9 = freeze / resume the game"));
    if (spec.rows.some((r) => r.click != null)) kb.append(el("div", "kp-hint", "click Start Button or Left Coin to press it"));
    root.append(kb);

    // the service cluster, drawn as the real coin-door panel
    let svcEls = [];
    if (spec.svc.length || spec.clear) {
      const sec = el("div", "kp-sec");
      sec.append(el("div", "kp-group", spec.svc.length ? "SERVICE  -  click and hold" : "SERVICE"));
      if (spec.svc.length) {
        const g = el("div", "kp-svc");
        svcEls = spec.svc.map((s) => {
          const b = el("div", "b");
          const o = el("div", "o", s.glyph);
          o.style.background = s.fill; o.style.borderColor = s.ring;
          const cap = el("div", "cap", s.sub); cap.style.color = s.subfg;
          b.append(o, cap, el("div", "ks", s.keys));
          b.addEventListener("pointerdown", (ev) => {
            if (ev.button !== 0) return;
            holdWith(b, ev, () => { b.classList.add("down"); api("svc", s.id, true); },
              () => { b.classList.remove("down"); api("svc", s.id, false); });
          });
          g.append(b);
          return { o, ring: s.ring };
        });
        sec.append(g, el("div", "kp-hint", "press SELECT for the service menu"));
      }
      if (spec.clear) {
        sec.append(btn(spec.clear, () => api("clear_alerts"), "kp-wide"));
        sec.append(el("div", "kp-hint", "presses every safe switch once, about 12 s"));
      }
      root.append(sec);
    }

    // the coin door, a toggle because the real door STAYS
    let door = null, doorTxt = null;
    if (spec.door) {
      door = el("div", "kp-door");
      doorTxt = el("span", "t", "COIN DOOR  closed - 48V on");
      door.append(el("span", "k", spec.door), doorTxt);
      door.addEventListener("click", () => api("door"));
      root.append(door);
    }

    // the BALLS section (PAD-134)
    let ball = null, drain = null, note = null, dots = null;
    if (spec.balls) {
      const sec = el("div", "kp-sec");
      const h = el("div", "kp-head");
      h.append(el("span", "kp-group", "BALLS"));
      if (spec.trough_keys) { const t = el("span", "ks mono", spec.trough_keys); t.style.color = "var(--key)"; t.style.fontSize = "10.5px"; h.append(t); }
      sec.append(h);
      ball = el("div", "kp-ball", "");
      sec.append(ball);
      dots = troughStrip(Object.assign({}, spec.balls, { clickable: false }), null);
      sec.append(dots.el);
      const bs = el("div", "kp-btns");
      bs.append(btn("Plunge", () => api("ball", "plunge")));
      drain = btn("Drain", () => api("ball", "drain"));
      bs.append(drain, btn("Reset balls", () => api("ball", "reset")));
      sec.append(bs);
      note = el("div", "kp-note");
      sec.append(note);
      root.append(sec);
    }

    function fitNote(msgs) {
      // WHOLE MESSAGES ARE DROPPED, OLDEST FIRST - never the head of one; a
      // message that alone needs more than three rows keeps its first rows
      note.textContent = "";
      if (!msgs.length) return;
      const lh = parseFloat(getComputedStyle(note).lineHeight) || 16;
      const max = lh * 3 + 1;
      let shown = msgs.slice();
      for (;;) {
        note.textContent = "";
        for (const m of shown) note.append(el("span", "m", m));
        if (note.scrollHeight <= max || shown.length === 1) break;
        shown = shown.slice(1);
      }
      if (note.scrollHeight > max && shown.length === 1) {
        note.textContent = "";
        note.append(el("span", "m cut", shown[0]));
      }
    }

    function update(d) {
      (d.rows || []).forEach((st, i) => {
        const r = rowEls[i];
        if (!r || !st) return;
        r.row.classList.toggle("hit", !!st[0]);
        r.x.textContent = st[1] || (spec.rows[i].na ? "n/a" : "");
        r.d.classList.toggle("on", !!st[2]);
      });
      (d.svc || []).forEach((m, i) => { if (svcEls[i]) svcEls[i].o.classList.toggle("made", !!m); });
      if (door && d.door != null) {
        door.classList.toggle("open", !d.door);
        // amber, not red: an open door is a state you chose, but no coil
        // will fire while it lasts
        doorTxt.textContent = d.door ? "COIN DOOR  closed - 48V on" : "COIN DOOR  OPEN - 48V off, coils dead";
      }
      if (ball) ball.textContent = d.ball || "";
      if (drain) drain.disabled = !d.drain;
      if (dots && d.dots) dots.update(d.dots);
      if (note) fitNote(d.note || []);
    }
    update(P.dyn || {});
    return { el: root, update };
  }

  // ---- the keyboard, with THIS window focused (item 39) -----------------------
  const typing = (e) => { const t = e.target; return t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA"); };
  // Pause and F9 freeze and resume the game (PAD-204), as in the game window
  const PLAY_CODES = /^(Key[A-Z]|Digit\d|Space|Enter|NumpadEnter|Backspace|Escape|Equal|Minus|Arrow(Left|Right|Up|Down)|Pause|F9)$/;
  addEventListener("keydown", (e) => {
    if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (!PLAY_CODES.test(e.code)) return;
    e.preventDefault();
    if (e.repeat) return;           // auto-repeat: the key is still held
    api("key", e.code, e.key, true);
  });
  addEventListener("keyup", (e) => {
    if (typing(e) || !PLAY_CODES.test(e.code)) return;
    e.preventDefault();
    api("key", e.code, e.key, false);
  });
  // a window that loses focus never hears the key come up: release it all
  addEventListener("blur", () => api("blur"));

  load().then(listen);
}

// ============================================================ villain vision
function startLcd() {
  const app = document.getElementById("app");
  let L = null, D = null, pic = null, ph = null, cap = null, nm = null, strip = null;

  async function load() {
    const st = await getState();
    seq = Math.max(seq, st._seq || 0);
    L = st.lcd; D = st.dyn;
    document.title = L.title;
    render();
    apply(D);
  }
  on("lcd", (d) => apply(d));

  function render() {
    app.textContent = "";
    const box = el("div", "lcd");
    const [w, h] = L.size;
    const set = el("div", "lcd-set");
    set.style.width = w + "px"; set.style.height = h + "px";
    const [sx, sy, sw, sh] = L.screen;
    if (!L.tv) set.append(cabinet());
    pic = el("img", "pic");
    pic.draggable = false;
    ph = el("div", "ph");
    if (L.tv) {
      // the composed image IS the set: it fills the canvas
      Object.assign(pic.style, { left: "0", top: "0", width: w + "px", height: h + "px" });
      Object.assign(ph.style, { left: sx + "px", top: sy + "px", width: sw + "px", height: sh + "px" });
    } else {
      // a bare 240x180 clip, centred in the drawn screen
      Object.assign(ph.style, { left: sx + "px", top: sy + "px", width: sw + "px", height: sh + "px" });
      pic.onload = () => {
        pic.style.left = (sx + (sw - pic.naturalWidth) / 2) + "px";
        pic.style.top = (sy + (sh - pic.naturalHeight) / 2) + "px";
      };
    }
    set.append(pic, ph);
    cap = el("div", "lcd-cap");
    nm = el("div", "lcd-nm");
    strip = el("div", "lcd-strip");
    strip.style.width = (L.cw + L.pad[0] + L.pad[2]) + "px";
    box.append(set, cap, nm, strip);
    app.append(box);
  }

  function cabinet() {
    // the real Villain Vision: a wood-cased 1960s portable with a chrome
    // bezel, two knobs on a right-hand panel and its name in script
    const [pl, pt, pr, pb] = L.pad;
    const cw = L.cw, ch = L.ch;
    const c = el("div", "lcd-case");
    const at = (e, x, y, w, h) => { Object.assign(e.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" }); return e; };
    c.append(el("div", "in"));
    c.append(at(el("div", "bez"), pl - 8, pt - 8, cw + 16, ch + 16));
    c.append(at(el("div", "lip"), pl - 3, pt - 3, cw + 6, ch + 6));
    c.append(at(el("div", "scr"), pl, pt, cw, ch));
    const px0 = pl + cw + 12, w = cw + pl + pr;
    const knobs = at(el("div", "knobs"), px0, pt - 8, w - 8 - px0, ch + 16);
    c.append(knobs);
    for (const cy of [pt + 26, pt + 74]) {
      const k = el("div", "knob");
      k.style.left = (px0 + 8) + "px"; k.style.top = (cy - 15) + "px";
      c.append(k);
    }
    c.append(at(el("div", "spk"), px0 + 8, pt + ch - 34, w - 16 - (px0 + 8), 22));
    const s = el("div", "script", "Villain Vision");
    s.style.top = (pt + ch + 9) + "px"; s.style.width = (pl + cw + pl) + "px";
    c.append(s);
    void pb;
    return c;
  }

  function apply(d) {
    if (!d || !pic) return;
    if (d.pic) {
      const src = "/blob/" + d.pic + "?t=" + encodeURIComponent(TOKEN);
      if (pic.getAttribute("src") !== src) pic.setAttribute("src", src);
      pic.style.visibility = d.shown ? "visible" : "hidden";
      ph.textContent = "";
    } else {
      pic.removeAttribute("src");
      pic.style.visibility = "hidden";
      ph.textContent = d.placeholder || "";
    }
    cap.textContent = d.cap || "";
    nm.textContent = d.nm || "";
    // the filmstrip: oldest left, current right, right-aligned so the newest
    // is always in the same place
    strip.textContent = "";
    const items = d.strip || [];
    for (let k = 0; k < L.strip_n; k++) {
      const idx = items.length - L.strip_n + k;
      const t = el("div", "t");
      const f = el("img", "f");
      f.draggable = false;
      const lab = el("div", "i", "");
      if (idx >= 0 && idx < items.length) {
        const [id, key] = items[idx];
        f.src = "/blob/" + key + "?t=" + encodeURIComponent(TOKEN);
        lab.textContent = String(id);
        if (idx === items.length - 1) lab.classList.add("cur");
      } else {
        f.removeAttribute("src");
        f.style.visibility = "hidden";
      }
      // every slot keeps its frame, filled or not
      const cell = el("div", "fbox");
      cell.append(f);
      t.append(cell, lab);
      strip.append(t);
    }
  }

  load().then(listen);
}

// Node (the tests) takes the pure part; a browser has no `module`.
if (typeof module !== "undefined") module.exports = { pfHit };
