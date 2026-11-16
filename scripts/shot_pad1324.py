"""PAD-1324 proof shots: MUSIC MODES on Spike 3 cards (scripts/shot_pad945.py's rig).

    python scripts/shot_pad1324.py <repo> <out_dir> [--after]

Serves <repo> on two scratch Spike 3 projects: Fallout LE 0.82 (PAD1324_FALLOUT, default
C:\\tmp\\PAD-1323\\proj_fo, a stock audio extract: a few of its sounds, its .extract_source.json and its sound
request map) and Pokemon LE 0.82 (PAD1324_POKEMON, default C:\\tmp\\PAD-1289\\proj_back: its card record, with
Fallout's few sounds, as only the card decides what the tab offers), each with one music file set for mode 2
on its first sound. Writes <before_|after_>audio_music_menu.png (Fallout: that sound's right-click menu with
its Music modes submenu open) and <before_|after_>audio_music_why.png (Pokemon: the same submenu's "Why not
this sound?" answer).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import glob
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
FALLOUT = os.environ.get("PAD1324_FALLOUT", r"C:\tmp\PAD-1323\proj_fo")
POKEMON = os.environ.get("PAD1324_POKEMON", r"C:\tmp\PAD-1289\proj_back")
SOUNDS = ["idx%04d" % i for i in (0, 1, 2, 3, 5, 8)]
TONE = os.environ.get("PAD1324_TONE", r"C:\tmp\PAD-1324\tones\tone700.wav")


def _project(scratch, src, name, audio_src=None):
    """A scratch project of *src*'s card with a few of *audio_src*'s sounds (default *src*'s)."""
    audio_src = audio_src or src
    dst = os.path.join(scratch, name)
    os.makedirs(os.path.join(dst, "audio"))
    for n in (".extract_source.json", "sound_requests.tsv"):
        if os.path.exists(os.path.join(src, n)):
            shutil.copy2(os.path.join(src, n), os.path.join(dst, n))
    lines, names = [], []
    for stem in SOUNDS:
        n = os.path.basename(sorted(glob.glob(os.path.join(audio_src, "audio", stem + "*.wav")))[0])
        names.append(n)
        shutil.copy2(os.path.join(audio_src, "audio", n), os.path.join(dst, "audio", n))
        with open(os.path.join(dst, "audio", n), "rb") as f:
            lines.append("audio/%s\t%s\n" % (n, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"sound_modes": {"names": ["Standard", "Custom A"],
                                   "slots": {"audio/" + names[0]: {"2": TONE}}, "levels": {}}}, f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch1324.py")
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


def _shoot(repo, project, shot, why):
    proc, url = _serve(repo, os.path.dirname(project), project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
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
            print("audio rows:", len(st.get("rows") or []), flush=True)
            row = page.locator(".tr:has-text('%s')" % SOUNDS[0]).first
            row.click()
            time.sleep(2)
            page.evaluate("() => document.querySelectorAll('audio').forEach((a) => { a.pause(); })")
            row.click(button="right")
            time.sleep(1)
            print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            page.locator(".menu .mi:has-text('Music modes')").first.hover()
            time.sleep(1.2)
            print("submenu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            if why:
                item = page.locator(".menu .mi:has-text('Why not this sound')").first
                if item.count():
                    item.click()
                    time.sleep(1.2)
                    print("why:", page.locator(".modal").first.inner_text()[:400], flush=True)
            page.screenshot(path=shot)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


def main():
    repo, out_dir = sys.argv[1:3]
    tag = "after_" if "--after" in sys.argv else "before_"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1324-")
    try:
        fo = _project(os.path.join(scratch, "fo"), FALLOUT, "fallout_le_082")
        _shoot(repo, fo, os.path.join(out_dir, tag + "audio_music_menu.png"), why=False)
        pk = _project(os.path.join(scratch, "pk"), POKEMON, "pokemon_le_082", audio_src=FALLOUT)
        _shoot(repo, pk, os.path.join(out_dir, tag + "audio_music_why.png"), why=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
