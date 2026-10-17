"""PAD-604 round 3 proof shots: one picture saved under a name of the user's, and the
closing question shows the file in its folder.

    python scripts/shot_pad604b.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad463's scratch Godzilla project, the test card given "Godzilla LE"
as its own profile.  Photographs, under the same names before and after:

- save_dialog.png  the test card right-clicked, "Save this picture with its color
                   profile…" clicked: the box that asks where (before: a folder;
                   after: Save As with the picture's own name filled in)
- save_done.png    the closing message once it is saved (before: "Open the folder?",
                   whose Yes failed with "Couldn't open file ... The file isn't there";
                   after: "Show in File Explorer?")

Before only, Yes is pressed on that question: before_open_error.png is the error.

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
import shot_pad463 as pics  # noqa: E402


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad604b-")
    project = pics._project(scratch)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import colour_profile as cp
    cp.store_own_profile(project, "images", base.PORTRAIT,
                         cp.Profile(name="Godzilla LE", gain=(1.0, 0.8, 1.15), saturation=1.2))
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    dest = os.path.join(scratch, "Saved pictures")
    os.makedirs(dest)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.set", "images", "search", "530x726")
            time.sleep(2.5)
            card = base.PORTRAIT.split("_")[-1][:8]
            row = page.locator(".img-tbl .tr:has-text('%s')" % card).first
            row.click()
            time.sleep(1.5)
            row.click(button="right")
            time.sleep(1)
            page.locator(".menu >> text=/Save this picture/").first.click()
            time.sleep(2.5)
            page.screenshot(path=out("save_dialog.png"))
            page.keyboard.press("Escape")
            time.sleep(1)
            for _ in range(3):
                btn = page.query_selector(".scrim button:has-text('Cancel')")
                if not btn:
                    break
                btn.click()
                time.sleep(1)
            if after:
                print("save:", api("images.colour_save", [base.PORTRAIT], None,
                                   os.path.join(dest, "Godzilla card.png")), flush=True)
            else:
                print("save:", api("images.colour_save", [base.PORTRAIT], dest), flush=True)
            for _ in range(60):
                if not (state().get("images") or {}).get("csave"):
                    break
                time.sleep(1)
            time.sleep(2)
            page.screenshot(path=out("save_done.png"))
            print("saved:", os.listdir(dest), flush=True)
            if not after:
                page.locator(".scrim button:has-text('Yes')").first.click()
                time.sleep(2)
                page.screenshot(path=out("open_error.png"))
            else:
                page.locator(".scrim button:has-text('No')").first.click()
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(dest, ignore_errors=True)


if __name__ == "__main__":
    main()
