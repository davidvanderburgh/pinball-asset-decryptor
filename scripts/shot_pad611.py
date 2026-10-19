"""PAD-611 proof shots: RAMP FRENZY (tools/mode_views/showcase.py) in the Modes tab's blocks, and in each alternative view.

    python scripts/shot_pad611.py <out dir> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder and a Godzilla Pro 1.15 project
holding the one blocks mode. Shots:
  blocks.png           the mode's blocks as the tab shows them today (the page scrolled to its scripts)
  <view>.png           the same mode in each alternative (tools/mode_views/render_views.py), drawn from its blocks.json
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
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.webui.tabs import modes as tab
CARD = MP.ProjectCard(r"C:\fake\godzilla_pro-1_15_0.Release.8G.sdcard.raw", "godzilla_pro", "1.15.0", "test")
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
    outdir = os.path.abspath(sys.argv[1])
    repo = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad611-")
    project = os.path.join(scratch, "godzilla project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "views": os.path.join(HERE, "tools", "mode_views")})
    blocks_json = subprocess.run([sys.executable, seed], check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run([sys.executable, os.path.join(HERE, "tools", "mode_views", "render_views.py"), outdir, blocks_json],
                   check=True)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo})
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
            page = browser.new_page(viewport={"width": 1440, "height": 1500})
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
            scripts = page.locator(".bk-script")
            print("scripts on the page:", scripts.count(), flush=True)
            if scripts.count():
                scripts.first.evaluate("(el) => el.scrollIntoView({block: 'start'})")
                page.evaluate("() => window.scrollBy(0, -120)")
                time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "blocks.png"))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
