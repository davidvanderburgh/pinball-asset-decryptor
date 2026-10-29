# Installing

[← Back to the README](../../README.md)

## Windows

1. Download the latest `Pinball_Asset_Decryptor_v*_Windows.exe` from the
   [Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases)
   and run it. It bundles its own Python, so nothing else is needed to
   launch the app.
2. Run **Install Prerequisites** from the Start Menu. It asks which
   manufacturers you use and installs only what they need (see
   [Per-manufacturer prerequisites](#per-manufacturer-prerequisites)).
3. If it ends with **restart required**, WSL2 was just installed. Restart
   Windows (use *Restart*: with Fast Startup on, *Shut down* doesn't
   count), then run **Install Prerequisites** once more.

Re-running the installer is always safe: it skips anything already there.

- **Administrator:** the app's shortcuts start it as Administrator (one UAC
  prompt), because writing SD cards and SSDs needs it.
- **Network drives:** mapped letters (`W:\…`) keep working in the elevated
  app, and in WSL too: the app translates and mounts them itself.

### If Install Prerequisites reports a problem

| What it says | What to do |
|---|---|
| **Ubuntu … Missing** (WSL2 OK) | `wsl.exe` couldn't register Ubuntu, often a blocked Microsoft Store. Run `wsl --install -d Ubuntu` in an admin PowerShell, or install Ubuntu from the Store and open it once. Then run Install Prerequisites again. |
| A **WSL package** MISSING (often `qemu-user-static`) | The installer names it and offers its repair: refresh the package index, switch on `universe`, or fetch the one package from another release. It asks first. |
| **Virtualization is disabled in BIOS/UEFI** | Turn on Intel **VT-x** or AMD **SVM** in firmware setup, boot Windows, and run Install Prerequisites again. |
| **Default distro is WSL 1** | WSL 1 can't mount card images. The installer offers to convert it, or run `wsl --set-version <name> 2` yourself, then **Re-check** in the app. |
| **The distro is not starting** | Try `wsl --shutdown`, wait ten seconds, then `wsl --update`. Still dead? Install a second distro beside it (below). |
| `Invalid distribution name: 'Ubuntu-24.04'` | Your `wsl.exe` is older than that release. Run `wsl --update`, or `wsl --list --online` and pick an Ubuntu from that list. |

Installing a second distro and making it the one the app uses:

```powershell
wsl --install -d Ubuntu-24.04
wsl --set-default Ubuntu-24.04
```

The old distro stays where it is, and `wsl --export <name> backup.tar`
still gets its files out.

### Which Ubuntu

Any current release works (22.04, 24.04 and later), and none is refused
on its version number. The prerequisite checks decide, by asking what the
machine can actually do.

- **24.04** is the one it is tested on, and what a fresh install gets.
- **The log names the distro** each check ran in, e.g. `WSL: Ubuntu
  (Ubuntu 24.04.4 LTS, WSL 2)`. A release older than 22.04 gets a warning
  line.
- **An app update never installs or switches a distro.** After you upgrade
  Ubuntu in place, the emulator's small programs and criu are rebuilt by
  themselves.
- **A WSL that logs in as root** builds multi-boot cards fine, but the
  emulator's game window opens black. See [Emulate](emulate.md#when-something-goes-wrong).

### Other Windows notes

- **`make: command not found`** on a multi-boot build: `make` builds the
  boot menu. Install Prerequisites installs it, or `apt install make` in
  WSL.
- **"Audio preview needs ffplay"** on Replace Audio: your ffmpeg has no
  `ffplay.exe`. Answer **Yes** and the app installs the full ffmpeg build.
  Only previewing needs it.
- **⚙ > Install / repair prerequisites…** stays clickable even when every
  check is green, for exactly this kind of case.

## macOS

1. Download the DMG for your Mac from the
   [Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases):
   - `…_macOS_AppleSilicon.dmg` for Apple Silicon (M1 or newer).
   - `…_macOS_Intel.dmg` for Intel Macs (macOS 13 Ventura or newer).

   Not sure? **Apple menu → About This Mac**: a *Chip* line saying "Apple
   M…" is Apple Silicon. The wrong one says *"…is not supported on this
   type of Mac"*.
2. Open the DMG and drag **Pinball Asset Decryptor** to `/Applications`.
3. **Allow it once.** The app is ad-hoc signed (no Apple Developer ID), so
   the first open is refused with *"Apple could not verify…"*. Then:
   - Open **System Settings → Privacy & Security**.
   - Under **Security**, click **Open Anyway** beside *"Pinball Asset
     Decryptor was blocked…"*, and confirm.
   - Click **Open** in the last dialog.

You only do this once. Later versions arrive through the app's own
**Install update**, with no security prompt (see [Auto-update](#auto-update)).

**Still bouncing in the Dock and never opening?** Clear the quarantine flag
in Terminal, then open the app again:

```bash
xattr -dr com.apple.quarantine "/Applications/Pinball Asset Decryptor.app"
```

**Docker** is needed on a Mac for two things:

- **Spooky and JJP** Clonezilla extraction, which runs partclone and
  debugfs in a container.
- **The Stern Emulate tab**, because the game is a Linux program. Its **Set
  up emulator…** button installs a container engine with Homebrew or
  MacPorts for you.

Docker Desktop, OrbStack, Rancher Desktop or Colima all work. Every other
manufacturer runs without Docker, and Windows and Linux never need it.

## Linux

1. Download the latest `Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage`
   from the [Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases),
   mark it executable and run it:

   ```bash
   chmod +x Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage
   ./Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage
   ```
2. Press **Install Missing** in the prerequisites row (or run
   [installer/install_prerequisites_linux.sh](../../installer/install_prerequisites_linux.sh)).
   It asks which manufacturers you use; **a** picks them all.

- **Package managers:** apt (Debian, Ubuntu) and pacman (Arch, Omarchy,
  CachyOS, EndeavourOS, Manjaro). On Arch it runs `pacman -Syu --needed`,
  a full update first.
- **A package apt refuses** doesn't stop the rest: they go on one at a
  time, and the refused one is named with an offer to try the app's repair.
- **Another distro?** Install the packages by hand from the table below;
  the script prints both spellings when it finds neither manager.
- **Run the app as yourself**, not with `sudo`.

### Arch package names

Everything not listed is spelled the same as on apt.

| apt | Arch |
|---|---|
| python3-zstandard | python-zstandard |
| xvfb | xorg-server-xvfb |
| webp | libwebp |
| xorriso | libisoburn |
| xxd | tinyxxd (skipped when vim already provides `xxd`) |
| gcc + libc6-dev | gcc |
| python3-gi | python-gobject |
| gir1.2-webkit2-4.1 | webkit2gtk-4.1 |
| qemu-user-static | qemu-user-static + qemu-user-static-binfmt |
| busybox-static | busybox |
| gcc-arm-linux-gnueabihf | Not in the repositories: AUR `arm-linux-gnueabihf-gcc` (or `-bin`). Only the Spike 2 emulator needs it. |

## From source

See [Development](../development.md#running-from-source).

## Per-manufacturer prerequisites

The prerequisite installer installs only what the manufacturers you pick
need. On Linux both tool columns are plain packages, installed together.

| Manufacturer | Windows | WSL (Ubuntu) / Linux | Other |
|---|---|---|---|
| Barrels of Fun | – | gnupg, tar, curl, unzip, xvfb, webp | **GDRE Tools**, only for an old Godot 3 pack. On a Mac, gpg is installed with Homebrew or MacPorts. |
| Chicago Gaming Company | ffmpeg *(optional: Cactus Canyon art videos)* | e2fsprogs/debugfs, xxd | `faster-whisper` (installed for you) names callouts. |
| Jersey Jack Pinball | **WSL2** | partclone, e2fsprogs/debugfs, xorriso, pigz, ffmpeg, python3-zstandard; Emulate adds `xserver-xephyr`, `xdotool` | **The purple JJP USB key** (Emulate only), and [usbipd-win](https://github.com/dorssel/usbipd-win) to hand it to WSL. [Key on another PC](../../tools/jjp_emu/README.md#the-key-on-another-pc-usbip-pad-529). |
| Pinball Brothers | – | e2fsprogs/debugfs *(only for `.iso` Clonezilla)* | – |
| Spooky Pinball | GnuPG (gpg.exe), ffmpeg | partclone, e2fsprogs/debugfs, zstd, python3-zstandard | – |
| Stern Spike 1 | **WSL2**, for Emulate only | nothing: the app downloads its own checked emulator | **Fix setup** on the Emulate tab can install the app's own Linux (PAD-Runtime, ~370 MB). |
| Stern Spike 2 | ffmpeg; **WSL2** for full-size videos, blip-free callouts and resizing files on the card | Emulate: `qemu-user-static` (or `qemu-user-binfmt`), ARM cross-compiler, `gcc` + `libc6-dev`, `make`, `e2fsprogs`, `fuse3`, `ffmpeg` | On a Mac, `brew install e2fsprogs`. See [Emulate](emulate.md#getting-set-up). |
| Stern SAM / Whitestar, Sega, Data East | ffmpeg | – | **libpinmame** ([vpinball/pinmame releases](https://github.com/vpinball/pinmame/releases)). No ROMs bundled. |
| Williams (WPC) | ffmpeg; `faster-whisper` *(optional)* | – | **libpinmame**, for the optional capture path. No ROMs bundled. |

- **WSL 1 won't do.** It has no loop devices, so it can't mount card or
  game images. The prerequisites strip checks for a real loop device and
  names the fix (`wsl --set-version <name> 2`).
- **Without WSL2 on Spike 2,** an oversized clip is squeezed into its slot,
  a Partition Explorer swap must be the same size, and callouts keep a
  tiny scrap of the original sound.
- **Two ffmpegs on Spike 2:** the emulator needs the distro's own ffmpeg,
  not the Windows one. Without it the game plays with black videos and no
  sound, and the run says so.

### Disk space (Windows)

The WSL extracts and the emulators keep gigabytes inside WSL's virtual
disk. **⚙ > Manage disk space** shows it all.

- **Resize the WSL disk** (grow or shrink, no admin needed).
- **Move to another drive**: WSL's disks are files on C: by default. Pick
  a roomier drive (NTFS) and the app's Linux, the emulators' data disk and
  the Spike 2 card store move there; the app finds them there from then
  on. WSL is shut down while they move. No admin needed.
- **Cached cards** of the Spike 2 emulator, several GB each. Delete any:
  it re-copies on its next boot.
- **What each Emulate tab keeps** in WSL, by maker. A running emulator's
  files can't be deleted until it stops.
- **Automatic clean-up** (on by default) runs shortly after start and then
  every half hour while WSL runs. Untick **Clean up automatically** to
  stop it.
  - Leftovers of crashed runs go after a day unused.
  - Unpacked games and cached cards go after 30 days unplayed, oldest
    first when the app's Linux has under 15 GB free.
  - Saved settings, high scores and save states are never touched.

## Auto-update

The app checks for a new release at launch and then as it runs (⚙ >
**Check automatically**: at startup, hourly, every 6 hours or daily; 6
hours by default). A new release shows a banner, a ● on the ⚙ gear and a
line in the log.

| | The banner offers | What happens |
|---|---|---|
| Windows | **Install update** | Downloads the installer, checks its SHA-256, installs silently and reopens. No SmartScreen or UAC prompt. |
| macOS | **Install update** | Downloads the DMG, replaces the app in place and restarts it. No security prompt. |
| Linux | **Download update** | Saves the new AppImage next to the old one (or in `~/Downloads`), makes it executable and offers to start it. The old one is kept. |

- **No security prompts,** because the app downloads the file itself:
  only a browser download gets marked as "from the internet".
- **Your settings are kept**, and the prerequisites installer is not run
  again.
- **Closing for an update shuts WSL down,** so the new version starts
  fresh. If something else runs in WSL (Docker Desktop, say), WSL is left
  alone.
- **Closing the banner** keeps it closed for that version. A manual check
  is in the ⚙ menu.

The release tag format is `vMAJOR.MINOR.PATCH`, parsed in
[core/updater.py](../../pinball_decryptor/core/updater.py). The version is
whatever [`pinball_decryptor/__init__.py`](../../pinball_decryptor/__init__.py)
declares in `__version__`.
