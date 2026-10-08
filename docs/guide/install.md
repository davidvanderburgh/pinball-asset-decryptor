# Installing

[← Back to the README](../../README.md)

## Windows

Download the latest `Pinball_Asset_Decryptor_v*_Windows.exe` from the
[Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases)
and run it. The installer bundles a Python runtime so nothing else is needed
to launch the GUI.

The installed shortcuts start the app **as Administrator** (one standard
UAC prompt per launch) — the SD-card and Direct-SSD write paths need
elevation, and forgetting the old right-click → *Run as administrator*
used to fail halfway through a run. Paths on mapped network drives
(`W:\…`) keep working in the elevated session: Windows hides mapped
letters from elevated processes, so the app translates them to their
`\\server\share` form automatically. Network paths work in the
WSL-backed pipelines too — the app mounts the share inside WSL on its
own when an extract or write needs it.

After install, run **Install Prerequisites** from the Start Menu — it asks
which manufacturers you'll actually use and installs only the tools those
plugins need (see [Per-manufacturer prerequisites](#per-manufacturer-prerequisites)
below).

If your machine didn't already have WSL2, that first run ends with a
**restart required** banner: WSL2 only finishes installing after Windows
restarts (use *Restart* — with Fast Startup enabled, *Shut down* doesn't
count). After the restart, run **Install Prerequisites** from the Start
Menu once more to pick up the remaining WSL-side packages — the script is
safe to re-run and skips anything already installed.

If the summary reports **Ubuntu … Missing** even though WSL2 shows OK,
your `wsl.exe` couldn't register the Ubuntu distro (the error it printed
above the summary says why — a blocked Microsoft Store is a common
cause). The installer already retries with a direct download where
supported; if it still fails, run `wsl --install -d Ubuntu` in an admin
PowerShell (create the username/password it asks for, then type `exit`),
or install **Ubuntu** from the Microsoft Store app and launch it once —
then run **Install Prerequisites** again.

If the summary instead reports one of the **WSL packages** as MISSING —
the Spike 2 emulator's `qemu-user-static` is the usual one — apt saying
no is no longer where the run stops. The installer names the packages apt
refused, says in plain words what the app can try that apt cannot (refresh
the package index and retry one at a time, switch on the `universe`
component if this Ubuntu has it turned off, or fetch a single
dependency-free package from a release that publishes it), and asks before
doing any of it — the same repair the Emulate tab's **Set up
emulator…** button runs. Every package it touched is then re-checked, so
the summary reports what is really on the machine rather than what apt was
asked for.

If the installer instead stops with a red **virtualization is disabled
in BIOS/UEFI** banner, WSL2 cannot run on your machine at all until you
switch the CPU virtualization option back on in firmware setup (Intel
**VT-x** / AMD **SVM**, usually under Advanced or CPU configuration) —
no reinstall or restart helps until then. The app's prerequisite check
reports the same condition in its tooltip. Enable the option, boot back
into Windows, then run **Install Prerequisites** again.

If the app keeps reporting **WSL2** as missing while **Install
Prerequisites** reports everything as already installed, your default
distro is registered as **WSL 1**. WSL 1 has no loop devices at all, so
it can't mount a card or game image whatever packages are present, and
reinstalling WSL doesn't change that — only converting the distro does.
Both halves now say so: the installer reads `wsl -l -v`, names the distro
and offers to convert it, and the app's prerequisite tooltip and log say
"WSL is installed, but its default distro is WSL 1" instead of asking for
another install. To do it by hand, run `wsl --set-version <name> 2` in an
admin PowerShell (it runs for a few minutes; close anything using WSL
first), then click **Re-check** in the app.

If the distro itself has stopped starting — most often after upgrading it
in place from inside WSL — nothing runs in it, and `wsl -l -v` still
lists it as VERSION 2 because that answer comes from the registry rather
than from the distro. The app now checks whether the distro can run
anything at all before it explains a failed prerequisite, so it says
"nothing can run inside it … the distro itself is not starting" instead
of blaming a package or a loop device, and **Install Prerequisites** says
which registered distro did not answer before it installs anything. Try
`wsl --shutdown` (wait ten seconds) and then `wsl --update`; if it still
won't start, install a second distro **alongside** it and make that the
default, which is the one the app uses:

```powershell
wsl --install -d Ubuntu-24.04
wsl --set-default Ubuntu-24.04
```

The old distro is left exactly where it is, and `wsl --export <name>
backup.tar` still gets its files out.

If that command answers `Invalid distribution name: 'Ubuntu-24.04'`, the
machine's own `wsl.exe` is older than that release and its catalogue has no
entry for it — nothing is installed, and restarting Windows changes nothing.
Run `wsl --update` first, or `wsl --list --online` to see which names it does
accept and install one of the Ubuntu entries from that list. **Install
Prerequisites** now does all of this itself: it asks the machine which names
it accepts, updates `wsl.exe` when the catalogue is out of date, installs the
newest Ubuntu that machine offers if it still cannot have the pinned one, and
— the thing it used to get wrong — reports a failed install as missing
instead of green with a restart request.

**Which Ubuntu release is up to you.** PAD works on any current one —
22.04, 24.04, and whatever comes next — and it is never refused on a
version number: what decides whether a machine can do the work is the
prerequisite checks, which ask what it can actually do. Every check that
runs inside WSL now writes one line naming the distro and release it
probed (`WSL: Ubuntu (Ubuntu 24.04.4 LTS, WSL 2)`), so a log pasted into
a bug report carries it; a release older than 22.04 adds a second line
saying it is older than anything this is tested against and is worth
ruling out first. An app update never installs or switches a distro —
a machine that works keeps working. PAD asks the machine rather than
assuming a release: the ARM handler is registered the way *this* distro
registers one, packages whose names changed between releases are tried
under every spelling they have had, and criu is used from apt where a
release publishes it and built from source where none does. The one
release named out loud, in the installer and in the hints above, is
24.04, and that is only "the one this is tested on": it is what a fresh
install gets, not something an existing distro has to become. Two things
follow an in-place upgrade to a new release automatically, because both
are built against the release they run on — the emulator's own small
binaries (rebuilt once on the next run) and criu (a criu that no longer
starts is now reported as one that does not start, and rebuilt, instead
of counting as present).

If your WSL **logs in as root** — a distro installed without its
first-run account setup does — building a multi-boot card used to stop
with *"cannot find your WSL home … check that WSL starts"*, on a WSL that
had just built the menu program, drawn the preview and planned the card.
The card is written as root, and the app was looking for an ordinary
user's home to hand that step; there isn't one on such a machine, and
there doesn't need to be — root's own home is where `~/spike2root` has
been all along. The build now runs there. (The emulator is the one thing
that still wants an ordinary account: a root run can't attach to the
WSLg X server, so the game window opens black.)

If a multi-boot **Build** stopped on its first step with *"install:
cannot change permissions of '…/spike2root/usr/local/codeselect': No
such file or directory"*, that line misleads: it is coreutils' account
of a folder it was not allowed to create. Pressing **Start** on the
Emulate tab unpacks the game's filesystem as root, and the step that
installs the menu program ran as your own account, so on any PC that had
run a game first the menu program had nowhere to go — while the menu
preview, which only reads that filesystem, kept working. From v0.212.2
that step runs as root on Windows, the way the card build itself does,
and hands what it installs back to you. Run by hand as an account that
cannot install there, it now names the folder in the way and who owns it.

If a multi-boot **Build** or menu preview stops with **`make: command
not found`**, that is the one build tool nobody had put on a
prerequisite list. The menu a multi-game card starts up into is an ARM
program built by a Makefile, and `make` is not a compiler, so a WSL
that emulates every title perfectly can still be without it. Install
Prerequisites installs it now, the Emulate tab's prerequisite strip
asks for it under **Multi-boot cards need:**, and the tab's own refusal
names the package to install rather than pointing at the lines above
(`apt install make` on Debian/Ubuntu).

If pressing ▶ on the Replace Audio tab says **Audio preview needs
ffplay**, the ffmpeg it found is an "essentials" build or the copy
bundled inside the app — neither carries `ffplay.exe`. Answer **Yes** to
that dialog and it runs **Install Prerequisites** for you (the full
ffmpeg build includes ffplay), or drop `ffplay.exe` from a full build
into the exact folder the dialog names, then restart the app. Nothing
else is affected: previewing is optional, and replacements still get
staged, converted and written without it. The gear menu's **Install /
repair prerequisites…** stays clickable even when every prerequisite
shows green, precisely because ffplay is not one of the things they
check.

## macOS

1. Download the DMG matching your Mac from the
   [Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases):
   - `Pinball_Asset_Decryptor_v*_macOS_AppleSilicon.dmg` for Apple
     Silicon Macs (M1 or newer).
   - `Pinball_Asset_Decryptor_v*_macOS_Intel.dmg` for Intel Macs
     (requires macOS 13 Ventura or newer).

   Not sure which you have?  **Apple menu → About This Mac** — the
   *Chip* line says "Apple M1/M2/…" on Apple Silicon; Intel Macs show a
   *Processor* line with "Intel" in it.  Opening the wrong one fails
   with *"…is not supported on this type of Mac"* (an architecture
   error, not the security prompt described below — releases before
   v0.39.0 shipped Apple Silicon only, which is why they refused to
   open on Intel iMacs).
2. Open the DMG and drag **Pinball Asset Decryptor** to your
   `/Applications` folder.
3. **First-launch security override** — required because the app is
   ad-hoc signed (no Apple Developer ID).  Try to open the app once;
   macOS will refuse with *"Apple could not verify Pinball Asset
   Decryptor is free of malware…"*.  Then:
   - Open **System Settings → Privacy & Security**.
   - Scroll down to the **Security** section.  You'll see a line that
     says *"Pinball Asset Decryptor was blocked to protect your Mac."*
   - Click **Open Anyway** next to it.  Confirm with your password /
     Touch ID.
   - macOS will pop one more dialog asking if you're sure — click
     **Open**.
4. The app now launches and remembers the override; subsequent launches
   open without prompting.

**You only do this once, for the first install.**  From v0.115.0 the app
updates itself: the update banner's **Install update** button downloads
the disk image, replaces the app in place and restarts it, with no
security prompt at any point.  That is not a bypass — the "could not
verify" wall comes from `com.apple.quarantine`, which is set by whatever
*downloads* a file.  A browser sets it; the app fetching its own update
does not, so there is nothing to override.  Updating by downloading the
DMG in a browser still goes through step 3 above.

**If the app still bounces in the Dock and never appears** after the
override, the quarantine attribute didn't get cleared — strip it
manually in Terminal:

```bash
xattr -dr com.apple.quarantine "/Applications/Pinball Asset Decryptor.app"
```

Then double-click the app again.  (This is rare but happens on some
Sonoma / Sequoia setups where Gatekeeper's "Allow Anyway" click doesn't
fully drop the extended attribute.)

For **Spooky** and **JJP** Clonezilla extraction you'll also need
[Docker Desktop](https://www.docker.com/products/docker-desktop/) —
the app builds and uses an ephemeral container for partclone / debugfs
on those flows.  The **Stern Emulate** tab needs it too on macOS, for a
different reason: the game is a Linux program, and a container is how a
Mac runs one.  You don't have to install it by hand there: the Emulate
tab's **Set up emulator…** button installs a container engine with
whichever of Homebrew or MacPorts you already have and starts it, in the
app, with every line in the log pane — which is also the answer when
Docker Desktop won't install on your version of macOS.  Any of Docker
Desktop, OrbStack, Rancher Desktop or Colima will do, and the app looks
for the `docker` command in each of their own locations as well as on
PATH.  The other manufacturers (PB, BOF, CGC, Williams)
run without Docker.  Docker is a macOS requirement only — emulation
goes through WSL on Windows and runs natively on Linux.

## Linux

Download the latest `Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage`
from the [Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases),
mark it executable, and run it:

```bash
chmod +x Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage
./Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage
```

After install, run **Install Missing** from the prereqs row (or run
[installer/install_prerequisites_linux.sh](../../installer/install_prerequisites_linux.sh)
directly) — it asks which manufacturers you'll actually use and installs
only the apt packages those plugins need (see
[Per-manufacturer prerequisites](#per-manufacturer-prerequisites) below).

From v0.184.2 the AppImage carries that script itself, so **Install
Missing** works from a downloaded AppImage and not only from a source
checkout. In the same pass: **'a' for all** really does install every
manufacturer's packages, Stern's included (the picker used to stop at the
five manufacturers the menu had when it was written, so the Spike 2
emulator's `qemu-user-static` was skipped without a word, and an
unrecognised number is now named instead of dropped); one package apt
cannot get no longer takes the whole batch down with it, since the batch
falls back to installing one at a time; running the script as root works
instead of failing on every install; and anything apt still refuses is
named, with the offer to try the app's own repair (index refresh, the
`universe` component, or a single dependency-free package fetched from a
release that publishes it).

The installer speaks **apt** (Debian / Ubuntu) and, from v0.187.1,
**pacman** (Arch and its spins: Omarchy, CachyOS, EndeavourOS, Manjaro).
A user reported the app
running without a fault on Omarchy from source, having translated the
package names by hand; that translation is now the installer's job, so
**Install Missing** works there too. On Arch the install is
`pacman -Syu --needed`, a full system update first, because pacman does
not install into a stale system. The apt names in the
[per-manufacturer table](#per-manufacturer-prerequisites) map to Arch as
follows; everything not listed is spelled the same:

| apt | Arch |
|---|---|
| python3-zstandard | python-zstandard |
| xvfb | xorg-server-xvfb |
| webp | libwebp |
| xorriso | libisoburn |
| xxd | tinyxxd, skipped when vim already provides `xxd` (the two conflict) |
| gcc + libc6-dev | gcc (Arch's glibc ships its headers) |
| python3-gi | python-gobject |
| gir1.2-webkit2-4.1 | webkit2gtk-4.1 |
| qemu-user-static | qemu-user-static + qemu-user-static-binfmt, which registers the ARM handler with the F flag the emulator needs, in the same transaction |
| busybox-static | busybox (Arch's is static) |
| gcc-arm-linux-gnueabihf | **not in the repositories.** AUR `arm-linux-gnueabihf-gcc` (or `arm-linux-gnueabihf-gcc-bin`, prebuilt). The installer names it rather than failing on it; only the Spike 2 emulator needs it |

The prerequisite strip's hover hints and the Emulate tab's "run this"
advice are spelled for pacman on such a machine as well, and the CGC
transcribe step's pip install survives Arch's externally-managed Python by
installing into your user site.

On any other distro, install the equivalent packages by hand using the
table in that section; the script prints both spellings when it finds
neither package manager.

## From source

See [Development](../development.md#running-from-source).

## Per-manufacturer prerequisites

Different plugins need different runtime tools. The prerequisite installer
lets you pick which manufacturers you care about and installs only what
those plugins need.

| Manufacturer | Host-side (Windows) | WSL-side (Ubuntu) / Linux apt (Arch names: see [Linux](#linux)) | Other |
|---|---|---|---|
| Barrels of Fun | – | gnupg, tar, curl, unzip, xvfb, webp | **GDRE Tools** — only required for a pack without a Godot 4 file directory (a Godot 3 pack); every current build (Labyrinth, Dune, Winchester) is unpacked and repacked by the bundled native extractor from the pack's own directory.  Install Prerequisites auto-downloads GDRE from [GDRETools/gdsdecomp](https://github.com/GDRETools/gdsdecomp/releases) regardless so older `.fun` files still work; on a Mac nothing installs it and nothing current needs it, and an old pack there stops with a message rather than an empty `pck/`.  **macOS** runs gpg and tar on the Mac itself, so both are probed there (they used to pass as "n/a", and a Mac without GnuPG only found out at "bash: gpg: command not found" under an Extract Failed box that blamed the `.fun` file); a missing gpg goes red on the prerequisites strip and **Install Missing** installs `gnupg` with Homebrew (or MacPorts) in the app's own log.  A MacPorts that was installed for an older macOS refuses every command with "OS platform mismatch"; Install Missing checks for that before asking for a password, and its consent dialog then runs `port migrate` first, in the same one-password run.  A failed install comes back in a box that quotes the package manager's own Error lines. |
| Chicago Gaming Company | ffmpeg *(optional — Cactus Canyon display-art videos)* | e2fsprogs/debugfs, xxd | `faster-whisper` pip package — auto-installed by Install Prerequisites, drives the **Auto-transcribe samples to callouts.csv** checkbox on the Extract tab (tiny.en model by default, ~75 MB downloaded on first use, runs entirely on CPU; larger/more-accurate models selectable with the **Voice recognition quality** picker beside it). Cactus Canyon DCS audio repack uses the bundled DCSExplorer/DCSEncoder (BSD-3). |
| Jersey Jack Pinball | **WSL2 itself** *(every JJP flow loop-mounts the ext4 filesystem it pulls out of the `.iso`, so a distro running under WSL 1 — which has no loop devices, ever — can't extract or write at all. It used to pass the prerequisite check and then fail with a bare "mount failed: No such file or directory" minutes into an extract, then re-extract the whole image on the corrupt-image theory and fail the same way. Both the prerequisites strip and the extract path now probe for a real loop device up front and name the fix: `wsl -l -v` to check, `wsl --set-version <name> 2` to convert)* | partclone, e2fsprogs/debugfs, xorriso, pigz, ffmpeg, python3-zstandard *(the loop-mount tools themselves ship in stock Ubuntu's util-linux/mount)*; the **Emulate** tab additionally needs `xserver-xephyr` (the nested display the game fullscreens into, which is what keeps it off a 4K desktop and out of software rendering) and `xdotool` (the only way to place the game and matrix windows — WSLg windows belong to its compositor, and a Win32 move is not seen by it) | **The purple JJP USB security key**, for the Emulate tab only. The game's code is encrypted with it, so this is not a check that can be skipped, and the keys are **per title**. Windows also needs [usbipd-win](https://github.com/dorssel/usbipd-win) to pass the key through to WSL; the panel attaches it for you once it is installed. The emulator rig itself ships with the app in [`tools/jjp_emu`](../../tools/jjp_emu) — see that folder's README. No ROMs or game files are bundled: everything comes from the ISO you supply. |
| Pinball Brothers | – | `e2fsprogs/debugfs` *(only for `.iso` Clonezilla)* | – |
| Spooky Pinball | GnuPG (gpg.exe), ffmpeg | partclone, e2fsprogs/debugfs, zstd + python3-zstandard | – |
| Stern Pinball (Spike 1) | **WSL2 itself**, for the **Emulate** tab only *(a patched ARM `qemu-user` plus a CUSE hardware model, so the game runs unmodified under an emulated version of its own board set)* | **nothing** — the emulator and its device model are binaries *we* build, verify and pin ([`core/payloads.py`](../../pinball_decryptor/core/payloads.py)), and the app installs them for you. Build tools (`ninja-build`, `libglib2.0-dev`, `pkg-config`, `flex`, `bison`, `gcc`, `libfuse3-dev`, `python3-venv`, `wget`, `xz-utils`) are needed **only** if you choose to build from source instead | The rig ships with the app in [`tools/spike1_emu`](../../tools/spike1_emu). The first Start **downloads the exact binaries this app version was tested with** — a static `qemu-arm` and a static `s1hwshim`, each checked against a SHA-256 pinned in the app — so nothing is compiled on your machine and no distro package is needed. **Fix setup** on the Emulate tab does the same on demand, and offers a file picker if the download is blocked (same checksum, different delivery). If you'd rather build from source, install the tools listed here and the rig's preflight (`tools/spike1_emu/prereqs.sh`) names anything still missing all at once, in your own package manager's spelling. From v0.194.0 there is usually no distro to prepare either: **Fix setup** on the Emulate tab installs the app's own pinned Linux (`PAD-Runtime`, a one-time ~370 MB download) and every later run uses it, so WSL2 itself is the only thing you have to have. Start uses that runtime once it is there, but never installs it for you — and `PAD_RUNTIME=0` sends everything back to the machine's own distro. Note that once it is installed **everything** the app runs in Linux runs inside it, both emulator rigs included — what they generate (extractions, card caches, save states) is kept on a separate expandable disk under `LOCALAPPDATA`, attached by name so it is at the same path in every distro, which is what lets the runtime be replaced or removed without destroying a saved game. Right-clicking **Fix setup** deletes that data, the downloaded files, or the runtime itself, one at a time and never while a rig is running. Extract and Write need no WSL at all — `image.bin` is plaintext PCM, decoded and patched directly on the host. |
| Stern Pinball (Spike 2) | ffmpeg *(Replace Audio/Video preview, spectrograms, video conversion, saving a scene preview as MP4)*; **WSL2 itself** *(full-size video replacement, the opt-in blip-free callouts, and different-size file swaps in the Partition Explorer — resizes files inside the card's ext4 partition; without it an oversized clip is crushed into its stock byte slot, a Partition Explorer replacement has to match the original's size exactly, and a build that opted in to blip-free silently falls back to the standard build with the brief original-sound scrap, which the prerequisites strip and Write Complete dialog now say. A distro running under WSL 1 has no loop devices and can't mount card images — it used to pass the prerequisite check and then fail mid-write; both the strip and the write path now probe for a real loop device up front and name the fix: `wsl -l -v` to check, `wsl --set-version <name> 2` to convert)* | – (the loop-mount tools ship in stock Ubuntu's util-linux/mount) | macOS uses e2fsprogs' `debugfs` for the same ext4 file-growth path (`brew install e2fsprogs`); native Linux mounts ext4 itself. The audio engine's pip packages (numpy, unicorn, capstone) are bundled by the installer, and from v0.173.3 so is `sounddevice`, which is the Emulate tab's speaker on Windows — the guest's PCM is played by the bundled Windows Python directly, rather than through WSLg's own audio hop; existing installs add it by re-running Install Prerequisites. The **Emulate** tab additionally needs WSL2; the emulator rig itself ships with the app in [`tools/spike2_emu`](../../tools/spike2_emu), and the prerequisites installer adds what it needs inside the distro (`qemu-user-static`, which Ubuntu 25.10 and 26.04 call `qemu-user-binfmt`, an ARM cross-compiler for the shim, `gcc` + `libc6-dev` for the native renderer, `make` for the boot menu a multi-boot card starts up into, `e2fsprogs`, `fuse3`, and `ffmpeg` — the distro's own, *not* the host ffmpeg in the first column, and a machine can have that one and still lack this one; the game decodes neither its video nor its sound itself, so both go through it and without it the emulator starts, boots and opens its window normally and plays black and silent, which the run now checks for up front and names). It has no setup step: the first run builds the guest rootfs out of the card image you picked (no root), compiles the hardware shim and the GL renderer, and every later run rebuilds any of them whose sources an update has moved on. All three were manual steps that `rootfs.sh` only printed as advice and nothing enforced, so a fresh install failed at whichever one you stopped at, naming a missing ring or binary rather than the step — `env: './padglhost': No such file or directory` (fixed v0.114.0) and `open ring: No such file or directory` (v0.116.0). Every run now also proves the guest can start a program before it starts one and repairs the causes that don't need root, so the last error of that family — `chroot: failed to run command '/bin/sh': No such file or directory` (v0.116.1) — is either fixed for you or explained with the one command that needs your password. A run also survives the machine's GPU driver refusing to load: on WSL the graphics libraries are injected from the Windows side, so a VM left running across a driver or WSL update can be handed a stale set that Linux's own loader then rejects outright — which used to end the run four lines after the window opened, with no guest, no sound and no playfield. The run now says what that loader line means (the cure is restarting WSL, because nothing inside Linux can re-lay those libraries), keeps the failed attempt's log beside the new one, and starts the renderer again on Mesa's software rasteriser, which this rig measures within a few percent of the GPU path anyway; a second death is reported as not being the GPU, and `PAD_GL_SOFTWARE=1` skips the GPU attempt from the start. See that folder's README. Everything else the rig needs is derived from the card at run time, including the virtual playfield's artwork and its switch, coil and insert positions, so no title needs anything added to the repository to work. The rig ships with the app from v0.109.0; before that it was a source-checkout feature, which left anyone who installed the app rather than cloning it with a tab that could only report the rig missing. |
| Williams (WPC) | ffmpeg; `faster-whisper` *(optional — Auto-transcribe)* | – (no WSL needed) | **libpinmame** (for the optional PinMAME capture path — download from [vpinball/pinmame releases](https://github.com/vpinball/pinmame/releases)). DCS audio decoding uses a bundled DCSExplorer build (BSD-3). User-supplied MAME ROM zips — no ROMs bundled. |

On Linux, the Windows host-side tools (gpg, ffmpeg) are just additional
apt packages alongside the rest — the Linux installer flattens both
columns into one apt-install set.

Run [installer/install_prerequisites.ps1](../../installer/install_prerequisites.ps1)
as Administrator (the Start Menu shortcut does this for you) and pick from
the manufacturer menu. Re-run any time — anything already installed gets
skipped.

On Linux, the equivalent script is
[installer/install_prerequisites_linux.sh](../../installer/install_prerequisites_linux.sh)
— same per-manufacturer picker, installs the apt packages directly (no
WSL layer to set up).

On macOS, Spooky/JJP Clonezilla flows use Docker Desktop instead of WSL
(the app builds the container automatically the first time it's needed).

On Windows, the WSL extract paths stage gigabytes inside the WSL virtual
disk. A **Manage disk space** dialog (⚙ settings menu) lets you see WSL disk usage and
**resize the WSL disk** (grow or shrink, no admin needed) so a big
Clonezilla extract doesn't wall on a too-small WSL volume.

From v0.206.0 the same dialog also shows the **Spike 2 emulator's cached cards**, which are the largest thing the app keeps on disk — a cached card is several gigabytes and the emulator holds one per title it has booted. They sit on the emulator's own work disk, so they get their own usage bar beside the WSL and Windows temp ones, and any of them can be deleted from the same list. A deleted card is not lost: it re-copies the next time that card boots, which is why the dialog prices the cached cards separately from the leftover staging beside them.

It also lists what the Emulate tabs keep inside WSL (under `/var/tmp/pad_<rig>`), grouped by maker: unpacked games, last-run folders, and each emulator's own Python and leftovers, each with its size. An emulator that is running right now has its files marked and they cannot be deleted until it stops; **Clean all** skips them. Saved emulator settings and high scores are never listed, so cleaning never loses them.

## Auto-update

The app polls the GitHub releases API on launch, and then keeps checking
while it runs — ⚙ → **Check automatically** picks the gap (only at
startup, hourly, every 6 hours, or once a day; 6 hours by default), so a
release published mid-session no longer goes unnoticed until you go
looking. If a newer release exists it shows a banner at the top of the
window, puts a ● notification on the ⚙ settings gear, and logs a
clickable download link. Closing the banner sticks: the repeating check
won't re-open it for a version you've already waved off (the gear's ●
and its menu entry still carry the news, and a newer version banners
normally). The check is non-blocking; the outcome ("update available" /
"you're on the latest" / "check failed") is always mirrored into the
log, and a manual check lives in the ⚙ menu.

On Windows the banner offers a one-click **Install update**: the app
downloads the release installer itself and runs it silently, then reopens
updated. Because the app downloads the file (not a browser), Windows does
not tag it with the Mark-of-the-Web, so the SmartScreen "Windows
protected your PC" prompt never appears, and since the app already runs
elevated there's no UAC prompt either. The whole update is one click with
no security passes. Installing over the top keeps your `settings.json`,
and the update never re-runs the prerequisites installer (the app checks
for missing prerequisites at runtime and offers **Install Missing** if
any actually are).
The download is verified against the release asset's SHA-256 before it
runs. Closing for the update also shuts WSL down, so the updated app starts
a fresh one: a WSL left running across an update could bring the emulator's
game window up with no picture until **Restart WSL…** was pressed. If
anything other than the app's own Linux is running in WSL (Docker Desktop,
say), WSL is left alone and the log says so.

On Linux the banner offers **Download update**, which fetches the new
AppImage itself rather than handing the release page to a browser. From
inside an AppImage a browser handoff is unreliable — the opener inherits
the bundle's environment and can fail to start at all — so the *Download*
button could look completely dead. Fetching the file needs no browser.
The new AppImage lands next to the one you're running (or in
`~/Downloads` if that folder is read-only), is marked executable, and the
app offers to start it and close itself. Nothing is installed and nothing
is overwritten: the version you were running stays exactly where it is,
so you can delete it whenever you're happy with the new one.

macOS keeps the plain *Download* button that opens the release page —
`open` isn't affected by the bundle environment, and a .dmg still has to
be mounted and dragged by hand, so downloading it for you would save
nothing.

The release tag format is `vMAJOR.MINOR.PATCH`; see
[core/updater.py](../../pinball_decryptor/core/updater.py) for the
parser. The current shipped version is whatever
[`pinball_decryptor/__init__.py`](../../pinball_decryptor/__init__.py)
declares — `__version__` is the single source of truth.
