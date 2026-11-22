"""PAD-1505: Editions and Music Mode on Pokemon LE 0.87 (Spike 3).

0.82's operator menu used every setting EDITION and MUSIC MODE could take over; 0.87's has spare ones (PAD-1504
found them), so both go on it once proven in the emulator, as Fallout's and Transformers' did:

- Music Mode (2026-11-22, Spike 3 rig slot 155, hidden, muted, the PCM kept): the Try it set of a 0.87 audio
  extract giving its 37 stereo songs of 20 s or more a 700 Hz tone for mode 2 and 1100 Hz for mode 3 (74 records,
  the grown program over the stock one). Adjustments > Machine Settings > Audio Content listed Music Mode
  ("1 = Standard, 2 = Custom A, 3 = Custom B") and read back 2, 3, 1 as set; request 64 in mode 2 took mode 2's
  record and played 99% 700 Hz, request 66 in mode 3 99% 1100 Hz, request 67 in mode 1 the game's own song.
- Editions: see docs/plans/spike3_modes.md, "Pokemon LE 0.87" (the real Write's EDITION on Attract Mode, a
  two-edition card booting the edition the setting names).

The program checks run when PAD_S3_PROGRAMS names a folder holding pokemon_le-0.87.game (the card's
/games/pokemon_le/game), as tests/test_pad1504_pokemon_087_port.py's do.
"""
import os
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import editions as Ed
from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern import spike3_menu as S3M
from pinball_decryptor.plugins.stern import spike3_music as S3MU

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "ports", "spike3", "pokemon_le-0.87.port")
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
NAMES = ["Standard", "Dark Side"]


def _program():
    path = os.path.join(PROGS, "pokemon_le-0.87.game") if PROGS else ""
    if not path or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no pokemon_le-0.87.game")
    with open(path, "rb") as f:
        return f.read()


def test_0_87_is_a_proven_music_mode_and_edition_build():
    assert "pokemon_le-0.87" in S3MU.PROVEN and "pokemon_le-0.87" not in S3MU.NO_ROW
    assert "pokemon_le-0.87" in Ed.SPIKE3_PROVEN and "pokemon_le-0.87" not in Ed.SPIKE3_FULL
    assert Ed.spike3_refusal("pokemon_le", "0.87.0") == ""


def test_0_82_still_has_no_spare_setting():
    assert "pokemon_le-0.82" in S3MU.NO_ROW and "pokemon_le-0.82" not in S3MU.PROVEN
    assert "uses every setting EDITION could take" in Ed.spike3_refusal("pokemon_le", "0.82.0")


def test_the_refusal_names_every_proven_build():
    why = Ed.spike3_refusal("some_new_title", "0.10.0")
    assert "Pokemon 0.87" in why and "Transformers 0.96" in why


def test_its_port_names_the_lookup_the_modes_swap_at():
    with open(PORT, encoding="utf-8") as f:
        assert any(ln.split()[:2] == ["site", "sound_lookup"] for ln in f if ln.startswith("site "))


def test_the_audio_tab_offers_them_on_0_87():
    from pinball_decryptor.plugins.stern import mode_project as MP
    prof = next((p for k, p in MP.profiles().items() if SMo.title_key(p) == "pokemon_le-0.87"
                 and S3MU.is_spike3(p)), None)
    if prof is None:
        pytest.skip("no Pokemon LE 0.87 Spike 3 profile")
    assert SMo.title_refusal(prof) == ""
    assert "only the music modes" in SMo.title_refusal(prof, turns=True)   # the rest of the pane stays Spike 2's


def test_edition_grows_onto_attract_mode():
    elf = _program()
    out, settings, refused = S3M.grow(elf, [(MS.EDITION, 2, NAMES)])
    assert not refused and [s.key for s in settings] == [MS.EDITION]
    assert settings[0].where == "Adjustments > Machine Settings > Attract Mode"
    assert Ed.in_program(out) == {"values": 2, "help": "1 = Standard, 2 = Dark Side", "id": settings[0].id}


def test_music_mode_grows_onto_audio_content_beside_edition():
    elf = _program()
    modes = SimpleNamespace(count=2, menu_names=lambda: ["Standard", "Custom A", "Custom B"])
    setting, grown = S3MU.menu_program(elf, modes, [(MS.EDITION, 2, NAMES)])
    assert setting.key == MS.MUSIC_MODE and not MS.check(grown, setting)
    assert setting.where == "Adjustments > Machine Settings > Audio Content"
    assert Ed.in_program(grown)["values"] == 2
