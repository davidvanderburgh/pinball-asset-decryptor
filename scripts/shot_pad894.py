"""PAD-894 proof shots: Audio > More > Rename from callouts.csv.

    python scripts/shot_pad894.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project made here: eight sounds named the way
Auto-name call-outs names them ("idx0042 - <what Whisper heard>.wav"), and a
callouts.csv whose text column has been corrected by hand.  Writes, under the
same name before and after:

- <before_|after_>audio_more_menu.png   the Audio tab with More opened
- <before_|after_>audio_list.png        the list after (in the after run)
                                        Rename from callouts.csv… was pressed
                                        and its question answered Yes

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import csv
import hashlib
import os
import struct
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import webui_shot  # noqa: E402

# (index, what Whisper heard, what the player corrected it to)
SOUNDS = (
    (42, "Shoot the a wreck for bonus", "Shoot the ARC for bonus!"),
    (200, "Jack pot", "JACKPOT!"),
    (311, "Kai Joo award", "Kaiju award"),
    (417, "Super jack pot is lit", "Super Jackpot is lit"),
    (419, "Go so long", "Godzilla!"),
    (431, "Monster lock is lit", "Monster lock is lit"),
    (494, "Double scoring", "Double scoring: 2x"),
    (667, "Mecca Godzilla", "Mechagodzilla?"),
)


def _wav(path, seconds=0.6, rate=22050):
    n = int(seconds * rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", 3000 if i % 40 < 20 else -3000)
                               for i in range(n)))


def _project(scratch):
    dst = os.path.join(scratch, "godzilla")
    os.makedirs(os.path.join(dst, "audio"))
    lines, rows = [], []
    for idx, heard, fixed in SOUNDS:
        name = "idx%04d - %s.wav" % (idx, heard)
        p = os.path.join(dst, "audio", name)
        _wav(p)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
        rows.append(["audio", name, "0.600", "speech", fixed])
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, "callouts.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["folder", "file", "seconds", "classification", "text"])
        w.writerows(rows)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad894-")
    # names the rename remembers go to the scratch APPDATA the server runs
    # under, never David's own audio_names.json
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            time.sleep(2)
            page.get_by_role("button", name="More").first.click()
            time.sleep(1)
            page.screenshot(path=out("audio_more_menu.png"))
            print("shot", out("audio_more_menu.png"), flush=True)
            item = page.get_by_text("Rename from callouts.csv…", exact=True)
            if after and item.count():
                item.first.click()
                time.sleep(1.5)
                page.get_by_role("button", name="Yes").first.click()
                time.sleep(2)
                ok = page.get_by_role("button", name="OK")
                if ok.count():
                    ok.first.click()
                time.sleep(1.5)
            else:
                page.keyboard.press("Escape")
                time.sleep(1)
            rows = [r["k"] for r in (state().get("audio") or {}).get("rows") or [] if not r.get("g")]
            print("rows:", rows, flush=True)
            print("on disk:", sorted(os.listdir(os.path.join(project, "audio"))), flush=True)
            page.screenshot(path=out("audio_list.png"))
            print("shot", out("audio_list.png"), "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
