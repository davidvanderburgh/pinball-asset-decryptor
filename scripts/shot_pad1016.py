"""PAD-1016 proof shots: Clear replacements that are the same picture as the
original, on the Replace Images tab.

    python scripts/shot_pad1016.py <repo> <out_dir> [--after]

Builds a small scratch Stern project (five pictures, checksummed) and a
folder of replacements: two re-saved copies of the originals (other bytes,
same pixels), one of them a JPEG-free PNG with a different compression, and
one real change.  All three are picked through the sidecar.  Writes, under
the same names before and after:

- more_menu.png   the tab's More menu, open
- images_list.png the list after the menu's identical-clear (after only; the
                  before shot is the same list with nothing run, since there
                  is no such command before)

Nothing outside the scratch folder is read or written.  Needs Playwright
(the user site-packages one) and the installed Edge.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _project(root, repo):
    sys.path.insert(0, repo)
    from PIL import Image, ImageDraw
    assets = os.path.join(root, "gz")
    pics = os.path.join(assets, "images")
    os.makedirs(pics)
    mine = os.path.join(root, "mine")
    os.makedirs(mine)
    names = []
    for i, (name, col) in enumerate((
            ("attract_logo", (200, 40, 40)), ("ball_save", (40, 160, 60)),
            ("jackpot", (230, 190, 30)), ("multiball", (40, 90, 210)),
            ("skill_shot", (150, 60, 190)))):
        im = Image.new("RGBA", (160, 80), col + (255,))
        d = ImageDraw.Draw(im)
        d.rectangle((10 + i * 8, 10, 70 + i * 8, 60), fill=(255, 255, 255, 255))
        d.text((90, 30), name[:8], fill=(0, 0, 0, 255))
        im.save(os.path.join(pics, name + ".png"))
        names.append(name)
    from pinball_decryptor.core import checksums, staged_changes
    checksums.generate_checksums(assets)
    picks = {}
    # two pixel-for-pixel copies saved again (other bytes, same picture)
    for name in ("attract_logo", "jackpot"):
        im = Image.open(os.path.join(pics, name + ".png"))
        dst = os.path.join(mine, name + ".png")
        im.save(dst, compress_level=1)
        picks["images/%s.png" % name] = dst
    # one real change
    im = Image.open(os.path.join(pics, "multiball.png")).convert("RGBA")
    ImageDraw.Draw(im).ellipse((100, 10, 150, 70), fill=(255, 0, 0, 255))
    dst = os.path.join(mine, "multiball.png")
    im.save(dst)
    picks["images/multiball.png"] = dst
    staged_changes.save(assets, {"image": picks})
    return assets


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    # the follow-up: attract_logo's "Correct its colors for the machine" on,
    # and the identical-clear run in both shots (it existed by then)
    colour = "--colour" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + ("colour_" if colour else "") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad1016-")
    project = _project(scratch, repo)
    launcher = os.path.join(scratch, "launch1016.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "theme": "dark",
                   "manufacturers": {"stern": {
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    print("serving", repo, "project", project, flush=True)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1.5)
            api("ui.select_tab", "images")
            time.sleep(2)
            api("images.scan")
            time.sleep(6)
            api("images.select", "images/attract_logo.png")
            time.sleep(2)
            if colour:
                page.get_by_text("Correct its colors for the machine").first.click()
                time.sleep(2)
            page.get_by_role("button", name="More").click()
            time.sleep(1)
            page.screenshot(path=out("more_menu.png"))
            item = page.get_by_text("Clear replacements identical to the original…")
            if (after or colour) and item.count():
                item.first.click()
                time.sleep(1.5)
                page.screenshot(path=out("confirm.png"))
                page.get_by_role("button", name="Yes").click()
                time.sleep(3)
            else:
                page.keyboard.press("Escape")
                time.sleep(1)
            page.mouse.move(5, 940)
            time.sleep(0.5)
            page.screenshot(path=out("images_list.png"))
            from pinball_decryptor.core import staged_changes
            print("picks left:", sorted(
                (staged_changes.load(project).get("image") or {})), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
