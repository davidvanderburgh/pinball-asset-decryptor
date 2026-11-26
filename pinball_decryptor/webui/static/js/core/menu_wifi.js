// The Wi-Fi a test card or a multi-boot card's menu joins with no game running (core/menu_network.py) - one saved
// network for the Test card and Multi-boot tabs. PAD keeps its name and the key Wi-Fi makes from the password,
// never the password itself.
import { html, Button, Field, tip, call, cx, useState, openMenu } from "./ui.js";

// Simon (2026-11-26): the test card on the network with no game running - the wired port always, and this Wi-Fi
const MENU_WIFI_TIP = { head: "Wi-Fi with no game running", lines: [
  "Stern's game keeps your Wi-Fi name and password to itself, so the test card and the boot menu cannot use them: give them here and they join that network while they are showing, so this computer can reach the machine.",
  "The wired port is always started too. Leave the password empty for an open network. One network is saved for the Test card and Multi-boot tabs.",
  "PAD keeps the network name and the key Wi-Fi makes from your password, not the password itself; the card holds that key in a file only the machine's system can read." ] };

// Simon (2026-11-26): "if the PC or machine PAD is running on has a wireless facility to scan for access points
// then ideally we should let them do that ... make sure they can still manually enter tho"
const SCAN_TIP = { head: "Scan for Wi-Fi networks", lines: [
  "This computer: the networks this PC's Wi-Fi can see.",
  "The machine: the networks the machine itself can see, over remote access, while its game runs. This is the better list: Stern's Wi-Fi adapter sees 2.4 GHz networks only.",
  "Pick one to fill in the name, or type the name yourself." ] };

function ScanList({ scan, onPick }) {
  if (!scan) return null;
  if (scan.busy) return html`<span class="small muted">${"Scanning " + (scan.where === "machine" ? "from the machine" : "from this computer") + "…"}</span>`;
  if (!scan.ok) return html`<span class="small bad">${scan.why}</span>`;
  return html`<div class="stack tc-scan">
    <span class="small muted">${(scan.where === "machine" ? "The machine sees " : "This computer sees ") + scan.networks.length + " network" + (scan.networks.length === 1 ? "" : "s") + ". Pick yours:"}</span>
    ${scan.networks.map((w) => html`<div class="row" key=${w.name}>
      <${Button} size="sm" onClick=${() => onPick(w.name)}
        title=${w.name === scan.current ? "The network it is joined to now" : "Use this network"}>${w.name}<//>
      <span class="small muted">${[w.signal + "%", w.band, w.secure === false ? "open" : w.secure ? "secured" : "",
        w.name === scan.current ? "joined now" : ""].filter(Boolean).join(" · ")}</span>
    </div>`)}
  </div>`;
}

// *saved*: {name, open} as the page may see it; *address*: the machine's, for a scan from it; *off*: why the line
// is greyed ("" when live); *label*: the line's own words; *onSaved*: after Save / Forget (the host re-reads)
export function MenuWifi({ saved, address, off = "", label = "Wi-Fi with no game running:", onSaved }) {
  const busy = !!off;
  const [name, setName] = useState(saved.name || "");
  const [pw, setPw] = useState("");
  const [why, setWhy] = useState("");
  const [scan, setScan] = useState(null);
  const done = (w) => { setWhy(w || ""); if (onSaved) onSaved(); };
  const save = async () => { done(await call("testcard.set_menu_wifi", name, pw)); setPw(""); };
  const forget = async () => { setName(""); setPw(""); done(await call("testcard.set_menu_wifi", "", "")); };
  const doScan = async (where) => {
    setScan({ busy: true, where });
    const got = (await call("testcard.scan_wifi", where)) || { ok: false, why: "The scan did not answer." };
    setScan({ ...got, where });
  };
  const scanMenu = (e) => openMenu(e.currentTarget, [
    { label: "From this computer", onClick: () => doScan("pc") },
    { label: "From the machine", onClick: () => doScan("machine"), disabled: !address,
      title: address ? "Over remote access, at " + address : "Find the machine on the Network tab first" },
  ]);
  return html`<div class="stack">
    <div class="row wrap" ...${tip(MENU_WIFI_TIP)}>
      <span class="k">${label}</span>
      <${Field} sm width="180px" value=${name} placeholder="network name" readOnly=${busy}
        onChange=${setName} onCommit=${setName} />
      <${Field} sm type="password" width="180px" value=${pw} readOnly=${busy}
        placeholder=${saved.name ? "password (key saved)" : "password"} onChange=${setPw} onCommit=${setPw} />
      <${Button} size="sm" disabled=${busy || (scan && scan.busy)} onClick=${scanMenu} title=${SCAN_TIP}>Scan…<//>
      <${Button} size="sm" disabled=${busy || !name.trim()} onClick=${save}>Save<//>
      <${Button} size="sm" disabled=${busy || !saved.name} onClick=${forget}>Forget<//>
    </div>
    <span class=${cx("small", why ? "bad" : "muted")}>${why || off
      || (saved.name ? "Joins “" + saved.name + "”" + (saved.open ? " (an open network)" : "") + " while it shows, and the wired port."
        : "No Wi-Fi given: only the wired port is started.")}</span>
    ${!busy ? html`<${ScanList} scan=${scan} onPick=${(v) => { setName(v); setScan(null); }} />` : null}
  </div>`;
}
