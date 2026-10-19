"""PAD-612 proof shots: RAMP FRENZY (tools/mode_views/showcase.py) in the Modes tab's view tabs.

    python scripts/shot_pad612.py <out dir> [<repo>] [--card <card image>]

The server runs from <repo> (default: this tree) against a scratch settings folder and a Godzilla Pro 1.15 project
holding the one blocks mode, bound to a real Godzilla Pro 1.15 card (read only: the Playfield tab reads its
playfield picture off it). Shots:
  blocks.png       the mode's pane on its Blocks tab (the tab strip and the shared Undo/Redo at its top)
  playfield.png    the Playfield tab with the Right ramp picked (only where the tree has one)
  playfield_undo.png  after a Score block was added on the Playfield and undone from the Blocks tab
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

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"

HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.webui.tabs import modes as tab
CARD = MP.ProjectCard(%(card)r, "godzilla_pro", "1.15.0", "test")
tab.ModesTab._title_card = lambda self, project: (CARD, "project")
tab.ModesTab.title_read = lambda self, card: ("none", None)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
sys.path.insert(0, %(views)r)
import showcase
from pinball_decryptor.plugins.stern import block_modes as BM
slug, _c = BM.new_blocks_mode(%(project)r, "RAMP FRENZY")
BM.save(%(project)r, slug, showcase.program())
print(BM.blocks_path(%(project)r, slug))
'''


def main():
    args = sys.argv[1:]
    card = CARD
    if "--card" in args:
        i = args.index("--card")
        card = args[i + 1]
        del args[i:i + 2]
    outdir = os.path.abspath(args[0])
    repo = os.path.abspath(args[1]) if len(args) > 1 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad612-")
    project = os.path.join(scratch, "godzilla project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "views": os.path.join(HERE, "tools", "mode_views")})
    blocks_json = subprocess.run([sys.executable, seed], check=True, capture_output=True, text=True).stdout.strip()
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "card": card})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
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
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("RAMP FRENZY", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            pane = page.locator(".bk-pane").first
            pane.evaluate("(el) => el.scrollIntoView({block: 'start'})")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "blocks.png"))
            tab = page.get_by_role("tab", name="Playfield")
            if not tab.count():
                print("no Playfield tab in", repo, flush=True)
                browser.close()
                return
            tab.first.click()
            page.wait_for_selector(".pf-art, .pf-none", timeout=60000)
            time.sleep(1.5)
            ramp = page.locator(".pf-shot", has_text="Right ramp")
            if ramp.count():
                ramp.first.click()
                time.sleep(1)
            pane.evaluate("(el) => el.scrollIntoView({block: 'start'})")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "playfield.png"))
            n = page.locator(".pf-card .bk-script").count()
            print("Right ramp rules on its card:", n, flush=True)
            # one history: a rule added here, undone from the Blocks tab
            page.locator(".pf-card .pf-group", has_text="While it runs").locator("button", has_text="Add a rule").first.click()
            time.sleep(1)
            print("after adding:", page.locator(".pf-card .bk-script").count(), flush=True)
            page.get_by_role("tab", name="Blocks").first.click()
            time.sleep(1)
            page.locator("button", has_text="Undo").first.click()
            time.sleep(1)
            page.get_by_role("tab", name="Playfield").first.click()
            page.wait_for_selector(".pf-art, .pf-none", timeout=60000)
            time.sleep(1)
            print("after Undo on the Blocks tab:", page.locator(".pf-card .bk-script").count(), flush=True)
            with open(blocks_json, encoding="utf-8") as f:
                print("blocks.json scripts:", len(json.load(f).get("scripts", [])), flush=True)
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
