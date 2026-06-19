"""Stern Pinball game database and detection metadata.

Stern's modern games run on the **Spike** hardware platform and ship their
content on an SD card / SSD as a raw disk image with multiple partitions:

* A data partition holds ``image.bin`` — a single packed container of every
  audio "category-0" sound (and other assets), each encoded with a per-sound
  stream cipher whose keystream is produced by the game firmware.
* The rootfs partition holds the game executable (``game_real``) — the
  firmware that owns the codec.  The decode/replace engine drives this
  firmware (in an emulator) to recover each sound's keystream.

Currently implemented: **Spike 2** (i.MX6, unencrypted ext4 card).  The audio
codec is fully reverse-engineered — every cat-0 sound decodes to WAV from
``image.bin`` + ``game_real`` alone, and new audio can be re-encoded back in
(size-neutral), bit-exact, for all 32 codec "scale" variants, mono and stereo.

The decode params + keystream are firmware-specific, so each supported title
ships a small derived-params blob (see ``data/``).
"""

GAME_DB = {
    "tmnt": {
        "display": "Teenage Mutant Ninja Turtles (Spike 2)",
        "platform": "spike2",
        # Filename substrings that hint at this title on a raw .img.
        "filename_hints": ["tmnt", "turtle", "ninja"],
        # Per-firmware derived data shipped with the plugin (under data/).
        "params": "tmnt_cat0_decode_params.pkl",
    },
}
