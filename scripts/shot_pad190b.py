"""PAD-190 (round 2) proof shot: Menu settings, where the menu's own WORDS are
set - the heading, the instructions line under the cards, and what the
countdown says.

    python scripts/shot_pad190b.py <out.png>

The server runs from THIS tree against a scratch settings folder (no WSL, no
rig).  A canned ``inspect`` report shaped like BEN's card - six Beatles
images, a 30 s countdown - is fed to the panel when the tab is first shown, so
the dialog's example line names a real image the way it does on his machine;
then 'Menu settings…' is opened and the modal itself is photographed.
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
    if not getattr(self, "_pad190_done", False):
        self._pad190_done = True
        self.load_inspect(REPORT, CARD, MEDIA)
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''

TITLES = [("Beatlemania", "1964"), ("Rubber Soul", "1965"), ("Revolver", "1966"),
          ("Sgt. Pepper", "1967"), ("Abbey Road", "1969"), ("Let It Be", "1970")]

#: The window the modal is photographed in.  Tall enough for the whole of
#: Menu settings, which is the one dialog in this tab that fills a screen.
SHOT_W, SHOT_H = 1180, 1080


def shoot(url, out, scratch):
    """The page, photographed.  Playwright when this machine has it (the rig
    in webui_shot.py); otherwise the installed Edge in headless mode, which
    every Windows machine already has - a screenshot is all this needs, and
    the browser's own --screenshot does it without a dependency nobody
    declared (there is no playwright in requirements-dev.txt)."""
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _edge_shot(url, out, scratch)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": SHOT_W, "height": SHOT_H})
        page.goto(url)
        page.wait_for_function("window.__padReady === true", timeout=60000)
        time.sleep(3)
        dlg = page.locator(".mb-dlg-menu")
        (dlg.first if dlg.count() else page).screenshot(path=out)
        browser.close()


def _edge_shot(url, out, scratch):
    import subprocess
    edge = None
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.isfile(p):
            edge = p
            break
    if edge is None:
        raise SystemExit("no playwright and no Edge: nothing to photograph with")
    prof = os.path.join(scratch, "edge")
    os.makedirs(prof, exist_ok=True)
    # NO --virtual-time-budget: this page holds a websocket open, so virtual
    # time never runs out and the browser never exits.  Plain --screenshot
    # fires on the load event, which the page reaches with the modal already
    # up (it is opened over the API before the browser starts).
    subprocess.run([edge, "--headless=new", "--disable-gpu",
                    "--user-data-dir=" + prof,
                    "--window-size=%d,%d" % (SHOT_W, SHOT_H),
                    "--screenshot=" + out, url],
                   check=True, timeout=120)


def main():
    out = os.path.abspath(sys.argv[1])
    scratch = tempfile.mkdtemp(prefix="pad190b-")
    cards = os.path.join(scratch, "pinball_spike2_multiboot", "cards")
    os.makedirs(cards)
    card = os.path.join(cards, "SanDisk_SD_Card-32G.multi.raw")
    with open(card, "wb") as f:
        f.write(bytes(16))
    sys.path.insert(0, REPO)
    from pinball_decryptor.webui.multiboot_core import loaded_media_dir
    media = loaded_media_dir(card)
    os.makedirs(media, exist_ok=True)
    devs = ["/dev/mmcblk0p3"] + ["/dev/mmcblk0p3:img%d" % i for i in range(1, 6)]
    images = [{"index": i, "device": d, "title": t, "subtitle": s, "art": None,
               "anim": None, "music": None, "art_source": "none",
               "anim_source": "none", "source": None, "source_exists": False,
               "title_dir": "beatles_le", "bypass": None, "version": "1.09.0"}
              for i, (d, (t, s)) in enumerate(zip(devs, TITLES))]
    report = {
        "card": card, "size": 31914983424, "layout": "store",
        "images": images, "timeout": 30, "default": 0, "volume": 35,
        "mixer_volume": None, "sound_move": "synth", "sound_confirm": "none",
        "heading": "The Beatles", "media": [], "has_media_json": True,
        "has_build_json": True,
        "selector": {"bytes": 41272, "version": "codeselect 1.0"},
        "warnings": []}
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump([report, card, media], f)
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "spec": spec})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "multiboot")
        time.sleep(4)
        webui_shot.api(url, "multiboot.menu_settings")
        st = webui_shot.state(url)["multiboot"]
        print("dialog:", st.get("dlg"), flush=True)
        shoot(url, out, scratch)
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
