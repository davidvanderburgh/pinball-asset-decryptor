# Spike 3 Replace tabs and Write (PAD-1186)

David: every Replace tab (Audio, Video, Images, Text, Scenes, Colors) on a
Stern **Spike 3** card, clicked through in the app end to end, Write included.

## The finding that makes it small

A Spike 3 card's games partition (p6, LUKS2 `aes-xts-plain64` over ext4) holds
**Spike 2's own asset tree**: `<title>/assets/lcd/auto_loaded/<sha>/scene.radium`
with its `scene.assets/*.asset` clips, loose PNGs, `image.bin`, and
`spk/index/<title>-<ver>.sidx` (FINF records, the same HMAC key). The Godot
game draws those scenes with Stern's own renderer, beside its own `main.pck`.

So the card is opened as **one plaintext partition** (`spike3_card.GamesVolume`)
and handed to the Spike 2 engine as a one-partition disk `[(0, size)]`:

- reads decrypt the covering XTS sectors (the existing
  `DecryptingSegmentReader`),
- writes read-modify-write whole 512-byte sectors and encrypt them back under
  the card's master key with the sector number as tweak - XTS is per sector,
  so a write changes the ciphertext of exactly the sectors it touches.

Measured on pokemon_le 0.82.0, the Spike 2 extractors ran unchanged: 263
videos (all named from scene data), 295 images, 315 scene pictures + 7849
glyphs, 186 text lines; `_compute_patches` produced video / image / text
writes and refreshed the FINF records with no change but one switch.

The engine's one switch: `engine._is_spike3(disk_f)` (the volume carries
`pad_spike3`). `_locate` then accepts `image.bin` with no Spike 2 program
beside it (the game is an aarch64 Godot program), and the write core leaves
the sounds to Spike 3's own writer.

The boot partition (the only signed one) is never touched, so nothing needs
re-signing.

## Extract (spike3_extract.py)

The SD pipeline runs `extract_videos`, `extract_images`, the scene textures /
radium pictures / spine, `extract_radium_text`, then the sounds, then
`generate_checksums`. Phases and categories are unchanged (the `.spk`
pipeline shares them; it has no card to write back to and keeps its layout).
"Scenes" on a card = the scenes' pictures and their words.

Sounds: one `image.bin` per sound set. The game's -> `audio/idxNNNN.wav`
(Spike 2's folder), another -> `audio_<its folder>/` (`audio_spike_menu`, the
service menu's), so two sets never share an `idxNNNN` name.

## Sounds (spike3_write.plan_sounds)

`image.bin` is plain 16-bit PCM at 44.1 kHz behind a plaintext directory of
24-byte records `{u64 offset, u32 flags (stereo = 0x2 << 16), u32 param,
u32 frames, u32 param2}`. Measured (pokemon, fallout, star_wars_elg,
walking_dead_remastered; game + service menu containers):

- the 8-byte trailer's first word is **CRC32 of the whole aligned directory**
  (`align16(24 * count)` bytes, padding included - odd counts prove it);
- header `0x40` = directory offset, header `0x38` = `filesize - 4` (the
  trailer's second word); `filesize == md_off + align16(24n) + 8`;
- `param2` is unique per sound and is no checksum of the body (crc32,
  adler, md5/sha1 words, crc of the record all tried): an id. Never changed.
- ~220 KB of something else sits between the last body and the directory, and
  0x80..first body is not sound either: both kept byte for byte.

Every replacement plays at its own length, as on Spike 2:

- not longer than its sound: the body goes over the old one in place and the
  record's `frames` is cut to it; the directory and its CRC are rewritten in
  place;
- longer: appended after the old body region, the directory moved past it
  with the record re-pointed, the CRC and the two tail words moved; the
  container goes on the card whole (a grow job).

`.sidx`: the container's record is refreshed from what the card then holds.

Music banks (merged from main's PAD-1185): `image-scNN.bin` beside an
`image.bin` is the same container (Fallout LE 0.81.0: 69 banks, Transformers
LE 0.96.0: 45; all 115 containers of the two follow the directory-CRC,
`0x38` and size rules above). They extract into their `image.bin`'s folder as
Spike 2's `music_catNN_NNNN.wav`, and `project_sound_dirs` gives each bank as
a container of its own with that stem, so a replaced song goes into its own
bank (in place or grown, staged as `<folder>_image-scNN.bin`), never into
`image.bin`'s `idx` of the same number nor another bank.

## Growing a file on an encrypted card (ext4_grow luks_key)

The grow script opens the partition through dm-crypt (`cryptsetup open
--type luks2 --volume-key-file`, the key in a 0600 file in /dev/shm only while
cryptsetup reads it), mounts the mapper device and runs the same copies.
Stock WSL 6.6.87.2 carries `dm_crypt` as a module and cryptsetup 2.7.
Without cryptsetup or dm-crypt: `PAD_GROW_NOCRYPT` -> `Ext4GrowUnavailable`;
macOS / native Linux (debugfs platforms) refuse an encrypted card up front.

## Write (spike3_write.write_card)

1. open the original's games volume (the original's key opens the copy too);
2. `_compute_patches` over it; plan the sounds;
3. nothing changed -> refuse, before any copy;
4. copy the card (`shutil.copyfile` on a thread, progress + cancel polled);
5. open the copy's volume writable; apply the engine's writes, the in-place
   sounds, the containers' `.sidx` records;
6. grow jobs (the engine's oversized videos, a grown container) through
   dm-crypt;
7. the build record beside the card (`.pad-build.json`) with a fresh
   `build_id`.

## The card store and a rebuilt card

`s3store.card_id` fingerprints the first 64 KiB of each volume, which an
in-place Write never touches - a rebuild under the same name read as the card
already stored, so Emulate ran the last build. The id now also takes the
`build_id` of the record beside the card; a stock card has none and keeps
its id (nothing already in the store is rebuilt).

## Proof

See the ticket's report: the readback of a built card through its own
encryption, the emulator runs (frames + the game's sound captured muted from
the fifo), and the click-through in the app (scripts/shot_pad1186.py).
