"""PAD-1386 proof shot: what the Multi-boot tab says about a loaded card whose image 1 was
swapped for a newer build.

    python scripts/shot_pad1386.py <out-dir> <name> <primary card> <old image 1> <new image 1>

The tab is put in editing mode on a stand-in card file in a scratch project (its
record present, as a card built by this app carries), with image 1 changed from
<old image 1> to <new image 1>; the shot is the card row's sentence.  Before
PAD-1386 it said only a fresh card could carry the change; after, it names the
in-place update.  No tool runs: the size/dry-run measure is stubbed out.

Adapted from shot_pad1385.py.
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
import sys, threading
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import multiboot_panel as mp
from pinball_decryptor.webui import host
_orig = mp.WebMultibootPanel.on_shown
def on_shown(self, *a, **k):
    r = _orig(self, *a, **k)
    if not getattr(self, "_pad1386_done", False):
        self._pad1386_done = True
        def add():
            import copy, os
            self._maybe_plan = lambda *a, **k: None
            self.add_image(%(primary)r)
            self.add_image(%(new)r)
            card = os.path.join(%(project)r, "multi", "Godzilla Heisei multi.multi.raw")
            os.makedirs(os.path.dirname(card), exist_ok=True)
            open(card, "wb").close()
            self._out_var.set(card)
            form = self.form()
            old = copy.deepcopy(form)
            old.images[1].path = %(old)r
            self._loaded_card = card
            self._loaded_form = old
            self._loaded_trees = {"free": 4 * 2**30, "dirty": [], "synced": [], "changed": {}}
            self._update_edit_status()
            for k, label, state, detail in self.checks():
                print("PAD1386 check:", k, state, detail, flush=True)
        threading.Timer(1.5, add).start()
    return r
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def shoot(out_dir, name, primary, old, new, wait):
    scratch = tempfile.mkdtemp(prefix="pad1386-")
    project = os.path.join(scratch, "Godzilla Heisei multi")
    os.makedirs(project)
    sys.path.insert(0, REPO)
    from pinball_decryptor.core import project_file
    project_file._write_maybe_hidden(project_file.anchor_path(project),
                                     {"manufacturer": "stern"})
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "primary": primary, "old": old, "new": new, "project": project})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"write_assets": project,
                                               "extract_output": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python")})
    print("repo", REPO, "url", url, "project", project, flush=True)
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
            time.sleep(wait)
            box = page.input_value("#mb-card") if page.query_selector("#mb-card") else "?"
            print("card box in page:", box, flush=True)
            out = os.path.join(out_dir, "%s.png" % name)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    out_dir, name, primary, old, new = os.path.abspath(sys.argv[1]), *sys.argv[2:6]
    os.makedirs(out_dir, exist_ok=True)
    shoot(out_dir, name, primary, old, new, float(os.environ.get("PAD1386_WAIT", "6")))


if __name__ == "__main__":
    main()
