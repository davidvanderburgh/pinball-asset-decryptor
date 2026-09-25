"""PAD-215 proof shot: the Replace Video row menu of a clip with a
replacement assigned, opened on its "This clip's length" submenu when the
tree has one.

    python scripts/shot_pad215.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of the commit before it for the "before" shot).  Writes
<out_dir>/<prefix>_video_menu.png.  A scratch Stern project holds a 6 s stock
clip with a 14 s replacement assigned and that clip set to 6 s in the
sidecar (a tree without per-clip lengths ignores the key).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

REL = "video/TagTeamIntro_GodzillaAnguirusVsKingGhidorahGigan.mov"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _clip(ffmpeg, path, seconds, ext):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i",
         "testsrc=size=1360x768:rate=30:duration=%g" % seconds,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
         path], check=True, capture_output=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.core import checksums, staged_changes
    from pinball_decryptor.core.video import find_ffmpeg
    ffmpeg = find_ffmpeg()
    scratch = tempfile.mkdtemp(prefix="pad215-")
    project = os.path.join(scratch, "GZ 1.16 Pro Extract")
    _clip(ffmpeg, os.path.join(project, *REL.split("/")), 6, "mov")
    mine = os.path.join(scratch, "mine", "Godzilla vs Battra.mp4")
    _clip(ffmpeg, mine, 14, "mp4")
    checksums.generate_checksums(project)
    staged_changes.save(project, {"video": {REL: mine},
                                  "video_trim": True,
                                  "video_best_quality": True,
                                  "video_length_slots": {REL: 6.0}})
    launcher = os.path.join(scratch, "launch215.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1560, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "video")
            webui_shot.api(url, "video.scan")
            time.sleep(6)
            row = page.get_by_text(os.path.basename(REL)).first
            row.click()
            time.sleep(1)
            row.click(button="right")
            time.sleep(1)
            sub = page.get_by_text("This clip's length")
            if sub.count():
                sub.first.hover()
            else:
                page.get_by_text("This clip's conversion").first.hover()
            time.sleep(1)
            out = os.path.join(out_dir, "%s_video_menu.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
