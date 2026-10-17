"""PAD-598 proof shots: a Beatles 1.29 blocks mode, its insert lit as it starts.

    python scripts/shot_pad598.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds FAB FOUR, a
blocks mode as the owner made it: Target 4 lights the mode at Target 4 with RINGO SPINNER pulsing, and When
the mode starts lights ... before: a shot (FAB drop A, all its Light block could pick); after: the RINGO SPINNER
insert itself. Shots:
  <before|after>_blocks_mode_start.png  the mode's blocks, the When the mode starts script at the top
  <before|after>_light_pick.png         the same, its Light block's list opened out: what it can light
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
start = %(start)r
slug, _c = BM.new_blocks_mode(%(project)r, "FAB FOUR")
BM.save(%(project)r, slug, BM.normalize({"name": "FAB FOUR", "seconds": 30, "vars": [], "scripts": [
    {"hat": {"kind": "mode_start"}, "do": [start]},
    {"hat": {"kind": "shot", "shot": "Target 4", "when": "any"},
     "do": [{"op": "light_mode", "shot": "Target 4", "insert": "RINGO SPINNER", "color": "#40c040",
             "pattern": "pulse"}]}]}))
'''

START = {"before": {"op": "light_shot", "shot": "FAB drop A", "color": "#ffd000", "pattern": "blink", "rate": None},
         "after": {"op": "light_shot", "insert": "RINGO SPINNER", "color": "#ff2000", "pattern": "solid", "rate": None}}


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad598-")
    project = os.path.join(scratch, "beatles project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "start": START[which]})
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
            rows = page.get_by_text("FAB FOUR", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.locator("text=/^Hide log/")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            scripts = page.locator(".bk-script")
            print("scripts", scripts.count(), flush=True)
            if scripts.count():
                scripts.first.evaluate("(el) => el.scrollIntoView({block: 'center'})")
                time.sleep(0.5)
            word = page.locator(".bk-script .bk-w", has_text="Light").first
            word.hover()
            time.sleep(1.5)
            page.screenshot(path=os.path.join(outdir, "%s_blocks_mode_start.png" % which))
            page.mouse.move(5, 5)
            time.sleep(0.5)
            # the Light block's own list, opened out in place (a native drop-down does not show in a screenshot)
            n = page.evaluate("""() => {
                const w = [...document.querySelectorAll('.bk-script .bk-w')].find((e) => e.textContent.trim() === 'Light');
                const sel = w && w.parentElement.querySelector('select');
                if (!sel) return -1;
                sel.size = 22;
                sel.style.height = 'auto';
                // the list scrolled to where the shots end: what comes after them, if anything
                const rows = sel.options.length + sel.querySelectorAll('optgroup').length;
                const row = sel.scrollHeight / Math.max(1, rows);
                sel.scrollTop = Math.max(0, (sel.querySelectorAll('optgroup')[0] ? 36 - 12 : 36 - 20) * row);
                let f = sel.closest('.field'); if (f) { f.style.height = 'auto'; f.style.width = '260px'; }
                return sel.options.length;
            }""")
            print("options", n, flush=True)
            time.sleep(0.8)
            page.screenshot(path=os.path.join(outdir, "%s_light_pick.png" % which))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
