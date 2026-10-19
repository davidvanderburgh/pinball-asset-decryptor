"""PAD-631 proof shots: compare a stock card against a modded one.

    python scripts/shot_pad631.py <repo> <out_dir> <card A> <card B> [--after]

Serves <repo> against a scratch settings folder, puts the two cards in the
Compare tab's A and B, presses Compare and photographs the report as
``before_compare_cards.png`` / ``after_compare_cards.png``.  The Rows per list
setting is turned down to 12 so the Sounds, Videos and Scenes sections all fit
in one shot.

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
    repo, out_dir, card_a, card_b = sys.argv[1:5]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    tag = "after_" if after else "before_"
    scratch = tempfile.mkdtemp(prefix="pad631-")
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
            page = browser.new_page(viewport={"width": 1600, "height": 2200})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); }"
                " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            end = time.time() + 60
            while time.time() < end:
                keys = [m.get("key") for m in
                        state()["shell"].get("mfrs") or []]
                if "stern" in keys:
                    break
                time.sleep(0.5)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1.5)
            api("ui.select_tab", "compare")
            time.sleep(1.5)
            api("ui.set", "compare", "a", card_a)
            api("ui.set", "compare", "b", card_b)
            time.sleep(0.8)
            api("ui.set", "compare", "limit", "12")
            time.sleep(0.5)
            page.click(".cmp-src button:has-text('Compare')")
            end = time.time() + 900
            while time.time() < end:
                time.sleep(1)
                c = state().get("compare") or {}
                if c.get("has_report") or page.locator(".modal").count():
                    break
            time.sleep(3)
            c = state().get("compare") or {}
            print("compare keys:", sorted(c), flush=True)
            print("report rows:", len(c.get("rows") or []),
                  "status:", c.get("status"), flush=True)
            page.mouse.move(900, 40)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir,
                                              tag + "compare_cards.png"),
                            full_page=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
