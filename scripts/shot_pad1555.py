"""PAD-1555 proof shot: a new mode's page on the Modes tab for one of Stern's November 2026 builds.

    python scripts/shot_pad1555.py <out dir> <before|after> <card.raw> <name> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder and a scratch title cache, so
the card's port is found (or derived) the way a fresh install finds it. The project is a scratch folder whose
.extract_source.json names <card>. Before: the build has no shipped port, the app derives one that no emulator
run has seen, and most of the page is greyed with yellow "not yet seen" lines. After: the shipped, proven port.
Shots: <before|after>_modes_<name>.png (the page's head) and <before|after>_modes_<name>_parts.png (scrolled to
the foot, where the mechanism parts are).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402


def main():
    outdir = os.path.abspath(sys.argv[1])
    which, card, name = sys.argv[2], os.path.abspath(sys.argv[3]), sys.argv[4]
    repo = os.path.abspath(sys.argv[5]) if len(sys.argv) > 5 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad1555-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card)}, f)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project,
                                               "extract_input": card}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_TITLE_CACHE": os.path.join(scratch, "titles")}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env)
    print("repo", repo, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        prof = {}
        for _ in range(600):                      # the card's read (and a derivation, before) comes first
            prof = (webui_shot.state(url).get("modes") or {}).get("profile") or {}
            if prof.get("game_modes") or prof.get("label"):
                break
            time.sleep(1)
        print("profile", prof.get("label"), "cannot", len(prof.get("cannot") or ()), flush=True)
        print("new", webui_shot.api(url, "modes.new"), flush=True)
        time.sleep(3)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1300})
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
            page.screenshot(path=os.path.join(outdir, "%s_modes_%s.png" % (which, name)))
            page.evaluate("() => document.querySelectorAll('.modes-editor-bd').forEach((e) => { e.scrollTop = e.scrollHeight; })")
            time.sleep(0.7)
            page.screenshot(path=os.path.join(outdir, "%s_modes_%s_parts.png" % (which, name)))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
        print("shot in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
