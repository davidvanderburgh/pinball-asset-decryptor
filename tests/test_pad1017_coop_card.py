"""PAD-1017: co-op play on the card - the Write tab's tick, the build's gate, coop.cfg beside the runtime, and the
titles it is offered on (the latest of each title without co-op of its own)."""
import os
import re

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import sound_modes as SMo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GZ_ELF = "C:/tmp/PAD-1010/elfs/godzilla_le-1_16_0_spike2.elf"


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _latest():
    """The newest profile of each title."""
    best = {}
    for p in MP.profiles().values():
        v = tuple(int(x) for x in p.version.split("."))
        if p.game_dir not in best or v > best[p.game_dir][0]:
            best[p.game_dir] = (v, p)
    return [p for _v, p in best.values()]


def test_offered_on_every_latest_title_without_its_own_coop():
    latest = _latest()
    own = [p for p in latest if SMo.title_key(p).startswith(CP.OWN_COOP)]
    offered = [p for p in latest if not CP.title_refusal(p)]
    assert len(latest) == 53 and len(own) == 15
    assert len(offered) == 38
    assert {SMo.title_key(p) for p in offered} >= {"godzilla_le-1.16", "james_bond_le-1.06", "jurassic_park_the_pin-1.05"}
    for p in own:
        assert CP.title_refusal(p) == CP.OWN % p.label
    assert CP.title_refusal(None) == CP.NO_TITLE


@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_coop_cfg_names_the_right_flipper_button():
    with open(GZ_ELF, "rb") as f:
        elf = f.read()
    assert CP.cfg_text(elf) == "coop on\nbutton 59\n"


def test_no_flipper_buttons_no_cfg():
    with pytest.raises(CP.CoopError):
        CP.cfg_text(b"not a program")


def test_the_plan_puts_coop_cfg_beside_the_runtime(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    prof = MP.profile_for_card("godzilla", "1.16") if hasattr(MP, "profile_for_card") else None
    prof = prof or next(p for p in MP.profiles().values() if SMo.title_key(p) == "godzilla_le-1.16")
    monkeypatch.setattr(CP, "cfg_text", lambda elf: "coop on\nbutton 59\n")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: MP.port_path(prof))
    result = MW.plan(str(tmp_path), b"", b"", b"elf", str(tmp_path / "scratch"), modes_on=False,
                     coop=True, coop_prof=prof)
    assert result is not None and result.build is None
    assert _read(result.coop_file) == "coop on\nbutton 59\n"
    assert any(line.startswith("co-op play: hold the right flipper button") for line in result.lines)


def test_the_card_install_and_the_emulator_carry_coop_cfg():
    install = _read(os.path.join(REPO, "tools", "spike2_emu", "mode_install.py"))
    assert '("coop.cfg", 0o100644)' in install
    assert re.search(r'STANDALONE_FILES = \([^)]*"coop\.cfg"', install)
    for rel in ("cardmodes.sh", "tryit.sh"):
        text = _read(os.path.join(REPO, "tools", "spike2_emu", "modes", rel))
        assert '"$DUMP/coop.cfg"' in text or '"$DUMP"/coop.cfg' in text
    stage = _read(os.path.join(REPO, "pinball_decryptor", "plugins", "stern", "mode_write.py"))
    assert 'if getattr(result, "coop_file", ""):' in stage


def test_the_write_tab_tick_saves_the_choice_and_says_how_teammates_join(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import write as W
    from pinball_decryptor.core import staged_changes

    class Mfr:
        key = "stern"
        current_era = "spike2"

    class Win:
        _running = False
        cb = {}

    monkeypatch.setattr(W.WriteTab, "mfr", property(lambda self: Mfr()))
    svc = W.WriteTab.__new__(W.WriteTab)
    svc.window = Win()
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "cap", lambda n: True, raising=False)
    monkeypatch.setattr(svc, "_is_direct", lambda: False, raising=False)
    monkeypatch.setattr(svc, "_info_assets_dir", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "log", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    staged_changes.save(str(tmp_path), {"audio": {"x": "y"}})
    assert svc.set_coop(True) is True
    data = staged_changes.load(str(tmp_path))
    assert data[CP.STAGED_KEY] == {"on": True} and data["audio"] == {"x": "y"}
    assert state["coop_cap"] is True and state["coop_on"] is True
    assert state["coop_note"].startswith("On the card: Hold the right flipper button and press Start")
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "Venom LE 1.07 has co-op play of its own.")
    svc._publish_coop()
    assert state["coop_note_kind"] == "err"
    assert svc.set_coop(False) is True
    assert CP.STAGED_KEY not in staged_changes.load(str(tmp_path))
    assert state["coop_on"] is False and state["coop_note"] == ""


def test_the_build_gate_leaves_it_out_of_a_direct_write(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    said = []
    assert E._coop_for_build(str(tmp_path), False, lambda m, *a: said.append(m)) is None and not said
    CP.save(str(tmp_path), True)
    assert E._coop_for_build(str(tmp_path), True, lambda m, *a: said.append(m)) is None
    assert "direct-SD write" in said[-1]
