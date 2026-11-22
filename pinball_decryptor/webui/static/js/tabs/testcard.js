// The Test card tab (PAD-1279, DragonRR: "make it independent ... as simple as possible").
// One list - what is ticked TEST in the Images, Video, Scenes and Audio tabs, and files
// added here - and one button that makes a small card booting any Stern Spike 2 machine
// into the TEST CARD menu.  The default PAD test card is always on it.
import { html, PageHead, Card, Button, Check, Field, Note, Progress, tip, call, cx } from "../core/ui.js";
import { useNs } from "../core/store.js";

const NS = "testcard";
const LISTS = [
  { kind: "image", title: "Images", how: "Tick TEST on a picture in the Images tab, or add your own pictures." },
  { kind: "video", title: "Videos", how: "Tick TEST on a clip in the Video tab, or add your own videos. They play whole, at their own frame rate." },
  { kind: "scene", title: "Scenes", how: "Tick TEST on a scene in the Scenes tab: its resting frame goes on the card." },
  { kind: "sound", title: "Sounds", how: "Tick TEST on a sound in the Audio tab, or add your own sounds." },
];

function ItemRow({ r, first, last, busy }) {
  const from = r.from ? r.from : "Your file";
  return html`<div class="row tc-item" key=${r.i}>
    <${Field} sm cls="tc-label" value=${r.label} placeholder="its name on the machine" readOnly=${busy}
      onChange=${() => {}} onCommit=${(v) => call("testcard.rename", r.i, v)} />
    <span class=${cx("small", r.problem ? "bad" : "muted")} ...${tip({ head: from, lines: [r.where, r.problem].filter(Boolean) })}>
      ${r.problem ? r.problem : from}</span>
    <span class="grow"></span>
    <${Button} size="sm" disabled=${busy || first} onClick=${() => call("testcard.move", r.i, -1)} title="Earlier on the machine's list">↑<//>
    <${Button} size="sm" disabled=${busy || last} onClick=${() => call("testcard.move", r.i, 1)} title="Later on the machine's list">↓<//>
    <${Button} size="sm" disabled=${busy} onClick=${() => call("testcard.remove", r.i)} title="Take it off the test card">✕<//>
  </div>`;
}

function List({ s }) {
  const rows = s.rows || [];
  return html`<div class="stack">
    <${Note}>The default PAD test card (test card, gray and color ramps, sharpness lines, full white and full black) is always on it.<//>
    ${LISTS.map((l) => {
      const mine = rows.filter((r) => r.kind === l.kind);
      return html`<div class="stack tc-list" key=${l.kind}>
        <div class="h3">${l.title + " (" + mine.length + ")"}</div>
        ${mine.length
          ? mine.map((r, k) => html`<${ItemRow} r=${r} first=${k === 0} last=${k === mine.length - 1} busy=${s.busy} />`)
          : html`<span class="small muted">${l.how}</span>`}
      </div>`;
    })}
    <div class="row">
      <${Button} drop disabled=${s.busy || s.full} onClick=${() => call("testcard.add_files")}>Add files…<//>
      <${Button} disabled=${s.busy || !rows.length} onClick=${() => call("testcard.clear")}>Clear the list<//>
      <span class="small muted">${rows.length + " of " + (s.max || 64) + " items. A file you add goes as it is; one ticked in a tab carries its color profile."}</span>
    </div>
  </div>`;
}

// Simon (2026-11-22): a test card updated over the network - the card stays small to write fast, with
// room asked for here ("Allow additional space on the test card for network updates?"), and remote
// access / Wi-Fi start-up on it as on a game card, so Send to machine can reach it
const ROOM_TIP = { head: "Space for network updates", lines: [
  "The card is kept small so it writes fast: its test files area is just big enough for what is on the list now.",
  "Tick this to give it more room, so test files you send later over the network fit. Any size you like: it has to fit on your SD card, and the image grows by the same amount, so it takes longer to write.",
  "A test card can also be grown later over the network, but that needs the machine to restart." ] };
const SSH_TIP = { head: "Remote access", lines: [
  "Puts the same remote access on the test card as the Network tab puts on a game card: this computer can reach the machine over your home network.",
  "Needed for Send to machine." ] };
const WIFI_TIP = { head: "Wi-Fi start-up", lines: [
  "For a machine on Wi-Fi: the test card starts its Wi-Fi the way the Network tab sets it up on a game card.",
  "Not needed when the machine is connected by cable." ] };

function NetworkBits({ s }) {
  const n = s.network || {};
  const busy = !!s.busy;
  return html`<div class="stack">
    <div class="row">
      <${Check} checked=${n.room} disabled=${busy} label="Allow additional space on the test card for network updates?"
        title=${ROOM_TIP} onChange=${(v) => call("testcard.set_network", "room", v)} />
      <${Field} sm type="number" width="130px" min="0.1" step="any" selectAll value=${n.room_gb} disabled=${busy || !n.room}
        suffix="GB" title="How much more room the test files area gets, in GB" onCommit=${(v) => call("testcard.set_network", "room_gb", Number(v))} />
    </div>
    <div class="row">
      <${Check} checked=${n.ssh} disabled=${busy} label="Remote access" title=${SSH_TIP}
        onChange=${(v) => call("testcard.set_network", "ssh", v)} />
      <${Check} checked=${n.wifi} disabled=${busy} label="Wi-Fi start-up" title=${WIFI_TIP}
        onChange=${(v) => call("testcard.set_network", "wifi", v)} />
      <${Check} checked=${n.band5} disabled=${busy || !n.wifi} label="5 GHz"
        title=${n.wifi ? "Wi-Fi on the 5 GHz band, as the Network tab offers it" : "Tick Wi-Fi start-up first"}
        onChange=${(v) => call("testcard.set_network", "band5", v)} />
    </div>
  </div>`;
}

function sendWhy(s) {
  const n = s.network || {};
  if (!s.source_ok) return "Pick a Spike 2 card image first";
  if (!n.ssh) return "Tick Remote access first: the test card you send must let this computer in again";
  if (!s.address) return "Find the machine on the Network tab first";
  return "";
}

function Build({ s }) {
  const msg = s.msg || ["", ""];
  return html`<div class="stack">
    <div class="row">
      <span class="k">Made from:</span>
      <span class=${cx("small", s.source && !s.source_ok ? "bad" : "")} ...${tip("The test card takes the boot and system of this card image; any Stern Spike 2 card will do. Its game is not copied.")}>
        ${s.source ? s.source + (s.source_ok ? "" : " (not there any more)") : "no card image picked yet"}</span>
      <${Button} drop disabled=${s.busy} onClick=${() => call("testcard.pick_source")}>Pick a Spike 2 card image…<//>
    </div>
    <${NetworkBits} s=${s} />
    <div class="row">
      ${s.busy
        ? html`<${Button} kind="danger" onClick=${() => call("testcard.cancel")}>Cancel<//>`
        : html`<${Button} kind="primary" disabled=${!s.source_ok} onClick=${() => call("testcard.build")}>Build test card…<//>
          <${Button} disabled=${!!sendWhy(s)} onClick=${() => call("testcard.send")}
            title=${sendWhy(s) || ("Build the test card and send it to the machine at " + s.address + ": only the files that differ go, then it restarts into the test card menu. The machine must be running a PAD test card already.")}>Send to machine…<//>`}
      <span class="small muted">${s.room_mib ? "Your videos plus " + (s.network.room_gb) + " GB of room, built in seconds. Write it to an SD card like any card image." : "Under 1 GB plus your videos, built in seconds. Write it to an SD card like any card image."}</span>
    </div>
    ${s.busy ? html`<div class="stack"><${Progress} pct=${s.pct} busy=${s.pct == null} /><span class="small">${s.step}</span></div>` : null}
    ${msg[1] ? html`<${Note} kind=${msg[0] === "ok" ? "ok" : msg[0] === "warn" ? "warn" : msg[0] === "bad" ? "err" : ""}>${msg[1]}<//>` : null}
    ${(s.log || []).length ? html`<details class="tc-log"><summary class="small">What it did</summary>
      <pre class="small mono" style="max-height:260px;overflow:auto;white-space:pre-wrap">${(s.log || []).join("\n")}</pre></details>` : null}
  </div>`;
}

export default function TestCardTab() {
  const s = useNs(NS) || {};
  const c = s.counts || {};
  const sub = "A small card that boots any Stern Spike 2 machine straight into a TEST CARD menu, with no game: "
    + "DEFAULT PAD TEST CARD, IMAGES, VIDEOS, SCENES and SOUNDS, and Color correction to tune the screen.";
  return html`<div class="page">
    <${PageHead} title="Test card" sub=${sub} />
    <${Card} style="flex:none" title="On the card" sub=${(c.image || 0) + " images, " + (c.video || 0) + " videos, " + (c.scene || 0) + " scenes, " + (c.sound || 0) + " sounds"}>
      <${List} s=${s} />
    <//>
    <${Card} style="flex:none" title="Build">
      <${Build} s=${s} />
    <//>
    <${Card} style="flex:none" title="On the machine">
      <div class="stack small">
        <span>Flippers move between the entries, START opens one, ACTION goes back. An entry with nothing on it does nothing.</span>
        <span>In a list, START shows the one picked full screen; the flippers then step to the previous and next, and START switches the color correction on and off (on a sound: plays it again).</span>
        <span>A video shows the frame rate the machine really reaches beside the one it was made at.</span>
        <span>Color correction changes brightness, contrast, saturation and each color's shades live; once the test card looks right, put the same numbers in the Color profile tab.</span>
      </div>
    <//>
  </div>`;
}
