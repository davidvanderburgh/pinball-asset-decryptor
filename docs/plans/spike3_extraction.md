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

The fleet OTP keyfile is now in hand and unlocks **every** Spike 3 card, so all
listed titles are decryptable once the user points PAD at their keyfile; none
are greyed. A card run without a keyfile detects but reports "no key" cleanly.

## Scope

- **Done:** decrypt + extract video/images/scenes from a Spike 3 SD image.
  Proven end-to-end on a real 62 GB secure image.
- **Done (PAD-1077):** `image.bin` sounds to WAVs.
- **Done (PAD-1186):** the SD extract runs the Spike 2 extractors over the
  decrypted volume (a Spike 2-shaped project), and the Replace tabs + Write
  work on it: edits go back through the card's own encryption, nothing is
  re-signed (only the boot partition is signed, and it is never touched).
  See `spike3_replace.md`.
- **Done (PAD-1244):** sounds named and requests mapped as on Spike 2, with no
  emulator (`spike3_requests.py`). The aarch64 PIE game keeps Spike 2's tables
  behind `R_AARCH64_RELATIVE` relocations: the registry `{table, count, 32}`
  finds the request table (last record's list pointer = the table's end), the
  Sound Test is 48-byte name groups plus a 16-byte `{group, node id}` array
  (node id = request). `image.bin`'s descriptors are plaintext: header u64
  @0x20 ends 5 equal pointers per sound id, and each op-11 marker names its
  record by the directory's `flags_lo | param << 32`. Extract names the files
  from the Sound Test (Fallout 0.82: 2029 of 2870) and writes
  `sound_requests.tsv` (2186 of 2298 requests); Auto-transcribe and Auto-name
  music are on for Spike 3. Read on all six cards on hand (Star Wars ELG,
  Pokemon and Star Wars 2025 Pro carry only the template Sound Test, so
  Auto-transcribe does their naming).
