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

## Proof still to do (next run)

1. Stand-in Send of the real case, V2.3 onto a v38 card with remote access set up: run it twice, with pieces and
   without (`PAD_NO_PIECES=1`). Compare the network bytes, the wall time, and the machine's card file by file
   against V2.3. The driver is `C:/tmp/PAD-1435/send.py` (scratch key dir `C:\tmp\PAD-1435\keys`; the KEY_DIR
   line there lost its backslashes to sed: fix it). The stand-in is `standin.sh`; `setup_cards.sh` sets up
   remote access. **The cards must not go into PAD-Runtime while C: is low.** Its vhdx is on C:, and the
   2026-11-19 attempt filled C: and broke the distro. Use a disk with room.
2. Real machine (192.168.4.130, its SSH was down on 2026-11-19): read-only timings of `padpieces hash` against
   BLOCKS_SCRIPT at 1 MiB on the same file, and the helper's copy speed. `C:/tmp/PAD-1435/mprobe.py` is the
   probe; add the helper to it. Model: 1.23 GB less over Wi-Fi at ~3.6 MB/s is ~340 s saved, against ~1 GB
   copied on the card (read plus write, ~150 s at SD speeds), and the hashing reads the same bytes as before.
