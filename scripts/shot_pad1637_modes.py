r"""PAD-1637 proof shot: the Modes tab's Sounds page of a Form mode on the Godzilla LE 1.16 card, its own music set,
before and after a mode's own sounds could change with the MUSIC MODE (the By music mode grid under Sounds of its own,
open in the after shot with music files of its own in music modes 2 and 3).

    python scripts/shot_pad1637_modes.py <app tree> <out png> <before|after> <music wav> <music 2 wav>
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    kind, music, music2 = sys.argv[3], sys.argv[4], sys.argv[5]
    scratch = tempfile.mkdtemp(prefix="pad1637-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.16.0"}, f)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    import shutil
    slug, _ = MP.new_mode(project, "MUSIC TEST")
    folder = MP.mode_folder(project, slug)
    spec = MP.load(os.path.join(folder, MP.MODE_FILE))
    shutil.copyfile(music, os.path.join(folder, "music.wav"))
    spec.music = "music.wav"
    if kind == "after":
        from pinball_decryptor.plugins.stern import service_menu as SvM
        for m in (2, 3):
            shutil.copyfile(music2, os.path.join(folder, MP.own_mode_file_name("music", m)))
            MP.set_own_mode_file(spec, "music", m, MP.own_mode_file_name("music", m))
        sv = SvM.load(project)
        sv["on"] = sorted(set(sv["on"]) | {"music_mode"})
        SvM.save(project, sv)
    MP.save(project, slug, spec)
    launcher = os.path.join(scratch, "launch1637.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 1500})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.get_by_text("Sounds", exact=True).first.click()
            time.sleep(2.5)
            if kind == "after":
                page.get_by_role("button", name="By music mode").first.click()
                time.sleep(2)
            anchor = page.get_by_text("Sounds of its own", exact=True).first
            anchor.scroll_into_view_if_needed()
            page.evaluate("(el) => el.scrollIntoView({block: 'start'})", anchor.element_handle())
            time.sleep(1)
            for line in page.inner_text("body").splitlines():
                if "music mode" in line.lower():
                    print("page:", line.strip()[:220], flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
