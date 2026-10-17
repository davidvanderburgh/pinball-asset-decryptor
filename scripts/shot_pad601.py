"""PAD-601 proof shots: a Beatles 1.29 blocks mode lighting RINGO SPINNER in When the mode ends, as the owner made it.

    python scripts/shot_pad601.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds RINGO HURRY
(the owner's: When the mode ends -> Write a line, Light RINGO SPINNER yellow blinking). The Light block's pattern list
is shown opened (the select drawn as a list, as a click opens it): before it has no way to light an insert off.
  <before|after>_blocks_light_off.png its blocks, the Light block's patterns listed
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
from shot_pad600 import HOST  # noqa: E402

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import block_modes as BM
project = %(project)r
slug, _c = BM.new_blocks_mode(project, "RINGO HURRY")
BM.save(project, slug, BM.normalize({"name": "RINGO HURRY", "seconds": 30, "vars": [], "scripts": [
    {"hat": {"kind": "mode_end"}, "do": [
        {"op": "log", "text": "the mode ended"},
        {"op": "light_shot", "insert": "RINGO SPINNER", "color": "#ffd000", "pattern": "blink", "rate": None}]}]}))
print(slug)
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad601-")
    project = os.path.join(scratch, "beatles project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project})
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
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("RINGO HURRY", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            # the Light block's pattern select, drawn open as a list
            n = page.evaluate("""() => {
                const sel = [...document.querySelectorAll('.bk-script select')]
                    .find((s) => [...s.options].some((o) => o.value === 'pulse'));
                if (!sel) return 0;
                sel.size = sel.options.length;
                sel.style.height = 'auto';
                sel.parentElement.style.height = 'auto';
                sel.parentElement.style.overflow = 'visible';
                sel.parentElement.style.zIndex = '5';
                sel.parentElement.style.outline = '2px solid #e02020';
                return sel.options.length;
            }""")
            print("pattern options", n, flush=True)
            scripts = page.locator(".bk-script")
            if scripts.count():
                scripts.last.evaluate("(el) => el.scrollIntoView({block: 'start'})")
                page.evaluate("() => window.scrollBy(0, -200)")
                time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "%s_blocks_light_off.png" % which))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
