"""PAD-1385 proof shot: where a new multi-boot card goes by default.

    python scripts/shot_pad1385.py <out-dir> <name> <primary card>

writes <out-dir>/<name>.png: the app on a scratch Stern PROJECT ("Godzilla Heisei
multi", an empty folder with its own anchor), Multi-boot tab, with <primary card>
added as the first image - so the "Multi-boot card image" box shows the default
this tree's code picks for it.  Before PAD-1385 that was beside the primary image
(every project starting from it got the same file); after, it is inside the
project.  Nothing is read from or written to the card; the scratch folder is left
behind in %TEMP% (pad1385-*) for a look and can be deleted.
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
    if not getattr(self, "_pad1385_done", False):
        self._pad1385_done = True
        def add():
            self.add_image(%(primary)r)
            print("PAD1385 card box:", self._out_var.get(), flush=True)
        threading.Timer(1.5, add).start()
    return r
mp.WebMultibootPanel.on_shown = on_shown
sys.exit(host.main(sys.argv[1:]))
'''


def shoot(out_dir, name, primary, wait):
    scratch = tempfile.mkdtemp(prefix="pad1385-")
    project = os.path.join(scratch, "Godzilla Heisei multi")
    os.makedirs(project)
    sys.path.insert(0, REPO)
    from pinball_decryptor.core import project_file
    project_file._write_maybe_hidden(project_file.anchor_path(project),
                                     {"manufacturer": "stern"})
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO, "primary": primary})
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
    out_dir, name, primary = os.path.abspath(sys.argv[1]), sys.argv[2], sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    shoot(out_dir, name, primary, float(os.environ.get("PAD1385_WAIT", "4")))


if __name__ == "__main__":
    main()
