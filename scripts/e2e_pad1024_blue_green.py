"""PAD-1024 end-to-end proof of the blue-green Windows update, with the REAL
setup exe and the REAL swap helper, in a scratch folder.

    python scripts/e2e_pad1024_blue_green.py <scratch_dir>

1. Compiles two installers from this tree's pinball_decryptor.iss (v1.0.0 and
   v9.9.9 payloads), changed only so that they run without administrator
   (PrivilegesRequired=lowest) and compile fast (no compression).  Nothing
   else about the script differs, so /STAGED behaves as it will for users.
2. Installs v1.0.0 with /STAGED into <scratch>\\Pinball Asset Decryptor and
   dresses it as an installed copy: an uninstaller pair, a package pip added
   (padtest_extra) and an OLDER dist-info of a package the bundle ships.
3. Stages v9.9.9 beside it with update_slots.stage_install (the app's code).
4. Runs update_slots.start_swap against a stand-in "app" process, with the
   launch, the controller registration and the fallback installer replaced
   by harmless stand-ins (each would act outside the scratch folder).
5. A second swap with a file held open in the app folder proves the
   fallback: the folder is put back and the stand-in installer runs.

Checks that nothing was written outside the scratch folder that a staged
install must not write: no per-user uninstall entry, no Start-menu folder.
Prints PASS/FAIL per check; exit status 1 on any FAIL.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from pinball_decryptor.core import update_slots as us  # noqa: E402

ISCC = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Inno Setup 6",
                    "ISCC.exe")
PYDIR = os.path.join(REPO, "installer", "build", "python")
KEY = r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" \
      r"\{B8E2D4F6-9A3C-5E7B-CAF1-4A6B8D2E0F3C}_is1"
START = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                     "Start Menu", "Programs", "Pinball Asset Decryptor")
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (" - " + detail if detail
                                                 else ""), flush=True)
    if not ok:
        fails.append(name)


def payload(scratch, version):
    """A copy of this tree's app files with __version__ = *version*."""
    src = os.path.join(scratch, "src_" + version)
    if os.path.isdir(src):
        return src
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.splitlines()
    for rel in files:
        if not (rel.startswith(("pinball_decryptor/", "tools/", "LICENSE",
                                "Pinball Asset Decryptor.pyw"))):
            continue
        dst = os.path.join(src, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(REPO, rel), dst)
    init = os.path.join(src, "pinball_decryptor", "__init__.py")
    text = open(init, encoding="utf-8").read()
    text = re.sub(r'__version__\s*=\s*"[^"]+"', '__version__ = "%s"' % version,
                  text)
    open(init, "w", encoding="utf-8").write(text)
    return src


def build(scratch, version):
    out = os.path.join(scratch, "out")
    exe = os.path.join(out, "Pinball_Asset_Decryptor_v%s_Windows.exe" % version)
    if os.path.isfile(exe):
        return exe
    iss = open(os.path.join(REPO, "installer", "pinball_decryptor.iss"),
               encoding="utf-8").read()
    iss = iss.replace("PrivilegesRequired=admin", "PrivilegesRequired=lowest")
    iss = re.sub(r"^Compression=.*$", "Compression=none", iss, flags=re.M)
    iss = re.sub(r"^(SolidCompression|LZMA\w+)=.*$", "", iss, flags=re.M)
    iss = iss.replace("[Setup]", "[Setup]\nOutputDir=%s" % out, 1)
    test_iss = os.path.join(REPO, "installer", "_pad1024_e2e.iss")
    open(test_iss, "w", encoding="utf-8").write(iss)
    try:
        r = subprocess.run([ISCC, "/Qp", "/DAppVersion=" + version,
                            "/DPythonDir=" + PYDIR,
                            "/DProjectDir=" + payload(scratch, version),
                            test_iss], capture_output=True, text=True)
    finally:
        os.unlink(test_iss)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("ISCC failed for %s" % version)
    return exe


def reg_exists():
    return subprocess.run(["reg", "query", KEY], capture_output=True
                          ).returncode == 0


def main():
    scratch = os.path.abspath(sys.argv[1])
    os.makedirs(scratch, exist_ok=True)
    app = os.path.join(scratch, "Pinball Asset Decryptor")
    for d in (app, us.next_dir(app), us.old_dir(app)):
        shutil.rmtree(d, ignore_errors=True)
    reg_before, start_before = reg_exists(), os.path.isdir(START)
    old_exe, new_exe = build(scratch, "1.0.0"), build(scratch, "9.9.9")
    print("built", old_exe, new_exe, flush=True)

    # --- the "installed" v1.0.0 ---------------------------------------
    t = time.time()
    r = subprocess.run('"%s" %s' % (old_exe, us.STAGE_ARGS % app),
                       capture_output=True)
    check("v1.0.0 installs with /STAGED", r.returncode == 0,
          "code %s, %.0f s" % (r.returncode, time.time() - t))
    check("v1.0.0 has no uninstaller of its own (Uninstallable=not IsStaged)",
          not glob.glob(os.path.join(app, "unins*")))
    for n in ("unins000.exe", "unins000.dat"):
        open(os.path.join(app, n), "wb").write(b"uninstaller of v1.0.0")
    site = os.path.join(app, "python", "Lib", "site-packages")
    os.makedirs(os.path.join(site, "padtest_extra"))
    open(os.path.join(site, "padtest_extra", "__init__.py"), "w").write("X=1\n")
    os.makedirs(os.path.join(site, "padtest_extra-0.1.dist-info"))
    shipped = sorted(n for n in os.listdir(site) if n.endswith(".dist-info"))
    old_ver = None
    if shipped:
        proj = shipped[0].split("-")[0]
        old_ver = "%s-0.0.1.dist-info" % proj
        os.makedirs(os.path.join(site, old_ver))
    check("installed copy recognised", us.installed_app_dir(
        os.path.join(app, "python", "pythonw.exe")) == app)

    # --- stage v9.9.9 beside it (the app's own code) --------------------
    t = time.time()
    ok, info = us.stage_install(new_exe, app, "9.9.9")
    check("v9.9.9 staged beside it", ok, "%s, %.0f s" % (
        info if not ok else "carried %d" % len(info), time.time() - t))
    nxt = us.next_dir(app)
    check("staged copy is whole and v9.9.9",
          us.staged_install_ok(app, "9.9.9"))
    check("pip-added package carried over", os.path.isfile(os.path.join(
        nxt, "python", "Lib", "site-packages", "padtest_extra",
        "__init__.py")))
    check("uninstaller carried over", open(os.path.join(
        nxt, "unins000.dat"), "rb").read() == b"uninstaller of v1.0.0")
    if old_ver:
        check("an older dist-info of a shipped package is NOT carried",
              not os.path.exists(os.path.join(nxt, "python", "Lib",
                                              "site-packages", old_ver)))
    check("compiled during staging", bool(glob.glob(os.path.join(
        nxt, "pinball_decryptor", "__pycache__", "*.pyc"))))
    check("running copy untouched", us.tree_version(app) == "1.0.0")
    check("no uninstall entry written", reg_exists() == reg_before)
    check("no Start-menu folder written", os.path.isdir(START) == start_before)

    # --- the swap, with a stand-in app process ---------------------------
    marker = os.path.join(scratch, "fallback_ran.txt")
    if os.path.exists(marker):
        os.unlink(marker)                  # an earlier run's
    fake_setup = os.path.join(scratch, "fake_setup.cmd")
    open(fake_setup, "w").write('@echo ran %%* > "%s"\n' % marker)
    stand_in = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(3)"], cwd=scratch)
    log = os.path.join(scratch, "swap.log")
    if os.path.exists(log):
        os.unlink(log)
    t = time.time()
    # through the app's own launch (PAD-1029: running the script here by
    # hand hid that start_swap's detached powershell.exe never ran it)
    ok, info = us.start_swap(app, "9.9.9", fake_setup, pid=stand_in.pid,
                             launch=False, register=False, log_path=log)
    check("swap helper started", ok, str(info))

    def _log():
        return open(log, encoding="utf-8").read() \
            if os.path.exists(log) else ""
    while time.time() - t < 90 and not (
            "swapped in" in _log() and not os.path.exists(us.old_dir(app))):
        time.sleep(0.2)
    took = time.time() - t
    print(_log() or "(no log)", flush=True)
    check("swap ran to the end", "swapped in v9.9.9" in _log(),
          "%.1f s incl. the 3 s stand-in app" % took)
    ps1 = os.path.join(scratch, "swap.ps1")
    check("app folder now holds v9.9.9", us.tree_version(app) == "9.9.9")
    check("pip-added package still there after the swap", os.path.isfile(
        os.path.join(site, "padtest_extra", "__init__.py")))
    check("uninstaller still there", os.path.isfile(os.path.join(
        app, "unins000.exe")))
    check(".next and .old gone", not os.path.exists(nxt)
          and not os.path.exists(us.old_dir(app)))
    check("staged marker removed", not os.path.exists(os.path.join(
        app, us.MARKER)))
    check("fallback installer not run", not os.path.exists(marker))

    # --- a swap that cannot rename falls back to the installer -----------
    ok, info = us.stage_install(new_exe, app, "9.9.9")
    check("re-staged for the fallback run", ok, str(info)[:200])
    held = open(os.path.join(app, "LICENSE"), "rb")      # a file in use
    held_dir = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(30)"],
                                cwd=os.path.join(app, "pinball_decryptor"))
    try:
        open(ps1, "w", encoding="utf-8-sig", newline="\r\n").write(
            us.swap_script(app, "9.9.9", fake_setup, 0, log, launch=False,
                           register=False))
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-File", ps1],
                           cwd=scratch, capture_output=True, text=True)
    finally:
        held.close()
        held_dir.kill()
        held_dir.wait()
    time.sleep(1.5)
    print(open(log, encoding="utf-8").read()[-600:], flush=True)
    check("folder in use: app folder left in place",
          us.tree_version(app) == "9.9.9" and os.path.isdir(app))
    check("folder in use: the installer ran instead", os.path.exists(marker),
          open(marker).read().strip()[:200] if os.path.exists(marker) else "")
    shutil.rmtree(nxt, ignore_errors=True)

    print("\n%d failed" % len(fails) if fails else "\nALL PASSED", flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
