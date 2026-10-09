"""PAD-489 proof: Emulate's Start on a project whose game clips all carry a color profile.

    python scripts/shot_pad489.py <repo> <out_dir> <prefix> [clips]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  A scratch Godzilla project gets <clips> (default 60) of the game's own
clips, every one switched on under the Video tab's Advanced box with the Black and white
files profile, and "Apply my replaced assets" ticked.  Start is pressed with the rig stood
in (PAD_UI_NO_RIG: nothing reaches WSL, no game is started), and:

  <prefix>_start.png     two seconds after Start: the question asked first (after), or the
                         tab already at it with no word of how much there is (before)
  <prefix>_progress.png  ~25 s into the conversion: the State line and the footer's bar
  <prefix>_cancel.png    a second after Cancel is pressed (round 2): still at it (before), or
                         stopped, with what was kept said beside the opt-in (after)

The game's own pictures (Desktop\\gzho's images) are switched on under the profile too.
Real ffmpeg encodes run, in the scratch folder only.
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CLIPS = r"D:\Pinball\gz116_bottleneck\stock116\video"
PICS = r"C:\Users\david\OneDrive\Desktop\gzho\images"
CARD = (r"C:\Users\david\Documents\development\pinball-asset-decryptor\images\Stern\spike2"
        r"\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
# the rig stood in: Start goes as far as the preparation and no further
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda *a, **k: 1
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def make_project(repo, scratch, n):
    sys.path.insert(0, repo)
    from pinball_decryptor.core import colour_profile as cp
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.core.checksums import md5_file
    proj = os.path.join(scratch, "Godzilla Extract")
    vid = os.path.join(proj, "video")
    os.makedirs(vid)
    names = sorted(x for x in os.listdir(CLIPS) if x.endswith(".mp4"))
    pick = names[::max(1, len(names) // n)][:n]
    sums, manifest = [], ["# output\tcard path\tbytes\n"]
    with open(os.path.join(CLIPS, "manifest.txt"), encoding="utf-8") as f:
        rows = {ln.split("\t")[0]: ln for ln in f if not ln.startswith("#")}
    for name in pick:
        dst = os.path.join(vid, name)
        shutil.copyfile(os.path.join(CLIPS, name), dst)
        sums.append("video/%s\t%s\n" % (name, md5_file(dst)))
        if name in rows:
            manifest.append(rows[name])
    with open(os.path.join(vid, "manifest.txt"), "w", encoding="utf-8") as f:
        f.writelines(manifest)
    # the game's own pictures, switched on behind the Images tab's unlock
    pics, pman = {}, ["# output\tcard path\tbytes\n"]
    with open(os.path.join(PICS, "manifest.txt"), encoding="utf-8") as f:
        for ln in f:
            out = ln.split("\t")[0]
            src = os.path.join(PICS, *out.split("/"))
            if ln.startswith("#") or not out.lower().endswith(".png") \
                    or not os.path.isfile(src):
                continue
            dst = os.path.join(proj, "images", *out.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            sums.append("images/%s\t%s\n" % (out, md5_file(dst)))
            pics["images/" + out] = True
            pman.append(ln)
    with open(os.path.join(proj, "images", "manifest.txt"), "w", encoding="utf-8") as f:
        f.writelines(pman)
    with open(os.path.join(proj, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(sums)
    with open(os.path.join(proj, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.16"}, f)
    staged_changes.save(proj, {
        "video_color_stock": True,
        "video_color_slots": {"video/" + name: True for name in pick},
        "image_color_unlocked": True,
        "image_color_slots": pics})
    cp.store_asset_profile(proj, dict(cp.PRESETS)["bw"])
    return proj, len(pick)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 60
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad489-")
    project, n = make_project(repo, scratch, n)
    print("repo", repo, "project", project, "clips", n, flush=True)
    launcher = os.path.join(scratch, "launch489.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": CARD, "emulate_overrides": True,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": ""}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(3)
            webui_shot.api(url, "emulate.toggle")
            time.sleep(2.5)
            st = webui_shot.state(url)
            modals = (st.get("modals") or {}).get("open") or []
            print("state", (st.get("emulate") or {}).get("vals", {}).get("state"),
                  "modals", [m.get("title") for m in modals], flush=True)
            out = os.path.join(out_dir, "%s_start.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            if modals:
                print("question:", modals[0].get("message"), flush=True)
                page.get_by_role("button", name="Yes").click()
            t0 = time.time()
            while time.time() - t0 < 25:
                time.sleep(1)
            st = webui_shot.state(url)
            print("state", (st.get("emulate") or {}).get("vals", {}).get("state"),
                  "footer", st.get("shell", {}).get("footer"), flush=True)
            out = os.path.join(out_dir, "%s_progress.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            webui_shot.api(url, "emulate.toggle")          # Cancel
            time.sleep(1.0)
            st = webui_shot.state(url).get("emulate") or {}
            print("after cancel: state", st.get("vals", {}).get("state"),
                  "button", (st.get("run_btn") or {}).get("label"),
                  "hint", st.get("ovr_hint"), flush=True)
            out = os.path.join(out_dir, "%s_cancel.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            time.sleep(8)
            st = webui_shot.state(url).get("emulate") or {}
            print("9 s after cancel: state", st.get("vals", {}).get("state"),
                  "button", (st.get("run_btn") or {}).get("label"), flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
