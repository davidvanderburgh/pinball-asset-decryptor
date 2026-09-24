"""PAD-209 proof shot: the Images tab's Original pane after Emulate's Start
applied a pick to the project folder.

    python scripts/shot_pad209.py <out_dir> <prefix> <original.png> <pick.png>

Writes <out_dir>/<prefix>_images_preview.png.  A scratch Stern project holding
one scene picture (<original.png>) with <pick.png> assigned to it (Keep size
on).  The row is selected, then the Emulate tab's own staging step
(``EmulateTab._stage_pending`` -> ``App.stage_pending_replacements``, what
Start does before a run) is called through a one-off rpc the launcher below
adds, and the page goes to the Emulate tab and back, as the user did.
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402

REL = "images/scene_textures/radimg_Shape_1360x768_2c78815f.png"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui.rpc import rpc
from pinball_decryptor.webui.tabs import emulate


@rpc(loop=False)
def pad209_stage(self, assets):
    return self._stage_pending(assets)


emulate.EmulateTab.pad209_stage = pad209_stage
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _make_project(project, original, pick):
    from PIL import Image
    tex = os.path.join(project, "images", "scene_textures")
    os.makedirs(tex)
    Image.open(original).save(os.path.join(project, *REL.split("/")))
    with open(os.path.join(tex, "radium_images.txt"), "w",
              encoding="utf-8") as f:
        f.write("scene_textures/%s\t/godzilla_le/assets/lcd/auto_loaded/"
                "cac32730af42b9d26d26c4bb6e667b07da53113e/scene.radium\t"
                "100\t10\t1360\t768\t5\n" % os.path.basename(REL))
    from pinball_decryptor.core import checksums, staged_changes
    checksums.generate_checksums(project)
    staged_changes.save(project, {"image": {REL: pick},
                                  "image_keep_size": [REL]})


def main():
    out_dir = os.path.abspath(sys.argv[1])
    prefix = sys.argv[2]
    original, pick = os.path.abspath(sys.argv[3]), os.path.abspath(sys.argv[4])
    scratch = tempfile.mkdtemp(prefix="pad209-")
    project = os.path.join(scratch, "Heisei 1.93 Extracted")
    _make_project(project, original, pick)
    launcher = os.path.join(scratch, "launch209.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % REPO)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1560, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "images")
            webui_shot.api(url, "images.scan")
            time.sleep(4)
            webui_shot.api(url, "images.select", REL)
            time.sleep(2)
            print("staged", webui_shot.api(url, "emulate.pad209_stage",
                                           project), flush=True)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "images")
            time.sleep(4)
            out = os.path.join(out_dir, "%s_images_preview.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
