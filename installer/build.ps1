<#
.SYNOPSIS
    Build the Windows installer for Pinball Asset Decryptor.

.DESCRIPTION
    Downloads a Python embeddable distribution that matches the local
    Python version, copies tkinter from the local install (the
    embeddable doesn't ship with it), pip-installs the runtime
    dependencies into the bundle, then compiles the Inno Setup
    installer (.exe).

.NOTES
    Prerequisites:
    - Python 3.10+ with tkinter installed locally (the source for the
      bundled tkinter files)
    - Inno Setup 6 (https://jrsoftware.org/isinfo.php)
    - Internet access (downloads the Python embeddable + pip + deps)
#>

param(
    [string]$InnoSetupPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$BuildDir = Join-Path $ScriptDir "build"

# --- Detect local Python and tkinter source paths -------------------------
Write-Host "Detecting local Python installation..." -ForegroundColor Cyan
try {
    $pyInfo = python -c "import sys, os, _tkinter, tkinter; base = os.path.dirname(os.path.dirname(_tkinter.__file__)); print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); print(base); print(_tkinter.__file__); print(os.path.dirname(tkinter.__file__))" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Python not found" }
    $pyLines = $pyInfo -split "`n" | ForEach-Object { $_.Trim() }
    $PythonVersion = $pyLines[0]
    $pyBase = $pyLines[1]
    $tkinterPydPath = $pyLines[2]
    $tkinterPkgDir = $pyLines[3]
} catch {
    Write-Error "Python with tkinter is required to build the installer. Install Python 3.10+ from python.org."
    exit 1
}

$pyMajorMinor = ($PythonVersion -split '\.')[0..1] -join ''  # e.g. "312"
Write-Host "  Python version: $PythonVersion (python$pyMajorMinor)" -ForegroundColor Green

# --- Locate Inno Setup compiler -------------------------------------------
if (-not $InnoSetupPath) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $InnoSetupPath = $c; break }
    }
}
if (-not $InnoSetupPath -or -not (Test-Path $InnoSetupPath)) {
    Write-Error "Inno Setup compiler (ISCC.exe) not found. Install Inno Setup 6 or pass -InnoSetupPath."
    exit 1
}
Write-Host "Using Inno Setup: $InnoSetupPath" -ForegroundColor Cyan

# --- Read version from pinball_decryptor/__init__.py ----------------------
$initFile = Join-Path $ProjectDir "pinball_decryptor\__init__.py"
$versionLine = Get-Content $initFile | Where-Object { $_ -match '__version__\s*=\s*"([^"]+)"' }
if ($versionLine -match '"([^"]+)"') {
    $AppVersion = $Matches[1]
} else {
    Write-Error "Could not read __version__ from $initFile"
    exit 1
}
Write-Host "Building version: $AppVersion" -ForegroundColor Cyan

# --- Clean and create build directory -------------------------------------
if (Test-Path $BuildDir) {
    Write-Host "Cleaning previous build..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $BuildDir
}
New-Item -ItemType Directory -Path $BuildDir | Out-Null
$PythonDir = Join-Path $BuildDir "python"
New-Item -ItemType Directory -Path $PythonDir | Out-Null

# --- Download Python embeddable zip ---------------------------------------
$embedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$embedZip = Join-Path $BuildDir "python-embed.zip"

Write-Host "`nDownloading Python $PythonVersion embeddable zip..." -ForegroundColor Cyan
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $embedUrl -OutFile $embedZip -UseBasicParsing

Write-Host "Extracting embeddable zip..." -ForegroundColor Cyan
Expand-Archive -Path $embedZip -DestinationPath $PythonDir -Force

# --- Copy tkinter files from local Python installation --------------------
Write-Host "`nCopying tkinter files from local Python..." -ForegroundColor Cyan

$tkinterDllDir = Split-Path -Parent $tkinterPydPath
foreach ($file in @("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll")) {
    $src = Join-Path $tkinterDllDir $file
    $dst = Join-Path $PythonDir $file
    if ((Test-Path $src) -and -not (Test-Path $dst)) {
        Copy-Item $src -Destination $dst -Force
        Write-Host "  Copied $file"
    }
}

$libDir = Join-Path $PythonDir "Lib"
if (-not (Test-Path $libDir)) { New-Item -ItemType Directory -Path $libDir | Out-Null }
Copy-Item $tkinterPkgDir -Destination (Join-Path $libDir "tkinter") -Recurse -Force
Write-Host "  Copied Lib/tkinter/"

$tclSrcDir = Join-Path $pyBase "tcl"
if (Test-Path $tclSrcDir) {
    Copy-Item $tclSrcDir -Destination (Join-Path $PythonDir "tcl") -Recurse -Force
    Write-Host "  Copied tcl/"
} else {
    Write-Warning "tcl/ directory not found at $tclSrcDir"
}

# --- Enable import site, install pip + deps ------------------------------
Write-Host "`nInstalling pip and dependencies into bundled Python..." -ForegroundColor Cyan
$pthFile = Join-Path $PythonDir "python${pyMajorMinor}._pth"
if (-not (Test-Path $pthFile)) {
    Write-Error "Could not find $pthFile"
    exit 1
}

# Uncomment 'import site' so pip works
$pthRaw = Get-Content $pthFile -Raw
$pthRaw = $pthRaw -replace '#\s*import site', 'import site'
Set-Content -Path $pthFile -Value $pthRaw -Encoding ASCII -NoNewline

$getPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$getPipFile = Join-Path $BuildDir "get-pip.py"
Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipFile -UseBasicParsing

$pythonExe = Join-Path $PythonDir "python.exe"
& $pythonExe $getPipFile --no-warn-script-location 2>&1 | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to install pip"; exit 1 }

$sitePackages = Join-Path $PythonDir "Lib\site-packages"
& $pythonExe -m pip install --no-warn-script-location --target $sitePackages setuptools wheel 2>&1 | ForEach-Object { Write-Host "    $_" }

# Runtime deps bundled into the app's isolated embeddable Python.  This MUST
# install the FULL runtime set from requirements.txt (Pillow / zstandard /
# pycryptodome / numpy / unicorn / capstone) -- the app uses ONLY this bundled
# interpreter (its ._pth sandboxes it from any system Python), so anything
# missing here is missing for the user with no fix: a manual `pip install` into
# their own Python is invisible to the app.  That's exactly what bit a
# fresh-install user whose system pip reported "already satisfied" while the
# app still showed the Stern deps (unicorn/capstone/numpy) missing.  The extras
# below aren't in requirements.txt: UnityPy/fsb5/pyogg power Spooky's Unity
# asset extraction.  faster-whisper (Auto-name call-outs) stays an on-demand
# "Install Missing" item on Windows -- it works there (bundled Python + a
# functional elevated installer), so it's kept out of the base installer for
# size; Mac/Linux bundle it because their frozen apps can't install it later.
$reqFile = Join-Path $ProjectDir "requirements.txt"
$pipExtras = @("UnityPy", "fsb5", "pyogg")
Write-Host "  Installing deps from requirements.txt + extras ($($pipExtras -join ', '))..."
$ErrorActionPreference = "Continue"
& $pythonExe -m pip install --no-warn-script-location --target $sitePackages -r $reqFile @pipExtras 2>&1 | ForEach-Object { Write-Host "    $_" }
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to install pip dependencies"; exit 1 }
Write-Host "  Dependencies installed successfully" -ForegroundColor Green

# --- Patch python3XX._pth for final layout --------------------------------
# The bundled python.exe lives in <app>\python\, so '..' makes the
# pinball_decryptor package (one level up) importable.
$pthContent = @(
    "python${pyMajorMinor}.zip",
    ".",
    "./Lib",
    "./Lib/site-packages",
    "..",
    "import site"
)
$pthContent -join "`r`n" | Set-Content -Path $pthFile -Encoding ASCII -NoNewline

# --- Smoke tests ----------------------------------------------------------
Write-Host "`nSmoke testing the bundled Python..." -ForegroundColor Cyan
$env:TCL_LIBRARY = Join-Path $PythonDir "tcl\tcl8.6"
$env:TK_LIBRARY = Join-Path $PythonDir "tcl\tk8.6"

$testTk = & $pythonExe -c "import tkinter; print('tkinter OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  $testTk" -ForegroundColor Green
} else {
    Write-Warning "tkinter smoke test failed: $testTk"
}

$testDeps = & $pythonExe -c "import Crypto, UnityPy, PIL, numpy, unicorn, capstone; print('deps OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  $testDeps" -ForegroundColor Green
} else {
    Write-Warning "Dependency smoke test failed: $testDeps"
}

Remove-Item Env:\TCL_LIBRARY -ErrorAction SilentlyContinue
Remove-Item Env:\TK_LIBRARY -ErrorAction SilentlyContinue

# --- Compile Inno Setup installer -----------------------------------------
Write-Host "`nCompiling installer..." -ForegroundColor Cyan
$issFile = Join-Path $ScriptDir "pinball_decryptor.iss"
& $InnoSetupPath /Qp "/DAppVersion=$AppVersion" "/DPythonDir=$PythonDir" "/DProjectDir=$ProjectDir" $issFile

if ($LASTEXITCODE -eq 0) {
    $outputDir = Join-Path $ScriptDir "Output"
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "  Build successful!" -ForegroundColor Green
    Write-Host "  Output: $outputDir" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Error "Inno Setup compilation failed with exit code $LASTEXITCODE"
    exit 1
}
