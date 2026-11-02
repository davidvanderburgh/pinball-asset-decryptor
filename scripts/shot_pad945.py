"""PAD-945 proof shots: SOUNDS ON SHOTS in the game's own modes (scripts/shot_pad638.py's rig).

    python scripts/shot_pad945.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Venom LE 1.07 project made from a stock audio extract (PAD945_EXTRACT,
default C:\\tmp\\PAD-945\\venom: a few of its sounds, its .extract_source.json and its sound request
map). The project's record already has one sound on a shot: idx0002 (a sound no request of the game's
plays) on Left orbit in Grendel Mode. Writes <before_|after_>audio_menu.png (the right-click menu of
that sound) and <before_|after_>shots_window.png (after: the Sounds on shots window its "Play on a
shot in one of the game's modes…" opens; before, main has neither, so the tab as it is).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
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
EXTRACT = os.environ.get("PAD945_EXTRACT", r"C:\tmp\PAD-945\venom")
SOUNDS = ["idx%04d.wav" % i for i in (0, 2, 5, 6, 8, 17, 21, 31, 41, 45, 50, 51, 56, 57)]
UNUSED = "idx0002.wav"


def _project(scratch):
    dst = os.path.join(scratch, "venom_le_107")
    os.makedirs(os.path.join(dst, "audio"))
    for name in (".extract_source.json", "sound_requests.tsv", "sound_test_names.csv"):
        shutil.copy2(os.path.join(EXTRACT, name), os.path.join(dst, name))
    lines = []
    for name in SOUNDS:
        shutil.copy2(os.path.join(EXTRACT, "audio", name), os.path.join(dst, "audio", name))
        with open(os.path.join(dst, "audio", name), "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"sound_modes": {"names": [], "slots": {}, "shots": [
            {"mode": 16, "mode_name": "Grendel Mode", "switch": 99, "switch_name": "Left orbit",
             "file": os.path.join(dst, "audio", "idx0006.wav")}]}}, f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch945.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait_scan(state, limit=180):
    deadline = time.time() + limit
    while time.time() < deadline:
        st = state().get("audio") or {}
        if st.get("rows") and not st.get("scanning") and "still checking" not in (st.get("status") or ""):
            return st
        time.sleep(1)
    return state().get("audio") or {}


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad945-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tag = "after_" if after else "before_"
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731
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
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            st = _wait_scan(state)
            print("audio rows:", len(st.get("rows") or []), "shots:", st.get("shots"), flush=True)
            row = page.locator(".tr:has-text('%s')" % UNUSED).first
            row.click()
            time.sleep(2)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            row.click(button="right")
            time.sleep(1)
            print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            page.screenshot(path=out("audio_menu.png"))
            item = page.locator(".menu .mi:has-text('Play on a shot')").first
            if item.count():
                item.click()
                time.sleep(1.5)
                print("window:", page.locator(".modal").first.inner_text()[:400], flush=True)
            else:
                page.keyboard.press("Escape")
                time.sleep(0.8)
            page.screenshot(path=out("shots_window.png"))
            print("page errors:", errors, flush=True)
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
