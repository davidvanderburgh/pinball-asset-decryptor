"""PAD-342 proof shot: the Multi-boot tab on a Barrels of Fun project.

    python scripts/shot_pad342.py <out-dir> <name> [<image.fun> ...]

writes <out-dir>/<name>.png: the app on a BOF project with the Multi-boot tab
asked for.  Before PAD-342 a BOF project has no Multi-boot tab, so the shot is
the tab bar without one; after it, the tab holds the .fun files named on the
command line (stock Labyrinth and a mod, say) and the menu preview.  The server
runs from THIS tree against a scratch settings folder.  PAD342_RANDOM=1 also adds
a random card over the builds, on a tree whose BOF backend has random cards.
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
IMAGES = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad342_done", False):
        self._pad342_done = True
        for p in IMAGES:
            self.add_image(p)
        # the random card over the builds, where the platform has one (the
        # sound + random half of PAD-342; before it a BOF update had neither)
        if %(random)r and self._backend.groups:
            self.add_random_over_existing()
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def shoot(out_dir, name, images, wait):
    scratch = tempfile.mkdtemp(prefix="pad342-")
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump(images, f)
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "spec": spec,
                        "random": os.environ.get("PAD342_RANDOM", "") == "1"})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "bof"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   # the preview and the size check run for real (WSL): the shot is the
                   # selector's own frame and the tool's own measurement
                   "PAD_UI_NO_RIG": os.environ.get("PAD342_NO_RIG", "0"),
                   "PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python")})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "bof")
        try:
            webui_shot.api(url, "ui.select_tab", "multiboot")
            print("multiboot tab selected", flush=True)
        except Exception as e:                      # the before code has no such tab
            print("no multiboot tab:", e, flush=True)
        time.sleep(4)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(wait)
            out = os.path.join(out_dir, "%s.png" % name)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    out_dir, name = os.path.abspath(sys.argv[1]), sys.argv[2]
    images = [os.path.abspath(p) for p in sys.argv[3:]]
    os.makedirs(out_dir, exist_ok=True)
    shoot(out_dir, name, images, float(os.environ.get("PAD342_WAIT", "3")))


if __name__ == "__main__":
    main()
