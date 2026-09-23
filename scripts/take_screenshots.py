"""Regenerate the README's docs/screenshots/*.png from the live web UI.

    python scripts/take_screenshots.py

Serves the app from this checkout on a COPY of the app's settings.json and
captures the picker, Extract, Replace Audio, Replace Images, Partition
Explorer and Multi-boot screens with scripts/webui_shot.py (Playwright, Edge
on Windows), straight into docs/screenshots/ under the names the README
embeds.  Nothing is written back into the real settings or the projects they
name (webui_shot sets PAD_UI_CAPTURE).

THE LOG PANE IS COLLAPSED in every shot: it quotes the developer's own
project files, which are not the README's business.

PREVIEW FEATURES ARE STRIPPED FROM THE COPY.  A developer's settings carry
preview codes; a capture made with one would put a preview-only tab on the
README.  The copy has none, and the run fails if a gated tab shows anyway.

Needs on this machine (checked up front; exits without touching the PNGs if
missing): the Stern extract input (a Spike 2 card image) and the project
folder saved in settings.json.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "screenshots")

#: README name -> the capture webui_shot names it
SHOTS = {
    "picker.png": "picker.png",
    "stern-extract.png": "stern-spike2-extract.png",
    "replace-audio.png": "stern-spike2-audio.png",
    "replace-images.png": "stern-spike2-images.png",
    "partition-explorer.png": "stern-spike2-partitions.png",
    "multi-boot.png": "stern-spike2-multiboot.png",
}
GATED_TABS = ("Modes",)


def settings_path():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
            "~/.config")
    return os.path.join(base, "pinball_decryptor", "settings.json")


def main():
    src = settings_path()
    try:
        with open(src, encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("no readable settings.json at %s (%s)" % (src, e))
    stern = (settings.get("manufacturers") or {}).get("stern") or {}
    card = stern.get("extract_input") or settings.get("extract_input") or ""
    project = (stern.get("extract_output") or stern.get("write_assets")
               or settings.get("extract_output") or "")
    if not (card and os.path.isfile(card)):
        sys.exit("the Stern card image in settings.json is not on this "
                 "machine (%r); screenshots left as they are" % card)
    if not (project and os.path.isdir(project)):
        sys.exit("the Stern project folder in settings.json is not on this "
                 "machine (%r); screenshots left as they are" % project)

    scratch = tempfile.mkdtemp(prefix="padreadme-")
    try:
        settings.pop("preview_codes", None)
        settings["disclaimer_accepted"] = True
        settings["last_manufacturer"] = "stern"
        copy = os.path.join(scratch, "settings.json")
        with open(copy, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        shots = os.path.join(scratch, "shots")
        cmd = [sys.executable, os.path.join(REPO, "scripts", "webui_shot.py"),
               "--out", shots, "--settings", copy, "--picker",
               "--mfr", "stern", "--era", "spike2",
               "--input", card, "--project", project, "--wait", "3",
               "--hide-log"]
        for tab in ("extract", "audio", "images", "partitions", "multiboot"):
            cmd += ["--tab", tab]
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        print(r.stdout[-4000:])
        if r.returncode != 0:
            print(r.stderr[-4000:], file=sys.stderr)
            sys.exit("capture failed; screenshots left as they are")
        report_path = os.path.join(shots, "report.json")
        report = {}
        if os.path.isfile(report_path):
            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)
        if report.get("errors"):
            sys.exit("the page reported errors; screenshots left as they "
                     "are:\n  " + "\n  ".join(report["errors"][:10]))
        missing = [v for v in SHOTS.values()
                   if not os.path.isfile(os.path.join(shots, v))]
        if missing:
            sys.exit("missing captures %s; screenshots left as they are"
                     % missing)
        _check_no_gated_tab(copy)
        os.makedirs(OUT, exist_ok=True)
        for readme_name, shot in SHOTS.items():
            shutil.copyfile(os.path.join(shots, shot),
                            os.path.join(OUT, readme_name))
            print("wrote docs/screenshots/%s" % readme_name)
        print("Look at every one before committing it.")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _check_no_gated_tab(settings_copy):
    """Serve the capture settings once more and ask the app which tabs Stern
    Spike 2 shows: a preview-only tab on the README is a leak, so the run
    fails rather than write a single PNG."""
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import webui_shot as W
    scratch = tempfile.mkdtemp(prefix="padreadme-gate-")
    proc, url = W.start_server(settings_copy, scratch)
    try:
        W.api(url, "ui.pick_manufacturer", "stern")
        if W.state(url)["shell"]["mfr"].get("era") != "spike2":
            W.api(url, "ui.set_era", "spike2")
        shown = [t["label"] for t in W.state(url)["shell"]["tabs"]
                 if t["visible"]]
    finally:
        proc.terminate()
        proc.wait(30)
        shutil.rmtree(scratch, ignore_errors=True)
    leaked = [t for t in shown if t in GATED_TABS]
    if leaked:
        sys.exit("the capture would show %s; screenshots left as they are"
                 % leaked)


if __name__ == "__main__":
    main()
