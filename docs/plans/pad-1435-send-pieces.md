# PAD-1435: Send to machine reuses 64 KB pieces the machine already has

## Measured offline (V2.1 Kaiju + daveyvandy modes v38 -> Heisei V2.3, /games)

| | GB |
|---|---|
| changed or new (896 files) | 9.49 |
| 1 MiB blocks, same file and place (the PAD-1433 delta) | 1.47 (1.73 at 64 KB) |
| 64 KB pieces anywhere on the old card | 2.70 |
| ...from other files: all in files the Send rewrites anyway | 0.98 |
| extra old bytes to read for them | **0.00** |
| 4 KB pieces anywhere (about what content-defined chunks could add) | 2.75 |

So the index covers only the machine's copies of the files the Send changes in place, which the delta already
reads. Nothing more is read, and aligned 64 KB leaves 0.05 GB on the table, so there are no content-defined chunks.
Probes: `C:/tmp/PAD-1435/probe2.py`, `probe4k.py`.

## What changed

- `resources/pieces/padpieces.c`: a static helper (armv7 for Spike 2, aarch64 for Spike 3; `build.sh` builds both;
  sha256 pinned in `remote_send.PIECES_SHA256`). `hash BS` hashes the files listed on stdin, BS at a time.
  `copy` does the piece copies listed on stdin, in order. With busybox alone this needs a dd plus a sha1sum
  process for every piece: ~250k processes for this card. The helper is checked against Python under qemu
  (`tests/test_send_pieces.py`, Linux only).
- `SshMachine.pieces_ready` uploads the helper to `/run` (or `/tmp`) and checks `version`. If either step fails,
  the Send uses the 1 MiB delta exactly as before. `piece_hashes` and `copy_pieces` are retried on a reconnect.
- `send_pieces.plan` decides, for each piece, whether to keep it, copy it from somewhere on the card, or send it.
  A run of copies with the same shift is one copy. Order matters: a copy that writes a place runs only after every
  copy that reads that place. When copies form a cycle, the smallest run in it is sent instead.
- `remote_send.pieces_prepare` runs in the Compare phase: the machine's 64 KB hashes, batched (the bar moves), and
  the build's own. `pieces_run` does the copies, the sends, and then each file's size, owner, mode and time, then
  checks each file's sha1.
  - A new file is built beside its name and renamed over it, or in place when there isn't room for that.
  - A batch of copies is cut wherever one copy would overwrite a piece the batch read, so doing a batch again
    after a dropped connection reads the same bytes.
- The full Send uses this on every game mount. The quick Send uses it only short of room, for the files it
  changes in place (the files it uploads beside never read their old copies, so indexing them would be extra).

## Stand-in proof (2026-11-19, Ubuntu, the card's own dropbear under qemu-arm, `C:/tmp/PAD-1435/run_one.sh`)

Each run: a fresh sparse copy of the old card, remote access set up with PAD's own code, the full Send by
`send.py` (the app's `send_image`), then every /games file's sha1, owner, mode and size against the new image.

| | before (`PAD_NO_PIECES=1`, 1 MiB delta) | after (64 KB pieces) |
|---|---|---|
| v36 -> v38 (David's real update, 406 files, 4.0 GB changed): sent | 2.65 GB | **2.05 GB** |
| Compare phase | 122 s | 166 s (index under qemu) |
| whole Send | 475 s | **380 s** |
| card after the Send | matches v38, every file | matches v38, every file |
| v38 -> V2.3: sent | 8.02 GB (= 9.49 - 1.47, as the probe said) | not run: the V2.3 image was deleted mid-proof |

The stand-in's network is the WSL bridge (~7.5 MB/s through qemu'd dropbear); over the machine's Wi-Fi
(~3.6 MB/s) every 0.6 GB less is ~170 s, so the gain there is larger than the 95 s here.

## On David's Godzilla (2026-11-19, armv7, `C:/tmp/PAD-1435/mprobe2.py`, read-only)

| | |
|---|---|
| helper's hashes == busybox's (1 MiB, a 58 MB game file) | yes |
| today's 1 MiB blocks, cold, 0.20-0.22 GB | 6.3-6.7 MB/s |
| helper's 64 KB pieces, cold, the other set of files (then swapped) | **15.1-15.9 MB/s** |
| helper copying 400 scattered 64 KB pieces from a card file into RAM, cold | 8.9 MB/s |
| one 64 MB file over the machine's Wi-Fi | 0.96 MB/s |

For the files rebuilt from pieces, the helper's hashing replaces the 1 MiB hashing (`sync`: `pieces_run`, then
`delta_put` only for files outside the job), so on the real board the index is ~2.4x faster than today's read,
not a cost (under qemu it looked like +44 s). With Wi-Fi at 1-3.9 MB/s, every GB not sent is 4-17 minutes.

## Done

1. (Done for v36 -> v38, above.) Stand-in Send of the real case, V2.3 onto a v38 card with remote access set up: run it twice, with pieces and
   without (`PAD_NO_PIECES=1`). Compare the network bytes, the wall time, and the machine's card file by file
   against V2.3. The driver is `C:/tmp/PAD-1435/send.py` (scratch key dir `C:\tmp\PAD-1435\keys`; the KEY_DIR
   line there lost its backslashes to sed: fix it). The stand-in is `standin.sh`; `setup_cards.sh` sets up
   remote access. **The cards must not go into PAD-Runtime while C: is low.** Its vhdx is on C:, and the
   2026-11-19 attempt filled C: and broke the distro. Use a disk with room.
2. Real machine (192.168.4.130, its SSH was down on 2026-11-19): read-only timings of `padpieces hash` against
   BLOCKS_SCRIPT at 1 MiB on the same file, and the helper's copy speed. `C:/tmp/PAD-1435/mprobe.py` is the
   probe; add the helper to it. Model: 1.23 GB less over Wi-Fi at ~3.6 MB/s is ~340 s saved, against ~1 GB
   copied on the card (read plus write, ~150 s at SD speeds), and the hashing reads the same bytes as before.
