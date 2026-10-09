"""PAD-442 proof shots: compare two project folders.

    python scripts/shot_pad442.py <repo> <out_dir> <folder A> <folder B> [--after]

Serves <repo> against a scratch settings folder and photographs, under the
same names before and after:

- compare_folders.png  Stern: the Compare tab with two project folders in A
                       and B and Compare pressed.  Before (main) that is a
                       "Not found" box: the tab only takes card images.  After
                       (--after, the ticket branch): the folder report.
- compare_jjp.png      JJP: before, no Compare tab in the rail at all (the
                       shot is the Extract tab it lands on); after, the
                       Compare tab with the same two folders compared (a
                       folder compare does not care whose extract it is).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


def main():
    repo, out_dir, dir_a, dir_b = sys.argv[1:5]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    tag = "after_" if after else "before_"
    scratch = tempfile.mkdtemp(prefix="pad442-")
    print("serving", repo, flush=True)
    webui_shot.REPO = repo
    # the scratch APPDATA would hide the user site-packages the plugins need
    env = {"PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""),
                                          "Python")}
    proc, url = webui_shot.start_server(None, scratch, extra_env=env)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1560})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)

            def compare_shot(mfr, name):
                # the plugins load after the page is up
                end = time.time() + 60
                while time.time() < end:
                    keys = [m.get("key") for m in
                            state()["shell"].get("mfrs") or []]
                    if mfr in keys:
                        break
                    time.sleep(0.5)
                print("manufacturers:", keys, flush=True)
                api("ui.pick_manufacturer", mfr)
                time.sleep(1.5)
                tabs = {t["ns"]: t for t in state()["shell"]["tabs"]}
                visible = bool(tabs.get("compare", {}).get("visible"))
                print(mfr, "compare tab visible:", visible, flush=True)
                if not visible:
                    time.sleep(1)
                    page.mouse.move(900, 40)          # no hover tips
                    time.sleep(0.5)
                    page.screenshot(path=os.path.join(out_dir, tag + name))
                    return
                api("ui.select_tab", "compare")
                time.sleep(1.5)
                api("ui.set", "compare", "a", dir_a)
                api("ui.set", "compare", "b", dir_b)
                time.sleep(0.8)
                page.click(".cmp-src button:has-text('Compare')")
                end = time.time() + 120
                while time.time() < end:
                    time.sleep(0.5)
                    c = state().get("compare") or {}
                    if c.get("has_report") or page.locator(
                            ".modal").count():
                        break
                time.sleep(2)
                c = state().get("compare") or {}
                print(name, "report rows:", len(c.get("rows") or []),
                      "status:", c.get("status"), flush=True)
                page.mouse.move(900, 40)
                time.sleep(0.5)
                page.screenshot(path=os.path.join(out_dir, tag + name))
                # close whatever box the run put up before the next shot
                ok = page.locator(".modal button:has-text('OK')")
                if ok.count():
                    ok.first.click()
                    time.sleep(0.8)

            compare_shot("stern", "compare_folders.png")
            compare_shot("jjp", "compare_jjp.png")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
