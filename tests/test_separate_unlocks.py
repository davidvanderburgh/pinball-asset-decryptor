"""The Advanced box's separate unlocks (Simon, 2026-11-19: "images and video AND text are separate unlocks", the same box
on Scenes, Images and Video): the game's own lines of text have an unlock of their own, which follows the images one
until it is set (a project from before keeps working as it did)."""
import os

from pinball_decryptor.core import colour_profile as cp

STATIC = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js")


def test_text_follows_images_until_it_has_its_own():
    assert not cp.text_unlocked({})
    assert cp.text_unlocked({cp.STOCK_IMAGES_KEY: True})
    assert not cp.text_unlock_separate({cp.STOCK_IMAGES_KEY: True})
    assert not cp.text_unlocked({cp.STOCK_IMAGES_KEY: True, cp.STOCK_TEXT_KEY: False})
    assert cp.text_unlocked({cp.STOCK_TEXT_KEY: True})


def test_the_text_box_puts_the_lines_aside_and_back():
    data = {cp.STOCK_TEXT_KEY: True, cp.TEXT_SLOTS_KEY: {"card#5": True}}
    cp.set_text_unlocked(data, False)
    assert cp.TEXT_SLOTS_KEY not in data and data[cp.LOCKED_SWITCHES_KEY] == {"text": {"card#5": True}}
    cp.set_text_unlocked(data, True)
    assert data[cp.TEXT_SLOTS_KEY] == {"card#5": True} and cp.LOCKED_SWITCHES_KEY not in data


def test_with_a_text_box_the_images_box_leaves_the_lines_alone():
    data = {cp.STOCK_IMAGES_KEY: True, cp.STOCK_TEXT_KEY: True, cp.TEXT_SLOTS_KEY: {"card#5": True}}
    cp.lock_switches(data, {"images/a.png": True})
    assert data[cp.TEXT_SLOTS_KEY] == {"card#5": True}
    assert data[cp.LOCKED_SWITCHES_KEY] == {"images": {"images/a.png": True}}
    assert cp.unlock_switches(data) == {"images/a.png": True}
    assert data[cp.TEXT_SLOTS_KEY] == {"card#5": True}


def test_without_a_text_box_the_images_box_still_takes_the_lines():
    """A project from before: the one box was both, and still is until the new box is used."""
    data = {cp.STOCK_IMAGES_KEY: True, cp.TEXT_SLOTS_KEY: {"card#5": True}}
    cp.lock_switches(data, {})
    assert cp.TEXT_SLOTS_KEY not in data
    cp.unlock_switches(data)
    assert data[cp.TEXT_SLOTS_KEY] == {"card#5": True}


def test_one_box_on_scenes_images_and_video():
    with open(os.path.join(STATIC, "core", "unlock_box.js"), encoding="utf-8") as f:
        box = f.read()
    for label in ("Unlock extracted images", "Unlock extracted videos", "Unlock extracted text"):
        assert label in box
    for tab in ("text_scenes.js", "images.js", "video.js"):
        with open(os.path.join(STATIC, "tabs", tab), encoding="utf-8") as f:
            src = f.read()
        assert "<${UnlockBox}" in src, tab
        assert 'label="Unlock extracted images and text"' not in src and 'label="Advanced"' not in src, tab
