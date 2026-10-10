// The page's copy of the UI state, kept in step with Python.
//
//   state[ns]   one object per tab / the shell ("shell", "extract", ...)
//   logLines    the current manufacturer's log
//
// Python publishes "state" patches (only the keys that changed), "item"
// updates (one row of a list), log lines and a few one-off events; this
// module applies them and re-renders whoever uses the namespace.
//
//   const s = useNs("extract")        // re-renders when extract changes
//   const shell = useNs("shell")
//   onEvent("open_dialog", e => ...)  // one-off events

import { useEffect, useState } from "../vendor/preact-htm.js";

const params = new URLSearchParams(location.search);
export const TOKEN = params.get("t") || "";
export const POLL = params.get("poll") === "1";

export const state = {};
export let logLines = [];
let seq = 0;
const nsListeners = new Map();     // ns -> Set(fn)
const logListeners = new Set();
const eventListeners = new Map();  // type -> Set(fn)
let connected = false;
const connListeners = new Set();

function emitNs(ns) {
  const set = nsListeners.get(ns);
  if (set) for (const fn of [...set]) fn();
  const all = nsListeners.get("*");
  if (all) for (const fn of [...all]) fn();
}

export function subscribe(ns, fn) {
  if (!nsListeners.has(ns)) nsListeners.set(ns, new Set());
  nsListeners.get(ns).add(fn);
  return () => nsListeners.get(ns).delete(fn);
}

export function useNs(ns) {
  const [, force] = useState(0);
  useEffect(() => subscribe(ns, () => force((n) => n + 1)), [ns]);
  return state[ns] || {};
}

export function useLog() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    logListeners.add(fn);
    return () => logListeners.delete(fn);
  }, []);
  return logLines;
}

export function onEvent(type, fn) {
  if (!eventListeners.has(type)) eventListeners.set(type, new Set());
  eventListeners.get(type).add(fn);
  return () => eventListeners.get(type).delete(fn);
}

export function useEvent(type, fn, deps = []) {
  useEffect(() => onEvent(type, fn), deps);
}

export function useConnected() {
  const [c, setC] = useState(connected);
  useEffect(() => {
    const fn = (v) => setC(v);
    connListeners.add(fn);
    setC(connected);
    return () => connListeners.delete(fn);
  }, []);
  return c;
}

function setConnected(v) {
  if (connected === v) return;
  connected = v;
  for (const fn of connListeners) fn(v);
}

function emitLog() {
  for (const fn of [...logListeners]) fn();
}

let logMaxId = 0;

// A BURST OF LOG LINES IS ONE REDRAW (PAD-505, DragonRR: "when I run emulate
// it is still hanging staging files with no way to know it is doing
// anything").  Each line used to copy the whole log and redraw the pane, and
// Emulate's Start converting Godzilla's 5,811 pictures sends 11,622 lines as
// fast as it converts them: on a busy PC the page fell minutes behind, with
// the State line and every click queued behind log redraws (a page throttled
// to a sixth of this PC's speed took 65 s to answer).  Lines now wait here and
// go into the log together, once a frame - or every 100 ms when the page is
// hidden and gets no frames.
let logPending = [];
let logFlushDue = false;

function queueLog(line) {
  logPending.push(line);
  if (logFlushDue) return;
  logFlushDue = true;
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(flushLog);
  setTimeout(flushLog, 100);
}

function flushLog() {
  logFlushDue = false;
  if (!logPending.length) return;
  const add = logPending;
  logPending = [];
  const all = logLines.concat(add);
  logLines = all.length > 5000 ? all.slice(-4000) : all;
  emitLog();
}

// lines still waiting that a fresh copy of the log already holds
function dropPendingUpTo(maxId) {
  logPending = logPending.filter((l) => l.id > maxId);
}

function currentMfr() {
  return (state.shell && state.shell.mfr && state.shell.mfr.key) || "";
}

function apply(e) {
  switch (e.t) {
    case "state": {
      if (e.replace) state[e.ns] = { ...e.patch };
      else state[e.ns] = { ...(state[e.ns] || {}), ...e.patch };
      emitNs(e.ns);
      break;
    }
    case "item": {
      const space = state[e.ns] || (state[e.ns] = {});
      const list = space[e.key];
      if (Array.isArray(list) && e.index >= 0 && e.index < list.length) {
        const copy = list.slice();
        copy[e.index] = e.value;
        state[e.ns] = { ...space, [e.key]: copy };
        emitNs(e.ns);
      }
      break;
    }
    case "log": {
      if (e.mfr !== currentMfr()) break;
      if (e.line.id <= logMaxId) break;
      logMaxId = e.line.id;
      queueLog(e.line);
      break;
    }
    case "log_update": {
      if (e.mfr !== currentMfr()) break;
      const p = logPending.findIndex((l) => l.id === e.id);
      if (p >= 0) {
        logPending[p] = { ...logPending[p], text: e.text, level: e.level };
        break;
      }
      const i = logLines.findIndex((l) => l.id === e.id);
      if (i >= 0) {
        logLines = logLines.slice();
        logLines[i] = { ...logLines[i], text: e.text, level: e.level };
        emitLog();
      }
      break;
    }
    case "log_reset": {
      reloadLog();
      break;
    }
    default:
      break;
  }
  const set = eventListeners.get(e.t);
  if (set) for (const fn of [...set]) {
    try { fn(e); } catch (err) { console.error(err); }
  }
}

async function reloadLog() {
  try {
    const r = await fetch("/api", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-PAD-Token": TOKEN },
      body: JSON.stringify({ m: "ui.log_history", a: [] }),
    });
    const j = await r.json();
    if (j.ok) {
      logLines = j.r || [];
      logMaxId = logLines.reduce((m, l) => Math.max(m, l.id || 0), 0);
      dropPendingUpTo(logMaxId);
      logMaxId = logPending.reduce((m, l) => Math.max(m, l.id || 0), logMaxId);
      emitLog();
    }
  } catch (err) { console.error(err); }
}

export async function loadAll() {
  const r = await fetch("/api/state?t=" + encodeURIComponent(TOKEN));
  if (!r.ok) throw new Error("state " + r.status);
  const j = await r.json();
  for (const k of Object.keys(state)) delete state[k];
  Object.assign(state, j.state || {});
  seq = j.seq || 0;
  logLines = j.log || [];
  logMaxId = logLines.reduce((m, l) => Math.max(m, l.id || 0), 0);
  dropPendingUpTo(logMaxId);
  logMaxId = logPending.reduce((m, l) => Math.max(m, l.id || 0), logMaxId);
  for (const ns of Object.keys(state)) emitNs(ns);
  emitNs("*");
  emitLog();
}

// ---- the event stream ------------------------------------------------------
let es = null;
let longPoll = false;
export function connect() {
  if (POLL) return pollLoop();
  if (longPoll || typeof EventSource === "undefined") return longPollLoop();
  if (es) es.close();
  let opened = false;
  let failures = 0;
  es = new EventSource("/events?t=" + encodeURIComponent(TOKEN) + "&since=" + seq);
  // An engine whose EventSource never opens on this server (seen in a
  // WKWebView) falls back to long polling, which works everywhere.
  const guard = setTimeout(() => {
    if (!opened) { es.close(); longPoll = true; longPollLoop(); }
  }, 4000);
  es.onopen = () => { opened = true; failures = 0; clearTimeout(guard); setConnected(true); };
  es.onmessage = (m) => {
    if (!opened) { opened = true; clearTimeout(guard); setConnected(true); }
    seq = Number(m.lastEventId) || seq;
    try { apply(JSON.parse(m.data)); } catch (err) { console.error(err, m.data); }
  };
  es.addEventListener("gap", async () => {
    es.close();
    await loadAll();
    connect();
  });
  es.onerror = () => {
    setConnected(false);
    failures += 1;
    if (!opened && failures >= 2) {
      clearTimeout(guard); es.close(); longPoll = true; longPollLoop();
    }
    // otherwise EventSource reconnects by itself with Last-Event-ID
  };
}

// Long polling: each request waits up to 20 s for events after seq.
async function longPollLoop() {
  while (true) {
    try {
      const r = await fetch("/events?poll=1&wait=20&t=" + encodeURIComponent(TOKEN) + "&since=" + seq);
      if (!r.ok) throw new Error("events " + r.status);
      const j = await r.json();
      setConnected(true);
      if (j.gap) { await loadAll(); continue; }
      for (const ev of j.events) { seq = ev.seq; apply(ev.e); }
    } catch (err) {
      setConnected(false);
      await new Promise((res) => setTimeout(res, 1000));
    }
  }
}

// Poll mode (captures, tests): short polls, then stop when asked.
let pollStop = false;
export function stopPolling() { pollStop = true; }
async function pollLoop() {
  setConnected(true);
  while (!pollStop) {
    try {
      const r = await fetch("/events?poll=1&wait=0.3&t=" + encodeURIComponent(TOKEN) + "&since=" + seq);
      const j = await r.json();
      if (j.gap) { await loadAll(); continue; }
      for (const ev of j.events) { seq = ev.seq; apply(ev.e); }
    } catch (err) {
      setConnected(false);
      await new Promise((res) => setTimeout(res, 500));
    }
  }
}
