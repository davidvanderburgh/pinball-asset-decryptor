// The pinHeck game window's page: the DMD, buttons, switches, status.
// Talks to window.py through pfweb: POST /api, GET /blob/dmd for frames.
"use strict";
const Q = new URLSearchParams(location.search);
const TOKEN = Q.get("t") || "";
const $ = (id) => document.getElementById(id);

function api(m, ...a) {
  return fetch("/api?t=" + encodeURIComponent(TOKEN), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ m, a }),
  }).then((r) => r.json()).then((j) => j.r).catch(() => null);
}

// ---------------------------------------------------------------- the DMD
let n = 0;
const img = $("dmd");
function nextFrame() {
  img.src = "/blob/dmd" + (n++) + "?t=" + encodeURIComponent(TOKEN);
}
img.onload = () => {
  const rows = img.naturalHeight || 32;
  img.parentElement.style.setProperty("--rows", rows);
  img.parentElement.style.setProperty("--ratio", (img.naturalWidth || 128) / rows);
  setTimeout(nextFrame, 33);
};
img.onerror = () => setTimeout(nextFrame, 500);

// ------------------------------------------------------------- the switches
const grid = $("grid");
const cells = [];
for (let i = 0; i < 64; i++) {
  const b = document.createElement("button");
  b.className = "sw";
  b.dataset.n = i;
  b.innerHTML = "<span>" + i + "</span><span class=r></span>";
  b.title = "Switch " + i + " (row " + (i >> 3) + ", column " + (i & 7) + "). Click: a hit. Right-click: hold it closed / let go.";
  b.onclick = () => api("tap", i);
  b.oncontextmenu = (e) => {
    e.preventDefault();
    const held = b.classList.toggle("held");
    api(held ? "press" : "release", i);
  };
  grid.appendChild(b);
  cells.push(b);
}

// ------------------------------------------------------------------- lamps
const lampGrid = $("lamps");
const lampCells = [];
for (let i = 0; i < 64; i++) {
  const d = document.createElement("span");
  d.className = "lamp";
  d.title = "Lamp " + i + " (column " + (i >> 3) + ", row " + (i & 7) + ")";
  lampGrid.appendChild(d);
  lampCells.push(d);
}

// ----------------------------------------------------------------- buttons
const keyMap = {};
document.querySelectorAll("[data-sw]").forEach((b) => {
  b.onclick = () => api("tap", b.dataset.sw);
  keyMap[b.dataset.key] = { down: () => api("press", b.dataset.sw), up: () => api("release", b.dataset.sw), el: b };
});
document.querySelectorAll("[data-hold]").forEach((b) => {
  const sw = b.dataset.hold;
  const down = () => { b.classList.add("down"); api("press", sw); };
  const up = () => { if (b.classList.contains("down")) { b.classList.remove("down"); api("release", sw); } };
  b.onpointerdown = down; b.onpointerup = up; b.onpointerleave = up;
  keyMap[b.dataset.key] = { down, up, el: b };
});
$("plunge").onclick = () => api("plunge");
keyMap[" "] = { down: () => api("plunge"), up: () => {}, el: $("plunge") };
$("drain").onclick = () => api("drain");
keyMap["d"] = { down: () => api("drain"), up: () => {}, el: $("drain") };
keyMap["Shift:left"] = keyMap["z"];
keyMap["Shift:right"] = keyMap["/"];

let paused = false;
$("pause").onclick = () => { paused = !paused; api("pause", paused); $("pause").textContent = paused ? "Resume" : "Pause"; };
keyMap["p"] = { down: () => $("pause").click(), up: () => {} };
$("power").onclick = () => { $("power").disabled = true; api("power").then(() => { $("power").disabled = false; }); };

const down = new Set();
function keyName(e) {
  if (e.key === "Shift") return "Shift:" + (e.location === 2 ? "right" : "left");
  return e.key.length === 1 ? e.key.toLowerCase() : e.key;
}
addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  const k = keyName(e), h = keyMap[k];
  if (!h || down.has(k)) return;
  e.preventDefault(); down.add(k);
  if (h.el) h.el.classList.add("down");
  h.down();
});
addEventListener("keyup", (e) => {
  const k = keyName(e), h = keyMap[k];
  if (!h) return;
  down.delete(k);
  if (h.el) h.el.classList.remove("down");
  h.up();
});

// ----------------------------------------------------------------- volume
let muted = false;
$("gain").oninput = () => api("volume", $("gain").value / 100);
$("mute").onclick = () => { muted = !muted; api("mute", muted); $("mute").textContent = muted ? "Unmute" : "Mute"; };

$("sform").onsubmit = (e) => { e.preventDefault(); const v = $("sin").value.trim(); if (v) api("serial", v); $("sin").value = ""; };

// ------------------------------------------------------------------ status
function fmt(s) { const m = Math.floor(s / 60); return m + ":" + String(Math.floor(s % 60)).padStart(2, "0"); }
async function full() {
  const r = await fetch("/state?t=" + encodeURIComponent(TOKEN) + "&page=main").then((x) => x.json()).catch(() => null);
  if (!r) return;
  $("title").textContent = r.title;
  document.title = r.title + " - PAD";
  $("launch").hidden = !r.has_launch;
  $("plunge").hidden = !r.hand_plunger && r.has_launch;
  for (const [k, role] of Object.entries(r.roles || {})) cells[+k].querySelector(".r").textContent = role;
  if (r.sound_note) { $("note").hidden = false; $("note").textContent = r.sound_note; }
  muted = r.muted; $("mute").textContent = muted ? "Unmute" : "Mute";
  $("gain").value = Math.round((r.gain || 0) * 100);
  if (r.force_mute) { $("mute").disabled = true; $("gain").disabled = true; }
  show(r.status);
}
function show(s) {
  if (!s) return;
  $("clock").textContent = fmt(s.seconds);
  $("speed").textContent = "×" + (s.speed || 0).toFixed(2);
  $("balls").textContent = s.trough == null ? "—" : ("Trough " + s.trough + " · Lane " + (s.shooter ? 1 : 0) + " · Play " + s.in_play);
  // the game sends a score for all four players; show the ones in the game
  const sc = Object.entries(s.scores || {}).filter(([k, v]) => k === "1" || v > 0);
  $("scores").textContent = sc.length ? sc.map(([k, v]) => "P" + k + " " + Number(v).toLocaleString("en-US")).join("   ") : "—";
  $("coils").textContent = (s.coils && s.coils.length) ? s.coils.join(", ") : "—";
  $("playing").textContent = (s.playing && s.playing.length) ? s.playing.join(", ") : "—";
  const closed = new Set(s.closed || []);
  cells.forEach((c, i) => c.classList.toggle("closed", closed.has(i)));
  const lamps = s.lamps || [];
  lampCells.forEach((c, i) => c.style.setProperty("--on", lamps[i] || 0));
  const pre = $("uart"); const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
  pre.textContent = s.uart || ""; if (atEnd) pre.scrollTop = pre.scrollHeight;
  if (s.error) { $("note").hidden = false; $("note").textContent = "The game stopped: " + s.error; }
}
async function poll() { show(await api("status")); setTimeout(poll, 250); }
full().then(() => { nextFrame(); poll(); });
