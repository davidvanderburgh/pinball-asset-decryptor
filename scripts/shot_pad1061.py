"""PAD-1061 proof shot: a sound's Type, changed in Audio Properties, after the app is closed and opened again.

    python scripts/shot_pad1061.py <repo> <out.png>

Serves <repo> on a scratch project of tiny WAVs whose callouts.csv marks four sounds as speech (one named, three
not), so the Type column reads Callouts for them.  The first run changes idx0002 (no name) and idx0001 (named) to
Sound FX in Audio Properties (audio.rename, what OK does), then the server is stopped and started again on the same
scratch settings folder - closing and reopening the app - and the tab is shot.  Before (main) idx0002 is back to
Callouts; after, both stay Sound FX.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import struct
import sys
import tempfile
import time
import wave

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
NAMES = ("idx0001 - Shoot the ramp.wav", "idx0002.wav", "idx0003.wav", "idx0004.wav", "idx0005 - SE FX POP BUMPER.wav")
CHANGED = ("audio/idx0002.wav", "audio/idx0001 - Shoot the ramp.wav")


def _wav(path, seconds):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        n = int(seconds * 8000)
        w.writeframes(b"".join(struct.pack("<h", 2000 if i % 16 < 8 else -2000) for i in range(n)))


def _serve(repo, settings, scratch, launcher):
    import site
    return webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                   extra_env={"PYTHONPATH": site.getusersitepackages()})


def _types(url):
    return {r["k"]: r.get("type") for r in webui_shot.state(url)["audio"]["rows"]}


def _open_tab(url):
    webui_shot.api(url, "ui.pick_manufacturer", "stern")
    webui_shot.api(url, "ui.select_tab", "audio")
    for _ in range(60):
        time.sleep(1)
        st = webui_shot.state(url)["audio"]
        if len(st["rows"]) == len(NAMES) and not st["scanning"]:
            return


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    print("repo", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1061-")
    project = os.path.join(scratch, "project")
    os.makedirs(os.path.join(project, "audio"))
    for i, name in enumerate(NAMES):
        _wav(os.path.join(project, "audio", name), 0.4 + 0.3 * i)
    with open(os.path.join(project, "callouts.csv"), "w", encoding="utf-8") as f:
        f.write("folder,file,seconds,classification,text\n")
        for name in NAMES[:4]:
            f.write("audio,%s,1.0,speech,\n" % name)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(project)
    launcher = os.path.join(scratch, "launch1061.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project,
                                               "write_output": scratch}}}, f)
    # first run: change the two callouts to Sound FX
    proc, url = _serve(repo, settings, scratch, launcher)
    try:
        _open_tab(url)
        print("opened:", _types(url), flush=True)
        for rel in CHANGED:
            label = rel.rpartition(" - ")[2][:-4] if " - " in rel else ""
            webui_shot.api(url, "audio.rename", rel, label, "sfx")
        print("changed:", _types(url), flush=True)
    finally:
        proc.terminate()
        proc.wait(30)
    time.sleep(2)
    # second run: the app opened again
    proc, url = _serve(repo, settings, scratch, launcher)
    try:
        _open_tab(url)
        print("reopened:", _types(url), flush=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 820})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(4)
            page.mouse.move(5, 815)
            time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
