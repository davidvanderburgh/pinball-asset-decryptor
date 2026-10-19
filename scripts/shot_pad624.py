"""PAD-624 proof shots: the Video tab's Played in and clip sounds on titles other than Godzilla,
and the one line it shows when the card gives it nothing.

    python scripts/shot_pad624.py <repo> <out_dir> [--after]

Serves <repo> on SCRATCH projects made of a few clips each, copied off the stock cards (read
only) into ``PAD624_SOURCE`` once and copied again for every run, so before and after see the
same files. Writes, under the same names before and after:

- video_xmen.png        Uncanny X-Men Pro 0.98, Stopping_A_Juggernaut_Award2 selected
- video_venom.png       Venom Pro 1.07, CarnageMultiball_CarnageJackpot selected
- video_card_gone.png   the X-Men project with its card moved away
- video_no_modes.png    Aerosmith 1.16 (its rules are plain C), a clip selected

Needs Playwright (the user site-packages one) and the installed Edge.
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
import shot_pad312 as base  # noqa: E402

CARDS = os.environ.get("PAD624_CARDS", r"D:\Pinball\images\Stern\spike2")
SOURCE = os.environ.get("PAD624_SOURCE", r"C:\tmp\PAD-624\proj_src")
SCRATCH = os.environ.get("PAD624_SCRATCH", r"C:\tmp\PAD-624\shot_scratch")
PROJECTS = {
    "xmen": ("uncanny_xmen_pro-0_98_0.Release.16G.sdcard.raw",
             ("Stopping_A_Juggernaut_Award2", "Stopping_A_Juggernaut_Award1", "Mode_Fail",
              "TMMXM_Rogue_Award", "Fiery_Assault_Award1", "EscapeNimrod_Start",
              "Bishop_PopAwardFire", "OrbitSkillShot_1", "Lock1", "Genosha_Under_Siege_BG")),
    "venom": ("venom_pro-1_07_0.Release.8G.sdcard.raw",
              ("CarnageMultiball_CarnageJackpot", "CarnageMultiball_Background_Phase1",
               "LasherBattle_Advance_1", "ToxinTeamUp_Award_Captain", "Bloodlust_Award_BlueShot",
               "RiotBattle_Advance_1", "HostHurryUp_Award_AgentVenom")),
    "aerosmith": ("aerosmith-1_16_0.Release.8G.sdcard.raw", None),
}
SHOTS = (("video_xmen", "xmen", "Stopping_A_Juggernaut_Award2.mp4", False),
         ("video_venom", "venom", "CarnageMultiball_CarnageJackpot.mp4", False),
         ("video_card_gone", "xmen", "Stopping_A_Juggernaut_Award2.mp4", True),
         ("video_no_modes", "aerosmith", None, False))


def _rows(card):
    """``{clip name: card path}`` of every clip in the card's video banks."""
    sys.path.insert(0, os.path.dirname(HERE))
    from pinball_decryptor.plugins.stern import video_bank as VB
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _v, part = card_title(card)
    out = {}
    with CardImage(card) as img:
        stack = ["/%s/assets" % game]
        while stack:
            d = stack.pop()
            try:
                ents = img.list_dir(part, d)
            except Exception:                               # noqa: BLE001
                continue
            for e in ents:
                if e.is_dir:
                    if not e.name.endswith(".assets"):
                        stack.append(e.path)
                elif e.name == "scene.radium" and e.size > 4096:
                    try:
                        bank = VB.parse(img.preview(part, e.path, cap=64 << 20))
                    except Exception:                       # noqa: BLE001 - not a bank
                        continue
                    for c in bank.library.entries:
                        out.setdefault(c.name, "%s/scene.assets/%s" % (d, c.path))
    return out, part


def _source(key):
    """The project's clips, copied off its card once (the card is read only)."""
    dst = os.path.join(SOURCE, key)
    if os.path.isfile(os.path.join(dst, "video", "manifest.txt")):
        return dst
    cardname, clips = PROJECTS[key]
    card = os.path.join(CARDS, cardname)
    rows, part = _rows(card)
    if clips is None:
        clips = sorted(rows)[:8]
    from pinball_decryptor.plugins.stern.explorer import CardImage
    os.makedirs(os.path.join(dst, "video"), exist_ok=True)
    lines = ["# output\tcard path\tbytes"]
    with CardImage(card) as img:
        for c in clips:
            out = os.path.join(dst, "video", c + ".mp4")
            img.extract_file(part, rows[c], out)
            lines.append("%s.mp4\t%s\t%d" % (c, rows[c], os.path.getsize(out)))
    with open(os.path.join(dst, "video", "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return dst


def _project(scratch, key, gone):
    src = _source(key)
    dst = os.path.join(scratch, key)
    shutil.copytree(src, dst)
    import hashlib
    sums = []
    for n in sorted(os.listdir(os.path.join(dst, "video"))):
        if n.endswith(".mp4"):
            with open(os.path.join(dst, "video", n), "rb") as f:
                sums.append("video/%s\t%s" % (n, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    card = os.path.join(CARDS, PROJECTS[key][0])
    st = os.stat(card)
    if gone:
        card = os.path.join(scratch, "moved_away", PROJECTS[key][0])
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card),
                   "size": st.st_size, "mtime": int(st.st_mtime)}, f)
    return dst


def _serve(repo, scratch, project, card):
    launcher = os.path.join(scratch, "launch624.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(base.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project,
                                               "extract_input": card}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python"),
                   "PAD_TITLE_CACHE": os.path.join(scratch, "titles")})


def _one(repo, out, pre, screen, key, rel, gone):
    os.makedirs(SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad624-", dir=SCRATCH)
    project = _project(scratch, key, gone)
    proc, url = _serve(repo, scratch, project, os.path.join(CARDS, PROJECTS[key][0]))
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
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
            deadline = time.time() + 300
            while time.time() < deadline:
                md = (state().get("video") or {}).get("modes") or {}
                if md.get("ready"):
                    break
                time.sleep(1)
            if rel:
                # the row may be below the list's fold (a clip several modes play has a row
                # for each): search for it, then click it
                page.locator(".vid-card .toolbar input").first.fill(os.path.splitext(rel)[0])
                time.sleep(1.5)
                page.locator(".vid-tbl .tr:has-text('%s')" % rel).first.click()
            else:
                page.locator(".vid-tbl .tr").first.click()
            time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, pre + screen + ".png"))
            st = state().get("video") or {}
            md = st.get("modes") or {}
            print(screen, "modes:", json.dumps({k: md.get(k) for k in ("note", "list", "why")}),
                  flush=True)
            print(screen, "sounds:", json.dumps((st.get("preview") or {}).get("sounds")),
                  flush=True)
            print(screen, "page errors:", errors, flush=True)
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
    pre = "after_" if "--after" in sys.argv else "before_"
    only = [a[7:] for a in sys.argv if a.startswith("--only=")]
    for screen, key, rel, gone in SHOTS:
        if only and screen not in only:
            continue
        _one(repo, out, pre, screen, key, rel, gone)


if __name__ == "__main__":
    main()
