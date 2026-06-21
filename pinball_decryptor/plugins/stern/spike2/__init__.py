"""Self-contained Spike 2 audio codec engine.

Everything here derives from the card's ``game_real`` firmware + ``image.bin``
asset container alone — no captured/derived blobs are bundled:

  * :mod:`elf`        — minimal ELF parser (PT_LOAD segments + GOT relocations).
  * :mod:`locate`     — build-independent firmware-address discovery, so titles
                        other than the validated build decode without hardcoded
                        addresses (returns None for dual-path / unsupported).
  * :mod:`rbtree`     — ``std::_Rb_tree_insert_and_rebalance`` for the harness.
  * :mod:`emulator`   — boots ``game_real`` in unicorn, builds the keystream /
                        runtime tables, derives per-sound params, and decodes.
  * :mod:`codec`      — analytic re-encode (recover the per-position keystream
                        with a pre-companding capture hook, then invert).

The heavy third-party deps (unicorn, capstone, numpy) are imported here, so
importing this subpackage is what requires them — the plugin's registration and
detection paths never touch it (they stay import-light).
"""
