"""PAD-529 proof shots: the JJP security key on another PC (USB/IP).

    python scripts/shot_pad529.py <repo> <out_dir> [--after]

Serves <repo> against a scratch settings folder and photographs, under the
same names before and after:

- emulate_jjp.png  JJP Emulate tab.  After (--after): a "Security key" card
                   set to "On another PC", pointed at the stand-in key server
                   (start it first, see tools/jjp_emu/README.md) and Test
                   pressed.
- extract_jjp.png  JJP Extract tab with "Decrypt using the game's HASP
                   dongle" ticked.  After: the line under it says where the
                   key is taken from.

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
    scratch = tempfile.mkdtemp(prefix="pad529-")
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
            time.sleep(1.5)

            def snap(name):
                page.mouse.move(1430, 890)          # no hover tips
                time.sleep(0.8)
                page.screenshot(path=os.path.join(out_dir, tag + name))
                print("saved", tag + name, flush=True)

            api("ui.select_tab", "emulate_jjp")
            time.sleep(1.5)
            if after:
                # the stand-in key server (tools/jjp_emu/usbip_standin.py,
                # --port 3241 --bus 1-4) answers Test for real
                api("ui.set", "emulate_jjp", "key_where", "usbip")
                api("ui.set", "emulate_jjp", "key_server", "127.0.0.1:3241")
                api("ui.set", "emulate_jjp", "key_busid", "1-4")
                time.sleep(1.0)
                api("emulate_jjp.test_key")
                end = time.time() + 60
                while time.time() < end:
                    msg = state()["emulate_jjp"].get("key_msg") or ""
                    if not msg.startswith("Asking"):
                        break
                    time.sleep(0.5)
                print("key_msg:", msg, flush=True)
            snap("emulate_jjp.png")

            api("ui.select_tab", "extract")
            time.sleep(1.5)
            api("ui.set", "extract", "dongle", True)
            time.sleep(1.0)
            snap("extract_jjp.png")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
