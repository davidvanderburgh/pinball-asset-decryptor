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


def _stern_lazy_modules():
    mods = ["pinball_decryptor.plugins.stern.ext4",
            "pinball_decryptor.plugins.stern.spike2"]
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
    """Regression guard — GDRE prereq false-negative (Joe_Blasi report).

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
