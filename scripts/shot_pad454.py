"""PAD-454 proof shots: the main Video players get Compare's Original / With its color
profile switch, each player its own.

    python scripts/shot_pad454.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad448's four video slots (King Ghidorah and Mothra replaced and
attached, "Blue to violet" / "Warm grade"; the atomic breath clip and Shin Godzilla left
as the game's own clips, the atomic breath one with "Sepia" as its own profile), with
Advanced ticked and the atomic breath clip's profile attached.  The Colors bar is open.
Photographs, under the same names before and after:

- video_main.png        the Mothra row: after, the Original player turned to "With its
                        color profile" and the Replacement player to "Replacement"
- video_main_stock.png  the atomic breath row (a game's own clip, profile attached): the
                        two players as they open

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
import shot_pad360 as saved  # noqa: E402
import shot_pad448 as clips  # noqa: E402


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad454-")
    project = base._project(scratch)
    clips._clips(scratch, project)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    tag = "after_" if after else "before_"
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731

    def settle(page):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                                   # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 990)
        time.sleep(1.5)

    def report(name, page):
        v = state().get("video") or {}
        look = v.get("look") or {}
        pv = v.get("preview") or {}
        print(name, "panes:", {k: (pv.get(k) or {}).get("title") for k in ("orig", "rep")},
              "steps:", {k: len(look.get(k) or []) for k in ("orig", "rep")},
              "lut:", look.get("lut"), "view:", look.get("view"), "views:", look.get("views"),
              flush=True)
        print(name, "segs:", page.evaluate(
            "[...document.querySelectorAll('.vid-view .seg')].map((s) =>"
            " [...s.querySelectorAll('button')].map((b) => b.textContent + (b.classList.contains('on') ? '*' : '')))"),
            "gl:", page.evaluate(
                "[...document.querySelectorAll('.vid-panes canvas.vid-gl')].map((c) => c.style.visibility)"),
            flush=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open.video', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            st = base._wait_scan(state, "video")
            print("video rows:", [r["rel"] for r in st.get("rows") or []], flush=True)
            api("ui.set", "video", "search", "video/pad")
            time.sleep(2)
            api("video.set_color_stock", True)
            time.sleep(1)
            api("video.set_color", clips.STOCK, True)
            time.sleep(1.5)
            names = [rel.split("/")[-1] for rel, _m, _r, _o in clips.CLIPS]
            row = lambda n: page.locator(".vid-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            pane = lambda i: page.locator(".vid-panes .vid-pane").nth(i)  # noqa: E731

            # the Mothra row: a replaced clip with Warm grade attached
            row(names[1]).click()
            time.sleep(4)
            tab = page.query_selector(".cpd-tabs button:has-text('Files')")
            if tab:
                tab.click()
                time.sleep(1)
            if after:
                pane(0).locator(".seg button:has-text('With its color profile')").click()
                time.sleep(1)
                pane(1).locator(".seg button:has-text('Replacement')").click()
                time.sleep(2.5)
            clips._seek_all(page, ".vid-screen video")
            settle(page)
            page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")
            report("video_main", page)
            page.screenshot(path=out("video_main.png"))

            # the atomic breath row: the game's own clip with its profile attached
            row(names[2]).click()
            time.sleep(4)
            clips._seek_all(page, ".vid-screen video")
            settle(page)
            report("video_main_stock", page)
            page.screenshot(path=out("video_main_stock.png"))
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
