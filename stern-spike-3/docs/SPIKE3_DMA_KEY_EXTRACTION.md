# Spike 3 — Method D: recover the key from live RAM via PCIe DMA

This is the route that survives Stern's secure boot **without running any code on the
locked CPU**. The LUKS disk key is fused into the CM4's OTP; at boot Stern's signed
`/init` reads it, unlocks the partitions, and `shred`s the temporary keyfile. But the
working key stays **live in kernel RAM** the whole time the volumes are mounted (that is
simply how dm-crypt works). A PCIe **DMA attack card** (PCILeech class) reads that RAM
directly over the bus, so the CPU never has to cooperate.

The CM4 is a removable module. For the extraction it is moved off Stern's carrier onto a
standard **Waveshare CM4-IO-BASE-A** (which exposes the CM4's PCIe lane on its M.2 slot),
the DMA card goes in that M.2 slot, and a separate host PC drives PCILeech. The machine's
own board is untouched and the CM4 goes back when finished.

## Status: viable, but the last link is unproven

Verified from the Star Wars SD image (`boot.img`, the signed device tree):

- **PCIe is enabled** in Stern's signed `bcm2711-rpi-cm4.dtb` (`/scb/pcie@7d500000`,
  no `status` override). The root complex comes up.
- **Inbound DMA window = low 3 GB.** The pcie node's `dma-ranges` is
  `cpu_base=0x0, size=0xC0000000`. External PCIe devices can DMA into physical RAM
  `0x0`–`0xC0000000`.
- **The module is a ~2 GB CM4 Lite** (Samsung LPDDR4, BCM2711 C0, onboard WiFi). All of
  its RAM sits inside the 3 GB window, so the key's page is reachable wherever the kernel
  put it.
- Stern uses the CM4's **native** USB (`dtoverlay=dwc2` / `otg_mode=1`), so PCIe is
  unused on their board — nothing competes for the lane on the test carrier.

Still unproven, and the whole route hinges on it:

- **Will `pcileech-fpga` enumerate and DMA through the BCM2711 root complex?** There is no
  published case of PCILeech run against a Pi/CM4 target; it is x86-proven only. Two
  BCM2711 PCIe quirks may need gateware attention: it **cannot do 64-bit accesses (use
  32-bit)** and has a **single outbound window**. Treat this attempt as the experiment
  that answers the question.

## THE ONE RULE (unchanged, non-negotiable)

Nothing in this procedure writes to the machine. Specifically:

- **Never** program, flash, provision, or write OTP or the bootloader EEPROM. No
  `rpi-eeprom`, no `program_pubkey`, no `revoke_devkey`, no `vcmailbox 0x00038021`
  (SET_CUSTOMER_OTP), no `usbboot recovery/`. This route does not even need the OTP read
  one-liner — the key is taken from RAM, not from fuses.
- The Stern SD card is only ever **read** (cloned). Work from the clone, never the original.
- The CM4 is reseated in the machine unchanged at the end.

## Hardware

- Waveshare **CM4-IO-BASE-A** carrier (already owned).
- An **M.2 M-key** PCILeech-class DMA card (e.g. CaptainDMA M.2, ScreamerM2, or an M.2
  Squirrel). Base/no-firmware variant is fine; the "emulated firmware" upsell is for
  evading game anti-cheat and is not needed here.
- A **host PC** to run PCILeech (Linux is the smoothest), plus the card's USB-C/USB3 cable.
- A **microSD** at least as large as the Stern card, and a full-size SD reader to clone from.
- Optional: an HDMI monitor on the carrier just to watch the CM4 boot.

## Procedure

### 0. Clone the Stern card (read-only) to a microSD
Put the Stern SD in the host, make a **byte-for-byte clone** onto the microSD
(`dd`, Win32DiskImager "read", or balenaEtcher clone). The clone boots identically because
the key is in the CM4's fuses, not on the card. This both protects the original and fits
the carrier's microSD slot. Set the original aside.

### 1. Prepare the DMA card
If the card is not pre-flashed, load the stock **`pcileech-fpga`** gateware for its FPGA
over its onboard USB/JTAG. Keep the BCM2711 quirks in mind (32-bit accesses, single
window) in case the default config needs adjustment.

### 2. Build the bench rig (ESD precautions)
Powered off and grounded:
1. Remove the CM4 from Stern's board — 4 screws, then gently and evenly lift it off the two
   100-pin board-to-board connectors. Do not flex the module.
2. Seat the CM4 on the CM4-IO-BASE-A (same connectors, press down evenly, replace screws).
3. Insert the DMA card into the carrier's **M.2 slot** (underside), secure the 2280 screw.
4. Insert the **microSD clone**.
5. Connect the DMA card to the host PC over USB-C. (Optionally attach HDMI to watch boot.)
   Do **not** attach any of Stern's cabinet wiring.

### 3. Bring up PCILeech on the host
Install PCILeech, then confirm it sees the FPGA device before powering the target, e.g.:

```
pcileech -device fpga probe
```

If the card enumerates as a device, you are ready.

### 4. Power on the CM4 and let it decrypt
Power the carrier. The CM4 boots Stern's signed image from the microSD; the initramfs
reads OTP and `luksOpen`s the partitions within a second or two, loading the dm-crypt
master key into kernel RAM. It may then reach the game, or panic for lack of Stern's
hardware — **either is fine**, the key is already resident (a panic just freezes it in RAM).
Give it ~30–60 s.

### 5. Dump the reachable RAM
From the host, dump the low 3 GB window (all of this CM4's RAM):

```
pcileech dump -device fpga -out cm4_ram.raw -min 0x0 -max 0xC0000000
```

(Exact flags vary by PCILeech version. If full-range reads misbehave, dump in smaller
spans and/or force 32-bit accesses per the BCM2711 quirk.)

### 6. Recover the key from the dump
Two independent targets, search for both:

- **dm-crypt master key (reliable — always resident while mounted).** Run an AES-key
  scanner over the dump:
  ```
  aeskeyfind cm4_ram.raw
  ```
  The volumes are `aes-xts-plain64`, `key_size 32` (AES-128-XTS = two 16-byte AES keys per
  volume). `aeskeyfind` will surface AES-128 schedules; the XTS pair is the master key.
- **The OTP keyfile (cleanest — one 32-byte value unlocks all four volumes).** Stern
  `shred`s its copy, but stale copies may linger in freed buffers. Slide a 32-byte window
  over the dump and test candidates against a real LUKS header we already have:
  ```
  python tools/luks_otp.py verify <p2_header.bin> --key-hex <64hex>
  ```

### 7. Verify and settle global-vs-per-device
Once a candidate verifies against the Star Wars header, test it against the **Pokemon** and
**Walking Dead** images' headers too (all three raw images are on hand). If it verifies on
all three, the key is shared across machines/titles — one read decrypts the catalogue.

### 8. Decrypt
Follow [KEY_EXTRACTION.md](KEY_EXTRACTION.md) "Once you have the key" to verify + decrypt
partitions with `tools/luks_otp.py`, and to recover the fixed `.spk` key.

### 9. Teardown
Power off, remove the CM4 from the carrier, reseat it in Stern's board (connectors +
4 screws), and boot the machine once to confirm it is happy. Nothing was written; the
machine is exactly as it was.

## If it fails

- **PCILeech can't see / enumerate the FPGA once it's in the CM4's slot** → this is the
  unproven `pcileech-on-BCM2711` link failing. Try a 32-bit-only PCILeech configuration, a
  different `pcileech-fpga` device profile, or a firmware build tuned for the single
  outbound window. If nothing enumerates, this route is closed and the honest conclusion is
  that the wall holds.
- **Dump works but no key found** → dump again immediately after the unlock (earlier in
  boot, before buffers are reused), and prioritise the dm-crypt master key via `aeskeyfind`
  over the shred'd OTP keyfile. A key page above 3 GB is only possible if the module turns
  out to be larger than 3 GB of RAM (it is ~2 GB), so reachability is not the suspect here.

## Appendix: verified facts (from the Star Wars image)

- `config.txt` (inside the signed `boot.img`, the operative one) sets `enable_uart=1` but
  leaves `uart_2ndstage` commented, and `cmdline.txt` routes console to `tty1` (HDMI) only.
  That is why the serial UART is silent (the `00 00` capture). It also carries Stern's own
  note that the signed `config.txt` "can't [be] change[d] and expect the image to still
  boot" — the plaintext `config.txt` on the FAT partition is ignored.
- Device tree: `/scb/pcie@7d500000` enabled; `dma-ranges` inbound window `0x0`–`0xC0000000`.
- Module: BCM2711 C0, Samsung LPDDR4 (~2 GB), CM4 Lite + WiFi.
