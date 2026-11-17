"""PAD-1359: music modes on Transformers LE 0.96 (Spike 3), and its sound request map.

Emulator-proven 2026-11-17 (Spike 3 slot 251, hidden, muted, the PCM kept): the Try it set of a project giving
its 14 stereo idx songs of 20 s or more a 700 Hz tone for mode 2 and 1100 Hz for mode 3 (28 records, the grown
program as game.pad) showed Music Mode on Adjustments > Machine Settings > Audio Content and read back 2, 3, 1 as
set; request 481 (idx0034) in mode 2 played 100% 700 Hz, request 477 (idx2440) in mode 3 100% 1100 Hz, request
478 (idx3945) in mode 1 the game's own song (work/artifacts/PAD-1359/emulator_transformers_*).

Transformers' request table reaches 66% of its 4945 sound ids (1545 requests, 1490 naming a recording), under
the 90% bar it was held to, so its extract had no Requests column and the proof had no request to ask for.
"""

import os

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


def test_a_table_reaching_two_thirds_of_the_sound_ids_is_taken():
    # Transformers' 66%: 9 sound ids of 13 is 69%
    fragments = 13
    assert 0.6 < REACHED / fragments < 0.7
    assert R.request_table(R.Program(build_game()), fragments) == LISTS


def test_a_table_reaching_under_half_is_still_refused():
    # Walking Dead Remastered's best table reaches 17%: not its requests
    fragments = 2 * REACHED + 1
    assert R.request_table(R.Program(build_game()), fragments) == []


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
