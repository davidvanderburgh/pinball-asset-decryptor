"""PAD-652: New mode opens a wizard (static/js/tabs/modes_new.js) instead of a drop-down.

The wizard only asks: Python makes the mode through the same calls the menu made. These pin the
wiring (every call it makes is one the Modes tab answers, and the tab uses the wizard in both
places), the order and words David asked for (Blocks recommended, C for an AI agent, the form a
playground), and that the drop-down is gone. scripts/e2e_pad652.py drives every path through the
served app.
"""

import os
import re

from pinball_decryptor.webui.tabs import modes as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")


def _read(name):
    with open(os.path.join(TABS, name), encoding="utf-8") as f:
        return f.read()


def test_every_call_the_wizard_makes_is_one_the_tab_answers():
    js = _read("modes_new.js")
    calls = set(re.findall(r'call\("modes\.([a-z_]+)"', js))
    assert calls == {"new", "example", "new_blocks_mode", "new_code_mode", "blocks_example",   # PAD-658
                     "open_sdk_doc", "open_limits_doc"}, calls                              # PAD-691: no C examples
    for name in calls:
        fn = getattr(M.ModesTab, name, None)
        assert callable(fn), name


def test_the_ways_in_their_order_with_their_words():
    js = _read("modes_new.js")
    keys = re.findall(r'^  \{ key: "([a-z]+)", icon: "[a-z]+", title: "([^"]+)", badge: "([^"]+)"', js, re.M)
    assert keys == [("blocks", "Blocks", "Recommended"), ("c", "C", "Best with an AI agent"),
                    ("form", "Form", "Playground")], keys
    # the agent's brief names the mode's file and the SDK's guide to read first
    assert "Its file is ${file}" in js and "Read ${sdkDoc} top to bottom first" in js


def test_the_tab_opens_the_wizard_and_the_menu_is_gone():
    modes = _read("modes.js")
    assert 'import { NewModeWizard, KindTiles } from "./modes_new.js";' in modes
    assert ">New mode<//>" in modes and "newMenuItems" not in modes and "Mode from blocks…" not in modes
    assert "<${KindTiles} s=${s} onPick=${onNew} compact />" in modes      # the first-mode page
    assert "NewCodeDialog" not in _read("modes_dialogs.js")
