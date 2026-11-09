# Spike 3 audio decode — recon (PAD-1076)

**Pivotal finding: this is NOT a Unicorn emulator port.** The Spike 3 game
firmware (`game`, AArch64 ELF, PIE, stripped) is dynamically linked and uses
**standard libraries**, so the Spike 2 approach (driving a custom embedded AES +
a custom per-sample stream codec through a Unicorn ARM32 harness) does not carry
over — and is not needed. Instead the decode is standard crypto + standard
codecs, reproducible in Python + ffmpeg once the key derivation is reversed.

## Evidence (from the SW PRO 0.84 game ELF)
Imported from OpenSSL 3 / FFmpeg 59 / ALSA / SoLoud:
- Crypto: **`EVP_aes_192_ofb`**, `EVP_DecryptInit/Update/Final`, `SHA1`, `SHA256`,
  `HMAC`. So the cipher is **AES-192 in OFB mode** (a standard OpenSSL cipher),
  and the key/IV are almost certainly derived from the seed via SHA/HMAC.
- Audio: `libavcodec`/`libavformat` (`avcodec_send_packet`/`receive_frame`),
  **SoLoud** (`external/soloud/.../stb_vorbis.cpp`), **Vorbis** (stb_vorbis),
  **ADPCM** ("Sound seeking is unsupported for ADPCM sounds"), WAV. So each sound
  is a standard codec payload — decodable with ffmpeg, no custom codec RE.

## image.bin layout (same master-dir container as Spike 2 — confirmed every title)
- `filesize == hdr[0x40] + align16(24*count) + 8`.
- SW PRO 0.84: `md_off = hdr[0x40] = 1013598274`, `count = hdr[0x60] = 1678`.
- Seed word at `md_off + align16(24*count)` = **`0x8da32980`**.
- Master directory = `24*count` bytes at `md_off`, **AES-192-OFB encrypted**
  (only 3/1678 records parse as plaintext offset/size, so it is not plaintext).
- Sound bodies occupy `[0, md_off)`; high entropy (~7.6 bits/byte) and no
  `OggS`/`RIFF` magic, so bodies are either raw/ADPCM/Vorbis-without-Ogg or
  AES-192-OFB encrypted — determined once the directory decrypts and names a
  body's codec + length.

## The work (revised, much smaller than an emulator port)
1. **Reverse the seed -> AES-192 key+IV derivation.** Disassemble the game ELF
   around the `EVP_DecryptInit(ctx, EVP_aes_192_ofb(), key, iv)` call that decodes
   the master dir, and trace how `key` (24 B) and `iv` (16 B) are built from the
   4-byte seed (likely a SHA256/SHA1/HMAC expansion). This is the one RE task.
2. **Decrypt the master directory** with pycryptodome AES-192-OFB; read each
   record's body offset / length / codec / sample-rate.
3. **Per sound:** slice its body from image.bin, AES-192-OFB decrypt if the record
   says so, then decode the standard codec payload to WAV with ffmpeg
   (`avcodec_find_decoder_by_name` in the ELF names the exact decoders used).
4. **Verify** a decoded WAV plays (ffprobe/ffmpeg) on a real title, then wire a
   "Sounds" category into the Spike 3 extract pipelines to emit `audio/*.wav`.

## Inputs
- Extracted `image.bin` + `game` ELF at `C:\tmp\pad1076\` (SW PRO 0.84, via the
  PAD-1072 decrypt). Any title works (five `.spk` in `D:\...\spike3\spk\`).
- Keys/mechanism stay in the private OneDrive\Documents\Spike3-Research, not the repo.

## Dependency
Operates on an already-extracted `image.bin` + `game` ELF, so it does not need
PAD-1072 merged; the extract (PAD-1072) produces those files.
