"""PAD-569 proof shots: the top bar's Reset..., and the Scenes window's Reset renamed Revert.

    python scripts/shot_pad569.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project (a replaced portrait, the color
profile on) with one of the project's modes copied in and one Scenes edit made, and writes
under the same names before and after:

- top_bar.png        the Write tab under the top bar: after, Reset... beside the project
- reset_dialog.png   what "Revert all changes..." on the Write tab opens: before, the old
                     question; after, Reset... with every kind ticked and counted
- scenes_revert.png  the Scenes window's menu under the preview: before "Reset", after
                     "Revert"

After only: reset_picked.png, Reset... opened from the top bar with two kinds ticked.
Nothing is reset: every dialog is cancelled.

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

MODE = os.path.join(base.SOURCE, "modes", "new_mode")


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad569-")
    project = base._project(scratch)
    if os.path.isdir(MODE):
        shutil.copytree(MODE, os.path.join(project, "modes", "new_mode"))
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
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            # one Scenes edit, so the Scenes window's menu is live
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(8)
            print("move:", api("text_scenes.tree_move", 1039, 20, 0), flush=True)
            time.sleep(3)
            btn = page.query_selector(".tree-actions button:has-text('Revert'), "
                                      ".tree-actions button:has-text('Reset')")
            print("scenes menu button:", btn.inner_text() if btn else None, flush=True)
            if btn:
                btn.click()
                time.sleep(1.5)
                page.screenshot(path=out("scenes_revert.png"))
                page.keyboard.press("Escape")
                time.sleep(0.5)
            api("text_scenes.close")
            time.sleep(1)
            api("ui.select_tab", "write")
            time.sleep(4)
            settle(page)
            page.screenshot(path=out("top_bar.png"))
            rv = page.query_selector("button:has-text('Revert all changes')")
            print("revert all button:", bool(rv), rv.is_enabled() if rv else None, flush=True)
            if rv and rv.is_enabled():
                rv.click()
                time.sleep(4)
                page.screenshot(path=out("reset_dialog.png"))
                rows = ((state().get("shellx") or {}).get("reset") or {}).get("rows")
                print("reset rows:", [(r["label"], r["n"]) for r in rows or []], flush=True)
                no = page.query_selector(".modal button:has-text('Cancel'), "
                                         ".modal button:has-text('No')")
                print("cancel with:", no.inner_text() if no else None, flush=True)
                if no:
                    no.click()
                time.sleep(1)
            if after:
                top = page.query_selector("header.topbar button:has-text('Reset')")
                print("top bar reset:", bool(top), flush=True)
                if top:
                    top.click()
                    time.sleep(4)
                    for label in ("Scenes edits", "Color profiles"):
                        page.click(".sx-reset-row label:has-text('%s')" % label)
                    time.sleep(1)
                    page.mouse.move(5, 990)
                    time.sleep(0.5)
                    page.screenshot(path=out("reset_picked.png"))
                    page.click(".modal button:has-text('Cancel')")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))
    print("scratch", scratch)


if __name__ == "__main__":
    main()
