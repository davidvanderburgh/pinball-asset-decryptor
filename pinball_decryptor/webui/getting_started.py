"""The Getting started page's content (PAD-813): one short video and a few
steps for each job a new user comes to the app for.

The videos are ``static/videos/getting-started/<id>.mp4`` with a poster
``<id>.jpg`` beside each; ``scripts/make_getting_started_videos.py`` films
them from the real app on a Stern Spike 2 card.  The page itself is
``GettingStarted`` in ``static/js/shell.js``, its state ``shellx.getting_started``
(``shellx_getting_started.py``).
"""

import os

VIDEO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "static", "videos", "getting-started")

#: The four steps every mod takes, one tab each (docs/guide/using-the-app.md).
FLOW = (
    ("Select card", "pick the card image"),
    ("Extract", "copy its files out"),
    ("Replace", "swap what you want"),
    ("Write", "build and flash"),
)

#: id, title, the tab its button opens (a rail ns), the button's words, steps.
#: The tab is only offered when the open manufacturer has it.
TASKS = (
    {"id": "extract", "title": "Open and extract a card", "tab": "card",
     "go": "Open Select card",
     "steps": (
         "Choose your manufacturer.",
         "On Select card, press Browse… and pick the card image, or switch to From SD card "
         "and read the card in a reader.",
         "On Extract, pick a project folder and press Extract.",
         "Save card as image… keeps a backup of a stock card first.",
     )},
    {"id": "song", "title": "Swap a song", "tab": "audio",
     "go": "Open Replace Audio",
     "steps": (
         "Extract the card first.",
         "On Replace Audio, set Type to Music and find the song. Most Stern games name "
         "their own sounds.",
         "Right-click it, choose Choose replacement… and pick your mp3, wav or flac.",
         "Play Original and Replacement to compare. Write builds the card.",
     )},
    {"id": "build", "title": "Build and flash your card", "tab": "write",
     "go": "Open Write",
     "steps": (
         "On Write, press Build / flash SD card….",
         "Tick what to do: build the image, flash it, or both.",
         "Pick the SD card. Flashing erases the whole card.",
         "Put the SD card in the machine and power it on.",
     )},
    {"id": "flash", "title": "Write an image to an SD card", "tab": "write",
     "go": "Open Write",
     "steps": (
         "On Select card, press Browse… and pick the image file.",
         "Open Write. Stern, Jersey Jack and Chicago Gaming images need no extract.",
         "Press Build / flash SD card… and pick the SD card.",
         "Confirm. Flashing erases the whole SD card.",
     )},
    {"id": "multiboot", "title": "Several games on one card", "tab": "multiboot",
     "go": "Open Multi-boot",
     "steps": (
         "On Multi-boot, add your card images. The first one is the one the card boots "
         "from.",
         "Press ✎ on a row to give it a title, a picture or music (optional).",
         "The strip under the list names the SD card size you need.",
         "Press Build / flash card…. At power-up, pick a game with the flippers.",
     )},
    {"id": "emulate", "title": "Try it on your PC first", "tab": "emulate",
     "go": "Open Emulate",
     "steps": (
         "On Emulate, press Set up emulator… the first time.",
         "Pick the card image: a stock card or one you built.",
         "Press Start emulator. The game runs in its own window, with sound.",
         "The card is never written to.",
     )},
    {"id": "transfer", "title": "Move your mods to a new game version", "tab": "modpack",
     "go": "Open Mod Pack",
     "steps": (
         "Extract the new stock card into a folder of its own.",
         "On Mod Pack, open Transfer Mods to New Version.",
         "Fill in your old extract, the new extract and the new card image.",
         "Read the plan in the log, then confirm. Your sounds follow even if their "
         "numbers moved.",
     )},
)

NOTE = ("The videos use a Stern Spike 2 card. Other makers work the same way on the tabs "
        "they have.")


def video_path(task_id, ext="mp4"):
    return os.path.join(VIDEO_DIR, "%s.%s" % (task_id, ext))


def new_user(settings):
    """True for a settings file that has never been used: no manufacturer
    picked and no project made."""
    s = settings or {}
    return not s.get("last_manufacturer") and not s.get("projects")


def opens_at_launch(settings, environ=None):
    """Whether the page opens when the app starts: the user's own tick, else
    only for a brand-new user.  Test runs and captures that ask for the plain
    picker (``PAD_UI_NO_GETTING_STARTED``) never get it."""
    env = os.environ if environ is None else environ
    if env.get("PAD_UI_NO_GETTING_STARTED") == "1" or env.get("PYTEST_CURRENT_TEST"):
        return False
    s = settings or {}
    if "getting_started_at_launch" in s:
        return bool(s["getting_started_at_launch"])
    return new_user(s)
