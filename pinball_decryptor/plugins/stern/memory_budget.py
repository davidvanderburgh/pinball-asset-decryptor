"""How much of the machine's memory a card's sounds will take, known before a Write (PAD-1005).

An owner putting three to six songs at random on each of Godzilla's seven multiball tracks only
found out at Write time that a song was too long ("this sound's bank can be at most 0 MB here"),
and asked what the limit was; David: "for limits like this we need to visualize it to the user
somehow. Knowing ahead of time is very meaningful."

The machine holds ``image.bin`` in memory for good and, beside it, every sound bank it is playing a
sound from, up to one for each of its sound channels; together they must stay within
:data:`.spike2.soundbank.MAPPED_MAX` (the build's own rule, ``engine._plan_sound_banks``). This
estimates the same sum off the project alone, no card needed:

* ``image.bin`` as shipped is the game's sounds' PCM, one record each: the project's own extracted
  sounds add up to it (Godzilla Pro 1.16: 1,647.7 MB of WAV data, 1,650 MB ``image.bin``);
* a build with music modes' files puts every sound a bank can hold into banks (PAD-749/995): the
  music modes' files, the files in turn and the user's longer replacements; the game's own
  recordings of the replaced ones come out of ``image.bin`` (PAD-880). A jukebox song stays in
  ``image.bin`` (PAD-685);
* a sound past a :data:`.spike2.soundbank.BANK_SLICE` bank (or the eighth of the room beside
  ``image.bin``) gets a bank of its own; the rest share banks of that size, the biggest first;
* the :data:`.spike2.soundbank.SOUND_CHANNELS` biggest banks are what can be held at once;
* a game that ships sound banks of its own (Deadpool, Metallica, D&D: ``music_catNN_*`` in its
  extract, one bank each, :func:`...core.card_paths.audio_container`) plays from them beside the
  app's, and its biggest takes one of those places (:func:`.spike2.soundbank.room_beside`).

It is an estimate: the build's own plan (sounds that cannot go into a bank, a song in parts) can
differ a little, and the Write still checks the real numbers.
"""
from __future__ import annotations

from .spike2 import soundbank as SB

#: Card samples a second (every Spike 2 sound plays at 44.1 kHz).
RATE = 44100
#: Bytes of a minute of stereo sound in a bank or in image.bin (16-bit PCM).
STEREO_BYTES_PER_MIN = 4 * RATE * 60


def pcm_bytes(seconds, channels):
    """A sound's bytes on the card: 16-bit samples at 44.1 kHz, *channels* of them."""
    return int(round(max(0.0, float(seconds or 0.0)) * RATE)) * max(1, int(channels or 1)) * 2


def estimate(stock, banked=(), credit=0, grow=0, vendor=()):
    """The memory the game will hold at most: *stock* ``image.bin``'s bytes as shipped, *banked*
    ``[(name, bytes)]`` the sounds that go into the app's sound banks, *credit* the bytes of the
    game's own recordings those replace (they come out of ``image.bin``), *grow* what ``image.bin``
    gains (the sounds that stay there longer than the game's), *vendor* the sizes of the game's own
    sound banks. Returns a dict: ``image`` (``image.bin`` held), ``banks`` (the app's banks'
    bytes, biggest first), ``chans`` (the places they share), ``live`` (the biggest *chans* of
    them together), ``game`` (the game's own biggest bank, 0 for none), ``game_n`` (how many it
    ships), ``total`` (``image + live + game``), ``cap`` (:data:`.spike2.soundbank.MAPPED_MAX`),
    ``left`` (``cap - total``, below 0 when over), ``longest`` (``(name, bytes)`` of the biggest
    sound in one of the app's banks, or None)."""
    image = max(0, int(stock) - int(credit) + int(grow))
    game, room, chans = SB.room_beside(vendor)
    units = sorted(((str(n), int(b)) for n, b in banked if int(b) > 0), key=lambda u: -u[1])
    limit = min(SB.BANK_SLICE, max(0, room - image) // chans)
    banks, shared = [], []
    for _n, b in units:
        if b > limit:
            banks.append(b)
            continue
        for i, used in enumerate(shared):          # the biggest first, into the first with room
            if used + b <= limit:
                shared[i] += b
                break
        else:
            shared.append(b)
    banks = sorted(banks + shared, reverse=True)
    live = sum(banks[:chans])
    total = image + live + game
    return {"image": image, "banks": banks, "chans": chans, "live": live, "game": game,
            "game_n": len([b for b in vendor or () if int(b) > 0]), "total": total,
            "cap": SB.MAPPED_MAX, "left": SB.MAPPED_MAX - total,
            "longest": units[0] if units else None}


def minutes(nbytes, channels=2):
    """*nbytes* of sound as minutes (stereo unless *channels* says otherwise)."""
    return float(nbytes) / (STEREO_BYTES_PER_MIN * max(1, int(channels)) / 2.0)


def _mb(n):
    return "{:,}".format(int(round(n / 1e6)))


def words(est):
    """``(chip text, kind, tooltip head, tooltip lines)`` for the Audio tab (kind ``""``,
    ``"warn"`` from 90 % of the room, ``"err"`` past it). The lines are the rich tooltip's
    (``tip({head, lines})``): a bar of what each part takes, ``[key, value]`` rows,
    ``{"sec"}`` headings and ``{"li"}`` bullets."""
    total, cap = est["total"], est["cap"]
    kind = "err" if total > cap else "warn" if total >= 0.9 * cap else ""
    text = "Machine memory: about %s of %s MB" % (_mb(total), _mb(cap))
    over = max(0, total - cap)
    parts = [{"v": est["image"], "label": "Main sound file", "kind": "img"},
             {"v": est["live"], "label": "This card's sound banks", "kind": "ours"}]
    if est["game"]:
        parts.append({"v": est["game"], "label": "The game's own bank", "kind": "game"})
    if not over:
        parts.append({"v": cap - total, "label": "Room left", "kind": "free"})
    n, chans = len(est["banks"]), est["chans"]
    lines = [
        {"bar": parts, "of": cap},
        ["In use", "about %s of %s MB%s" % (_mb(total), _mb(cap), " (over by %s MB)" % _mb(over)
                                            if over else "")],
        {"sec": "What counts"},
        ["Main sound file", "%s MB, held all the time (image.bin)" % _mb(est["image"])],
        ["This card's banks", ("%s MB: the %d biggest of %d" % (_mb(est["live"]), chans, n)
                               if n > chans else "%s MB: %d bank%s" % (_mb(est["live"]), n,
                                                                       "" if n == 1 else "s"))
         if n else "none"],
    ]
    if est["game"]:
        lines.append(["The game's own banks", "%s MB: the biggest of its %d" % (
            _mb(est["game"]), est["game_n"])])
    if est["longest"]:
        name, b = est["longest"]
        lines.append(["Longest song", "%s, %s MB (%.1f min)" % (name, _mb(b), minutes(b))])
    if est.get("unplayed"):
        # (the Audio tab's: a slot no sound request plays keeps its files in image.bin)
        lines.append({"sec": "Never played by the game"})
        for name, k in est["unplayed"]:
            lines.append({"li": "%s: no sound request plays it, so its %d song%s stay in the "
                                "main sound file and are never heard." % (
                                    name, k, "" if k == 1 else "s")})
    lines.append({"sec": "Over the limit" if over else "Room left"})
    if over:
        lines += [{"li": "About %s MB too much, about %.1f minutes of stereo." % (
                      _mb(over), minutes(over))},
                  {"li": "Shorten the longest songs: they count the most."},
                  {"li": "Write refuses the card until it fits."}]
    else:
        lines += [{"li": "About %s MB, about %.1f minutes of stereo, for the longest songs "
                         "to share." % (_mb(cap - total), minutes(cap - total))},
                  {"li": "Only the %d biggest banks count: a shorter song costs nothing more "
                         "until it is one of them." % chans}]
    lines += [{"sec": "How it works"},
              {"li": "The machine holds the main sound file in memory all the time."},
              {"li": "Beside it, every sound bank it is playing a sound from, up to %d at once "
                     "(one for each sound channel)." % SB.SOUND_CHANNELS}]
    if est["game"]:
        lines.append({"li": "This game ships sound banks of its own: its biggest takes one of "
                            "those places."})
    lines += [{"li": "This is the machine's memory, not the card's space: removing videos "
                     "does not change it."},
              {"li": "An estimate from this project: Write checks the real numbers."}]
    return text, kind, "Machine memory", lines
