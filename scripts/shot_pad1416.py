"""PAD-1416 proof shot: the security key in a JJP machine on the network.

    python scripts/shot_pad1416.py <repo> <out_dir> [--after]

Serves <repo> against a scratch settings folder and photographs the JJP
Emulate tab's "Security key" card set to "On another PC (network)" with only a
machine's address typed and the Bus ID left empty, as someone with a key
sharing machine fills it in.  Before: refused, a bus ID is required.  After:
accepted ("the key on <machine>"), with the button that writes the key
sharing stick.  Saved as before_/after_emulate_jjp_key.png.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

MACHINE = "192.168.1.50"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    tag = "after_" if after else "before_"
    scratch = tempfile.mkdtemp(prefix="pad1416-")
    webui_shot.REPO = repo
    env = {"PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""),
                                          "Python")}
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
                if "jjp" in keys:
                    break
                time.sleep(0.5)
            api("ui.pick_manufacturer", "jjp")
            try:
                api("shellx.getting_started_close")   # a fresh settings folder opens it
            except Exception:                              # noqa: BLE001
                pass
            time.sleep(1.5)
            api("ui.select_tab", "emulate_jjp")
            time.sleep(1.5)
            api("ui.set", "emulate_jjp", "key_where", "usbip")
            api("ui.set", "emulate_jjp", "key_server", MACHINE)
            api("ui.set", "emulate_jjp", "key_busid", "")
            time.sleep(1.5)
            print("key_msg:", state()["emulate_jjp"].get("key_msg"), flush=True)
            page.mouse.move(1430, 890)
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out_dir, tag + "emulate_jjp_key.png"))
            print("saved", tag + "emulate_jjp_key.png", "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
