"""PAD-604 proof shots: Images and Video save files with their color profile baked in.

    python scripts/shot_pad604.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad463's scratch Godzilla project (four Battle Select portraits
replaced, the test card given "Godzilla LE" as its own profile) with shot_pad448's four
video slots (King Ghidorah "Blue to violet" and Mothra "Warm grade", both replaced and
attached).  Photographs, under the same names before and after:

- images_menu.png  the four replaced portraits selected, right-clicked
- images_more.png  the Images tab's More menu
- video_menu.png   the two replaced clips selected, right-clicked
- video_more.png   the Video tab's More menu

With --after it then saves the selections through the new calls into
<out_dir>/saved_images and <out_dir>/saved_video and photographs each tab's closing
message (after_images_done.png, after_video_done.png).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
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
import shot_pad448 as clips  # noqa: E402
import shot_pad463 as pics  # noqa: E402


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad604-")
    project = pics._project(scratch)
    clips._clips(scratch, project)
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
        time.sleep(wait)

    def wait_done(ns, limit=600):
        t0 = time.time()
        while time.time() - t0 < limit:
            cs = (state().get(ns) or {}).get("csave")
            if not cs:
                return True
            print(ns, "saving:", cs.get("text"), flush=True)
            time.sleep(2)
        return False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open.images');"
                " localStorage.removeItem('pad.colorbar.open.video'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)

            # ---- Images ----
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.set", "images", "search", "530x726")
            time.sleep(2.5)
            row = lambda n: page.locator(".img-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            card = base.PORTRAIT.split("_")[-1][:8]
            names = [card] + [n[-12:-4] for n, _k in pics.MORE]
            row(names[0]).click()
            time.sleep(1)
            for n in names[1:]:
                row(n).click(modifiers=["Control"])
                time.sleep(0.4)
            time.sleep(1.5)
            row(names[-1]).click(button="right")
            settle(page, 1.5)
            page.screenshot(path=out("images_menu.png"))
            page.keyboard.press("Escape")
            time.sleep(0.8)
            page.locator(".page button[aria-label='More'], .page button:has-text('More')").first.click()
            settle(page, 1.0)
            page.screenshot(path=out("images_more.png"))
            page.keyboard.press("Escape")
            time.sleep(0.8)
            if after:
                dest = os.path.join(out_dir, "saved_images")
                shutil.rmtree(dest, ignore_errors=True)
                os.makedirs(dest)
                rels = [base.PORTRAIT] + [pics.TEX + n for n, _k in pics.MORE]
                print("images.colour_save", api("images.colour_save", rels, dest), flush=True)
                wait_done("images")
                settle(page, 1.5)
                page.screenshot(path=out("images_done.png"))
                print("saved images:", sorted(os.listdir(dest)), flush=True)
                btn = page.query_selector(".dlg button:has-text('OK'), .modal button:has-text('OK')")
                if btn:
                    btn.click()
                    time.sleep(1)

            # ---- Video ----
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video")
            api("ui.set", "video", "search", "video/pad")
            time.sleep(2)
            vnames = [rel.split("/")[-1] for rel, _m, _r, _o in clips.CLIPS[:2]]
            vrow = lambda n: page.locator(".vid-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            vrow(vnames[0]).click()
            time.sleep(1.5)
            vrow(vnames[1]).click(modifiers=["Control"])
            time.sleep(1.5)
            vrow(vnames[1]).click(button="right")
            settle(page, 1.5)
            page.screenshot(path=out("video_menu.png"))
            page.keyboard.press("Escape")
            time.sleep(0.8)
            page.locator(".page button[aria-label='More'], .page button:has-text('More')").first.click()
            settle(page, 1.0)
            page.screenshot(path=out("video_more.png"))
            page.keyboard.press("Escape")
            time.sleep(0.8)
            if after:
                dest = os.path.join(out_dir, "saved_video")
                shutil.rmtree(dest, ignore_errors=True)
                os.makedirs(dest)
                rels = [rel for rel, _m, _r, _o in clips.CLIPS[:2]]
                print("video.colour_save", api("video.colour_save", rels, dest), flush=True)
                time.sleep(2)
                page.screenshot(path=out("video_saving.png"))
                wait_done("video")
                settle(page, 1.5)
                page.screenshot(path=out("video_done.png"))
                print("saved video:", sorted(os.listdir(dest)), flush=True)
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
