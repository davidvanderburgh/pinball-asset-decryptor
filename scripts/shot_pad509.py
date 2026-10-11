"""PAD-509 proof: Emulate's Start again and again on a project with every picture edited.

    python scripts/shot_pad509.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  The project is PAD-505's (scripts/shot_pad505.py): every one of
Godzilla's own pictures (Desktop\\gzho's images, 5,813) switched on under the Images tab's
Advanced box with the Black and white files profile, "Apply my replaced assets" ticked, the
rig stood in (PAD_UI_NO_RIG: Start goes as far as the preparation, then says the rig is
off).  Three Starts, each waited out:

  1. the first: every picture converted, the emulator's override set built
  2. the second, nothing changed:  <prefix>_emulate_second_start.png
  3. the third, after one picture's original was changed (a stand-in for the user editing
     one picture):                 <prefix>_emulate_one_picture_changed.png

stdout says how long each Start took and the log's lines about the set.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad505 as P  # noqa: E402
import webui_shot  # noqa: E402

#: the picture whose original is changed before the third Start
ONE = "images/scene_textures/11a44e92_109_306x200.png"
_SAID = ("preparing your edits", "reusing it", "override set in", "unchanged since",
         "came out just as", "failed to start", "picture(s) left as they are")


def _reply(url, mid, v):
    """Answer the app's question *mid* (the conversion's "this takes a while")."""
    import json
    import urllib.request
    base = url.split("/?")[0]
    token = url.split("t=")[1].split("&")[0]
    req = urllib.request.Request(base + "/api/reply?t=" + token,
                                 data=json.dumps({"id": mid, "v": v}).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-PAD-Token": token})
    urllib.request.urlopen(req, timeout=30).read()


def _button(url):
    return (((webui_shot.state(url).get("emulate") or {}).get("run_btn") or {})
            .get("label") or "")


def _start_and_wait(url, page, what, limit=900):
    webui_shot.api(url, "emulate.toggle")
    t0 = time.time()
    time.sleep(2)
    while time.time() - t0 < limit:
        btn = _button(url)
        if btn and "Cancel" not in btn and "…" not in btn and "Stop" not in btn:
            break
        for mm in ((webui_shot.state(url).get("modals") or {}).get("open") or []):
            _reply(url, mm["id"], "yes")
        time.sleep(1)
    took = time.time() - t0
    lines = page.evaluate(
        "Array.from(document.querySelectorAll('.line')).map(e => e.textContent)")
    print("%s: Start over after %.0f s" % (what, took), flush=True)
    for ln in lines[-60:]:
        if any(s in ln for s in _SAID):
            print("   ", ln[:200], flush=True)
    return took


#: the log pane's height for the shots (the shell keeps it in localStorage)
LOG_H = 430
#: the line each shot is about (the set built, or reused), shown with a few lines above it
_ANCHOR = r"override set in|reusing it"
_SCROLL_JS = """([pat, above]) => {
  const ls = Array.from(document.querySelectorAll('.line'));
  for (let k = ls.length - 1; k >= 0; k--) {
    if (new RegExp(pat).test(ls[k].textContent)) {
      ls[Math.max(0, k - above)].scrollIntoView({block: 'start'});
      return true; } }
  return false; }"""


def _shot(page, out, above):
    found = page.evaluate(_SCROLL_JS, [_ANCHOR, above])
    time.sleep(0.5)
    page.screenshot(path=out)
    print("shot", out, "(log scrolled to the set's line: %s)" % found, flush=True)


def _change_one_picture(project):
    """Paint a corner of one picture's pristine copy: its next staging converts it
    again, and it comes out different."""
    from PIL import Image
    snap = os.path.join(project, ".orig", *ONE.split("/"))
    if not os.path.isfile(snap):
        raise RuntimeError("no .orig snapshot of %s" % ONE)
    im = Image.open(snap).convert("RGBA")
    for x in range(24):
        for y in range(24):
            im.putpixel((x, y), (255, 255, 255, 255))
    im.save(snap)
    print("changed the original of", ONE, flush=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    import json
    import shutil
    import site
    import tempfile
    scratch = tempfile.mkdtemp(prefix="pad509-")
    project, n = P.make_project(repo, scratch)
    print("repo", repo, "project", project, "pictures", n, flush=True)
    launcher = os.path.join(scratch, "launch509.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(P.LAUNCHER.replace("@REPO@", repr(repo)).replace("@SLEEP@", "0.0"))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": P.CARD, "emulate_overrides": True,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    tmp = os.path.join(scratch, "tmp")      # %TEMP%\spike2_overrides goes here
    os.makedirs(tmp)
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "TEMP": tmp, "TMP": tmp}
    proc, url = webui_shot.start_server(settings, scratch,
                                        app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.add_init_script("localStorage.setItem('pad.log.open', '1');"
                                 "localStorage.setItem('pad.log.h', '%d');" % LOG_H)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(3)
            _start_and_wait(url, page, "first Start")
            time.sleep(2)
            _start_and_wait(url, page, "second Start (nothing changed)")
            _shot(page, os.path.join(out_dir, "%s_emulate_second_start.png" % prefix), 4)
            _change_one_picture(project)
            time.sleep(2)
            _start_and_wait(url, page, "third Start (one picture changed)")
            _shot(page, os.path.join(out_dir, "%s_emulate_one_picture_changed.png"
                                     % prefix), 9)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                    # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
