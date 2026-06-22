# Manufacturer Architecture Docs

Per-manufacturer architecture references for the `pinball_decryptor` plugins.
Each doc captures the container/encryption format, the extract and write/repack
pipelines, audio + other asset handling, detection, prerequisites, and the
non-obvious gotchas — cross-checked against the code with `file:line` links.

These complement the deeper format reverse-engineering session logs:
[AP_PKG_RE.md](../AP_PKG_RE.md) (American Pinball `.pkg` AES) and
[CGC_BNK_RE.md](../CGC_BNK_RE.md) (Chicago Gaming JPS `.bnk` audio banks).

## The plugins

| Manufacturer | Key | Format family | Write | Direct-SSD | Doc |
|---|---|---|---|---|---|
| Pinball Brothers | `pb` | gzip+tar `.upd` (plain); optional Clonezilla `.iso` | ✅ | — | [pb.md](pb.md) |
| American Pinball | `ap` | AES-256-CBC `.pkg` → ZIP | ✅ | — | [ap.md](ap.md) |
| Spooky Pinball | `spooky` | AES/GPG over Godot & Unity (`.pkg/.ed/…`); Clonezilla | ✅ | — | [spooky.md](spooky.md) |
| Barrels of Fun | `bof` | Godot PCK inside GPG `.fun` (May-2026 RSCC/Zstd) | ✅ | — | [bof.md](bof.md) |
| Jersey Jack | `jjp` | Encrypted ext4 `edata` in ISO (`fl.dat` + CRC32 forgery) | ✅ | ✅ | [jjp.md](jjp.md) |
| Chicago Gaming | `cgc` | Nested installer `.img` (ext4); JPS `.bnk` audio | ✅ | — | [cgc.md](cgc.md) |
| Stern Pinball | `stern` | Spike 2 raw SD-card `.img` (ext4); `image.bin` stream-cipher audio | ✅ | ✅ | [stern.md](stern.md) |
| Williams | `williams` | WPC/DCS MAME ROMs (extract-only; PinMAME capture) | — | — | [williams.md](williams.md) |
| Dutch Pinball | `dp` | TBL plain-ZIP deltas; AAIW Clonezilla `.img` | ✅¹ | ✅ | [dp.md](dp.md) |

¹ Dutch Pinball write is TBL-only; AAIW is edit-in-place / Direct-SSD.

## Cross-cutting concepts

- **Plugin contract** — every plugin subclasses `Manufacturer`
  ([core/registry.py](../../pinball_decryptor/core/registry.py)) and advertises a
  `Capabilities` set that gates the GUI tabs (Extract / Replace Audio / Write /
  Mod Pack).
- **Pipelines** — all extract/write work runs through `BasePipeline`
  ([core/pipeline_base.py](../../pinball_decryptor/core/pipeline_base.py)), which
  reports via `log/phase/progress/done` callbacks and now dumps full tracebacks
  to the log pane on unexpected errors.
- **Change detection** — Write flows diff the assets folder against a baseline
  `.checksums.md5` emitted at Extract time to find user edits.
- **Replace Audio** — the shared tab scans an extract for `.wav`/`.ogg` slots and
  stages format-matched replacements over them (auto-transcoded via ffmpeg) so
  the normal Write step repacks them. Plugins narrow the scan via
  `Manufacturer.audio_slot_dirs()` (BoF → `_EDITABLE ASSETS`; others → whole
  tree). See [core/audio_slots.py](../../pinball_decryptor/core/audio_slots.py).

## Conventions for these docs

- Live in `docs/architecture/`; source links use `../../` to reach the repo root.
- Cite concrete `file:line`; mark anything not confirmed in code as `(unverified)`.
- Same section skeleton across all nine, so they're skimmable side by side.
