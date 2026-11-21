// PAD-1475 (reopened): any of the game's own light shows by its number, beside the pick lists of them (a mode's
// Lights page, the Play the game's light show block, the co-op intro). s.show_pick is the tab's
// {max, names {n: name}, seen {n: "lit"|"dark"}}: the highest number the game's table has, the names the app knows
// (the port's, else the mode whose own code the show is) and what the show reel saw of it in the emulator.
import { html, useState, Field } from "../core/ui.js";

export const BY_NUMBER = "#?";
const NUM = /^#(\d+)$/;

// What the app knows of show *n*, in words.
export function showNumberWords(n, pick) {
  if (!pick || !pick.max) return "";
  if (!(n >= 1 && n <= pick.max)) return `The game's shows are numbered 1 to ${pick.max}.`;
  const name = (pick.names || {})[String(n)];
  const seen = (pick.seen || {})[String(n)];
  if (seen === "hangs") return `${name ? name + ": it" : "It"} stops the game when one of ours starts it, so it cannot be used.`;
  const what = seen === "lit" ? "seen lighting the playfield on its own"
    : seen === "dark" ? "seen lighting nothing on its own: it lights only while the game's mode for it runs"
    : "not checked on this game: it may light only while the game's own mode for it runs";
  return `${name ? name + ", " : ""}${what}.`;
}

// The pick list's options with "Another, by its number…" last, the value the list shows, its change handler and the
// number box to put after it (null unless a number is being picked). *value* is the saved pick ("#211", a port's
// name, "" / "(none)"); *onChange* saves one.
export function useShowNumber(value, opts, pick, onChange) {
  const [asking, setAsking] = useState(false);
  const can = !!(pick && pick.max);
  const m = NUM.exec(value || "");
  const listed = opts.some((o) => (Array.isArray(o) ? o[0] : typeof o === "object" ? o.value : o) === value);
  const open = can && (asking || (!!m && !listed));
  const all = can ? [...opts, { value: BY_NUMBER, label: "Another, by its number…", group: "Any of the game's shows" }] : opts;
  const onSel = (v) => {
    if (v === BY_NUMBER) { setAsking(true); return; }
    setAsking(false);
    onChange(v);
  };
  const n = m ? Number(m[1]) : NaN;
  // keyed by the saved number: a pick changed elsewhere (another tab, an undo) starts the box afresh
  const box = open ? html`<${ShowNumberBox} key=${m && !listed ? String(n) : "new"} n=${m && !listed ? n : NaN} pick=${pick}
      onPick=${(k) => { setAsking(false); onChange("#" + k); }} />` : null;
  return { opts: all, sel: open ? BY_NUMBER : value, onSel, box };
}

function ShowNumberBox({ n, pick, onPick }) {
  const [typed, setTyped] = useState(Number.isFinite(n) ? String(n) : "");
  const k = Number(typed);
  const usable = (t) => /^\d+$/.test(t) && Number(t) >= 1 && Number(t) <= pick.max && (pick.seen || {})[t] !== "hangs";
  const ok = usable(typed);
  return html`<span class="row" style="gap:6px; display:inline-flex; align-items:center">
    <${Field} sm type="number" min=${1} max=${pick.max} width=${96} value=${typed} autoFocus=${!Number.isFinite(n)}
      title=${`The game's own number for the show, 1 to ${pick.max}`} bad=${typed !== "" && !ok}
      onChange=${(v) => setTyped(String(v).trim())} onCommit=${(v) => { const t = String(v).trim(); if (usable(t)) onPick(Number(t)); }} />
    <span class="small muted wrap">${typed === "" ? `1 to ${pick.max}` : showNumberWords(k, pick)}</span>
  </span>`;
}
