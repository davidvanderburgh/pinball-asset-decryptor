#!/usr/bin/env python3
"""
image_sound.py - decode a Stern "Spike 3" image.bin sound container to per-sound WAVs.

The decoder itself lives in the app at
``pinball_decryptor/plugins/stern/spike3_sound.py`` (PAD-1077: a normal Spike 3
extract now writes ``sound/<game>/audio/idxNNNN.wav`` with it). This CLI loads
that one file directly - stdlib only, no package import, no keys - so it still
runs standalone from a checkout:

    python image_sound.py info    <image.bin>
    python image_sound.py list    <image.bin> [--limit N]
    python image_sound.py extract <image.bin> --out <dir> [--limit N]
    python image_sound.py selftest

See spike3_sound.py for the container format.
"""

import importlib.util
import os
import sys

_SRC = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "pinball_decryptor", "plugins", "stern", "spike3_sound.py"))
_spec = importlib.util.spec_from_file_location("spike3_sound", _SRC)
_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("spike3_sound", _mod)
_spec.loader.exec_module(_mod)

globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})

if __name__ == "__main__":
    raise SystemExit(_mod.main())
