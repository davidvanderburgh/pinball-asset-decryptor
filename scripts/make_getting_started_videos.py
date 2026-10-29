"""Film the Getting started page's videos (PAD-813) from the real app.

    python scripts/make_getting_started_videos.py [--only extract,song,...] [--shots-only]
                                                   [--render-only] [--work DIR]

Each video is a script of steps run against THIS checkout's web UI on a
scratch settings file (webui_shot.start_server), with Playwright clicking
the real controls.  Before each step the page is captured at 1600x900 with
the box of the control the step uses; scripts/getting_started/player.html
then turns the captures into motion (a camera that eases onto the control,
the cursor gliding to it and clicking, a caption per step, a title and a
recap card), rendered frame by frame into
pinball_decryptor/webui/static/videos/getting-started/<id>.mp4 (H.264,
1280x720, 30 fps) with a poster <id>.jpg.

The steps and captions follow webui/getting_started.py's TASKS.

Needs: Playwright + the installed Edge, ffmpeg, and the stock cards named in
CARDS (Deadpool Pro and Godzilla Pro 1.16, Stern's own releases).  The work
folder (default C:/tmp/Pinball) gets the extracted Deadpool project, which
later videos reuse.  Nothing is ever flashed: every Build / flash dialog is
shown and cancelled.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402
from pinball_decryptor.webui import getting_started as GS  # noqa: E402

PLAYER = os.path.join(HERE, "getting_started", "player.html")
LIB = r"D:\Pinball\images\Stern\spike2"
CARDS = {
    "deadpool": os.path.join(LIB, "deadpool_pro-1_16_0.Release.8G.sdcard.raw"),
    "godzilla": os.path.join(LIB, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"),
}
VW, VH = 1600, 900
FPS = 30

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


# ------------------------------------------------------------------ the app
class App:
    """The real app on a scratch settings file, a Playwright page on it."""

    def __init__(self, pw, work, settings, rig=False):
        self.scratch = tempfile.mkdtemp(prefix="pad813film-")
        launcher = os.path.join(self.scratch, "launch.py")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write(LAUNCHER % REPO)
        path = os.path.join(self.scratch, "settings.json")
        base = {"disclaimer_accepted": True, "theme": "dark", "getting_started_at_launch": False}
        base.update(settings)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(base, f)
        import site
        self.proc, self.url = webui_shot.start_server(
            path, os.path.join(self.scratch, "srv"), app_cmd=[sys.executable, launcher],
            extra_env={"PYTHONPATH": site.getusersitepackages(),
                       # real projects here: let the app write them
                       "PAD_UI_CAPTURE": "", "PAD_UI_NO_GETTING_STARTED": "1",
                       # the Emulate tab looks at this PC's emulator set-up
                       **({"PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": ""} if rig else {})})
        self.browser = pw.chromium.launch(channel="msedge")
        self.page = self.browser.new_page(viewport={"width": VW, "height": VH})
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); "
                                  "localStorage.setItem('pad.lang.seen', '1'); } catch (e) {}")
        self.page.goto(self.url)
        self.page.wait_for_function("window.__padReady === true", timeout=60000)
        time.sleep(1.5)

    def api(self, method, *args):
        return webui_shot.api(self.url, method, *args)

    def state(self, ns=None):
        st = webui_shot.state(self.url)
        return st.get(ns) or {} if ns else st

    def api_bg(self, method, *args):
        """A call that opens one of the page's own file pickers: it blocks
        until the picker is answered, so it runs on a thread."""
        out = {}
        th = threading.Thread(target=lambda: out.setdefault("r", self.api(method, *args)),
                              daemon=True)
        th.start()
        return th, out

    def answer_modal(self, value, kind=None, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            mods = (self.state().get("modals") or {}).get("open") or []
            if mods and (kind is None or mods[-1].get("kind") == kind):
                mid = mods[-1]["id"]
                base = self.url.split("/?")[0]
                token = self.url.split("t=")[1].split("&")[0]
                req = urllib.request.Request(
                    base + "/api/reply", data=json.dumps({"id": mid, "v": value}).encode(),
                    headers={"Content-Type": "application/json", "X-PAD-Token": token})
                with urllib.request.urlopen(req, timeout=60) as r:
                    r.read()
                return mods[-1]
            time.sleep(0.3)
        raise RuntimeError("no %s modal came up" % (kind or "modal"))

    def wait(self, pred, timeout=600, step=0.5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred():
                return True
            time.sleep(step)
        return False

    def close(self):
        try:
            self.browser.close()
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except Exception:                               # noqa: BLE001
                self.proc.kill()
            shutil.rmtree(self.scratch, ignore_errors=True)


class Film:
    """The steps of one video: a capture each, with its control's box."""

    def __init__(self, app, out_dir, vid):
        self.app, self.vid = app, vid
        self.dir = os.path.join(out_dir, vid)
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir)
        self.shots = []

    def box(self, target):
        if target is None:
            return None
        if isinstance(target, (list, tuple)):
            return list(target)
        loc = self.app.page.locator(target) if isinstance(target, str) else target
        loc = loc.first
        loc.scroll_into_view_if_needed(timeout=10000)
        b = loc.bounding_box(timeout=10000)
        return [round(b["x"]), round(b["y"]), round(b["width"]), round(b["height"])]

    def snap(self, caption, target=None, n=None, click=True, hold=None, zoom=None, settle=0.8,
             pull=False):
        time.sleep(settle)
        b = self.box(target)
        img = os.path.join(self.dir, "%02d.png" % len(self.shots))
        self.app.page.mouse.move(VW - 2, VH - 2)          # no hover look on the capture
        time.sleep(0.25)
        self.app.page.screenshot(path=img)
        shot = {"img": img, "caption": caption, "box": b, "n": n, "click": click and b is not None}
        if hold:
            shot["hold"] = hold
        if zoom is not None:
            shot["zoom"] = zoom
        if pull:
            shot["pull"] = True
        self.shots.append(shot)
        return shot

    def save(self, task):
        script = {"title": task["title"], "subtitle": SUBTITLES.get(self.vid, ""),
                  "recap": RECAPS.get(self.vid) or list(task["steps"]), "shots": self.shots}
        with open(os.path.join(self.dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump(script, f, indent=1)
        return script


SUBTITLES = {
    "extract": "A Deadpool Pro card, from the picker to a project folder.",
    "song": "Replace one tune on a Deadpool card with your own.",
    "build": "Turn your changes into a card the machine boots.",
    "flash": "Put a card image you already have onto an SD card.",
    "multiboot": "Deadpool and Godzilla on one SD card, with a menu at power-up.",
    "emulate": "Play the game on this PC before it goes near the machine.",
    "transfer": "New game code? Carry your mods onto it in one go.",
}
RECAPS = {
    "extract": ["Choose your manufacturer", "Select card: Browse… to the image", "Extract into a project folder"],
    "song": ["Replace Audio, Type: Music", "Right-click the song, Choose replacement…", "Compare, then build on Write"],
    "build": ["Write: Build / flash SD card…", "Tick build, flash or both", "Pick the SD card and start"],
    "flash": ["Write: Build / flash SD card…", "Image file: Browse… to the image", "Pick the SD card, Flash image"],
    "multiboot": ["Multi-boot: add your card images", "✎ dresses each menu card", "Build / flash card…"],
    "emulate": ["Emulate: Set up emulator… once", "Pick the card image", "Start emulator"],
    "transfer": ["Open the project with your mods", "Mod Pack: Port + build…", "Pick the new stock card"],
}


def rail_item(app, label):
    return app.page.locator(".rail").get_by_role("button", name=label, exact=False).first


def to_spike2(app):
    app.api("ui.pick_manufacturer", "stern")
    time.sleep(1.2)
    if (app.state("shell").get("mfr") or {}).get("era") != "spike2":
        app.api("ui.set_era", "spike2")
        time.sleep(1.2)


# ------------------------------------------------------------------ videos
def film_extract(pw, work, out):
    proj = os.path.join(work, "Deadpool Pro")
    shutil.rmtree(proj, ignore_errors=True)
    app = App(pw, work, {})
    try:
        f = Film(app, out, "extract")
        page = app.page
        f.snap("Choose your manufacturer: <b>Stern Pinball</b>",
               page.locator(".mfrcard", has_text="Stern Pinball"), n=1)
        page.locator(".mfrcard", has_text="Stern Pinball").first.click()
        time.sleep(1.5)
        if (app.state("shell").get("mfr") or {}).get("era") != "spike2":
            app.api("ui.set_era", "spike2")
        app.api("ui.select_tab", "card")
        f.snap("On <b>Select card</b>, press <b>Browse…</b> and pick the card image",
               page.get_by_role("button", name="Browse…").first, n=2)
        app.api("extract.use_recent", "input", CARDS["deadpool"])
        app.wait(lambda: (app.state("card").get("preview") or {}).get("state") not in (None, "loading"),
                 timeout=120)
        time.sleep(2)
        f.snap("It shows what the machine shows as it starts, so you know it is the right card",
               None, click=False, hold=4.6)
        f.snap("Press <b>Go to Extract</b>", page.get_by_role("button", name="Go to Extract").first, n=3)
        page.get_by_role("button", name="Go to Extract").first.click()
        time.sleep(1.2)
        f.snap("Pick a folder for the project", "#x-proj", n=4, click=False)
        os.makedirs(proj, exist_ok=True)
        app.api("extract.use_recent", "output", proj)
        time.sleep(1)
        ext = page.locator("main").get_by_role("button", name="Extract", exact=True).first
        f.snap("Press <b>Extract</b>", ext, n=5)
        ext.click()
        app.wait(lambda: app.state("shell").get("running"), timeout=30)
        time.sleep(8)
        f.snap("It copies the card's sounds, videos and pictures out: a few minutes",
               ".statusbar, footer", click=False, zoom=1.0, hold=4.6)
        app.wait(lambda: (app.state("shell").get("footer") or {}).get("pct", 0) >= 55, timeout=1800, step=2)
        f.snap("The log under it says what it is doing", None, click=False, hold=3.6)
        app.wait(lambda: not app.state("shell").get("running"), timeout=3600, step=2)
        time.sleep(3)
        f.snap("Done. The Replace tabs are unlocked and the project opens next time",
               rail_item(app, "Audio"), click=False, hold=5)
        return f.save(_task("extract"))
    finally:
        app.close()


def _task(vid):
    return next(t for t in GS.TASKS if t["id"] == vid)


def _project(work):
    proj = os.path.join(work, "Deadpool Pro")
    if not os.path.isfile(os.path.join(proj, ".checksums.md5")):
        raise SystemExit("film 'extract' first: it makes %s" % proj)
    return proj


def _with_project(proj):
    return {"last_manufacturer": "stern",
            "manufacturers": {"stern": {"extract_output": proj, "write_assets": proj}}}


def _my_song(work):
    """A stand-in for the user's own song (the video has no sound)."""
    path = os.path.join(work, "My music", "My disco tune.mp3")
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=30", "-ac", "2", "-b:a", "192k", path], check=True)
    return path


def _button(app, name, scope="main"):
    return app.page.locator(scope).get_by_role("button", name=name, exact=False).first


def _clear_rail_switch(app, f, ns, label, caption, n):
    """A step that opens a tab from the rail, captured on the tab before."""
    f.snap(caption, rail_item(app, label), n=n)
    app.api("ui.select_tab", ns)
    time.sleep(1.5)


def film_song(pw, work, out):
    proj = _project(work)
    song = _my_song(work)
    app = App(pw, work, _with_project(proj))
    try:
        to_spike2(app)
        app.api("ui.select_tab", "extract")
        f = Film(app, out, "song")
        page = app.page
        _clear_rail_switch(app, f, "audio", "Audio", "Open <b>Replace Audio</b>", 1)
        app.wait(lambda: app.state("audio").get("rows") is not None or app.state("audio").get("loaded"),
                 timeout=180)
        time.sleep(3)
        music = page.locator(".aud-seg").get_by_role("button", name="Music", exact=True).first
        f.snap("Set <b>Type</b> to <b>Music</b>", music, n=2)
        music.click()
        time.sleep(1.5)
        search = page.locator(".aud-tools .search input").first
        f.snap("Search for the song: the game names its own sounds", search, n=3, click=True)
        search.click()
        search.type("disco", delay=60)
        time.sleep(2)
        row = page.locator(".aud-tbl .tr").first
        f.snap("Right-click the song", row, n=4)
        row.click(button="right")
        time.sleep(0.8)
        item = page.locator(".menu [role=menuitem]", has_text="Choose replacement").first
        f.snap("<b>Choose replacement…</b>, then pick your mp3, wav or flac", item, n=5, settle=0.3)
        th, _ = (threading.Thread(target=item.click), None)
        th.start()
        app.answer_modal(song, kind="file")
        th.join(30)
        time.sleep(2.5)
        play = page.locator(".aud-pane").nth(1).get_by_role("button", name="Play").first
        f.snap("Play <b>Original</b> and <b>Replacement</b> to compare them", play, n=6, click=False,
               hold=4.6)
        f.snap("Done. <b>Write</b> builds the card with it",
               rail_item(app, "Write"), click=False, hold=4.4)
        return f.save(_task("song"))
    finally:
        app.close()


def _flash_dialog(app):
    return app.page.locator(".modal, [role=dialog]").filter(has_text="Build").last


def film_build(pw, work, out):
    proj = _project(work)
    app = App(pw, work, _with_project(proj))
    try:
        to_spike2(app)
        app.api("ui.select_tab", "audio")
        f = Film(app, out, "build")
        page = app.page
        _clear_rail_switch(app, f, "write", "Write", "Open <b>Write</b>", 1)
        app.wait(lambda: not app.state("write").get("busy"), timeout=300)
        time.sleep(4)
        f.snap("It lists every file you changed since the extract", "main", click=False,
               zoom=1.0, hold=4.0)
        btn = _button(app, "Build / flash SD card")
        f.snap("Press <b>Build / flash SD card…</b>", btn, n=2)
        btn.click()
        app.wait(lambda: app.state("write").get("flash_dlg"), timeout=30)
        time.sleep(1.5)
        dlg = _flash_dialog(app)
        f.snap("Tick what to do: build the image, flash it, or both", dlg, n=3, click=False, zoom=1.15,
               hold=4.8)
        sel = dlg.locator("select").first
        f.snap("With both ticked, pick the SD card here. Flashing erases the whole card",
               sel if sel.count() else dlg, n=4, click=False, hold=4.8)
        start = dlg.get_by_role("button", name=(app.state("write").get("flash_dlg") or {}).get(
            "start_label") or "Start").first
        f.snap("Press it, and the card is ready for the machine", start, n=5, click=False, hold=4.2)
        app.api("write.flash_close")
        return f.save(_task("build"))
    finally:
        app.close()


def film_flash(pw, work, out):
    app = App(pw, work, {"last_manufacturer": "stern"})
    try:
        to_spike2(app)
        app.api("ui.select_tab", "card")
        f = Film(app, out, "flash")
        page = app.page
        f.snap("No extract needed: open <b>Write</b>",
               page.locator(".rail").get_by_role("button", name="Write").first, n=1)
        app.api("ui.select_tab", "write")
        time.sleep(3)
        btn = _button(app, "Build / flash SD card")
        f.snap("Press <b>Build / flash SD card…</b>", btn, n=2)
        btn.click()
        app.wait(lambda: app.state("write").get("flash_dlg"), timeout=30)
        time.sleep(1)
        st = app.state("write").get("flash_dlg") or {}
        if st.get("build"):
            app.api("write.flash_set", "build", False)
        if not st.get("write"):
            app.api("write.flash_set", "write", True)
        time.sleep(1.2)
        dlg = _flash_dialog(app)
        browse = dlg.locator(".wr-frow", has_text="Image file").get_by_role("button", name="Browse…").first
        f.snap("Tick <b>Write an image onto the SD card</b>, then <b>Browse…</b> to the image", browse, n=3)
        app.api("write.flash_set", "image_path", CARDS["godzilla"])
        time.sleep(2)
        sel = dlg.locator("select").first
        f.snap("Pick the SD card", sel if sel.count() else dlg, n=4)
        start = dlg.get_by_role("button", name=(app.state("write").get("flash_dlg") or {}).get(
            "start_label") or "Start").first
        f.snap("Press <b>Flash image</b> and confirm. Flashing erases the whole SD card", start, n=5,
               click=False, hold=4.8)
        app.api("write.flash_close")
        return f.save(_task("flash"))
    finally:
        app.close()


def film_multiboot(pw, work, out):
    app = App(pw, work, {"last_manufacturer": "stern"})
    try:
        to_spike2(app)
        app.api("ui.select_tab", "card")
        f = Film(app, out, "multiboot")
        page = app.page
        _clear_rail_switch(app, f, "multiboot", "Multi-boot", "Open <b>Multi-boot</b>", 1)
        time.sleep(2)
        add = page.locator("main").get_by_role("button", name="Add image", exact=False).first
        f.snap("Add your card images. The first one is the one the card boots from", add, n=2)
        for key in ("deadpool", "godzilla"):
            th, _ = app.api_bg("multiboot.add_choice", "_add_image")
            app.answer_modal(CARDS[key], kind="file")
            th.join(600)
            app.wait(lambda: not app.state("multiboot").get("busy"), timeout=600, step=1)
            time.sleep(2)
        app.wait(lambda: not (app.state("multiboot").get("size") or {}).get("measuring"), timeout=900,
                 step=2)
        time.sleep(3)
        f.snap("The preview draws the menu the way the machine will show it", ".mb-menu",
               click=False, zoom=1.25, hold=4.6)
        edit = page.locator('.mb-acts button[aria-label="Edit"]').first
        f.snap("Press <b>✎</b> to give a game a title, a picture or music", edit, n=3)
        edit.click()
        app.wait(lambda: app.state("multiboot").get("dlg") == "edit", timeout=30)
        time.sleep(1.5)
        f.snap("The card is drawn next to the fields as you fill them in",
               page.locator(".modal, [role=dialog]").last, click=False, zoom=1.0, hold=4.4)
        app.api("multiboot.edit_cancel")
        time.sleep(1)
        f.snap("This strip names the SD card size you need", ".mb-size", n=4, click=False, hold=4.2)
        bf = page.locator("main").get_by_role("button", name="Build / flash card", exact=False).first
        f.snap("Press <b>Build / flash card…</b>", bf, n=5)
        bf.click()
        app.wait(lambda: app.state("multiboot").get("dlg") == "build", timeout=30)
        time.sleep(1.5)
        f.snap("Build the card, flash it, or both. At power-up, pick a game with the flippers",
               page.locator(".modal, [role=dialog]").last, click=False, zoom=1.15, hold=5)
        app.api("multiboot.build_cancel")
        return f.save(_task("multiboot"))
    finally:
        app.close()


def film_emulate(pw, work, out):
    app = App(pw, work, {"last_manufacturer": "stern"})
    try:
        to_spike2(app)
        app.api("ui.select_tab", "card")
        f = Film(app, out, "emulate")
        page = app.page
        _clear_rail_switch(app, f, "emulate", "Emulate", "Open <b>Emulate</b>", 1)
        time.sleep(4)
        setup = page.locator("main").get_by_role("button", name="Set up emulator", exact=False)
        if setup.count():
            f.snap("The first time, press <b>Set up emulator…</b>", setup.first, n=2, click=False)
        inp = page.locator('main input[placeholder*="Spike 2 card"]').first
        f.snap("Pick the card image: a stock card or one you built", inp, n=3 if setup.count() else 2)
        app.api("ui.set", "emulate", "card", CARDS["deadpool"])
        time.sleep(3)
        run = page.locator("main").get_by_role("button", name="Start emulator").first
        f.snap("Press <b>Start emulator</b>. The game runs in its own window, with sound", run,
               n=4 if setup.count() else 3, click=False, hold=4.8)
        f.snap("The card is never written to, so a stock card is safe to try", None, click=False,
               hold=4)
        return f.save(_task("emulate"))
    finally:
        app.close()


def film_transfer(pw, work, out):
    proj = _project(work)
    app = App(pw, work, _with_project(proj))
    try:
        to_spike2(app)
        app.api("ui.select_tab", "audio")
        f = Film(app, out, "transfer")
        page = app.page
        f.snap("Open the project that holds your mods", "header button[aria-label='Project menu']",
               n=1, click=False)
        _clear_rail_switch(app, f, "modpack", "Mod Pack", "Open <b>Mod Pack</b>", 2)
        time.sleep(2)
        port = page.locator("main").get_by_role("button", name="Port + build", exact=False).first
        f.snap("Press <b>Port + build onto card image(s)…</b>", port, n=3)
        f.snap("Pick the new stock card image: a new version, or the other model", port, n=4,
               click=False, zoom=1.0, hold=4.4)
        f.snap("It extracts that card, moves your mods onto it and builds it. The log names anything "
               "it skipped", None, click=False, hold=5)
        return f.save(_task("transfer"))
    finally:
        app.close()


FILMS = {"extract": film_extract, "song": film_song, "build": film_build, "flash": film_flash,
         "multiboot": film_multiboot, "emulate": film_emulate, "transfer": film_transfer}


# ------------------------------------------------------------------ render
def render(script, mp4, poster):
    from playwright.sync_api import sync_playwright
    tmp = mp4 + ".tmp.mp4"
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 1280, "height": 720})
        page.goto("file:///" + PLAYER.replace("\\", "/"))
        shots = [dict(s, img="file:///" + s["img"].replace("\\", "/")) for s in script["shots"]]
        total = page.evaluate("s => load(s)", dict(script, shots=shots))
        page.wait_for_function("Array.from(document.images).every(i => i.complete)", timeout=60000)
        page.evaluate("document.fonts.ready")
        n = int(total * FPS)
        ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS),
                               "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "slow",
                               "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                               "-tune", "stillimage", tmp], stdin=subprocess.PIPE)
        stage = page.locator("#stage")
        for i in range(n):
            page.evaluate("t => setTime(t)", i / FPS)
            ff.stdin.write(stage.screenshot(type="jpeg", quality=92))
        ff.stdin.close()
        if ff.wait() != 0:
            raise SystemExit("ffmpeg failed on " + mp4)
        # the poster: the first step, settled
        page.evaluate("t => setTime(t)", 2.6 + 2.4)
        stage.screenshot(path=poster, type="jpeg", quality=85)
        b.close()
    os.replace(tmp, mp4)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--work", default=r"C:\tmp\Pinball")
    ap.add_argument("--shots-only", action="store_true")
    ap.add_argument("--render-only", action="store_true")
    a = ap.parse_args()
    ids = [x for x in a.only.split(",") if x] or [t["id"] for t in GS.TASKS]
    shots_dir = os.path.join(a.work, "_film")
    os.makedirs(GS.VIDEO_DIR, exist_ok=True)
    for vid in ids:
        if not a.render_only:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                script = FILMS[vid](pw, a.work, shots_dir)
            print(vid, "filmed:", len(script["shots"]), "steps", flush=True)
        if a.shots_only:
            continue
        with open(os.path.join(shots_dir, vid, "script.json"), encoding="utf-8") as f:
            script = json.load(f)
        secs = render(script, GS.video_path(vid), GS.video_path(vid, "jpg"))
        print(vid, "rendered: %.1f s, %d KB" % (secs, os.path.getsize(GS.video_path(vid)) // 1024),
              flush=True)


if __name__ == "__main__":
    main()
