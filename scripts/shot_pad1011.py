"""PAD-1011 (PR #18) proof shot: Munsters Pro 1.28's Spot Mode page on the Modes tab, with its Shots section.

    python scripts/shot_pad1011.py <out dir> <before|after> [<repo>]

The server runs from <repo> (default: this tree) against a scratch settings folder and a scratch title cache.
The project is a scratch folder whose .extract_source.json names the library's Munsters Pro 1.28 card, so the
tab reads that card's own modes; the shot is Spot Mode's page. Run against main for "before" (its port names
none of the game's rules: the page has no Shots section) and this tree for "after".
Shot: <before|after>_spot_mode_shots.png
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\munsters_pro-1_28_0.Release.8G.sdcard.raw"
SPOT = 17


def main():
    outdir = os.path.abspath(sys.argv[1])
    which = sys.argv[2]
    repo = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad1011-")
    project = os.path.join(scratch, "munsters project")
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
        game = []
        for _ in range(240):                      # the card's read: its modes come once it is done
            game = (webui_shot.state(url).get("modes") or {}).get("game_rows") or []
            if any(str(r.get("slug", r.get("id"))) == str(SPOT) for r in game):
                break
            time.sleep(1)
        print("game rows", [(r.get("slug", r.get("id")), r.get("name")) for r in game], flush=True)
        print("select", webui_shot.api(url, "modes.select", str(SPOT), "game"), flush=True)
        time.sleep(2)
        st = webui_shot.state(url).get("modes") or {}
        gm = st.get("game_mode") or {}
        print("page", gm.get("name"), "rule", gm.get("rule"), "| remap:", (st.get("remap") or {}).get("msg"),
              flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1150})
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
            # the page's last sections (Shots, Advanced) at the foot of the editor, which scrolls on its own
            page.evaluate("() => document.querySelectorAll('.modes-editor-bd').forEach((e) => { e.scrollTop = e.scrollHeight; })")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "%s_spot_mode_shots.png" % which))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
        print("shot in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
