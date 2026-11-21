"""PAD-1475 (reopened) proof shots: a mode's Lights page on James Bond LE 1.06, picking any of the game's light
shows by its number.

    python scripts/shot_pad1475_numbers.py <repo> <out_dir> <before|after>

Serves <repo> (preview on) on a scratch project made from the Bond LE 1.06 card, makes a new mode and writes to
<out_dir>:

* <kind>_lights_list.png - its Lights page, "When it starts" drawn open (the native drop-down cannot be photographed,
  so it is shown as a list box): the shows of the game's own modes under each mode; after, each mode's own shows it
  picks as it plays too, the other shows seen lighting the playfield, and "Another, by its number…" last.
* after_lights_number.png - the start show set to a number no list has (#100), the number box beside the list
  saying what the app knows of it; and #271 (one of Disco Volante Multiball's own shows), #2 (one not lighting).

Prints the start list's groups and options. Needs Playwright (the user site-packages one), the installed Edge and
the card in D:\\Pinball\\images\\Stern\\spike2.
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

CARD = r"D:\Pinball\images\Stern\spike2\james_bond_le-1_06_0.Release.16G.sdcard.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
OPEN_LIST = """(lab) => {
  const row = [...document.querySelectorAll('.modes-kv .lbl')].find((e) => e.textContent.trim() === lab);
  const sel = row && row.nextElementSibling && row.nextElementSibling.querySelector('select');
  if (!sel) return [];
  sel.size = 30;
  sel.style.height = 'auto'; sel.style.width = '460px';
  sel.closest('.field').style.height = 'auto'; sel.closest('.field').style.width = '460px';
  return [...sel.querySelectorAll('optgroup')].map((g) => g.label + ': ' + g.querySelectorAll('option').length);
}"""
ROW_TEXT = """(lab) => {
  const row = [...document.querySelectorAll('.modes-kv .lbl')].find((e) => e.textContent.trim() === lab);
  const box = row && row.nextElementSibling;
  if (!box) return '';
  const sel = box.querySelector('select');
  const num = box.querySelector('input');
  const words = [...box.querySelectorAll('.small.muted')].map((e) => e.innerText).join(' ');
  return [sel ? sel.options[sel.selectedIndex].text : '', num ? 'box ' + num.value : '', words].join(' | ');
}"""


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1475-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.06.0"}, f)
    launcher = os.path.join(scratch, "launch1475.py")
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
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            webui_shot.api(url, "modes.new")
            time.sleep(3)
            page.get_by_role("tab", name="Lights").first.click()
            page.wait_for_selector("text=The game's light shows", timeout=60000)
            try:                                # the card's reading (the game's modes' shows) comes from a worker
                page.wait_for_function("[...document.querySelectorAll('optgroup')].some((g) => "
                                       "g.label.startsWith('From '))", timeout=900000)
            except Exception as e:                           # noqa: BLE001
                print("no mode shows:", e, flush=True)
            time.sleep(2)
            if kind == "after":
                for num in ("#100", "#2", "#271"):
                    webui_shot.api(url, "ui.set", "modes", "f:show_start", num)
                    time.sleep(2.5)
                    print("start %s: %s" % (num, page.evaluate(ROW_TEXT, "When it starts").replace("\n", " | ")),
                          flush=True)
                page.locator(".modes-kv .lbl", has_text="When it starts").first.evaluate(
                    "e => e.scrollIntoView({block: 'center'})")
                page.mouse.move(5, 1290)
                time.sleep(1)
                page.screenshot(path=os.path.join(out_dir, "after_lights_number.png"))
                print("shot lights_number", flush=True)
                webui_shot.api(url, "ui.set", "modes", "f:show_start", "(none)")
                time.sleep(2)
            groups = page.evaluate(OPEN_LIST, "When it starts")
            print("start list groups", groups, flush=True)
            page.locator(".modes-kv .lbl", has_text="When it starts").first.evaluate(
                "e => e.scrollIntoView({block: 'start'})")
            page.mouse.move(5, 1290)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, "%s_lights_list.png" % kind))
            print("shot lights_list | page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        time.sleep(2)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
