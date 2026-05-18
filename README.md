# Pinball Asset Decryptor

One app to extract, view, and modify game assets from pinball machines made
by **Barrels of Fun**, **Jersey Jack Pinball**, **Pinball Brothers**, and
**Spooky Pinball** — 32 games across four manufacturers.

This is a unified replacement for four separate decryptor apps that all shared
the same Tk GUI shell, queue-based pipeline contract, checksum tracking,
and mod-pack workflow. Each manufacturer is a plugin under
[pinball_decryptor/plugins/](pinball_decryptor/plugins/); the shared shell
lives in [pinball_decryptor/core/](pinball_decryptor/core/) and
[pinball_decryptor/gui/](pinball_decryptor/gui/).

## Supported manufacturers

| Manufacturer | Games | Input formats | Capabilities |
|---|---|---|---|
| **Barrels of Fun** | 3 (Labyrinth, Dune, Winchester) | `.fun` | Extract, Write, Mod Pack |
| **Jersey Jack Pinball** | 11 (Wonka, GnR, Hobbit, Wizard of Oz, Avatar, etc.) | `.iso` | Extract, Write, Mod Pack |
| **Pinball Brothers** | 4 (ABBA, Alien, Queen, Predator) | `.upd`, `.iso` (Clonezilla) | Extract, Write, Apply Delta, Mod Pack |
| **Spooky Pinball** | 14 (Beetlejuice, Evil Dead, R&M, Halloween, Looney Tunes, etc.) | `.pkg`, `.ed`, `.scooby`, `.beetlejuice`, `.looney`, `.iso`, `.zip` | Extract, Write, Mod Pack |

The full per-game lists with the format-specific quirks live in the plugin
sources:
[bof/games.py](pinball_decryptor/plugins/bof/games.py),
[jjp/games.py](pinball_decryptor/plugins/jjp/games.py),
[pb/games.py](pinball_decryptor/plugins/pb/games.py),
[spooky/games.py](pinball_decryptor/plugins/spooky/games.py).

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

Download the latest `Pinball_Asset_Decryptor_v*_macOS.dmg` from the
[Releases page](https://github.com/davidvanderburgh/pinball-asset-decryptor/releases),
open it, and drag the app to `/Applications`.

For Spooky and JJP Clonezilla extraction you'll also need Docker Desktop
(the app builds and uses an ephemeral container for partclone / debugfs).

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

| Manufacturer | Host-side (Windows) | WSL-side (Ubuntu) / Linux apt |
|---|---|---|
| Barrels of Fun | – | gnupg, tar |
| Jersey Jack Pinball | – | partclone, e2fsprogs/debugfs, xorriso, pigz, ffmpeg, python3-zstandard |
| Pinball Brothers | – | `e2fsprogs/debugfs` *(only for `.iso` Clonezilla)* |
| Spooky Pinball | GnuPG (gpg.exe), ffmpeg | partclone, e2fsprogs/debugfs, zstd + python3-zstandard |

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
│   ├── bof/                      # Barrels of Fun
│   ├── jjp/                      # Jersey Jack Pinball (+ private Docker)
│   ├── pb/                       # Pinball Brothers
│   └── spooky/                   # Spooky Pinball (+ private Docker)
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
| Jersey Jack | Detection + write-output-rename wrapper | Full Extract needs WSL + real ISO (gigabytes), not testable in CI |
| Pinball Brothers | Extract + Write round-trip, all 4 games | Synthetic `.upd` (gzip+tar) |
| Spooky Pinball | Extract + Write round-trip for `.ed`, `.scooby`, `.looney`, P3 `.zip`, `.pkg` (RM, AC) | Synthetic format-correct files; AES rounds use the known plugin keys |

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

To cut a release:

```bash
# Bump pinball_decryptor/__init__.py to the new version, then:
git tag vX.Y.Z
git push origin vX.Y.Z
```

## License

[MIT](LICENSE).

Each upstream decryptor's reverse-engineering work is credited in its source
project; this is the unification layer.
