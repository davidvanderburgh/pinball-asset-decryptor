"""PAD-463 proof shots: the Images tab gets the Video tab's color work (Compare, the preview
drawn through the color profiles, several pictures profiled at once), and the Which files
card's "Every replaced picture / video" boxes become "All images / All videos".

    python scripts/shot_pad463.py <repo> <out_dir> [--after [--confirm]]

Serves <repo> on shot_pad312's scratch Godzilla project with four of its seven Battle
Select portraits replaced (shot_pad312's vivid test card, and three of the others
recolored), "Godzilla LE" / "Black playfield" in the folder the Saved profiles list reads,
and the test card given "Godzilla LE" as its own profile, attached.  The Images tab is
searched to the portraits and its Colors bar is open on Files.  Photographs, under the
same names before and after:

- images_preview.png  the test card's row: the Original / Replacement panes
- images_multi.png    the three recolored portraits selected together (Shift-click) and
                      "Black playfield" picked from Saved profiles
- images_compare.png  the four replaced portraits selected, then Compare (before: there
                      is no Compare, so the list as it is with them selected)
- images_which.png    a game's own portrait (locked) clicked: the bar's Which files card
- color_which.png     the Color profile tab on Files: its Which files card

With --after --confirm, after images_which.png also images_allconfirm.png (the question
"All images..." asks) and images_all.png (the list once it is answered Yes).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad360 as saved  # noqa: E402

TEX = "images/scene_textures/"
#: three more portraits replaced, each by a recolored copy of itself
MORE = (("radimg_530x726_3621969f.png", (1.35, 0.85, 0.7)),
        ("radimg_530x726_3889d8a2.png", (0.7, 1.0, 1.4)),
        ("radimg_530x726_7d50e4f5.png", (0.8, 1.3, 0.8)))
#: a game's own portrait, left as it is
STOCK = TEX + "radimg_530x726_dd093439.png"


def _project(scratch):
    project = base._project(scratch)
    from PIL import Image
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    for name, (kr, kg, kb) in MORE:
        with Image.open(os.path.join(project, *(TEX + name).split("/"))) as im:
            r, g, b, a = im.convert("RGBA").split()
            im2 = Image.merge("RGBA", (r.point(lambda v: min(255, int(v * kr))),
                                       g.point(lambda v: min(255, int(v * kg))),
                                       b.point(lambda v: min(255, int(v * kb))), a))
        mine = os.path.join(scratch, "my_" + name)
        im2.save(mine)
        data.setdefault("image", {})[TEX + name] = mine
    for k in ("image_color_slots", "video_color_slots", "image_color_profiles",
              "video_color_profiles", "color_all_images", "color_all_videos",
              "image_color_unlocked", "image_group_by_scene"):
        data.pop(k, None)
    data["image_change_filter"] = "All"
    data["image_source_filter"] = "All sources"
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return project


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad463-")
    project = _project(scratch)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    for name, text in (("Godzilla LE.txt", saved.GODZILLA), ("Black playfield.txt", saved.DARK)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731

    def settle(page, wait=1.5):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                                   # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 990)
        time.sleep(wait)
        bar = page.query_selector(".cpd-body")
        if bar:
            page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")

    def report(name):
        im = state().get("images") or {}
        c = state().get("color") or {}
        rows = [r for k in range(im.get("nchunks") or 0) for r in im.get("rows_%d" % k) or []]
        print(name, "bar file:", c.get("file"), "name:", c.get("name"), flush=True)
        print(name, "rows c:", [(r["r"].split("_")[-1], r.get("c"), r.get("co"), r.get("cl"))
                                for r in rows if "530x726" in r["r"]], flush=True)
        print(name, "own names:", (c.get("own_names") or {}).get("images"), flush=True)
        print(name, "look:", {k: v for k, v in (im.get("look") or {}).items()
                              if k in ("offered", "on", "sw", "views", "keys")}, flush=True)
        print(name, "compare:", [(t.get("rel"), t.get("side")) for t in
                                 (im.get("compare") or {}).get("tiles") or []], flush=True)

    def pick_saved(label):
        c = state().get("color") or {}
        pick = next((o["value"] for o in c.get("saved") or [] if label in o.get("label", "")), None)
        print("use_saved", label, api("color.use_saved", pick), flush=True)
        time.sleep(2.5)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open.images', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            st = base._wait_scan(state, "images")
            print("images:", st.get("status"), flush=True)
            api("ui.set", "images", "search", "530x726")
            time.sleep(2.5)
            row = lambda n: page.locator(".img-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            card = base.PORTRAIT.split("_")[-1][:8]

            # the test card: its own profile, attached
            row(card).click()
            time.sleep(2)
            tab = page.query_selector(".cpd-tabs button:has-text('Files')")
            if tab:
                tab.click()
                time.sleep(1)
            pick_saved("Godzilla")
            row(MORE[0][0][-12:-4]).click()
            time.sleep(1.5)
            row(card).click()
            time.sleep(3)
            settle(page, 3)
            report("images_preview")
            page.screenshot(path=out("images_preview.png"))

            # three recolored portraits selected together, a saved profile picked
            row(MORE[0][0][-12:-4]).click()
            time.sleep(1)
            row(MORE[2][0][-12:-4]).click(modifiers=["Shift"])
            time.sleep(2.5)
            sel = page.eval_on_selector_all(".img-tbl .tr.sel, .img-tbl .tr.on, .img-tbl .tr[aria-selected='true']",
                                            "els => els.length")
            print("selected rows (dom):", sel, flush=True)
            pick_saved("Black")
            settle(page, 2.5)
            report("images_multi")
            page.screenshot(path=out("images_multi.png"))

            # the four replaced portraits, then Compare
            row(card).click()
            time.sleep(1)
            for name, _k in MORE:
                row(name[-12:-4]).click(modifiers=["Control"])
                time.sleep(0.4)
            time.sleep(2)
            btn = page.query_selector(".img-cmp-open")
            print("compare button:", bool(btn), flush=True)
            if btn:
                btn.click()
                time.sleep(5)
            settle(page, 3)
            report("images_compare")
            page.screenshot(path=out("images_compare.png"))
            if btn:
                page.keyboard.press("Escape")
                time.sleep(1.5)
                close = page.query_selector(".icm button:has-text('Close')")
                if close:
                    close.click()
                    time.sleep(1.5)

            # a game's own portrait: no file for the bar, its Which files card
            row(STOCK.split("_")[-1][:8]).click()
            time.sleep(2.5)
            settle(page)
            report("images_which")
            page.screenshot(path=out("images_which.png"))

            if after and "--confirm" in sys.argv:
                # All images...: the question it asks, then Yes, then the list
                btn = page.query_selector(".cp-which-all button:has-text('All images')")
                print("all images button:", bool(btn), flush=True)
                if btn:
                    btn.click()
                    time.sleep(1.5)
                    page.screenshot(path=out("images_allconfirm.png"))
                    page.click(".modal button:has-text('Yes')")
                    time.sleep(3)
                    settle(page)
                    report("images_all")
                    page.screenshot(path=out("images_all.png"))

            # the Color profile tab on Files
            api("ui.select_tab", "color")
            time.sleep(2)
            api("color.set_mode", "assets")
            time.sleep(2)
            which = page.query_selector(".cp-which")
            if which:
                which.scroll_into_view_if_needed()
            settle(page)
            page.screenshot(path=out("color_which.png"))
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
