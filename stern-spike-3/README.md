# stern-spike-3

Reverse-engineering and tooling for **Stern "Spike 3"** (2025-generation, e.g.
Star Wars 2025, Pokémon, Walking Dead Remastered) SD card encryption, toward
extracting the audio/video assets on a PC.

## TL;DR

Spike 3 runs on a **Raspberry Pi CM4**. The SD card's four data partitions
(`rootfs`, `data`, `connectivity`, `games`) are **LUKS2 / AES-XTS**. The unlock
key is the CM4's **256-bit customer OTP**, read at boot via `vcmailbox 0x00030021`
— exactly as the (signed) initramfs `/init` does. The scheme is fully understood
and an offline, pure-Python decryptor is built and **cross-validated against
`cryptsetup`**.

The catch: that key lives in the SoC's fuses and is **not in the SD image** (by
design). So decryption is 100% on-PC, but the key must be read **once** from a
physical board. If it's a single Stern-wide key (plausible for golden release
images, unproven), one read decrypts every Spike 3 game on any PC forever.

**Status:** scheme cracked ✅ · offline decryptor built + tested ✅ · OTP key
**not yet obtained** ⛔ (needs a one-time hardware read) · no working end-to-end
asset extraction yet.

## Layout

```
docs/
  REVERSE_ENGINEERING.md   how the encryption works; the full evidence; what's ruled out
  KEY_EXTRACTION.md        how to get the key (extractor card / SSH / serial) + how to decrypt
tools/
  luks_otp.py              offline LUKS2 verifier + AES-XTS decryptor (pure Python, no cryptsetup)
  build_extractor_card.py  build a boot image that dumps the OTP key to the FAT partition
  spike3_otp_probe.sh      read-only on-board probe: reports secure-boot enforcement + reads the OTP key (run on a board you own, over SSH/UART)
  image_sound.py           decode an extracted image.bin to per-sound WAVs (pure Python, no keys)
  xcheck_setup.sh          reproduces the cryptsetup cross-validation of luks_otp.py
tests/
  test_luks_otp.py         self-tests + end-to-end verify against a known-key LUKS2 fixture
  test_image_sound.py      self-tests for the image.bin sound decoder (synthetic container)
  fixtures/                a synthesized (non-Stern) LUKS2 header with a known key
```

Once the `games` partition is decrypted and `image.bin` is pulled out, the audio
needs no further keys: the sound master directory is plaintext and the bodies are
raw 44100 Hz signed-16-bit PCM (mono or stereo). `tools/image_sound.py` reads the
container and writes `idxNNNN.wav` per sound. The app's Spike 3 Extract does this
itself (its Audio box, on by default): each `image.bin` becomes
`sound/<path>/audio/idxNNNN.wav` in the project, e.g. `sound/pokemon_le/audio/`
and `sound/pokemon_le/spike3/spike_menu/audio/`, and the raw container is not
kept. The decoder lives in `pinball_decryptor/plugins/stern/spike3_sound.py`;
this CLI loads that file directly:

```sh
python tools/image_sound.py info    path/to/image.bin
python tools/image_sound.py extract path/to/image.bin --out out/audio
```

## Quick start

```sh
# prove the crypto + the decryptor work (no hardware, no Stern data)
cd stern-spike-3 && python -m pytest tests/ -v
python tools/luks_otp.py selftest

# build an OTP-key extractor card from a Spike 3 image (see docs/KEY_EXTRACTION.md FIRST)
python tools/build_extractor_card.py path/to/<game>.Release.64G.sdcard-secure.raw -o out/
```

## Getting the key (summary)

There is **no way to recover the key from the SD image** — it's hardware-fused.
The options, in `docs/KEY_EXTRACTION.md`:

- **Extractor card** (built) — patched boot image dumps the key to a text file on
  the FAT partition. Works only if the board doesn't *enforce* RPi secure boot;
  it's a safe, ~10-min test on a real machine.
- **SSH / serial console** (follow-up) — run Stern's own `vcmailbox … | xxd`
  one-liner on a live machine; survives secure boot. Gated on finding the remote
  shell, which a single decrypted `rootfs` would reveal.

Once a key is in hand, `tools/luks_otp.py verify` it against all three game images
to determine whether it's global, then decrypt the `games` partition (where the
assets are).

## Cross-reference

This consolidates and corrects an earlier local effort at
`C:\Users\david\Documents\development\spike 3` (full pipeline scripts + a hashcat
attempt that used a wrong 36-byte keyfile model — the real busybox-`xxd` keyfile
is **32 bytes**; see `docs/REVERSE_ENGINEERING.md` §6, §9).

## Disclaimer

Independent interoperability research, not affiliated with or endorsed by Stern
Pinball. Use only on machines/cards you own. No Stern firmware or keys are
included in this repository.
