"""PAD-503 proof shots: a James Bond LE 1.06 blocks mode of the owner's own, for a film with no mini-wizard.

    python scripts/shot_pad503.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds DIAMOND DEATH
THREAT, a blocks mode as the owner made it: Diamonds Are Forever done -> before: Start the mode (all there was);
after: Light the mode at the Right ramp with the MR. HENDERSON insert (the game's own villain for that film). Shot:
  <before|after>_blocks_daf_wizard.png its blocks, the pointer on the block its film event runs
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
film = %(film)r
slug, _c = BM.new_blocks_mode(%(project)r, "DIAMOND DEATH THREAT")
BM.save(%(project)r, slug, BM.normalize({"name": "DIAMOND DEATH THREAT", "seconds": 30, "vars": [], "scripts": [
    {"hat": {"kind": "shot", "shot": "Side ramp enter opto", "when": "running"},
     "do": [{"op": "score", "points": {"k": "num", "v": 5000000}}, {"op": "add_time", "seconds": {"k": "num", "v": 5}}]},
    {"hat": {"kind": "event", "event": "film_daf", "when": "any"}, "do": [film]}]}))
'''

FILM = {"before": {"op": "start_mode"},
        "after": {"op": "light_mode", "shot": "Right ramp exit opto", "insert": "MR. HENDERSON", "color": "#ffd000",
                  "pattern": "blink"}}
WORDS = {"before": "Start the mode", "after": "Light the mode at"}


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad503-")
    project = os.path.join(scratch, "bond project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "film": FILM[which]})
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
            page = browser.new_page(viewport={"width": 1440, "height": 1500})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("DIAMOND DEATH THREAT", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            scripts = page.locator(".bk-script")
            if scripts.count():
                scripts.last.evaluate("(el) => el.scrollIntoView({block: 'center'})")
                time.sleep(0.5)
            block = page.locator(".bk-script .bk-w", has_text=WORDS[which])
            print("blocks", block.count(), flush=True)
            if block.count():
                block.last.hover()
                time.sleep(1.5)
            page.screenshot(path=os.path.join(outdir, "%s_blocks_daf_wizard.png" % which))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
