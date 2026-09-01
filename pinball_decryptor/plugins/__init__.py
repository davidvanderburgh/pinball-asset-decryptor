r"""Manufacturer plugins.

**A plugin's ``__init__`` must not import its manufacturer at module level.**
Python runs a package's ``__init__`` before it can hand out ANY module inside
it, so an eager ``from .manufacturer import X`` here means that reading one
small leaf module drags in the whole application: that manufacturer's
pipelines, every plugin they reach sideways (stern -> pinmame_classic ->
williams -> spooky), and with them pycryptodome, Pillow and the rest of
``requirements.txt``.

That matters because the emulator rigs import leaf modules from a **bare**
interpreter — the WSL distro's own ``python3``, which has nothing
pip-installed:

* ``tools/spike1_emu/build_rootfs.py`` reads a Spike 1 card with
  ``plugins.stern.ext4`` + ``plugins.stern.formats`` (pure-Python ext + the
  partition walk),
* ``tools/spike1_emu/s1view.py`` reads ``plugins.stern.spike1_emulate``,
* ``tools/jjp_emu/pfimage.py`` reads ``plugins.jjp.crypto``.

Eagerly, every one of those died with ``ModuleNotFoundError: No module named
'Crypto'`` raised deep inside the *Spooky* plugin, from scripts that never
touch Spooky — the Spike 1 emulator could not extract a card at all.

So each entry point does its importing inside ``register()``, which
:func:`pinball_decryptor.core.registry.load_plugins` calls at startup.  The
app pays exactly the same cost, one call later, and a leaf module costs only
what it actually uses.  ``tests/test_rig_leaf_imports.py`` holds the line.
"""
