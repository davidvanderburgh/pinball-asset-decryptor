"""PAD-455 proof shots: the Video tab names the sound files the game plays with a clip.

    python scripts/shot_pad455.py <repo> <out_dir> [--after]

Serves <repo> on a SCRATCH Godzilla Pro 1.16 project: a few clips of the stock extract
(``D:\\Pinball\\gz116_bottleneck\\stock116``, with their manifest rows), the audio and
``sound_requests.tsv`` of an extract made with the PAD-455 build (``PAD455_AUDIO``, its files
hard-linked: same volume), and the stock Pro 1.16 card as its source so the tab can read the
card's game program. Writes, under the same names before and after:

- video_clip_sounds.png   monster_zero_intro selected: sounds its code asks for right after it,
                          and the one named after it
- video_clip_record.png   adv_fighter2 selected: the sound its display effect keeps with it

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
import shot_pad312 as base  # noqa: E402

STOCK = os.environ.get("PAD455_EXTRACT", r"D:\Pinball\gz116_bottleneck\stock116")
AUDIO = os.environ.get("PAD455_AUDIO", r"D:\Pinball\pad455_extract\gzpro116")
CARD = os.environ.get("PAD455_CARD", r"D:\Pinball\images\Stern\spike2"
                      r"\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
SCRATCH = os.environ.get("PAD455_SCRATCH", r"D:\Pinball\pad455_shots")
CLIPS = ("monster_zero_intro", "mt_fuji_loop", "adv_fighter2", "adv_fighter3", "rampage1",
         "rampage2", "BridgeAttack_1", "extra_ball", "tilt_warning", "Godzilla_TrainStomp",
         "Godzilla_TrainCrash", "match")
SCREENS = {"video_clip_sounds": "monster_zero_intro.mp4", "video_clip_record": "adv_fighter2.mp4"}


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _project(scratch):
    dst = os.path.join(scratch, "gz116pro")
    vid = os.path.join(dst, "video")
    aud = os.path.join(dst, "audio")
    os.makedirs(vid)
    os.makedirs(aud)
    rows, sums = ["# output\tcard path\tbytes"], []
    with open(os.path.join(STOCK, "video", "manifest.txt"), encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 2 or line.startswith("#") or os.path.splitext(cols[0])[0] not in CLIPS:
                continue
            os.link(os.path.join(STOCK, "video", cols[0]), os.path.join(vid, cols[0]))
            rows.append("\t".join(cols))
            sums.append("video/%s\t%s" % (cols[0], _md5(os.path.join(vid, cols[0]))))
    with open(os.path.join(vid, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    for n in os.listdir(os.path.join(AUDIO, "audio")):
        os.link(os.path.join(AUDIO, "audio", n), os.path.join(aud, n))
    shutil.copy2(os.path.join(AUDIO, "sound_requests.tsv"), dst)
    st = os.stat(CARD)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "size": st.st_size, "mtime": int(st.st_mtime), "card_version": "1.16.0"}, f)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch455.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(base.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project,
                                               "extract_input": CARD}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python"),
                   "PAD_TITLE_CACHE": os.path.join(scratch, "titles")})


def _shot(repo, out, after):
    os.makedirs(SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad455-", dir=SCRATCH)
    project = _project(scratch)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open.video', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video")
            # the card's game program is read once, off the UI thread
            deadline = time.time() + 180
            while time.time() < deadline:
                if ((state().get("video") or {}).get("modes") or {}).get("ready"):
                    break
                time.sleep(1)
            for screen, rel in SCREENS.items():
                page.locator(".vid-tbl .tr:has-text('%s')" % rel).first.click()
                time.sleep(3)
                page.mouse.move(5, 990)
                time.sleep(0.6)
                page.screenshot(path=os.path.join(
                    out, ("after_" if after else "before_") + screen + ".png"))
                v = state().get("video") or {}
                pv = v.get("preview") or {}
                print(screen, "preview:", pv.get("rel"), json.dumps(pv.get("sounds")), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    repo, out = sys.argv[1:3]
    os.makedirs(out, exist_ok=True)
    _shot(repo, out, "--after" in sys.argv)


if __name__ == "__main__":
    main()
