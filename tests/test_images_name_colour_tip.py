"""The Images tab's replacement name says what its colour means (Simon, 2026-11-19: "I didn't know what it meant and
therefore it needs explaining"): orange, picked and not yet written to the project; blue, written by an earlier Write."""
import os

TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")


def test_the_replacement_tooltip_explains_the_colour():
    src = open(os.path.join(TABS, "images.js"), encoding="utf-8").read()
    assert "{ text: \"Orange name = new, not yet written to the project (it goes in at the next Write)\", tone: \"accent\" }" in src
    assert "{ text: \"Blue name = already written to the project (by an earlier Write)\", tone: \"info\" }" in src
    assert 'TAG_CLS = { assigned: "img-picked", changed: "img-ondisk"' in src     # orange / blue, as said
