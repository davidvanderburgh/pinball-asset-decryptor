"""PAD-600 proof shots: a Beatles 1.29 blocks mode, qualified by three hits of Target 4, as the owner made it.

    python scripts/shot_pad600.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds TARGET 4 (the
owner's: hits of Target 4 = 3 -> Light the mode at Target 4 and the RINGO SPINNER insert) and TARGET 1 to 3 beside it.
before: the If holds only the light (no block could set the other targets' hits or put their lights out);
after: the same If also sets the hits of Target 1 to 3 to 0 and puts out the lights of TARGET 1 to 3. Shot:
  <before|after>_blocks_target4.png its blocks, the palette's Mode and Score and variables groups open
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
CARD = MP.ProjectCard(r"C:\fake\beatles-1_29_0.Release.16G.sdcard.raw", "beatles", "1.29.0", "test")
tab.ModesTab._title_card = lambda self, project: (CARD, "project")
tab.ModesTab.title_read = lambda self, card: ("none", None)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import block_modes as BM
project, after = %(project)r, %(after)r
num = lambda v: {"k": "num", "v": v}
for n in (1, 2, 3, 4):
    slug, _c = BM.new_blocks_mode(project, "TARGET %%d" %% n)
    then = [{"op": "light_mode", "shot": "Target %%d" %% n, "insert": "RINGO SPINNER" if n == 4 else "",
             "color": "#00c040", "pattern": "pulse"}]
    if n == 4 and after:
        then += [{"op": "set_hits", "shot": "Target %%d" %% t, "value": num(0)} for t in (1, 2, 3)]
        then += [{"op": "unlight_mode", "mode": "target_%%d" %% t} for t in (1, 2, 3)]
    BM.save(project, slug, BM.normalize({"name": "TARGET %%d" %% n, "seconds": 30, "vars": [], "scripts": [
        {"hat": {"kind": "shot", "shot": "Target %%d" %% n, "when": "idle"},
         "do": [{"op": "if", "cond": {"k": "cmp", "op": "=", "a": {"k": "hits", "shot": "Target %%d" %% n},
                                      "b": num(3)}, "then": then}]}]}))
    print(slug)
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad600-")
    project = os.path.join(scratch, "beatles project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "after": which == "after"})
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
            page = browser.new_page(viewport={"width": 1440, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("TARGET 4", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            scripts = page.locator(".bk-script")
            if scripts.count():
                scripts.last.evaluate("(el) => el.scrollIntoView({block: 'start'})")
                page.evaluate("() => window.scrollBy(0, -260)")
                time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "%s_blocks_target4.png" % which))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
