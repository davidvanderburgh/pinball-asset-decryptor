# Spike 3 extraction

Stern **Spike 3** is the Raspberry-Pi-4 (BCM2711) secure-boot generation. A game
SD card keeps the game on an **encrypted** partition, so — unlike Spike 1/2 — PAD
must decrypt before it can read the asset tree. This note describes the path PAD
takes. The key *values* and the recovery "how" are deliberately **not** in this
repo.

## Card layout (MBR)

    p1  0x0c  FAT32   64 MB boot   PLAINTEXT (signed, not encrypted)
    p2  0x83  LUKS2   rootfs
    p3  0x83  LUKS2   data (settings/NVRAM)
    p4  0x0f  extended
    p5  0x83  LUKS2   connectivity   (logical)
    p6  0x83  LUKS2   games / assets (logical — the large one)

Every encrypted partition is a LUKS2 container (`aes-xts-plain64`) over ext4.
The **p6** asset tree carries the same formats as Spike 2:

- videos: QuickTime `.asset` files (`ftyp qt`) — renamed to `.mov` on extract,
- images: `.png`,
- scenes: `.radium` + `.sidx`,
- audio: an `image.bin` container (Spike 2's format), plus scene-renderer
  texture `.asset` blobs.

## How PAD reads it (pure Python, no root, no cryptsetup)

1. `spike3.parse_partitions` — MBR primaries + the EBR logical chain, each entry
   flagged `luks` by its magic. `partition_for_role(parts, "games")` returns p6
   (fixed disk order, falling back to the largest LUKS partition).
2. `spike3.read_luks_header` reads the LUKS2 header **off the image** (no carved
   header needed by a user).
3. The partition is unlocked with a key from `spike3_keys.Spike3KeySource`
   (below) and verified against the LUKS digest.
4. `spike3.DecryptingSegmentReader` presents the partition's **plaintext** data
   segment as a seekable file-like, XTS-decrypting the covering sectors on
   demand and caching them. Handed to the existing `ext4.Ext4Reader`, it walks a
   multi-GB filesystem reading only the blocks it needs — never the whole 62 GB
   image. (Opening p6 + finding a file by name is ~0.1 s.)
5. `spike3_extract.Spike3ExtractPipeline` walks p6 once and copies video/images/
   scenes into the output dir, preserving each file's path.

The picker gains a `spike3` era in the Stern plugin (`manufacturer.py`): detect,
capabilities (extract-only), phases, and the pipeline factory.

## Keys — never in the repo

`Spike3KeySource` only **loads** a key the user supplies; this repo ships no key
material. Two kinds unlock a partition:

- an **unlock keyfile** (the board's customer-OTP value) — fleet-wide, run
  through the LUKS keyslot to derive the master key; or
- a **per-volume master key** — one partition of one image, used directly.

Resolved from `$PAD_SPIKE3_KEYFILE` or a `<image>.padkeys.json` sidecar:

    { "otp_keyfile": "<64 hex / path>",
      "master_keys": { "games": "<64 hex>" } }

A card whose key isn't in hand detects but reports "no key" cleanly, and in the
picker the titles we can't yet decrypt are greyed with a reason.

## Scope

- **Done:** decrypt + extract video/images/scenes from a Spike 3 SD image.
  Proven end-to-end on a real 62 GB secure image.
- **Not here:** build/replace (would re-encrypt + re-sign); decoding the
  `image.bin` audio and scene-renderer `.asset` blobs into loose WAVs/clips
  (reuses the Spike 2 scene/audio engine over the decrypting reader — a follow-up);
  the `.spk` update-package path (a separate input that needs a real Stern `.spk`
  to verify — none on hand).
