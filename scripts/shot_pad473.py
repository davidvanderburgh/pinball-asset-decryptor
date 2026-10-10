"""PAD-473 proof shots: the Modes tab's mini-wizard section on Spike 2 builds besides James Bond LE 1.06.

    python scripts/shot_pad473.py <out dir> <before|after> <screen>=<title key> [...] [--repo <repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder, once per screen: a project on
the title's card holding one mode of its own. Each shot is that mode's Mode page scrolled to its end, with the
mini-wizard list opened out where it can be used. E.g.

    python scripts/shot_pad473.py C:/tmp/shots after bondpro=james_bond_pro_1_06 kong=king_kong_le_0_97

<title key>@<mini-wizard name> saves the mode handing that one over (the list then stays closed, the page shows how
it is handed over).
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
CARD = MP.ProjectCard(r"C:\fake\%(card)s", %(game)r, %(version)r, "test")
tab.ModesTab._title_card = lambda self, project: (CARD, "project")
tab.ModesTab.title_read = lambda self, card: ("none", None)
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''

SEED = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.plugins.stern import mode_project as MP
p = MP.profile(%(title)r)
spec = MP.blank_spec(p, "MY MODE")
spec.seconds, spec.award = 45, 2000000
if %(wizard)r:
    spec.game_wizard, spec.wizard_how = %(wizard)r, "light"
MP.save(%(project)r, "1_my_mode", spec)
'''


def _card(title):
    """(card file name, game dir, version) of a profile key like ``james_bond_pro_1_06``."""
    parts = title.split("_")
    game, version = "_".join(parts[:-2]), "%s.%s" % (parts[-2], parts[-1])
    return "%s-%s_0.Release.16G.sdcard.raw" % (game, version.replace(".", "_")), game, version + ".0"


def shoot(outdir, which, screen, title, repo):
    scratch = tempfile.mkdtemp(prefix="pad473-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        title, _, wizard = title.partition("@")
        f.write(SEED % {"repo": repo, "project": project, "title": title, "wizard": wizard})
    subprocess.run([sys.executable, seed], check=True)
    card, game, version = _card(title)
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "card": card, "game": game, "version": version})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    webui_shot.REPO = repo
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print(screen, title, "repo", repo, "url", url, flush=True)
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
            rows = page.get_by_text("MY MODE", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            n = page.evaluate("""() => {
                const bd = document.querySelector('.modes-editor-bd');
                if (bd) bd.scrollTop = 1e6;
                for (const s of document.querySelectorAll('select')) {
                    const labels = [...s.options].map(o => o.textContent);
                    if (labels.includes('(nothing: this mode runs)')) {
                        if (!s.disabled && s.value === '(none)') {
                            s.size = s.options.length;
                            s.style.height = 'auto';
                            s.closest('.field').style.height = 'auto';
                            s.closest('.field').style.overflow = 'visible';
                        }
                        s.scrollIntoView({block: 'center'});
                        return s.disabled ? -s.options.length : s.options.length;
                    }
                }
                return 0;
            }""")
            print(screen, "wizard choices", n, "(negative: greyed; 0: no section)", flush=True)
            time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "%s_%s.png" % (which, screen)))
            browser.close()
    finally:
        proc.terminate()


def main():
    args = sys.argv[1:]
    repo = HERE
    if "--repo" in args:
        i = args.index("--repo")
        repo = os.path.abspath(args[i + 1])
        del args[i:i + 2]
    outdir, which = os.path.abspath(args[0]), args[1]
    os.makedirs(outdir, exist_ok=True)
    for pair in args[2:]:
        screen, title = pair.split("=", 1)
        shoot(outdir, which, screen, title, repo)
    print("shots in", outdir, flush=True)


if __name__ == "__main__":
    main()
