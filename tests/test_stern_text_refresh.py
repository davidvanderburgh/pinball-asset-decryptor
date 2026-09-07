"""The Text tab's card-backed refresh of the game program's text limits
(engine.refresh_program_text_flags).

A project extracted before the tool measured which program strings can take
longer text carries the original length as every budget and no flags; the tab
offers the 96-byte cap anyway, and a Scan fills in the exact answer from the
card the project came out of.
"""

import json

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.core import text_manifest as tm      # noqa: E402
from pinball_decryptor.plugins.stern import engine          # noqa: E402
from tests.test_stern_progtext import _build                # noqa: E402

GAME = "/godzilla_pro/game"
SCENE = "/godzilla_pro/assets/lcd/auto_loaded/aaaa1111/scene.radium"


def _project(tmp_path, card_size=4096, card_name="card.raw", rows=None):
    """A project folder with a manifest and an .extract_source.json pointing
    at a stand-in card image of *card_size* bytes."""
    assets = tmp_path / "proj"
    (assets / "text").mkdir(parents=True)
    card = tmp_path / card_name
    card.write_bytes(b"\0" * card_size)
    (assets / ".extract_source.json").write_text(
        json.dumps({"input_path": str(card), "input_name": card_name,
                    "size": card_size}), encoding="utf-8")
    tm.save(str(assets), rows if rows is not None else _old_rows())
    return assets, card


def _old_rows():
    """What an older extract wrote: budgets = the originals' own lengths,
    no flags anywhere, and an edit the user has already typed."""
    return [
        {"path": SCENE, "original": "TILT", "replacement": "TOLT"},
        {"path": GAME, "original": "GODZILLA VS EBIRAH",
         "replacement": "GODZILLA VS BIOLLANTE", "budget": 18},
        {"path": GAME, "original": "JACKPOT AWARD!", "replacement": "",
         "budget": 14},
        {"path": GAME, "original": "NOT ON THIS CARD", "replacement": "",
         "budget": 16},
    ]


def _fake_card(monkeypatch, raw):
    class _Reader:
        def read_file_bytes(self, _node):
            return raw
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [(0, 4096)])
    monkeypatch.setattr(engine, "_locate",
                        lambda f, parts: (_Reader(), object(), None))


def test_refresh_rewrites_program_budgets_and_flags_from_the_card(
        tmp_path, monkeypatch):
    raw, _offs = _build()
    assets, _card = _project(tmp_path)
    _fake_card(monkeypatch, raw)

    assert engine.refresh_program_text_flags(str(assets)) == 2

    rows = tm.load(str(assets))
    by = {(r["path"], r["original"]): r for r in rows}
    # a growable string: the 96-byte cap and the flag, edit untouched
    ebirah = by[(GAME, "GODZILLA VS EBIRAH")]
    assert ebirah["budget"] == 96 and ebirah.get("grow") is True
    assert ebirah.get("fixed") is None
    assert ebirah["replacement"] == "GODZILLA VS BIOLLANTE"
    # one the scan can't move says so explicitly, so "no flag" keeps meaning
    # "nobody has looked" for older manifests
    jackpot = by[(GAME, "JACKPOT AWARD!")]
    assert jackpot["budget"] == 14 and jackpot.get("fixed") is True
    assert jackpot.get("grow") is None and jackpot.get("unused") is True
    # a row this card doesn't have, and every scene row, are left alone
    gone = by[(GAME, "NOT ON THIS CARD")]
    assert gone["budget"] == 16 and "grow" not in gone and "fixed" not in gone
    tilt = by[(SCENE, "TILT")]
    assert tilt["replacement"] == "TOLT" and "budget" not in tilt
    # row order is the manifest's, not the ELF's
    assert [r["original"] for r in rows] == [
        "TILT", "GODZILLA VS EBIRAH", "JACKPOT AWARD!", "NOT ON THIS CARD"]


def test_refresh_is_a_no_op_when_the_card_is_gone(tmp_path, monkeypatch):
    raw, _offs = _build()
    assets, card = _project(tmp_path)
    card.unlink()
    _fake_card(monkeypatch, raw)
    said = []
    assert engine.refresh_program_text_flags(
        str(assets), log=lambda m, lvl="info": said.append(m)) == 0
    assert any("isn't where it was" in m for m in said)
    assert tm.load(str(assets)) == tm.load(str(assets))
    assert tm.load(str(assets))[1]["budget"] == 18      # untouched


def test_refresh_is_a_no_op_when_the_card_has_changed_size(
        tmp_path, monkeypatch):
    """Identity check: a different image at the remembered path would answer
    for the wrong build, so it is not consulted at all."""
    raw, _offs = _build()
    assets, card = _project(tmp_path)
    card.write_bytes(b"\0" * 8192)
    _fake_card(monkeypatch, raw)
    assert engine.refresh_program_text_flags(str(assets)) == 0
    assert tm.load(str(assets))[1]["budget"] == 18


def test_refresh_without_a_sidecar_or_program_rows_does_nothing(
        tmp_path, monkeypatch):
    raw, _offs = _build()
    _fake_card(monkeypatch, raw)
    # no .extract_source.json at all
    bare = tmp_path / "bare"
    (bare / "text").mkdir(parents=True)
    tm.save(str(bare), _old_rows())
    assert engine.refresh_program_text_flags(str(bare)) == 0
    # a scene-only project never opens the card
    scenes, _card = _project(
        tmp_path, rows=[{"path": SCENE, "original": "TILT",
                         "replacement": ""}])
    monkeypatch.setattr(engine, "_locate", lambda f, p: 1 / 0)
    assert engine.refresh_program_text_flags(str(scenes)) == 0


def test_refresh_survives_an_unreadable_card(tmp_path, monkeypatch):
    raw, _offs = _build()
    assets, _card = _project(tmp_path)
    _fake_card(monkeypatch, raw)
    monkeypatch.setattr(engine, "_locate",
                        lambda f, parts: (_ for _ in ()).throw(
                            ValueError("no ext4 partition")))
    said = []
    assert engine.refresh_program_text_flags(
        str(assets), log=lambda m, lvl="info": said.append(m)) == 0
    assert any("no ext4 partition" in m for m in said)
    assert tm.load(str(assets))[1]["budget"] == 18
