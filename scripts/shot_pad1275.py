"""PAD-1275 proof shots: the Audio tab's "Hide unused" tick became "Show unused".

    python scripts/shot_pad1275.py <repo> <out_dir> [--after]

Reuses the PAD-1105 scratch Stern project (ten sounds, four played by no
request). Writes, under the same names before and after:

- <before_|after_>audio_default.png  the list as it opens (every sound shown)
- <before_|after_>audio_hidden.png   after clicking the tick once, so the
                                     unused sounds are left out

The tick is found by its label: "Hide unused" before, "Show unused" after.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import shot_pad1105 as U  # noqa: E402
import webui_shot  # noqa: E402


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    label = "Show unused" if after else "Hide unused"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1275-")
    project = U._project(repo, scratch)
    proc, url = S._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            time.sleep(2)
            for name, click in (("audio_default.png", False), ("audio_hidden.png", True)):
                if click:
                    page.get_by_text(label, exact=True).first.click()
                    time.sleep(1.5)
                st = state().get("audio") or {}
                print(name, "hide_unused:", st.get("hide_unused"),
                      "rows:", len(st.get("rows") or []), flush=True)
                page.mouse.move(5, 990)
                time.sleep(0.6)
                page.screenshot(path=out(name))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
