"""PAD-1544 proof shots: Edit image... on the second image of a two-image
Godzilla card, before and after Replace image... put a newer build in it.

    python scripts/shot_pad1544.py <out-dir> <prefix>

writes <prefix>_edit_image.png (the dialog as it opens) and, where the build
has the button, <prefix>_edit_image_replaced.png (the newer build picked: the
file's name moved, the title, picture choice, ticks and sounds did not).
Scratch settings, fake .raw files, no WSL (the shot_pad1196.py rig).
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
PLAIN, NEWER = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad1544_done", False):
        self._pad1544_done = True
        for p in PLAIN:
            self.add_image(p)
        self._rows[0].title, self._rows[0].subtitle = "Godzilla", "by Stern"
        row = self._rows[1]
        row.title, row.subtitle = "Heisei", "Kaiju Edition"
        row.own_scores = "heisei"
        row.version = "1.16.0"
        self._refresh_tree()
        # the page's Replace image... opens a native file picker; the shot
        # answers it with the newer build
        fd = getattr(mp, "_FILEDIALOG", None)
        if fd is not None:
            class _Pick:
                def __getattr__(self, name):
                    return lambda *a, **k: NEWER
            type(fd).target = _Pick()
    return _orig(self, *a, **k)
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def _raw(folder, name):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(bytes(16))
    return path


def main():
    out_dir, prefix = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1544-")
    imgs = os.path.join(scratch, "images")
    plain = [_raw(imgs, "godzilla_le-1_16_0.Release.8G.sdcard.raw"),
             _raw(imgs, "Godzilla Premium 1.16 Heisei Custom V2.3 Kaiju Edition.raw")]
    newer = _raw(imgs, "Godzilla Premium 1.16 Heisei Custom V2.4 Kaiju Edition.raw")
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump([plain, newer], f)
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
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            webui_shot.api(url, "multiboot.edit", 1)
            time.sleep(3)
            out = os.path.join(out_dir, "%s_edit_image.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            button = page.get_by_role("button", name="Replace image")
            if button.count():
                button.first.click()
                time.sleep(3)
                out = os.path.join(out_dir, "%s_edit_image_replaced.png" % prefix)
                page.screenshot(path=out)
                print("shot", out, flush=True)
                webui_shot.api(url, "multiboot.edit_ok")
                time.sleep(2)
                out = os.path.join(out_dir, "%s_table_replaced.png" % prefix)
                page.screenshot(path=out)
                print("shot", out, flush=True)
            else:
                webui_shot.api(url, "multiboot.edit_cancel")
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
