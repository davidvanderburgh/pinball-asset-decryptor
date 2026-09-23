"""Item 149: ONE BUILDER for what the emulator runs and what Write ships.

Item 149's acceptance: "the emulator's override set (Try it) is built by the same code" as the
card. ``mode_write.build_tryit_set`` is that builder (``engine.write_overrides``: the same
``_compute_patches`` a card build runs, with the end sound, the manifest and the patched game
program). Item 127's Modes tab calls ``mode_tryit.build_set``; this module skips until that
module exists (the two items are merged on feature/mode-editor), and from then on it FAILS
until ``mode_tryit.build_set`` hands its work to ``mode_write.build_tryit_set`` - on purpose, so
the merge cannot leave two builders behind. The integration edit is in item 149's TODO entry.

feature/emulate-prepare adds the second half of the same promise: the builder prepares the set
the way the Emulate tab's own edits path does - FROM the card the project was extracted from
(``cards.override_base_card``, PAD-161) and run over the card picked (``run_card``, PAD-172).
"""
import json
import os

import pytest

# The mode maker ships dark behind a preview switch (core/preview.py); these tests are
# about what it does when it is ON (tests/test_preview_switch.py covers it OFF).
pytestmark = pytest.mark.usefixtures("preview_modes_on")

MT = pytest.importorskip("pinball_decryptor.plugins.stern.mode_tryit")

from pinball_decryptor.plugins.stern import cards                # noqa: E402
from pinball_decryptor.plugins.stern import engine as E          # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402
from pinball_decryptor.plugins.stern import mode_write as MW    # noqa: E402


def test_try_it_builds_its_set_with_writes_code(monkeypatch, tmp_path):
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 4096)
    base = str(tmp_path / "tryit")
    stage = os.path.join(base, MW.TRYIT_SET) + "-modes"
    calls = []

    def writes_builder(p, c, b, log=None, progress=None, cancel=None, label=None, sound_ok=None):
        calls.append((p, c, b))
        os.makedirs(stage, exist_ok=True)
        return MW.TryItSet(set_dir=os.path.join(b, MW.TRYIT_SET), stage_dir=stage,
                           game_dir="godzilla_pro", version="1.15",
                           mode_files=["mode.cfg", "mode1.cfg"],
                           slots=[(0, "atomic_breath", "ATOMIC BREATH"),
                                  (1, "kaiju_rush", "KAIJU RUSH")],
                           port=os.path.join(stage, "game.port"))
    monkeypatch.setattr(MW, "build_tryit_set", writes_builder)
    if hasattr(MT, "card_title"):          # Try it's own refusal of a card for another build
        monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 2))
    ts = MT.build_set(project, str(card), base=base)
    assert calls == [(project, str(card), base)], (
        "mode_tryit.build_set did not build through mode_write.build_tryit_set: Try it and "
        "Write are two builders again")
    assert ts.stage_dir == stage and [s[2] for s in ts.slots] == ["ATOMIC BREATH", "KAIJU RUSH"]


def test_writes_builder_prepares_from_the_base_card_and_runs_over_the_picked_one(
        monkeypatch, tmp_path):
    """The Emulate tab's own edits path prepares its set from override_base_card's answer and
    passes the picked card as run_card; Try it's set is built by the same call with the same
    two roles, so a card PAD built from the project runs the modes prepared from the card the
    project was measured on."""
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    picked = str(tmp_path / "built.raw")
    with open(picked, "wb") as f:
        f.write(b"\0" * 4096)
    stock = str(tmp_path / "stock.raw")
    with open(stock, "wb") as f:
        f.write(b"\0" * 4096)
    base = str(tmp_path / "tryit")
    asked, handed = [], {}

    def base_card(card_path, assets_dir, title_index):
        asked.append((card_path, assets_dir, title_index))
        return stock, "prepared from the stock card"

    def write_overrides(original_path, assets_dir, out_dir, log=None, progress=None,
                        cancel=None, label=None, run_card=None, **extra):
        handed.update(original=original_path, assets=assets_dir, out=out_dir,
                      run_card=run_card, extra=extra)
        stage = out_dir + E.OVERRIDE_MODES_SUFFIX
        os.makedirs(stage, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, E.OVERRIDE_MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"version": E.OVERRIDE_VERSION, "generation": "abc", "parent": "",
                       "files": [], "modes": {"dir": stage, "files": ["mode.cfg", "mode1.cfg"]}},
                      f)
        return (1, 0, 0, 0), ("", ""), ("", ""), []
    monkeypatch.setattr(cards, "override_base_card", base_card)
    monkeypatch.setattr(E, "write_overrides", write_overrides)
    said = []
    ts = MW.build_tryit_set(project, picked, base, log=lambda m, lvl="info": said.append(m),
                            sound_ok=False)
    assert asked == [(picked, project, E.card_title_index)]
    assert handed["original"] == stock and handed["run_card"] == picked
    assert handed["assets"] == project and handed["out"] == os.path.join(base, MW.TRYIT_SET)
    assert handed["extra"] == {"sound_ok": False}
    assert "prepared from the stock card" in said
    assert ts.reused is False and ts.mode_files == ["mode.cfg", "mode1.cfg"]
    # with the gate left to the environment, None reaches the engine, whose own default
    # (the environment gate) then stands
    handed.clear()
    os.remove(MW.tryit_sidecar(base))
    MW.build_tryit_set(project, picked, base)
    assert handed["extra"] == {"sound_ok": None}
