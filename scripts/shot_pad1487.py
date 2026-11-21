"""PAD-1487 proof shot: the Stern Emulate tab's "Hold the ball in the shooter lane".

    python scripts/shot_pad1487.py <repo> <out_dir> [--after]

Serves <repo> against a scratch settings folder, opens the Stern Emulate tab
and photographs its card section (the machine row and the ticks under it).
After: the new tick is there, ticked, with its tooltip open.  Saved as
before_/after_emulate_hold.png.

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
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    tag = "after_" if after else "before_"
    scratch = tempfile.mkdtemp(prefix="pad1487-")
    webui_shot.REPO = repo
    env = {"PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python")}
    proc, url = webui_shot.start_server(None, scratch, extra_env=env)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            end = time.time() + 60
            while time.time() < end:
                if "stern" in [m.get("key") for m in state()["shell"].get("mfrs") or []]:
                    break
                time.sleep(0.5)
            api("ui.pick_manufacturer", "stern")
            try:
                api("shellx.getting_started_close")
            except Exception:                              # noqa: BLE001
                pass
            time.sleep(1.5)
            api("ui.select_tab", "emulate")
            time.sleep(2)
            if after:
                api("ui.set", "emulate", "launch_hold", True)
                time.sleep(1)
                print("launch_hold:", state()["emulate"].get("launch_hold"), flush=True)
            card = page.locator(".emu-card").first
            if not card.count():
                page.screenshot(path=os.path.join(out_dir, "..", "pad1487_debug.png"))
                print("NO CARD; page errors:", errors, flush=True)
                return
            if after:
                page.get_by_text("Hold the ball in the shooter lane").first.hover()
                time.sleep(1.5)
            box = card.bounding_box()
            clip = {"x": max(0, box["x"] - 8), "y": max(0, box["y"] - 8),
                    "width": min(1440 - box["x"] + 8, box["width"] + (360 if after else 16)),
                    "height": min(900, box["height"] + (260 if after else 16))}
            page.screenshot(path=os.path.join(out_dir, tag + "emulate_hold.png"), clip=clip)
            print("saved", tag + "emulate_hold.png", "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
