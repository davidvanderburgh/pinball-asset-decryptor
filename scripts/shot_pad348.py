"""PAD-348 proof shot: the Scenes preview's three colour switches come back as they were
left, not all on.

    python scripts/shot_pad348.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder, seeds the settings copy with
what a user who left the whole screen overlay and the machine screen off saves
(``look_switches``), launches <repo>, opens Scenes on KAIJU BATTLE SELECT and snaps
<out_png>.  A build without PAD-348 ignores the saved switches and shows all three on.
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
import shot_pad251_tab as rig  # noqa: E402

LEFT = {"scenes": {"overlay": False, "files": True, "screen": False}}


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad348-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "look_switches": LEFT,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    launcher = os.path.join(scratch, "launch348.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(rig.LAUNCHER % repo)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            assert api("text_scenes.select", rig.BATTLE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(4)
            print("switches:", (state().get("look") or {}).get("sw"), flush=True)
            page.screenshot(path=out)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
