"""PAD-197 proof shot: the Multi-boot tab after reading a card's boot MENU off
an SD card (item 99).  That image holds the menu partition only, so the
inspect cannot read a single games tree - which used to raise the red "game
code version could not be read" strip about a card with nothing wrong on it.

    python scripts/shot_pad197.py <out.png>

The server runs from THIS tree against a scratch settings folder (no WSL, no
rig).  The inspect is a canned report shaped like the one in the ticket: six
Beatles images, every tree unread, fed to the panel's own load_inspect when
the tab is first shown.
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import json, sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import multiboot_panel as mp
from pinball_decryptor.webui import host
REPORT, CARD, MEDIA = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad197_done", False):
        self._pad197_done = True
        self.load_inspect(REPORT, CARD, MEDIA)
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''

TITLES = [("Beatlemania", "1964"), ("Rubber Soul", "1965"), ("Revolver", "1966"),
          ("Sgt. Pepper", "1967"), ("Abbey Road", "1969"), ("Let It Be", "1970")]


def main():
    out = os.path.abspath(sys.argv[1])
    scratch = tempfile.mkdtemp(prefix="pad197-")
    cards = os.path.join(scratch, "pinball_spike2_multiboot", "cards")
    os.makedirs(cards)
    card = os.path.join(cards, "SanDisk_SD_Card-32G.menu.raw")
    with open(card, "wb") as f:
        f.write(bytes(16))
    sys.path.insert(0, REPO)
    from pinball_decryptor.webui.multiboot_core import loaded_media_dir
    media = loaded_media_dir(card)
    os.makedirs(media, exist_ok=True)
    devs = ["/dev/mmcblk0p3"] + ["/dev/mmcblk0p3:img%d" % i for i in range(1, 6)]
    notes = (["its games tree could not be read (Refused: no title directory "
              "with a game file in this tree)"] +
             ["images.conf names %s but the card carries no such games tree" % d
              for d in devs[1:]])
    images = [{"index": i, "device": d, "title": t, "subtitle": s, "art": None,
               "anim": None, "music": None, "art_source": "none",
               "anim_source": "none", "source": None, "source_exists": False,
               "title_dir": None, "bypass": None, "version": None}
              for i, (d, (t, s)) in enumerate(zip(devs, TITLES))]
    report = {
        "card": card, "size": 31914983424, "layout": "store",
        "images": images, "timeout": 30, "default": 0, "volume": 35,
        "mixer_volume": None, "sound_move": "synth", "sound_confirm": "none",
        "media": [], "has_media_json": True, "has_build_json": True,
        "selector": {"bytes": 41272, "version": "codeselect 1.0"},
        "warnings": ["image %d (%s): %s" % (i, d, n)
                     for i, (d, n) in enumerate(zip(devs, notes))],
        "unknown_version": "%d image(s) did not say what game code they run: %s." % (
            len(devs), "; ".join("image %d (%s)" % (i, n) for i, n in enumerate(notes)))}
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump([report, card, media], f)
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "spec": spec})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    # the scratch APPDATA moves Python's user site too, and Pillow may live there
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        time.sleep(4)
        st = webui_shot.state(url)["multiboot"]
        print("alarm:", json.dumps(st.get("alarm"))[:300], flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
