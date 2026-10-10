"""PAD-507 proof shots: Godzilla's score panel colours, which the game program paints itself.

    python scripts/shot_pad507.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project set up the way DragonRR had his:
the individual files profile Black and white, the game's own lines unlocked and every line
of the score panel (scene 9d578751, the HUD's player boxes) switched on.  Then, under the
same names before and after:

- scenes_score.png       Scenes on the score panel, Player 1's score selected.  Before: the
                         score is drawn in its scene colour through the profile (grey), while
                         the game paints it gold and the empty boxes green whatever the scene
                         says.  After: the boxes are drawn in the colours the game paints, and
                         the Selected panel lists them (through the profile, or picked by hand).

After only: scenes_score_picked.png, the same with PRESS START picked white and the player
who is up picked red by hand.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

SCORE = "/godzilla_le/assets/lcd/auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821"
#: Player 1's box: its score, and the three other players' boxes beside it
P1_SCORE = 2161
PANEL = (2161, 2206, 2212, 2218, 2232, 2277, 2283, 2289, 2303, 2348, 2354, 2360)


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad507-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright

    def settle(page, wait=1.5):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                               # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 1100)
        time.sleep(wait)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            time.sleep(1)
            print("preset bw:", api("color.preset", "bw"), flush=True)
            time.sleep(1)
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", SCORE + "/scene.radium") or api("text_scenes.select", SCORE)
            time.sleep(8)
            print("unlocked:", api("text_scenes.tree_color_unlocked", True), flush=True)
            time.sleep(3)
            for nid in PANEL:
                api("text_scenes.tree_color", nid, True)
            time.sleep(2)
            api("text_scenes.tree_select", P1_SCORE)
            time.sleep(5)
            sc = state().get("text_scenes") or {}
            props = (sc.get("tree_view") or {}).get("props") or {}
            print("picked:", props.get("name"), "game colors:", props.get("game_colors"),
                  flush=True)
            settle(page)
            page.screenshot(path=out("scenes_score.png"))
            if after:
                api("text_scenes.tree_game_color", "start", "#ffffff")
                api("text_scenes.tree_game_color", "up", "#e02020")
                time.sleep(5)
                props = ((state().get("text_scenes") or {}).get("tree_view") or {}).get(
                    "props") or {}
                print("after picks:", props.get("game_colors"), flush=True)
                settle(page)
                page.screenshot(path=out("scenes_score_picked.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
