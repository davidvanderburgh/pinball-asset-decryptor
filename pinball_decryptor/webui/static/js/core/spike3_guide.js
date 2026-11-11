// PAD-1133: "How to get the OTP key" - a short, verified guide shown from the
// Spike 3 key gate (shell.js Spike3KeyGate) and the Extract unlock panel
// (tabs/extract.js Spike3UnlockPanel).
//
// Every shipped Spike 3 board enforces Raspberry Pi secure boot (David,
// PAD-1133), so every software/card/network/serial route to the OTP key is
// walled - the patched "extractor card" simply will not boot.  The ONE route
// that has actually yielded the key is a hardware PCIe RAM dump (DMA) of the
// running CM4: a Captain DMA / PCILeech card in a Waveshare CM4-IO-BASE-A
// carrier, booting the known-good Star Wars 0.84 SD image, with PCILeech on a
// host PC.  That procedure is what this guide documents, matching
// stern-spike-3/docs/SPIKE3_DMA_KEY_EXTRACTION.md (the route that worked,
// 2026-11-09).  No key value appears here or anywhere in the repo.
import { html, useState, Button, Icon, Modal } from "./ui.js";

// A single "How to get the OTP key" button that opens the guide.
export function Spike3KeyGuide({ disabled }) {
  const [open, setOpen] = useState(false);
  return html`
    <${Button} size="sm" kind="ghost" icon="help" disabled=${disabled}
      onClick=${() => setOpen(true)}>How to get the OTP key…<//>
    ${open ? html`<${Spike3KeyGuideModal} onClose=${() => setOpen(false)} />` : null}`;
}

function Spike3KeyGuideModal({ onClose }) {
  return html`<${Modal} title="How to get your Spike 3 OTP key" icon="unlock"
      wide onClose=${onClose} cls="s3guide"
      footer=${html`<${Button} kind="primary" onClick=${onClose}>Got it<//>`}>
    <div class="s3guide-bd stack">
      <p>Your Spike 3 machine encrypts its SD card with a 256-bit key burned into
        the machine's Raspberry Pi (the CM4 module), not kept on the card. PAD
        never ships this key. You read it once from your own machine; PAD then
        keeps it and unlocks every Spike 3 card you own, because the key is the
        same on every machine.</p>

      <p>Every Spike 3 board locks the Pi's secure boot, so there is no software
        trick, patched SD card, network login or serial console that can read the
        key - they are all closed off. The one way that actually works is to read
        it straight out of the machine's memory while it is running, with a PCIe
        capture card. This is an advanced hardware job; here is the whole of it.</p>

      <h3>What you need</h3>
      <ul class="s3guide-steps">
        <li>A <b>Captain DMA</b> (PCILeech-class) M.2 capture card.</li>
        <li>A <b>Waveshare CM4-IO-BASE-A</b> carrier board - it exposes the CM4's
          PCIe lane on its M.2 slot and takes a microSD.</li>
        <li>A <b>host PC</b> to run <a href="https://github.com/ufrisk/pcileech"
          target="_blank" rel="noopener">PCILeech</a>, plus the card's USB-C cable.</li>
        <li>A <b>microSD</b> and a full-size SD reader.</li>
      </ul>

      <h3>Read the key</h3>
      <ol class="s3guide-steps">
        <li>Put a <b>Star Wars 0.84</b> SD image on the microSD (that build is
          known to boot cleanly on the bench carrier). You can clone your own
          Stern card instead - the key is in the Pi, not on the card, so any
          Spike 3 card boots the same - but the 0.84 image is the safe choice.
          Only ever <b>read</b> your Stern card; work from the clone.</li>
        <li>Flash the stock <code>pcileech-fpga</code> firmware onto the Captain
          DMA card if it is not pre-loaded.</li>
        <li>Powered off and grounded, lift the <b>CM4 module</b> off Stern's board
          (4 screws, two board-to-board connectors) and seat it on the Waveshare
          CM4-IO-BASE-A. Put the Captain DMA card in the carrier's M.2 slot and
          the microSD in its slot. Connect the DMA card to the host PC over USB-C.
          Do not wire up any of the cabinet.</li>
        <li>On the host, start PCILeech and confirm it sees the card
          (<code>pcileech -device fpga probe</code>).</li>
        <li>Power the carrier on. The CM4 boots, reads its OTP and unlocks the
          card, which loads the key into memory. It may reach the game or just
          sit there - either is fine. Give it 30-60 seconds.</li>
        <li>Dump the Pi's memory from the host:
          <code>pcileech dump -device fpga -out cm4_ram.raw -min 0x0 -max 0xC0000000</code>.</li>
        <li>Find the key in the dump: run <code>aeskeyfind cm4_ram.raw</code> to
          surface the disk key. PAD checks any candidate for you - a good one
          verifies against your card's header; a wrong one is rejected, never
          used.</li>
        <li>Power off and put the CM4 back on Stern's board (connectors, 4 screws)
          and boot the machine once to confirm it is happy. Nothing was written to
          it.</li>
      </ol>
      <p class="s3guide-note"><${Icon} name="warn" /> The one rule: never program,
        flash or write the OTP fuses or the bootloader. This route only ever reads.
        Writing them can brick the board for good.</p>

      <p>Once you have the 64-character key, paste it into the key box above
        (or use <b>Choose a key file…</b>). PAD checks it against this card, unlocks
        extraction, and keeps it for every Spike 3 tab and every Spike 3 card you
        own.</p>
    </div>
  <//>`;
}
