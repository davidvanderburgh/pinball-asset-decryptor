"""PAD-471 proof shots: lines of text in Scenes and "all of them" in black and white.

    python scripts/shot_pad471.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project set up the way DragonRR had his:
the individual files profile Black and white, the game's own pictures and lines unlocked,
and every picture of the orange GameFont_Secondary attached (what All images did to them).
Then, under the same names before and after:

- scenes_font_lines.png   Scenes on "SUPER JACKPOT IS LIT!" (2872b0bb): the orange title is
                          drawn black and white through its font's pictures, but its palette
                          was red (after: green, with the link mark)
- scenes_line_colors.png  the first scene (1e3687a3), its green "LINE 1" selected, Colors
                          bar open (after: Apply to all profiled lines of text / Apply to all
                          lines of text)
- scenes_first_line.png   the same scene with the Colors bar closed: before, nothing has
                          reached the line (green, red palette); after, Apply to all lines of
                          text answered Yes (grey, green palette)
- color_which.png         the Color profile tab's Which files card (after: All text)

After only: scenes_apply_all_confirm.png, the question Apply to all lines of text asks.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

FIRST = ("/godzilla_le/assets/lcd/demand_loaded/bc0792d8dc81e8aa30b987246a5ce97c40cd6833/"
         "1e3687a305fa008208c5f4387ae54b562a15e70e")
JACKPOT = ("/godzilla_le/assets/lcd/auto_loaded/c65ecc5e2f5769bdc59851eb951a1c781b53deb8/"
           "2872b0bbe7154d0f7fe1250554f32085d0336b49")
#: GameFont_Secondary's three pictures (PAD-451)
FONT_PICS = ("images/scene_textures/radimg_GameFont_Secondary_512x512_115d03b4.png",
             "images/scene_textures/radimg_512x512_1a9486f2.png",
             "images/scene_textures/radimg_512x512_9d77fb3f.png")


def _layers(state):
    tv = (state().get("text_scenes") or {}).get("tree_view") or {}
    return tv.get("layers") or []


def _unlock_font(project):
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    data["image_color_unlocked"] = True
    data["image_color_slots"] = dict(data.get("image_color_slots") or {},
                                     **{r: True for r in FONT_PICS})
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad471-")
    project = base._project(scratch)
    _unlock_font(project)
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

    def scene(where):
        api("text_scenes.select", where + "/scene.radium") or api("text_scenes.select", where)
        time.sleep(8)

    def lines(name):
        for l in _layers(state):
            if (l.get("color") or {}).get("line"):
                print(name, l["id"], l["name"], l.get("text"),
                      {k: v for k, v in l["color"].items() if k != "font_pictures"}, flush=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.fontbar.open'); } catch (e) {}")
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
            which = page.query_selector(".cp-which")
            if which:
                which.scroll_into_view_if_needed()
            settle(page)
            page.screenshot(path=out("color_which.png"))

            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            scene(JACKPOT)
            print("unlocked:", api("text_scenes.tree_color_unlocked", True), flush=True)
            time.sleep(4)
            lines("jackpot")
            settle(page)
            page.screenshot(path=out("scenes_font_lines.png"))

            scene(FIRST)
            line1 = next(l for l in _layers(state) if l.get("name") == "Line1")
            api("text_scenes.tree_select", line1["id"])
            time.sleep(3)
            handle = page.query_selector("button.cpd-handle[aria-label='Color profiles']")
            if handle:
                handle.click()
                time.sleep(3)
            print("color file:", (state().get("color") or {}).get("file"), flush=True)
            settle(page)
            page.screenshot(path=out("scenes_line_colors.png"))
            btn = page.query_selector(".cpd-file-all button:has-text('Apply to all lines of text')")
            print("apply to all lines button:", bool(btn), flush=True)
            if btn:
                btn.click()
                time.sleep(1.5)
                page.screenshot(path=out("scenes_apply_all_confirm.png"))
                page.click(".modal button:has-text('Yes')")
                time.sleep(6)
            if handle:
                handle.click()
                time.sleep(2)
            api("text_scenes.tree_select", None)
            time.sleep(4)
            lines("first")
            settle(page)
            page.screenshot(path=out("scenes_first_line.png"))
            print("text slots on:", sum(1 for _ in (json.load(open(
                os.path.join(project, ".staged_changes.json"), encoding="utf-8")).get(
                    "text_color_slots") or {})), flush=True)
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
