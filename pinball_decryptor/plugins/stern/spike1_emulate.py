"""Stern Spike 1 emulation — orchestration + the hardware-state model.

This is the PC-emulation surface for the Spike 1 era (the 2015-2016 DMD
generation).  It is deliberately split from the codec/asset work in
``spike1.py``: emulation runs the *real game binary* under qemu-user, whereas
``spike1.py`` only reads/writes the asset container.

Status (see ``docs/architecture/spike1_emulation.md`` for the full write-up):

* The rig in ``tools/spike1_emu/`` boots the real static ARM game binary under
  qemu-user in an unprivileged user+mount+pid namespace (no root, no
  LD_PRELOAD — the game is statically linked, so the Spike 2 shim technique
  does not apply).  It reaches **hardware initialization**: SoC detect, asset
  container open, the NVRAM tree, and the first device opens.
* It then needs a **device model** for the board peripherals (the i2c board-ID
  EEPROM at 0x50 is the first hard requirement, then the node bus, DMD, and
  audio).  A responding device model needs a one-time privileged setup on the
  host (CUSE, or a patched qemu-user) — see the doc.

What lives here and is usable *now*, independent of the boot depth:

* :class:`HardwareState` — a **format-agnostic** model of the machine's live
  I/O: switches, lamps/LEDs (RGB), and coils, each addressed by ``(node,
  index)``.  The switch-matrix / LED viewer (``tools/spike1_emu/s1view.py``)
  renders this, and injects switch presses back through :class:`SwitchInput`.
  Deliberately NOT a wire-format codec: the Spike 1 node-bus byte layout is
  unverified (no live capture yet), so the device model fills this state from
  whatever it decodes; the viewer only ever sees the abstract state.
* Rig path + prerequisite helpers the GUI Emulate tab uses.

The shared-state block (:class:`StateBlock`) is a small fixed-layout binary
buffer mmapped into a file in the run dir, so the (host-side) node-bus decoder
writes it and the viewer reads it without any IPC beyond the file.
"""

import os
import struct

# --------------------------------------------------------------------------
# hardware-state model (format-agnostic; the viewer's data contract)
# --------------------------------------------------------------------------

# Capacities are generous fixed maxima so the shared block is a constant size
# (a Spike machine addresses well under these).  node in 0..15, index in 0..63
# covers every Stern Spike node board's I/O.
MAX_NODES = 16
MAX_INDEX = 64
_MAGIC = 0x53314857          # "S1HW"
_VERSION = 1


def addr(node, index):
    """Flatten a ``(node, index)`` I/O address to a 0-based slot."""
    if not (0 <= node < MAX_NODES and 0 <= index < MAX_INDEX):
        raise ValueError("address out of range: node=%r index=%r"
                         % (node, index))
    return node * MAX_INDEX + index


N_SLOTS = MAX_NODES * MAX_INDEX


class HardwareState:
    """Live machine I/O, format-agnostic.

    * ``switches[slot]``  -> 0/1 (closed)
    * ``lamps[slot]``     -> (r, g, b) 0..255  (a plain lamp uses r=g=b=level)
    * ``coils[slot]``     -> 0/1 (energized)

    Slots are ``addr(node, index)``.  Names are optional labels the viewer
    shows (from a title's switch/lamp tables when available).
    """

    def __init__(self):
        self.switches = bytearray(N_SLOTS)
        self.lamps = bytearray(N_SLOTS * 3)
        self.coils = bytearray(N_SLOTS)
        self.switch_names = {}
        self.lamp_names = {}
        self.coil_names = {}

    # ---- switches ----
    def set_switch(self, node, index, closed):
        self.switches[addr(node, index)] = 1 if closed else 0

    def get_switch(self, node, index):
        return self.switches[addr(node, index)]

    # ---- lamps / LEDs ----
    def set_lamp(self, node, index, r, g=None, b=None):
        """Set a lamp/LED colour.  One value = a mono lamp at that level."""
        if g is None:
            g = r
        if b is None:
            b = r
        s = addr(node, index) * 3
        self.lamps[s] = r & 0xFF
        self.lamps[s + 1] = g & 0xFF
        self.lamps[s + 2] = b & 0xFF

    def get_lamp(self, node, index):
        s = addr(node, index) * 3
        return (self.lamps[s], self.lamps[s + 1], self.lamps[s + 2])

    # ---- coils ----
    def set_coil(self, node, index, on):
        self.coils[addr(node, index)] = 1 if on else 0

    def get_coil(self, node, index):
        return self.coils[addr(node, index)]

    def clear(self):
        for buf in (self.switches, self.lamps, self.coils):
            for i in range(len(buf)):
                buf[i] = 0


class StateBlock:
    """Fixed-layout binary serialization of :class:`HardwareState`.

    Layout (little-endian)::

        u32 magic  u32 version  u32 seq  u32 flags
        u8  switches[N_SLOTS]
        u8  lamps[N_SLOTS*3]
        u8  coils[N_SLOTS]

    ``seq`` bumps on every write so a reader can detect a fresh frame; the
    block is a constant size so it can be mmapped once.  The switch/lamp/coil
    *names* are not in the block (they're static per title — the viewer loads
    them separately).
    """

    HEADER = struct.Struct("<4I")
    SIZE = HEADER.size + N_SLOTS + N_SLOTS * 3 + N_SLOTS

    @classmethod
    def pack(cls, state, seq=0, flags=0):
        return (cls.HEADER.pack(_MAGIC, _VERSION, seq & 0xFFFFFFFF, flags)
                + bytes(state.switches) + bytes(state.lamps)
                + bytes(state.coils))

    @classmethod
    def unpack(cls, buf, state=None):
        """Fill *state* (or a new one) from *buf*; returns ``(state, seq,
        flags)``.  Raises ValueError on a bad magic/version/size."""
        if len(buf) < cls.SIZE:
            raise ValueError("state block too small: %d < %d"
                             % (len(buf), cls.SIZE))
        magic, version, seq, flags = cls.HEADER.unpack_from(buf, 0)
        if magic != _MAGIC:
            raise ValueError("bad state-block magic 0x%08x" % magic)
        if version != _VERSION:
            raise ValueError("unsupported state-block version %d" % version)
        st = state or HardwareState()
        o = cls.HEADER.size
        st.switches[:] = buf[o:o + N_SLOTS]
        o += N_SLOTS
        st.lamps[:] = buf[o:o + N_SLOTS * 3]
        o += N_SLOTS * 3
        st.coils[:] = buf[o:o + N_SLOTS]
        return st, seq, flags


class SwitchInput:
    """The reverse channel: the viewer's injected switch state -> the node-bus
    decoder.  A constant-size bitmap block (one bit per slot) mmapped in the
    run dir; the viewer sets bits on click, the decoder ORs them into what it
    reports to the game."""

    HEADER = struct.Struct("<3I")      # magic, version, seq
    _MAGIC = 0x53315357                # "S1SW"
    NBYTES = (N_SLOTS + 7) // 8
    SIZE = HEADER.size + NBYTES

    @classmethod
    def pack(cls, closed_slots, seq=0):
        bits = bytearray(cls.NBYTES)
        for slot in closed_slots:
            bits[slot >> 3] |= 1 << (slot & 7)
        return cls.HEADER.pack(cls._MAGIC, _VERSION, seq & 0xFFFFFFFF) + bytes(bits)

    @classmethod
    def unpack(cls, buf):
        magic, _version, seq = cls.HEADER.unpack_from(buf, 0)
        if magic != cls._MAGIC:
            raise ValueError("bad switch-input magic 0x%08x" % magic)
        bits = buf[cls.HEADER.size:cls.HEADER.size + cls.NBYTES]
        closed = {i for i in range(N_SLOTS) if bits[i >> 3] & (1 << (i & 7))}
        return closed, seq


# --------------------------------------------------------------------------
# rig orchestration helpers (used by the GUI Emulate tab)
# --------------------------------------------------------------------------

AVAILABLE = True

# The emulation rig scripts live alongside the Spike 2 rig, under tools/.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
RIG_DIR = os.path.join(_REPO_ROOT, "tools", "spike1_emu")


def rig_state_paths(run_dir):
    """The shared-state + switch-input file paths for a run dir."""
    return (os.path.join(run_dir, "s1hw.state"),
            os.path.join(run_dir, "s1sw.input"))


def init_state_files(run_dir):
    """Create zeroed shared-state + switch-input files so the viewer can
    mmap them before the rig writes anything.  Returns the two paths."""
    os.makedirs(run_dir, exist_ok=True)
    state_path, input_path = rig_state_paths(run_dir)
    if not os.path.exists(state_path) or \
            os.path.getsize(state_path) != StateBlock.SIZE:
        with open(state_path, "wb") as f:
            f.write(StateBlock.pack(HardwareState()))
    if not os.path.exists(input_path) or \
            os.path.getsize(input_path) != SwitchInput.SIZE:
        with open(input_path, "wb") as f:
            f.write(SwitchInput.pack(set()))
    return state_path, input_path
