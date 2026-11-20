"""PAD-1475: the light shows each of the game's modes starts, read off the game program, on the mode's How it works."""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import clip_modes as CM
from pinball_decryptor.plugins.stern import clip_shows as SH
from pinball_decryptor.plugins.stern import stock_modes as SM
from pinball_decryptor.webui import modes_how as MH

TEXT = 0x10000


class _Prog:
    """A program of a few words: ``word``, ``in_text`` and the bytes ``locate_starter`` searches."""

    def __init__(self, words):
        self.words = dict(words)
        self.tlo = TEXT
        self.thi = TEXT + 0x1000
        top = max(self.words) + 4
        self.b = b"".join(self.words.get(va, 0).to_bytes(4, "little") for va in range(TEXT, top, 4))

    def word(self, va):
        return self.words.get(va, 0)

    def in_text(self, va):
        return self.tlo <= va < self.thi

    def va2off(self, va):
        return va - TEXT


def _movw(rd, v):
    return 0xE3000000 | ((v >> 12) & 0xF) << 16 | rd << 12 | (v & 0xFFF)


def _movt(rd, v):
    return 0xE3400000 | ((v >> 12) & 0xF) << 16 | rd << 12 | (v & 0xFFF)


def _b(at, target):
    return 0xEA000000 | (((target - at - 8) >> 2) & 0xFFFFFF)


COUNT_AT, TABLE = 0x5F834C, 0x7C46B8
#: James Bond LE 1.06's show starter, as it reads its count and its table (0x311928)
STARTER = [0xE92D47F0, 0xE2508000, 0x0A000054, _movw(3, COUNT_AT & 0xFFFF), _movt(3, COUNT_AT >> 16), 0xE5933000,
           0xE1580003, 0x2A00004F, 0xE3069DF8, 0xE3409082, 0xE5994000, 0xE3540000, 0x0A00002F, 0xE0885088,
           _movw(6, TABLE & 0xFFFF), 0xE3067DFC, _movt(6, TABLE >> 16), 0xE3407082, 0xE0865105]


def _starter_prog(extra=()):
    words = {TEXT + 4 * i: w for i, w in enumerate(STARTER)}
    words[COUNT_AT] = 538
    words.update(extra)
    return _Prog(words)


def test_the_starter_gives_its_count_and_its_table():
    prog = _starter_prog()
    assert SH.starter_table(prog, TEXT) == (538, TABLE)
    # found by its shape when no port places it
    assert SH.locate_starter(prog) == TEXT
    # a function with the same first words but no table is not it
    assert SH.starter_table(_Prog({TEXT: STARTER[0], TEXT + 4: STARTER[1]}), TEXT) == (0, 0)


def test_a_show_is_its_rows_body_through_the_jump():
    jump, body = TEXT + 0x200, TEXT + 0x100
    prog = _starter_prog({TABLE + 12 * 448: jump, jump: _b(jump, body), TABLE + 12 * 449: body, body: 0xE92D4FF0})
    assert SH.body_of(prog, TABLE, 448) == body
    assert SH.body_of(prog, TABLE, 449) == body
    assert SH.body_of(prog, TABLE, 5) == 0              # an empty row


def test_the_port_names_shows_by_body_and_the_flash_by_its_shared_words():
    body, flash = TEXT + 0x100, TEXT + 0x300
    prog = _Prog({body: 0xE92D4FF0, body + 4: 0xE24DD01C, flash: 0xE92D4010, flash + 4: 0xE1A04000})
    port = """
site show_7 0x%x 0xe92d4ff0 0xe24dd01c
text show_name_7 Wide slow fade
site show_8 0x20000 0xe92d4ff0 0xe24dd01c
text show_name_8 Not this build's
site show_13 0x%x 0xe92d4010 0xe1a04000
value show_call_13 1
text show_name_13 Lit shot flash white
site show_14 0x%x 0xe92d4010 0xe1a04000
value show_call_14 2
text show_name_14 Lit shot flash dark orange
""" % (body, flash, flash)
    lines = [ln.split() for ln in port.strip().splitlines()]
    bodies, sites = SH.port_names(prog, lines)
    assert bodies == {body: "Wide slow fade"}
    assert sites == {flash: ("Lit shot flash", ["Lit shot flash white", "Lit shot flash dark orange"])}


def test_a_reading_keeps_each_modes_shows_in_its_cache():
    sh = SH.ShowReading(origin="port", count=538, modes={"ROCKET_MULTIBALL": [[206, 16, 1], [448, 32, 2]]},
                        names={"448": "Wide slow fade"}, pickable={"448": ["Wide slow fade"]})
    clips = CM.CardClips(card="c", shows=sh.to_json())
    back = CM.CardClips.from_json(json.loads(json.dumps(clips.to_json())))
    assert back.show_reading.modes == sh.modes and back.show_reading.names == sh.names
    # a card read before PAD-1475 has none (and its cache key changed with the shows' revision)
    assert CM.CardClips.from_json({}).show_reading.modes == {}


BOND_LE = r"C:\tmp\PAD-1446\gr\james_bond_le-1_06_0.elf"


@pytest.mark.skipif(not os.path.isfile(BOND_LE), reason="James Bond LE 1.06's game program is not on this PC")
def test_bond_le_modes_light_shows():
    ctx = {}
    with open(BOND_LE, "rb") as f:
        CM.analyse(f.read(), set(), ctx=ctx)
    r = SH.analyse(game="james_bond_le", version="1.06", ctx=ctx)
    assert (r.origin, r.starter, r.count, r.table) == ("port", 0x311928, 538, 0x7C46B8)
    assert SH.locate_starter(ctx["prog"]) == 0x311928
    shows = {m: [n for n, _a, _c in rows] for m, rows in r.modes.items()}
    assert len(shows) == 40
    assert shows["ASTON_MARTIN_MULTIBALL"] == [382, 440, 385, 448, 386, 387, 388, 523, 390, 391]
    assert shows["DR_NO_MULTIBALL"] == [235, 440, 448, 242, 244, 239, 240, 241, 243]
    assert r.names["385"] == "Wide fast orange and purple strobe" and r.names["448"] == "Wide slow fade"
    # show 464 (PAD-642: body 0x139448) is the lit-shot flash; a mini-wizard's own through the wrappers
    assert r.names["464"] == "Lit shot flash" and 464 in shows["DIAMOND_DEATH_RAY"]
    assert len(r.pickable["464"]) == 10


TABLE_TXT = """
build james_bond_le 1.06 sha1 0000000000000000000000000000000000000000
mode 7 ASTON_MARTIN_MULTIBALL obj 0x7a18a8 vtable 0x629b98 title_msg 3235
mode 8 BUST_OUT obj 0x7a18b8 vtable 0x629ba8 title_msg 3236
"""


class _Tab(MH.HowItWorksMixin):
    def __init__(self, clips):
        self._init_how()
        self._how = clips
        self._how_key = ("p", "card", 1, 1)

    def project(self):
        return ""


def test_the_page_lists_the_modes_light_shows():
    b = SM.parse(TABLE_TXT)[0]
    sh = SH.ShowReading(origin="port", count=538,
                        modes={"ASTON_MARTIN_MULTIBALL": [[382, 16, 1], [448, 32, 3], [464, 48, 1]]},
                        names={"448": "Wide slow fade", "464": "Lit shot flash"},
                        pickable={"448": ["Wide slow fade"], "464": ["Lit shot flash white", "Lit shot flash red"]})
    reading = CM.Reading(labels={"ASTON_MARTIN_MULTIBALL": "Aston Martin Multiball"})
    tab = _Tab(CM.CardClips(card="card", reading=reading, shows=sh.to_json()))
    how = tab._how_for(b, 7)
    first, fade, flash = how["shows"]
    assert (first["text"], first["named"]) == ("Light show 382", False)
    assert first["tip"]["lines"] == ["The game's light show 382",          # PAD-1476: pickable by its number
                                     'A mode of yours and the co-op intro can play it too: "Light show 382 (Aston '
                                     'Martin Multiball)" on its Lights page']
    assert (fade["text"], fade["num"], fade["named"]) == ("Wide slow fade", 448, True)
    assert fade["tip"]["lines"] == ["The game's light show 448",
                                    'A mode of yours can play it too: "Wide slow fade" on its Lights page',
                                    "Started in 3 places of its code"]
    assert flash["tip"]["lines"][1] == ('A mode of yours can play it too, in one of 2 colors: "Lit shot flash white" '
                                        "and the rest on its Lights page")
    assert how["shows_note"] == MH.SHOWS_NOTE
    # a mode with none: an empty list, the note still
    assert tab._how_for(b, 8)["shows"] == []


def test_the_page_draws_the_light_shows():
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js",
                           "tabs", "modes.js"), encoding="utf-8").read()
    assert "Light shows it plays" in js and "h.shows_note" in js
