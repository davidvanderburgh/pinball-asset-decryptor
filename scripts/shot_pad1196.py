"""PAD-1196 proof shots: pb_lawww's six-image Godzilla card - two Original images
(3 and 5 ball) sharing high-score table 'original', four Heisei images sharing table
'heisei', the two orchestral 3-ball images sharing one settings store - in the
Multi-boot tab, and Edit image... open on 'Heisei b/w, orchestral, 3 ball'.

    python scripts/shot_pad1196.py <out-dir> <prefix>

writes <prefix>_table.png and <prefix>_edit_image.png.  Before PAD-1196 the box has two
ticks and no way to say WHICH images share; after it, each tick has a 'Share with'
choice.  Scratch settings, fake .raw files, no WSL (the shot_pad239.py rig).
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
PLAIN, PRE = json.load(open(%(spec)r))
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    if not getattr(self, "_pad1196_done", False):
        self._pad1196_done = True
        for p in PLAIN:
            self.add_image(p)
        # pb_lawww's card: Original keeps its own table; the two Heisei images
        for ri, ent in enumerate(PRE):
            title, own = ent[0], ent[1]
            row = self._rows[ri]
            row.title = title
            if own:
                row.own_scores = own
            for key, val in (PRE[ri][2] if len(PRE[ri]) > 2 else {}).items():
                setattr(row, key, val)
        self._refresh_tree()
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
    scratch = tempfile.mkdtemp(prefix="pad1196-")
    imgs = os.path.join(scratch, "images")
    names = ["Original - 3 ball", "Original - 5 ball",
             "Heisei color, original sound, 3 ball", "Heisei color, orchestral, 3 ball",
             "Heisei b/w, orchestral, 3 ball", "Heisei color, orchestral, 5 ball"]
    plain = [_raw(imgs, "godzilla_le-1_16_0.v%d.8G.sdcard.raw" % n) for n in range(len(names))]
    stores = ["original-3-ball", "original-5-ball", "heisei-color-original-3",
              "heisei-orchestral-3", "heisei-orchestral-3", "heisei-orchestral-5"]
    tables = ["original", "original", "heisei", "heisei", "heisei", "heisei"]
    pre = [[t, s, {"hiscores": h}] for t, s, h in zip(names, stores, tables)]
    spec = os.path.join(scratch, "spec.json")
    with open(spec, "w", encoding="utf-8") as f:
        json.dump([plain, pre], f)
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
            for row, name in ((4, "edit_image"),):
                webui_shot.api(url, "multiboot.edit", row)
                time.sleep(3)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
                if name == "edit_image":
                    out2 = os.path.join(out_dir, "%s_table.png" % prefix)
                    webui_shot.api(url, "multiboot.edit_cancel"); time.sleep(1)
                    page.screenshot(path=out2); print("shot", out2, flush=True)
                    webui_shot.api(url, "multiboot.edit", row); time.sleep(3)
                page.screenshot(path=out)
                print("shot", out, flush=True)
                webui_shot.api(url, "multiboot.edit_cancel")
                time.sleep(1)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
