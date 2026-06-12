# Stern Spike 3 — getting the OTP key, then decrypting

The encryption is fully understood (see [REVERSE_ENGINEERING.md](REVERSE_ENGINEERING.md))
and decryption runs entirely on a PC. The one thing not in the SD image is the
256-bit key, fused into the Raspberry Pi CM4's customer OTP. It must be read
**once** from a physical Spike 3 board. This doc covers the ways to do that, and
what to do once you have it.

If the key turns out to be **global** (shared across machines — plausible for
golden release images, but unproven), one read decrypts every Spike 3 game on
any PC forever. The first key recovered should be tested against all three game
images to settle that (see "Once you have the key").

---

## The gatekeeper: Raspberry Pi secure boot

Stern signs `boot.img` (`boot.sig` carries an RSA-2048 signature). If the board
**enforces** RPi secure boot — `SIGNED_BOOT=1` in the bootloader EEPROM plus the
public-key hash burned in OTP — then the bootloader only runs a boot image signed
with Stern's private key. That has two consequences:

1. Any **modified** boot image (Method A) is rejected → the patched card won't
   boot (harmless; restore the original files).
2. You can't run your own code at all, so the only code that ever touches the OTP
   is Stern's signed `/init`, which reads the key and immediately `shred`s it.

Enforcement **cannot be determined from the SD image** — it depends on OTP fuses
and the EEPROM config that live on the board. On a board you control you can check
it directly: `vcgencmd otp_dump` (secure-boot/customer-key rows). Given Stern went
to the trouble of LUKS + OTP, enforcement is *likely* but not certain — so
Method A is a cheap, safe test, and Methods B/C are the fallback if it's enforced.

---

## Method A — Extractor card (built; works only if secure boot is NOT enforced)

Patch the initramfs so that, at boot, `/init` writes the key (read exactly as
Stern does) to `OTP_KEY.TXT` on the FAT boot partition — readable on any PC. The
rest of boot is unchanged, so the machine still boots the game.

Build it (pure Python, cross-platform — no WSL, no cryptsetup):

```
python tools/build_extractor_card.py <BOOT.IMG | whole_image.raw>  -o out/
# -> out/boot.img  (patched)   out/boot.sig  (SHA-256 line regenerated)
```

Input can be a `BOOT.IMG` copied off the card's first (FAT) partition, or a whole
`*.raw` SD image (it extracts `boot.img`/`boot.sig` from partition 1 itself,
reading only that partition — safe on 60 GB files). Because `boot.img` is
byte-identical across all current Spike 3 games, one patched image fits any of
them.

Deploy + read back (≈10 min, zero risk if you keep backups):

1. Power off, remove the SD, put it in a PC. Its **first partition is FAT** and
   mounts anywhere; the rest look unreadable (encrypted) — ignore them.
2. **Back up** the card's original `boot.img` and `boot.sig`.
3. Copy the patched `boot.img` + `boot.sig` onto that partition, overwriting.
   (Alternatively, delete `boot.sig` entirely — some non-secure-boot configs boot
   a ramdisk without a sig. Keep your backup either way.)
4. Put the card back, power on.
   - **Boots to the game** → key was dumped (step 5). (Secure boot is *not*
     enforced.)
   - **Won't boot / blank** → secure boot **is** enforced. Power off, restore the
     backup. Method A is closed; use Method B/C. (No harm done — a failed
     signature check just halts.)
5. Power off, bring the card to a PC, read `OTP_KEY.TXT` (64 hex chars) from the
   FAT partition. If it's missing but the machine booted, the key was also written
   raw to the **last 512-byte sector** of the FAT partition as a fallback (read
   that sector's first 64 hex chars).
6. Restore the original `boot.img` + `boot.sig` so the machine updates normally.

The patch only adds a key-dump and never alters the encrypted partitions or game
data.

## Method B — SSH / network shell (follow-up; survives secure boot)

If a board is reachable on the network with a shell, you skip secure boot
entirely: just run Stern's own pipeline and print the key.

```sh
vcmailbox 0x00030021 40 40 0 8 0 0 0 0 0 0 0 0 \
  | awk '{print substr($0,77,88)}' | xxd -r -p | xxd -p
# -> 64 hex chars = the 32-byte keyfile
```

Open questions to make this work (investigate on a live machine, or once Method A
yields a key and we can decrypt+read the `rootfs`/`connectivity` partitions):

- **Is there an sshd / dropbear / telnet listening?** The dedicated
  `connectivity` partition and Stern "Insider Connected" networking strongly imply
  a network stack. `nmap` a machine on the LAN (22/23/80/443 and high ports).
- **Credentials.** Once we have *one* key (via Method A or a cooperating owner),
  decrypt `rootfs` with [../tools/luks_otp.py](../tools/luks_otp.py) and read:
  `/etc/passwd`, `/etc/shadow`, `/etc/ssh/sshd_config`,
  `/root/.ssh/authorized_keys`, any dropbear keys, and the systemd units that
  start the app/network — this tells us whether remote shell is enabled and how
  to authenticate. That turns Method B into a no-hardware-modification route for
  every future machine/version.
- **Service / diagnostic menu.** Stern machines have an operator menu; check for a
  hidden engineering/diagnostic mode or a local web UI that exposes a shell or
  command execution.

This is the cleanest long-term path (no SD surgery, no secure-boot dependency),
but it is gated on discovering the remote-access surface, which currently requires
either a live machine to probe or one decrypted `rootfs` to read.

## Method C — Serial console (follow-up; survives secure boot)

`config.txt` enables UART (`enable_uart=1`, console on `tty1` / `ttyS0`, plus the
aux ports `ttyAMA4/5`). With a USB-TTL adapter on the Spike 3 service UART you may
get a console. If the booted OS offers a login or the boot drops to a shell, run
the same `vcmailbox … | awk … | xxd` one-liner. Whether a usable login exists
depends on the rootfs config (see Method B — reading the decrypted rootfs answers
this too). Lower-effort than full RE, but needs physical access to the board's
UART header.

---

## Once you have the key

The keyfile is 64 hex chars (32 bytes). Verify and decrypt offline:

```sh
# verify against a real header (settles global-vs-per-device by trying all 3 games)
python tools/luks_otp.py verify  <p2_header.bin> --key-hex <64hex>
python tools/luks_otp.py verify  <p2_header.bin> --otp-words 0x..,0x..,0x..,..  # 8 words

# decrypt sectors of a partition once the key verifies
python tools/luks_otp.py decrypt <image.raw> --header <p2_header.bin> \
    --part-base-lba <LBA> --key-hex <64hex> --sector 0 --count 8 --out plain.bin
```

Partition base LBAs (Star Wars image; identical structure on all): p2 rootfs
131073, p3 data 1359873, p5 connectivity 1409026, p6 games 51740675. Carve a
header with e.g. `dd if=image.raw of=p6_header.bin bs=512 skip=51740675 count=8192`.

For bulk extraction it is easiest to let `cryptsetup` do the mounting on Linux/WSL
once the key is known:

```sh
sudo cryptsetup luksOpen --key-file=key.bin <loopXp6> games
sudo mount -o ro /dev/mapper/games /mnt/games   # video/audio assets live here
```

The **`games`** partition (p6, ~35 GB, mounted read-only by Stern) is where the
per-title audio and video assets are; `data`/`connectivity` hold settings and
networking state. After extraction, curate videos with the repo's
`pinball-video-curator` workflow.

`tools/luks_otp.py` is pure-Python and cross-validated byte-for-byte against
`cryptsetup` (see `tools/xcheck_setup.sh`), so the whole verify+decrypt path runs
on Windows with no machine and no `cryptsetup`.
