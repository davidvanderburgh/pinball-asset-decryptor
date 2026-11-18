"""PAD-1407: a whole new game's own attract - the game's own attract screens taken off (Replace the game's attract
keeps its high score and champion screens), the owner's title card in their place.

- The record keeps the screens taken off (``hidden``), attract.cfg says them as ``hide <entry>`` lines, and the
  runtime reads those lines (one wrapper per entry, as many as the app lets be taken off).
- A build of hidden screens alone writes attract.cfg; every screen taken off with nothing of the owner's is refused.
- Mod packs and Move Your Mods carry a record of hidden screens alone.
- The Attract page: Hide/Show a run of screens, Replace the game's attract (and back).
"""
import json
import os
import re
import types

import pytest

from pinball_decryptor.plugins.stern import attract_items as AI

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk")


# ---- the record and attract.cfg -------------------------------------------------------------------------------
def test_the_record_keeps_the_screens_taken_off():
    rec = AI.clean({"items": [], "hidden": [5, 1, 1, "x", -2, AI.MAX_HIDE, 3]})
    assert rec.hidden == [1, 3, 5]
    assert not rec.empty()
    assert rec.as_dict() == {"items": [], "champions": True, "hidden": [1, 3, 5]}
    assert "hidden" not in AI.Record().as_dict() and AI.Record().empty()


def test_asks_sees_a_record_of_hidden_screens_alone():
    assert AI.asks({"items": [], "hidden": [2]})
    assert AI.asks({"champions": False}) and AI.asks({"items": [{"kind": "text"}]})
    assert not AI.asks({"items": [], "champions": True}) and not AI.asks(None)


def test_attract_cfg_says_the_hidden_screens():
    text = AI.cfg_text([(0, "before", "PadAttract1", 6000)], champions=True, hidden=[4, 2, 2])
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == ["hide 2", "hide 4", "item 0 before PadAttract1 6000"]


def test_hidden_words():
    assert AI.hidden_words([0, 1, 2, 5]) == "screens 1-3, 6"
    assert AI.hidden_words([7]) == "screen 8"


def test_replace_keeps_the_high_score_and_champion_screens():
    keep = AI.Page(entry=4, page=1, test=0, name="High score / champion page")
    assert AI.kept_on_replace(keep)
    assert not AI.kept_on_replace(AI.Page(entry=1, page=1, test=0, name="Game Intro"))
    assert not AI.kept_on_replace(AI.Page(entry=2, page=1, test=0, name="Game screen 3"))


# ---- the runtime -----------------------------------------------------------------------------------------------
def test_the_runtime_reads_hide_lines_with_a_wrapper_per_entry():
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"#define AIT_WRAP (\d+)", src)
    assert m and int(m.group(1)) == AI.MAX_HIDE
    assert 'str_eq(f[0], "hide")' in src and 'str_eq(f[0], "census")' in src
    assert 'str_starts(raw + i, "hide ")' in src                 # a card of hidden screens alone takes the gate
    blocks = int(m.group(1)) // 8
    assert len(re.findall(r"AIT_W8\(\d+\)", src)) == blocks and len(re.findall(r"AIT_P8\(\d+\)", src)) == blocks
    # a hidden entry with items shows them and not the game's page; a whole round of no lets one through
    assert "!ait_bit(ait_hidden, ait_anchor_entry[a])" in src and "ait_noes < ait_count" in src
    # every screen taken off with nothing of the owner's: the runtime shows the game's screens instead
    assert "the game's screens are all shown" in src


# ---- the build ---------------------------------------------------------------------------------------------------
def _fake_title(monkeypatch, count=10):
    monkeypatch.setattr(AI, "title_refusal", lambda prof: "")
    monkeypatch.setattr(AI, "port_table", lambda prof: {"count": count, "size": 8, "table": 0, "page_at": 4})


def test_a_build_of_hidden_screens_alone_writes_attract_cfg(tmp_path, monkeypatch):
    _fake_title(monkeypatch)
    from pinball_decryptor.plugins.stern import clip_variants as CV
    monkeypatch.setattr(CV, "bank_scene", lambda prof: "game/assets/lcd/bank/scene.radium")
    rec = AI.Record(hidden=[1, 2, 3, 12])
    got = AI.build(str(tmp_path), object(), b"BANK", str(tmp_path / "out"), rec=rec)
    with open(got.cfg, encoding="utf-8") as f:
        lines = [l for l in f.read().splitlines() if not l.startswith("#")]
    assert lines == ["hide 1", "hide 2", "hide 3"]               # 12 is past the game's 10 screens
    assert got.bank == b"BANK" and got.new == []
    assert any("3 of the game's 10 attract screens taken off (screens 2-4)" in l for l in got.lines)


def test_every_screen_taken_off_and_nothing_of_yours_is_refused(tmp_path, monkeypatch):
    _fake_title(monkeypatch, count=4)
    with pytest.raises(AI.AttractError, match="nothing of yours"):
        AI.build(str(tmp_path), object(), b"BANK", str(tmp_path / "out"), rec=AI.Record(hidden=[0, 1, 2, 3]))


# ---- carried with the project -----------------------------------------------------------------------------------
def test_a_mod_pack_carries_hidden_screens_alone(tmp_path):
    from pinball_decryptor.core import modpack
    rec, files, gone = modpack.pack_attract({"items": [], "champions": True, "hidden": [0, 2]})
    assert rec == {"items": [], "champions": True, "hidden": [0, 2]} and files == [] and gone == []
    assert "2 of the game's attract screens taken off" in modpack._attract_words(rec)
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(tmp_path), {})
    applied = modpack.apply_extras(str(tmp_path), {AI.STAGED_KEY: rec})
    assert applied.get(AI.STAGED_KEY) == 1
    assert AI.load(str(tmp_path)).hidden == [0, 2]


# ---- the page ----------------------------------------------------------------------------------------------------
class _Page:
    """the Attract tab's hidden/replace buttons without a window"""

    def __init__(self, tmp_path, pages, items=()):
        from pinball_decryptor.webui.tabs import attract as T
        self.T = T
        tab = T.AttractTab.__new__(T.AttractTab)
        tab._state = {"available": True, "running": False}
        tab.get = lambda k, d=None: tab._state.get(k, d)
        tab.set = lambda **kw: tab._state.update(kw)
        tab.log = lambda *a, **k: None
        tab._project = str(tmp_path)
        tab._pages = pages
        tab._rec = AI.Record(items=list(items))
        self.tab = tab


def _pages():
    names = ["Game Intro", "Game screen 2", "High score / champion page", "High score / champion page",
             "Game screen 5"]
    return [AI.Page(entry=k, page=0x1000 + k, test=0, name=n) for k, n in enumerate(names)]


def _rpc(fn):
    return getattr(fn, "__wrapped__", fn)


def test_replace_takes_off_all_but_the_high_scores_and_puts_a_title_card_first(tmp_path):
    p = _Page(tmp_path, _pages())
    tab = p.tab
    assert _rpc(p.T.AttractTab.replace_all)(tab, True)
    assert tab._rec.hidden == [0, 1, 4]
    assert [(i.kind, i.entry, i.where) for i in tab._rec.items] == [("text", 0, "before")]
    assert tab._state["hidden"] == 3 and tab._state["replaced"] is True
    rows = [r for r in tab._state["seq"] if r["t"] == "game"]
    assert [(r["first"], r["last"], r["hidden"]) for r in rows] == [(0, 0, True), (1, 1, True), (2, 3, False),
                                                                    (4, 4, True)]
    saved = json.load(open(os.path.join(str(tmp_path), ".staged_changes.json"), encoding="utf-8"))
    assert saved[AI.STAGED_KEY]["hidden"] == [0, 1, 4]
    assert _rpc(p.T.AttractTab.replace_all)(tab, False)
    assert tab._rec.hidden == [] and tab._state["replaced"] is False
    assert len(tab._rec.items) == 1                                # the owner's title card stays


def test_hide_and_show_a_run_of_screens(tmp_path):
    p = _Page(tmp_path, _pages())
    tab = p.tab
    assert _rpc(p.T.AttractTab.set_hidden)(tab, 2, 3, True)
    assert tab._rec.hidden == [2, 3]
    assert _rpc(p.T.AttractTab.set_hidden)(tab, 3, 3, False)
    assert tab._rec.hidden == [2]


def test_hiding_every_screen_with_nothing_of_yours_is_refused(tmp_path, monkeypatch):
    p = _Page(tmp_path, _pages())
    said = []
    monkeypatch.setattr(p.T.compat, "messagebox", types.SimpleNamespace(showinfo=lambda *a: said.append(a)))
    assert not _rpc(p.T.AttractTab.set_hidden)(p.tab, 0, 4, True)
    assert p.tab._rec.hidden == [] and said
