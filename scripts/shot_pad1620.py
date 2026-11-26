"""PAD-1620 (PR #51) proof shots: Grow on the machine... on the Test card tab and the Multi-boot tab.

    python scripts/shot_pad1620.py <repo to run> <out dir> --prefix before|after

Serves <repo> on a scratch settings folder (Stern picked, a remembered machine at 192.168.1.141 so the network
buttons are live) and shoots <prefix>_testcard.png and <prefix>_multiboot.png; where the repo has a Grow button,
its tooltip is hovered open for the shot.  Nothing talks to a machine: no button is pressed.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

W, H = 1500, 1000


def main():
    repo, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    prefix = sys.argv[sys.argv.index("--prefix") + 1] if "--prefix" in sys.argv else "after"
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1620-")
    keys = os.path.join(scratch, "cfg", "pinball_decryptor", "remote_access")
    os.makedirs(keys, exist_ok=True)
    with open(os.path.join(keys, "machines.json"), "w", encoding="utf-8") as f:
        json.dump({"address": "192.168.1.141"}, f)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, extra_env={"PYTHONPATH": repo + os.pathsep + site.getusersitepackages(),
                                      "PAD_UI_NO_RIG": "1"},
        app_cmd=[sys.executable, "-c", "import sys; sys.path.insert(0, %r); "
                 "from pinball_decryptor.webui import host; sys.exit(host.main(sys.argv[1:]))" % repo])
    from playwright.sync_api import sync_playwright
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": W, "height": H})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for tab in ("testcard", "multiboot"):
                webui_shot.api(url, "ui.select_tab", tab)
                time.sleep(5)
                page.mouse.move(5, 5)
                grow = page.get_by_role("button", name="Grow on the machine…")
                if grow.count():
                    grow.first.scroll_into_view_if_needed()
                    grow.first.hover(force=True)
                    time.sleep(1.5)
                    print(tab, "grow button enabled:", grow.first.is_enabled(), flush=True)
                else:
                    print(tab, "has no Grow button", flush=True)
                path = os.path.join(out, "%s_%s.png" % (prefix, tab))
                page.screenshot(path=path)
                print("saved", path, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
