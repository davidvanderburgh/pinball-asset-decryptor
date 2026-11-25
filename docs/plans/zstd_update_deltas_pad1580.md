# zstd for update deltas (PAD-1580): measured, not worth it

David's performance idea 8 of 10 (2026-11-25): pack the delta-update pieces
(installer/make_delta.py, PAD-1519) with zstd instead of zlib level 9 for
smaller downloads and faster unpacking. The ticket said to measure on the
last few real releases first. Measured; the answer is no, the format stays
zlib.

## What was measured

`scripts/measure_delta_compression.py MANIFEST PACK [...]` unpacks every
blob a release's manifest places in its pack and repacks it alone (as
make_delta.py does) with zstd (the `zstandard` 0.25 module the Python 3.12
app would need), timing both decompressors. Real assets downloaded from the
releases on 2026-11-25:

| pack | files | zlib-9 | zstd-3 | zstd-19 | zstd-22 |
|---|---|---|---|---|---|
| v1.596.2 | 22 | 539,303 | +2.9% | -10.8% | -10.8% |
| v1.596.3 | 13 | 249,476 | +4.0% | -5.6% | -5.7% |
| v1.597.0 | 22 | 339,125 | +5.1% | -6.2% | -6.3% |
| v1.597.1 | 13 | 229,359 | +3.7% | -5.3% | -5.4% |
| v1.598.0 | 24 | 410,046 | +4.9% | -6.1% | -6.1% |
| v1.599.1 | 97 | 10,278,076 | +2.9% | -2.7% | -2.7% |
| v1.599.2 | 15 | 360,941 | +1.7% | -10.6% | -10.6% |
| **7 releases** | | 12.41 MB | +3.0% | -3.6% | -3.6% |
| v1.575.0 base (whole tree) | 6,202 | 196.4 MB | -2.1% | -14.0% | -14.3% |

Unpacking: 1-2 ms per release pack with either (zlib 22 ms, zstd-19 14 ms
for all seven together); the whole 449 MB tree 0.50 s zlib vs 0.38 s
zstd-19. Packing the whole tree at zstd-19 takes 70 s on the CI's critical
path (zlib-9 is a few seconds), 147 s at level 22.

## Why no

* **A routine update saves 20-40 KB.** A release's own pack is 230-540 KB;
  zstd-19 trims 5-11% of that. The PAD-1519 end-to-end update was ready in
  4.7 s for 0.14 MB downloaded: the time is copying and hashing the 460 MB
  install and the ~0.4 s of redirects per request, not decompression
  (1-2 ms, under 0.1%). "Much faster unpacking" is real per byte but there
  are almost no bytes to unpack.
* **The switch costs every installed copy one full setup exe.** Apps out
  there accept only `format: 1` with zlib/stored pieces
  (core/update_delta.py `parse_manifest`); a zstd manifest is refused and
  they fall back to the 157 MB setup exe. That one fallback per install
  outweighs thousands of releases' worth of 30 KB savings. Avoiding it means
  publishing two manifests and two packs per release (zlib for old apps,
  zstd for new), more upload on the release's critical path for the same
  30 KB.
* **The big win is only the rare whole-tree case** (27 MB of 196 MB, when
  the bundled Python or its packages change wholesale), and that case is
  capped by the setup exe anyway (`max_download`).
* **A new compiled dependency** (`zstandard`, a pinned wheel in the bundled
  Python 3.12) to ship and keep building for that.

## If it is ever revisited

The format already carries a version, so the safe path is: teach the app to
read `format: 2` with a `ZSTD = 2` piece method first (zlib/stored rows
still valid, so a format-2 manifest can keep pointing at the old zlib
packs), ship that reader for a good while, and only then publish format 2.
Re-run the script above on the then-current packs before deciding.
