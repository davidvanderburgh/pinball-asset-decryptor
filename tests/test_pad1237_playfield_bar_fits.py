"""PAD-1237: long words in the virtual playfield's bottom bar (the boot step,
"98% Guided Setup is waiting for you: ...", or the status line) pushed Volume,
Mute and the save states off the window. Words now give way, cut with an
ellipsis and whole in a tooltip only when cut; the controls keep their size,
and the bar wraps onto another row when even they do not fit.

Proven in a real browser by scripts/shot_pad1237_playfield.py (every control's
right edge inside the window at 820, 1000 and 1500 px); this pins the rules.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PF = os.path.join(ROOT, "tools", "spike2_emu", "pfpage")


def _read(name):
    with open(os.path.join(PF, name), encoding="utf-8") as f:
        return f.read()


def _rule(css, selector):
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def test_the_bar_wraps_and_its_controls_never_shrink():
    css = _read("pf.css")
    assert "flex-wrap: wrap" in _rule(css, ".pf-status")
    assert "flex-shrink: 0" in _rule(css, ".pf-status > *")
    # the run's controls are the bar's own items, so they wrap with it
    assert "display: contents" in _rule(css, ".pf-run")
    assert "flex-shrink: 0" in _rule(css, ".pf-run > *")
    # Volume, its % and Mute wrap as one
    assert "inline-flex" in _rule(css, ".pf-run .volgrp")


def test_words_take_only_the_room_left_and_are_cut():
    css = _read("pf.css")
    txt = _rule(css, ".pf-status .txt")
    boot = _rule(css, ".pf-run .boot")
    for r in (txt, boot):
        assert re.search(r"flex: \d+ 1 0;", r), r
        assert "overflow: hidden" in r
    assert "text-overflow: ellipsis" in txt
    assert "text-overflow: ellipsis" in _rule(css, ".pf-run .boot .w")
    # an empty status line reserves nothing
    assert "min-width: 0" in _rule(css, ".pf-status .txt:empty")
    # the old cap that let the boot words push the controls out is gone
    assert "64ch" not in boot


def test_cut_words_carry_a_tooltip_and_whole_ones_none():
    js = _read("pf.js")
    fn = js[js.index("function tipWhenCut("):]
    fn = fn[:fn.index("\n}\n")]
    assert "scrollWidth > words.clientWidth" in fn
    assert "host.title = words.textContent" in fn
    assert 'removeAttribute("title")' in fn
    assert "tipWhenCut(stxt, stxt)" in js
    assert "tipWhenCut(boot, bootW)" in js
    # the boot step no longer sets a tooltip of its own every update
    assert "boot.title" not in js
    # Mute stays with its slider
    assert re.search(r'grp\.append\(lab, vol, pct, mbox\)', js)
