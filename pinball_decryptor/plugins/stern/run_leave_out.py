"""What an Emulate run may leave out of its override set (PAD-1197).

DragonRR: "I need to have a facility to turn off any items individually which can
slow the speed at which the emulator is able to run up especially after the first
time. I think one of the problems would be the extra audio tracks/variants and
possibly video variants?"  Any edit (one picture moved on the Scenes tab) builds
the set again, and the set carries everything the project has: the replaced
sounds and the music modes' files make the sound bank (image.bin, gigabytes) to
be rebuilt and staged, the random clips are converted and put in the video bank,
the modes are compiled.  Testing one picture needs none of it.

The Emulate tab offers a tick per kind under "Apply my replaced assets"; a ticked
kind is left out of THIS run's set only (a card build always carries all of it),
said in the log, and recorded in the set's manifest (``left_out``) so flipping a
tick builds the set again (:func:`webui.emulate_core.overrides_reason`).  Kinds
are left out after the project is read (:func:`engine._compute_patches_inner`)
and before the Replace tabs' picks are converted (``App.stage_pending_replacements``),
so a left-out video is not converted at Start either: it stays assigned and is
converted at the first Start or build that carries videos.
"""

import os

#: ``(key, label, tip)`` in the order the tab shows them.
KINDS = (
    ("sounds", "Replaced sounds",
     "Your replaced sounds and songs (the Audio tab). Left out, the game plays its own, and the "
     "card's sound bank is not rebuilt for this run: with many or long sounds, that is most "
     "of the wait."),
    ("music_modes", "Music modes and extra sounds",
     "Music modes, sounds played in turn or at random, the jukebox and the other extra sound "
     "files the Audio tab adds. Left out, each sound plays its own one file (its replacement "
     "or the stock one) and MUSIC MODE is not in the menu."),
    ("videos", "Replaced videos",
     "Your replaced videos (the Video tab). Left out, the game shows its own, and a video you "
     "assigned is not converted at Start: it is converted the next time videos are included."),
    ("random_clips", "Random clips",
     "Clips set to play one of several at random. Left out, each plays its one clip."),
    ("pictures", "Replaced pictures",
     "Your replaced pictures and fonts (the Images tab). Left out, the game shows its own, and "
     "a picture you assigned is not converted at Start."),
    ("modes", "Modes",
     "The modes you made on the Modes tab. Left out, the game plays as it was made."),
)
KEYS = tuple(k for k, _l, _t in KINDS)
LABELS = {k: l for k, l, _t in KINDS}


def clean(kinds):
    """*kinds* (any iterable of keys, or a comma list) as a sorted tuple of known keys."""
    if isinstance(kinds, str):
        kinds = kinds.split(",")
    return tuple(sorted({str(k).strip() for k in kinds or ()} & set(KEYS)))


def said(kinds):
    """``"replaced sounds and music modes and extra sounds"`` for the log."""
    names = [LABELS[k].lower() for k in KEYS if k in set(clean(kinds))]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def offered(project):
    """The keys worth a tick for *project*: the three replaced kinds always (whether a
    sound was replaced is only known by checksumming every one), the rest when the
    project has any."""
    out = ["sounds", "videos", "pictures"]
    if not project or not os.path.isdir(project):
        return [k for k in KEYS if k in out]
    try:
        from . import jukebox, sound_modes
        if sound_modes.load(project).any or jukebox.load(project).any:
            out.append("music_modes")
    except Exception:                                   # noqa: BLE001
        pass
    try:
        from . import clip_variants
        if clip_variants.load(project):
            out.append("random_clips")
    except Exception:                                   # noqa: BLE001
        pass
    try:
        from . import mode_write
        if mode_write.held_modes(project):
            out.append("modes")
    except Exception:                                   # noqa: BLE001
        pass
    return [k for k in KEYS if k in out]
