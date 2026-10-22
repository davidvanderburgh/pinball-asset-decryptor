"""The CPU board's bus master (the ``netbridge`` MCU), run from the program
the card carries, for game programs that key their sounds through it
(PAD-674).

Every released Spike 2 build in the library seeds its sound keystream from
constants in the game program.  Early builds (Jurassic Park 1.13, Venom LE
0.95) don't carry the seed: the game asks the CPU board's bus master four
questions over the node bus (frame ``0d 05 <op> <word>``), seeds its
keystream from the answers, and asks again to unscramble its sound
directory's header, to whiten each record and to check the result.  The
board answers from a per-slot state word the game sets at start-up (``0d 05
<slot<<4> <seed>``, the seeds being constants in the game program) and a
hash of its own, and nothing in the game program stands in for that hash.

The board's program is on the card, though: ``usr/local/spike/netbridge.hex``
(Intel hex, plain Cortex-M0 code), the image the game flashes into the board
when the board's version differs.  This runs it in unicorn and asks it the
way the game does: a frame laid out as the board's receive buffer has it,
its ``0d`` handler entered, the bytes it hands to its UART send routine
taken as the reply, stopping where it returns to its main loop.  The
board's RAM persists across asks, as on the machine between the reset the
game gives the board and the next.

The three entry points (the handler, the UART send, the main loop) are per
firmware version (:data:`SITES`, by the version in the file's name, each
checked against the first instruction at each site); a version not listed
raises :class:`BoardFirmwareError`, as does a card without the file.
Proven on Jurassic Park LE 1.13 (netbridge 0.5.0): the game's own CRC of
its unwhitened sound directory matches the value it expects, and the sounds
decode to audio.
"""
import glob
import os
import re
import struct

from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_MCLASS, UC_MODE_THUMB,
                     Uc)
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R1,
                               UC_ARM_REG_R10, UC_ARM_REG_R3, UC_ARM_REG_R5,
                               UC_ARM_REG_R7, UC_ARM_REG_R9, UC_ARM_REG_SP)

#: the board's RAM (LPC11xx: 0x10000000); the state words are its first four
RAM = 0x10000000
RAMSZ = 0x4000
_FRAME = RAM + 0x2000      # the receive buffer we hand the handler
_STATUS = RAM + 0x2100     # its status word (sb)
_STACK = RAM + 0x3f00

#: per firmware version: where the ``0d`` handler reads the frame, the UART
#: byte send, the main-loop return, and the first instruction (Thumb) at each
SITES = {
    "0_5_0": dict(handler=0x792, send=0x11dc, loop=0x446,
                  check={0x792: 0x7b3b, 0x11dc: 0xb5f8, 0x446: 0x465b}),
}

_NAME = re.compile(r"netbridge[-_]?([0-9_]+)\.hex$", re.I)


class BoardFirmwareError(RuntimeError):
    """A board-keyed game program without a board the app can run; the
    message is the user's."""


def load_hex(path):
    """The Intel-hex file at *path* as the flash image (bytes from 0)."""
    mem = {}
    base = 0
    with open(path, encoding="ascii", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line.startswith(":"):
                continue
            b = bytes.fromhex(line[1:])
            n, addr, kind, d = b[0], (b[1] << 8) | b[2], b[3], b[4:4 + b[0]]
            if kind == 0:
                for i, x in enumerate(d):
                    mem[base + addr + i] = x
            elif kind == 4:
                base = ((d[0] << 8) | d[1]) << 16
            elif kind == 2:
                base = ((d[0] << 8) | d[1]) << 4
    if not mem:
        raise BoardFirmwareError("%s holds no program" % os.path.basename(path))
    out = bytearray(max(mem) + 1)
    for a, v in mem.items():
        out[a] = v
    return bytes(out)


class NetBridge:
    """The board, answering as its own firmware does."""

    def __init__(self, image, sites, name="netbridge"):
        self.name = name
        self.sites = sites
        for va, word in sites.get("check", {}).items():
            got = struct.unpack_from("<H", image, va)[0] if va + 2 <= len(image) else None
            if got != word:
                raise BoardFirmwareError(_unknown(name))
        self.mu = mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        mu.mem_map(0, (len(image) + 0x1fff) & ~0xfff)
        mu.mem_write(0, image)
        mu.mem_map(RAM, RAMSZ)
        self.sent = []
        self.asks = 0
        mu.hook_add(UC_HOOK_CODE, self._code)

    @classmethod
    def from_file(cls, path):
        name = os.path.basename(path)
        m = _NAME.search(name)
        sites = SITES.get(m.group(1)) if m else None
        if sites is None:
            raise BoardFirmwareError(_unknown(name))
        return cls(load_hex(path), sites, name)

    def _code(self, mu, addr, size, _ud):
        if addr == self.sites["send"]:
            self.sent.append(mu.reg_read(UC_ARM_REG_R1) & 0xff)
            mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
        elif addr == self.sites["loop"]:
            mu.emu_stop()

    def ask(self, op, value):
        """The board's 4-byte answer to ``0d 05 <op> <value>``, or None for
        an op it answers nothing to (a slot set)."""
        mu = self.mu
        frame = bytes(8) + bytes([0x0d, 5, op & 0xff]) + struct.pack("<I", value & 0xffffffff) + b"\x04"
        mu.mem_write(_FRAME, frame)
        mu.reg_write(UC_ARM_REG_R7, _FRAME)
        mu.reg_write(UC_ARM_REG_R10, RAM)        # sl: the state words
        mu.reg_write(UC_ARM_REG_R9, _STATUS)     # sb: the status word
        mu.reg_write(UC_ARM_REG_R3, 5)
        mu.reg_write(UC_ARM_REG_R5, 0)
        mu.reg_write(UC_ARM_REG_SP, _STACK)
        mu.reg_write(UC_ARM_REG_LR, self.sites["loop"] | 1)
        self.sent = []
        self.asks += 1
        mu.emu_start(self.sites["handler"] | 1, 0, count=20000)
        if len(self.sent) == 4:
            return struct.unpack("<I", bytes(self.sent))[0]
        return None

    def reset(self):
        """The board as the game's reset pulse leaves it: state words zero."""
        self.mu.mem_write(RAM, bytes(RAMSZ))


def _unknown(name):
    return ("This card's sounds can't be read: its game code gets the key to its "
            "sounds from the machine's CPU board, and this card's board program "
            "(%s) isn't one the app knows yet." % name)


def beside(game_real_path):
    """The board for the card whose program is *game_real_path*: the
    ``netbridge*.hex`` the engine copied beside it (:func:`find_on_card`).
    Raises :class:`BoardFirmwareError` when there is none or its version is
    not known."""
    files = sorted(glob.glob(os.path.join(os.path.dirname(game_real_path) or ".",
                                          "netbridge*.hex")))
    if not files:
        raise BoardFirmwareError(
            "This card's sounds can't be read: its game code gets the key to its "
            "sounds from the machine's CPU board, and the board's program "
            "(netbridge.hex) isn't on this card for the app to run.")
    return NetBridge.from_file(files[-1])
