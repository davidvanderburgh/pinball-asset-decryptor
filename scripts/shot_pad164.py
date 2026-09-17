"""PAD-164 proof shot: what the prerequisite run says when wsl.exe refuses
the distro name the installer asks for.

The reporter pasted a run whose WSL step read, in this order:

    Installing WSL2 + Ubuntu (this may take several minutes)...
    Invalid distribution name: 'Ubuntu-24.04'.
    To get a list of valid distributions, use 'wsl --list --online'.
    The parameter is incorrect.
    [INSTALLED] WSL2 + Ubuntu (restart required)

Nothing was installed - wsl.exe rejected the name before it enabled anything -
and the run still reported it green and asked for a restart.  After the restart
the same run does the same thing, which is why he had "tried to redownload the
missing files" more times than he could count.

The shot photographs the console the app opens, because that is the surface the
reporter reads and quotes.  The WSL section of installer/install_prerequisites.ps1
is run FOR REAL - the definitions and section 2 are lifted out of the script
itself, so whatever that file says is what appears - against a fake wsl.exe that
answers exactly like the reporter's:

  * legacy  - a wsl.exe whose --list --online catalogue predates 24.04 (the
              reporter's machine), so `--install -d Ubuntu-24.04` can only
              answer "Invalid distribution name".
  * storefail - a wsl.exe that offers the pinned release and then fails every
              install (a blocked / signed-out Microsoft Store), which is where
              the false green is the whole of what the user is told.
  * the third shot is the state the old release LEAVES BEHIND on the
              reporter's disk: its restart-pending marker naming this boot
              session, with no Windows feature ever enabled - the machine on
              which "just install the update" has to heal itself.

Only the package plan is stubbed (it is built by the interactive manufacturer
picker in section 1) and $env:ProgramData is redirected at a temp dir so the
run cannot write the real restart marker.  The admin gate is dropped; nothing
in the section needs admin once wsl.exe is a fake.

    python scripts/shot_pad164.py <out_dir> <before|after>

`before` re-runs the same rig against origin/main's copy of the script, so the
pair is the same machine and the same code path with only the fix between them.
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit("Windows-only (PrintWindow/GDI).")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(
    REPO, "docs", "screenshots")
WHEN = (sys.argv[2] if len(sys.argv) > 2 else "after").strip().lower()
PS1 = os.path.join(REPO, "installer", "install_prerequisites.ps1")

os.makedirs(OUT, exist_ok=True)

# DPI-AWARE, unlike take_screenshots.py.  A console window is sized by the
# host in physical pixels, and a DPI-unaware capture process is handed
# virtualized (scaled-down) coordinates by GetWindowRect - so PrintWindow drew
# the full-width window into a too-small bitmap and every long line came out
# clipped at the right edge instead of wrapped.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PIL import Image  # noqa: E402

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


# ----------------------------------------------------------------------
# The script under photograph.  `before` is origin/main's copy of the same
# file, so the two shots differ by the fix and nothing else.
# ----------------------------------------------------------------------
def script_text():
    if WHEN != "before":
        with open(PS1, encoding="utf-8") as fh:
            return fh.read()
    out = subprocess.run(
        ["git", "-C", REPO, "show", "origin/main:installer/install_prerequisites.ps1"],
        capture_output=True)
    if out.returncode != 0:
        sys.exit("git show failed: %s" % out.stderr.decode("utf-8", "replace"))
    return out.stdout.decode("utf-8", "replace")


#: The package plan section 2 reads.  Built by the manufacturer picker in
#: section 1, which is interactive; these are the two Stern rows that put a
#: WSL2 requirement on the plan (losetup is what makes it ask about WSL 1).
WSL_PLAN = """
$wslPlan = @(
    @{ label="e2fsprogs/debugfs"; pkg="e2fsprogs"; probe="debugfs" },
    @{ label="util-linux (losetup/mount, in WSL)"; pkg="util-linux"; probe="losetup" }
)
"""


def harness_parts(text):
    """(definitions, section 2) of the real script, as two separate pieces.

    Separate, because a shot that needs to set the machine up further - seed
    the restart marker, shadow a Windows cmdlet - has to do it AFTER the
    definitions are in scope and BEFORE the section runs.
    """
    # Everything down to the last reporting helper: functions and constants
    # only, so running it has no effect beyond defining them.
    defs_end = text.index("\n", text.index("function Write-SKIP($n)"))
    defs = text[:defs_end + 1]
    # ...minus the admin gate, which a fake wsl.exe does not need.
    gate = defs.index("$currentPrincipal = New-Object")
    defs = defs[:gate] + defs[defs.index('$ErrorActionPreference = "Continue"'):]
    section = text[text.index("$needsWsl = $wslPlan.Count -gt 0"):
                   text.index("# 2b. The repair for an apt")]
    return defs, section


#: What the old release left on disk: the marker naming THIS boot session, so
#: the run reads "a previous run installed WSL2 and you have not restarted",
#: while every Windows feature it would have enabled is still off.  A function
#: shadows the real cmdlet - PowerShell resolves functions before cmdlets - so
#: this box's own answer is never the one under photograph.
STALE_MARKER = """
New-Item -ItemType Directory -Force (Split-Path -Parent $script:RestartMarker) | Out-Null
Set-Content -LiteralPath $script:RestartMarker -Value (Get-BootSessionId)
function Get-WindowsOptionalFeature {
    # -Online is a SWITCH on the real cmdlet: declared as a value parameter
    # here it swallows the next argument, the call throws, and the probe's
    # catch answers "don't know" - which silently photographs the old
    # behaviour instead of the new one.
    param([switch]$Online, $FeatureName, $ErrorAction)
    [PSCustomObject]@{ FeatureName = $FeatureName; State = "Disabled" }
}
"""


# ----------------------------------------------------------------------
# The fake machine.
# ----------------------------------------------------------------------
#: The catalogue an inbox wsl.exe from before 24.04 answers with.  Real shape,
#: real names: two preamble lines, a header whose column titles are localized,
#: then NAME / FRIENDLY NAME rows.
LEGACY_ONLINE = """The following is a list of valid distributions that can be installed.
Install using 'wsl.exe --install -d <Distro>'.

NAME            FRIENDLY NAME
Ubuntu          Ubuntu
Debian          Debian GNU/Linux
kali-linux      Kali Linux Rolling
Ubuntu-18.04    Ubuntu 18.04 LTS
Ubuntu-20.04    Ubuntu 20.04 LTS
Ubuntu-22.04    Ubuntu 22.04 LTS
OracleLinux_7_9 Oracle Linux 7.9
OracleLinux_8_7 Oracle Linux 8.7
SUSE-Linux-Enterprise-Server-15-SP4 SUSE Linux Enterprise Server 15 SP4
openSUSE-Leap-15.4 openSUSE Leap 15.4
openSUSE-Tumbleweed openSUSE Tumbleweed
"""

MODERN_ONLINE = LEGACY_ONLINE.replace(
    "Ubuntu-22.04    Ubuntu 22.04 LTS\n",
    "Ubuntu-22.04    Ubuntu 22.04 LTS\nUbuntu-24.04    Ubuntu 24.04 LTS\n")

#: No --no-launch, no --web-download: the flags a pre-Store wsl.exe has never
#: heard of.  The capability probe (PAD-19) is what reads this.
LEGACY_HELP = """Copyright (c) Microsoft Corporation. All rights reserved.

Usage: wsl.exe [Argument] [Options...] [CommandLine]

Arguments for running Linux binaries:
    --exec, -e <CommandLine>
    --

Arguments for managing Windows Subsystem for Linux:
    --install [Distro]
        Install a Windows Subsystem for Linux distribution.
    --list, -l [Options]
    --set-default, -s <Distro>
    --set-version <Distro> <Version>
    --status
    --shutdown
    --update
"""

FAKE_WSL = r'''
"""A wsl.exe that answers like the PAD-164 reporter's."""
import os
import sys

MODE = os.environ.get("PAD164_MODE", "legacy")
ONLINE = os.environ["PAD164_ONLINE"]
HELP = os.environ["PAD164_HELP"]

a = sys.argv[1:]


def out(s, code=0):
    sys.stdout.write(s if s.endswith("\n") else s + "\n")
    sys.exit(code)


if "--help" in a:
    out(HELP)
if "--status" in a or "--version" in a:
    # No WSL on this machine at all - which is the reporter's state, and the
    # branch that never looked at an exit code.
    out("Windows Subsystem for Linux has no installed distributions.\n"
        "Use 'wsl.exe --list --online' to list available distributions\n"
        "and 'wsl.exe --install <Distro>' to install.", 1)
if "--update" in a:
    # An inbox wsl.exe on a machine the Store WSL cannot reach: the update
    # reports success and the catalogue it offers does not change.
    out("Checking for updates.\n"
        "The most recent version of Windows Subsystem for Linux is already "
        "installed.")
if ("--list" in a or "-l" in a) and ("--online" in a or "-o" in a):
    out(ONLINE)
if "--list" in a or "-l" in a:
    out("Windows Subsystem for Linux has no installed distributions.", 1)
if "--install" in a:
    want = None
    for flag in ("-d", "--distribution"):
        if flag in a:
            i = a.index(flag)
            if i + 1 < len(a):
                want = a[i + 1]
    names = [ln.split()[0] for ln in ONLINE.splitlines()
             if ln[:1].strip() and len(ln.split()) > 1]
    if want is not None and want not in names:
        out("Invalid distribution name: '%s'.\n"
            "To get a list of valid distributions, use 'wsl --list --online'.\n"
            "The parameter is incorrect." % want, 87)
    if MODE == "storefail":
        out("Installing: %s\n"
            "The operation could not be started because a required feature "
            "is not installed.\n"
            "Error code: Wsl/InstallDistro/WSL_E_INSTALL_PROCESS_FAILED"
            % (want or "Ubuntu"), 1)
    out("Installing: Windows Subsystem for Linux\n"
        "Windows Subsystem for Linux has been installed.\n"
        "Installing: %s\n"
        "%s has been installed.\n"
        "The requested operation is successful. Changes will not be effective "
        "until the system is rebooted." % ((want or "Ubuntu"), (want or "Ubuntu")))
out("", 1)
'''


def make_machine(root, mode):
    """A directory to put first on PATH, holding the fake wsl.exe."""
    fake = os.path.join(root, "bin")
    os.makedirs(fake, exist_ok=True)
    py = os.path.join(fake, "fakewsl.py")
    with open(py, "w", encoding="utf-8") as fh:
        fh.write(FAKE_WSL)
    with open(os.path.join(fake, "wsl.cmd"), "w", encoding="ascii",
              newline="\r\n") as fh:
        fh.write('@echo off\r\n"%s" "%%~dp0fakewsl.py" %%*\r\n' % sys.executable)
    return fake


# ----------------------------------------------------------------------
# Capture
# ----------------------------------------------------------------------
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)]


def find_window(title, timeout=30):
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = []

    def _cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if title in buf.value:
            found.append(hwnd)
            return False
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        user32.EnumWindows(proc(_cb), 0)
        if found:
            return found[0]
        time.sleep(0.2)
    return None


def grab(hwnd, path):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)          # PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    img.save(path)
    print("snapped %s (%dx%d)" % (os.path.basename(path), img.width,
                                  img.height), flush=True)


HARNESS = """$Host.UI.RawUI.WindowTitle = "%(title)s"
# Buffer width == window width, so every line WRAPS on screen instead of
# running off to the right of a narrower window and out of the photograph.
# The window is narrowed FIRST: a buffer smaller than the current window is
# rejected, and the failure is silent, which is what clipped the first pair.
$w = [Math]::Min(100, $Host.UI.RawUI.MaxWindowSize.Width)
try {
    $Host.UI.RawUI.WindowSize = New-Object Management.Automation.Host.Size($w, %(rows)d)
} catch { Write-Host ("window resize failed: " + $_) }
try {
    $Host.UI.RawUI.BufferSize = New-Object Management.Automation.Host.Size($w, 500)
} catch { Write-Host ("buffer resize failed: " + $_) }
$env:PATH = "%(fake)s;" + $env:PATH
$env:ProgramData = "%(data)s"
Write-Host "Pinball Asset Decryptor - Prerequisite Installer" -ForegroundColor White
Write-Host "%(caption)s" -ForegroundColor DarkGray
$script:results = @()
. "%(defs)s"
%(prelude)s
%(plan)s
. "%(section)s"
Write-Host ""
Write-Host "Summary:" -ForegroundColor White
$script:results | ForEach-Object { Write-Host ("  {0,-10} {1}" -f $_.Status, $_.Name) }
Start-Sleep -Seconds 600
"""


def shoot(mode, online, rows, caption, name, prelude=""):
    root = tempfile.mkdtemp(prefix="pad164_%s_" % name)
    fake = make_machine(root, mode)
    data = os.path.join(root, "ProgramData")
    os.makedirs(data, exist_ok=True)

    defs, section = harness_parts(script_text())
    defs_file = os.path.join(root, "defs.ps1")
    section_file = os.path.join(root, "wslsection.ps1")
    with open(defs_file, "w", encoding="utf-8") as fh:
        fh.write(defs)
    with open(section_file, "w", encoding="utf-8") as fh:
        fh.write(section)

    title = "PAD164-%s-%s" % (WHEN, name)
    harness = os.path.join(root, "harness.ps1")
    with open(harness, "w", encoding="utf-8") as fh:
        fh.write(HARNESS % {
            "title": title, "rows": rows, "caption": caption,
            "fake": fake.replace('"', ''), "data": data,
            "defs": defs_file, "section": section_file,
            "prelude": prelude, "plan": WSL_PLAN,
        })

    env = dict(os.environ)
    env["PAD164_MODE"] = mode
    env["PAD164_ONLINE"] = online
    env["PAD164_HELP"] = LEGACY_HELP
    # conhost, not the default terminal: a classic console host is one window
    # this process can find and PrintWindow.
    proc = subprocess.Popen(
        ["conhost.exe", "powershell.exe", "-NoProfile", "-ExecutionPolicy",
         "Bypass", "-File", harness], env=env)
    try:
        hwnd = find_window(title)
        if hwnd is None:
            raise SystemExit("the console window never appeared (%s)" % title)
        # The section runs a handful of fake wsl calls; wait for the summary
        # line to be on screen before the shutter.
        time.sleep(6)
        grab(hwnd, os.path.join(OUT, "%s_%s.png" % (WHEN, name)))
    finally:
        proc.kill()


shoot("legacy", LEGACY_ONLINE, 24,
      "Simulated machine: a wsl.exe too old to list Ubuntu-24.04 "
      "(the PAD-164 reporter's).", "prereq_wsl_old_wsl")
shoot("storefail", MODERN_ONLINE, 34,
      "Simulated machine: every wsl --install fails (a blocked Microsoft Store).",
      "prereq_wsl_install_fails")
shoot("legacy", LEGACY_ONLINE, 30,
      "Simulated machine: the old release's restart marker, and no Windows "
      "feature ever enabled.", "prereq_wsl_stale_marker", prelude=STALE_MARKER)
print("done", flush=True)
