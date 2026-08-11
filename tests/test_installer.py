"""Static + structural checks for the prerequisite installers.

Several installer bugs reached users because the installer scripts
had no test coverage:

  * GDRE Tools install — a bash script embedded in a PowerShell
    here-string picked up a UTF-8 BOM and CRLF line endings, which
    broke it inside WSL ("set: command not found", unterminated
    heredoc).
  * faster-whisper — the pip step searched only PATH for a Python, so
    on a packaged install (which ships its own Python and puts nothing
    on PATH) it silently skipped the install.
  * GDRE prereq check — the BOF gdre_tools probe used `which`, a PATH
    lookup that traverses WSL's appended Windows PATH and failed
    intermittently, reporting GDRE missing when it was installed.
  * faster-whisper perms — the elevated installer pip-installed it
    under Program Files with permissions the normal-user app process
    could not read ([Errno 13] Permission denied on import). A plain
    `icacls /grant` didn't fully fix it; the install step must
    `icacls /reset` the bundled-Python tree so it re-inherits the
    parent ACL. The Inno installer repeats the repair on every
    install, so an install-over-the-top fixes an already-broken
    machine without re-running the prerequisites installer.
  * macOS / Linux plugin discovery — PyInstaller's static-import
    analyser cannot follow ``importlib.import_module(<string>)`` in
    ``core/registry.py``, so without explicit ``--collect-submodules
    pinball_decryptor.plugins`` the .app / AppImage shipped with an
    empty plugins/ tree and every plugin failed with "No module
    named pinball_decryptor.plugins.<name>" on launch (v0.7.1 macOS
    build hit this).

These tests guard those classes: installer shell scripts must stay
LF-only and parse clean, the PowerShell installer must stay
syntactically valid, and the specific fixes must not regress.

A true end-to-end run of the installer (WSL provisioning, apt, etc.)
isn't feasible in CI — `wsl --install` needs a reboot and nested
virtualisation.  These are the checks that *are* feasible and would
have caught both shipped bugs.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "installer"
SH_SCRIPTS = sorted(INSTALLER.glob("*.sh"))
PS1 = INSTALLER / "install_prerequisites.ps1"
ISS = INSTALLER / "pinball_decryptor.iss"
PYINSTALLER_BUILD_SCRIPTS = [
    INSTALLER / "build_macos.sh",
    INSTALLER / "build_linux.sh",
]
WINDOWS_BUILD = INSTALLER / "build.ps1"


def test_installer_layout():
    """The shared GDRE script and the PowerShell installer must exist."""
    assert PS1.is_file(), "install_prerequisites.ps1 missing"
    assert ISS.is_file(), "pinball_decryptor.iss missing"
    assert (INSTALLER / "install_gdre.sh").is_file(), (
        "install_gdre.sh missing — both installers depend on it")
    assert SH_SCRIPTS, "no installer shell scripts found"


@pytest.mark.parametrize("sh", SH_SCRIPTS, ids=lambda p: p.name)
def test_shell_script_is_lf_only(sh):
    """Installer .sh files run under bash (WSL / Linux); a stray CR
    breaks heredoc terminators and `#!` shebang lines.  `.gitattributes`
    pins them to LF — this catches a regression of that."""
    assert b"\r" not in sh.read_bytes(), (
        f"{sh.name} contains CR bytes — must be LF-only "
        f"(see .gitattributes: '*.sh text eol=lf')")


def _bash_works():
    """True only if `bash` is present AND functional.

    On Windows the `bash` on PATH is often the WSL launcher
    (C:\\Windows\\System32\\bash.exe); with no WSL distro installed it
    exists but fails every command — so a plain which('bash') isn't
    enough (this is what broke the v0.6.1 CI on the Windows runner)."""
    if shutil.which("bash") is None:
        return False
    try:
        return subprocess.run(
            ["bash", "-c", "exit 0"],
            capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _bash_works(),
                    reason="no working bash (WSL launcher without a distro?)")
@pytest.mark.parametrize("sh", SH_SCRIPTS, ids=lambda p: p.name)
def test_shell_script_parses(sh):
    """`bash -n` — syntax-check each installer shell script.

    The script is fed on stdin rather than as a path argument so it
    works whichever `bash` is on PATH — git-bash and the WSL launcher
    disagree on how to interpret a native Windows path."""
    r = subprocess.run(["bash", "-n"], input=sh.read_bytes(),
                       capture_output=True)
    assert r.returncode == 0, (
        f"{sh.name} failed `bash -n`:\n"
        f"{r.stderr.decode('utf-8', 'replace')}")


def _powershell():
    return shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(_powershell() is None,
                    reason="PowerShell not available")
def test_powershell_installer_parses():
    """AST-parse install_prerequisites.ps1 — catches syntax breaks
    before they ship (the GDRE bug shipped a script that broke at
    runtime; a parse error in the .ps1 itself would be just as bad)."""
    check = (
        "$e=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{PS1}',[ref]$null,[ref]$e)|Out-Null;"
        "if($e){$e|ForEach-Object{Write-Output $_.Message};exit 1}")
    r = subprocess.run([_powershell(), "-NoProfile", "-Command", check],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"install_prerequisites.ps1 has parse errors:\n{r.stdout}")


def test_gdre_install_is_consolidated():
    """Regression guard — GDRE BOM/CRLF bug.

    The GDRE install logic must be the shared install_gdre.sh run as a
    real file, NOT a bash script embedded in a PowerShell here-string
    and piped to WSL (`bash -s`), which is what corrupted it.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "install_gdre.sh" in ps1, (
        "install_prerequisites.ps1 must run the shared install_gdre.sh")
    assert "bash -s" not in ps1, (
        "install_prerequisites.ps1 pipes a script to `bash -s` again — "
        "that reintroduces the BOM/CRLF corruption. Run install_gdre.sh "
        "as a file instead.")


def test_wsl_installs_check_firmware_virtualization():
    """Regression guard — PAD-21 (virtualization disabled in BIOS/UEFI).

    With firmware virtualization off, `wsl --install` fails with
    0x80370102 in plain console color; the message scrolled past a user
    unnoticed through three support round-trips of reinstall advice that
    could never work.  Both WSL install paths (the framework install and
    the Ubuntu registration) must consult Test-VirtualizationDisabled and
    show the red banner instead of attempting a doomed install.  The
    probe must gate on HypervisorPresent — Windows reports the firmware
    flag False whenever a hypervisor is already running, so the flag
    alone would false-positive on every healthy Hyper-V machine.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "HypervisorPresent" in ps1, (
        "Test-VirtualizationDisabled must check HypervisorPresent first — "
        "VirtualizationFirmwareEnabled reads False on machines where a "
        "hypervisor is already running.")
    assert "VirtualizationFirmwareEnabled" in ps1, (
        "install_prerequisites.ps1 must probe the firmware virtualization "
        "flag so a disabled BIOS/UEFI setting is named instead of retried.")
    assert ps1.count("Test-VirtualizationDisabled") >= 3, (
        "Both WSL install paths (WSL2 framework + Ubuntu registration) "
        "must consult Test-VirtualizationDisabled before installing.")


def test_pip_step_uses_bundled_python():
    """Regression guard — faster-whisper skip bug.

    The pip step must look for the app's bundled interpreter
    ({app}\\python\\python.exe), not only a `python` on PATH — a
    packaged install ships its own Python and puts nothing on PATH, so
    a PATH-only search silently skips every pip package.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "python\\python.exe" in ps1, (
        "install_prerequisites.ps1's pip step must discover the bundled "
        "interpreter ({app}\\python\\python.exe) — without it, packaged "
        "installs silently skip pip packages like faster-whisper.")


def test_pip_step_fixes_read_permissions():
    """Regression guard — faster-whisper [Errno 13] (RTS feedback).

    The installer runs elevated; packages it pip-installs under Program
    Files can land unreadable to the normal-user app process. The pip
    step must repair this so `import faster_whisper` (and its deps, e.g.
    typing_extensions) don't fail with Permission denied.

    It must use `icacls /reset` — a plain `/grant` only adds an allow
    ACE and cannot override a stray DENY or broken ACL inheritance
    (this is why the v0.6.3 `/grant`-only fix still left
    typing_extensions.py unreadable). The explicit Users-group
    (SID S-1-5-32-545) grant stays as a belt-and-suspenders guard.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "icacls" in ps1, (
        "install_prerequisites.ps1's pip step must fix file perms on "
        "the bundled Python — without it, elevated-installed pip "
        "packages are unreadable to the app (Errno 13 on import).")
    assert "/reset" in ps1, (
        "install_prerequisites.ps1 must use `icacls /reset` to repair "
        "perms — a plain `/grant` cannot override a DENY ACE or broken "
        "inheritance (v0.6.3's /grant-only fix regressed on this).")
    assert "S-1-5-32-545" in ps1, (
        "install_prerequisites.ps1 should also keep the explicit Users "
        "group (SID S-1-5-32-545) read grant as a belt-and-suspenders "
        "guard for hardened systems with a non-standard Program Files "
        "ACL.")


# Derived from the registry's actual load list, NOT hardcoded — so the
# guard can never go stale.  The moment a manufacturer is added to
# core/registry._PLUGIN_MODULES it becomes required in the build scripts
# too.  A hardcoded copy here is precisely what let American Pinball (ap)
# and Dutch Pinball (dp) be wired into the registry yet omitted from the
# PyInstaller --hidden-import list, so the Linux AppImage / macOS .app
# silently shipped without them (Windows bundles the whole source tree,
# so it was unaffected — which is why the bug only showed on Mint).
from pinball_decryptor.core.registry import _PLUGIN_MODULES as _PLUGIN_PACKAGES


@pytest.mark.parametrize(
    "script", PYINSTALLER_BUILD_SCRIPTS,
    ids=lambda p: p.name)
def test_pyinstaller_explicit_plugin_hidden_imports(script):
    """Regression guard — v0.7.1/v0.7.2/v0.7.3 macOS dead-on-arrival.

    Plugins are loaded dynamically via
    ``importlib.import_module(<string>)`` in core/registry.py.
    PyInstaller's static analyser cannot trace string-based imports,
    AND ``--collect-submodules pinball_decryptor.plugins`` silently
    no-ops at build time in PyInstaller 6.x for packages added via
    ``--paths`` (v0.7.2 and v0.7.3 macOS builds confirmed: empty
    plugins/ tree in the bundle, app crashed at startup with
    "no manufacturer plugins registered").

    The bulletproof mechanism is an explicit ``--hidden-import`` for
    each plugin package: PyInstaller then imports the package's
    __init__.py during analysis and follows the transitive
    manufacturer.py / pipeline.py imports the normal way.

    Every plugin in the registry MUST appear in the build script's
    --hidden-import list, or the bundle will silently drop it.
    """
    if not script.exists():
        pytest.skip(f"{script.name} not present in this checkout")
    src = script.read_text(encoding="utf-8", errors="replace")
    assert "pyinstaller" in src.lower(), (
        f"{script.name} is no longer a PyInstaller build script — "
        f"this test needs an updated check.")
    missing = []
    for pkg in _PLUGIN_PACKAGES:
        # Tolerate either single- or double-quoted forms.
        if (f'--hidden-import "{pkg}"' not in src
                and f"--hidden-import '{pkg}'" not in src
                and f"--hidden-import {pkg}" not in src):
            missing.append(pkg)
    assert not missing, (
        f"{script.name} is missing --hidden-import for: "
        f"{', '.join(missing)}.  Without these, the bundle ships "
        f"with no plugin source code and the app crashes on launch "
        f"with 'no manufacturer plugins registered'.  See the "
        f"v0.7.4 fix notes for context.")


# Stern is the one plugin whose engine is imported LAZILY (inside functions,
# via relative imports) so its heavy deps (unicorn/capstone/numpy) aren't
# required at plugin-discovery time.  PyInstaller's static analyser can't
# follow those lazy imports, so each engine submodule needs its own explicit
# --hidden-import or the Linux/macOS bundle silently drops it — and the app
# would crash only later, the moment a user runs Extract/Write.  Glob-derived
# so adding a spike2 module makes it required in the build scripts too (it
# can't go stale the way the v0.7.x per-plugin list did).
_STERN = REPO / "pinball_decryptor" / "plugins" / "stern"

# Top-level stern modules reachable the *normal* way (the `stern` package
# hidden-import pulls in __init__ -> manufacturer -> pipeline/games/formats, all
# top-level imports), so they don't need their own --hidden-import.  Everything
# else at the top level (engine, ext4, rawdevice, radium, ...) is imported
# function-locally by engine.py / pipeline.py and so must be listed explicitly.
_STERN_PKG_REACHABLE = {"__init__", "manufacturer", "pipeline", "games",
                        "formats"}


def _stern_lazy_modules():
    """Glob-derived (top level + spike2/) so a newly-added lazily-imported
    stern engine module becomes required in the build scripts automatically —
    it can't go stale the way a hardcoded list would."""
    mods = ["pinball_decryptor.plugins.stern.spike2"]
    for p in sorted(_STERN.glob("*.py")):
        if p.stem not in _STERN_PKG_REACHABLE:
            mods.append("pinball_decryptor.plugins.stern." + p.stem)
    for p in sorted((_STERN / "spike2").glob("*.py")):
        if p.stem != "__init__":
            mods.append("pinball_decryptor.plugins.stern.spike2." + p.stem)
    return mods


@pytest.mark.skipif(not (_STERN / "spike2").is_dir(),
                    reason="stern spike2 engine not present")
@pytest.mark.parametrize("script", PYINSTALLER_BUILD_SCRIPTS, ids=lambda p: p.name)
def test_stern_lazy_engine_hidden_imports(script):
    if not script.exists():
        pytest.skip(f"{script.name} not present in this checkout")
    src = script.read_text(encoding="utf-8", errors="replace")
    missing = [m for m in _stern_lazy_modules()
               if f'--hidden-import "{m}"' not in src
               and f"--hidden-import '{m}'" not in src
               and f"--hidden-import {m}" not in src]
    assert not missing, (
        f"{script.name} is missing --hidden-import for stern's lazily-loaded "
        f"engine module(s): {', '.join(missing)}.  PyInstaller cannot follow "
        f"the lazy imports in stern/engine.py, so the bundle would drop these "
        f"and Extract/Write would crash on Linux/macOS.")
    for dep in ("unicorn", "capstone"):
        assert (f'--collect-all "{dep}"' in src or f"--collect-all '{dep}'" in src
                or f"--collect-all {dep}" in src), (
            f"{script.name} must --collect-all {dep} (it ships a native library "
            f"the Spike 2 engine loads at runtime).")


@pytest.mark.parametrize("script", PYINSTALLER_BUILD_SCRIPTS, ids=lambda p: p.name)
def test_pyinstaller_build_installs_runtime_deps(script):
    """Regression guard — frozen-build missing-deps bug (Stern DOA on macOS).

    The build scripts --collect-all unicorn/capstone (guarded above) and rely
    on PyInstaller's import analysis to bundle numpy/zstandard/etc.  But
    --collect-all and import analysis can only collect what is INSTALLED in the
    build environment.  The v0.15.0 macOS DMG shipped with all four Stern
    prerequisites missing because the build installed a hardcoded list
    (UnityPy/fsb5/pyogg/Pillow) that omitted the requirements.txt deps
    (unicorn/capstone/numpy) entirely — and a frozen bundle cannot be
    pip-fixed by the user, so the whole Stern audio feature was dead.

    The build MUST install the runtime deps from requirements.txt (the single
    source of truth) so the collect step actually has something to collect.
    """
    if not script.exists():
        pytest.skip(f"{script.name} not present in this checkout")
    src = script.read_text(encoding="utf-8", errors="replace")
    assert "requirements.txt" in src, (
        f"{script.name} must `pip install -r requirements.txt` so the frozen "
        f"bundle includes the declared runtime deps (unicorn/capstone/numpy/"
        f"zstandard/...).  Installing a hardcoded subset is exactly what shipped "
        f"the v0.15.0 macOS DMG with every Stern prerequisite missing.")


@pytest.mark.parametrize("script", PYINSTALLER_BUILD_SCRIPTS, ids=lambda p: p.name)
def test_pyinstaller_bundles_whisper_stack(script):
    """faster-whisper (Auto-name call-outs) must be bundled into the frozen
    Mac/Linux apps.

    A frozen bundle can't pip-install faster-whisper after the fact, so if it
    isn't collected at build time the feature is unusable there with no user
    workaround.  Installing the package is necessary but not sufficient: its
    native deps (ctranslate2 / onnxruntime / PyAV) need an explicit
    --collect-all to pull their shared libraries into the bundle — import
    analysis alone misses them.
    """
    if not script.exists():
        pytest.skip(f"{script.name} not present in this checkout")
    src = script.read_text(encoding="utf-8", errors="replace")
    assert "faster-whisper" in src or "faster_whisper" in src, (
        f"{script.name} must install + collect faster-whisper so Auto-name "
        f"call-outs works in the frozen app (it can't be added post-install).")
    for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av"):
        assert (f'--collect-all "{pkg}"' in src
                or f"--collect-all '{pkg}'" in src
                or f"--collect-all {pkg}" in src), (
            f"{script.name} must --collect-all {pkg} — faster-whisper's native "
            f"runtime libraries aren't bundled by PyInstaller import analysis "
            f"alone.")


@pytest.mark.parametrize("script", PYINSTALLER_BUILD_SCRIPTS, ids=lambda p: p.name)
def test_pyinstaller_bundles_ffmpeg(script):
    """The frozen Mac/Linux apps must bundle an ffmpeg binary (via the
    imageio-ffmpeg wheel) so the Replace Audio/Video tabs work without a
    system ffmpeg.

    The apps are frozen, so the user can't install ffmpeg into them, and a Mac
    .app launched from Finder doesn't even inherit a shell PATH to locate a
    brew install.  core/audio.find_ffmpeg() falls back to imageio_ffmpeg's
    bundled binary -- which only exists in the app if the package is both
    installed in the build env AND collected by PyInstaller.
    """
    if not script.exists():
        pytest.skip(f"{script.name} not present in this checkout")
    src = script.read_text(encoding="utf-8", errors="replace")
    assert "imageio-ffmpeg" in src, (
        f"{script.name} must install imageio-ffmpeg so the frozen app ships a "
        f"working ffmpeg (Replace Audio/Video need it, and a frozen app can't "
        f"have one added later).")
    assert ('--collect-all "imageio_ffmpeg"' in src
            or "--collect-all 'imageio_ffmpeg'" in src
            or "--collect-all imageio_ffmpeg" in src), (
        f"{script.name} must --collect-all imageio_ffmpeg so its bundled "
        f"ffmpeg binary actually lands in the frozen app.")


@pytest.mark.parametrize("script", PYINSTALLER_BUILD_SCRIPTS, ids=lambda p: p.name)
def test_pyinstaller_collects_all_of_pillow(script):
    """Every preview canvas needs PIL.ImageTk, which needs more of Pillow
    than static analysis finds.

    Naming ``PIL`` + ``PIL.Image`` bundles enough to open an image and not
    enough to draw one: ImageTk's Tk glue reaches PIL._tkinter_finder and
    the _imagingtk extension by paths PyInstaller's tracer never walks.
    The v0.86-v0.88 AppImages shipped exactly that way and every video
    frame preview came up "No module named 'PIL._tkinter_finder'" (a tester) --
    a frozen bundle the user cannot pip-fix.  --collect-all takes the
    submodules, the data and the native libraries together.
    """
    if not script.exists():
        pytest.skip(f"{script.name} not present in this checkout")
    src = script.read_text(encoding="utf-8", errors="replace")
    assert ('--collect-all "PIL"' in src or "--collect-all 'PIL'" in src
            or "--collect-all PIL" in src), (
        f"{script.name} must --collect-all PIL — hidden-importing PIL/PIL.Image "
        f"alone drops PIL._tkinter_finder and _imagingtk, which kills every "
        f"image and video preview in the frozen app.")
    for mod in ("PIL.ImageTk", "PIL._tkinter_finder"):
        assert (f'--hidden-import "{mod}"' in src
                or f"--hidden-import '{mod}'" in src
                or f"--hidden-import {mod}" in src), (
            f"{script.name} must --hidden-import {mod} — belt-and-braces "
            f"alongside --collect-all PIL, because these two are the exact "
            f"modules whose absence broke previews in the AppImage.")


def test_windows_build_installs_runtime_deps():
    """Regression guard — Windows fresh-install missing Stern deps (a tester).

    The Windows app ships an isolated embeddable Python under {app}\\python;
    its bundled site-packages is the ONLY interpreter the app uses (the ._pth
    sandboxes it from any system Python).  build.ps1 must pre-install the
    runtime deps from requirements.txt into that bundle -- otherwise a fresh
    install has no unicorn/capstone/numpy and Stern audio fails, and a user's
    manual `pip install` into their system Python can't help (wrong
    interpreter: pip reports "already satisfied" while the app still can't
    import them).
    """
    if not WINDOWS_BUILD.exists():
        pytest.skip("build.ps1 not present in this checkout")
    src = WINDOWS_BUILD.read_text(encoding="utf-8", errors="replace")
    assert "requirements.txt" in src, (
        "build.ps1 must `pip install -r requirements.txt` into the bundled "
        "Python so a fresh Windows install ships the runtime deps "
        "(unicorn/capstone/numpy/zstandard).  A hardcoded subset is what left "
        "Stern's deps out and pushed users to a wrong-interpreter manual pip.")


def test_windows_build_bundles_ffmpeg():
    """Regression guard — "ffmpeg not found" on a fresh Windows install
    (a tester).

    The Replace Audio/Video tabs convert non-native formats + resample via
    ffmpeg.  On Windows the app's isolated embeddable Python can't fall back to
    a system ffmpeg the user installs into their own interpreter, and a fresh
    box often has none on PATH at all -- so build.ps1 must pip-install
    imageio-ffmpeg into the bundle (it ships a real ffmpeg.exe).
    core/audio.find_ffmpeg() + ensure_bundled_ffmpeg_on_path() then expose it,
    the same way the Mac/Linux frozen apps already do.
    """
    if not WINDOWS_BUILD.exists():
        pytest.skip("build.ps1 not present in this checkout")
    src = WINDOWS_BUILD.read_text(encoding="utf-8", errors="replace")
    assert "imageio-ffmpeg" in src, (
        "build.ps1 must install imageio-ffmpeg into the bundled Python so a "
        "fresh Windows install ships a working ffmpeg -- otherwise Replace "
        "Audio/Video show 'ffmpeg not found' and can't convert/resample.")


def test_windows_installer_offers_every_stern_pip_dep():
    """Regression guard — Stern absent from Install Missing (a tester).

    install_prerequisites.ps1 (what the GUI's "Install Missing" runs) had no
    Stern Pinball entry, so its manufacturer picker showed no Spike 2 option
    and a Windows user could not install unicorn/capstone through the app at
    all.  Derive Stern's pip-probe prerequisites from the registry and require
    each to appear in the installer, so a newly-added Stern pip dep can't go
    stale here the way the original omission did.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "Stern Pinball" in ps1, (
        "install_prerequisites.ps1 has no 'Stern Pinball' entry -- the GUI's "
        "Install Missing then offers no Spike 2 option, so Windows users can't "
        "install unicorn/capstone through the app.")
    from pinball_decryptor.core.registry import load_plugins, get_manufacturer
    load_plugins()
    stern = get_manufacturer("stern")
    pip_prereqs = [p for p in stern.prerequisites
                   if p.probe.startswith("python:")]
    missing = [p.name for p in pip_prereqs
               if p.name not in ps1 and p.name.replace("-", "_") not in ps1]
    assert not missing, (
        f"install_prerequisites.ps1's Stern entry is missing pip prereq(s): "
        f"{', '.join(missing)} -- Install Missing won't install them on Windows.")


def test_both_installers_offer_every_emulator_package_the_tab_names():
    """Regression guard — the native compiler was on nobody's list.

    The Emulate tab probes what a run needs (emulate_tab._SETUP_TOOLS); the two
    installers are where a user who never opens that tab gets the same things.
    Those were three separate lists and they came apart: the rig compiles the
    ARM shim AND a native renderer, only the cross compiler was ever named, and
    a user with gcc-arm-linux-gnueabihf and no gcc watched the shim build and
    the run die on padglhost thirty seconds later.

    Derived from the tab, so a sixth prerequisite cannot go stale here the way
    the fifth did.  libc6-dev is part of it for the reason the JJP entry
    already records: gcc only *recommends* the headers."""
    from pinball_decryptor.gui.emulate_tab import (_SETUP_OPTIONAL,
                                                   _SETUP_TOOLS)
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    linux = (INSTALLER / "install_prerequisites_linux.sh").read_text(
        encoding="utf-8", errors="replace")
    # The Stern block only, in both: `gcc` alone appears under JJP already, and
    # a match there would prove nothing about the Spike 2 user.
    ps1_stern = ps1.split('"Stern Pinball" = @{', 1)[-1]
    # [6] is Stern in every one of that script's parallel arrays, so scope to
    # the packages one — MFR_NAMES[6] would otherwise match and prove nothing.
    assert "MFR_PACKAGES=(" in linux, (
        "install_prerequisites_linux.sh lost its package manifest")
    linux_pkgs = linux.split("MFR_PACKAGES=(", 1)[1].split("\n)", 1)[0]
    linux_stern = [ln for ln in linux_pkgs.splitlines()
                   if ln.strip().startswith("[6]=")]
    assert linux_stern, "install_prerequisites_linux.sh lost its Stern package list"
    # _SETUP_OPTIONAL too: busybox-static costs the save states rather than the
    # run, but the installer is still where a user who never opens the tab gets
    # it - and that omission is exactly what made v0.126.0 refuse to start.
    for _key, pkg, _why in _SETUP_TOOLS + _SETUP_OPTIONAL:
        for name in pkg.split():
            assert name in ps1_stern, (
                f"install_prerequisites.ps1's Stern entry never installs "
                f"{name} — the Emulate tab needs it and Install Missing "
                f"will not supply it.")
            assert name in linux_stern[0], (
                f"install_prerequisites_linux.sh's Stern list never installs "
                f"{name} — the Emulate tab needs it.")


def test_stern_declares_ext4_grow_prereq_per_platform():
    """Regression guard — the blip-free WSL2 dependency was undeclared.

    v0.94.0's blip-free cave grows game_real through core/ext4_grow (WSL2 on
    Windows, e2fsprogs on macOS), but the Stern plugin never declared that
    dependency, so the GUI said "All prerequisites OK" on machines whose every
    build silently fell back to the scrap-remains standard build -- a tester
    burned two hardware tests on a fallback card (Elvira spinner, 2026-07-30).
    The declaration is platform-built; check all three branches directly."""
    from pinball_decryptor.plugins.stern.manufacturer import _ext4_grow_prereqs

    (win,) = _ext4_grow_prereqs("win32")
    assert win.name == "WSL2" and win.where == "wsl"
    # Must mirror the probe ext4_grow.available() actually runs on the write
    # path so the indicator can never disagree with it.  That probe is
    # LOOP_PROBE (losetup), NOT bare reachability: a WSL 1 distro answers
    # `echo ok` as root while owning zero loop devices, so the strip said
    # "All prerequisites OK" on a machine where every grow failed after the
    # card's .sidx was already rewritten (PAD-13, a 489-video write that
    # shipped nothing).
    from pinball_decryptor.core.ext4_grow import LOOP_PROBE
    assert win.probe == LOOP_PROBE
    assert "losetup" in win.probe
    # The reason names both riders.  Video leads since v0.104.0 (blip-free went
    # opt-in), but blip-free must stay named: a build that opts back in still
    # falls back to the scrap-remains card without this, silently.
    assert "video" in win.reason and "blip-free" in win.reason.lower()
    assert "wsl --install" in win.install_hint
    # And the hint must carry the WSL 1 -> 2 conversion, the actual fix on
    # the machines this probe newly catches.
    assert "wsl --set-version" in win.install_hint

    (mac,) = _ext4_grow_prereqs("darwin")
    assert mac.name == "e2fsprogs" and mac.where == "host"
    # The probe must search every keg-only location _find_e2fsprogs does --
    # e2fsprogs is keg-only in Homebrew, so a bare PATH check reports it
    # missing on a machine where ext4_grow works fine.
    from pinball_decryptor.core import ext4_grow  # noqa: F401  (location source)
    for d in ("/opt/homebrew/opt/e2fsprogs/sbin",
              "/usr/local/opt/e2fsprogs/sbin", "/opt/local/sbin"):
        assert d in mac.probe, f"macOS probe must search {d}"
    assert "brew install e2fsprogs" in mac.install_hint

    # Native Linux mounts ext4 itself -- declaring a prereq there would show
    # a permanently-unfixable indicator.
    assert _ext4_grow_prereqs("linux") == ()

    # And the live registry actually carries the current platform's entry in
    # the Spike 2 (default-era) strip.
    import sys as _sys
    from pinball_decryptor.core.registry import get_manufacturer, load_plugins
    load_plugins()
    names = [p.name for p in get_manufacturer("stern").prerequisites]
    if _sys.platform == "win32":
        assert "WSL2" in names
    elif _sys.platform == "darwin":
        assert "e2fsprogs" in names


def test_windows_installer_requires_wsl_for_stern():
    """The installer's Stern entry must pull in the WSL2 + Ubuntu framework.

    Companion to the plugin-side declaration above: WslPackages = @() meant a
    Stern user who dutifully ran Install Prerequisites still had no WSL2, and
    the framework step only runs when a selected manufacturer lists at least
    one WSL package."""
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    stern = ps1.split('"Stern Pinball" = @{', 1)[1].split("PipPackages", 1)[0]
    assert "losetup" in stern, (
        "The Stern entry lists no WSL package, so the installer never offers "
        "the WSL2 + Ubuntu framework to Stern users -- blip-free callouts "
        "then silently fall back on every Windows machine without WSL2.")


def test_reboot_banner_names_the_start_menu_shortcut():
    """Regression guard — PAD-16 (user looped on the WSL2 reboot step).

    The post-install banner used to say "Re-run this script from the
    Start Menu" without naming the shortcut; the user couldn't find it,
    re-ran the setup .exe instead, and got the identical banner again.
    The banner must name the exact Start Menu entry — and that entry
    must actually exist in the .iss [Icons] section, so a shortcut
    rename can't silently strand the banner text.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    iss = ISS.read_text(encoding="utf-8", errors="replace")
    shortcut = "Install Prerequisites"
    icon_lines = [ln for ln in iss.splitlines()
                  if ln.startswith("Name:") and shortcut in ln]
    assert icon_lines, (
        "pinball_decryptor.iss no longer creates the 'Install "
        "Prerequisites' Start Menu shortcut — the .ps1 reboot banner "
        "points users at it by name.")
    assert shortcut in ps1, (
        "install_prerequisites.ps1's restart banner must name the "
        "'Install Prerequisites' Start Menu shortcut — 'Re-run this "
        "script from the Start Menu' is what left the PAD-16 user "
        "unable to find it.")
    assert "Re-run this script" not in ps1, (
        "the vague 'Re-run this script' wording is back — name the "
        "Start Menu shortcut instead (PAD-16).")


def test_wsl_install_detects_missed_restart():
    """Regression guard — PAD-16 (re-run before the restart).

    `wsl --install` only takes effect after a real Windows restart.  A
    re-run before that restart used to re-run `wsl --install` and print
    the same "reboot required" banner, giving the user no clue that the
    restart itself was the missing step — an endless-looking loop.  The
    installer must remember which boot session ran `wsl --install`
    (LastBootUpTime marker: it only changes on a real restart, not a
    Fast Startup shut down) and tell a same-session re-run plainly that
    Windows has not been restarted yet.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "LastBootUpTime" in ps1, (
        "install_prerequisites.ps1 must key its restart-pending marker "
        "on LastBootUpTime — it only changes on a real restart, which "
        "is the event WSL2 setup waits for (Fast Startup 'Shut down' "
        "resumes the same session).")
    assert "wsl_restart_pending" in ps1, (
        "install_prerequisites.ps1 must persist a restart-pending "
        "marker so a pre-restart re-run can say 'you haven't restarted "
        "yet' instead of silently re-running wsl --install (PAD-16).")
    assert "been restarted" in ps1, (
        "the same-session re-run path must tell the user Windows has "
        "not been restarted yet — that message is the whole point of "
        "the marker (PAD-16).")


def test_wsl_install_flags_are_capability_detected():
    """Regression guard — PAD-19 ("wsl --install exit -1", nothing installed).

    Older inbox wsl.exe builds (pre-Store WSL) reject options they don't
    know by printing usage and exiting -1 WITHOUT installing anything.
    Releases through v0.104.1 hardcoded `wsl --install -d Ubuntu --no-launch`, so on those
    machines the Ubuntu step was a silent no-op: WSL2 reported OK, Ubuntu
    reported Missing, and the user was stranded (the PAD-19 reporter hit
    exactly this after the PAD-16/17 restart saga finally got WSL2 up).
    The installer must derive its optional wsl --install flags from what
    the machine's own wsl.exe advertises (`wsl --help`), never hardcode
    them, and must keep the --web-download fallback for machines whose
    Microsoft Store is broken or blocked.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "wsl --help" in ps1, (
        "install_prerequisites.ps1 must probe `wsl --help` to learn which "
        "--install flags this machine's wsl.exe supports — hardcoding "
        "--no-launch makes old inbox builds exit -1 without installing "
        "anything (PAD-19).")
    assert "Ubuntu --no-launch" not in ps1, (
        "install_prerequisites.ps1 hardcodes `--no-launch` onto the wsl "
        "--install command line again — older wsl.exe builds reject the "
        "unknown flag and install nothing (PAD-19). Gate it on the "
        "capability probe instead.")
    assert "--web-download" in ps1, (
        "install_prerequisites.ps1 lost the --web-download retry — that "
        "fallback is what rescues machines whose Microsoft Store is "
        "broken/blocked, the other common cause of a failed Ubuntu "
        "install.")


def test_ubuntu_install_failure_names_a_manual_route():
    """Regression guard — PAD-19 (dead-end failure hint).

    When the automatic Ubuntu install fails, the old FAIL line said
    'try: wsl --list --verbose' — a diagnostic that only re-confirms the
    distro is missing (the PAD-19 reporter dutifully ran it and was no
    further ahead). A failed install must instead name a manual route
    the user can actually follow: `wsl --install -d Ubuntu` in an admin
    PowerShell, or installing Ubuntu from the Microsoft Store app.
    """
    ps1 = PS1.read_text(encoding="utf-8", errors="replace")
    assert "try: wsl --list --verbose" not in ps1, (
        "the dead-end 'try: wsl --list --verbose' failure hint is back — "
        "it only re-confirms the distro is missing. Name the manual "
        "install routes instead (PAD-19).")
    assert "wsl --install -d Ubuntu" in ps1, (
        "the Ubuntu failure path must spell out the manual command "
        "(`wsl --install -d Ubuntu`) so a stranded user can finish the "
        "install without this script.")
    assert "Microsoft Store" in ps1, (
        "the Ubuntu failure path must offer the Microsoft Store app as "
        "the no-command-line fallback route.")


def test_iss_repairs_python_permissions():
    """Regression guard — faster-whisper [Errno 13], install-over fix.

    install_prerequisites.ps1 repairs the perms of the packages it
    pip-installs — but that script only runs when the user explicitly
    launches it. A user who simply installs a newer version over a
    broken one would never trigger it. So the Inno installer itself —
    which runs elevated on every (re)install — must repair the
    bundled-Python tree, making a plain install-over-the-top enough to
    fix an already-broken machine.

    The repair must use `icacls /reset` (not just /grant — see
    test_pip_step_fixes_read_permissions), target {app}\\python, and
    NOT be gated behind the optional `runprereqs` Task.
    """
    iss = ISS.read_text(encoding="utf-8", errors="replace")
    icacls_lines = [ln for ln in iss.splitlines()
                    if "icacls" in ln.lower()
                    and not ln.lstrip().startswith(";")]
    assert icacls_lines, (
        "pinball_decryptor.iss must run icacls on {app}\\python in [Run] "
        "so a plain install-over repairs an already-broken machine "
        "without the user re-running the prerequisites installer.")
    joined = "\n".join(icacls_lines)
    assert "/reset" in joined, (
        "the .iss icacls repair must use /reset — a plain /grant cannot "
        "override a DENY ACE or broken inheritance.")
    assert "{app}\\python" in joined, (
        "the .iss icacls repair must target {app}\\python (the bundled "
        "interpreter + the pip-installed packages under it).")
    assert "S-1-5-32-545" in joined, (
        "the .iss icacls repair must also grant the Users group "
        "(SID S-1-5-32-545) read access.")
    assert not any("Tasks:" in ln for ln in icacls_lines), (
        "the .iss icacls repair must NOT be gated behind an optional "
        "Task — it has to run on every install, including install-over, "
        "which is the whole point of moving the fix into the installer.")


LAUNCHER_VBS = INSTALLER / "launcher.vbs"


def test_windows_launcher_always_elevates():
    """Regression guard — always-run-as-Administrator launch.

    Direct-SSD / SD-card operations need Administrator, and the app used
    to rely on the user remembering right-click → "Run as administrator"
    every single launch — forgetting it surfaced halfway through a run
    as WSL_E_ELEVATION_NEEDED_TO_MOUNT_DISK.  launcher.vbs (the target
    of every installed shortcut AND the installer's post-install launch)
    must start pythonw with the ShellExecute "runas" verb so every
    launch elevates behind a standard one-click UAC prompt.
    """
    src = LAUNCHER_VBS.read_text(encoding="utf-8", errors="replace")
    assert "ShellExecute" in src and '"runas"' in src, (
        "launcher.vbs no longer launches the app with the ShellExecute "
        "'runas' verb — installed users are back to remembering "
        "right-click → Run as administrator, and Direct-SSD runs fail "
        "halfway through with WSL_E_ELEVATION_NEEDED_TO_MOUNT_DISK.")
    assert "On Error Resume Next" in src, (
        "launcher.vbs must swallow the ShellExecute error raised when "
        "the user declines the UAC prompt — otherwise declining shows a "
        "cryptic Windows Script Host error dialog.")


def test_iss_shortcuts_route_through_launcher():
    """Every app shortcut the installer creates must point at
    launcher.vbs — a shortcut aimed straight at pythonw.exe would
    silently bypass the launcher's self-elevation, resurrecting the
    right-click → Run as administrator dance for that entry point."""
    iss = ISS.read_text(encoding="utf-8", errors="replace")
    app_icon_lines = [ln for ln in iss.splitlines()
                      if ln.startswith("Name:") and "icon.ico" in ln]
    assert app_icon_lines, (
        "no app shortcuts found in the .iss [Icons] section — has the "
        "shortcut layout changed?")
    for ln in app_icon_lines:
        assert "launcher.vbs" in ln, (
            f"installer shortcut bypasses launcher.vbs (and with it the "
            f"always-run-as-Administrator elevation): {ln}")


DOCKERFILES = sorted((REPO / "pinball_decryptor" / "plugins").glob("*/Dockerfile"))


@pytest.mark.parametrize("dockerfile", DOCKERFILES,
                         ids=lambda p: p.parent.name)
def test_dockerfile_copy_sources_exist(dockerfile):
    """Regression guard — JJP macOS dead-on-arrival (TonyScoots report).

    The macOS DockerExecutor builds these images with the Dockerfile's
    own directory as the build context.  A COPY of a path that isn't in
    that directory makes `docker build` fail, which surfaces as
    "Missing prerequisites: partclone, xorriso" (the tools live inside
    the image, so a failed build reads as missing tools).

    The JJP Dockerfile shipped with `COPY jjp_decryptor/ ...` — a
    directory that only existed in the old standalone repo, never in the
    unified app's build context — so the image NEVER built on macOS and
    JJP extract was impossible there.  Verify every COPY source exists.
    """
    ctx = dockerfile.parent
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("COPY "):
            continue
        # COPY <src>... <dest> — last token is the destination.
        parts = stripped.split()[1:]
        srcs = parts[:-1]
        for src in srcs:
            src = src.rstrip("/")
            assert (ctx / src).exists(), (
                f"{dockerfile.parent.name}/Dockerfile COPYs '{src}', which "
                f"does not exist in the build context ({ctx}). `docker build` "
                f"will fail and the macOS app will report the in-image tools "
                f"as missing prerequisites.")


@pytest.mark.parametrize("dockerfile", DOCKERFILES,
                         ids=lambda p: p.parent.name)
def test_dockerfile_has_no_hijacking_entrypoint(dockerfile):
    """The DockerExecutor runs each image with an explicit command
    (`sleep infinity`) and `docker exec`s tool commands into it.  An
    ENTRYPOINT prepends to that command, so `ENTRYPOINT ["python3",
    "-m", "jjp_decryptor.cli"]` would turn the run command into
    `python3 -m jjp_decryptor.cli sleep infinity` — the container exits
    immediately and every later `docker exec` fails.  The image must be
    a plain toolbox (no ENTRYPOINT, or a shell CMD)."""
    has_entrypoint = any(
        line.strip().upper().startswith("ENTRYPOINT")
        for line in dockerfile.read_text(encoding="utf-8").splitlines())
    assert not has_entrypoint, (
        f"{dockerfile.parent.name}/Dockerfile declares an ENTRYPOINT — the "
        f"macOS executor runs the image with `sleep infinity` and execs into "
        f"it, so an ENTRYPOINT hijacks that command and the container dies "
        f"on start. Use `CMD [\"bash\"]` instead.")


def test_gdre_prereq_probe_matches_install_location():
    """Regression guard — GDRE prereq false-negative (tester report).

    The BOF gdre_tools prerequisite probe must check the canonical path
    install_gdre.sh writes to (/opt/gdre_tools), NOT `which gdre_tools`
    — a PATH lookup that traverses WSL's appended Windows PATH and
    failed intermittently even with GDRE correctly installed.
    """
    gdre_sh = (INSTALLER / "install_gdre.sh").read_text(
        encoding="utf-8", errors="replace")
    assert "/opt/gdre_tools" in gdre_sh, (
        "install_gdre.sh no longer installs to /opt/gdre_tools — the "
        "BOF gdre_tools probe must be updated to match.")

    from pinball_decryptor.core.registry import (load_plugins,
                                                 get_manufacturer)
    load_plugins()
    bof = get_manufacturer("bof")
    probe = next(p.probe for p in bof.prerequisites
                 if p.name == "gdre_tools")
    assert "/opt/gdre_tools" in probe, (
        "BOF gdre_tools probe must check /opt/gdre_tools — the path "
        "install_gdre.sh installs to.")
    assert "which " not in probe, (
        "BOF gdre_tools probe uses `which` again — a PATH lookup inside "
        "WSL is slow/flaky; test the install path directly.")
