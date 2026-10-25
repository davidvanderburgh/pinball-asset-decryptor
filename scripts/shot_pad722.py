"""PAD-722 proof shots: a James Bond PRO 1.06 blocks mode made as the LE's mini-wizards are.

    python scripts/shot_pad722.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project (a Bond Pro 1.06 card)
holds FRWL WIZARD: started when From Russia With Love is done, its name in the game's status bar, SUPER JACKPOT on its
info line. Before PAD-722 the Pro's port had neither the film events nor the status bar (the LE's had both), so the
page flags the start and offers no bar. Shot:
  <before|after>_blocks_bond_pro.png its blocks page
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
CARD = MP.ProjectCard(r"C:\fake\james_bond_pro-1_06_0.Release.16G.sdcard.raw", "james_bond_pro", "1.06.0", "test")
tab.ModesTab._title_card = lambda self, project: (CARD, "project")
tab.ModesTab.title_read = lambda self, card: ("none", None)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import block_modes as BM
slug, _c = BM.new_blocks_mode(%(project)r, "FRWL WIZARD")
BM.save(%(project)r, slug, BM.normalize({"name": "FRWL WIZARD", "seconds": 40, "vars": [], "screen": True,
    "screen_style": "words", "bar": {"on": True, "color": "#2060ff"},
    "info": {"on": True, "text": "SUPER JACKPOT", "value": {"k": "num", "v": 5000000}},
    "scripts": [
    {"hat": {"kind": "event", "event": "film_frwl", "when": "idle"}, "do": [{"op": "start_mode"}]},
    {"hat": {"kind": "shot", "shot": "Right ramp exit opto", "when": "running"},
     "do": [{"op": "score", "points": {"k": "num", "v": 5000000}}]}]}))
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad722-")
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
            rows = page.get_by_text("FRWL WIZARD", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            print("bar row", page.get_by_text("in the game's bar").count(), flush=True)
            print("not reported", page.get_by_text("does not report").count(), flush=True)
            page.screenshot(path=os.path.join(outdir, "%s_blocks_bond_pro.png" % which))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
