r"""PAD-1379 proof shots: the Expression lights tab on a Spike 3 card's project (Fallout LE 0.82).

    python scripts/shot_pad1379.py <app tree> <out png>

A scratch project made from the library's Fallout LE 0.82 card, with three stand-in songs in its audio folder (one
of image.bin's, two of the music banks', ``music_cat01_0000`` and ``music_cat41_0001``: beat-like tones, not the
game's music) and one show of the project's on bank 1's song, served by <app tree> (main for the before shot, the
ticket's branch for the after). Prints the tab's lines that say whether the game takes shows and which songs it lists.
"""
import json
import math
import os
import struct
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
SONGS = (("audio/idx0412 - music - Vault Theme.wav", 70, 1.9),
         ("audio/music_cat01_0000.wav", 95, 2.1),
         ("audio/music_cat41_0001.wav", 64, 1.6))
SHOW = {"name": "Vault 33", "slot": -((1 << 16 | 0) + 1), "loop": True,
        "blades": [{"fx": "chase_up", "ms": 4000, "a": "#1e90ff", "b": "#000000", "rate": 6, "blend": 0},
                   {"fx": "pulse", "ms": 4000, "a": "#ffd700", "b": "#1e90ff", "rate": 4, "blend": 300}],
        "speakers": [{"fx": "solid", "ms": 8000, "a": "#ffd700", "b": "#000000", "rate": 0, "blend": 0}]}


def _song(path, seconds, beat):
    """A stand-in song: a tone whose loudness pulses on a beat (a waveform with bars to see)."""
    rate = 22050
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            t = i / rate
            env = 0.25 + 0.75 * math.exp(-6 * ((t * beat) % 1.0))
            frames += struct.pack("<h", int(12000 * env * math.sin(2 * math.pi * 220 * t)))
        w.writeframes(bytes(frames))


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1379-")
    project = os.path.join(scratch, "project")
    os.makedirs(os.path.join(project, "audio"))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    for rel, secs, beat in SONGS:
        _song(os.path.join(project, rel), secs, beat)
    sys.path.insert(0, repo)
    from pinball_decryptor.core import staged_changes
    staged_changes.save(project, {"cab_shows": {"shows": [SHOW]}})
    launcher = os.path.join(scratch, "launch1379.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "audio")          # the scan the song list is read from
            time.sleep(12)
            webui_shot.api(url, "ui.select_tab", "lights")
            time.sleep(30)                       # the card's program read (a Spike 3 card: its encrypted volume)
            for line in page.inner_text("body").splitlines():
                low = line.lower()
                if any(w in low for w in ("expression", "cabinet", "cannot", "spike 3", "music_cat", "idx0412",
                                          "vault")):
                    print("page:", line.strip()[:240], flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
