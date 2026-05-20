# CGC Pulp Fiction `.bnk` Format — Reverse-Engineering Notes

Working notes for adding extract+repack of Pulp Fiction's audio bank files
to the CGC plugin. Each session should append findings + revise hypotheses
here so future sessions resume from current state.

**Status:** Header + ID table + event-chunk layout cracked. Sample header
table format identified but byte semantics not yet confirmed. MP3 stream
boundaries known but mapping back to sound IDs not yet figured out.

## Sample bank under analysis

Primary: `pfsndui.bnk` (2,872,003 bytes — smallest, 11 sound events).

The 6 PF banks all use the same format:
- `pfsndui.bnk`  2.8 MB — UI sounds
- `pfsnddiag.bnk` 3.1 MB — diagnostic sounds (140 events — most entries to cross-ref)
- `pfsndfx.bnk`  163 MB — sound effects
- `pfspeech.bnk`  91 MB — speech (uncensored)
- `pfspeechBEEPD.bnk` 89 MB — speech (clean/beeped)
- `pfmusic.bnk`  222 MB — music

## Confirmed format

### File header (offset 0)
```
0x0000  16 bytes  null-padded filename string (e.g. "pfsndui.txt\0\0\0\0\0")
0x0010  ...       mostly zeros + MSVC debug-fill (0xCC = uninit stack, 0xCD = uninit heap)
                  CGC build tool didn't zero its buffers before serializing
                  ↳ "real" fields are interspersed with this garbage everywhere
```

### Scattered audio-params fields in 0x200–0x300 region
Identified but exact semantics not nailed down:
```
@0x2A0  80 bb        0xBB80 = 48000 (sample rate, LE uint16)
@0x2A4  02           number of channels (stereo)
@0x220  9e a8 f4 40  LE float ≈ 7.643
@0x288  1d 26 53 2b  ?  (per-bank identifier?)
@0x294  8b d2 8d b9  ?
```

### ID table (sound-event index)

**Location in pfsndui.bnk:** 0x5C0 — 0x720 (352 bytes / 11 entries × 32 bytes)

Each 32-byte entry:

| Offset | Type | Field | Notes |
|---|---|---|---|
| 0–3 | LE uint32 | `id` | Sound event ID (0xD0, 0xD1, ..., 0xC5, 0x104, 0x105) |
| 4–7 | LE uint32 | `chunk_offset` | Byte offset of this event's first chunk, **relative to start of chunk region** |
| 8–11 | LE uint32 | `chunk_count` | How many chunks belong to this event |
| 12–15 | LE uint32 | `flag` | Always 1 (purpose unknown) |
| 16–19 | bytes | `params` | Variable per entry. e.g. `1e 00 78 00` (most), `60 00 7d 00` (id=0xD6), `01 00 96 00` (id=0xC5). Likely sample-count or duration. |
| 20–23 | LE uint32 | `reserved` | Always 0 |
| 24–27 | LE uint32 | `hash` | Per-event hash (random-looking, unique per entry) |
| 28–31 | LE uint32 | `pad` | 0 |

**Verified** by cross-checking `chunk_offset` against actual chunk positions
(see below): every `chunk_offset + chunk_region_base` lands exactly on a
SETV chunk header.

**Verified** that `chunk_count` matches observed chunk groups:
- id=0xD0..0xD5,0xD7 → chunk_count=3 → SETV+PLAY+END (simple play event)
- id=0xD6 → chunk_count=5 → SETV+DUCK+PLAY+UNDU+END (ducks other audio while playing)
- id=0x104, 0x105 → chunk_count=4
- id=0xC5 → chunk_count=6 (most complex event)

### Event chunks region

**Location in pfsndui.bnk:** 0x71C — 0x161C (3,840 bytes / 40 chunks × 96 bytes)

**Chunk layout:** every chunk is **uniform 96 bytes** (0x60). Each chunk
starts with a 4-char ASCII tag, then MSVC garbage with sparse real fields:

| Tag | Meaning | Pair with |
|---|---|---|
| `SETV` | Set volume (envelope?) | starts each event |
| `PLAY` | Play sound (references a sample by index) | always paired with `END` |
| `END\0` | End of play action | closes a `PLAY` |
| `DUCK` | Begin ducking other audio | paired with `UNDU` |
| `UNDU` | End ducking | closes a `DUCK` |
| `WAIT` | Wait/delay | rare; closes mid-event |
| `STOP` | (not seen yet in pfsndui — may appear in other banks) | ? |

**PLAY chunk internal fields** (partial):
```
+0x00  PLAY\0 + 0xCD garbage
+0x20  LE uint32 — DIFFERS PER PLAY. Values for pfsndui PLAYs:
          PLAY @0x77C: 0x00000000
          PLAY @0x89C: 0x00000044
          PLAY @0x9BC: 0x00000088
          ↳ increments by 0x44 (68) for each subsequent PLAY
          ↳ may be sample index OR byte offset into a sample table
+0x28  LE uint32 — always 1 (channel count? voice count?)
+0x2C  LE uint16 — 0xFFFF (sentinel?)
+0x5C  LE uint32 — always 1 (priority?)
+0xBC  LE uint32 — always 4 (?)
```

**SETV chunk internal fields** (partial):
```
+0x00  SETVOL\0T  (8-char tag — not 4-char as initially scanned!)
+0x10  ...
+0x1E  cd bb 00     ← partial pattern; need to confirm
+0x5C  LE uint32 — always 2 (??)
```

### Sample header table (NEW, not yet confirmed)

**Location in pfsndui.bnk:** appears to start at 0x1654 (immediately after
last END chunk + alignment). Layout candidates:

```
@0x1654  uint32 size    = 612    (0x264)
         float  gain    = 0.5    (0x3F000000)
@0x165C  uint32 size    = 680    (0x2A8)
         float  gain    = 0.5
@0x1664  uint32 size    = ?
         ...
```

Confirmed:
- Pairs of `(uint32 size, float gain)` at fixed 8-byte stride
- `gain` values all observed = 0.5 so far → likely a normalized gain factor
- `size` values 612, 680, ... small (~600-byte) — too small to be byte
  sizes of MP3 streams (those would be KB-to-MB scale)

**Open questions:**
- Is `size` a sample-count, a frame-count, an offset, or something else?
- Where does each sample's actual audio data live? The MP3 frame syncs
  start much later at 0x3108, not adjacent to these size headers.

### MP3 audio data region

**Location in pfsndui.bnk:** first valid MP3 frame at **0x3108**, runs
through 0x2BD2BB (end of file). That's ~2.85 MB of MP3 streams.

First MP3 frame at 0x3108:
- `ff f5 d9 c2 79 b1 7c 13 ...`
- MPEG version_idx=2 (MPEG-2), layer_idx=2 (Layer II)
- Sample rate index 2, bitrate index 13

Not yet confirmed:
- Where do individual stream boundaries fall?
- How are streams mapped back to the sound IDs in the ID table?
- Are there per-stream headers separating them, or are they back-to-back?

### Unexplored: 0x161C — 0x3108 (6,892 bytes)

Definitely contains:
- The sample header table starting at 0x1654 (continues at least through 0x1830 by inspection)

May also contain:
- A second index mapping sample headers → MP3 stream offsets
- Or PCM/uncompressed audio for short UI sounds (the "612 bytes ≈ 13ms of 48kHz mono 16-bit" theory)

## Recommended next session approach

1. **Cross-bank sweep**: dump the same regions from `pfsnddiag.bnk` (140 events,
   richest sample set) and compare structure. Fields that vary in `pfsndui`
   but are constant in `pfsnddiag` (or vice versa) are real fields; fields
   that look like garbage in both are garbage.

2. **PLAY-chunk field 0x20**: the increments-by-0x44 sequence. Hypothesis:
   it's a byte offset into the sample header table.
   `0x44 (68) = 8.5 × 8` — not a clean multiple of 8 (the sample header stride).
   Confirm or reject with a longer bank.

3. **Audio data extraction**: with the header table location confirmed,
   write a script that walks the MP3 stream starting at 0x3108, identifies
   stream boundaries via frame-chain validation, and emits each stream as
   `.mp3`. Cross-reference against the ID table count (11 streams expected
   for pfsndui, 140 for pfsnddiag).

4. **Decode `pfsnddiag.bnk` sample table first** if available — its 140
   entries should reveal the pattern more clearly than 11.

## What we already know works for OPTION A (dump only)

If a session decides to ship listen-only Option A: the MP3 stream region
starts at 0x3108 in pfsndui.bnk (and an analogous offset in other banks
— would need per-bank discovery via "first valid MP3 frame past chunk
region"). A pure MP3-frame walker emitting `.mp3` files would let users
preview audio without needing the index figured out. Repack requires the
sample table mapping figured out.

## Bigger-picture caveat

The MSVC debug-fill garbage (0xCC stack-fill, 0xCD heap-fill) is a CGC
build-tool bug, not encryption. Some fields we're treating as "real" might
actually be garbage that *happens* to look meaningful. Cross-referencing
multiple banks is the only reliable defense.

## Session 1 close-out (2026-05-20)

Resolved: filename header, ID table at 0x5C0 (11 × 32-byte entries),
event chunks region (uniform 96-byte chunks), audio params hints
(48 kHz, stereo). Open: MP3 stream walker assumptions (turned out to
be wrong — see session 2).

## Session 2 close-out (2026-05-20)

### Pivot: audio is NOT MP3

`ffprobe` rejects the data as "Invalid data found." The 0xFFE? bytes
that looked like MP3 frame syncs are coincidental noise — the next
expected frame offset always lands on garbage. Wasted ~30 min on this
red herring before the strings dump on the `pin` binary cracked it.

### Audio engine identified: JPS (custom CGC library)

`strings pin | grep '^jps_'` returns 30+ symbols showing the full bank
loader API: `jps_bank_load_compiled`, `jps_bank_alloc`, `jps_parse_*`
(compiler), `jps_init`, `jps_init_audio`. Error messages reveal the
bank load order: **header → version → ID → sound buffers → playlists →
commands → groups → group sounds**, with each sound buffer having both
compressed AND uncompressed sizes.

The `pin` binary uses SDL_mixer 1.2 for playback and statically links
JPS. Bank source files are `.txt` (human-readable) compiled by JPS into
`.bnk` (binary) — the filename in the header is the source `.txt` name
(e.g. `pfsndui.txt`). Source files aren't shipped — only the compiled
`.bnk` is.

### Audio codec: zlib (libz.so.1)

`zlibVersion` + `uncompress` symbols in the `pin` ELF imports.
**Each sound buffer is a standard zlib DEFLATE stream.** Found via:

```python
i = 0
while i < len(data):
    if data[i] == 0x78 and data[i+1] in (0x01, 0x5E, 0x9C, 0xDA):
        try:
            d = zlib.decompressobj()
            out = d.decompress(data[i:])
            consumed = len(data) - i - len(d.unused_data)
            # out is the decompressed JPS sound buffer
        except zlib.error:
            i += 1
```

**pfsndui.bnk has 12 zlib streams** (matches ~11 sound events).
**pfsnddiag.bnk has only 3 zlib streams** despite 140 events — short
diagnostic sounds must be either (a) concatenated within fewer streams,
indexed by per-event offset/length pairs we haven't yet found, or
(b) stored uncompressed without the JPS magic prefix (no direct hits
for the magic bytes in raw data, so option (b) is unlikely).

### Decompressed payload format

```
+0x00  uint32  magic        = 0x0E6F07BB           (constant)
+0x04  uint32  hash1        = per-stream varying   (algorithm unknown)
+0x08  uint32  magic        = 0x1385CA6D           (constant)
+0x0C  uint32  magic        = 0xDB8E52BF           (constant)
+0x10  uint32  magic        = 0xCBA86BDF           (constant)
+0x14  uint32  magic        = 0x3C4B88A6           (constant)
+0x18  uint32  magic        = 0x31933080           (constant)
+0x1C  uint32  magic        = 0x3855CD0A           (constant)
+0x20  uint32  magic        = 0x9AC705CB           (constant)
+0x24  uint32  magic        = 0xD16487E2           (constant)
+0x28  uint32  hash2        = per-stream varying   (algorithm unknown)
+0x2C  bytes[]  s16le_stereo_pcm at 48 kHz        (until end of decompressed buf)
```

**hash1 and hash2** are NOT CRC32 or Adler32 of the PCM data (verified).
They could be:
- A custom CGC hash (FNV / rotating XOR / etc.)
- A per-bank-instance identifier (UUID-like)
- Plain stream sequence counter encoded somehow

For repack, we don't yet know if the JPS engine validates these on load.
The error message `"version # is corrupt"` exists but no `"hash mismatch"`
string, so they might be informational only — to be tested by injecting
synthetic values during repack.

### Working extractor (pfsndui.bnk)

Implemented in `c:\tmp\` scratch scripts; produces 12 standard WAVs
(s16le stereo 48kHz). Verified with ffprobe: real audio, mean volume
-13 to -15 dB, sensible durations (65ms to 6.6s), matches expected
UI-sound profile. Output dir: `C:\tmp\pf_bnk_extract_v2\`.

### What's still open for session 3

1. **Multi-sound-per-stream mapping** (pfsnddiag puzzle). 140 events +
   3 zlib streams = need a per-event (stream_idx, offset, length)
   table. Likely lives in the unexplored 0x161C..0x3108 region or in
   the (size, gain) pairs at 0x1654 (which we now know don't correspond
   to per-stream sizes — they may be per-EVENT sizes pointing into a
   shared decompressed PCM buffer).

2. **PLAY chunk +0x20 field** (the 0x00, 0x44, 0x88, ... increments
   in pfsndui). Hypothesis: byte offset into the per-event sample
   table OR into the decompressed PCM. Cross-check with pfsnddiag's
   140 PLAY chunks would confirm.

3. **The 0x161C..first-zlib-stream region** for pfsndui (≈3KB) and
   the analogous region for pfsnddiag. This is where the
   stream-index → event mapping must live.

4. **hash1/hash2 algorithm.** Even if not validated on load, we'd
   ideally compute correct values during repack. Could try common
   hashes (FNV-1, FNV-1a, Murmur, custom rotations) against the PCM
   data, or experiment with injecting zeros to see if the engine
   rejects the bank.

5. **Repack flow design** (session 4 territory once extract is solid).

## Session 3 close-out (2026-05-20)

### Resolved

1. **Per-buffer header table at 0x2A0** — uniform 68-byte entries, one
   per zlib stream. Found by scanning for the sample-rate marker
   `80 bb 00 00` (= 48000): hits are exactly 68 bytes apart, count
   matches stream count (12 in pfsndui, 3 in pfsnddiag, 49 in
   pfmusic-RIFF, etc).

2. **PLAY chunk +0x20 field decoded** — it's `buffer_index * 68`,
   i.e. the BYTE OFFSET into the per-buffer header table for the
   buffer this PLAY references. Verified against pfsndui events
   (which map 1:1 to buffers 0..11) and pfsnddiag (140 events, 3
   buffers, most events reference buffer 1).

3. **Two storage formats** identified, not one:
   - `zlib`: zlib stream containing 44-byte JPS magic + raw PCM.
     Used by UI, SFX, speech, diagnostic banks.
   - `riff`: standard embedded RIFF/WAVE inline, no compression.
     Used by music bank (24 buffers) and occasionally elsewhere
     (1 of 465 sfx buffers in pfsndfx). Makes sense: music is large
     enough that zlib overhead doesn't help, and RIFF is naturally
     streamable.

4. **Working unified extractor** in
   [pinball_decryptor/plugins/cgc/jps_bnk.py](pinball_decryptor/plugins/cgc/jps_bnk.py):
   `parse_bnk()` returns structured contents; `extract_bnk()` writes
   WAVs + manifest. Tested against all 6 PF banks:

   | Bank | Size | Buffers | Storage | Events | Audio |
   |---|---|---|---|---|---|
   | pfmusic | 222 MB | 24 | riff | 69 | 11.9 min |
   | pfsnddiag | 3 MB | 3 | zlib | 140 | 0.4 min |
   | pfsndfx | 163 MB | 465 | zlib (464) + riff (1) | 267 | 18.9 min |
   | pfsndui | 2.7 MB | 12 | zlib | 11 | 0.3 min |
   | pfspeech | 92 MB | 264 | zlib | 261 | 11.2 min |
   | pfspeechBEEPD | 90 MB | 264 | zlib | 261 | 11.2 min |
   | **TOTAL** | | **1032** | | **1009** | **54 min** |

5. **Wired into CGC Extract pipeline** ([pipeline.py::_explode_jps_banks](../pinball_decryptor/plugins/cgc/pipeline.py)).
   PF extract now produces both raw `.bnk` files AND a sibling
   sub-directory per bank with all the decoded WAVs + `manifest.json`.
   End-to-end test: full PF extract from `.img` to decoded WAVs in
   224 s (vs ~70 s without bank decoding).

### What's still open for session 4

1. **Hash1/hash2 algorithm** (zlib-storage buffers' 44-byte header
   fields at u32[1] and u32[10]). Not CRC32 / Adler32 / xxHash of
   PCM. Pragmatic next step: test if the JPS engine actually
   validates them — repack with arbitrary values and see if the
   bank loads. If it does, we don't need to compute them.

2. **Repack flow**:
   - Detect which WAVs in `<bnk>/` subdirs differ from baseline.
   - For each modified buffer: re-encode (zlib for zlib-storage,
     raw RIFF copy for riff-storage), update the per-buffer header
     entry at `0x2A0 + buffer_idx * 68` with new size, splice the
     new compressed payload into the `.bnk` at the original offset,
     adjust subsequent offsets if size changed.
   - Most challenging case: size growth pushes following buffers
     forward, which requires updating the per-buffer offset table
     (which we haven't fully identified yet — `0x2A0+offset` may
     contain offset bytes, needs cross-bank confirmation).

3. **(size, gain) pairs at 0x1654 in pfsndui** — what we initially
   thought was a sample-size table is something else (count doesn't
   match buffer count cleanly). Now believe it's a sub-structure
   within the first per-buffer header entry (offset 0x2A0+0x44 from
   table start = 0x2E4 in pfsndui; close to 0x1654 if there's a
   different base). Needs re-examination during repack work.

### Session 4 work plan

1. (15 min) Test "ignore hash fields" hypothesis: repack one .bnk
   with hash1/hash2 set to 0 or to garbage, see if the engine
   accepts it. If yes, we can skip the hash algorithm entirely.
2. (1 hr) Map the per-buffer offset table fully. Find which bytes
   in the 68-byte header encode `bnk_offset` (the byte position of
   each zlib/RIFF stream).
3. (2 hr) Implement `repack_bnk(manifest_path, modified_wavs_dir,
   output_bnk_path)` in `jps_bnk.py`.
4. (1 hr) Wire into the CGC Write pipeline: detect modified WAVs
   under each `<bnk>/` subdir, repack the .bnk file, then let the
   normal Write flow inject the modified .bnk back into the .img.
5. (Stretch) Round-trip verification: extract -> tweak one byte
   in one WAV -> repack -> extract again -> verify WAV matches
   tweaked input byte-for-byte.

## Session 4 close-out (2026-05-20)

### Resolved

1. **Per-buffer header table does NOT contain offsets or sizes.**
   Verified by exhaustive uint32 dump across all 12 pfsndui entries:
   no field matches any buffer's bnk_offset, compressed_size,
   decompressed_size, or pcm_size. JPS reads buffers sequentially
   via zlib's natural framing (`uncompress()` advances the read
   pointer by the consumed compressed bytes), no offset table needed.

2. **4-byte gap between consecutive buffers is preserved-but-unknown.**
   Values look random (likely uninitialized MSVC heap fill or a JPS
   per-buffer hash that the loader doesn't validate). Repack
   preserves them bit-for-bit and the round-trip passes, so they're
   either ignored or our preservation is correct.

3. **Repack implemented and round-trip verified** end-to-end against
   real `.img`:
   - Extract installer.img -> 1,032 WAVs across 6 banks (~4 min)
   - Reverse pfsndui_sound_006.wav (drastic edit, easy to verify)
   - Write modified .img -> Write pipeline correctly detects ONE
     modified file (`data/pfsndui.bnk`, automatically repacked from
     the user's WAV edit), patches it into the inner ext4 via
     debugfs, repacks the outer .img (~5 min)
   - Re-extract modified .img -> pfsndui_sound_006.wav has the
     EXACT md5 of the reversed edit (~4 min)
   - All other WAVs preserved byte-for-byte

4. **Hash1/hash2 in 44-byte JPS magic header:** preserved verbatim
   from original during repack (decompress original, splice in new
   PCM, recompress). This sidesteps needing to compute the algorithm.
   Whether the JPS engine validates these on load is still
   technically unknown -- but since the bytes match what the engine
   expects (just attached to different PCM), it should accept them.
   **Test on a real machine to confirm the modified .img boots and
   plays the reversed sound.**

### Pipeline wiring

- **Extract** ([pipeline.py::_explode_jps_banks](../pinball_decryptor/plugins/cgc/pipeline.py)):
  after the inner-ext4 rdump, walks every `.bnk` and runs
  `jps_bnk.extract_bnk()` to produce a sibling `<name>/` dir of
  decoded WAVs + manifest.json.

- **Write** ([pipeline.py::_diff_assets](../pinball_decryptor/plugins/cgc/pipeline.py)
  + [_repack_modified_jps_bnks](../pinball_decryptor/plugins/cgc/pipeline.py)):
  pre-step before the normal asset diff runs `repack_bnk()` on every
  `.bnk` whose sibling `<name>/` subdir has any modified WAV.
  Modified WAVs in subdirs are excluded from the to-write set
  (they're decode artifacts, not eMMC payloads).

### Open items / future work

1. **Machine-level verification** of the round-tripped .img. The
   software round-trip passes; need a real PF machine to confirm
   the JPS engine accepts the repacked .bnk and plays the modified
   audio. If hash1/hash2 IS validated, modified .bnks will fail to
   load and we'd need to crack the algorithm. Possible workaround:
   if the engine logs "hash mismatch" or similar, we can read JPS's
   validation code from `pin` strings.

2. **Cross-bank generality**. Extract works across all 6 PF banks;
   repack tested only on pfsndui (the smallest). Other banks (pfmusic
   with RIFF storage, big banks like pfsndfx with 465 buffers, the
   beeped-speech bank) should work but haven't been exercised.

3. **Same-format constraint**. Modified WAVs MUST match the original
   buffer's audio params (48 kHz / stereo / 16-bit). Mismatch raises
   ValueError. Could be relaxed by transcoding (would need ffmpeg).

4. **Variable-size repack tested but not full chain**. A modified
   buffer's compressed size differs from the original (e.g.
   pfsndui_sound_006 went 682,062 -> 668,824 bytes after re-zlib).
   The repacker handles this correctly by shifting subsequent
   buffers; the test confirmed this works for one modification.
   Multi-modification stress-tests would be a nice-to-have.
