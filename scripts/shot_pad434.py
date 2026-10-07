"""PAD-434 proof shots: the Modes tab after a card is saved into a project it already showed bare.

    python scripts/shot_pad434.py <out.png> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The
project is a scratch folder with no card. The Modes tab is shown (it says the project names
no card), then the Extract tab, while the project's anchor is saved naming James Bond 007
LE 1.06 (as Select card + Project > Save do), then the Modes tab again, and the shot is
taken. Before PAD-434 the tab still says "This project names no card"; after, it shows the
Bond build.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SAVE = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import project_file
project_file.save(project_file.anchor_path(%(project)r), manufacturer_key="stern",
                  paths={"extract_input": %(card)r}, extract_options={})
'''

CARD = r"C:\fake\james_bond_le-1_06_0.Release.16G.sdcard.raw"


def main():
    out = os.path.abspath(sys.argv[1])
    repo = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else HERE
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad434-")
    project = os.path.join(scratch, "jbo")
    os.makedirs(project)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo})
    save = os.path.join(scratch, "save.py")
    with open(save, "w", encoding="utf-8") as f:
        f.write(SAVE % {"repo": repo, "project": project, "card": CARD})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", repo, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(3)
        webui_shot.api(url, "ui.select_tab", "extract")
        subprocess.run([sys.executable, save], check=True)
        time.sleep(1)
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(3)
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
