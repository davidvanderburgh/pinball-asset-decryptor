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
* the :data:`.spike2.soundbank.SOUND_CHANNELS` biggest banks are what can be held at once.

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


def estimate(stock, banked=(), credit=0, grow=0):
    """The memory the game will hold at most: *stock* ``image.bin``'s bytes as shipped, *banked*
    ``[(name, bytes)]`` the sounds that go into sound banks, *credit* the bytes of the game's own
    recordings those replace (they come out of ``image.bin``), *grow* what ``image.bin`` gains
    (the sounds that stay there longer than the game's). Returns a dict: ``image`` (``image.bin``
    held), ``banks`` (every bank's bytes, biggest first), ``live`` (the
    :data:`.spike2.soundbank.SOUND_CHANNELS` biggest together), ``total``, ``cap``
    (:data:`.spike2.soundbank.MAPPED_MAX`), ``left`` (``cap - total``, below 0 when over),
    ``longest`` (``(name, bytes)`` of the biggest sound in a bank, or None)."""
    image = max(0, int(stock) - int(credit) + int(grow))
    units = sorted(((str(n), int(b)) for n, b in banked if int(b) > 0), key=lambda u: -u[1])
    limit = min(SB.BANK_SLICE, max(0, SB.MAPPED_MAX - image) // SB.SOUND_CHANNELS)
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
    live = sum(banks[:SB.SOUND_CHANNELS])
    total = image + live
    return {"image": image, "banks": banks, "live": live, "total": total, "cap": SB.MAPPED_MAX,
            "left": SB.MAPPED_MAX - total, "longest": units[0] if units else None}


def minutes(nbytes, channels=2):
    """*nbytes* of sound as minutes (stereo unless *channels* says otherwise)."""
    return float(nbytes) / (STEREO_BYTES_PER_MIN * max(1, int(channels)) / 2.0)


def words(est):
    """``(chip text, kind, tooltip head, tooltip lines)`` for the Audio tab (kind ``""``,
    ``"warn"`` from 90 % of the room, ``"err"`` past it)."""
    mb = lambda n: "{:,}".format(int(round(n / 1e6)))   # noqa: E731
    total, cap = est["total"], est["cap"]
    kind = "err" if total > cap else "warn" if total >= 0.9 * cap else ""
    text = "Machine memory: about %s of %s MB" % (mb(total), mb(cap))
    n = min(len(est["banks"]), SB.SOUND_CHANNELS)
    lines = [
        "The machine holds the card's main sound file (image.bin) in memory all the time, and "
        "beside it every sound bank it is playing a sound from, up to %d at once. Together they "
        "have to fit in %s MB, or Write refuses the card." % (SB.SOUND_CHANNELS, mb(cap)),
        "Main sound file: about %s MB." % mb(est["image"]),
        "Sound banks: %d, the %s together about %s MB." % (
            len(est["banks"]), "%d biggest" % n if len(est["banks"]) > n else
            "all of them" if n > 1 else "one", mb(est["live"])) if est["banks"] else
        "Sound banks: none.",
    ]
    if est["longest"]:
        name, b = est["longest"]
        lines.append("Longest sound in a bank: %s, about %s MB (%.1f minutes of stereo)."
                     % (name, mb(b), minutes(b)))
    if total > cap:
        lines.append("Over by about %s MB (about %.1f minutes of stereo): shorten the longest "
                     "songs, they count the most." % (mb(-est["left"]), minutes(-est["left"])))
    else:
        lines.append("Room left: about %s MB, about %.1f minutes of stereo across the longest "
                     "songs." % (mb(est["left"]), minutes(est["left"])))
    lines.append("This is the machine's memory, not the card's space. An estimate: Write "
                 "checks the real numbers.")
    return text, kind, "Machine memory", lines
