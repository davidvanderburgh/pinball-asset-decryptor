"""PAD-1388 proof shots: the Mod Pack tab's "Move Your Mods to Another Card".

    python scripts/shot_pad1388_port.py <repo> <project> <out_png> [<new.raw> <build_dir> [news]]

Serves <repo> with <project> (an extract folder; use a scratch COPY, the server
may write caches into it) as the Stern project, opens the Mod Pack tab and
photographs the transfer card.  With <new.raw> and <build_dir> the port form's
fields are filled (the after build has them; the before build ignores them),
and with ``news`` What's new is pressed and the shot waits for its answer (put
a finished extract at ``<build_dir>/<raw stem> extract`` to skip extracting).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, project, out = sys.argv[1:4]
    raw = sys.argv[4] if len(sys.argv) > 4 else ""
    build = sys.argv[5] if len(sys.argv) > 5 else ""
    news = len(sys.argv) > 6 and sys.argv[6] == "news"
    scratch = tempfile.mkdtemp(prefix="pad1388-")
    launcher = os.path.join(scratch, "launch1388.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1700})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1.5)
            api("ui.select_tab", "modpack")
            time.sleep(2)
            if raw:
                api("ui.set", "modpack", "port_imgs", raw)
                api("ui.set", "modpack", "port_out", build)
                time.sleep(4)          # the card's own version, off the loop
            if news:
                import threading
                threading.Thread(target=lambda: api("modpack.whats_new"),
                                 daemon=True).start()
                deadline = time.time() + 3600
                while time.time() < deadline:
                    st = webui_shot.state(url).get("modpack") or {}
                    if st.get("news") and not st.get("running"):
                        break
                    time.sleep(3)
                time.sleep(2)
                page.keyboard.press("Escape")       # the "done" message box
                time.sleep(1)
            card = page.locator("section.card").nth(1)
            card.scroll_into_view_if_needed()
            time.sleep(1)
            card.screenshot(path=out)
            print("saved", out, flush=True)
            if news:
                print(json.dumps((webui_shot.state(url).get("modpack") or {})
                                 .get("news"), indent=1)[:3000])
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
