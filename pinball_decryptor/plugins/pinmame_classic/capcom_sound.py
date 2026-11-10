"""Capcom sounds: every sound out of the sound ROMs (u28-u31), one WAV each.

Capcom's sound board (an 8752 CPU feeding TI TMS320AV120 MPEG decoders)
plays ordinary MPEG-1 Layer II audio: 144-byte frames, 32 kbit/s, 32 kHz,
mono, each with its standard ``FF FD 18/19 C0`` header.  What is Capcom's
own is how the frames are filed (PAD-1088; the same on Big Bang Bar,
Kingpin and Pinball Magic):

*Chips.*  The sound ROMs are chips 1-4: u28, u29, u30, u31.  Each starts
with a banner (title, version, copyright) and, at 0x40, a header: chip
number, size in 32 KB banks, a pointer to the board's code, and a
pointer to the chip's *sound table* (all zero when another chip's table
covers it: Pinball Magic files u28 and u29 under u29's).

*Pointers* are four bytes, ``chip, bank, address``: the 8752 sees each
chip through a 32 KB window, so the file offset is ``bank * 0x8000 +
(address & 0x7FFF)``.

*A sound table* is a big-endian ``u16`` count, then one 8-byte entry per
sound: ``u16 frames, u16 flag, pointer`` to the sound's *playlist*.  An
entry with no frames is an unused number.  The flag is 1 on almost every
sound (two Pinball Magic ones carry 70 and 15); it is kept in the index.

*A playlist* is ``u16 frames`` then that many frame pointers, in play
order.  A sound's frames sit just before its playlist, but a playlist can
name frames anywhere on the four chips.

*A frame* is stored as ``00 90 01`` (its length, 144, and a 1) and then
the 144 bytes of a standard MPEG frame.

The game's command scripts (beside the tables) play whole sounds or runs
of a sound's frames; every sound here is one table entry, whole, so
nothing in the ROMs is left out.  The frames are joined into an MPEG
stream and ffmpeg decodes it, the same as the board does.
"""

import os
import struct
import subprocess
import zipfile
from dataclasses import dataclass

#: chip number -> ROM name prefix
CHIPS = {1: "u28", 2: "u29", 3: "u30", 4: "u31"}
FRAME_BYTES = 144
FRAME_PREFIX = b"\x00\x90\x01"
#: the frame headers the board's decoders are fed (32 kbit/s, 32 kHz, mono)
FRAME_SYNC = (b"\xff\xfd\x18\xc0", b"\xff\xfd\x19\xc0")
RATE = 32000
_HEADER_AT = 0x40
_MAX_SOUNDS = 4096


class CapcomSoundError(Exception):
    pass


@dataclass
class CapcomSound:
    chip: int           # the chip whose table lists it
    number: int         # its entry number in that table
    flag: int
    frames: list        # file offsets, as (chip, offset), in play order

    @property
    def seconds(self):
        return len(self.frames) * 1152.0 / RATE

    @property
    def name(self):
        """``u28_017``: the table's ROM and the entry number."""
        return "%s_%03d" % (CHIPS[self.chip], self.number)


def offset(pointer):
    """``(chip, file offset)`` for a four-byte chip/bank/address pointer."""
    chip = pointer >> 24
    bank = (pointer >> 16) & 0xFF
    return chip, bank * 0x8000 + (pointer & 0x7FFF)


def read_chips(path):
    """``{chip: bytes}`` for the sound ROMs in a ROM zip (u28-u31, any
    version suffix).  Empty when it has none."""
    chips = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            base = os.path.basename(info.filename).lower()
            for chip, prefix in CHIPS.items():
                if base.startswith(prefix) and chip not in chips:
                    chips[chip] = z.read(info)
    return chips


def _u16(data, at):
    if at + 2 > len(data):
        raise CapcomSoundError("a sound table runs past its ROM's end")
    return data[at] << 8 | data[at + 1]


def _frame(chips, pointer):
    chip, at = offset(pointer)
    data = chips.get(chip)
    if data is None:
        raise CapcomSoundError("a sound names %s, which is missing"
                               % CHIPS.get(chip, "chip %d" % chip))
    if data[at:at + 3] != FRAME_PREFIX or \
            data[at + 3:at + 7] not in FRAME_SYNC:
        raise CapcomSoundError("no MPEG frame at %s 0x%06x"
                               % (CHIPS[chip], at))
    return chip, at + 3


def tables(chips):
    """``[(chip, file offset)]`` of every sound table, each once."""
    out = []
    for chip in sorted(chips):
        head = chips[chip][_HEADER_AT:_HEADER_AT + 10]
        if len(head) < 10:
            continue
        ptr = struct.unpack_from(">I", head, 6)[0]
        if not ptr:
            continue
        where = offset(ptr)
        if where[0] in chips and where not in out:
            out.append(where)
    return out


def read_sounds(chips):
    """Every sound in the ROMs, table by table, unused numbers skipped."""
    if not chips:
        raise CapcomSoundError("no sound ROMs (u28-u31) in the zip")
    found = tables(chips)
    if not found:
        raise CapcomSoundError("the sound ROMs have no sound table")
    sounds = []
    for chip, at in found:
        data = chips[chip]
        count = _u16(data, at)
        if count > _MAX_SOUNDS or at + 2 + 8 * count > len(data):
            raise CapcomSoundError("%s's sound table is not one"
                                   % CHIPS[chip])
        for n in range(count):
            frames, flag, ptr = struct.unpack_from(">HHI", data, at + 2 + 8 * n)
            if not frames:
                continue
            lchip, lat = offset(ptr)
            ldata = chips.get(lchip)
            if ldata is None or _u16(ldata, lat) != frames:
                raise CapcomSoundError(
                    "%s sound %d's playlist is not where its table says"
                    % (CHIPS[chip], n))
            if lat + 2 + 4 * frames > len(ldata):
                raise CapcomSoundError("a playlist runs past its ROM's end")
            ptrs = struct.unpack_from(">%dI" % frames, ldata, lat + 2)
            sounds.append(CapcomSound(chip, n, flag,
                                      [_frame(chips, p) for p in ptrs]))
    return sounds


def mpeg(chips, sound):
    """The sound as an MPEG-1 Layer II stream (what ffmpeg decodes)."""
    return b"".join(chips[c][at:at + FRAME_BYTES] for c, at in sound.frames)


def decode(chips, sound, ffmpeg, wav_path):
    """Decode one sound to a 16-bit mono WAV at the board's 32 kHz.

    ffmpeg only takes a stream once it has seen two frames in a row, and
    some sounds are one frame long, so the last frame goes in twice and
    the output is cut back to the sound's own 1152 samples a frame."""
    tmp = wav_path + ".part"
    stream = mpeg(chips, sound)
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "mp3", "-i", "pipe:0",
         "-af", "atrim=end_sample=%d" % (len(sound.frames) * 1152),
         "-c:a", "pcm_s16le", "-ar", str(RATE), "-ac", "1", "-f", "wav",
         tmp],
        input=stream + stream[-FRAME_BYTES:], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0 or not os.path.isfile(tmp):
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise CapcomSoundError("ffmpeg could not decode %s: %s" % (
            sound.name, proc.stderr.decode("utf-8", "replace").strip()[-300:]))
    os.replace(tmp, wav_path)


def extract_all(path, output_dir, ffmpeg, log=None, progress=None,
                cancel=None):
    """Write every sound in *path*'s sound ROMs to ``audio/<name>.wav``
    under *output_dir*, and ``audio/sounds.csv`` listing them.  Returns
    ``{"samples": n, "seconds": total}``."""
    log = log or (lambda msg, level="info": None)
    chips = read_chips(path)
    sounds = read_sounds(chips)
    audio_dir = os.path.join(output_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    log("  %d sound(s) in %s" % (
        len(sounds), ", ".join(CHIPS[c] for c in sorted(chips))), "info")
    rows = ["file,rom,number,frames,seconds,flag"]
    total = 0.0
    for i, s in enumerate(sounds):
        if cancel is not None and cancel():
            return None
        if progress is not None:
            progress(i, len(sounds), "decoding %s" % s.name)
        decode(chips, s, ffmpeg, os.path.join(audio_dir, s.name + ".wav"))
        total += s.seconds
        rows.append("%s.wav,%s,%d,%d,%.3f,%d" % (
            s.name, CHIPS[s.chip], s.number, len(s.frames), s.seconds,
            s.flag))
    if progress is not None:
        progress(len(sounds), len(sounds), "sounds decoded")
    with open(os.path.join(audio_dir, "sounds.csv"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rows) + "\n")
    return {"samples": len(sounds), "seconds": total}
