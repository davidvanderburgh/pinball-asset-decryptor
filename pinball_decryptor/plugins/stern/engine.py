"""Spike 2 audio codec engine — integration point.

This wraps the proven standalone decode/replace engine (validated bit-exact for
all 32 codec scale-variants, mono + stereo).  The codec is a per-sample stream
cipher::

    out_j = G(ROR16(body16_j, rb_j) ^ K_j)        G(S) = (QMUL * sxth(S)) >> 16

Decode recovers ``K_j``/``rb_j`` by driving the game firmware (``game_real``) in
unicorn and reading the keystream just before the volume multiply; encode
inverts it analytically.

What this needs at runtime — ALL derived from the card alone (no shipped blobs):
  * ``game_real`` — read from the card's rootfs ext partition (pure-Python ext4).
  * ``image.bin`` — read from the card's data ext partition (pure-Python ext4).
  * vf2 table + rt tables (ac4/ac8/acc) — game_real BUILDS these at boot
    (verified: boot-built rt tables are byte-identical to the old captured
    files), so the emulator derives them; nothing is bundled.
  * per-sound params (×2053) — derived from ``image.bin`` + ``game_real`` via the
    chain (~64s); cache alongside the extract output.
  * ELF relocations — parsed from ``game_real`` itself.
  * voice template — synthesizable (the codec reads only ``voice[0]`` = obj ptr
    and ``voice[0xc]`` = cursor; the volume is a passed constant).

The only firmware-VERSION coupling is hardcoded addresses (codec 0x32b428,
boot 0x348198, dispatch 0x539d00, ...): stable across games on the same Spike 2
build; a very different build would need address re-resolution (not a blob).

The standalone implementation lives in the spike2 reverse-engineering workspace
(``spike2_extract.py`` / ``spike2_replace.py`` / ``spike2_genrecover.py`` /
``fc_exact2.py``).  Porting it here (parameterizing its hard-coded paths, reading
game_real / image.bin straight from the ext partitions, dropping the captured
rt/voice files in favour of the boot-built tables) is the next step, with GUI
verification.  Until then ``AVAILABLE`` is False and the pipelines surface a
clear status.
"""

import os

# Flips True once the ported engine lands (no bundled data dir needed — all
# inputs derive from the card's game_real + image.bin).
AVAILABLE = False


def extract_all(image_path, partitions, output_dir, log=None, progress=None,
                cancel=None):
    """Decode every cat-0 sound in the card image to ``output_dir`` as WAV.

    ``partitions`` is the list of ``(byte_offset, byte_size)`` ext partitions
    (from ``formats.linux_partitions``); the engine reads ``game_real`` from the
    rootfs partition and ``image.bin`` from the data partition.
    """
    raise NotImplementedError("Spike 2 decode engine not yet bundled.")


def write_image(original_path, assets_dir, output_path, log=None, progress=None,
                cancel=None):
    """Re-encode edited WAVs under ``assets_dir`` into a copy of the card image
    (size-neutral) written to ``output_path``."""
    raise NotImplementedError("Spike 2 replace engine not yet bundled.")
