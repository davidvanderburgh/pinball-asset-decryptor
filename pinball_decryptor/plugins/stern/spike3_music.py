"""MUSIC MODES ON A SPIKE 3 CARD (PAD-1324).

Spike 2's music modes (:mod:`.sound_modes`, PAD-494) give a sound files for modes 2.. and put
MUSIC MODE in the operator menu; the runtime hands the game a mode's DESCRIPTOR at its resolver, the
sound's length declared there. A Spike 3 game plays a sound for as long as its own RECORD says (the
frames in ``image.bin``'s directory: a 20 s file under a 26 s carrier was heard looping past it,
PAD-1296), and its descriptors are 64-bit, so a Spike 3 card needs no descriptor of the game's:

1. each mode file is made into its slot's format (:func:`.sound_modes.convert`, its own loudness
   offset applied) and APPENDED to the game's ``image.bin`` as a record of its own, keyed beside
   the slot's record (:func:`.spike3_write.free_key`, the modes' own sounds' road, PAD-1296); one
   file in several modes of a slot at one loudness is one record. It plays at its own length, as
   a Spike 3 replacement does;
2. ``sounds.cfg`` beside the 64-bit runtime says where the setting's value lives (``setting``,
   the program's own address: the runtime adds the PIE's load address) and, for each slot and
   mode, ``mswap <m> <slot's key> <mode m's key>``: pad_mode_runtime.c swaps the key at the
   game's record lookup (``site sound_lookup``) while the setting says m;
3. MUSIC MODE goes on the operator menu's **Audio Content** page (Adjustments > Machine Settings),
   found by the page's NAME (:func:`.menu_settings.wide_category`), on a setting the game no
   longer uses: the descriptor, captions and help rewritten in place and the menu's page table
   grown (:func:`.menu_settings.grow_wide_program`, PAD-1321). The card's own program is never
   touched: the grown copy goes beside the runtime as ``game.pad``, and the modes' hook
   (:data:`.spike3_modes.HOOK_SCRIPT`) runs it in the stock one's place, so taking the modes off
   (or a Write without them) gives the card its own program back.

Emulator-proven on Star Wars ELG 1.10, Fallout LE 0.82 and Transformers LE 0.96 (the row on Audio Content, set in the menu;
mode 2's and mode 3's records played, mode 1 the game's own) - docs/plans/spike3_modes.md "Music modes
on Spike 3".

PAD-1358: a MUSIC BANK's song (``music_catNN_NNNN``, record NNNN of ``image-scNN.bin``; most of Fallout's
game music) takes mode files too. A bank has a descriptor table of its own naming its records by key, a
request plays its sound id ``NN << 16 | n``, and the game finds the record at the same lookup, so its mode
files are records appended to that bank, keyed beside the song with the bank's number (the params' low 12
bits, :data:`BANK_KEEP`) kept, and swapped by the same ``mswap`` lines - docs/plans/spike3_modes.md "Music
modes for bank songs".
"""
import dataclasses
import os
import struct

from . import sound_modes as SMo

#: the program the hook runs in the stock one's place (in pad/padmode)
PROGRAM_NAME = "game.pad"

#: ``<game>-<version>`` of the Spike 3 builds MUSIC MODE goes on: a shipped Spike 3 port naming
#: ``sound_lookup`` and a program whose menu takes the row (a DEPRECATED setting to take over and
#: a page table that grows). Each emulator-proven: the row read and set in the menu, mode 2's
#: record played (Transformers LE 0.96 by PAD-1359, once PAD-1293 gave it its port).
PROVEN = frozenset({"star_wars_elg-1.10", "fallout_le-0.82", "transformers_mtmte_le-0.96"})
#: the Spike 3 builds with a port whose menu has no setting the game stopped using
#: (:func:`.menu_settings.offered` refuses them: the siblings of ELG's DEPRECATED rows are live)
NO_ROW = frozenset({"pokemon_le-0.82", "star_wars_2025_le-0.96", "star_wars_2025_pro-0.84",
                    "walking_dead_remastered_le-0.92"})

#: PAD-1358: the param bits a music bank's new record keeps (the bank's number: ``0x82600008`` in image-sc02.bin)
BANK_KEEP = 0xFFF

NOT_PROVEN = "Music modes are not offered on %s yet: on Spike 3 they go on the games the app has proven them on."
NO_ROW_WORDS = ("Music modes are not offered on %s: its operator menu has no setting the game "
                "stopped using, so it cannot take MUSIC MODE.")
#: the parts of the Audio tab's sound pane that ride sounds.cfg and stay Spike 2's
LEFT_OUT = {
    "turns": "sounds in turn",
    "attract": "sounds for the flipper buttons in attract",
    "shots": "sounds on the shots of the game's modes",
    "jukebox": "the jukebox",
}


class Spike3MusicError(ValueError):
    """The project's music modes cannot go on this card; the message says why."""


def is_spike3(prof):
    return prof is not None and getattr(prof, "arch", "arm") == "a64"


def other_refusal(prof, what):
    """Why *what* (a part of the sound pane other than the music modes) is not offered on Spike 3 title
    *prof*, or ``""`` on a Spike 2 one: a Spike 3 card carries the music modes only."""
    if not is_spike3(prof):
        return ""
    return "%s %s not offered on %s: on Spike 3 cards only the music modes are." % (
        what[0].upper() + what[1:], "is" if what.startswith("the ") else "are", getattr(prof, "label", "this game"))


def title_refusal(prof, turns=False):
    """Why a Spike 3 title takes no music modes (*turns*: sounds in turn, Spike 2's only), or ``""``."""
    label = getattr(prof, "label", "this game")
    if turns:
        return other_refusal(prof, LEFT_OUT["turns"])
    key = SMo.title_key(prof)
    if key in NO_ROW:
        return NO_ROW_WORDS % label
    if key not in PROVEN:
        return NOT_PROVEN % label
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except OSError:
        return NOT_PROVEN % label
    if "sound_lookup" not in port["site"]:
        return NOT_PROVEN % label
    return ""


def wanted(project, real_card=True):
    """``(modes, prof)``: the project's music modes a Spike 3 build carries, or ``(None, None)``
    with no mode file. *modes* keeps the music modes only (the rest of the pane is said left out
    by :func:`left_out_lines`)."""
    modes = SMo.load(project)
    if not modes.count:
        return None, None
    if not SMo.enabled():
        return None, None
    prof = SMo.project_title(project, probe=True)
    return modes, prof


def left_out_lines(project):
    """The log's sentences for what the project's sound pane asked that a Spike 3 card leaves out."""
    modes = SMo.load(project)
    from . import jukebox as JB
    out = []
    for attr, words in (("turns", LEFT_OUT["turns"]), ("attract", LEFT_OUT["attract"]),
                        ("shots", LEFT_OUT["shots"])):
        if getattr(modes, attr):
            out.append("%s: left out of this build: a Spike 3 card carries the music modes only."
                       % (words[0].upper() + words[1:]))
    try:
        if JB.load(project).any:
            out.append("The jukebox: left out of this build: a Spike 3 card carries the music modes only.")
    except Exception:                                   # noqa: BLE001 - no jukebox record: nothing asked
        pass
    return out


def menu_program(game_raw, modes, extra=()):
    """``(setting, program bytes)``: *game_raw* (the card's 64-bit program) with MUSIC MODE on its
    Audio Content page, values 1..``modes.count`` named by the modes. Raises
    :class:`Spike3MusicError` when the program cannot take it. PAD-1325: *extra* are the card's
    other rows of ours (:func:`.spike3_menu.rows_wanted`: EDITION), grown in the same pass, because
    this copy is the program the modes' hook runs (one that lacks a row the card's own program has
    would leave EDITION out of the running game). One of them refused never stops MUSIC MODE."""
    from . import menu_settings as MS
    from . import spike3_menu
    try:
        grown, settings, refused = spike3_menu.grow(
            game_raw, [(MS.MUSIC_MODE, modes.count, modes.menu_names())] + list(extra))
    except MS.MenuSettingError as e:
        raise Spike3MusicError("MUSIC MODE cannot be added to this game's operator menu: %s" % e) from None
    except ValueError as e:
        raise Spike3MusicError("this game's settings could not be read (%s)" % e) from None
    setting = next((s for s in settings if s.key == MS.MUSIC_MODE), None)
    if setting is None:
        raise Spike3MusicError("MUSIC MODE cannot be added to this game's operator menu: %s"
                               % refused.get(MS.MUSIC_MODE, "unknown"))
    return setting, grown


def _gain(wav, db):
    """*wav* (16-bit PCM) moved by *db* decibels, as a copy beside it, kept while it is there."""
    import wave
    import numpy as np
    out = "%s.db%+.1f.wav" % (os.path.splitext(wav)[0], float(db))
    if os.path.isfile(out) and os.path.getsize(out) > 44:
        return out
    with wave.open(wav, "rb") as r:
        params = r.getparams()
        a = np.frombuffer(r.readframes(r.getnframes()), "<i2").astype(np.float64)
    if params.sampwidth != 2:
        return wav
    a = np.clip(np.round(a * 10 ** (float(db) / 20.0)), -32768, 32767).astype("<i2")
    tmp = out + ".part"
    with wave.open(tmp, "wb") as w:
        w.setparams(params)
        w.writeframes(a.tobytes())
    os.replace(tmp, out)
    return out


def records(project, modes, img, log=None, taken=(), first_idx=None, bank=None, like=None):
    """``(mswaps, news, used)`` for *modes*' files over the container view *img*
    (:class:`.spike3_sound.ImageSound`): *mswaps* ``[(mode, slot key, record key)]``, *news* the
    :class:`.spike3_write.NewRecord` s to append (after *first_idx*, default the container's
    count), *used* the record lines' entries (:func:`.sound_modes.card_record`). *taken*: record
    keys other new records of the build already have. PAD-1358: *bank* NN when *img* is the music
    bank ``image-scNN.bin`` and the slots are its songs (``music_catNN_NNNN``); *like* the records
    of every bank, whose params say which bits a new key may vary (the bank's number stays)."""
    from . import spike3_write as W
    log = log or (lambda *a, **k: None)
    taken = [tuple(t) for t in taken]
    first = img.count if first_idx is None else int(first_idx)
    mswaps, news, used, made, p2s = [], [], [], {}, []
    for rel in sorted(modes.slots):
        if bank is None:
            idx = SMo.slot_idx(rel)
        else:
            b = SMo.bank_slot(rel)
            idx = b[1] if b is not None and b[0] == int(bank) else None
        for m, src in sorted(modes.slots[rel].items()):
            if idx is None:
                log("Music modes: %s is left out: %s" % (SMo.what(rel, m), SMo.NOT_SOUND), "warning")
                continue
            if idx >= img.count:
                log("Music modes: %s is left out: this card's %s has only %d sounds."
                    % (SMo.what(rel, m), "sound container" if bank is None
                       else "music bank image-sc%02d.bin" % int(bank), img.count), "warning")
                continue
            rec = img.records[idx]
            try:
                wav = SMo.convert(project, rel, m, src, log)
            except SMo.SoundModeError as e:
                log("Music modes: %s is left out: %s." % (SMo.what(rel, m), str(e).rstrip(".")), "warning")
                continue
            db = float(modes.level(rel, m) or 0.0)
            if db:
                wav = _gain(wav, db)
            k = (idx, os.path.abspath(wav))
            if k not in made:
                if bank is None:
                    flags, param = W.free_key(img.records, rec.flags_lo, rec.param, taken)
                else:
                    flags, param = W.free_key(img.records, rec.flags_lo, rec.param, taken,
                                              like=like or img.records, keep=BANK_KEEP)
                taken.append((flags, param))
                p2 = W.free_param2(img.records, ("%s|%d|%s" % (rel, m, wav)).encode(), p2s)
                p2s.append(p2)
                nr = W.NewRecord(wav, rec.channels, flags, param, p2)
                made[k] = (nr, first + len(news))
                news.append(nr)
            nr, host = made[k]
            mswaps.append((m, struct.pack("<II", rec.flags_lo, rec.param), nr.key))
            u = {"rel": rel, "slot": idx, "mode": m, "host": host, "db": db, "lines": 1}
            if bank is not None:                        # the record line says ``<bank>:<record>``
                u.update(bank=int(bank), bank_idx=host)
            used.append(u)
    return mswaps, news, used


def cfg_text(setting, modes, mswaps, used, only):
    """``sounds.cfg`` for a Spike 3 card: the setting, an ``mswap`` line per slot and mode, and the
    record lines an extract of the card reads the modes back from."""
    text = SMo.cfg_text(setting.live, modes.count, [], only, record=SMo.card_record(modes, used))
    lines = text.rstrip("\n").split("\n")
    at = next((i + 1 for i, l in enumerate(lines) if l.startswith("setting\t")), len(lines))
    lines[at:at] = ["mswap\t%d\t%s\t%s" % (int(m), bytes(s).hex(), bytes(o).hex()) for m, s, o in mswaps]
    return "\n".join(lines) + "\n"


class Spike3Music:
    """What a Spike 3 Write puts on the card for the project's music modes."""

    def __init__(self, setting, program, cfg, news, count, n_files):
        self.setting = setting          # menu_settings.MenuSetting
        self.program = program          # the grown game program (game.pad)
        self.cfg = cfg                  # sounds.cfg's text
        self.news = news                # [spike3_write.NewRecord] for the game's image.bin
        self.count = count              # modes offered
        self.n_files = n_files          # mode files that went on


def plan(project, modes, prof, reader, game_raw, log=None, only=False, adds=None):
    """The :class:`Spike3Music` of *modes* for the card behind the games volume *reader* (its
    program *game_raw*), or raises :class:`Spike3MusicError` with the reason they are left out.
    *adds*: the build's other new records (``{card path: [NewRecord]}``, the modes' own sounds),
    appended before these: their keys are not taken again. *only*: the card carries no modes."""
    from . import spike3_write as W
    log = log or (lambda *a, **k: None)
    why = SMo.NO_TITLE if prof is None else title_refusal(prof)
    if why:
        raise Spike3MusicError(why)
    # each slot's own container: the image.bin whose project folder holds its idx file (the game's own, ``audio``,
    # or the system's menu sounds, ``audio_spike_menu``), or PAD-1358 the music bank image-scNN.bin beside it whose
    # song it is (``music_catNN_NNNN``: Fallout's game music is mostly in its 137 bank songs)
    conts = {(folder, stem): (cp, node) for cp, node, folder, stem in W.project_sound_dirs(reader)}
    if not any(stem is None for _f, stem in conts):
        raise Spike3MusicError("this card has no sound container")
    from . import spike3_menu
    setting, program = menu_program(game_raw, modes, spike3_menu.rows_wanted(project))
    groups = {}
    for rel in modes.slots:
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
        b = SMo.bank_slot(rel) if SMo.slot_idx(rel) is None else None
        groups.setdefault((folder, None if b is None else "music_cat%02d" % b[0]), []).append(rel)
    likes = {}

    def bank_like(folder):
        """Every music bank's records of *folder*: the bits their keys vary."""
        if folder not in likes:
            likes[folder] = [r for (f, stem), (_cp, nd) in conts.items() if f == folder and stem
                             for r in W.read_container(reader, nd)[1].records]
        return likes[folder]

    mswaps, news, used = [], {}, []
    for (folder, stem), rels in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        sub = dataclasses.replace(modes, slots={r: modes.slots[r] for r in rels})
        if (folder, stem) not in conts:
            where = ("music bank image-sc%s.bin" % stem[len("music_cat"):]) if stem else (folder or "it")
            for rel in rels:
                log("Music modes: %s is left out: this card has no sound container for %s."
                    % (SMo.what(rel, 2), where), "warning")
            continue
        card_path, node = conts[(folder, stem)]
        _hdr, img = W.read_container(reader, node)
        before = list((adds or {}).get(card_path) or ())
        bank = int(stem[len("music_cat"):]) if stem else None
        ms, nw, us = records(project, sub, img, log, taken=[(r.flags_lo, r.param) for r in before],
                             first_idx=img.count + len(before), bank=bank,
                             like=bank_like(folder) if stem else None)
        mswaps += ms
        used += us
        if nw:
            news[card_path] = nw
    if not mswaps:
        raise Spike3MusicError("none of the modes' files could be made into its sound")
    return Spike3Music(setting, program, cfg_text(setting, modes, mswaps, used, only),
                       news, modes.count, len(mswaps))
