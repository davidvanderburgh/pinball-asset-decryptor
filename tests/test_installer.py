"""Static + structural checks for the prerequisite installers.

Two installer bugs reached users because the installer scripts had no
test coverage:

  * GDRE Tools install — a bash script embedded in a PowerShell
    here-string picked up a UTF-8 BOM and CRLF line endings, which
    broke it inside WSL ("set: command not found", unterminated
    heredoc).
  * faster-whisper — the pip step searched only PATH for a Python, so
    on a packaged install (which ships its own Python and puts nothing
    on PATH) it silently skipped the install.

These tests guard both classes: installer shell scripts must stay
LF-only and parse clean, the PowerShell installer must stay
syntactically valid, and the two specific fixes must not regress.

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


def test_installer_layout():
    """The shared GDRE script and the PowerShell installer must exist."""
    assert PS1.is_file(), "install_prerequisites.ps1 missing"
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


@pytest.mark.skipif(shutil.which("bash") is None,
                    reason="bash not available")
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
