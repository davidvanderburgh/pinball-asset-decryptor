"""PICTURE SETTINGS (PAD-537): BRIGHTNESS, CONTRAST and SATURATION in the game's own service menu.

An owner asked to "provide end users with the facility for simple colour and brightness controls
in the service menu", with "a test card showing Saturation, Brightness, Contrast". A Write with the
Write tab's "Picture settings in the service menu" ticked does two things:

1. the operator menu gets the three rows (:mod:`.menu_settings`), on Adjustments > Machine
   Settings > LCD/Lamp beside the game's own LCD Brightness: values 1 to 9, 5 (no change) the
   default, a help line each. They take settings the game no longer reads (Godzilla 1.16 has
   three, the DEPRECATED LED max brightnesses), the ones MUSIC MODE and EDITION leave: a card
   with neither gets all three, a card with both BRIGHTNESS alone;
2. ``picture.cfg`` beside the mode runtime names the game program's import slots of four GL
   calls, where each setting's value lives and what each value means, and where the test card
   goes. The runtime (pad_mode_runtime.c "picture settings") re-points those slots: every
   fragment shader the game hands GL gets a last step that applies the three, and once a frame
   the values are read, so a value accepted in the menu changes the whole screen at once; for
   :data:`CARD_MS` after a change the Color profile tab's test card is drawn on the game's
   screen (right of the menu's rows, under its "Set new value"), through the same step.

PAD-575: THAT STEP COSTS THE MACHINE'S GPU ON EVERY PIXEL, even at 5. A tester's Godzilla card
with all three at 5 drew 7-9 pictures a second in busy scenes on the machine; the same card
written without picture settings played smoothly. So the runtime only adds the step when the game
last ran with a value away from 5 (it keeps the values in ``/dump/pad_picture.state``, the
shaders being compiled at boot before the game has read its settings): at 5, the default, the
game draws exactly as it does without picture settings, and a value changed in the menu takes
effect from the next start of the game (the help lines say so). Away from 5 the step is on, live,
test card included, until a start that finds all three back at 5.

The maths are the Color profile tab's (core/colour_profile.py ``Profile.curve``: brightness and
contrast folded into a gain and a power about the middle grey, saturation toward the Rec.601 grey),
the same the multi-boot menu's Color correction uses, on top of whatever the card was built with.

It rides the modes' delivery (the runtime, the title's port and the cfg on the system partition),
so it needs an image build, a title the app has a port for, and a game program that can grow.
Emulator-proven on Godzilla Premium/LE 1.16 (:data:`PROVEN`).
"""
from __future__ import annotations

import struct

from . import menu_settings as _MS

#: the project sidecar's key: ``{"on": true}``
STAGED_KEY = "picture_settings"
#: the runtime's table, beside mode.so on p2 (pad_mode_runtime.c PIC_FILES)
CFG_NAME = "picture.cfg"
#: the settings in the order they take spare adjustments (and are listed)
KEYS = (_MS.BRIGHTNESS, _MS.CONTRAST, _MS.SATURATION)
#: every setting's values, and the one that changes nothing (the default)
VALUES = 9
NORMAL = 5
#: what each value 1..9 means, in thousandths (pad_mode_runtime.c ``setting`` lines): brightness
#: and contrast 60% to 140% in tens, saturation black and white (0) to twice the color
FACTORS = {
    _MS.BRIGHTNESS: (600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400),
    _MS.CONTRAST: (600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400),
    _MS.SATURATION: (0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000),
}
#: each row's help line (the game's spare help strings hold 63 characters or more)
#: (PAD-575: a change takes effect at the game's next start, so they say "after restart")
HELP = {
    _MS.BRIGHTNESS: "Brightness after restart. 5 is normal, 1 darkest, 9 brightest.",
    _MS.CONTRAST: "Contrast after restart. 5 is normal, 1 softest, 9 strongest.",
    _MS.SATURATION: "Color after restart. 5 is normal, 1 black and white, 9 vivid.",
}
#: the four GL imports the runtime re-points (pad_mode_runtime.c PIC_SYMS)
SYMBOLS = ("glShaderSource", "glLinkProgram", "glUseProgram", "eglSwapBuffers")
#: the test card: x, y, width, height in GL pixels of the 1360 x 768 screen (origin bottom left),
#: 480 x 300 in the bottom right, below the menu's "Set new value" (seen on Godzilla 1.16)
CARD = (860, 6, 480, 300)
#: how long the test card stays after a value is accepted, ms
CARD_MS = 15000
#: ``<game>-<version>`` of the builds where the rows and the live picture were SEEN working
#: (emulator: a value accepted in the menu, the whole screen changing and the test card shown)
PROVEN = frozenset({"godzilla_le-1.16", "godzilla_pro-1.16"})

NO_TITLE = ("The app cannot tell which game this project is for, so it cannot give it picture "
            "settings.")
NOT_PROVEN = ("Picture settings have not been tried on %s yet, so they are not offered there. "
              "Godzilla Pro and Premium/LE 1.16 have them.")

_R_ARM_JUMP_SLOT = 22


class PictureError(ValueError):
    """The game program cannot take the picture settings; the message says why."""


def load(project):
    """Whether the project asks for the picture settings."""
    if not project:
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("on"))


def save(project, on):
    """Ask (or stop asking) for the picture settings; returns what it was before."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    was = bool(isinstance(data.get(STAGED_KEY), dict) and data[STAGED_KEY].get("on"))
    if on:
        data[STAGED_KEY] = {"on": True}
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def title_refusal(prof):
    """Why ``prof``'s title cannot have the picture settings, or ``""``."""
    from .sound_modes import title_key
    if prof is None:
        return NO_TITLE
    if title_key(prof) not in PROVEN:
        return NOT_PROVEN % prof.label
    return ""


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def wanted():
    """The rows for :func:`.menu_settings.plan_many`, in the order they take spare settings."""
    return [(k, VALUES, (), {"default": NORMAL, "help_text": HELP[k]}) for k in KEYS]


def import_slots(elf):
    """``{symbol: address}`` of the game program's import slots (``R_ARM_JUMP_SLOT``) of
    :data:`SYMBOLS`. Raises :class:`PictureError` when the program is not one the runtime can
    re-point (not a 32-bit ARM executable at a fixed address, or one of the four not imported)."""
    elf = bytes(elf)
    if len(elf) < 52 or elf[:4] != b"\x7fELF" or elf[4] != 1 or elf[5] != 1:
        raise PictureError("the game program is not a 32-bit ARM program")
    e_type, machine = struct.unpack_from("<HH", elf, 16)
    if e_type != 2 or machine != 40:
        raise PictureError("the game program is not an ARM executable at a fixed address")
    phoff = struct.unpack_from("<I", elf, 28)[0]
    phent, phnum = struct.unpack_from("<HH", elf, 42)
    loads, dyn = [], None
    for k in range(phnum):
        p_type, off, va, _pa, filesz, _memsz = struct.unpack_from("<6I", elf, phoff + k * phent)
        if p_type == 1:
            loads.append((va, off, filesz))
        elif p_type == 2:
            dyn = (off, filesz)

    def at(va):
        for v, o, n in loads:
            if v <= va < v + n:
                return o + va - v
        raise PictureError("the game program's import table is not where it says")

    if dyn is None:
        raise PictureError("the game program has no import table")
    tags = {}
    for k in range(0, dyn[1] - 7, 8):
        tag, val = struct.unpack_from("<iI", elf, dyn[0] + k)
        if tag == 0:
            break
        tags.setdefault(tag, val)
    if tags.get(20, 17) != 17 or 23 not in tags or 6 not in tags or 5 not in tags:
        raise PictureError("the game program's imports are not in the table the runtime reads")
    rel, size, symtab, strtab = at(tags[23]), tags.get(2, 0), at(tags[6]), at(tags[5])
    out = {}
    for k in range(0, size, 8):
        r_off, info = struct.unpack_from("<II", elf, rel + k)
        if info & 0xFF != _R_ARM_JUMP_SLOT:
            continue
        name_off = struct.unpack_from("<I", elf, symtab + (info >> 8) * 16)[0]
        end = elf.index(b"\x00", strtab + name_off)
        name = elf[strtab + name_off:end].decode("ascii", "replace")
        if name in SYMBOLS:
            out[name] = r_off
    missing = [s for s in SYMBOLS if s not in out]
    if missing:
        raise PictureError("the game program does not call %s through its import table"
                           % ", ".join(missing))
    return out


def cfg_text(slots, settings, only):
    """``picture.cfg``: *slots* from :func:`import_slots`, *settings* the
    :class:`.menu_settings.MenuSetting` of each row that went into the menu, *only* when the card
    carries no modes (the runtime then arms nothing else)."""
    lines = ["# PAD-537 picture settings: the operator's BRIGHTNESS, CONTRAST and SATURATION, live"]
    if only:
        lines.append("only")
    for sym in SYMBOLS:
        lines.append("got\t%s\t0x%08x" % (sym, slots[sym]))
    for s in settings:
        if s.key not in FACTORS:
            continue
        lines.append("\t".join(["setting", s.key, "0x%08x" % s.live] + [str(v) for v in FACTORS[s.key]]))
    lines.append("card\t%d\t%d\t%d\t%d\t%d" % (CARD + (CARD_MS,)))
    return "\n".join(lines) + "\n"


def menu_path():
    """Where the rows are, in the operator's words."""
    return "Adjustments > Machine Settings > LCD/Lamp"
