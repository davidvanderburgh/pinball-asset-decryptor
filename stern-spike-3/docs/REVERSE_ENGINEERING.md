# Stern "Spike 3" — SD card encryption, reverse-engineered

Working notes on how Stern's 2025-generation **Spike 3** pinball machines encrypt
their SD card, and exactly what it would take to decrypt the audio/video assets
on a PC. Investigated 2026-06-12 against three official "Release" SD images:
`star_wars_2025_le-0_96_0`, `pokemon_le-0_82_0`, `walking_dead_remastered_le-0_92_0`
(each `*.Release.64G.sdcard-secure.raw`, ~62 GB).

**Status:** the scheme is fully understood and an offline decryptor is built and
cross-validated against `cryptsetup`. The **only** thing missing is the 256-bit
key, which is fused into the Raspberry Pi SoC and is provably **not** present in
the SD image. Obtaining it requires a one-time read from a physical board — see
[KEY_EXTRACTION.md](KEY_EXTRACTION.md).

---

## 1. Hardware: it's a Raspberry Pi CM4

Spike 3 runs on a **Raspberry Pi Compute Module 4** (BCM2711). Evidence:

- The boot image contains `bcm2711-rpi-cm4.dtb` and the inner boot filesystem is
  labelled **`SPIKE3-BOOT`**.
- The unlock path uses `vcmailbox 0x00030021` (the VideoCore mailbox
  *GET_CUSTOMER_OTP* tag) and reads **8 OTP rows = 256 bits**, which is the
  non-BCM2712 customer-OTP layout (rows 36–43). A Pi 5 / BCM2712 would use
  different rows and a different mailbox layout.
- Community teardowns ("SPIKE 3 in the wild", Pinside, ~Aug 2025) report a
  Raspberry Pi Compute Module under a metal shield as the main processor.

## 2. SD card layout (MBR)

```
p1  FAT32  type 0x0c   LBA 1         67 MB    UNENCRYPTED boot partition
p2  Linux  type 0x83   LBA 131073    629 MB   LUKS2  -> "rootfs"
p3  Linux  type 0x83   LBA 1359873   25 MB    LUKS2  -> "data"
--  extended partition (type 0x0f) holds two logical volumes:
p5  Linux              ~25.7 GB               LUKS2  -> "connectivity"
p6  Linux              ~35.4 GB               LUKS2  -> "games"     <- assets live here
```

Only **p1 (FAT32) is unencrypted.** Everything else is LUKS2/AES-XTS. The bulk of
the card is sparse (long zero runs); real ciphertext measures ~8.0 bits/byte.

## 3. The unencrypted boot partition (p1)

p1 contains exactly three things:

- `config.txt` — just `boot_ramdisk=1`
- `boot.sig` — RSA-2048 signature header: line 1 = SHA-256 of `boot.img`,
  line 2 = `ts:`, line 3 = `rsa2048:`
- `boot.img` — a 20 MB **FAT16** image (label `SPIKE3-BOOT`) which is itself the
  Raspberry Pi boot filesystem:
  - `Image.gz` (Linux kernel 6.6.28-v8), `bcm2711-rpi-cm4.dtb`, `start4.elf`,
    `fixup4.dat`, `overlays/`, `config.txt`, `cmdline.txt`
  - **`rootfs.cpio.zst`** — the zstd-compressed initramfs (this is the prize)

`cmdline.txt` = `root=/dev/ram0 rootwait console=tty1 fbcon=map:2
drm.edid_firmware=HDMI-A-2:edid.bin` — i.e. the initramfs *is* the root and is
responsible for unlocking + mounting the real (LUKS) partitions.

**`boot.img` and `boot.sig` are byte-identical across all three games** (and so
is the initramfs `/init`, SHA-256 `92fe4d24…e535fca810`). The boot image is
generic; all game-specific data is inside the encrypted partitions.

## 4. The LUKS2 parameters (identical on all four volumes, all games)

```
type        LUKS2
cipher      aes-xts-plain64        sector_size 512     payload offset 16 MB
keyslot 0   pbkdf2 / sha256 / 250000 iters    key_size 32 (=> AES-128-XTS volume key)
            AF: 4000 stripes / sha256          area: aes-xts-plain64 @ 32768
digest 0    pbkdf2 / sha256 / 1000 iters
```

There is **only keyslot 0** — no backup/recovery slot, no tokens. The KDF being
**PBKDF2** (not LUKS2's default Argon2id) is the tell that these were created by
an automated factory script feeding a fixed keyfile, not a human passphrase.

## 5. The unlock mechanism (`/init`)

```sh
echo `vcmailbox 0x00030021 40 40 0 8 0 0 0 0 0 0 0 0` \
    | awk '{print substr ($0, 77, 88)}' | xxd -r -p > /ktmp
cryptsetup luksOpen /dev/mmcblk0p2 rootfs       --key-file=/ktmp
cryptsetup luksOpen /dev/mmcblk0p3 data         --key-file=/ktmp
cryptsetup luksOpen /dev/mmcblk0p5 connectivity --key-file=/ktmp
cryptsetup luksOpen /dev/mmcblk0p6 games        --key-file=/ktmp
shred -f -n 5 -z -u /ktmp     # key wiped immediately after use
```

The LUKS keyfile is the **CM4 customer OTP** (256 bits): `vcmailbox 0x00030021`
returns OTP rows 0–7; `awk` slices out the 8 hex words; `xxd -r -p` turns them
into the raw key bytes; the result unlocks all four volumes.

## 6. The keyfile byte layout — it is **32 bytes** (not 36)

This was the single most important detail to get right, and it is a place an
earlier attempt went wrong (see §9).

`vcmailbox` prints the mailbox buffer as space-separated `0x%08x` words. The
`awk '{print substr($0,77,88)}'` window is exactly the 8 OTP words *with* their
`0x` prefixes:

```
 0xWORD0 0xWORD1 0xWORD2 0xWORD3 0xWORD4 0xWORD5 0xWORD6 0xWORD7
```

The initramfs `xxd` is **busybox xxd** (`/usr/bin/xxd` is a symlink to busybox).
Running the *actual* aarch64 busybox `xxd -r -p` on that slice (under qemu) gives
a clean **32 bytes** — busybox treats `0x` and spaces as separators and reads the
8 eight-hex-digit words straight through:

```
key = struct.pack('>8I', w0, w1, w2, w3, w4, w5, w6, w7)   # 32 bytes, MSB-first
```

This is consistent with the LUKS `key_size = 32` and with the machine actually
booting (the keyfile that unlocks the volume must be what the init produces).
`tools/luks_otp.py` (`otp_words_to_keyfile`) implements exactly this, with a
`--word-endian little` fallback in case a future OTP-dump tool byte-swaps words.

## 7. Why the key cannot be recovered from the image alone

The 256 bits live in the SoC's one-time-programmable fuses and are never written
to storage. Exhaustively confirmed:

- **No embedded copy / fallback.** The unencrypted boot partition of all three
  images was fully walked (p1 FAT32 → `boot.img` FAT16 → `rootfs.cpio.zst`
  initramfs). The only unlock path is `/init`, which reads OTP live and shreds
  the keyfile. No hardcoded key, no keyfile, no provisioning/factory script.
- **No weak slot.** Every LUKS2 volume has only keyslot 0 (strong PBKDF2/250000)
  and no tokens — there is no alternate password to attack.
- **Brute force is infeasible.** The slot "password" is the raw 256-bit
  high-entropy OTP, not a guessable passphrase.
- **Structured guesses fail.** ~200 plausible non-random candidates (vendor
  strings, the public boot-image hash, constants, repeated bytes; both
  endiannesses) were run through the LUKS digest oracle — none verified.
- **Off-board reads don't expose it.** RPi `rpiboot`/`usbboot` recovery metadata
  exposes only the *public* `CUSTOMER_KEY_HASH`, never the secret OTP rows;
  reading customer OTP requires running code on the live SoC via the mailbox.

The encrypted payloads measure ~7.997 bits/byte (genuine AES-XTS, no plaintext
leakage, no stored key). The key must be read once from a physical board.

## 8. Is the key global (one Stern-wide key) or per-device?

Unresolved from public information; it must be tested empirically.

- **For global:** Stern ships one golden `*.Release.*` image flashed to every
  machine of a model, and the unlock `/init` is byte-identical across games. A
  single shared OTP, burned identically at manufacturing, makes that operationally
  clean. If true, one key read from any board decrypts every Spike 3 game on any
  PC, forever.
- **For per-device:** Raspberry Pi's *documented* secure-boot tooling
  (`rpi-sb-provisioner`, `usbboot/secure-boot-example`) mints a fresh random key
  per board (`openssl rand -hex 32` → `cryptsetup luksFormat`), explicitly so
  storage "can't be read on other systems." If Stern followed that, each machine
  differs.

Stern bypassed RPi's key-store tooling (raw customer-OTP region + a custom
`awk`/`xxd` unlock), so the per-device default cannot be assumed. **The cheap,
decisive test:** read the OTP once, then try that keyfile against all three
games' headers with `tools/luks_otp.py`. One key opening all three ⇒ at least
model/Stern-wide.

## 9. Cross-reference: the earlier `spike 3` working repo

A prior local effort lives at `C:\Users\david\Documents\development\spike 3`.
It reached the same architecture independently and adds useful scaffolding, but
**never recovered a key** (`output/volume_keys.json` is `{}`, `output/videos/`
empty). Reconciliation:

- `scripts/analyze_boot_chain_security.py` — same boot-chain analysis; its own
  summary correctly says *"Derive **32-byte** LUKS key from OTP"*, and it reaches
  the same secure-boot conclusion (can't tell from the SD; check
  `vcgencmd otp_dump` row 90 on hardware).
- `scripts/build_otp_dump_image.py` — an equivalent extractor-card builder,
  pure-Python via `zstandard` (the portability pattern adopted here in
  [../tools/build_extractor_card.py](../tools/build_extractor_card.py)). It omits
  `boot.sig`; ours regenerates the SHA-256 line instead. Neither was ever
  confirmed to boot (that needs hardware).
- `cracking/` — a hashcat (`-m 29521`) attempt to brute the key. **It used a
  wrong 36-byte keyfile model** (`cracking/otp.py`: the theory that `xxd -r -p`
  keeps the `0` and drops only the `x`, giving 9 hex digits/word). The real
  busybox `xxd` produces **32 bytes** (§6), so those candidates could never have
  matched even with the right OTP words. Any future brute-force (e.g. the
  "all 8 OTP words equal one 32-bit value" 2³² hypothesis in `cracking/gen_t3.py`)
  must be redone with the **32-byte** encoding. It remains a long shot (the OTP is
  most likely fully random), but it is now at least *correctly* encoded.
- `scripts/01..05_*.py` — a full extract pipeline (derive keys → decrypt → carve
  videos) that works only once a key exists; [../tools/luks_otp.py](../tools/luks_otp.py)
  is the cleaned-up, `cryptsetup`-cross-validated equivalent.
