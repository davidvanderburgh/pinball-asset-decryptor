"""PAD-1310 proof shots: a name typed in Audio Properties keeps its
punctuation in callouts.csv; only the file name loses the characters
Windows can't hold.

    python scripts/shot_pad1310.py <repo> <out_dir> [--after]

Serves <repo> on the PAD-1069 scratch Stern project, names "idx0891 - Okay"
"Who are you? Spider-Man: Here!" in Audio Properties, presses OK, opens
Properties again and shoots it (<before_|after_>audio_properties.png), then
prints callouts.csv.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import shot_pad1060 as P  # noqa: E402
import shot_pad1069 as C  # noqa: E402
import webui_shot  # noqa: E402

WORDS = "Who are you? Spider-Man: Here!"


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1310-")
    project = C._project(scratch)
    proc, url = S._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
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
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            time.sleep(2)
            P._props(page, "idx0891")
            page.locator(".modal input").first.fill(WORDS)
            time.sleep(0.4)
            page.get_by_role("button", name="OK").first.click()
            time.sleep(2)
            P._props(page, "idx0891")
            time.sleep(0.6)
            print("name box:", page.locator(".modal input").first.input_value(),
                  flush=True)
            page.screenshot(path=out("audio_properties.png"))
            print("shot", out("audio_properties.png"), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
    print(sorted(os.listdir(os.path.join(project, "audio"))), flush=True)
    with open(os.path.join(project, "callouts.csv"), encoding="utf-8") as f:
        print(f.read(), flush=True)


if __name__ == "__main__":
    main()
