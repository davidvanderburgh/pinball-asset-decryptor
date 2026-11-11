// PAD-1133: "How to get the OTP key" - the guide shown from the Spike 3 key
// gate (shell.js Spike3KeyGate) and the Extract unlock panel (tabs/extract.js
// Spike3UnlockPanel).
//
// Every shipped Spike 3 board enforces Raspberry Pi secure boot, so every
// software / card / network / serial route to the OTP key is walled.  The ONE
// route that recovers it is a hardware PCIe RAM dump (DMA) of the running CM4:
// a Captain DMA / PCILeech card in a Waveshare CM4-IO-BASE-A carrier, booting
// a signed image that still has PCIe enabled (Stern disabled PCIe in every
// build after the early Star Wars 0.84 release, so a user's own current card
// will not work), with PCILeech on a host PC (the Pi's RAM sits at PCIe bus
// 0x400000000; aeskeyfind over the dump; PAD verifies the key).
//
// David (PAD-1133): put as much of the method in the app as makes sense, then
// point people to the PAD Discord for the hands-on help - the capture-card
// firmware, the recovery kit, and sourcing the PCIe-enabled boot image, none
// of which PAD can hand over inside the app (the image is Stern's signed
// firmware and is never redistributed). No key value appears here or in the repo.
import { html, useState, Button, Icon, Modal, call } from "./ui.js";

// A single "How to get the OTP key" button that opens the guide.
export function Spike3KeyGuide({ disabled }) {
  const [open, setOpen] = useState(false);
  return html`
    <${Button} size="sm" kind="ghost" icon="help" disabled=${disabled}
      onClick=${() => setOpen(true)}>How to get the OTP key…<//>
    ${open ? html`<${Spike3KeyGuideModal} onClose=${() => setOpen(false)} />` : null}`;
}

function Spike3KeyGuideModal({ onClose }) {
  const footer = html`
    <${Button} kind="" icon="discord" onClick=${() => call("shellx.open_discord")}>Ask on Discord<//>
    <${Button} kind="primary" onClick=${onClose}>Got it<//>`;
  return html`<${Modal} title="How to get your Spike 3 OTP key" icon="unlock"
      wide onClose=${onClose} cls="s3guide" footer=${footer}>
    <div class="s3guide-bd stack">
      <p>Your Spike 3 machine encrypts its SD card with a 256-bit key burned into
        the machine's Raspberry Pi (the CM4 module), not kept on the card. PAD
        never ships this key. It is the same key on every Spike 3 machine, so it
        only has to be read once; PAD then keeps it and unlocks every Spike 3 card
        you own.</p>

      <p>Every shipped board locks the Pi's secure boot, so there is no software
        trick, patched SD card, network login or serial console that can read the
        key - they are all closed off. The one way that works is to read it
        straight out of the machine's memory while it runs, with a PCIe capture
        card. This is an advanced hardware job. The whole method is below, and
        our <b>Discord</b> can help with the parts that are hard to get.</p>

      <h3>What you need</h3>
      <ul class="s3guide-steps">
        <li>A <b>Waveshare CM4-IO-BASE-A</b> carrier board - it exposes the CM4's
          PCIe lane on an M.2 slot and takes a microSD.</li>
        <li>A <b>Captain DMA</b> (PCILeech-class) M.2 capture card, flashed with a
          <code>pcileech-fpga</code> build set up for the Pi's PCIe (Gen1, 32-bit
          DMA). A stock or unflashed card will not enumerate - ask on Discord for
          the right firmware.</li>
        <li>A <b>host PC</b> running <a href="https://github.com/ufrisk/pcileech"
          target="_blank" rel="noopener">PCILeech</a> with the card's FTDI (FT601)
          USB driver, on a <b>USB 3</b> port.</li>
        <li>A <b>microSD</b> and a full-size SD reader, plus an anti-static strap
          and a precision screwdriver.</li>
      </ul>

      <h3>The boot image (the hard part)</h3>
      <p>The capture only works if the Pi boots a signed image that still has PCIe
        turned on. Stern turned PCIe off in every build after the early Star Wars
        2025 release (0.84), and the card in your machine has it off - so
        you <b>cannot</b> use your own card. You need that early PCIe-enabled signed
        image, which Stern no longer distributes (and a very new board may refuse
        it). Sorting this out is most of the battle; come to Discord for help.</p>

      <h3>Read the key</h3>
      <ol class="s3guide-steps">
        <li>Powered off and grounded, lift the <b>CM4 module</b> off Stern's board
          (screws, then evenly off the two board-to-board connectors) and seat it
          on the Waveshare carrier.</li>
        <li>Put the Captain DMA card in the carrier's M.2 slot and the microSD
          (with the PCIe-enabled image) in its slot; leave the boot jumper off.
          Connect the card's USB-C to a USB 3 port on the host PC, then power the
          carrier.</li>
        <li>Let it boot 30-60 seconds. It may reach the game or just sit there -
          either is fine; the key is in memory as soon as the card unlocks.</li>
        <li>On the host, run PCILeech's probe and confirm the card enumerates (a
          Xilinx endpoint). Then dump the Pi's memory. The window is offset: the
          Pi's RAM starts at PCIe bus address <code>0x400000000</code>, not 0 -
          dump from there.</li>
        <li>Find the key in the dump with <code>aeskeyfind</code>. PAD checks any
          candidate for you - paste it in and a good one verifies against your
          card; a wrong one is rejected, never used.</li>
        <li>Power off and put the CM4 back on Stern's board (connectors, screws),
          then boot the machine once to confirm it is happy. Nothing was written
          to it.</li>
      </ol>
      <p class="s3guide-note"><${Icon} name="warn" /> The one rule: only ever
        <b>read</b>. Never program, flash or write the OTP fuses or the
        bootloader - that can brick the board for good. This method only reads the
        Pi's memory.</p>

      <p>Once you have the 64-character key, paste it into the key box above
        (or use <b>Choose a key file…</b>). PAD checks it against this card, unlocks
        extraction, and keeps it for every Spike 3 tab and every Spike 3 card you
        own. Stuck on the firmware, the recovery kit or the boot image? Join our
        Discord and we will walk you through it.</p>
    </div>
  <//>`;
}
