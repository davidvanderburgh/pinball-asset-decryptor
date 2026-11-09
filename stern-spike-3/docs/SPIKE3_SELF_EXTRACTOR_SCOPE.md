# Spike 3 OTP keyfile self-extractor — feasibility scope (PAD-1086)

*Scope pass. Decides what a software-only, user-runnable key-extraction flow can
and cannot do, and the PAD step shape worth building. No key value appears in
this repo; the recovered universal keyfile stays private.*

## Why this exists

The Spike 3 SD is LUKS2-encrypted under a 256-bit key fused into the CM4's
**customer OTP**. The signed `/init` reads it (`vcmailbox 0x00030021`), writes the
raw 32 bytes to `/ktmp`, `luksOpen`s all four volumes (p2 rootfs, p3 data, p5
connectivity, p6 games), then `shred`s `/ktmp`. The key is **universal /
fleet-wide** — one board's read decrypts every title on any PC — and it has
already been recovered (DMA, 2026-11-09; held privately).

So the key is not what's missing. What's missing is a way for an **ordinary
owner** to obtain it from **their own** board without the DMA rig, so PAD can
ship the *method* and keep the master key out of the public tree. That posture
(ship the tool, user brings the hardware) is what keeps PAD off the wrong side of
the §1201 trafficking line — the same "you bring the card" shape as the Spike 2
codec oracle. Committing the universal key instead would make a public repo the
circumvention artifact, permanently and irreversibly.

## Feasibility by board lock-state

The read path depends entirely on whether the board **enforces** Raspberry Pi
secure boot (SIGNED_BOOT=1 + customer-key-hash fused, OTP rows 47–54). This
cannot be told from the SD image; it's a per-board fuse state.

### Un-enforced boards — FEASIBLE, software-only, already built
Early/service/dev units, or modules where secure boot was never fused, will boot
unsigned/modified code. The existing **Method A** tool already does exactly the
self-extract:

- `stern-spike-3/tools/build_extractor_card.py` patches the initramfs so `/init`
  writes the key (read byte-for-byte as Stern does) to `OTP_KEY.TXT` on the FAT
  boot partition (p1) — readable on any PC. Game boot is otherwise unchanged.
- No DMA, no shell, no SD surgery beyond swapping two files on a FAT partition.
  `--no-sig` + deleting `boot.sig` is also the definitive enforced-vs-not test.
- On-board read is validated by `stern-spike-3/tools/spike3_otp_probe.sh`
  (read-only; refuses a malformed/partial key rather than emitting a wrong one),
  and the result verifies offline with `stern-spike-3/tools/luks_otp.py verify`.

**Self-extractor work here is packaging/UX, not new mechanism**: turn Method A
into a one-click PAD step (build card image → user boots → pull card → read
`OTP_KEY.TXT`), auto-validate the key, and ingest it as the user-supplied key for
PAD-1072's extraction.

### Enforced / hardened boards — NOT feasible by software alone (field-confirmed)
Every software/USB/network/serial route is walled or absent. From
`SPIKE3_HANDOFF.md` §5, field-confirmed on a real board (2026-09-07):

- **Modified extractor card** → signature check rejects the patched `boot.img`;
  we don't have Stern's signing key. Method A is closed here.
- **rpiboot / USB OTP read** → DEFINITIVELY WALLED. Secure boot gates every stage
  that could run `vcmailbox`; usbboot mass-storage is disabled once locked. A
  rpiboot *connect* is not a bypass.
- **Network shell (Method B)** → no inbound/listening surface. `conagent` /
  Insider is outbound-only HTTPS and never carries the key. No sshd/dropbear/
  telnet. No network RCE door.
- **Serial console (Method C)** → initramfs has no getty; `config.txt` routes the
  console to **tty1 (HDMI) only**, no `console=ttyS0`. The serial line goes quiet
  after kernel handoff. A login would need a `serial-getty` unit inside the
  (formerly unreadable) rootfs.

For hardened boards the only proven route is the **DMA RAM dump** (what actually
worked), which needs the hardware rig and is **out of scope** for a software-only
self-extractor.

## The one genuinely-open, non-DMA lead for hardened boards

A hardened board still runs Stern's **own signed OS** after `switch_root`. If that
OS offers a **local login or shell** reachable with obtainable credentials, a user
with just an HDMI display + USB keyboard could run `spike3_otp_probe.sh` and read
the key — no DMA, no SD surgery, no signature break, secure boot fully intact.
Candidates: a getty on tty1, the operator/service menu offering a shell-escape or
command exec, or a local web UI.

In September these were **open questions gated on the encrypted rootfs**. They are
now answerable **at a desk**, because the rootfs is decrypted (universal keyfile,
held privately). The recommended next step is pure config review of the real
rootfs:

- `/etc/passwd`, `/etc/shadow` — any account with a blank/default/weak or known
  password, or a login shell.
- getty / `serial-getty` / autologin units (systemd), and which tty they bind.
- the app's service/diagnostic-menu code — any shell-out, command field, or
  file-manager surface; any local web UI and whether it exposes exec.
- `cmdline.txt` / `config.txt` console routing as actually booted.

This is configuration review on data we already hold — **not** exploit
development. If the only way in turns out to be cracking a strong `/etc/shadow`
hash or exploiting a daemon, it stops there and the board stays DMA-only. In
particular the `conagent` memory-safety-bug lead is **explicitly out of scope**
(flagged exploit-dev, safety-declined) and must not be pursued as a bypass.

## Explicitly out of scope / do not re-explore
- **OTP-HANG card as a software route** — it only *freezes the key resident in
  RAM*; reading it still needs DMA. Not software-only. (Corrects this ticket's
  opening assumption.)
- DMA RAM dump (hardware rig) — the hardened-board route, but not "software-only".
- rpiboot/USB read, SPI-EEPROM-as-key-source, `.spk` forge, `conagent` bug hunt —
  all dead/walled/declined per handoff §5.

## Proposed PAD step shape
1. **Build OTP-read card** — wrap `build_extractor_card.py` behind a PAD action
   that takes a Spike 3 `*.raw` (or `BOOT.IMG`) and emits the patched card files
   + clear deploy/read-back instructions.
2. **Lock-state detect-and-branch** — the card's own boot *is* the enforced-vs-not
   test. Boots + `OTP_KEY.TXT` present → done (un-enforced). Won't boot → report
   "secure boot enforced: software extraction not possible on this board" and
   point to the DMA route (and, if the rootfs recon lands a credentialed local
   login, to that path).
3. **Ingest + verify** — read `OTP_KEY.TXT`, validate with `luks_otp.py verify`,
   hand the verified key to PAD-1072 as the user-supplied key. **Never written to
   the repo**; lives only in the user's PAD working area.

## Hard constraints
- The universal OTP keyfile / master key NEVER enters the repo — not as a fixture,
  test vector, or doc. Private OneDrive research folder only.
- Any extractor must be proven on **real CM4 hardware**; the emulator cannot stand
  in for the OTP fuse read. Method A is already proven for the un-enforced case.

## Residual risk (on the record)
Because the key is universal, any self-extractor means the keyfile will leak into
the wild the first time a user runs it and posts the bytes. Accepted: "PAD shipped
a tool, a user leaked the key" is a materially different posture from "PAD shipped
the master key," and only the latter puts PAD in the trafficking seat.

## Verdict + open questions (recommended answers)
**Verdict:** a software-only self-extractor is real and mostly-built for
**un-enforced** boards (productize Method A); it is **impossible by software** for
**hardened** boards (field-confirmed) short of DMA — unless the rootfs recon turns
up a credentialed local login, which is the single cheap desk-work lead worth
chasing before concluding hardened = DMA-only.

- *Build the self-extractor now, or stop at scope?* → **Recommend: do the rootfs
  local-login recon first (cheap, desk-only), then build the Method-A PAD step.**
  Other option: build the Method-A PAD step immediately and file the recon
  separately.
- *Should the Method-A PAD step ship even though it only helps un-enforced
  boards?* → **Recommend: yes** — it's the honest accessible path for the boards
  that allow it, and it gives every other user a clear, correct lock-state answer
  instead of a mystery. Other option: hold until the recon settles whether a
  hardened-board path exists.
