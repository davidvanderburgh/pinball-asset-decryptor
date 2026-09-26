"""A mode's OWN SOUNDS: the stock requests that carry them, and the sound bank that holds them (item 150).

A Spike 2 game plays sounds by REQUEST id; a request names sound ids, and each names a record
in ``image.bin``. A mode cannot add a request, so each sound of its own rides on a stock
request the game never plays in the meantime (a CARRIER): a record is appended to the bank
and the carrier's descriptor re-pointed at it (item 130, the engine's grow path). The mode
file then names the carrier (``sound_start`` / ``sound_shot`` / ``sound_end`` / ``music``,
read by ``tools/spike2_emu/modes/sdk/mode_file.c``).

Carriers, per title. Request ids and names are the same on Godzilla Pro 1.15 and Premium
1.16; the sids and records under them are not. The CALL carriers are the game's
Japanese-language variants of its own callouts (an English game plays the sibling one id
below): single sid, a record and a sid no other request names, no constant call site - the
test ``tools/spike2_emu/modes/sound_map.py`` runs over the ELF and the bank. MUSIC carriers
are stereo requests passing the same test. Whether normal play ever fires one is measured by
the census (``sdk/sound_census.c``); each title's ``status`` says how far that got.

The one way the game plays a Japanese variant: ``callout`` swaps a request for its Japanese
one (a 147-entry map built at run time) only while the CURRENT PLAYER's flag in RuleCities is
set. What sets it is NOT traced; the game's strings ("PLAYER LANGUAGE SELECT", "USE FLIPPERS
TO SELECT LANGUAGE:", "Japanese") point at a per-player language choice the operator can turn
on. With default adjustments a census game played 9 swap sources in English and 0 variants,
so a mode's own call is safe unless a player ends up with Japanese callouts.
Read off both ELFs (desk): the adjustment ``AD_PLAYER_LANGUAGE_SELECT`` ("PLAYER LANGUAGE
SELECT") has a compiled default of Off on Pro 1.15 and Premium 1.16; the menu ``LANGUAGE``
offers only English, German, French, Spanish and Italian; the one "Japanese" string sits in a
small UNKNOWN / Japanese / English table beside "USE FLIPPERS TO SELECT LANGUAGE:". So only an
operator who turns PLAYER LANGUAGE SELECT on can let a player reach the Japanese callouts.

MUSIC carriers, checked at the desk on Premium 1.16 (2026-09-17; request ids are the same on
Pro 1.15). The census covered attract and whole games with default adjustments; it never
reached the features below, so each was traced in the ELF instead:
  - THEME MUSIC (adjustment 160) picks 66 / 67 / 68 / 69 / 70 / 73.
  - Godzilla multiball music selection (202, default On) and its Random pick play 122, 73,
    77, 88, 96, 101, 106 (the Random list is 7 u16s at 0x6431a4).
  - The u16 run at 0x714510 that names 125 and 127 is the Game Audits menu's list of audit
    ids (handler 0x3d1e50 beside "Game Audits"), not a list of requests.
  - Terror of Mechagodzilla plays 863-866 by name ({"terrorloop1", 863} ... at 0x70e56c), and
    918 and 863 play on effects buses (0x08 / 0x04 in RUN 1's dump), where the game's music
    goes on underneath. So those five are NOT music carriers any more.
  - The DJ MIXER (a player jukebox, adjustment 106 default On, offered only in FREE PLAY) was
    measured in the emulator (item 150 RUN 9, Premium 1.16, census over all its playlists): its
    ALL SONGS list is 40 requests from the unnamed block 127-179, and it starts on 127
    ("GODZILLA"), so 127 is NOT a carrier. 125 was in no playlist. Not traced: ATTRACT DEV
    CREDITS MUSIC (245, default Off).

Lengths. A record appended for a sound must be longer than the carrier's own, so a SHORTER
sound gets silence after it. For music, :func:`build_bank` tiles the WAV in whole repeats past
the carrier's length instead, so the record loops it without a gap. For a call, the mode file
carries the sound's own length (:func:`cfg_lines` ``ms``) and mode_file.c stops the carrier
once that much has played, so the silence does not hold the voice bus.
"""
from __future__ import annotations

import os
import shutil
import struct
from dataclasses import dataclass, field

SOUND_KEYS = ("sound_start", "sound_shot", "sound_end", "music")


@dataclass(frozen=True)
class Carriers:
    key_mask: int                        # the build's descriptor key mask (measured)
    calls: tuple                         # mono requests, best first
    music: tuple                         # stereo requests, best first
    status: str = "provisional"          # "provisional" (static test) or "census" (measured in play)
    notes: dict = field(default_factory=dict)
    #: item 150 follow-up: sound ids NO request names, each the only name of its stereo record,
    #: longest stock record first. Each holds ONE mode's music bed; the mode points the music
    #: carrier at its own bed while it runs (``music <request> <sid>``, pad_mode.h
    #: ``pm_sound_sid``), so every mode has music of its own on the one carrier.
    beds: tuple = ()
    #: item 163: every sound of a mode's own on this title is SWAPPED in at run time. Each carrier's
    #: own record is grown with the mode's sound and left un-pointed (no stock sound id changes);
    #: while the mode plays it, the runtime swaps the carrier's key for the appended record's
    #: (pad_mode.h ``pm_sound_swap``). Carriers are distinct per sound, music too.
    swap: bool = False


# The 21 Japanese-language variants, longest record first on Premium 1.16 (the same ids on
# Pro 1.15). A sound longer than its carrier's record grows the record; a shorter one is
# followed by silence, which mode_file.c cuts off when the mode file gives the sound's length.
_JP_CALLS = (1251, 1249, 1133, 1020, 1170, 1188, 945, 1174, 1186, 1192, 1172, 1076, 1190,
             1247, 1129, 1197, 972, 1281, 1259, 1101, 979)
# Stereo, on the music bus, never fired in either census or by the DJ Mixer. 125 carries the music
# priority word (0x101) the game's own tunes carry. Dropped 2026-09-17: 918 and 863 / 864 / 866
# (effects buses; Terror of Mechagodzilla plays the TERRORLOOPs) and 127 (the DJ Mixer's first
# track). ONE music carrier, so one mode per project can have music. mode_file.c starts the music
# again whenever no channel plays it.
_MUSIC = (125,)

# Music BEDS (item 150 follow-up, read at the desk 2026-09-18 with the request table, the
# descriptor sites and the stock derive): the sids no request of the build names whose record no
# requested sid names either, stereo, longest stock record first - and whose descriptor is long
# enough to take the music carrier's looping-music head (engine._music_template_writes: a bed's
# bus and loop are its DESCRIPTOR's, measured in the rig; four of the sixteen free stereo sids,
# Premium 6 / 34 / 59 / 51 = Pro 57 / 5 / 62 / 9, are too short and are left out). The two builds
# number the same sounds differently (Premium 1.16 sid 618 = Pro 1.15 sid 257, a 4.13 s record).
# A bed's record is grown past its stock length and its sid re-pointed at it; nothing the game
# plays names that sid, and the census (which counts requests) cannot see a sid, so what is NOT
# traced is a sid the game might play without a request (none is known).
_BEDS_LE116 = (618, 105, 576, 555, 357, 422, 88, 768, 122, 172, 547, 548)
_BEDS_PRO115 = (257, 94, 234, 369, 347, 617, 605, 607, 421, 486, 248, 391)

# status "census": no carrier played in the emulator's census over attract and played games with
# default adjustments - Premium 1.16 RUN 1 (441 requests), Pro 1.15 RUN 2B (495 requests, two
# whole 3-ball games). It does not cover the DJ Mixer or the Japanese callouts (see above).
TITLES = {
    ("godzilla_le", "1.16"): Carriers(key_mask=0xE0001FFF, calls=_JP_CALLS, music=_MUSIC, status="census",
                                      beds=_BEDS_LE116),
    ("godzilla_pro", "1.15"): Carriers(key_mask=0xFC0003FF, calls=_JP_CALLS, music=_MUSIC, status="census",
                                       beds=_BEDS_PRO115),
}


# Item 163: every other latest build, by KEY SWAP (Carriers.swap). Read off each card by the app's
# own resolver and the build's request table (item 163's carrier census): calls are
# single-sid mono voice requests, longest record first (a call cannot outlast its carrier's
# record); music are stereo music-bus requests, looping first. "census": none of them played in the
# emulator's full scripted check game with the sound log on; "provisional": not yet measured.
# key mask, calls, music, status
_SWAP = {
    ("aerosmith_le", "1.15"): (0xFFFC0003, (635, 566, 609, 506, 577, 581, 583, 558, 305, 584, 441, 564, 575, 578, 440, 556, 568, 414, 557),
        (68, 99, 103, 95, 108), "census"),
    ("avengers_infinity_le", "1.09"): (0xFF0000FF, (681, 688, 738, 751, 729, 685, 690, 810, 684, 809, 634, 817, 592, 730, 708, 581, 667, 694, 709, 726, 591),
        (99, 71, 101, 77, 87), "census"),
    ("beatles", "1.29"): (0x80007FDF, (112, 123, 133, 234, 176, 180, 220, 315, 329, 93, 116, 157, 124),
        (), "census"),
    ("deadpool_le", "1.14"): (0x70000FF7, (859, 863, 583, 587, 864, 540, 585, 539, 572, 580, 565, 586, 861, 556, 551, 561, 553, 862, 544, 841, 552),
        (), "census"),
    ("deadpool_pro", "1.16"): (0xFFF0000F, (864, 868, 588, 592, 869, 545, 590, 544, 577, 585, 570, 591, 866, 561, 556, 566, 558, 867, 549, 846, 557),
        (), "census"),
    ("dungeons_and_dragons_le", "1.00"): (0xBF780007, (1136, 1119, 1273, 1134, 843, 1138, 1131, 824, 1099, 1095, 845, 1140, 1076, 852, 1147, 846, 1141, 848, 1143, 1045, 847),
        (67, 86, 64, 125, 75), "census"),
    ("elvira3", "1.13"): (0xFF70000F, (829, 432, 414, 831, 830, 387, 1906, 1134, 385, 804, 382, 416, 2179, 408, 419, 403, 1187, 401, 372, 379, 618),
        (320, 3427, 298, 3430, 1941), "census"),
    ("foo_fighters_le", "1.04"): (0x800075FF, (899, 875, 321, 314, 281, 316, 315, 280, 805, 322, 898, 320, 312, 327, 352, 339, 184, 313, 317, 200, 806),
        (63, 64), "census"),
    ("godzilla_pro", "1.16"): (0xE0001FFF, (1845, 1846, 2001, 1319, 2008, 1545, 1548, 1996, 2006, 1457, 1550, 2007, 1851, 1547, 1850, 1597, 1544, 1999, 1037, 1539, 1848),
        (123, 86, 73, 79, 101), "census"),
    ("guardians_le", "1.14"): (0xE0001FFF, (625, 680, 538, 722, 549, 857, 729, 598, 683, 699, 791, 694, 600, 686, 602, 860, 691, 624, 862, 527, 893),
        (90, 93, 112, 113, 138), "census"),
    ("iron_maiden_le", "1.16"): (0x7F00007B, (489, 298, 498, 491, 465, 490, 482, 471, 390, 392, 456, 386, 383, 367, 384, 388, 391, 449, 385, 346, 389),
        (551, 553, 539, 541, 545), "census"),
    ("james_bond_60th_le", "1.11"): (0x7FC0002F, (147, 151, 150, 146, 145, 171, 170, 144, 149, 148, 143, 142, 139, 138, 191, 190, 137, 233, 136, 232, 131),
        (102, 82, 89, 98, 79), "census"),
    ("james_bond_le", "1.06"): (0xE0001FFF, (1057, 1071, 291, 1060, 1010, 1008, 1058, 1052, 401, 297, 1012, 1013, 1068, 1059, 173, 1054, 394, 1021, 764, 1014, 1018),
        (94, 66, 168, 72, 95), "census"),
    ("jaws_le", "1.02"): (0xF0000FFF, (554, 1215, 1217, 1216, 1222, 1220, 1232, 1229, 1233, 555, 1231, 1228, 1224, 1219, 1225, 1221, 1236, 1377, 1218, 1343, 1316),
        (130, 129, 77, 124, 109), "census"),
    ("john_wick_le", "1.01"): (0xFFA0001F, (445, 374, 442, 441, 453, 443, 406, 439, 417, 371, 382, 418),
        (61, 96, 73, 72, 83), "census"),
    ("jurassic_park_le", "1.16"): (0xDF80003F, (999, 933, 786, 915, 732, 855, 918, 759, 737, 904, 819, 712, 853, 867, 851, 763, 852, 835, 906, 841, 829),
        (99, 90, 107, 108, 97), "census"),
    ("jurassic_park_the_pin", "1.05"): (0xE0001FFF, (285, 296, 310, 328, 306, 330, 298, 304, 286, 302, 300, 331, 297, 289, 307, 313, 305, 303, 299, 332),
        (66, 68, 75, 81, 78), "census"),
    ("king_kong_le", "0.97"): (0xE0001FFF, (721, 722, 720, 725, 724, 718, 726, 723, 711, 739, 710, 709, 742, 963, 968, 706, 896, 888, 943, 693, 700),
        (67, 68, 84, 65, 71), "census"),
    ("led_zeppelin_le", "1.22"): (0xE0001FEF, (269, 203, 255, 268, 205, 254, 204, 202, 267, 272, 207, 190, 286, 293, 251, 257, 198, 201, 291, 233, 234),
        (76, 70, 80, 64, 74), "census"),
    ("led_zeppelin_pro", "1.22"): (0xFC0002FF, (269, 203, 255, 268, 205, 254, 204, 202, 267, 272, 207, 190, 286, 293, 261, 251, 257, 198, 201, 291, 233),
        (70, 80, 64, 74, 71), "census"),
    ("mando_le", "1.44"): (0xF0000FBF, (672, 674, 690, 685, 873, 662, 701, 695, 680, 677, 670, 660, 683, 684, 641, 712, 688, 687, 616, 661, 678),
        (115, 102, 104, 78, 88), "census"),
    ("metallica_spike", "1.03"): (0xFFFF0000, (735, 734, 705, 715, 709, 710, 724, 698, 657, 714, 701, 706, 725, 723, 736, 737, 100, 704, 713, 726, 711),
        (81,), "census"),
    ("munsters_le", "1.28"): (0xF80003FF, (426, 565, 417, 422, 421, 423, 436, 184, 420, 434, 428, 425, 433, 431, 435, 429, 418, 424, 432, 430, 419),
        (70, 71, 69, 79, 73), "census"),
    ("rush_le", "1.18"): (0xEFFF0000, (257, 309, 248, 308, 346, 350, 305, 291, 279, 306, 304, 301, 277, 300, 324, 278, 256, 271, 310, 352, 255),
        (71, 60, 72, 70, 63), "census"),
    ("star_wars_elg", "1.10"): (0xFF60001F, (133, 200, 199, 72, 236),
        (68, 343, 344, 71, 76), "census"),
    ("star_wars_le", "1.30"): (0x80007FFF, (797, 802, 803, 804, 798, 796, 794, 799, 728, 795, 800),
        (63, 88, 93, 65, 84), "census"),
    ("stranger_things_le", "1.12"): (0x00003FFF, (307, 680, 229, 576, 739, 630, 647, 296, 667, 147, 490, 471, 489, 663, 593, 607, 622, 639, 148, 262, 514),
        (65, 110, 111, 112, 64), "census"),
    ("sword_of_rage_le", "1.18"): (0xF7F40003, (439, 377, 374, 376, 470, 485, 448, 479, 455, 535, 504),
        (100, 92, 86, 87, 104), "census"),
    ("turtles_le", "1.59"): (0xFF80006F, (703, 698, 731, 583, 706, 705, 736, 744, 699, 594, 507, 549, 695, 591, 740, 659, 684, 742, 438, 585, 578),
        (433, 74, 70, 101, 95), "census"),
    ("turtles_pro", "1.59"): (0xABFF0000, (703, 698, 731, 583, 706, 705, 736, 744, 699, 594, 507, 549, 695, 591, 740, 659, 684, 742, 438, 585, 578),
        (433, 101, 95, 97, 99), "census"),
    ("uncanny_xmen_le", "0.98"): (0xFFBC0003, (729, 677, 116, 705, 115, 691, 652, 706, 738, 578, 544, 728, 543, 542, 653, 725, 541, 698, 762, 550, 693),
        (88, 75, 71, 74, 80), "census"),
    ("venom_le", "1.07"): (0xFC0003FF, (943, 928, 937, 881, 882, 942, 939, 1580, 944, 914, 941, 899, 915, 886, 925, 905, 1829, 1775, 916, 880, 875),
        (124, 117, 140, 106, 95), "census"),
}
for (_g, _v), (_m, _c, _mu, _st) in _SWAP.items():
    TITLES[(_g, _v)] = Carriers(key_mask=_m, calls=_c, music=_mu, status=_st, swap=True)


class ModeSoundError(ValueError):
    """Own sounds that cannot be carried or built as asked."""


def carriers(game, version):
    """The title's :class:`Carriers`, or ``None`` when no carrier has been measured for it."""
    return TITLES.get((game, str(version)))


def assign(game, version, wants, taken=(), taken_beds=()):
    """Carriers for several modes' own sounds, distinct across all of them.

    *wants* is one entry per mode slot, each a collection of the :data:`SOUND_KEYS` that
    mode has a WAV for. Returns ``[{key: request}]`` in the same order. Calls come off the
    title's call list in slot order (start, shot, end), music off its music list, so a
    project's assignment only changes when its modes' sounds do. *taken* are requests
    already carrying a sound in this build (item 149 asks one sound at a time): they are
    never handed out again, so no carrier gets two sounds. Raises
    :class:`ModeSoundError` when the title has no carriers or runs out.

    Music on a title with BEDS (item 150 follow-up): every mode's music is the title's one
    music carrier plus a bed sid of its own, returned as ``"music"`` (the request) and
    ``"music_sid"`` (the bed); the carrier itself holds no sound, so several modes share it
    and each still plays its own music. *taken_beds* are beds already holding a sound."""
    c = carriers(game, version)
    if c is None:
        raise ModeSoundError("no sound carriers are known for %s %s" % (game, version))
    used = {int(r) for r in taken}
    calls = [r for r in c.calls if r not in used]
    beds = [s for s in c.beds if s not in {int(b) for b in taken_beds}]
    music = list(c.music[:1]) if c.beds else [r for r in c.music if r not in used]
    out = []
    for slot, keys in enumerate(wants):
        keys = set(keys)
        bad = keys - set(SOUND_KEYS)
        if bad:
            raise ModeSoundError("slot %d: unknown sound key(s) %s" % (slot, sorted(bad)))
        got = {}
        for key in SOUND_KEYS:
            if key not in keys:
                continue
            if key == "music" and c.beds:
                if not music or not beds:
                    raise ModeSoundError(
                        "%s %s has no music bed left for slot %d (%d beds, %d modes' own sounds)"
                        % (game, version, slot, len(c.beds), len(wants)))
                got["music"] = music[0]
                got["music_sid"] = beds.pop(0)
                continue
            pool = music if key == "music" else calls
            if not pool:
                raise ModeSoundError(
                    "%s %s has no %s carrier left for slot %d (%d modes' own sounds)"
                    % (game, version, "music" if key == "music" else "call", slot, len(wants)))
            got[key] = pool.pop(0)
        out.append(got)
    return out


def cfg_lines(assigned, shot_every=1, ms=None):
    """The mode-file lines for one slot's :func:`assign` result. *ms* is ``{key: length in
    ms}`` of the calls' own sounds (:func:`call_ms`): mode_file.c stops a call's carrier once
    that much has played, so the silence after a sound shorter than the carrier's record does
    not hold the voice bus. The music never takes a length (its record is tiled)."""
    ms = ms or {}
    lines = []
    for key in SOUND_KEYS:
        req = assigned.get(key)
        if not req:
            continue
        length = int(ms.get(key) or 0) if key != "music" else 0
        every = int(shot_every or 1)
        if key == "music" and assigned.get("music_sid"):
            # item 150 follow-up: the mode's own bed; mode.so points the carrier at it
            lines.append("%-14s %d %d" % (key, req, int(assigned["music_sid"])))
        elif key == "sound_shot" and length:
            lines.append("%-14s %d %d %d" % (key, req, every, length))
        elif key == "sound_shot" and every > 1:
            lines.append("%-14s %d %d" % (key, req, every))
        elif length:
            lines.append("%-14s %d %d" % (key, req, length))
        else:
            lines.append("%-14s %d" % (key, req))
    return lines


def sound_ms(path):
    """A WAV's length in whole milliseconds (rounded up), or ``None`` if it cannot be read."""
    import math
    import wave
    try:
        with wave.open(path, "rb") as w:
            n, rate = w.getnframes(), w.getframerate()
    except Exception:  # noqa: BLE001 - a float or unreadable WAV: no length, the record plays out
        return None
    if not n or not rate:
        return None
    return int(math.ceil(n * 1000.0 / rate))


def call_ms(spec, folder):
    """``{key: ms}`` for the CALLS a mode has a WAV for (start, shot, end), for :func:`cfg_lines`."""
    have = {"sound_start": spec.sound_start, "sound_shot": spec.sound_shot, "sound_end": spec.end_sound}
    out = {}
    for key, name in have.items():
        if name:
            length = sound_ms(os.path.join(folder, name))
            if length:
                out[key] = length
    return out


def tile_wav(src, dst, min_frames_44k):
    """Write *src* repeated WHOLE until it is at least *min_frames_44k* frames long at 44.1 kHz,
    so a record that loops it has no silence and no seam but its own. Returns the repeat count.
    Integer PCM is tiled byte for byte; any other WAV the engine can read is written as 16-bit."""
    import math
    import wave
    try:
        with wave.open(src, "rb") as w:
            params, frames = w.getparams(), w.readframes(w.getnframes())
        n, rate = params.nframes, params.framerate
        if not n or not rate:
            raise ModeSoundError("%s holds no audio" % src)
        reps = max(1, int(math.ceil(min_frames_44k / (n * 44100.0 / rate))))
        with wave.open(dst, "wb") as w:
            w.setnchannels(params.nchannels)
            w.setsampwidth(params.sampwidth)
            w.setframerate(rate)
            w.writeframes(frames * reps)
        return reps
    except wave.Error:
        pass
    import numpy as np

    from . import engine as E
    a, ch, rate = E._read_wav_any(src, np)
    n = len(a) // ch
    if not n or not rate:
        raise ModeSoundError("%s holds no audio" % src)
    reps = max(1, int(math.ceil(min_frames_44k / (n * 44100.0 / rate))))
    pcm = np.clip(a[:n * ch], -32768, 32767).astype("<i2").tobytes()
    with wave.open(dst, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm * reps)
    return reps


#: The game declares a sound's duration in 1/4000 s and the voice loops at that duration, so a
#: record loops exactly only when its audio is a whole number of 441-sample (10 ms) steps.
LOOP_STEP = 441
#: A bed's record is repeated to outlast its mode (item 150 follow-up): the engine's own restart of a
#: record at its end drops ~4 ms (measured in the rig on a bed's loop seam, and on the game's own tunes),
#: so a mode never reaches it. Seconds past the mode's time, and the longest record made that way.
BED_MARGIN_S = 3
BED_MAX_S = 150


def bed_min_frames(mode_seconds, stock_length=0):
    """Frames a mode's bed record needs so the mode's music never reaches the record's own loop:
    the mode's time + :data:`BED_MARGIN_S` (its start waits for the game's music to fade, its end
    fades), at most :data:`BED_MAX_S`, and never less than the stock record it grows."""
    want = int((min(float(mode_seconds or 0) + BED_MARGIN_S, BED_MAX_S)) * 44100)
    return max(want, int(stock_length))
LOOP_XFADE_MS = 40.0


def _seam_ok(a):
    """1 when *a* (frames x ch float, -1..1) runs from its last frame into its first with no
    step the click detector would flag (|jump| over 25 x the 5 ms mean before it and > 0.05)."""
    import numpy as np
    n = min(len(a), 221)
    if n < 8:
        return False
    for c in range(a.shape[1]):
        d = np.abs(np.diff(a[-n:, c]))
        jump = abs(float(a[0, c]) - float(a[-1, c]))
        if jump > 0.05 and jump > 25.0 * max(float(d.mean()), 1e-9):
            return False
    return True


#: A bed's RECORD fades in over this long at its head and out at its tail (the showcase, 2026-09-18):
#: a bed started at its loop head's full level, a step the click detector flagged at 4 of 7 bed starts
#: in the rig. The record outlasts its mode (bed_min_frames), so its faded tail - and the record's own
#: loop point, now a dip rather than a seam - is never reached while the mode runs; every tile seam
#: inside it stays the loop's own seamless seam.
BED_EDGE_MS = 60.0


def _edge_fades(pcm16, ch, ms):
    """*pcm16* (int16 bytes, *ch* channels) with a raised-cosine fade in over its first *ms* and out
    over its last, both edges landing on zero."""
    import numpy as np
    a = np.frombuffer(pcm16, "<i2").reshape(-1, ch).astype(np.float64)
    n = min(len(a) // 2, int(round(ms * 44.1)))
    if n > 1:
        ramp = (0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n)))[:, None]
        a[:n] *= ramp
        a[len(a) - n:] *= ramp[::-1]
    return np.clip(np.round(a), -32768, 32767).astype("<i2").tobytes()


def loop_wav(src, dst, min_frames_44k, xfade_ms=LOOP_XFADE_MS, edge_ms=0.0):
    """Write *src* as a SEAMLESS loop, repeated whole until it is at least *min_frames_44k*
    frames at 44.1 kHz (item 150 follow-up: a mode's music bed must loop with no click).

    - 44.1 kHz, 16-bit, the source's channels (resampled by linear interpolation if needed);
    - the loop is a whole number of :data:`LOOP_STEP` samples, so the record the build makes
      of it ends exactly where its declared duration does;
    - its seam: a source that already runs from its end into its start with no step and is a
      whole number of steps is kept as it is; any other has its loop cut near its end at the
      step where the audio that FOLLOWS the cut best matches its head, and those following
      *xfade_ms* crossfaded (equal power) onto the head, so the end flows into the start;
    - repeated whole, so every tile seam and the record's own loop are that same seam;
    - with *edge_ms* (a mode's bed: :data:`BED_EDGE_MS`), the whole record fades in at its head and
      out at its tail, so the bed never ENTERS with a step; its own loop point becomes a dip.
    Returns ``(repeats, loop_frames)``. Raises :class:`ModeSoundError` for a WAV too short to
    loop (under 0.5 s)."""
    import math
    import wave

    import numpy as np

    from . import engine as E
    a, ch, rate = E._read_wav_any(src, np)
    a = np.asarray(a[: len(a) // ch * ch], np.float64).reshape(-1, ch)
    if ch > 2:
        a, ch = a[:, :2], 2
    if not len(a) or not rate:
        raise ModeSoundError("%s holds no audio" % src)
    if rate != 44100:
        t = np.arange(int(len(a) * 44100 / rate)) * (rate / 44100.0)
        a = np.stack([np.interp(t, np.arange(len(a)), a[:, c]) for c in range(ch)], 1)
    n = len(a)
    if n < 22050:
        raise ModeSoundError("%s is %.2f s: too short to loop (0.5 s at least)" % (src, n / 44100.0))
    x = int(round(xfade_ms * 44.1))
    if n % LOOP_STEP == 0 and _seam_ok(a / 32768.0):
        body = a
    else:
        head = a[:x].ravel()
        best, best_l = -2.0, None
        hi = (n - x) // LOOP_STEP * LOOP_STEP
        lo = max(LOOP_STEP, hi - 200 * LOOP_STEP)          # search the last ~2 s of cut points
        for cut in range(hi, lo - 1, -LOOP_STEP):
            tail = a[cut:cut + x].ravel()
            den = float(np.linalg.norm(head) * np.linalg.norm(tail))
            score = float(np.dot(head, tail)) / den if den > 0 else 0.0
            if score > best + 1e-9:
                best, best_l = score, cut
        body = a[:best_l].copy()
        w = np.linspace(0.0, 1.0, x)[:, None]
        body[:x] = a[:x] * np.sqrt(w) + a[best_l:best_l + x] * np.sqrt(1.0 - w)
    loop = len(body)
    reps = max(1, int(math.ceil(min_frames_44k / float(loop))))
    pcm = np.clip(np.round(body), -32768, 32767).astype("<i2").tobytes()
    whole = pcm * reps
    if edge_ms:
        whole = _edge_fades(whole, ch, edge_ms)
    with wave.open(dst, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(whole)
    return reps, loop


def title_version(profile_key):
    """``("godzilla_pro", "1.15")`` from a mode profile key such as ``godzilla_pro_1_15``."""
    parts = str(profile_key).split("_")
    if len(parts) < 3 or not (parts[-1].isdigit() and parts[-2].isdigit()):
        return None, None
    return "_".join(parts[:-2]), "%s.%s" % (parts[-2], parts[-1])


def wants(spec):
    """The :data:`SOUND_KEYS` a mode (a ``mode_project.ModeSpec``) has a WAV for."""
    have = {"sound_start": spec.sound_start, "sound_shot": spec.sound_shot,
            "sound_end": spec.end_sound, "music": spec.music}
    return tuple(k for k in SOUND_KEYS if have.get(k))


def assign_specs(profile_key, specs):
    """:func:`assign` for a project's modes in slot order, keyed by their profile."""
    game, version = title_version(profile_key)
    return assign(game, version, [wants(s) for s in specs])


def sound_files(spec, folder, assigned):
    """``{request: WAV path}`` a :func:`build_bank` needs for one mode's assigned carriers."""
    have = {"sound_start": spec.sound_start, "sound_shot": spec.sound_shot,
            "sound_end": spec.end_sound, "music": spec.music}
    return {req: os.path.join(folder, have[k]) for k, req in assigned.items() if have.get(k)}


# ---- the bank ----------------------------------------------------------------------------
def _play_key(payload8, sid, mask):
    w1, w2 = struct.unpack("<II", payload8)
    return struct.pack("<II", w1, (w2 & mask) | (((sid >> 16) << 13) & 0xFFFFFFFF))


def request_sids(game_elf_bytes, fragments, requests):
    """``{request: [sid, ...]}`` from the game ELF's request table."""
    from .spike2 import sound_requests as SR
    from .spike2.elf import parse_elf
    count, table = SR.locate_sound_requests(game_elf_bytes, fragments)
    if count is None:
        raise ModeSoundError("the game's sound request table was not found")
    segs, _r = parse_elf(game_elf_bytes)

    def va2off(va):
        for vaddr, foff, filesz, _m in segs:
            if vaddr <= va < vaddr + filesz:
                return foff + va - vaddr
        return None

    end = table + count * 20
    out = {}
    for req in requests:
        if not 0 < req < count:
            raise ModeSoundError("request %d is outside the table (%d requests)" % (req, count))
        sids = []
        for w in struct.unpack_from("<5I", game_elf_bytes, table + req * 20):
            o = va2off(w) if w else None
            if o is None or o < end:
                continue
            for i in range(256):
                (s,) = struct.unpack_from("<I", game_elf_bytes, o + 4 * i)
                if s == 0:
                    break
                sids.append(s)
            break
        out[req] = sids
    return out


def request_records(sids_by_req, sites, params, key_mask):
    """``{request: record idx}`` for single-sid, single-record requests; raises for any other."""
    fk = {p["findkey"]: p["idx"] for p in params if p.get("findkey")}
    by_sid = {}
    for s in sites:
        by_sid.setdefault(s.sid, []).append(s)
    out = {}
    for req, sids in sids_by_req.items():
        if len(sids) != 1:
            raise ModeSoundError("request %d plays %d sids; a carrier needs exactly one" % (req, len(sids)))
        recs = {fk.get(_play_key(s.payload, s.sid, key_mask)) for s in by_sid.get(sids[0], ())}
        recs.discard(None)
        if len(recs) != 1:
            raise ModeSoundError("request %d (sid %d) names %d records under mask 0x%08X; a carrier needs one"
                                 % (req, sids[0], len(recs), key_mask))
        out[req] = recs.pop()
    return out


def sid_records(sids, sites, params, key_mask):
    """``{sid: record idx}`` for sids that each name exactly one record (a music bed's sid)."""
    fk = {p["findkey"]: p["idx"] for p in params if p.get("findkey")}
    out = {}
    for sid in sids:
        recs = {fk.get(_play_key(s.payload, s.sid, key_mask)) for s in sites if s.sid == sid}
        recs.discard(None)
        if len(recs) != 1:
            raise ModeSoundError("sid %d names %d records under mask 0x%08X; a bed needs one"
                                 % (sid, len(recs), key_mask))
        out[sid] = recs.pop()
    return out


def build_bank(game_elf, stock_image, out_image, sounds, work_dir, key_mask, log=None, music=(),
               beds=None, level_ref=None, bed_carrier=None, bed_seconds=None):
    """Append one record per own sound to a copy of *stock_image* and re-point each carrier.

    *sounds* maps carrier request -> WAV path. The requests in *music* are LOOPED sounds: a WAV
    shorter than its carrier's record is tiled in whole repeats past it, so the record loops the
    music with no silence; any other shorter sound is followed by silence. *beds* (item 150
    follow-up) maps a bed SID (:attr:`Carriers.beds`) -> a music WAV: its record is grown to hold
    the music, made a seamless loop (:func:`loop_wav`), and only that sid is re-pointed - no
    request plays it until a mode points the music carrier at it; the bed sid's descriptor is
    rewritten as a copy of the music carrier's (*bed_carrier*, default *level_ref*), so it plays on
    the music bus and loops (``engine._music_template_writes``). *level_ref* is a request whose
    stock record sets the loudness of every music sound (the game's own music, e.g. carrier 125);
    by default each sound matches its own carrier's stock record.

    Runs the engine's grow path end to end: descriptor sites, a staged bank with every record
    appended (``_stage_grown_image``), its derive (``_derive_grown``, which refuses if a stock
    record moved), the re-point (``_repoint_descriptors``, verified through the game's resolver,
    each declared duration ending where its record's audio ends), then the CHAIN-AWARE encode
    (``_chain_encode_appended``: the appended records encoded in the firmware's chain order, so
    no window of theirs is put back to the scaffold and none plays a scrap of another sound),
    and the engine's integrity check on the finished bank. The engine's key mask is set to
    *key_mask* for the duration (it is per build). Writes *out_image*; returns a report dict."""
    import numpy as np

    from . import engine as E
    from .info import container_counts
    from .spike2.emulator import BLOCK, Spike2Emu, collapse_shadowed, emitted_length

    log = log or (lambda msg, level="info": None)
    beds = dict(beds or {})
    if not sounds and not beds:
        raise ModeSoundError("no sounds to build")
    os.makedirs(work_dir, exist_ok=True)
    with open(stock_image, "rb") as f:
        fragments, _n = container_counts(f.read(0x100))
    fw = open(game_elf, "rb").read()
    bed_carrier = bed_carrier or level_ref
    if beds and not bed_carrier:
        raise ModeSoundError("music beds need the title's music carrier (bed_carrier)")
    sids = request_sids(fw, fragments, sorted(set(sounds) | {int(r) for r in (level_ref, bed_carrier) if r}))
    old_mask = E._DESC_KEY2_MASK
    E._DESC_KEY2_MASK = key_mask
    try:
        sites = E._descriptor_sites(game_elf, stock_image, log)
        emu = Spike2Emu(game_elf, stock_image)
        try:
            emu.boot()
            params_stock = collapse_shadowed(emu.derive_params())
        finally:
            emu.close()
        recs = request_records({r: sids[r] for r in sounds}, sites, params_stock, key_mask)
        bed_recs = sid_records(sorted(beds), sites, params_stock, key_mask)
        ref_idx = None
        if level_ref:
            ref_idx = request_records({int(level_ref): sids[int(level_ref)]}, sites, params_stock,
                                      key_mask)[int(level_ref)]
        idx_users = {}
        for req, idx in recs.items():
            idx_users.setdefault(idx, []).append("request %d" % req)
        for sid, idx in bed_recs.items():
            idx_users.setdefault(idx, []).append("bed sid %d" % sid)
        shared = {i: r for i, r in idx_users.items() if len(r) > 1}
        if shared:
            raise ModeSoundError("carriers share a record: %s" % shared)
        byidx = {p["idx"]: p for p in params_stock}
        edits, grows, loops, refs = {}, {}, set(), {}
        jobs = [("request %d" % req, recs[req], wav, req in set(music), 0) for req, wav in sounds.items()]
        jobs += [("bed sid %d" % sid, bed_recs[sid], wav, True, (bed_seconds or {}).get(sid, 0))
                 for sid, wav in beds.items()]
        for what, idx, wav, is_music, secs in jobs:
            want = E._wav_frames_44k(wav)
            if not want:
                raise ModeSoundError("%s: %s is not a readable WAV" % (what, wav))
            room = emitted_length(byidx[idx]["length"])
            # an appended record must be longer than the one it copies (masterdir's rule);
            # a shorter sound is padded with silence to just past it - or, for music, looped
            floor = int(byidx[idx]["length"]) - BLOCK + 1
            if is_music:
                looped = os.path.join(work_dir, "music_%d_loop.wav" % idx)
                reps, loop = loop_wav(wav, looped, bed_min_frames(secs, floor), edge_ms=BED_EDGE_MS)
                log("%s: %s made a seamless %.3f s loop, repeated %d time(s) to fill the record"
                    % (what, os.path.basename(wav), loop / 44100.0, reps))
                wav = looped
                want = E._wav_frames_44k(wav)
                loops.add(idx)
                if ref_idx is not None:
                    refs[idx] = ref_idx
            if want < floor:
                log("%s: %s is %.2f s, shorter than the carrier's record; %.2f s of "
                    "silence follow it" % (what, os.path.basename(wav), want / 44100.0,
                                           (floor - want) / 44100.0))
            grows[idx] = (room, max(want, floor))
            edits[idx] = os.path.abspath(wav)
            log("%s -> idx %d (%.2f s stock) carries %s (%.2f s)"
                % (what, idx, room / 44100.0, os.path.basename(wav), want / 44100.0))
        copy = os.path.join(work_dir, "image.stock_copy.bin")
        shutil.copyfile(stock_image, copy)
        staged, places = E._stage_grown_image(game_elf, copy, work_dir, byidx, grows, log)
        params, _reads = E._derive_grown(game_elf, staged, params_stock, log)
        patches, params = E._chain_encode_appended(game_elf, staged, params, edits, np, log,
                                                   loops=loops, level_refs=refs)
        E._assert_param_integrity(game_elf, staged, patches, params, np, log, work_dir)
        with open(staged, "r+b") as f:
            for off, body in sorted(patches.items()):
                f.seek(off)
                f.write(body)
        # The container key of an appended record comes out of the chain (measured: encoding the
        # records before it moved it), so the play tables are re-pointed at the keys the FINISHED
        # bank registers - after the chain encode, never before. The descriptors are no window of
        # any record, so this touches nothing the derive reads.
        templates = {}
        if beds:
            tsid = sids[int(bed_carrier)]
            if len(tsid) != 1:
                raise ModeSoundError("the music carrier %d plays %d sids; a bed needs one to copy"
                                     % (int(bed_carrier), len(tsid)))
            templates = {sid: tsid[0] for sid in beds}
        E._repoint_descriptors(game_elf, staged, params, sites, log, templates=templates)
        if os.path.abspath(staged) != os.path.abspath(out_image):
            shutil.move(staged, out_image)
    finally:
        E._DESC_KEY2_MASK = old_mask
    return {"records": recs, "beds": bed_recs, "loops": sorted(loops),
            "places": [(pl.idx, pl.new_idx, pl.body_off) for pl in places],
            "patches": len(patches), "out": out_image}


def clicks(x, ratio=25.0, floor=0.05, win=220):
    """Sample indexes where a click detector fires on *x* (one channel, -1..1): a first
    difference over *ratio* x its mean over the *win* samples before it AND over *floor*
    full scale. The rule every item 150 follow-up measurement uses (capture and record)."""
    import numpy as np
    x = np.asarray(x, np.float64)
    if len(x) <= win + 1:
        return []
    d = np.abs(np.diff(x))
    c = np.concatenate(([0.0], np.cumsum(d)))
    idx = np.arange(win, len(d))
    local = (c[idx] - c[idx - win]) / win
    return [int(i) + 1 for i in idx[(d[idx] > ratio * np.maximum(local, 1e-12)) & (d[idx] > floor)]]


def verify_bank(game_elf, stock_image, built_image, sounds, key_mask, log=None, beds=None,
                loop_wavs=None):
    """Check a :func:`build_bank` result from a fresh boot of each file: no stock record
    moved, every carrier's sid (and every bed sid) resolves to its appended record and nothing
    else does, each appended record decodes to its WAV, and the click detector (:func:`clicks`)
    finds nothing in any decoded record - nor, for a loop, across its seam. *loop_wavs*
    ``{record idx: wav}`` names the looped WAV a music sound was built from (the build's work
    dir); without it a loop is scored against its source WAV. Returns ``{key: corr}`` (key =
    request, or ``"sid N"`` for a bed) and raises :class:`ModeSoundError` on any failure."""
    import numpy as np

    from . import engine as E
    from .info import container_counts
    from .spike2.emulator import Spike2Emu, collapse_shadowed, emitted_length

    log = log or (lambda msg, level="info": None)
    beds = dict(beds or {})
    loop_wavs = dict(loop_wavs or {})
    with open(stock_image, "rb") as f:
        fragments, _n = container_counts(f.read(0x100))
    fw = open(game_elf, "rb").read()
    sids = request_sids(fw, fragments, sorted(sounds))
    stock_sites = E._descriptor_sites(game_elf, stock_image, log)
    built_sites = E._descriptor_sites(game_elf, built_image, log)
    emu = Spike2Emu(game_elf, stock_image)
    try:
        emu.boot()
        stock = collapse_shadowed(emu.derive_params())
    finally:
        emu.close()
    emu = Spike2Emu(game_elf, built_image)
    try:
        emu.boot()
        rows = emu.derive_params()
        n_stock = len(stock)
        moved = [r["idx"] for r in rows[:n_stock]
                 if (r["body_off"], r["length"], r["scale"], r["pred16"])
                 != (stock[r["idx"]]["body_off"], stock[r["idx"]]["length"],
                     stock[r["idx"]]["scale"], stock[r["idx"]]["pred16"])]
        if moved:
            raise ModeSoundError("%d stock record(s) moved (first idx %d)" % (len(moved), moved[0]))
        appended = rows[n_stock:]
        if len(appended) != len(sounds) + len(beds):
            raise ModeSoundError("%d appended record(s), %d sounds" % (len(appended), len(sounds) + len(beds)))
        fk_row = {r["findkey"]: r for r in rows if r.get("findkey")}
        targets = {sids[req][0]: ("request %d" % req, req, sounds[req]) for req in sounds}
        for sid, wav in beds.items():
            targets[sid] = ("bed sid %d" % sid, "sid %d" % sid, wav)
        # Every sid resolves exactly as on the stock bank, except the ones whose descriptor
        # named a carrier's (or a bed's) stock record: the re-point moves ALL of those (a sid no
        # request plays can name the same record - Premium 1.16's sid 2490 shares carrier 125's).
        stock_fk = {p["findkey"]: p["idx"] for p in stock if p.get("findkey")}
        grown_recs = set(request_records({r: sids[r] for r in sounds}, stock_sites, stock, key_mask).values())
        grown_recs |= set(sid_records(sorted(beds), stock_sites, stock, key_mask).values())
        movable = {s.sid for s in stock_sites
                   if stock_fk.get(_play_key(s.payload, s.sid, key_mask)) in grown_recs}
        before = {(s.sid, _play_key(s.payload, s.sid, key_mask)) for s in stock_sites}
        after = {(s.sid, _play_key(s.payload, s.sid, key_mask)) for s in built_sites}
        changed = {sid for sid, _k in before ^ after}
        if changed - movable:
            raise ModeSoundError("sids that named no carrier's record changed: %s" % sorted(changed - movable)[:10])
        log("%d sid(s) re-pointed (%s); every other sid resolves as on the stock bank"
            % (len(changed), ", ".join(map(str, sorted(changed)))))
        params = collapse_shadowed(rows)
        for p in params:
            p["grown"] = p.get("shadows") is not None
        emu.warm_slots_for_grown(params)
        result, bad = {}, []
        for sid, (what, key, wav) in targets.items():
            keys = {k for s2, k in after if s2 == sid}
            hit = [fk_row[k] for k in keys if k in fk_row]
            if len(hit) != 1 or hit[0] not in appended:
                raise ModeSoundError("%s (sid %d) does not resolve to one appended record" % (what, sid))
            row = hit[0]
            got = emu.decode(row)
            if got is None:
                raise ModeSoundError("%s: the appended record does not decode" % what)
            stereo = row.get("chan") == 2
            n = emitted_length(row["length"])
            left = np.asarray(got[0], np.float64)[:n]
            right = np.asarray(got[1], np.float64)[:n] if stereo and got[1] is not None else None
            dec = np.stack([left, right[:len(left)]], 1) if right is not None else left[:, None]
            coll = next((p for p in params if p["body_off"] == row["body_off"]), None)
            ref_wav = loop_wavs.get(coll["idx"] if coll else None, wav)
            want = E._load_wav(ref_wav, stereo, np)
            want = want if stereo else np.asarray(want)[:, None]
            m = min(len(dec), len(want))
            a, b = dec[:m].ravel(), np.asarray(want[:m], np.float64).ravel()
            corr = float(np.corrcoef(a, b)[0, 1]) if m > 16 and a.std() > 0 and b.std() > 0 else float("nan")
            result[key] = corr
            # the click detector over the record, and over two turns of it for a loop; a click
            # the source WAV has at the same place (a blast's own onset) is the sound, not ours
            loop = coll is not None and coll["idx"] in loop_wavs
            span = np.concatenate([dec, dec]) if loop else dec
            src = np.asarray(want[:m], np.float64)
            src = np.concatenate([src, src]) if loop else src
            own = {i for c in range(src.shape[1]) for i in clicks(src[:, c] / 32768.0)}
            found = sorted(i for i in {i for c in range(span.shape[1]) for i in clicks(span[:, c] / 32768.0)}
                           if not any(abs(i - j) <= 88 for j in own))
            if found:
                bad.append("%s: %d click(s) at %s s" % (what, len(found), ", ".join(
                    "%.3f" % (i / 44100.0) for i in found[:6])))
            # the lead-out block the machine plays past the emitted end must be silence, not scaffold
            tail = emu.decode(E._extended_row(row, E._APPENDED_TAIL))
            tpk = int(np.abs(np.asarray(tail[0], np.int64)[n:n + E._APPENDED_TAIL]).max()) if tail else -1
            if tpk > 330:
                bad.append("%s: the lead-out block past its end decodes to a %d-count burst" % (what, tpk))
            log("%s: appended idx %d, chan %s, %.2f s, corr %.5f, clicks %d%s, lead-out peak %d"
                % (what, row["idx"], row.get("chan"), row["length"] / 44100.0, corr, len(found),
                   " (two turns of the loop)" if loop else "", tpk))
        if bad:
            raise ModeSoundError("the click detector fires in the decoded records: " + "; ".join(bad))
    finally:
        emu.close()
    return result
