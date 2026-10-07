"""PAD-436 proof shots: the Modes tab on James Bond 007 LE 1.06, a mode that is the game's own mini-wizard.

    python scripts/shot_pad436.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder. The project holds two modes:
FRWL WIZARD, started when From Russia With Love is done (where the tree has PAD-436: handing the player the game's
Ahoy Mr. Bond, started at once), and YOLT MODE, a mode of its own started when You Only Live Twice is done. Shots:
  <before|after>_modes_mini_wizard.png     FRWL WIZARD's Mode page
  <before|after>_modes_wizard_section.png  YOLT MODE's Mode page scrolled to its end, the mini-wizard list opened out
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
p = MP.profile("james_bond_le_1_06")
spec = MP.blank_spec(p, "FRWL WIZARD")
spec.seconds, spec.award = 45, 2000000
spec.starts_on, spec.starts = "event film_frwl", "once_per_game"
if hasattr(spec, "game_wizard"):
    spec.game_wizard, spec.wizard_how = "Ahoy Mr. Bond", "start"
MP.save(%(project)r, "1_frwl_wizard", spec)
spec = MP.blank_spec(p, "YOLT MODE")
spec.seconds, spec.award = 45, 2000000
spec.starts_on, spec.starts = "event film_yolt", "once_per_game"
MP.save(%(project)r, "2_yolt_mode", spec)
'''


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad436-")
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
            page.evaluate("() => localStorage.setItem('pad.modes.page', 'mode')")
            time.sleep(2)

            def open_mode(name):
                rows = page.get_by_text(name, exact=True)
                if rows.count():
                    rows.first.click()
                    time.sleep(2.5)

            open_mode("FRWL WIZARD")
            page.screenshot(path=os.path.join(outdir, "%s_modes_mini_wizard.png" % which))
            open_mode("YOLT MODE")
            n = page.evaluate("""() => {
                const bd = document.querySelector('.modes-editor-bd');
                if (bd) bd.scrollTop = 1e6;
                for (const s of document.querySelectorAll('select')) {
                    const labels = [...s.options].map(o => o.textContent);
                    if (labels.includes('(nothing: this mode runs)') && !s.disabled) {
                        s.size = s.options.length;
                        s.style.height = 'auto';
                        s.closest('.field').style.height = 'auto';
                        s.closest('.field').style.overflow = 'visible';
                        s.scrollIntoView({block: 'center'});
                        return s.options.length;
                    }
                }
                return 0;
            }""")
            print("wizard choices", n, flush=True)
            time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "%s_modes_wizard_section.png" % which))
            browser.close()
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
