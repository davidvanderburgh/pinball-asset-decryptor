"""PAD-1462 (PR #39) proof shots: themes on the Images tab and the Colors bar's new panels.

    python scripts/shot_pad1462.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad463's scratch Godzilla project (four Battle Select portraits replaced).
The Images tab is searched to the portraits, its Colors bar open on Files.  Photographs, under the
same names before and after:

- images_bar.png     the test card's row clicked: the top of the Colors bar
- images_themes.png  themes switched on, a theme "Dark" added and picked, the test card given a
                     picture of its own in it (before: main has no themes, so the list as it is)

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
import shot_pad463 as imgs  # noqa: E402

# the Godzilla scratch source shot_pad312 copied is gone: King Kong LE's extract (a scratch copy), its 512x512
# scene pictures standing in for the portraits, audio and video left out
base.SOURCE = os.environ.get("PAD1462_SOURCE", "C:/tmp/kk_fix/project")
base.SKIP = tuple(base.SKIP) + ("video",)
base.PORTRAIT = imgs.TEX + "radimg_512x512_0075f30f.png"
imgs.MORE = (("radimg_512x512_010d9c9a.png", (1.35, 0.85, 0.7)), ("radimg_512x512_01460d0d.png", (0.7, 1.0, 1.4)), ("radimg_512x512_036f3ea6.png", (0.8, 1.3, 0.8)))
SEARCH = "512x512"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1462-")
    project = imgs._project(scratch)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    for name, text in (("Godzilla LE.txt", saved.GODZILLA), ("Black playfield.txt", saved.DARK)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    state = lambda: webui_shot.state(url)                    # noqa: E731

    def api(m, *a):
        try:
            return webui_shot.api(url, m, *a)
        except Exception as e:                              # noqa: BLE001 - main has no themes calls
            print("api", m, "failed:", e, flush=True)
            return None

    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731

    def settle(page, wait=2.0, end=False):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                                   # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 990)
        time.sleep(wait)
        if page.query_selector(".cpd-body"):
            page.eval_on_selector(".cpd-body", "el => { el.scrollTop = %s; }"
                                  % ("el.scrollHeight" if end else "0"))
            time.sleep(0.5)

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
            base._wait_scan(state, "images")
            api("ui.set", "images", "search", SEARCH)
            time.sleep(2.5)
            row = lambda n: page.locator(".img-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            card = base.PORTRAIT.split("_")[-1][:8]
            row(card).click()
            time.sleep(2)
            tab = page.query_selector(".cpd-tabs button:has-text('Files')")
            if tab:
                tab.click()
                time.sleep(1)
            settle(page)
            page.screenshot(path=out("images_bar.png"))

            # themes: switched on, "Dark" added and picked, the test card its own picture in it
            print("themes on:", api("imgsets.set_enabled", True), flush=True)
            print("add:", api("imgsets.add", "Dark"), flush=True)
            if after:
                sys.path.insert(0, repo)
                from pinball_decryptor.plugins.stern import scene_variants as SV
                SV.set_picture(project, 2, base.PORTRAIT,
                               os.path.join(scratch, "my_" + imgs.MORE[1][0]))
                api("imgsets.pick", 1)                  # (written behind the app's back: a re-pick reads it,
                time.sleep(1.5)                         # as Choose... does itself)
                api("imgsets.pick", 2)
                time.sleep(2.5)
            row(card).click()
            time.sleep(2.5)
            settle(page, 2.5)
            st = state()
            print("imgsets:", {k: (st.get("imgsets") or {}).get(k) for k in ("enabled", "names", "current")},
                  flush=True)
            page.screenshot(path=out("images_themes.png"))
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
