"""Stern Pinball manufacturer plugin (Spike 2 audio extract + replace).

The Spike 2 audio codec is fully reverse-engineered: every cat-0 sound decodes
from ``image.bin`` + ``game_real`` alone, and new audio re-encodes back in
bit-exact (size-neutral), mono and stereo, across all 32 codec scale-variants.
The engine drives the game firmware in an emulator (unicorn) to recover each
sound's per-position keystream, then inverts it analytically.

Audio here is NOT loose files inside the extract — it is packed/encoded inside
``image.bin`` — so this plugin uses a custom Extract (image.bin -> per-sound
.wav) + Write/Direct-SSD (edited .wav -> re-encode -> patch image.bin), not the
generic loose-file ``replace_audio`` tab (which only repacks .wav/.ogg the
normal Write copies verbatim).
"""

import os
import re
import sys

from ...core.ext4_grow import LOOP_PROBE
from ...core.registry import (Capabilities, Game, InputSpec, Manufacturer,
                              Prerequisite)
from ...core.transcribe import TranscribePipeline
from ...core.musicid import MusicIdPipeline
from ..pinmame_classic import capture as _wscapture
from ..pinmame_classic.formats import detect_game as _ws_detect
from ..pinmame_classic.games import GAME_DB as _PMC_GAME_DB
from .formats import (detect_game, detect_spike1_game, display_for_key,
                      spike1_display_for_key)
from .games import GAME_DB, SPIKE1_GAME_DB
from .pipeline import (Spike1ExtractPipeline, Spike1RevertPipeline,
                       Spike1WritePipeline, SternDirectSsdExtractPipeline,
                       SternDirectSsdWritePipeline, SternExtractPipeline,
                       SternFlashImagePipeline, SternRevertPipeline,
                       SternWritePipeline)

# Stern handles three hardware eras under one picker entry:
#   * "spike2"    — the modern SD-card games (image.bin audio + ext4 assets),
#                   the full extract / write / replace / Direct-SD surface.
#   * "spike1"    — the 2015-2016 DMD generation (WrestleMania … Ghostbusters):
#                   same image.bin idea but plaintext master directory and raw
#                   PCM sounds; audio extract + write (see spike1.py).
#   * "whitestar" — the classic 1999-2006 MAME-ROM games (Monopoly, Elvis,
#                   LOTR, Sopranos, etc.), shared with the PinMAME-capture
#                   pipeline the Data East / Sega entries use; capture-only.
# detect() reports the era of the loaded file; the GUI re-applies the
# capability-dependent layout when it changes (default era = spike2, so the
# Spike 2 flow is unchanged until a Spike 1 .iso / MAME .zip is loaded).
# SAM (2006-2014) is a planned fourth era (sam.c).
_WHITESTAR_DB = {k: v for k, v in _PMC_GAME_DB.items()
                 if v["manufacturer"] == "Stern"}

_SPIKE2_GAMES = tuple(
    Game(key=k, display=info["display"], manufacturer_key="stern",
         era="spike2")
    for k, info in GAME_DB.items())
_SPIKE1_GAMES = tuple(
    Game(key=k, display=info["display"], manufacturer_key="stern",
         era="spike1")
    for k, info in SPIKE1_GAME_DB.items())
_WHITESTAR_GAMES = tuple(sorted(
    (Game(key=k, display=v["display"], manufacturer_key="stern",
          notes=f"Whitestar {v['year']}", era="whitestar")
     for k, v in _WHITESTAR_DB.items()),
    key=lambda g: g.display.lower()))
_GAMES = _SPIKE2_GAMES + _SPIKE1_GAMES + _WHITESTAR_GAMES

# Capture-only capabilities for the Whitestar era (no write/replace/Direct-SD
# — you can't repack a MAME ROM; extraction is a libpinmame attract capture).
_WHITESTAR_CAPS = Capabilities(extract=False, capture=True)
# Spike 3 (Raspberry Pi CM4) is a preview: the ONLY thing wired is the OTP-key
# helper tab.  No extract, write or emulator yet - so its era shows just that
# one tab (the header pill carries a BETA badge).  See core.spike3 and
# gui/spike3_tab.py.
_SPIKE3_CAPS = Capabilities(extract=False, spike3_key=True)

# Spike 1: audio extract + write.  The master directory is plaintext and every
# sound is raw PCM, so no emulator/codec prerequisites; the surface is audio-
# only for now (the DMD-era display content is .spv/dot data — a future era
# upgrade, not a video/image replace tab).  Partition Explorer stays off: the
# game data lives on a *logical* partition, which the explorer doesn't
# enumerate yet.
_SPIKE1_CAPS = Capabilities(
    extract=True,
    write=True,
    modpack=True,
    replace_audio=True,
    audio_level_offset=True,
    flash_image=True,
    # Emulate tab (its OWN flag, era-gated — the Spike 2 ``emulate`` panel is a
    # different rig).  The static armel game now boots and renders its attract
    # to the DMD under tools/spike1_emu, so a tab that shows the running game is
    # worth surfacing (docs/architecture/spike1_emulation.md).  Windows/WSL only.
    emulate_spike1=True,
    # Default Settings tab: preset the game firmware's compiled operator-
    # adjustment DEFAULTS (free play, volume, replay levels, …) inside a card
    # image.  Same model as Spike 2 (settings live in board NVRAM; the card
    # holds the compiled default a fresh flash / factory reset copies in) —
    # decoded/patched by spike1_adjustments over the game ELF, which
    # spike1.read_game_elf / write_game_elf_defaults pull from and write back
    # into the card.  The tab shows the full "all settings" list (Spike 1 has
    # no curated-units / menu-visibility layer yet).
    settings_editor=True,
    # read_card_image stays off: the Save-card-as-image button lives inside
    # the Direct-SD drive row, which only renders with direct_ssd — declaring
    # it here would advertise a control the era can't reach.  Both come on
    # together when Spike 1 Direct-SD is wired up.
    transcribe=True,
    music_id=True,
    audio_duration_names=True,
)
_SPIKE1_PREREQS = (
    Prerequisite(name="numpy", where="host",
                 probe="python:numpy",
                 reason="Audio sample math for the Write's resample / "
                        "loudness fit.",
                 install_hint="pip install numpy"),
    Prerequisite(name="faster-whisper", where="host",
                 probe="python:faster_whisper",
                 reason="Auto-transcribe spoken callouts to name the WAVs.",
                 install_hint="pip install faster-whisper"),
    Prerequisite(name="ffmpeg", where="host",
                 probe="ffmpeg -version",
                 reason="Convert replacement audio to WAV + match sample "
                        "rate (optional).",
                 install_hint=(
                     "winget install Gyan.FFmpeg  (Windows)\n"
                     "brew install ffmpeg          (macOS)\n"
                     "apt-get install ffmpeg       (Linux)")),
)
_WHITESTAR_PREREQS = (
    Prerequisite(name="ffmpeg", where="host", probe="ffmpeg -version",
                 reason="Rendering the captured DMD animations into MP4s.",
                 install_hint=(
                     "winget install Gyan.FFmpeg  (Windows)\n"
                     "brew install ffmpeg          (macOS)\n"
                     "apt-get install ffmpeg       (Linux)")),
)

_EXT4_GROW_REASON = (
    "Full-size video replacement, the opt-in blip-free callouts, and "
    "different-size file swaps in the Partition Explorer: resizes files "
    "inside the card's ext4 partition through the platform's Linux "
    "filesystem path. Without it an oversized replacement clip is crushed "
    "into its stock byte slot instead of going on at full quality, and a "
    "Partition Explorer replacement has to match the original's size "
    "exactly.")


def _ext4_grow_prereqs(platform):
    """The platform dependency of :mod:`...core.ext4_grow` — what full-size
    video replacement and the (now opt-in) blip-free cave ride on.  It became
    load-bearing for AUDIO quality the moment the blip-free cave started
    growing ``game_real``, but was never declared, so the strip said "All
    prerequisites OK" on machines whose every build was quietly falling back
    to the scrap-remains build — a tester burned two hardware tests that way
    (Elvira spinner, 2026-07-30).  Blip-free going opt-in in v0.104.0 takes
    the audio half of that off the default path, but does not retire the
    declaration: video still needs it, and a build that opts back in still
    falls back silently without it.  Missing is not fatal (the build still
    degrades gracefully and the completion dialog now says so); declaring it
    makes the gap visible BEFORE a card is built and tested.

    Windows needs a WSL2 distro reachable as root **that can hand out loop
    devices** — the probe is ``ext4_grow.LOOP_PROBE``, the exact capability
    the write path's mount script opens with.  It used to be ``echo ok``
    (mirroring ``WslExecutor.check_available``), which a WSL 1 distro passes
    as root while owning zero loop devices: the strip said OK on a machine
    where every grow failed with a bare losetup error, after the card's
    .sidx had already been rewritten (PAD-13, a 489-video write that shipped
    nothing).  macOS needs e2fsprogs' ``debugfs`` (probed in the same
    keg-only locations ``ext4_grow._find_e2fsprogs`` searches); native Linux
    mounts ext4 itself — nothing to declare."""
    if platform == "win32":
        return (
            Prerequisite(name="WSL2", where="wsl", probe=LOOP_PROBE,
                         reason=_EXT4_GROW_REASON,
                         install_hint=(
                             "wsl --install -d Ubuntu  "
                             "(admin PowerShell, then reboot)\n"
                             "Installed, but a loop-device error? That "
                             "distro is WSL 1, which can't mount card "
                             "images:\n"
                             "wsl -l -v   (look at VERSION)\n"
                             "wsl --set-version <name> 2")),
        )
    if platform == "darwin":
        return (
            Prerequisite(
                name="e2fsprogs", where="host",
                probe="test -x /opt/homebrew/opt/e2fsprogs/sbin/debugfs || "
                      "test -x /usr/local/opt/e2fsprogs/sbin/debugfs || "
                      "test -x /opt/local/sbin/debugfs || "
                      "command -v debugfs",
                reason=_EXT4_GROW_REASON,
                install_hint="brew install e2fsprogs"),
        )
    return ()


_EXT4_GROW_PREREQS = _ext4_grow_prereqs(sys.platform)


class SternManufacturer(Manufacturer):
    key = "stern"
    display = "Stern Pinball"
    games = _GAMES
    # Spike 2 modding flow: Extract decodes image.bin -> per-sound .wav; Write
    # re-encodes edited .wav back into image.bin (size-neutral) and patches the
    # image.  The Direct path reads/writes the game SD card directly (Spike 2
    # stores its code + assets on an SD card).  NOTE: the framework names this
    # capability ``direct_ssd`` generically (= "physically-connected drive");
    # for Spike 2 that drive is an SD card, so all UI wording says "SD card".
    # NOTE: ``capabilities`` is an era-aware @property below — this is the
    # Spike-2-era value it returns by default.
    _SPIKE2_CAPS = Capabilities(
        extract=True,
        write=True,
        modpack=True,
        direct_ssd=True,
        # Spike 2 is the era whose Emulate tab is wired: an armhf Linux ELF
        # under qemu-user with every peripheral replaced by an LD_PRELOAD
        # shim.  Spike 1 now has a rig too (tools/spike1_emu, see
        # docs/architecture/spike1_emulation.md) — its static armel binary
        # boots to hardware-init under qemu-user, but its device model needs a
        # privileged host setup, so no GUI tab is surfaced yet (a tab that
        # starts nothing is worse than no tab).  Spike 3 is its own era (a BETA
        # OTP-key preview - see _SPIKE3_CAPS), not a rider here.
        emulate=True,
        # Item 90: the Multi-boot tab - one SD card, several images, a menu at
        # power-up.  Spike 2 only: the layout (the extra images' partition
        # appended as p7, the selector injected into p2) is this era's.
        multiboot=True,
        # Audio is loose per-sound idxNNNN.wav in the extract output, so the
        # per-slot Replace Audio tab works: assignments are staged over those
        # WAVs and the Write pipeline re-encodes the changed ones into image.bin
        # (only the changed ones — Write diffs against .checksums.md5).
        replace_audio=True,
        # …and per slot, a loudness offset for that one replacement: the
        # encoder gains every replacement to the level of the sound it
        # replaces, so without this the only lever is build-wide and music
        # cannot be lifted without lifting the callouts with it.
        audio_level_offset=True,
        # Video is loose H.264 .asset clips copied out to video/ (named from
        # scene.radium).  The Replace Video tab stages a replacement over each,
        # and Write patches it back into the SD-card image IN PLACE via the
        # ext4 file->disk map (size-neutral: the .asset isn't resized, so a
        # replacement is fit to the original's byte size — padded if smaller,
        # re-encoded down if larger, skipped if it still won't fit).
        replace_video=True,
        # Images are loose .png files on the card (UI art); the Replace Image
        # tab stages a replacement scaled to the original's dimensions, and
        # Write patches it back in place the same size-neutral way as video.
        replace_image=True,
        # Flash a pre-built SD-card image (.img/.raw) straight onto a card from
        # the GUI — a dd-style whole-image write, so users no longer need a
        # separate imaging tool (and the built-in size guard refuses an image
        # too big for the card, the failure a tester hit externally).
        flash_image=True,
        # …and the other direction: save the whole card to a .raw image file, so
        # a stock card can be backed up before modding and two dumps of the same
        # card can be diffed on the Compare tab (a tester wanted to see where
        # the machine stores a setting he changed on the machine itself).
        read_card_image=True,
        # On-screen LCD text lives in the .radium scene files; Extract pulls the
        # editable display strings out to text/strings.tsv, the Replace Text tab
        # lets the user edit them, and Write patches every matching occurrence
        # back into its radium in place (size-neutral: a replacement is padded
        # to the original's byte length, and one that's longer is rejected).
        replace_text=True,
        # Mod transfer: Stern ships frequent code updates that re-lay-out the
        # card, so the Mod Pack tab's "Transfer Mods to New Version" section lets
        # a user carry their Replace edits from an old extract to a new one
        # (audio matched by sound content, since idxNNNN indices can shift).
        mod_transfer=True,
        # Partition Explorer: browse a raw card image's partitions + ext4 tree
        # read-only and extract files/folders — pull radium/.sh files out of an
        # old modded card or dump folders to diff vs stock (a tester).
        partition_explorer=True,
        # Settings editor: decode the game firmware's compiled operator-
        # adjustment defaults (free play, volume, pricing, …) and preset them
        # for a fresh-flash / factory-reset machine (a tester).
        settings_editor=True,
        # Compare: diff two card images — releases, or mod vs stock — by the
        # cards' own validation digests + firmware tables, no Extract needed
        # (a tester's wish list).
        compare=True,
        # Auto-transcribe: TMNT is full of spoken callouts; faster-whisper
        # (+VAD, which skips the music/SFX beds) renames voice WAVs by their
        # spoken text, keeping the idx prefix so Write still round-trips.
        transcribe=True,
        # Music ID: the jukebox song->index binding is unrecoverable from the
        # firmware (it lives in runtime game-rule logic), but band pins play
        # commercial recordings — so identify each full music track online via
        # AcoustID + MusicBrainz and name it by song (preferring the pin's band).
        music_id=True,
        # Length-prefix names: Spike 2 sounds are named only by master-dir
        # index, and indexes shift between firmware versions — a play-length
        # prefix gives users a sort key that survives updates (a tester).
        audio_duration_names=True,
        # Per-type Extract checkboxes (default all on): audio decode is the slow
        # part (~minutes) and images now include hundreds of scene textures, so
        # let the user skip categories they don't need for a faster extract.
        extract_categories=(("audio", "Audio"), ("video", "Video"),
                            ("images", "Images"), ("text", "Text")),
    )
    # Accepts Spike 2 / Spike 1 SD-card images AND classic Whitestar MAME ROM
    # zips; detect() routes by signature + extension and reports the era.
    input_spec = InputSpec(
        label="Stern SD-card image (Spike 2 / Spike 1) or MAME ROM zip "
              "(Whitestar)",
        extensions=(".img", ".bin", ".raw", ".iso", ".zip"),
    )
    _SPIKE2_EXTRACT_PHASES = ("Detect", "Locate partitions", "Extract video",
                              "Extract images", "Decode audio", "Checksums")
    _SPIKE1_EXTRACT_PHASES = Spike1ExtractPipeline.PHASES
    _SPIKE2_WRITE_PHASES = ("Detect", "Stage", "Re-encode", "Patch image")
    _SPIKE1_WRITE_PHASES = Spike1WritePipeline.PHASES
    transcribe_phases = ("Load model", "Transcribe", "Rename", "Write CSV")
    music_id_phases = ("Scan", "Identify", "Write CSV")
    # Direct-SD extract drives the same engine phases as the file Extract (its
    # phase indices 2-5 must line up), with phase 0/1 reworded for the card.
    direct_ssd_extract_phases = ("Read SD card", "Locate partitions",
                                 "Extract video", "Extract images",
                                 "Decode audio", "Checksums")
    direct_ssd_write_phases = ("Scan", "Re-encode audio", "Write to SD card")
    flash_phases = ("Check card", "Write image", "Verify card", "Flush")

    #: ...and the same four for a MENU-ONLY write, named for what they really
    #: do there: the check is "is this the card this image was flashed from",
    #: and the write is one partition, not the image.
    menu_flash_phases = ("Check the card", "Write the menu", "Verify", "Flush")
    # "Revert all changes" fallback: re-derive originals with no .orig snapshot
    # straight from the source card.
    revert_phases = ("Read source", "Restore")
    # The decode/replace engine emulates the ARM game firmware via unicorn.
    _SPIKE2_PREREQS = (
        Prerequisite(name="unicorn", where="host",
                     probe="python:unicorn",
                     reason="Emulates the Spike firmware to recover the audio "
                            "codec keystream (decode + re-encode).",
                     install_hint="pip install unicorn"),
        Prerequisite(name="numpy", where="host",
                     probe="python:numpy",
                     reason="Audio sample math for decode / encode.",
                     install_hint="pip install numpy"),
        Prerequisite(name="capstone", where="host",
                     probe="python:capstone",
                     reason="Locates the codec's companding point to recover "
                            "the keystream when re-encoding replaced audio.",
                     install_hint="pip install capstone"),
        # Platform ext4-grow path (WSL2 / e2fsprogs) — needed by blip-free
        # callouts and full-size video replacement; absent on native Linux
        # (see _ext4_grow_prereqs).
        *_EXT4_GROW_PREREQS,
        # Optional — only the Auto-transcribe action needs it; extract/write
        # work without it.
        Prerequisite(name="faster-whisper", where="host",
                     probe="python:faster_whisper",
                     reason="Auto-transcribe spoken callouts to name the WAVs.",
                     install_hint="pip install faster-whisper"),
        # Optional — Replace Audio/Video swap files already in the game's
        # format (wav/ogg) without it; ffmpeg is only needed to convert other
        # formats (mp3/flac/m4a/mp4...) or match the original's sample rate.
        # The Windows build bundles it (imageio-ffmpeg) and startup puts it on
        # PATH, so this normally shows green out of the box; on Mac/Linux the
        # frozen bundle does too.
        Prerequisite(name="ffmpeg", where="host",
                     probe="ffmpeg -version",
                     reason="Convert replacement audio/video to the game's "
                            "format + match sample rate (optional).",
                     install_hint=(
                         "winget install Gyan.FFmpeg  (Windows)\n"
                         "brew install ffmpeg          (macOS)\n"
                         "apt-get install ffmpeg       (Linux)")),
    )
    # Spike 2 ships on an SD card (not an ISO/SSD), so the source/destination
    # toggle reads in those terms (see Manufacturer defaults).
    extract_iso_label = "From SD-card image"
    extract_ssd_label = "From SD card"
    write_iso_label = "Build SD-card image"
    write_ssd_label = "Write to SD card"
    # ``extract_input_label`` is an era-aware @property below (Spike 2 = raw
    # SD-card image, Whitestar = MAME ROM zip), so the input-field label isn't
    # hardcoded to either medium.
    # No picker-card corner badge: the card spans multiple eras (Spike 2 +
    # Whitestar), so a single "SPIKE 2" pill there would misrepresent it — the
    # working-view header era switcher shows the eras instead.
    # Hardware eras, surfaced as a segmented pill switcher in the working-view
    # header so the user picks the era explicitly (which makes the input field
    # single-mode per era — Card image vs ROM zip — instead of multi-modal).
    # A 3rd tuple element is an optional corner badge on that pill (the GUI's
    # _build_era_badges renders it) — "BETA" on Spike 3 so nobody mistakes the
    # key-extraction preview for finished support.
    eras = (("spike2", "SPIKE 2"), ("spike1", "SPIKE 1"),
            ("whitestar", "WHITESTAR"), ("spike3", "SPIKE 3", "BETA"))
    # Mirror the destination radio so the action button names what it does
    # (the generic "Build update" / "Apply Modifications" don't connect to
    # the SD-card wording above them).
    write_build_button = "Build SD-card image"
    write_direct_button = "Write to SD card"
    direct_medium_noun = "SD card"
    # The card is small removable media in a reader — bias the picker away
    # from large backup drives (see core.drives.pick_best_game_ssd).
    direct_target_kind = "sd_card"
    # Spike 1 cards ship (and build) as .iso, so the flash picker must not
    # filter the era's own extension away.
    flash_image_filetypes = (("SD-card image", "*.img *.raw *.bin *.iso"),
                             ("All files", "*.*"))
    direct_safety_text = (
        "⚠ Power off the machine and remove the SD card before connecting "
        "it to this PC. Always keep a backup image of the original card.")
    # Built images get a distinct default name (…-modified.raw) so they can't
    # be mistaken for the stock image in the same folder (a tester 5).  Safe
    # here: the flashed card doesn't care what the image file was called.
    write_output_suffix = "-modified"

    # ------------------------------------------------------------------
    # Era-aware surface (Spike 2 SD-card vs Whitestar MAME capture)
    # ------------------------------------------------------------------

    def __init__(self):
        # Default to Spike 2 so the shipped flow is unchanged until a MAME
        # .zip is detected.  ``set_era`` is driven by the GUI off detect().
        self._era = "spike2"

    def set_era(self, era):
        self._era = era if era in ("whitestar", "spike1", "spike3") \
            else "spike2"

    @property
    def current_era(self):
        return self._era

    @property
    def capabilities(self):
        if self._era == "whitestar":
            return _WHITESTAR_CAPS
        if self._era == "spike1":
            return _SPIKE1_CAPS
        if self._era == "spike3":
            return _SPIKE3_CAPS
        return self._SPIKE2_CAPS

    @property
    def prerequisites(self):
        if self._era == "whitestar":
            return _WHITESTAR_PREREQS
        if self._era == "spike1":
            return _SPIKE1_PREREQS
        if self._era == "spike3":
            # The Spike 3 key tools are pure Python (only zstandard, already a
            # project dependency), so the era demands nothing of the host.
            return ()
        return self._SPIKE2_PREREQS

    @property
    def extract_phases(self):
        if self._era == "whitestar":
            return _wscapture.PHASES
        if self._era == "spike1":
            return self._SPIKE1_EXTRACT_PHASES
        return self._SPIKE2_EXTRACT_PHASES

    @property
    def write_phases(self):
        return self._SPIKE1_WRITE_PHASES if self._era == "spike1" \
            else self._SPIKE2_WRITE_PHASES

    @property
    def capture_phases(self):
        return _wscapture.PHASES

    @property
    def extract_input_label(self):
        # The input medium differs by era, so the field label can't say
        # "Card image" universally: Spike 2 loads a raw SD-card image, Whitestar
        # loads a MAME ROM zip.  Reads better than the bare ".img:"/".zip:" the
        # raw extension would otherwise produce.
        return "ROM zip" if self._era == "whitestar" else "Card image"

    def write_output_ext(self):
        # Spike 2 ships on a raw SD-card image, so a built image must be ".raw"
        # for the user's flashing tools (and the app's own re-detect) — regard-
        # less of whether the original was named .img/.bin/.raw.  Spike 1
        # updates ship as ".iso" (still a raw MBR image), so a built Spike 1
        # card keeps that extension.  Whitestar is MAME capture-only (no
        # build), so it pins nothing.
        if self._era == "spike1":
            return ".iso"
        return ".raw" if self._era == "spike2" else ""

    def audio_forces_length_match(self, assets_dir=None):
        # Spike audio (both generations) is a size-neutral in-place patch:
        # each sound is fit to its original slot length (longer trimmed,
        # shorter padded) and the body is written back in place — keeping a
        # different length would strand every following offset in image.bin.
        # So trim/pad is mandatory, not a user choice: the GUI forces the
        # checkbox on and disables it.
        return True

    def audio_length_note(self):
        if self._era == "spike1":
            return ("Replacements are patched in place as raw PCM: each "
                    "sound is fit to its original slot length (longer is "
                    "trimmed, shorter padded with silence) and loudness-"
                    "matched to the original (soft-limited).")
        return ("Replacements are encoded size-neutral: each sound is fit to "
                "its original slot length (longer is trimmed, shorter padded "
                "with silence) and amplitude-limited into the codec's range.")

    def video_length_note(self):
        return ("Video is patched into the SD-card image in place, so each "
                "replacement is fit to its original clip's byte size: a small "
                "enough clip drops straight in, a larger one is automatically "
                "re-encoded down to fit, and one that still won't fit is "
                "skipped (left unchanged) — use a shorter / lower-resolution "
                "clip. Tick “Trim / pad” to also match the original length.")

    def image_note(self):
        # No inline note — the auto-fit / per-store fitting rules live in the
        # "?" help window (a tester: the tab read as cluttered; the earlier
        # one-line summary went too).
        return ""

    def detect(self, path):
        # Route by signature + extension: MAME ROM zip => classic Whitestar
        # (capture era); Spike 2 partition shape => spike2; Spike 1 partition
        # shape (Stern's .iso updates, or a card dump) => spike1.  detect()
        # has no side effects (it's also called to probe other manufacturers)
        # — the era it reports on the Game is applied to the live
        # manufacturer by the GUI.
        if path.lower().endswith(".zip"):
            key = _ws_detect(path, _WHITESTAR_DB)
            if key is None:
                return None
            info = _WHITESTAR_DB[key]
            return Game(key=key, display=info["display"],
                        manufacturer_key="stern", era="whitestar",
                        notes=f"Whitestar {info['year']}, {info['dmd']} DMD")
        key = detect_game(path)
        if key is not None:
            return Game(key=key, display=display_for_key(key, path),
                        manufacturer_key="stern", era="spike2",
                        notes="Spike 2 card image")
        key = detect_spike1_game(path)
        if key is not None:
            return Game(key=key, display=spike1_display_for_key(key, path),
                        manufacturer_key="stern", era="spike1",
                        notes="Spike 1 card image")
        return None

    def title_caption(self, path, game):
        # "Led Zeppelin v1.22 LE", not "Led Zeppelin (Spike 2) — Spike 2 card
        # image": the title bar identifies the game; the era pill already says
        # Spike 2 (feedback batch 20).  Version + edition parse straight off
        # Stern's vendor filename — cheap enough for the Tk thread; a renamed
        # card just shows the bare title.
        # DELIBERATELY the filename, unlike info.resolve_version (which reads
        # the card's own update index and outranks the name).  This runs on the
        # Tk thread on every card pick, and the index costs an ext4 mount plus
        # a directory walk — seconds on a multi-GB card, which is why the Info
        # window probes on a worker with a spinner.  So a relabelled card can
        # show one version here and the true one in Image Info; Image Info is
        # the place that reports it as a fact, and it names the source it used.
        disp = re.sub(r"\s*\((?:Spike [12]|Whitestar[^)]*)\)$", "",
                      game.display)
        if game.era == "spike2":
            from .info import version_from_filename
            version, edition = version_from_filename(path)
            if version:
                disp += " v%s" % version
            if edition:
                disp += " %s" % edition
        elif game.era == "spike1":
            # Spike 1 updates are named "<TITLE>_<EDITION>-<V>_<vv>[_p].iso"
            # (GOT_LE-1_37.iso -> v1.37 LE); a renamed card shows bare title.
            m = re.match(r"(.+?)-(\d+(?:_\d+)+)", os.path.basename(path))
            if m:
                disp += " v%s" % m.group(2).replace("_", ".")
                em = re.search(r"_(le|pro|se)$", m.group(1).lower())
                if em:
                    disp += " %s" % em.group(1).upper()
        elif game.era == "whitestar" and game.notes:
            disp += " (%s)" % game.notes
        return disp

    def image_info(self, path, assets_dir=None):
        # Only the Spike 2 card probe — a Whitestar MAME zip or Spike 1 card
        # gets just the generic File/Detection sections (the Spike 2 probe
        # reads the card through the primary-partition explorer, which a
        # Spike 1 card's logical layout would only confuse).  Route on the
        # file, not the era pill, so the Info tab matches whatever image is
        # actually selected.
        if path.lower().endswith(".zip"):
            return []
        if detect_spike1_game(path) is not None:
            return []
        from .info import card_info
        return card_info(path)

    def card_version(self, path):
        """``(version, exact)`` — the build a card image really is, read
        from its own update index (see info.card_version_probe).  Opens the
        image: call off the UI thread."""
        from .info import card_version_probe
        return card_version_probe(path)

    def compare_images(self, path_a, path_b, assets_a=None, assets_b=None):
        # Spike 2 cards only — a Whitestar MAME zip has no manifest/firmware
        # to diff, and the Spike 1 comparer isn't built yet, so refuse with a
        # plain explanation instead of a stack.
        if path_a.lower().endswith(".zip") or path_b.lower().endswith(".zip"):
            return [("Error", [("Compare", "Whitestar ROM zips can't be "
                                "compared — pick two Spike 2 card images.")])]
        if (detect_spike1_game(path_a) is not None
                or detect_spike1_game(path_b) is not None):
            return [("Error", [("Compare", "Spike 1 cards can't be compared "
                                "yet — pick two Spike 2 card images.")])]
        from .compare import compare_cards
        return compare_cards(path_a, path_b, assets_a, assets_b)

    def extract_report_file(self, image_path, ref, out_dir):
        from .compare import extract_ref
        return extract_ref(image_path, ref, out_dir)

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              extract_categories=None, duration_names=False):
        if self._era == "spike1":
            return Spike1ExtractPipeline(
                input_path, output_dir, log_cb, phase_cb, progress_cb,
                done_cb, extract_categories=extract_categories,
                duration_names=duration_names)
        return SternExtractPipeline(
            input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            extract_categories=extract_categories,
            duration_names=duration_names)

    def make_capture_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              **kwargs):
        # Whitestar era: libpinmame attract-mode DMD capture (same as the
        # Data East / Sega entries).
        return _wscapture.CapturePipeline(
            input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            game_db=_WHITESTAR_DB,
            duration_seconds=kwargs.get("duration_seconds", 180.0),
            frame_cb=kwargs.get("frame_cb"),
            capture_ready_cb=None)

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        if self._era == "spike1":
            return Spike1WritePipeline(
                original_path, assets_dir, output_path,
                log_cb, phase_cb, progress_cb, done_cb)
        return SternWritePipeline(
            original_path, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb)

    def make_direct_ssd_extract_pipeline(
            self, device_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None, extract_categories=None,
            duration_names=False):
        return SternDirectSsdExtractPipeline(
            device_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override,
            extract_categories=extract_categories,
            duration_names=duration_names)

    def make_direct_ssd_write_pipeline(
            self, device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        return SternDirectSsdWritePipeline(
            device_path, assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override)

    def make_flash_pipeline(self, image_path, device_path,
                            log_cb, phase_cb, progress_cb, done_cb,
                            menu_only=False):
        return SternFlashImagePipeline(
            image_path, device_path, log_cb, phase_cb, progress_cb, done_cb,
            menu_only=menu_only)

    def make_revert_pipeline(self, source, assets_dir, rels,
                             log_cb, phase_cb, progress_cb, done_cb,
                             is_device=False, partition_override=None):
        """Build the fallback pipeline that re-derives pre-snapshot originals
        from the source card (the GUI calls this only for changed files with no
        ``.orig`` snapshot)."""
        if self._era == "spike1":
            return Spike1RevertPipeline(
                source, assets_dir, rels, log_cb, phase_cb, progress_cb,
                done_cb, is_device=is_device,
                partition_override=partition_override)
        return SternRevertPipeline(
            source, assets_dir, rels, log_cb, phase_cb, progress_cb, done_cb,
            is_device=is_device, partition_override=partition_override)

    def make_transcribe_pipeline(self, assets_dir,
                                 log_cb, phase_cb, progress_cb, done_cb,
                                 rename_after=False, model_size="tiny.en"):
        return TranscribePipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after, model_size=model_size)

    def make_music_id_pipeline(self, assets_dir,
                               log_cb, phase_cb, progress_cb, done_cb,
                               rename_after=False):
        return MusicIdPipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after)

    def extract_input_help(self):
        if self._era == "spike1":
            return ("Select a Stern Spike 1 SD-card image — Stern's update "
                    ".iso files are raw card images and work directly. "
                    "Extract decodes every packed sound in image.bin to a "
                    "per-sound WAV (audio/). Tick Auto-transcribe to rename "
                    "voice callouts by their spoken text.")
        return ("Select a Stern Spike 2 SD-card image (raw .img/.bin), or use "
                "the Direct SD option to read the card itself. Extract decodes "
                "its packed audio to per-sound WAVs (audio/) and copies out the "
                "LCD videos (video/). Tick Auto-transcribe to rename voice "
                "callouts by their spoken text.")
