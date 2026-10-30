"""PAD-869 proof shot: the Text tab on a Stern Spike 1 (KISS) project, with
the song names renamed (before: Spike 1 had no Text tab at all).

    python scripts/shot_pad869.py <repo> <out_dir> <prefix> <card> <project>

Writes <prefix>_text_tab.png.  Serves <repo>'s app against a scratch settings
folder, the Stern section pointed at *card* (a Spike 1 .iso) and *project*
(a folder holding the text/strings.tsv a Spike 1 extract writes), the era set
to Spike 1 and the Text tab's Show filter on Changed.
"""
import json
import os
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
    repo, out_dir, prefix, card, project = sys.argv[1:6]
    print("repo", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad869-")
    launcher = os.path.join(scratch, "launch869.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "theme": "dark",
                   "manufacturers": {"stern": {"extract_input": card,
                                               "write_original": card,
                                               "extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1.5)
            webui_shot.api(url, "ui.set_era", "spike1")
            time.sleep(1.5)
            tabs = {t["ns"]: t for t in webui_shot.state(url)["shell"]["tabs"]}
            shown = [ns for ns, t in tabs.items() if t.get("visible")]
            print("visible tabs", shown, flush=True)
            if tabs.get("text", {}).get("visible"):
                webui_shot.api(url, "ui.select_tab", "text")
                time.sleep(4.0)
                webui_shot.api(url, "text.set_show", "Changed")
                time.sleep(1.5)
                st = webui_shot.state(url)["text"]
                print("rows", len(st.get("rows") or []), "shown",
                      len(st.get("view") or []), flush=True)
            else:
                # Spike 1 had no Text tab: the Extract tab is where it lands
                webui_shot.api(url, "ui.select_tab", "extract")
                time.sleep(2.0)
            page.mouse.move(5, 880)
            page.screenshot(path=os.path.join(out_dir,
                                              "%s_text_tab.png" % prefix))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
