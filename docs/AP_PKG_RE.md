# American Pinball `.pkg` Format — Reverse-Engineering Notes

Notes for the `ap` plugin: how American Pinball game-code updates
(`*-gamecode_*.pkg`) are packaged, and how the decryption key was recovered.

**Status:** Fully cracked. Container format, padding scheme, and the static
AES key are all confirmed; both a 2021 (Houdini) and a 2024 (Barry-O's BBQ)
package decrypt + ZIP-verify end-to-end. Clonezilla `.iso` extraction
(partclone ext4 restore) is not yet wired into the plugin.

## Container format

```
offset 0   8 bytes   plaintext (ZIP) length   — uint64, little-endian
offset 8   16 bytes  AES-CBC IV               — random per file
offset 24  N bytes   AES-256-CBC ciphertext   — space-padded to a 16B multiple
```

Total file size = `8 + 16 + roundup16(plaintext_length)`. The decryptor reads
the size, reads the IV, AES-CBC-decrypts the remainder, then **truncates to
the declared size** to drop the padding — it never inspects the padding
bytes. The plaintext is a plain ZIP of the P-ROC / pyprocgame tree
(`houdini.py`, `procgame/`, `assets/`, `config.yaml`, …; newer titles like
BBQ nest under a top-level `bbq/` and add `ApiLib/` + `apiav/`).

This is the same `[8B size][16B IV][AES-CBC ZIP]` container Spooky's P-ROC
titles use (Rick & Morty, Alice Cooper) — both descend from the same
`pkgprocess` helper, which is itself the well-known PyCrypto "encrypt a file
in CBC chunks" recipe (size prefix + IV + space-padded final block).

## The key

```
PACKAGE_SIGNING_KEY = '2f5fc7a0cae8aaf63aef767ceb998b7f'
```

`pkgprocess` passes that 32-character string **verbatim** to
`AES.new(key, AES.MODE_CBC, iv)`, so the ASCII bytes are the key → **AES-256**
(not the 16 hex-decoded bytes). It is a single static key shared across the
whole product line: byte-identical in `/usr/bin/pkgprocess` on the Houdini,
Oktoberfest, and Hot Wheels restore images, and it also decrypts the 2024
BBQ package. There is **no signature or MAC** anywhere in the package — every
byte is `8 + 16 + ciphertext` — so integrity rests entirely on key secrecy.

## How it was recovered

1. Blind analysis of the `.pkg` showed uniform ~7.997 bits/byte entropy after
   an 8-byte header whose first dword ≈ filesize and whose `(filesize - 24)`
   is a 16-byte multiple → AES-CBC with an explicit IV and block padding.
2. The Clonezilla restore ISO (Clonezilla Live + partclone v2 images) was
   opened with `7z`; the `sda5` (root) partclone image was decompressed and
   reconstructed to a raw ext4 image, then read with Sleuth Kit (`fls`/`icat`).
   `sda4` mounts at `/game`, `sda5` at `/`.
3. `/usr/bin/pkgprocess` turned out to be a plaintext Python 2 script
   containing the algorithm and `PACKAGE_SIGNING_KEY`. The USB update handler
   (`/usr/bin/codeupdate`) copies `*-gamecode*.pkg` to `/game/tmp/` and runs
   `pkgprocess`, which decrypts → unzips → `mv` into `/game/<title>/`.

## Plugin mapping

| Concept | Code |
|---|---|
| Key + chunk size | `ap/games.py` (`AP_AES_KEY`, `AES_CHUNK_SIZE`) |
| Decrypt / encrypt / key-probe | `ap/crypto.py` |
| Detection (filename + key-validated probe) | `ap/formats.py` |
| Extract / Write pipelines | `ap/pipeline.py` |

Detection runs **before** Spooky in the registry because Spooky's generic
AES-magic fallback (`bytes[4:8] == 0`) would otherwise claim AP packages;
`ap` instead key-probes (decrypt first block → expect `PK\x03\x04`), so it
only ever claims files that actually decrypt with the AP key.

## TODO / open items

- Clonezilla `.iso` extract path: AP images store partitions as
  `sdaN.ext4-ptcl-img.gz.*` (partclone), unlike the `.dd-ptcl-img` raw images
  `core/clonezilla.py` currently handles — needs a partclone→raw step
  (cf. `jjp/partclone_to_raw.py`) before `debugfs rdump`.
- Confirm the marketed title behind the `bbq` code name (referred to as
  "Barry-O's BBQ" here).
