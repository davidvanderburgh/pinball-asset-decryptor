// Calling Python.
//
//   await call("extract.browse_input")          // positional args
//   await call("ui.set", "extract", "input", v) // set a field
//   await callk("audio.pick", {rel, path})      // keyword args
//   setField("extract", "input", value)          // debounced ui.set
//
// A failing call shows a toast with Python's message and resolves to
// undefined (so a button handler never has to catch).

import { TOKEN } from "./store.js";

let toastHook = null;
export function onCallError(fn) { toastHook = fn; }

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-PAD-Token": TOKEN },
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function raw(m, a = [], k = null) {
  return post("/api", k ? { m, a, k } : { m, a });
}

export async function call(m, ...a) {
  try {
    const j = await post("/api", { m, a });
    if (!j.ok) {
      console.error(m, j.error, j.trace || "");
      if (toastHook) toastHook(j.error || "That did not work.", m);
      return undefined;
    }
    return j.r;
  } catch (err) {
    console.error(m, err);
    if (toastHook) toastHook("Lost contact with the app (" + err.message + ").", m);
    return undefined;
  }
}

export async function callk(m, k) {
  try {
    const j = await post("/api", { m, a: [], k });
    if (!j.ok) {
      console.error(m, j.error, j.trace || "");
      if (toastHook) toastHook(j.error || "That did not work.", m);
      return undefined;
    }
    return j.r;
  } catch (err) {
    if (toastHook) toastHook("Lost contact with the app (" + err.message + ").", m);
    return undefined;
  }
}

export async function reply(id, v) {
  return post("/api/reply", { id, v });
}

const pending = new Map();
// Send a field edit after the user pauses (typing), or at once (flush=true).
export function setField(ns, key, value, { delay = 250, flush = false } = {}) {
  const k = ns + "." + key;
  const prev = pending.get(k);
  if (prev) clearTimeout(prev);
  if (flush || delay <= 0) {
    pending.delete(k);
    return call("ui.set", ns, key, value);
  }
  pending.set(k, setTimeout(() => {
    pending.delete(k);
    call("ui.set", ns, key, value);
  }, delay));
  return Promise.resolve(true);
}
