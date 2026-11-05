"""PAD-1000: the Jukebox window (and Sounds on shots) can be moved and resized, and keeps its place.

The behaviour itself is proven in a browser by scripts/shot_pad1000.py (drag the title bar, drag the
corner grip, reload, reopen: same place and size); these keep the wiring from going missing.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "pinball_decryptor", "webui", "static")


def _read(*parts):
    with open(os.path.join(STATIC, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_dialog_takes_a_name_to_remember_its_place_by():
    js = _read("js", "core", "ui.js")
    assert re.search(r"export function Modal\(\{[^}]*\bremember\b", js)
    assert '"pad.modal." + name' in js                      # kept per dialog, across sessions
    assert 'class="modal-grip"' in js                       # the corner to size it by
    assert "onDblClick=${remember ? reset : null}" in js    # a double-click puts it back
    assert "function fitGeom" in js                         # never left off the page


def test_the_audio_windows_remember_their_place():
    js = _read("js", "tabs", "audio.js")
    assert 'title="Jukebox" icon="audio" wide remember="jukebox"' in js
    assert 'title="Sounds on shots" icon="audio" wide remember="shots"' in js


def test_a_placed_dialog_is_sized_by_hand_and_its_list_fills_it():
    css = _read("css", "app.css")
    assert ".modal.placed { position: fixed; max-height: none;" in css
    assert ".modal-grip {" in css and "nwse-resize" in css
    assert ".modal.placed .aud-juke { max-height: none;" in _read("css", "tabs", "audio.css")
