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

#: id, title, the tab its button opens (a rail ns, or "" for none), the
#: button's words, steps.  The tab is only offered when the open manufacturer
#: has it.
TASKS = (
    {"id": "install", "title": "Install and get ready", "tab": "", "go": "",
     "steps": (
         "Run the installer. It brings its own Python, so the app starts straight away.",
         "From the Start Menu, run Install Prerequisites and tick the makers you use.",
         "If it says restart required, use Restart (not Shut down), then run it again.",
         "In the app, ⚙ > Prerequisites shows what is in, and Install missing "
         "prerequisites… adds the rest.",
     )},
    {"id": "extract", "title": "Open and extract a card", "tab": "card",
     "go": "Open Select card",
     "steps": (
         "Choose your manufacturer.",
         "On Select card, press Browse… and pick the card image, or switch to From SD card "
         "and read the card in a reader.",
         "On Extract, pick a project folder and press Extract.",
         "Reading an SD card? Save card as image… on Select card keeps a backup of it "
         "first.",
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
    {"id": "video", "title": "Swap a video", "tab": "video",
     "go": "Open Replace Video",
     "steps": (
         "Extract the card first.",
         "On Replace Video, find the clip. Click it to play it in the Original pane.",
         "Right-click it, choose Choose replacement… and pick your clip. One that does "
         "not match the slot is converted when you build.",
         "Compare plays them side by side. Write builds the card.",
     )},
    {"id": "images", "title": "Swap a picture", "tab": "images",
     "go": "Open Replace Images",
     "steps": (
         "Extract the card first.",
         "On Replace Images, search for the picture and click it.",
         "Right-click it, choose Choose replacement… and pick your png or jpg.",
         "It is scaled to the original's size, transparency kept. Write builds the card.",
     )},
    {"id": "text", "title": "Change the game's text", "tab": "text",
     "go": "Open Replace Text",
     "steps": (
         "Extract the card first.",
         "On Replace Text, search for the words you want to change and click the line.",
         "Type the new words in New text and press Apply. Max is how long the line can be.",
         "Replace everywhere… changes the same words on every line at once. Write builds "
         "the card.",
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
         "Open Write. Stern, Jersey Jack and Chicago Gaming images need no extract.",
         "Press Build / flash SD card… and tick Write an image onto the SD card.",
         "Next to Image file, press Browse… and pick the image, then pick the SD card.",
         "Press Flash image and confirm. Flashing erases the whole SD card.",
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
         "Open the project that holds your mods.",
         "On Mod Pack, press Port + build onto card image(s)….",
         "Pick the new stock card image: a new version, or the other model.",
         "It extracts that card, moves your mods onto it and builds it. The log names "
         "anything it skipped.",
     )},
)

#: Common first-day problems and what fixes them (docs/guide/install.md).
PROBLEMS = (
    ("Ubuntu failed to install",
     "Restart Windows with Restart, then run Install Prerequisites again. Still missing? "
     "Install Ubuntu from the Microsoft Store, open it once, and run Install Prerequisites "
     "again."),
    ("Virtualization is disabled",
     "Turn on Intel VT-x or AMD SVM in the PC's firmware setup, then run Install "
     "Prerequisites again."),
    ("A tab has a lock on it",
     "That tab needs the card's files. Extract the card into a project folder first."),
    ("Something else went wrong",
     "Report a problem in the top bar sends the log and the card's details."),
)

#: The written guides on GitHub (docs/guide), opened from the page.
GUIDES = {
    "getting_started": "getting-started.md",
    "common_problems": "common-problems.md",
}


def guide_url(key):
    from ..core.config import GITHUB_REPO
    page = GUIDES.get(key)
    if not page:
        return ""
    return "https://github.com/%s/blob/main/docs/guide/%s" % (GITHUB_REPO, page)


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
