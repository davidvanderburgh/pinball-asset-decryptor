"""PAD-457 proof shots: what the Modes tab says a James Bond LE 1.06 mini-wizard hand-over does.

    python scripts/shot_pad457.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds FRWL WIZARD
(From Russia With Love done -> the game's Ahoy Mr. Bond, started at once) and FILM WIZARDS, a blocks mode handing
over Ahoy Mr. Bond on that film. Shots:
  <before|after>_modes_handover_note.png FRWL WIZARD's Mode page, the note under the mini-wizard it hands out
  <before|after>_modes_start_tip.png   FRWL WIZARD's Mode page, the pointer on "Start it at once" (its tooltip)
  <before|after>_blocks_wizard_tip.png FILM WIZARDS' blocks, the pointer on the game's mini-wizard block
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
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import block_modes as BM
p = MP.profile("james_bond_le_1_06")
spec = MP.blank_spec(p, "FRWL WIZARD")
spec.starts_on, spec.starts = "event film_frwl", "once_per_game"
spec.game_wizard, spec.wizard_how = "Ahoy Mr. Bond", "start"
MP.save(%(project)r, "1_frwl_wizard", spec)
slug, _c = BM.new_blocks_mode(%(project)r, "FILM WIZARDS")
BM.save(%(project)r, slug, BM.normalize({"name": "FILM WIZARDS", "seconds": 30, "vars": [], "scripts": [
    {"hat": {"kind": "event", "event": "film_frwl"},
     "do": [{"op": "game_wizard", "name": "Ahoy Mr. Bond", "how": "start"}]}]}))
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad457-")
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
            page = browser.new_page(viewport={"width": 1440, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.page', 'mode');"
                          " localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)

            def open_mode(name):
                rows = page.get_by_text(name, exact=True)
                if rows.count():
                    rows.first.click()
                    time.sleep(2.5)

            open_mode("FRWL WIZARD")
            page.mouse.move(5, 5)
            time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "%s_modes_handover_note.png" % which))
            radio = page.get_by_text("Start it at once", exact=True)
            radio.first.scroll_into_view_if_needed()
            radio.first.hover()
            time.sleep(1.5)
            page.screenshot(path=os.path.join(outdir, "%s_modes_start_tip.png" % which))
            page.mouse.move(5, 5)
            open_mode("FILM WIZARDS")
            block = page.get_by_text("the game's mini-wizard", exact=True)
            print("wizard blocks", block.count(), flush=True)
            if block.count():
                block.first.scroll_into_view_if_needed()
                block.first.hover()
                time.sleep(1.5)
            page.screenshot(path=os.path.join(outdir, "%s_blocks_wizard_tip.png" % which))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
