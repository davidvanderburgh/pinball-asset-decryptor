"""PAD-199 proof shot: the Emulate tab running a card that is NOT the one
the project in the header was extracted from.

    python scripts/shot_pad199.py <out.png> [foreign|source|build]

The server runs from THIS tree against a scratch settings folder (no WSL, no
rig).  A scratch project "Orchestral Extracted Godzilla" records its source
card (a stand-in godzilla_le 1.16 file) and a card PAD built from it; the
card picked to run is chosen by the second argument:

- foreign: a custom card from somewhere else (the ticket's screenshot)
- source:  the card the project was extracted from
- build:   the card PAD built from the project
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402


def _touch(path, size=4096):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(size))


def main():
    out = os.path.abspath(sys.argv[1])
    which = sys.argv[2] if len(sys.argv) > 2 else "foreign"
    scratch = tempfile.mkdtemp(prefix="pad199-")
    cards = os.path.join(scratch, "Pinball RAW Images")
    source = os.path.join(cards, "godzilla_le-1_16_0.Release.16G.sdcard.raw")
    foreign = os.path.join(cards, "Heisei", "1.16 Heisei Custom V1.93 "
                                              "Standard Edition.raw")
    _touch(source)
    _touch(foreign)
    project = os.path.join(scratch, "Orchestral Extracted Godzilla")
    os.makedirs(project)
    from pinball_decryptor.core import extract_source, project_file
    extract_source.write_extract_source(project, source)
    built = os.path.join(project, "build",
                         "godzilla_le-1_16_0.Release.16G.sdcard-modified.raw")
    _touch(built)
    with open(built + ".pad-build.json", "w", encoding="utf-8") as f:
        json.dump({"version": 1, "assets": project,
                   "stock": {"path": source}}, f)
    card = {"foreign": foreign, "source": source, "build": built}[which]
    paths = {"extract_input": source, "extract_output": project,
             "write_output": "", "write_original": source,
             "write_assets": project}
    project_file.save(project_file.anchor_path(project),
                      manufacturer_key="stern", paths=paths,
                      extract_options={},
                      extra={"emulate_card": card, "emulate_overrides": True})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": source, "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch,
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "emulate")
        time.sleep(3)
        st = webui_shot.state(url)["emulate"]
        print("card:", st.get("card"), "| which:",
              json.dumps(st.get("which"))[:400], flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
