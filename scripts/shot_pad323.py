"""PAD-323 proof: lay out a mode's screen in the Scenes editor.

    python scripts/shot_pad323.py <repo> <out_dir> <prefix> [--rig]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). The project is a scratch copy of the Godzilla Premium/LE 1.16 extract on the
Desktop (its pictures, text and scene drawings; none of its modes) holding one mode, WALL OF
FIRE, whose screen is a picture of its own. Writes, in <out_dir>:

* <prefix>_show.png: the Modes tab's Show page for that mode (the "Lay out on the screen..."
  button and what it says about where the screen goes);
* <prefix>_scenes_editor.png: the Scenes tab on the HUD scene. On a tree with the button it
  is pressed, and the screen is moved, made smaller and sent under the HUD's own pictures with
  the editor's own calls; before, the Scenes tab simply shows the HUD scene (the mode's screen
  is not in it).

With --rig (after only) it then presses Try it on the 1.16 card, pinned to rig slot 3 (never
David's own rig: no PAD_TICKET), hidden and muted, starts a game and the mode, and saves the
guest's framebuffer before and during the mode as <prefix>_glass_*.png.
"""

import json
import os
import shutil
import subprocess
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
SOURCE = r"C:\Users\david\OneDrive\Desktop\gzho"
CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
HUD_DIR = "/godzilla_le/assets/lcd/auto_loaded/32e6ae280ddaec08e203a02289bb39a04968e7b0"
RIGSH = "/mnt/c/tmp/pad323_rig.sh"
SLOT = "3"
RIG_LAYOUT = {"x": 20.0, "y": 300.0, "scale": 0.7, "order": 0}


def rig(*args, timeout=120):
    r = subprocess.run(["wsl", "-d", "PAD-Runtime", "-u", "root", "--", "bash", RIGSH] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def win_to_wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:])


def wall_picture(path):
    """The mode's own picture: a wide band, magenta into orange, with its name on it."""
    from PIL import Image, ImageDraw, ImageFont
    w, h = 1000, 360
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for x in range(w):
        t = x / float(w - 1)
        c = (255, int(40 + 120 * t), int(220 * (1 - t)), 255)
        for y in range(h):
            px[x, y] = c
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 110)
    except OSError:
        font = ImageFont.load_default()
    d.text((w // 2, h // 2 - 20), "WALL OF FIRE", font=font, fill=(255, 255, 255, 255),
           anchor="mm", stroke_width=6, stroke_fill=(60, 0, 40, 255))
    img.save(path)


def magenta(png):
    from PIL import Image
    im = Image.open(png).convert("RGB")
    return sum(1 for r, g, b in im.getdata() if r > 220 and b > 120 and g < 110)


def project_copy(scratch, repo, layout=None):
    """The scratch project. With *layout* (the rig run) it is the card's record and the mode
    alone, laid out as given: the extract's own edits change the HUD scene, and a build
    refuses modes beside another edit of the scene they go into."""
    project = os.path.join(scratch, "Godzilla LE 1.16 Extract")
    os.makedirs(project)
    for name in (("images", "text") if layout is None else ()):
        shutil.copytree(os.path.join(SOURCE, name), os.path.join(project, name))
    shutil.copy2(os.path.join(SOURCE, ".extract_source.json"), project)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    spec = MP.blank_spec(MP.profile_for_card("godzilla_le", "1.16"), name="WALL OF FIRE")
    spec.start_count, spec.seconds, spec.clip = 1, 30, "none"
    slug, _ = MP.new_mode(project, spec=spec)
    folder = MP.mode_folder(project, slug)
    wall_picture(os.path.join(folder, "wall.png"))
    spec = MP.load(os.path.join(folder, MP.MODE_FILE))
    spec.screen_art = "wall.png"
    spec.screen_layout = dict(layout or {})
    MP.save(project, slug, spec)
    return project, slug


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    with_rig = "--rig" in sys.argv[4:]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad323-")
    # the rig run: the layout the editor shot makes (scripts/shot_pad323.py without --rig)
    project, slug = project_copy(scratch, repo, RIG_LAYOUT if with_rig else None)
    print("project", project, "mode", slug, flush=True)
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch323.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes, "emulate_card": CARD,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    cfgdir = os.path.join(scratch, "cfg", "pinball_decryptor")
    os.makedirs(cfgdir, exist_ok=True)
    with open(os.path.join(cfgdir, "audio_ctl.json"), "w", encoding="utf-8") as f:
        json.dump({"gain": 0.0, "muted": True}, f)       # a rig run is always muted
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    if with_rig:
        tmp = os.path.join(scratch, "tmp")              # a Try it set of its own, never David's
        os.makedirs(tmp, exist_ok=True)
        env.update({"TEMP": tmp, "TMP": tmp, "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "1",
                    "PAD_SLOT": SLOT, "PAD_TICKET": "", "PAD_LABEL": "PAD-323-check",
                    "PAD_HIDDEN": "1"})
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1250})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            if not with_rig:
                webui_shot.api(url, "ui.select_tab", "modes")
                time.sleep(3)
                webui_shot.api(url, "modes.select", slug, "form")
                time.sleep(2)
                page.get_by_role("tab", name="Show").first.click()
                time.sleep(2)
                out = os.path.join(out_dir, "%s_show.png" % prefix)
                page.screenshot(path=out)
                print("shot", out, flush=True)

                button = page.get_by_role("button", name="Lay out on the screen…")
                if button.count():
                    button.first.click()
                    # the editor draws the HUD with the mode's screen; then it is laid out with the
                    # editor's own calls, as a drag, a size and Send to back would make them
                    ready = lambda: ((webui_shot.state(url).get("text_scenes") or {})
                                     .get("tree_view") or {}).get("layers")
                    for _ in range(120):
                        if ready():
                            break
                        time.sleep(0.5)
                    from pinball_decryptor.webui import scene_mode_layout as ML
                    mode_json = os.path.join(project, "modes", slug, "mode.json")

                    def layout():
                        with open(mode_json, encoding="utf-8") as f:
                            return json.load(f).get("screen_layout") or {}
                    webui_shot.api(url, "text_scenes.tree_set_scale", ML.ART_ID, 70)
                    time.sleep(1)
                    # over the HUD's slide-out badges at the left, so "under the HUD" shows
                    lay = layout()
                    webui_shot.api(url, "text_scenes.tree_move", ML.ART_ID,
                                   20 - lay.get("x", 0.0), 300 - lay.get("y", 0.0))
                    time.sleep(1)
                    webui_shot.api(url, "text_scenes.tree_order", ML.GROUP_ID, "back")
                    time.sleep(1)
                    # nothing selected: a selected layer is drawn on top to drag it, and the shot
                    # is of the scene as the game draws it
                    webui_shot.api(url, "text_scenes.tree_select", None)
                    time.sleep(4)
                    print("screen_layout", layout(), flush=True)
                else:
                    webui_shot.api(url, "ui.select_tab", "scenes")
                    time.sleep(4)
                    webui_shot.api(url, "text_scenes.select", HUD_DIR)
                    for _ in range(120):
                        if (webui_shot.state(url).get("text_scenes") or {}).get("tree_view"):
                            break
                        time.sleep(0.5)
                    time.sleep(4)
                out = os.path.join(out_dir, "%s_scenes_editor.png" % prefix)
                page.screenshot(path=out)
                print("shot", out, flush=True)
                browser.close()
                return

            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(2)
            print("rig before:", rig("ps")[1].strip() or "(nothing running)", flush=True)
            webui_shot.api(url, "modes.tryit")
            t0, last, ts = time.time(), None, {}
            while time.time() - t0 < 3600:
                ts = (webui_shot.state(url).get("modes") or {}).get("tryit") or {}
                now = (ts.get("state"), (ts.get("reason") or "")[:200])
                if now != last:
                    print("%5ds tryit %s" % (time.time() - t0, now), flush=True)
                    last = now
                if ts.get("state") in ("live", "ended", "failed"):
                    break
                time.sleep(10)
            if (ts.get("state") or "") != "live":
                return
            time.sleep(60)
            for k in ("coin", "game"):
                print(k, rig(k)[1].strip()[-200:], flush=True)
            time.sleep(25)
            rig("plunge")
            time.sleep(15)
            g = os.path.join(out_dir, "%s_glass_before_mode.png" % prefix)
            rig("shot", win_to_wsl(g))
            if os.path.isfile(g):
                print("  magenta before:", magenta(g), flush=True)
            webui_shot.api(url, "modes.start_now")
            for i, wait in enumerate((1.5, 2.5, 4.0)):
                time.sleep(wait)
                g = os.path.join(out_dir, "%s_glass_mode_%d.png" % (prefix, i))
                rig("shot", win_to_wsl(g))
                if os.path.isfile(g):
                    print("  t+%d %s magenta %d" % (i, os.path.basename(g), magenta(g)), flush=True)
            print("mode.log tail:\n" + rig("modelog", "30")[1], flush=True)
            browser.close()
    finally:
        try:
            if with_rig:
                st = webui_shot.state(url).get("emulate", {})
                if st.get("up") or st.get("running"):
                    webui_shot.api(url, "emulate.toggle")
                    time.sleep(20)
        except Exception as e:                        # noqa: BLE001
            print("stop:", e, flush=True)
        proc.terminate()
        if with_rig:
            print("rig after:", rig("ps")[1].strip() or "(nothing running)", flush=True)


if __name__ == "__main__":
    main()
