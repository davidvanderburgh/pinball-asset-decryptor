"""PAD-1026 proof shot: a James Bond LE mode's "The game's own modes" section on the Modes tab.

    python scripts/shot_pad1026.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder and a scratch title cache, on a
scratch project whose .extract_source.json names the library's Bond LE 1.06 card. A new mode is made and its page
scrolled to the section. Run against main for "before" (Bond names none of the game's features: no "keep counting"
list) and this tree for "after" (the Attache Case, DB5 and Powerpack countdowns, none ticked: they count nothing while
the mode runs, as under the game's own mini-wizards).
Shot: <before|after>_bond_game_modes.png
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\james_bond_le-1_06_0.Release.16G.sdcard.raw"


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad1026-")
    project = os.path.join(scratch, "bond project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project,
                                               "extract_input": CARD}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_TITLE_CACHE": os.path.join(scratch, "titles")}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env)
    print("repo", repo, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        for _ in range(240):                      # the card's read: the form opens once it is done
            prof = (webui_shot.state(url).get("modes") or {}).get("profile") or {}
            if prof.get("game_modes"):
                break
            time.sleep(1)
        print("new", webui_shot.api(url, "modes.new"), flush=True)
        time.sleep(3)
        prof = (webui_shot.state(url).get("modes") or {}).get("profile") or {}
        print("game rules", prof.get("game_rules"), flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1400})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()
                time.sleep(1)
            # the section's foot: the last of the game's modes, then (after) the features that keep counting
            page.evaluate("""() => { const a = [...document.querySelectorAll('label, span')].find((e) =>
                e.textContent.trim() === "Can run during the game's own modes"); if (a) a.scrollIntoView({block: "end"}); }""")
            time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "%s_bond_game_modes.png" % which))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
        print("shot in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
