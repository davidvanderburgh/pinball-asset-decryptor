"""PAD-1092: the limits an owner adding lots of audio asks about, shown in the app.

The tester asked how long a song can be, how much fits, and how many files in turn or at random a
music mode's sound takes; David asked for the answer "somewhere in the app". The Machine memory
tooltip gains a "Limits" section built off the build's own numbers, and the Replace Audio tips gain
"How much audio fits". The tips are static words, so these tests hold them to the same numbers.
"""
import re

from pinball_decryptor.plugins.stern import memory_budget as MB
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from pinball_decryptor.webui.help_content import HELP_CONTENT


def _li(lines):
    return [x["li"] for x in lines if isinstance(x, dict) and "li" in x]


def _tips():
    body = dict(HELP_CONTENT["Replace Audio"])["How much audio fits"]
    return "\n".join(b if isinstance(b, str) else b.get("note", "") for b in body)


def test_the_limits_come_off_the_builds_own_numbers():
    lines = MB.limit_lines()
    assert lines[0] == {"sec": "Limits"}
    li = " ".join(_li(lines))
    assert int(MB.minutes(SB.BANK_MAX_SEEN)) == 20
    assert "up to about 20 minutes of stereo" in li
    assert "up to %d, the card's own sounds as mode 1" % SMo.MAX_MODES in li
    assert "up to %d files a sound" % SMo.TURN_MAX in li
    assert "%d more for each music mode's file" % (SMo.TURN_MAX - 1) in li
    assert "Put the longest first" in li


def test_the_memory_tooltip_shows_them_between_the_room_and_how_it_works():
    est = MB.estimate(1_650_000_000, banked=[("song.wav", 60_000_000)])
    _text, _kind, head, lines = MB.words(est)
    secs = [x["sec"] for x in lines if isinstance(x, dict) and "sec" in x]
    assert head == "Machine memory"
    assert secs.index("Room left") < secs.index("Limits") < secs.index("How it works")
    # over the limit too
    _t, kind, _h, lines = MB.words(MB.estimate(2_100_000_000, banked=[("a", 200_000_000)]))
    assert kind == "err" and {"sec": "Limits"} in lines


def test_the_tips_say_the_same_numbers():
    t = _tips()
    assert "| Music modes | %d," % SMo.MAX_MODES in t
    assert "| %d files a sound, its own included |" % SMo.TURN_MAX in t
    assert "| %d more for each mode's file |" % (SMo.TURN_MAX - 1) in t
    assert "about %d minutes of stereo |" % int(MB.minutes(SB.BANK_MAX_SEEN)) in t
    assert "up to %d at once" % SB.SOUND_CHANNELS in t
    assert "The %d longest songs" % SB.SOUND_CHANNELS in t
    assert "about {:,} MB".format(int(round(SB.MAPPED_MAX / 1e6, -1))) in t
    # songs that share a bank: a BANK_SLICE of stereo, rounded
    assert "under about %d minutes share banks" % round(MB.minutes(SB.BANK_SLICE)) in t
    # Godzilla 1.16's main file (1,650 MB) leaves about 50 minutes beside it
    assert "about %d minutes of stereo beside" % (
        round(MB.minutes(SB.MAPPED_MAX - 1_650_000_000), -1)) in t


def test_the_tips_render():
    from pinball_decryptor.webui import tips_render
    body = dict(HELP_CONTENT["Replace Audio"])["How much audio fits"]
    blocks = tips_render.render(body)
    kinds = [b["t"] for b in blocks]
    assert "table" in kinds and "note" in kinds and kinds.count("h") == 2
    # a cell starting "no" draws as a red no-chip: no limit reads as "unlimited", not a cross
    table = next(b for b in blocks if b["t"] == "table")
    assert not any(c.get("chip") for row in table["rows"] for c in row)
    text = tips_render.plain(blocks)
    assert "Music modes" in text and not re.search(r"\|---|###", text)
