"""PAD-396 proof shots: a Godzilla Premium/LE mode taken to a Godzilla Pro card.

    python scripts/shot_pad396.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before"
shots). Two projects are made in a scratch folder, a Premium/LE 1.16 one and a Pro 1.16 one, both in
the settings' known projects. The Premium one holds KAIJU BRIDGE: it starts on the centre shield
target, scores the shield ramp spinner and both ramps, holds the magnet, and holds the bridge and the
Mechagodzilla magnet (Premium/LE only). Writes into <out_dir>:

- <prefix>_opened_on_pro.png  the same mode file copied as it is into the Pro project and opened there
- <prefix>_port_report.png    the Premium project's mode taken to the Pro project: on a tree with
                              ``MP.port_modes`` by its Port to Pro button, else by Copy to...; the
                              message the app answers with
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

LE_CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
PRO_CARD = "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"


def _project(scratch, name, card):
    project = os.path.join(scratch, name)
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    return project


def _serve(repo, scratch, project, known):
    """shot_pad232._serve, with ``known`` in the settings' known projects."""
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        codes = json.load(f).get("preview_codes", [])
    launcher = os.path.join(scratch, "launch396.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": codes,
                   "projects": [{"folder": k, "manufacturer": "stern", "last_opened": ""} for k in known],
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("serving", repo, "port_modes" if hasattr(MP, "port_modes") else "(no port_modes)", flush=True)

    scratch = tempfile.mkdtemp(prefix="pad396-")
    prem = _project(scratch, "GZ 1.16 Premium", LE_CARD)
    pro = _project(scratch, "GZ 1.16 Pro", PRO_CARD)
    spec = MP.ModeSpec(name="KAIJU BRIDGE", title="godzilla_le_1_16")
    spec.start_shot, spec.start_count = "Shield target center", 2
    spec.scoring_shots = ["Shield ramp spinner", "Left ramp", "Right ramp"]
    spec.magnet_ms = 2000
    spec.coil_holds = [["bridge", 3000, "Left ramp"], ["mg_magnet", 2000, ""]]
    slug, _path = MP.new_mode(prem, spec=spec)
    print("premium problems:", MP.validate(spec), flush=True)

    # 1. the Premium mode's file, copied by hand into the Pro project and opened there
    shutil.copytree(MP.mode_folder(prem, slug), MP.mode_folder(pro, slug))
    proc, url = _serve(repo, scratch, pro, [pro, prem])
    try:
        def opened(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            st = webui_shot.state(url)
            print("status:", (st.get("modes") or {}).get("status"), flush=True)
            out = os.path.join(out_dir, "%s_opened_on_pro.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, opened, height=1000)
    finally:
        proc.terminate()
    shutil.rmtree(MP.mode_folder(pro, slug))

    # 2. the Premium project's modes taken to the Pro project
    proc, url = _serve(repo, scratch, prem, [prem, pro])
    try:
        def port(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(2)
            btn = page.get_by_role("button", name="Port to Pro")
            if btn.count():
                btn.first.click()
                time.sleep(1)
                page.get_by_text("GZ 1.16 Pro", exact=False).last.click()
            else:
                threading.Thread(target=webui_shot.api, args=(url, "modes.copy_to", pro),
                                 daemon=True).start()
            time.sleep(4)
            out = os.path.join(out_dir, "%s_port_report.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, port, height=1000)
    finally:
        proc.terminate()
    for s, sp in MP.list_modes(pro)[0]:
        print("in pro:", s, sp.title, sp.start_shot, sp.scoring_shots, sp.coil_holds, MP.validate(sp), flush=True)


if __name__ == "__main__":
    main()
