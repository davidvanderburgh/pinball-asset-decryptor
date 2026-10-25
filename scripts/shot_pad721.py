"""PAD-721 proof shots: a James Bond LE 1.06 blocks mode's status bar filling as shots are made.

    python scripts/shot_pad721.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds YOLT WIZARD, a
blocks mode as the owner makes their mini-wizards: its name in the game's bar, a Right ramp scoring. It is seeded with
the bar filling with the shots scored out of 12; the code before PAD-721 has no such setting (its blocks.json loses
it), so its page shows the bar's clock alone. Shot:
  <before|after>_blocks_bar_fill.png the top of its blocks page: the bar's settings
"""

import json
import os
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
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.webui.tabs import modes as tab
CARD = MP.ProjectCard(r"C:\fake\james_bond_le-1_06_0.Release.16G.sdcard.raw", "james_bond_le", "1.06.0", "test")
tab.ModesTab._title_card = lambda self, project: (CARD, "project")
tab.ModesTab.title_read = lambda self, card: ("none", None)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import block_modes as BM
slug, _c = BM.new_blocks_mode(%(project)r, "YOLT WIZARD")
BM.save(%(project)r, slug, BM.normalize({"name": "YOLT WIZARD", "seconds": 60, "vars": [],
    "bar": {"on": True, "color": "#ff2020", "fill": "value", "value": {"k": "scored"}, "of": {"k": "num", "v": 12}},
    "scripts": [
    {"hat": {"kind": "shot", "shot": "Right ramp exit opto", "when": "running"},
     "do": [{"op": "score", "points": {"k": "num", "v": 5000000}}]}]}))
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad721-")
    project = os.path.join(scratch, "bond project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project})
    import subprocess
    subprocess.run([sys.executable, seed], check=True)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo})
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
        time.sleep(4)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("YOLT WIZARD", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            print("fill row", page.get_by_text("The bar fills with").count(), flush=True)
            with open(os.path.join(project, "modes", "yolt_wizard", "blocks.json"), encoding="utf-8") as f:
                print("bar", json.load(f).get("bar"), flush=True)
            page.screenshot(path=os.path.join(outdir, "%s_blocks_bar_fill.png" % which))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
