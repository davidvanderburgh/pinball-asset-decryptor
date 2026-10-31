"""PAD-889 proof shots: James Bond LE 1.06's Bond Women multiplier as a value in a blocks mode.

    python scripts/shot_pad889.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds YOLT WIZARD, a
blocks mode as the owner makes theirs: a Right ramp scoring, then its words showing the Bond Women multiplier. Run
against main for "before" (no such value: the Words block's value slot comes back empty) and this tree for "after".
Shot: <before|after>_blocks_women_mult.png - the blocks page, its palette's values and the script.
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
    "scripts": [
    {"hat": {"kind": "shot", "shot": "Right ramp exit opto", "when": "running"},
     "do": [{"op": "score", "points": {"k": "num", "v": 5000000}},
            {"op": "words", "text": "BOND WOMEN X", "value": {"k": "women_mult"}}]}]}))
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    screen = "blocks_women_mult"
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad889-")
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
            page = browser.new_page(viewport={"width": 1440, "height": 1700})
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
            print("value pieces", page.get_by_text("the Bond Women multiplier").count(), flush=True)
            # the palette's values (the last of them, the player up, is there before and after) and the script's
            # Words block, scrolled into view in their own panes
            for loc in (page.get_by_text("the player up", exact=True), page.locator('input[value="BOND WOMEN X"]')):
                if loc.count():
                    loc.last.scroll_into_view_if_needed()
                    time.sleep(0.5)
            time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "%s_%s.png" % (which, screen)))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
