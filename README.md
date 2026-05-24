# Pinball Asset Decryptor

One app to extract, view, and modify game assets from pinball machines made
by **Barrels of Fun**, **Chicago Gaming Company**, **Jersey Jack Pinball**,
**Pinball Brothers**, **Spooky Pinball**, and **Williams** (WPC-era) —
70+ games across six manufacturers.

This is a unified replacement for separate decryptor apps that all shared
the same Tk GUI shell, queue-based pipeline contract, checksum tracking,
and mod-pack workflow. Each manufacturer is a plugin under
[pinball_decryptor/plugins/](pinball_decryptor/plugins/); the shared shell
lives in [pinball_decryptor/core/](pinball_decryptor/core/) and
[pinball_decryptor/gui/](pinball_decryptor/gui/).

## Disclaimer

This project is an independent interoperability utility. It is **not
affiliated with, endorsed by, or sponsored by** Chicago Gaming Company,
Planetary Pinball Supply, Bally, Williams, Stern Pinball, Jersey Jack
Pinball, Pinball Brothers, Spooky Pinball, Barrels of Fun, or any other
pinball manufacturer, publisher, or rights holder. All trademarks and
game titles referenced are the property of their respective owners and
are used here in their nominative/descriptive sense only — to identify
which file formats this tool can read.

The tool ships **no game content** of any kind — no ROMs, no audio
samples, no graphics, no executables from any pinball machine. It is
inert until the user supplies their own file that they obtained
legitimately (typically by purchasing the machine, downloading the
official update from the manufacturer's support portal, or imaging
their own physical media).

Intended use is **personal customization of a machine you own** — the
same kind of fair-use modification covered by Sega v. Accolade (1992)
for reverse engineering interoperability and by the general right to
modify property you've legally purchased. Distributing modified game
assets to others, hosting copyrighted ROMs, or reselling modified
firmware is not supported by this tool and is **your responsibility to
avoid** — those activities have separate legal considerations the tool
does not address.

No warranty. Use entirely at your own risk; flashing a modified `.img`
to a real pinball machine can render it inoperable until you flash a
known-good image back. The maintainers accept no liability for damage
to hardware, voided warranties, or any consequence of using this tool.

## Supported manufacturers

| Manufacturer | Games | Input formats | Capabilities |
|---|---|---|---|
| **Barrels of Fun** | 3 (Labyrinth, Dune, Winchester) | `.fun` | Extract, Write, Mod Pack |
| **Chicago Gaming Company** | 4 (Medieval Madness Remake, AFM Remake, MB Remake, Pulp Fiction) | `.img` (raw bootable installer disk image) | Extract, Write, Mod Pack — audio only (WPC remakes: 1300+ DCS `.wav` samples + ROM; Pulp Fiction: 6 JPS sound banks that the plugin auto-decodes into ~1,000 individual `.wav` files you can edit, then repacks back into the bnk on Write). CGC games render all DMD/LCD video in real time, so there are no video files to mod. Optional **Generate callouts.csv** action runs Whisper across the extracted WAVs (skipping non-speech via VAD) so you can search "who says *Excellent!*" instead of opening files blind. |
| **Jersey Jack Pinball** | 11 (Wonka, GnR, Hobbit, Wizard of Oz, Avatar, etc.) | `.iso` Clonezilla image, or **directly from the game SSD** | Extract, Write, Mod Pack, **Direct-SSD** (read/write the game's physical SSD without an ISO intermediate — auto-discovers the right partition, content-verifies `/jjpe/gen1`, mirrors writes across A/B slots so the change survives the next firmware boot). |
| **Pinball Brothers** | 4 (ABBA, Alien, Queen, Predator) | `.upd`, `.iso` (Clonezilla) | Extract, Write, Apply Delta, Mod Pack |
| **Spooky Pinball** | 14 (Beetlejuice, Evil Dead, R&M, Halloween, Looney Tunes, etc.) | `.pkg`, `.ed`, `.scooby`, `.beetlejuice`, `.looney`, `.iso`, `.zip` | Extract, Write, Mod Pack |
| **Williams** (WPC-era) | 41 WPC titles (Attack From Mars, Medieval Madness, Twilight Zone, Theatre of Magic, Fish Tales, etc.) | `.zip` (MAME ROM dumps) | **Static**: DMD scene PNGs, animation MP4s, font strips, and per-track DCS sound-ROM audio decoded from the ROM. **Capture**: per-scene gameplay MP4s with synced DCS audio via libpinmame (scripted playthrough — skill shots, mode starts, multiball, jackpots). Optional **Auto-transcribe** names the extracted audio by its spoken call-outs. |

The full per-game lists with the format-specific quirks live in the plugin
sources:
[bof/games.py](pinball_decryptor/plugins/bof/games.py),
[cgc/games.py](pinball_decryptor/plugins/cgc/games.py),
[jjp/games.py](pinball_decryptor/plugins/jjp/games.py),
[pb/games.py](pinball_decryptor/plugins/pb/games.py),
[spooky/games.py](pinball_decryptor/plugins/spooky/games.py),
[williams/games.py](pinball_decryptor/plugins/williams/games.py).

The Williams plugin has two complementary extract paths, independently
togglable via checkboxes on the Extract tab:

### Static extract (ROM-decoded assets)

Python port of
[permartinson/wpcedit.js](https://github.com/permartinson/wpcedit.js)
(based on Garrett Lee's original 2004 WPC Edit) to walk the WPC ROM's
font/graphics/animation master tables and decode the 11 compressed-frame
encodings the game's 6809 code uses at runtime. Output per game:

- **`dmd_scenes/scene_*.png`** — one PNG per full-frame DMD bitmap
  (jackpot splashes, mode-start announcements, title cards). Order
  of magnitude: ~800–1400 scenes per game ROM.
- **`dmd_scenes/pairs/pair_*.png`** — 4-shade composites that pair
  consecutive low+high planes.
- **`dmd_scenes/browse.mp4`** — every scene back-to-back at 2 fps so
  you can skim hundreds in a minute.
- **`animations/anim_*.mp4`** — true game animations decoded from
  the WPC animation table (one MP4 per cinematic sequence — the
  "fish growing toward you" attract animation in Fish Tales, the
  motorcycle ride in No Fear, etc.).
- **`fonts/font_*.png`** — sprite-sheet grids of every DMD glyph
  atlas (full ASCII alphabets in multiple sizes).
- **`sounds/track_*.wav`** — every music cue, voice line, and sound
  effect from the game's DCS sound ROMs, one WAV per track, plus a
  `manifest.json`. DCS-era games (1993+) only — pre-DCS titles like
  Fish Tales use the older YM2151 sound board and have no statically
  decodable audio. Decoded with a bundled
  [DCSExplorer](https://github.com/mjrgh/DCSExplorer) build (BSD-3).

Tick **Auto-transcribe samples to callouts.csv** on the Extract tab
(shown only for DCS-era games) to run `faster-whisper` over the
extracted tracks and emit a CSV — or renamed WAVs — mapping each
sound to its spoken call-out, the same mechanism the CGC plugin uses.

### PinMAME runtime capture (composed cinematics + audio)

Drives [libpinmame](https://github.com/vpinball/pinmame) under ctypes,
auto-credits + presses Start + plays a per-game scripted shot sequence
so the ROM walks through its named cinematics — skill shots, mode
starts, multiball, jackpots, end-of-ball bonus, etc.  Emits one MP4 per
scene named for the moment (e.g. `skill_shot.mp4`,
`multiball_start.mp4`, `total_annihilation_setup.mp4`) with synced DCS
audio.

16 popular titles have hand-tuned scripts of 10–21 named moments each:
AFM, MM, ToM, FT, WW, TZ, AF, STTNG, IJ, JD, NGG, T2, DM, RS, SS,
Dracula. The remaining 25 games use a smart-generic pattern matcher
that builds an equivalent playthrough from the per-game PinMAME switch
profile.

While the capture is running, the GUI shows a live DMD preview pane
and a labeled switch-matrix grid — click any switch to manually press
it for diagnostics.

## Chicago Gaming Company plugin (v0.5.0)

CGC's installer `.img` files are raw bootable disk images with three
nested layers — an MBR-partitioned installer rootfs containing an
`emmc.img` blob that's itself an MBR-partitioned ext4 disk holding the
actual game. **No encryption** anywhere in the chain; the difficulty
is purely the nesting. The plugin handles all three layers
transparently — you give it `.img`, you get back the playable game's
asset tree.

### Asset shape per game

- **MM / AFM / MB Remakes** (CGC's `emumm` WPC emulator + original
  Williams ROM): `appdata/samples/vol_25perc/S<NNNN>_C<N>.wav` — a few
  hundred pre-attenuated `.wav` callouts per game, in standard 16-bit
  stereo PCM. Plus the original WPC ROM in `rom/` and boot bitmaps.
- **Pulp Fiction** (CGC original on a BeagleBone Black, audio engine
  CGC's in-house "JPS" library): 6 `.bnk` sound banks the plugin
  auto-decodes into ~1,000 individual `.wav` files (music + speech +
  SFX + diagnostics + beeped-speech) plus a `manifest.json` mapping
  every event to its underlying buffer. Repacks on Write so audio
  swaps end up back in the `.img` byte-for-byte verified by software
  round-trip. The full reverse-engineering journal lives in
  [docs/CGC_BNK_RE.md](docs/CGC_BNK_RE.md).

### Auto-transcribe samples to `callouts.csv` (opt-in)

CGC's audio filenames are sequential codes (`S0197_C6.wav`) with no
human-readable names. Tick **Auto-transcribe samples to callouts.csv**
on the Extract tab to run `faster-whisper` (tiny.en, CPU-int8) across
every extracted WAV, with silence/non-speech filtered out via the
built-in Silero VAD. Output is a CSV mapping each WAV's relative path
to its detected English text, so you can open Excel and search "Joust
champion!" to find which sample to swap.

Tick the companion **...and rename WAVs using transcripts** checkbox
to also rename each speech WAV in place — `S0197_C6.wav` becomes
`S0197_C6 - Get the troops ready.wav` so File Explorer shows the
content inline. Write is rename-aware: edits to renamed files get
written back to the original inner-ext4 path the game expects.

The `faster-whisper` pip package is treated as a real prerequisite and
auto-installed by **Install Prerequisites** (same flow as the WSL
tools). The model itself (~75 MB) downloads on first transcribe-run
and is cached in `%USERPROFILE%\.cache\huggingface\`.

## Install

### Windows

Download the latest `Pinball_Asset_Decryptor_v*_Windows.exe` from the
[Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases)
and run it. The installer bundles a Python runtime so nothing else is needed
to launch the GUI.

After install, run **Install Prerequisites** from the Start Menu — it asks
which manufacturers you'll actually use and installs only the tools those
plugins need (see [Per-manufacturer prerequisites](#per-manufacturer-prerequisites)
below).

### macOS

1. Download the latest `Pinball_Asset_Decryptor_v*_macOS.dmg` from the
   [Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases).
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
on those flows.  The other manufacturers (PB, BOF, CGC, Williams) run
without Docker.

### Linux

Download the latest `Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage`
from the [Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases),
mark it executable, and run it:

```bash
chmod +x Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage
./Pinball_Asset_Decryptor_v*_Linux_x86_64.AppImage
```

After install, run **Install Missing** from the prereqs row (or run
[installer/install_prerequisites_linux.sh](installer/install_prerequisites_linux.sh)
directly) — it asks which manufacturers you'll actually use and installs
only the apt packages those plugins need (see
[Per-manufacturer prerequisites](#per-manufacturer-prerequisites) below).

The installer expects an apt-based distro (Debian / Ubuntu); on other
distros, install the equivalent packages manually using the table in that
section.

### From source

```bash
git clone https://github.com/davidvanderburgh/pinball-asset-decryptor.git
cd pinball-asset-decryptor
pip install -r requirements.txt
pip install pycryptodome UnityPy fsb5 pyogg   # only needed for Spooky
python -m pinball_decryptor
```

Or double-click [Pinball Asset Decryptor.pyw](Pinball Asset Decryptor.pyw)
on Windows / [launch.vbs](launch.vbs) for a no-console launch.

## Quick start

1. On launch, the **picker** shows a card per manufacturer with every
   compatible game listed (greyed + struck-through for ones not
   currently decryptable — e.g. Spooky's Total Nuclear Annihilation,
   AES key unknown). Click a card to enter that manufacturer's view.
2. The **prerequisites** row at the top of the mfr view turns each
   needed tool green (✓) or red (✗); hover for an install hint.
3. **Extract tab** — pick an input file and an output folder; click
   *Extract*. The output folder gets the decrypted assets plus a
   `.checksums.md5` baseline used by the Write tab.
4. Modify any files in the output folder you want to change.
5. **Write tab** — pick the original file, the (now-modified) assets
   folder, and an output folder; click *Build update*. You get an
   installable file that's ready for a USB drive.
6. **Mod Pack tab** — share just your changed files as a zip, or apply
   someone else's mod pack on top of an extracted folder.
7. **< Back** in the top bar returns to the picker. Each manufacturer
   keeps its own log scrollback, so coming back to the same one
   shows your previous activity intact.

If you browse to a file the current manufacturer doesn't recognise but
*another* manufacturer does, the badge under the input field will say
**"Looks like &lt;game&gt; (&lt;manufacturer&gt;) — click to switch"** and one click
swaps to the right plugin without losing the path you just chose.

## Per-manufacturer prerequisites

Different plugins need different runtime tools. The prerequisite installer
lets you pick which manufacturers you care about and installs only what
those plugins need.

| Manufacturer | Host-side (Windows) | WSL-side (Ubuntu) / Linux apt | Other |
|---|---|---|---|
| Barrels of Fun | – | gnupg, tar, curl, unzip, xvfb, webp | **GDRE Tools** (auto-downloaded by Install Prerequisites from [GDRETools/gdsdecomp](https://github.com/GDRETools/gdsdecomp/releases)) |
| Chicago Gaming Company | – | e2fsprogs/debugfs, xxd | `faster-whisper` pip package — auto-installed by Install Prerequisites, drives the **Auto-transcribe samples to callouts.csv** checkbox on the Extract tab (tiny.en model, ~75 MB downloaded on first use, runs entirely on CPU). |
| Jersey Jack Pinball | – | partclone, e2fsprogs/debugfs, xorriso, pigz, ffmpeg, python3-zstandard | – |
| Pinball Brothers | – | `e2fsprogs/debugfs` *(only for `.iso` Clonezilla)* | – |
| Spooky Pinball | GnuPG (gpg.exe), ffmpeg | partclone, e2fsprogs/debugfs, zstd + python3-zstandard | – |
| Williams (WPC) | ffmpeg; `faster-whisper` *(optional — Auto-transcribe)* | – (no WSL needed) | **libpinmame** (for the optional PinMAME capture path — download from [vpinball/pinmame releases](https://github.com/vpinball/pinmame/releases)). DCS audio decoding uses a bundled DCSExplorer build (BSD-3). User-supplied MAME ROM zips — no ROMs bundled. |

On Linux, the Windows host-side tools (gpg, ffmpeg) are just additional
apt packages alongside the rest — the Linux installer flattens both
columns into one apt-install set.

Run [installer/install_prerequisites.ps1](installer/install_prerequisites.ps1)
as Administrator (the Start Menu shortcut does this for you) and pick from
the manufacturer menu. Re-run any time — anything already installed gets
skipped.

On Linux, the equivalent script is
[installer/install_prerequisites_linux.sh](installer/install_prerequisites_linux.sh)
— same per-manufacturer picker, installs the apt packages directly (no
WSL layer to set up).

On macOS, Spooky/JJP Clonezilla flows use Docker Desktop instead of WSL
(the app builds the container automatically the first time it's needed).

## Auto-update

The app polls the GitHub releases API on launch and posts an "Update
available" link in the log pane if a newer release exists. The check is
non-blocking and silent if you're already on the latest version.

The release tag format is `vMAJOR.MINOR.PATCH`; see
[core/updater.py](pinball_decryptor/core/updater.py) for the
parser. The current shipped version is whatever
[`pinball_decryptor/__init__.py`](pinball_decryptor/__init__.py)
declares — `__version__` is the single source of truth.

## Architecture

The app is a thin Tk shell that loads manufacturer plugins:

```
pinball_decryptor/
├── core/                         # manufacturer-agnostic shell
│   ├── pipeline_base.py          # 4-callback pipeline contract
│   ├── checksums.py              # baseline .checksums.md5 generator
│   ├── modpack.py                # mod-pack zip export/import
│   ├── executor.py               # WSL/Mac/Native subprocess wrapper
│   ├── updater.py                # GitHub release-check
│   ├── clonezilla.py             # generic gunzip+debugfs ISO extraction
│   └── registry.py               # Manufacturer ABC + plugin discovery
├── gui/
│   └── main_window.py            # manufacturer-aware window
├── plugins/
│   ├── bof/                      # Barrels of Fun (gpg + GDRE Tools)
│   ├── cgc/                      # Chicago Gaming Company (nested .img -> ext4)
│   ├── jjp/                      # Jersey Jack Pinball (+ private Docker)
│   ├── pb/                       # Pinball Brothers
│   ├── spooky/                   # Spooky Pinball (+ private Docker)
│   └── williams/                 # WPC-era (static ROM scrape + PinMAME capture)
├── app.py                        # controller — wires GUI ↔ plugins
└── icon.{ico,png}
```

Each plugin subclasses [`Manufacturer`](pinball_decryptor/core/registry.py) and
sets a few attributes — `key`, `display`, `games`, `capabilities`,
`input_spec`, plus `extract_phases` / `write_phases` for the GUI's phase
indicator. Then it implements `detect(path)` and the pipeline factories
appropriate for its capabilities.

Pipelines all speak the same callback contract:

```python
log_cb(text, level)              # append to log pane ("info"/"success"/"error")
phase_cb(index)                  # light up phase indicator N
progress_cb(current, total, desc) # drive the progress bar
done_cb(success, summary)        # terminal message
```

Settings persist per-manufacturer at
`%APPDATA%\pinball_decryptor\settings.json` (or
`~/Library/Application Support/pinball_decryptor/` on macOS,
`~/.config/pinball_decryptor/` on Linux), keyed by mfr key:

```json
{
  "theme": "dark",
  "last_manufacturer": "spooky",
  "manufacturers": {
    "pb":     {"extract_input": "...", "extract_output": "...", ...},
    "spooky": {"extract_input": "...", ...}
  }
}
```

A path you've browsed to under one manufacturer doesn't bleed into
another's saved settings — the App's save logic validates the path with
that manufacturer's `detect()` before persisting.

## Adding a new manufacturer plugin

1. Copy [plugins/pb/](pinball_decryptor/plugins/pb/) to `plugins/<mfr>/`.
2. Replace [games.py](pinball_decryptor/plugins/pb/games.py) with that
   manufacturer's GAME_DB.
3. Rewrite [formats.py](pinball_decryptor/plugins/pb/formats.py) for that
   manufacturer's detection logic.
4. Lift the pipelines from the upstream decryptor into
   [pipeline.py](pinball_decryptor/plugins/pb/pipeline.py); change imports to
   use `...core.checksums`, `...core.tar_utils`, etc. Lift any
   format-specific helpers (`audio.py`, `crypto.py`, `godot.py`, etc.)
   into the plugin directory alongside.
5. Update [manufacturer.py](pinball_decryptor/plugins/pb/manufacturer.py) —
   change `key`, `display`, `capabilities`, `input_spec`, `extract_phases`,
   `write_phases`, `detect`, factory methods, `extract_input_help`,
   `write_install_help`.
6. Append `"pinball_decryptor.plugins.<mfr>"` to `_PLUGIN_MODULES` in
   [core/registry.py](pinball_decryptor/core/registry.py).
7. Add a manufacturer entry to the prereq manifest in
   [installer/install_prerequisites.ps1](installer/install_prerequisites.ps1).
8. Smoke-test: load all plugins, run `detect()` against real sample files,
   instantiate the pipelines.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests
```

The suite exercises the full Extract → Write round-trip per manufacturer
against synthetic fixtures generated at test time — no real game files
are shipped or required. Coverage:

| Manufacturer | Tested | How |
|---|---|---|
| Barrels of Fun | Extract + Write round-trip, all 3 games | Synthetic `.fun` (gpg-symmetric tar.gz) — *skipped automatically when gpg isn't installed* |
| Chicago Gaming Company | Detection (filename + MBR signature) + contract + JPS .bnk extract/repack round-trip on synthetic banks | Full Extract walks 3 nested layers of ext4 disk images and needs WSL + a real installer .img (7-15 GB), not testable in CI; the JPS sound-bank extractor/repacker is unit-tested against synthetic in-memory bnks |
| Jersey Jack | Detection + write-output-rename wrapper | Full Extract needs WSL + real ISO (gigabytes), not testable in CI |
| Pinball Brothers | Extract + Write round-trip, all 4 games | Synthetic `.upd` (gzip+tar) |
| Spooky Pinball | Extract + Write round-trip for `.ed`, `.scooby`, `.looney`, P3 `.zip`, `.pkg` (RM, AC) | Synthetic format-correct files; AES rounds use the known plugin keys |
| Williams (WPC) | Static extract end-to-end on Fish Tales + Attack From Mars; per-game switch-profile + game-script contract validation across all 41 titles | Synthetic ROM zips with valid WPC font/animation tables; PinMAME capture path needs libpinmame + a real ROM so it's `@pytest.mark.requires_libpinmame` and skipped in CI |

Plus: per-mfr contract validation (capabilities, prereqs, phase labels,
game lists), GUI smoke (picker, mfr switch, per-mfr log persistence,
Back navigation), and `detect()` against synthetic filenames.

[CI runs this matrix on every push + PR](.github/workflows/test.yml):

| Runner | gpg | Tk display |
|---|---|---|
| `ubuntu-latest` | apt | `xvfb-run` wraps pytest |
| `macos-latest` | brew | native |
| `windows-latest` | winget (GnuPG.GnuPG) | native |

Tests that need WSL or Docker (full Clonezilla / JJP extraction) are
marked `@pytest.mark.requires_wsl` / `requires_docker` and skip
automatically when those aren't available. Adding new manufacturers
should come with at least a detection test + a contract test in
[tests/](tests/).

## Building installers locally

### Windows

```powershell
# Requires: Python 3.10+ with tkinter, Inno Setup 6
installer\build.ps1
# Output: installer\Output\Pinball_Asset_Decryptor_vX.Y.Z_Windows.exe
```

### macOS

```bash
# Requires: Python 3.10+, brew install create-dmg
bash installer/build_macos.sh
# Output: installer/Output/Pinball_Asset_Decryptor_vX.Y.Z_macOS.dmg
```

### Linux

```bash
# Requires: Python 3.10+ with tkinter, wget (for appimagetool fetch)
#   apt-get install python3-tk wget
bash installer/build_linux.sh
# Output: installer/Output/Pinball_Asset_Decryptor_vX.Y.Z_Linux_x86_64.AppImage
```

CI does all three automatically on a `v*` tag push and uploads to a
GitHub release. See [.github/workflows/release.yml](.github/workflows/release.yml).

To cut a release: use the `/release` slash command in Claude Code
(`.claude/commands/release.md`), which bumps `__version__`, audits the
README for content drift, runs the test suite, commits, pushes,
tags, and publishes the GitHub release in the right order — designed
to never again ship a tag where `__version__` lags the tag string.

## License

[MIT](LICENSE).

Each upstream decryptor's reverse-engineering work is credited in its source
project; this is the unification layer.
