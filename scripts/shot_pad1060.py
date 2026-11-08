"""PAD-1060 proof shots: Audio Properties renames that change only the case.

    python scripts/shot_pad1060.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project made here (sounds named the way a
tester's Venom LE project names them), selects "... - ONE", presses F2, types
"One" and presses OK.  Then it clears a second sound's name while switching
its Type and presses OK.  Writes, under the same name before and after:

- <before_|after_>audio_case_rename.png   right after OK on "ONE" -> "One"
- <before_|after_>audio_clear_name.png    right after OK on the cleared name

and prints the audio folder's file names at the end.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
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

SOUNDS = (
    "00m00s780 - idx2268 - ONE.wav",
    "00m00s602 - idx2376 - Four.wav",
    "00m00s762 - idx2724 - Argh!.wav",
    "00m03s385 - idx0614 - million plus pops.wav",
)


def _wav(path, amp):
    n = int(0.6 * 22050)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", amp if i % 40 < 20 else -amp)
                               for i in range(n)))


def _project(scratch):
    dst = os.path.join(scratch, "venom")
    os.makedirs(os.path.join(dst, "audio"))
    lines = []
    for i, name in enumerate(SOUNDS):
        p = os.path.join(dst, "audio", name)
        _wav(p, 2000 + 300 * i)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    return dst


def _props(page, row_text):
    page.locator(".tr").filter(has_text=row_text).first.click()
    time.sleep(0.6)
    page.keyboard.press("F2")
    page.wait_for_selector(".modal input", timeout=10000)
    time.sleep(0.6)


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1060-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
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
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            S._wait_scan(state)
            time.sleep(2)

            _props(page, "idx2268")
            page.locator(".modal input").first.fill("One")
            page.get_by_role("button", name="OK").first.click()
            time.sleep(1.5)
            page.screenshot(path=out("audio_case_rename.png"))
            print("shot", out("audio_case_rename.png"), flush=True)
            ok = page.get_by_role("button", name="OK")
            if ok.count():
                ok.first.click()
                time.sleep(0.8)

            _props(page, "idx2376")
            page.locator(".modal input").first.fill("")
            sel = page.locator(".modal select")
            if sel.count():
                cur = sel.first.input_value()
                sel.first.select_option("sfx" if cur != "sfx" else "music")
            page.get_by_role("button", name="OK").first.click()
            time.sleep(1.5)
            page.screenshot(path=out("audio_clear_name.png"))
            print("shot", out("audio_clear_name.png"), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
    print("files after:", sorted(os.listdir(os.path.join(project, "audio"))), flush=True)


if __name__ == "__main__":
    main()
