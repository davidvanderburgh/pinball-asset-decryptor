"""PAD-1359: music modes on Transformers LE 0.96 (Spike 3), and its sound request map.

Emulator-proven 2026-11-17 (Spike 3 slot 251, hidden, muted, the PCM kept): the Try it set of a project giving
its 14 stereo idx songs of 20 s or more a 700 Hz tone for mode 2 and 1100 Hz for mode 3 (28 records, the grown
program as game.pad) showed Music Mode on Adjustments > Machine Settings > Audio Content and read back 2, 3, 1 as
set; request 481 (idx0034) in mode 2 played 100% 700 Hz, request 477 (idx2440) in mode 3 100% 1100 Hz, request
478 (idx3945) in mode 1 the game's own song (work/artifacts/PAD-1359/emulator_transformers_*).

Transformers' request table reaches 66% of its 4945 sound ids (1545 requests, 1490 naming a recording), under
the 90% bar it was held to, so its extract had no Requests column and the proof had no request to ask for. Walking
Dead Remastered LE 0.92's reaches 17% of its 7836 (817 requests, 746 naming a recording): a table is taken now when
it reaches half the sound ids, or a tenth and three times any other registry table.
"""

import os
import struct

import pytest

from pinball_decryptor.plugins.stern import spike3_music as S3MU
from pinball_decryptor.plugins.stern import spike3_requests as R
from pinball_decryptor.plugins.stern import sound_modes as SMo

from tests.test_pad1244_spike3_sound_names import LISTS, build_game

#: the sound ids the synthetic table's lists reach (sid 0 ends a list)
REACHED = len({s for li in LISTS for s in li})
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "ports", "spike3",
                    "transformers_mtmte_le-0.96.port")


class _Program:
    """Just what :func:`.spike3_requests.request_table` reads: registry triples (pointer slots in
    ``rel``) over tables of 32-byte records whose sid-list pointer is at +16, VA = file offset."""

    def __init__(self, *tables):
        self.raw = bytearray(0x100)
        self.rel = {}
        for lists in tables:
            table = self._put(b"\x00" * (32 * len(lists)))
            for r in reversed(range(len(lists))):     # the last record's list right at the table's end
                at = self._put(b"".join(struct.pack("<I", x) for x in lists[r]) + b"\x00" * 4)
                self.rel[table + 32 * r + 16] = at
            reg = self._put(b"\x00" * 24)
            self.rel[reg] = table
            struct.pack_into("<QQ", self.raw, reg + 8, len(lists), 32)
        self.raw = bytes(self.raw)

    def _put(self, data):
        self.raw.extend(b"\x00" * (-len(self.raw) % 8))
        at = len(self.raw)
        self.raw.extend(data)
        return at

    def off(self, va):
        return va if 0 <= va < len(self.raw) else None

    def u64(self, va):
        return struct.unpack_from("<Q", self.raw, va)[0]

    def ptr(self, va):
        return self.rel.get(va, 0)


def _lists(first, n):
    """*n* requests over sound ids first .. first + n - 1 (eight is the least a table may have)."""
    return [[first + i] for i in range(n)]


def test_a_table_reaching_two_thirds_of_the_sound_ids_is_taken():
    # Transformers' 66%: 9 sound ids of 13 is 69%
    fragments = 13
    assert 0.6 < REACHED / fragments < 0.7
    assert R.request_table(R.Program(build_game()), fragments) == LISTS


def test_a_table_reaching_a_sixth_is_taken_when_it_dominates():
    # Walking Dead Remastered: 17% of the sound ids, the next table a handful
    req, other = _lists(1, 170), _lists(500, 9)
    assert R.request_table(_Program(other, req), 1000) == req


def test_a_table_that_does_not_dominate_is_refused_under_half():
    req, other = _lists(1, 170), _lists(500, 80)
    assert R.request_table(_Program(other, req), 1000) == []


def test_half_the_sound_ids_is_taken_whatever_else_there_is():
    req, other = _lists(1, 500), _lists(600, 300)
    assert R.request_table(_Program(other, req), 1000) == req


def test_under_a_tenth_is_refused_even_alone():
    assert R.request_table(_Program(_lists(1, 90)), 1000) == []
    # the PAD-1244 table on a card with ten times the sound ids
    assert R.request_table(R.Program(build_game()), 10 * (REACHED + 1)) == []


def test_transformers_is_a_proven_music_mode_build():
    assert "transformers_mtmte_le-0.96" in S3MU.PROVEN
    assert "transformers_mtmte_le-0.96" not in S3MU.NO_ROW


def test_its_port_names_the_lookup_the_modes_swap_at():
    with open(PORT, encoding="utf-8") as f:
        sites = [ln.split() for ln in f if ln.startswith("site ")]
    assert ["site", "sound_lookup", "0x0051fe30", "0xf9400c02", "0xb5000142"] in sites


def test_the_audio_tab_offers_them_on_transformers():
    from pinball_decryptor.plugins.stern import mode_project as MP
    prof = MP.profiles().get("transformers_mtmte_le_0_96_spike3")
    if prof is None:
        pytest.skip("no Transformers Spike 3 profile")
    assert S3MU.is_spike3(prof)
    assert SMo.title_refusal(prof) == ""
    # the rest of the sound pane stays Spike 2's
    assert "only the music modes" in SMo.title_refusal(prof, turns=True)
