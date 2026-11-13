"""PAD-1237: long words in the virtual playfield's bottom bar (the boot step,
"98% Guided Setup is waiting for you: ...") pushed Volume, Mute and the save
states off the window. David's call: the bar is the run's controls alone, on
one row; the save states are a SAVE STATES section in the side panel (with
their own message line); what the last press said (a ball, a helper) is the
BALLS section's; the boot words are cut with a tooltip when they do not fit.

Proven in a real browser by scripts/shot_pad1237_playfield.py (one 36 px row,
every control inside the window at 820 and 1000 px); this pins the rules.
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PF = os.path.join(ROOT, "tools", "spike2_emu", "pfpage")


def _read(name):
    with open(os.path.join(PF, name), encoding="utf-8") as f:
        return f.read()


def _rule(css, selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def _fn(js, head):
    body = js[js.index(head):]
    return body[:body.index("\n  }\n") + 4]


def test_the_bar_is_one_row_of_controls_that_never_shrink():
    css = _read("pf.css")
    bar = _rule(css, ".pf-status")
    assert "wrap" not in bar
    assert "flex-shrink: 0" in _rule(css, ".pf-status > *")
    assert "display: contents" in _rule(css, ".pf-run")
    assert "flex-shrink: 0" in _rule(css, ".pf-run > *")
    assert "inline-flex" in _rule(css, ".pf-run .volgrp")
    # only the boot words give way, cut with an ellipsis
    boot = _rule(css, ".pf-run .boot")
    assert "min-width: 0" in boot and "overflow: hidden" in boot
    assert "text-overflow: ellipsis" in _rule(css, ".pf-run .boot .w")


def test_save_states_and_messages_left_the_bar():
    js = _read("pf.js")
    assert "stateCluster" not in js
    assert "status.append(states" not in js
    panel = _fn(js, "function statesPanel()")
    assert '"SAVE STATES"' in panel and 'saveDialog(sel.selectedIndex)' in panel
    assert 'api("load", sel.selectedIndex)' in panel and "s.msg" in panel
    # the status line's text is drawn in the BALLS section
    assert "panel.ballSec" in js and 'el("div", "pf-msg"' in js
    assert "msg.textContent = f.status" in js


def test_cut_boot_words_carry_a_tooltip_and_whole_ones_none():
    js = _read("pf.js")
    fn = js[js.index("function tipWhenCut("):]
    fn = fn[:fn.index("\n}\n")]
    assert "scrollWidth > words.clientWidth" in fn
    assert 'removeAttribute("title")' in fn
    assert "tipWhenCut(boot, bootW)" in js
    assert "boot.title" not in js


def test_save_state_messages_ride_the_slots_event_not_the_status_line():
    sys.path.insert(0, os.path.join(ROOT, "tools", "spike2_emu"))
    import playfield as pf
    ctl = pf.Playfield.__new__(pf.Playfield)
    ctl._slot_msg = None
    ctl._state_msg = None
    ctl.slot_labels = {}
    ctl._state_busy = False
    assert ctl.slot_msg() == ["", None]
    ctl.slot_say("saving state...", None)
    assert ctl.slots_payload(busy=True)["msg"] == ["saving state...", None]
    assert ctl.slots_payload(busy=True)["busy"] is True
    ctl.slot_say("slot 2 is empty - nothing to load", 5.0)
    text, left = ctl.slot_msg()
    assert text.startswith("slot 2 is empty") and 0 < left <= 5.0
    # never on the status line the BALLS section shows
    assert ctl.state_status() is None
    ctl._slot_msg = ("old", time.monotonic() - 1)
    assert ctl.slot_msg() == ["", None]
