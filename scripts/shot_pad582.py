"""PAD-582 proof shots: a Stern SAM code update and its extracted sounds.

    python scripts/shot_pad582.py <repo> <out_dir> --input <game .bin>
        --project <extracted project folder> [--after]

Serves <repo> on a scratch settings file whose Stern Extract input / Write
original is the SAM file and whose project is <project> (a folder the
SAM Extract has filled: audio/idxNNNN.wav + .checksums.md5), and writes,
under the same names before and after:

- extract.png   the Extract tab with that file picked
- audio.png     the Replace Audio tab (no such tab for SAM before)
- write.png     the Write tab

Nothing is extracted or written.  Needs Playwright (the user site-packages
one) and the installed Edge.
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
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    src = sys.argv[sys.argv.index("--input") + 1]
    project = sys.argv[sys.argv.index("--project") + 1]
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad582-")
    launcher = os.path.join(scratch, "launch582.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    built = scratch
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": src, "extract_output": project,
                       "write_original": src, "write_assets": project,
                       "write_output": built}}}, f)
    print("serving", repo, "input", src, "project", project, flush=True)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            for tab, name in (("extract", "extract.png"),
                              ("audio", "audio.png"),
                              ("write", "write.png")):
                try:
                    api("ui.select_tab", tab)
                except Exception as e:                      # noqa: BLE001
                    print(tab, "not selectable:", e, flush=True)
                time.sleep(6)
                page.mouse.move(5, 940)
                time.sleep(0.5)
                page.screenshot(path=out(name))
                st = webui_shot.state(url)
                shell = st.get("shell") or {}
                print(tab, "shown tab:", shell.get("tab"), "era:",
                      (shell.get("mfr") or {}).get("era"), flush=True)
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
