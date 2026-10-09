"""PAD-460 proof shots: the voice-recognition quality beside Auto-name call-outs on the Extract
tab, and naming the sounds of a project that is already extracted.

    python scripts/shot_pad460.py <repo> <out_dir> <prefix> [<speech_dir>]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  A scratch project holds a small Godzilla extract (short silent WAVs with a
baseline, plus every WAV in <speech_dir> as a spoken call-out: e.g. two lines made with
Windows text-to-speech), Auto-name call-outs is ticked and the saved quality is High.
Writes into <out_dir>:

- <prefix>_extract_naming.png  the Extract tab, the Naming section in view
- <prefix>_gear_menu.png       the ⚙ settings menu open
- <prefix>_audio_names.png     the Audio tab after pressing Auto-name now (a real run, at
                               Standard so it uses the small cached model); a tree without
                               the button shows the project as extracted
"""

import json
import os
import shutil
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

CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


def _project(scratch, speech_dir=""):
    project = os.path.join(scratch, "Godzilla LE 1.16")
    audio = os.path.join(project, "audio")
    os.makedirs(audio)
    for i in range(1, 7):
        name = "idx%04d.wav" % i
        with wave.open(os.path.join(audio, name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(struct.pack("<h", 0) * 2205)
    spoken = sorted(f for f in os.listdir(speech_dir)
                    if f.lower().endswith(".wav")) if speech_dir else []
    for k, f in enumerate(spoken):
        name = "idx%04d.wav" % (7 + k)
        shutil.copyfile(os.path.join(speech_dir, f), os.path.join(audio, name))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(scratch, CARD), "input_name": CARD}, f)
    # the baseline last, as an extract writes it (the files read as unchanged)
    from pinball_decryptor.core.checksums import generate_checksums
    generate_checksums(project)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    speech_dir = os.path.abspath(sys.argv[4]) if len(sys.argv) > 4 else ""
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    scratch = tempfile.mkdtemp(prefix="pad460-")
    project = _project(scratch, speech_dir)
    launcher = os.path.join(scratch, "launch460.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "voice_quality": "small.en",
                   "manufacturers": {"stern": {
                       "extract_output": project, "write_assets": project,
                       "extract_options": {"auto_name_callouts": True,
                                           "auto_name_music": False}}}}, f)
    import site
    print("serving", repo, flush=True)
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1.5)
            webui_shot.api(url, "ui.select_tab", "extract")
            time.sleep(3)
            naming = page.get_by_text("Naming", exact=True).first
            naming.scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, prefix + "_extract_naming.png"))
            st = webui_shot.state(url)
            x = st.get("extract", {})
            print("transcribe:", x.get("transcribe"), "quality:",
                  st.get("shellx", {}).get("voice_quality"),
                  "autoname_reason:", repr(x.get("autoname_reason")), flush=True)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(1.2)
            vq = page.get_by_text("Voice recognition quality")
            if vq.count():
                vq.first.hover()
                time.sleep(1.2)
            page.screenshot(path=os.path.join(out_dir, prefix + "_gear_menu.png"))
            print("gear:", [it.get("label") for it in
                            webui_shot.state(url)["shell"]["settings_items"]
                            if not it.get("sep")], flush=True)
            page.keyboard.press("Escape")
            time.sleep(0.5)

            # the real thing: Auto-name now over the extracted folder
            button = page.get_by_role("button", name="Auto-name now")
            if button.count():
                page.get_by_label("Voice recognition quality").select_option("tiny.en")
                time.sleep(1)
                button.first.click()
                end = time.time() + 600
                time.sleep(2)
                while time.time() < end and webui_shot.state(url)["shell"].get("running"):
                    time.sleep(1)
                print("after the run:", sorted(os.listdir(os.path.join(project, "audio"))),
                      flush=True)
                csv_path = os.path.join(project, "callouts.csv")
                if os.path.isfile(csv_path):
                    with open(csv_path, encoding="utf-8") as f:
                        print(f.read(), flush=True)
            else:
                print("no Auto-name now button on this tree", flush=True)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(3)
            page.screenshot(path=os.path.join(out_dir, prefix + "_audio_names.png"))
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
