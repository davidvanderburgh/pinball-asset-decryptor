"""PAD-701 proof shot: Previous / Next beside the Audio tab's Play buttons.

    python scripts/shot_pad701.py <repo> <out_dir> [--after]

Serves <repo> on the PAD-685 scratch The Beatles 1.29 project (shot_pad685's project, a dozen stock
sounds from PAD685_EXTRACT), types a search so the list is filtered, plays the first row and then
(after) presses Next, so the shot shows the second row of the filtered list selected and loaded.
Writes, under the same name before and after:

- <before_|after_>audio_transport.png   the Audio tab with its two players

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import shot_pad685 as J  # noqa: E402
import webui_shot  # noqa: E402


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad701-")
    project = J._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_transport.png")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            api("ui.set", "audio", "search", "idx04")      # a filter: only idx04xx rows show
            time.sleep(1.5)
            rows = [r["k"] for r in (state().get("audio") or {}).get("rows") or [] if not r.get("g")]
            print("filtered rows:", rows, flush=True)
            api("audio.play_row", rows[0])
            time.sleep(2)
            nxt = page.locator(".aud-pane").first.get_by_role("button", name="Next")
            if nxt.count():
                nxt.click()
                time.sleep(2)
            else:
                print("no Next button", flush=True)
            page.locator(".aud-pane").first.get_by_role("button", name="Stop").click()
            time.sleep(1)
            st = state().get("audio") or {}
            print("sel:", st.get("sel"), "| orig pane:", (st.get("panes") or {}).get("orig", {}).get("name"),
                  flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
