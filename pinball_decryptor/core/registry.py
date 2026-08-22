"""Manufacturer plugin registry.

Each plugin module under :mod:`pinball_decryptor.plugins` defines a
:class:`Manufacturer` subclass and calls :func:`register_manufacturer` at
import time.  :func:`load_plugins` imports every known plugin so its
``register()`` runs.
"""

import importlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .config import EXTRACT_PHASES, WRITE_PHASES
from .pipeline_base import ReadCardPipeline
from .prereqs import Prerequisite  # re-exported for plugins

# Plugins are imported in this order at startup.  Order drives the
# dropdown ordering; auto-detect tries them in this sequence too.
_PLUGIN_MODULES = [
    "pinball_decryptor.plugins.pb",
    # AP must precede spooky: AP's detector is key-validated (only claims
    # .pkg files that decrypt to a ZIP with the AP key), while spooky's
    # generic AES-magic fallback would otherwise grab AP packages first.
    "pinball_decryptor.plugins.ap",
    "pinball_decryptor.plugins.spooky",
    "pinball_decryptor.plugins.bof",
    "pinball_decryptor.plugins.jjp",
    "pinball_decryptor.plugins.cgc",
    "pinball_decryptor.plugins.williams",
    "pinball_decryptor.plugins.pinmame_classic",
    "pinball_decryptor.plugins.dp",
    "pinball_decryptor.plugins.stern",
]


# ---------------------------------------------------------------------------
# Data classes describing what a plugin exposes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Game:
    key: str               # "alien", "halloween", ...
    display: str           # "Alien", "Halloween", ...
    manufacturer_key: str  # "pb", "spooky", ...
    notes: str = ""        # optional UI-visible hint shown in detect badge
    # Optional sub-format/era discriminator for manufacturers that handle
    # multiple hardware generations under one picker entry (e.g. Stern:
    # "spike2" SD-card images vs "whitestar"/"sam" MAME ROM zips).  The GUI
    # re-applies the capability-dependent layout when the detected era
    # differs from the manufacturer's current era.  Empty = single-era.
    era: str = ""
    # Whether decryption/extraction is currently possible at all.
    # Set False for games whose encryption key isn't known or whose
    # format isn't (yet) implemented — picker shows them greyed out
    # with a tooltip explaining the reason.
    supported: bool = True
    unsupported_reason: str = ""


@dataclass(frozen=True)
class Capabilities:
    """Which tabs / actions the GUI should expose for this manufacturer."""
    extract: bool = True
    write: bool = False
    modpack: bool = False
    apply_delta: bool = False
    iso: bool = False
    # Runtime-capture path: spawn an emulator (e.g. PinMAME via
    # libpinmame), capture composed DMD frames + audio while attract
    # mode plays, and emit per-cinematic MP4s.  Used by Williams.
    capture: bool = False
    # Emulate tab: run the manufacturer's OWN game binary on this PC under
    # qemu-user with LD_PRELOAD hardware shims, in a window, with sound and
    # keyboard input.  Unlike ``capture`` this is interactive and is NOT driven
    # by the image on the Input box — it runs a prepared root filesystem built
    # from a card image by the rig in ``tools/spike2_emu`` (see
    # gui/emulate_tab.py).  Used by Stern Spike 2.  Windows only in practice:
    # the rig runs inside WSL and draws through WSLg.
    emulate: bool = False
    # Emulate tab for Jersey Jack.  A SEPARATE flag from ``emulate`` rather
    # than a shared one, because ``emulate`` is read at exactly one place to
    # gate exactly one frame — two manufacturers setting it True would both
    # get the STERN panel.  The two rigs have almost nothing in common beyond
    # "runs inside WSL": JJP's game is a native x86-64 binary (no qemu-user,
    # no GL bridge, no video bridge) but it cannot run at all without the
    # purple Sentinel USB key, which supplies the AES key its code is
    # encrypted with.  See gui/jjp_emulate_tab.py and tools/jjp_emu.
    emulate_jjp: bool = False
    # Auto-transcribe path: run faster-whisper across the extracted
    # audio files and emit a ``callouts.csv`` mapping each WAV to its
    # spoken text (non-speech samples are skipped via VAD).  Used by
    # CGC where samples are numbered by index with no embedded names.
    transcribe: bool = False
    # Music-ID path: identify the extracted music WAVs online via AcoustID +
    # MusicBrainz (acoustic fingerprint -> title/artist) and name each by song.
    # For band pins (e.g. Stern Led Zeppelin) whose song->index binding is
    # unrecoverable from the firmware but whose music is a commercial recording.
    music_id: bool = False
    # Length-prefixed extract names: surfaces a "Length-prefix names" checkbox
    # on the Extract tab.  When ON, the plugin's extract leads each decoded
    # audio filename with its play length ("01m22s235 - idx0001.wav") so a
    # name sort orders by duration — durations are stable across firmware
    # versions while slot indexes shift, so this is how a modder lines up the
    # same sounds between two extracts (a tester).  app.py passes
    # ``duration_names`` (bool) to the extract factories.  Used by Stern
    # Spike 2, whose sounds are otherwise named only by index.
    audio_duration_names: bool = False
    # Direct-SSD path: read from / write to a physically-connected
    # game SSD instead of an ISO/file.  Surfaces a radio toggle on
    # the Extract / Write tabs swapping the file picker for a drive
    # picker + manual partition override.  Used by JJP.
    direct_ssd: bool = False
    # Dongle-decrypt path: surfaces a "Decrypt using the game's HASP dongle"
    # checkbox on the Extract tab (advanced).  When ticked, app.py routes the
    # ISO extract through the manufacturer's dongle factory instead of the
    # dongle-free one — the game binary is run under an LD_PRELOAD shim that
    # drives the game's OWN decryption via the plugged-in Sentinel/HASP key.
    # This is how a JJP title whose asset encryption isn't reverse-engineered
    # yet (e.g. Sonic) can still be extracted, provided the matching dongle is
    # present.  Windows/WSL only (needs usbipd USB passthrough).  Used by JJP.
    dongle_extract: bool = False
    # Per-category Extract filters: surfaces "Graphics" / "Sounds" /
    # "File System" checkboxes on the Extract tab.  Used by JJP where
    # the encrypted edata tree has two distinct asset categories and
    # a separately-toggled full filesystem dump.  When True, app.py
    # passes ``extract_graphics`` / ``extract_sounds`` / ``full_dump``
    # kwargs to the manufacturer's extract factories.
    asset_filters: bool = False
    # Per-type Extract selection: a tuple of ``(key, label)`` pairs the plugin's
    # Extract supports (e.g. ``(("audio","Audio"),("video","Video"),...)``).  When
    # non-empty the Extract tab shows a default-all-on checkbox per entry, and
    # app.py passes ``extract_categories={key: bool}`` to the extract factories so
    # the user can skip slow/unwanted categories.  Empty -> no checkboxes.
    extract_categories: tuple = ()
    # Update-version date field: surfaces an "Update version date" control
    # on the Write tab (an Auto checkbox + an editable YYYY.MM.DD entry).
    # Used by BOF, whose game only applies a .fun whose embedded version
    # date is newer than what's installed — the field lets the user see the
    # date Write will stamp and override it (e.g. to force-install official
    # code over a higher-dated mod).  When set, app.py passes
    # ``version_date_override`` (None in Auto mode) to make_write_pipeline.
    write_version_date: bool = False
    # Per-slot audio-loop injection: surfaces a "Loop" checkbox column on the
    # Replace Audio tab (one per track, defaulted ON for tracks whose name
    # contains "LOOP").  When a looped slot's replacement is repacked, the
    # inverse converter adds resource-level forward looping to it.  Used by
    # BOF: Dune plays its mode-music stems once (engine loop is off), so a
    # replacement shorter than the long original goes silent partway through a
    # mode; looping the clip fills the mode (the game's music system fades/
    # stops it on the next song change).  app.py passes the set of looped
    # slot filenames to make_write_pipeline as ``loop_names``.
    audio_loop_inject: bool = False
    # Per-slot "keep full length" override: surfaces a "Full" checkbox column on
    # the Replace-Audio tab.  Only meaningful for plugins that otherwise force a
    # length match (audio_forces_length_match), where it lets the user exempt
    # individual slots from the trim-to-original-length so a longer replacement
    # plays at its full length.  Used by JJP: its Write trims every track to the
    # original slot length by default, but a slot the game doesn't immediately
    # play another sound over (e.g. the end-of-game cue before attract) can hold
    # a longer track.  app.py passes the set of exempt slot paths to the write
    # pipeline as ``keep_full_length_names`` and to staging.
    audio_keep_length_override: bool = False
    # Optional WPC-DMD decode pass: surfaces a "Decode DMD scenes
    # (experimental, extract-only)" checkbox on the Extract tab.
    # When True, app.py passes ``decode_dmd`` to the extract factory.
    # Used by CGC's WPC remakes (MM/AFM/MB) — the bundled Williams
    # ROM is decoded into PNG scenes + MP4 animations + font sheets
    # under ``dmd/``.  Default OFF because the render is slow (a few
    # minutes) and the output isn't writable back to the eMMC.
    decode_dmd: bool = False
    # Chain-deltas-into-extract: surfaces an optional multi-file "updates
    # to apply on top" picker on the Extract tab.  The user supplies a full
    # image as the input plus the delta(s) needed; the extract auto-applies
    # them in version order so the output is a complete, up-to-date asset
    # set.  When True, app.py passes ``deltas`` (a list of paths) to the
    # extract factory.  Used by Dutch Pinball (The Big Lebowski).
    chain_deltas: bool = False
    # Replace-audio path: surfaces a "Replace Audio" tab that scans the
    # extracted assets folder for loose .wav/.ogg files, lists them as
    # named slots, and lets the user assign + preview a replacement track
    # per slot.  Assignments are format-matched to the original and staged
    # over the extracted files so the normal Write pipeline repacks them.
    # Set True only for plugins whose audio is loose .wav/.ogg in the
    # extract output (JJP, Spooky, American Pinball, Pinball Brothers,
    # Dutch Pinball) — not CGC (indexed sound banks) or BOF (Godot
    # .sample/.oggvorbisstr).
    replace_audio: bool = False
    # Replace-video path: surfaces a "Replace Video" tab that scans the
    # extracted assets folder for loose video files (.mp4/.mov/.webm/.ogv/…),
    # lists them as named slots, and lets the user assign + embedded-preview a
    # replacement clip per slot.  Assignments are re-encoded to the original's
    # container / codec / resolution (alpha preserved) and staged over the
    # extracted files so the normal Write pipeline repacks them.  Set True only
    # for plugins whose video is loose files Write actually round-trips — JJP
    # (loose containers), Dutch Pinball AAIW (.mp4/.mov; gated off for TBL,
    # whose .cdmd videos have no inverse encoder), and Spooky (the loose
    # video in the game tree, e.g. Halloween's 242 .webm).
    # NOT BOF (no .ogv->.ctex encoder yet) and NOT CGC/Williams (real-time
    # render, no video files to swap).
    replace_video: bool = False
    # Replace-image path: surfaces a "Replace Image" tab that scans the
    # extracted assets folder for loose image files (.png/.jpg/.bmp/…), lists
    # them as named slots with a thumbnail preview, and lets the user assign a
    # replacement per slot.  Assignments are scaled to the original's pixel
    # dimensions (via Pillow) and staged over the extracted files so the normal
    # Write pipeline repacks them.  Set True only for plugins whose images are
    # loose files Write round-trips — e.g. Stern Spike 2 (loose .png on the SD
    # card, patched in place size-neutral).
    replace_image: bool = False
    # Replace-text path: surfaces a "Replace Text" tab that loads the editable
    # on-screen-text manifest Extract produced (``<assets>/text/strings.tsv`` —
    # see core.text_manifest) and lets the user edit each player-facing display
    # string in place.  Edits are saved straight back to the manifest, and the
    # plugin engine patches every matching string size-neutral at Write time
    # (each replacement must fit its original's byte length).  Set True only for
    # plugins whose Extract writes that manifest — e.g. Stern Spike 2 (LCD text
    # in .radium scene files).
    replace_text: bool = False
    # Flash-image path: surfaces a "Flash image to SD card" action (a button on
    # the Write tab that opens a small dialog) for putting a pre-built image
    # onto a physical card/stick.  For Stern/CGC that is a dd-style raw
    # whole-image write of a ``.img``/``.raw``; for JJP the same surface
    # instead formats the USB stick FAT32/MBR and copies the installer ISO's
    # files onto it (the machine mounts the stick's FAT volume itself — a
    # raw-imaged stick is unreadable to it).  Distinct from the
    # asset-modifying Write/Direct-SD paths.  When True, the GUI calls
    # ``make_flash_pipeline`` and the ``flash_*`` wording attributes below
    # label the button/dialog; raw device writes need Administrator/root.
    flash_image: bool = False
    # Read-card path: surfaces a "Save card as image…" action on the Extract
    # tab's card row, dumping the whole physical card into a ``.raw`` file — the
    # exact inverse of ``flash_image``.  For backing a stock card up before
    # modding it, and for diffing a card against itself after a change made on
    # the machine (batch 33: the app could write a card but not read one, so
    # that round trip needed an outside imaging tool).  Set True only for
    # plugins whose medium IS a small raw whole-card image the app can hand
    # straight to its own Partitions / Compare tabs — Stern Spike 2 today.  Off
    # for JJP: its Direct medium is a multi-hundred-GB game SSD, and a sector
    # dump of one is neither practical nor useful to the rest of the flow.  The
    # button lives on the Extract tab's card row, so a plugin also needs
    # ``direct_ssd`` for it to surface.  The read itself is manufacturer-
    # agnostic (see core.pipeline_base.ReadCardPipeline); raw device reads need
    # Administrator/root, elevated per-run exactly like the flash.
    read_card_image: bool = False
    # Mod-transfer path: surfaces a "Transfer Mods to New Version" section on the
    # (shared) Mod Pack tab that pulls a user's pending Replace edits from an OLD
    # extract folder onto the current new-version one, reconciling layout changes
    # (see core.mod_transfer).  Set True only for plugins where a new firmware
    # version ships a re-laid-out card and mods are worth carrying over — Stern
    # Spike 2, whose audio is index-numbered (idxNNNN.wav) and must be matched by
    # sound content, not index.  Off elsewhere (the section is hidden).
    mod_transfer: bool = False
    # Partition-explorer path: surfaces a read-only "Partition Explorer" tab that
    # opens a raw card image (.raw/.img), lists its MBR partitions, browses the
    # ext4 filesystem(s), previews small text files, and extracts files/folders
    # to disk.  For pulling radium/script files out of an old modded card, or
    # dumping folders to diff a modded card vs stock without a mount+map cycle
    # (a tester).  Set True only for plugins whose medium is a partitioned card
    # image the app can read (Stern Spike 2 via plugins.stern.explorer).
    partition_explorer: bool = False
    # Settings-editor path: surfaces a "Settings" tab that opens a card image,
    # decodes the game firmware's compiled operator-adjustment DEFAULTS, and
    # lets the user preset them (free play, volume, pricing, …) for a fresh
    # flash / factory-reset machine — the only card-side settings lever, since
    # a configured machine keeps its board-NVRAM values.  Stern Spike 2 only
    # (plugins.stern.explorer + plugins.stern.adjustments).
    settings_editor: bool = False
    # Compare path: surfaces a "Compare" tab that takes two card images (two
    # releases, or a mod against its stock base) and reports what changed —
    # added / modified / deleted files per asset type by the cards' own
    # validation digests, sound counts, adjustment defaults and high-score
    # boards.  The plugin implements ``compare_images``.  Stern Spike 2 only
    # (plugins.stern.compare).
    compare: bool = False


@dataclass(frozen=True)
class InputSpec:
    """File-dialog filter for the Extract tab's input picker."""
    label: str                              # "PB game files"
    extensions: Sequence[str] = field(default_factory=tuple)  # (".upd", ".iso")


# ---------------------------------------------------------------------------
# Manufacturer base class
# ---------------------------------------------------------------------------

class Manufacturer(ABC):
    """Base class for a manufacturer plugin.

    Subclasses must set class attributes ``key``, ``display``, ``games``,
    ``capabilities``, ``input_spec``, and implement :meth:`detect` plus the
    pipeline factories appropriate for their capabilities.
    """

    key: str = ""
    display: str = ""
    games: Sequence[Game] = ()
    capabilities: Capabilities = Capabilities()
    input_spec: InputSpec = InputSpec(label="Files", extensions=("*",))

    # Phase labels rendered in the GUI's phase indicator.  Each pipeline
    # produced by this manufacturer should call ``phase_cb(i)`` for
    # ``0 <= i < len(phases)``.  Override per manufacturer when the
    # default 4-step shape doesn't match — e.g. BOF's Decrypt has 5
    # phases (Detect/Decrypt/Extract/Checksums/Cleanup).
    extract_phases: Tuple[str, ...] = tuple(EXTRACT_PHASES)
    write_phases: Tuple[str, ...] = tuple(WRITE_PHASES)
    # Phase labels for the runtime-capture path (only meaningful
    # when ``capabilities.capture`` is True).
    capture_phases: Tuple[str, ...] = ()
    # Phase labels for the COMBINED extract + capture path (static
    # asset extract followed by runtime capture).  Used when the
    # capture toggle is on and capture is additive on top of static.
    # Falls back to capture_phases if a plugin doesn't define both.
    combined_phases: Tuple[str, ...] = ()
    # Phase labels for the auto-transcribe path (Whisper-based) —
    # used when ``capabilities.transcribe`` is True.
    transcribe_phases: Tuple[str, ...] = ()
    # Phase labels for the Direct-SSD paths (only meaningful when
    # ``capabilities.direct_ssd`` is True).  Mount/Decrypt/Cleanup
    # for extract; Scan/Mount/Encrypt/Cleanup for write — same shape
    # the standalone jjp-decryptor used.
    direct_ssd_extract_phases: Tuple[str, ...] = ()
    direct_ssd_write_phases: Tuple[str, ...] = ()
    # Phase labels for the flash-image path (only meaningful when
    # ``capabilities.flash_image`` is True) — a dd-style raw copy of a
    # pre-built image onto a card.
    flash_phases: Tuple[str, ...] = ()
    # Phase labels for the read-card path (``capabilities.read_card_image``).
    # The default matches the shared ReadCardPipeline; a plugin only needs to
    # override this if it also overrides ``make_read_card_pipeline``.
    read_card_phases: Tuple[str, ...] = ReadCardPipeline.PHASES

    # Runtime tools this plugin needs.  Probed on a worker thread when
    # the user picks this manufacturer in the GUI; results render as
    # `[✓] gpg [✗] partclone` indicators with hover tooltips.  Default
    # is empty (no prereqs to verify — e.g. PB's stdlib-only flow).
    prerequisites: Tuple[Prerequisite, ...] = ()

    # Label for the optional "decode DMD" extract checkbox (shown only when
    # ``capabilities.decode_dmd`` is True).  Plugins override this so the
    # toggle reads sensibly for their format (CGC decodes a WPC ROM; Dutch
    # Pinball applies a dot-matrix shader to its colour videos).
    decode_dmd_label: str = ("Decode DMD scenes to PNG/MP4 "
                             "(experimental, extract-only)")

    # Description text for the optional "updates to merge on top" picker
    # (shown only when ``capabilities.chain_deltas`` is True).  Plugins
    # override this to tell the user exactly which files to download.
    chain_deltas_help: str = (
        "Supply a full image as the Input above, then add the delta "
        "update(s) needed to reach the version you want — Extract merges "
        "them automatically, in version order.")

    # Optional: GitHub repo override.  When None, the core update checker
    # uses :data:`core.config.GITHUB_REPO`.
    update_repo: Optional[str] = None

    # Whether this plugin should be flagged as "Beta" in the UI.  Set
    # True on plugins where major features are still in active
    # development (e.g. capture pipeline emerging from initial
    # bring-up) so users know to expect rough edges.
    beta: bool = False

    # Optional custom corner badge shown on the manufacturer picker card
    # (e.g. "EXTRACT ONLY").  Takes precedence over the default "BETA" badge
    # that ``beta = True`` produces.
    badge: str = ""

    # Hardware-generation eras this plugin handles under one picker entry, as
    # ``((key, "LABEL"), ...)``.  When more than one is listed the working-view
    # header shows a segmented pill switcher (the active era highlighted) so the
    # user picks the era explicitly instead of relying on input auto-detection.
    # The plugin must accept ``set_era(key)`` and expose ``current_era``.  Empty
    # / single-entry → no switcher (the common single-era plugins).
    eras: tuple = ()

    # Active era key for an era-switching plugin (mirrors the last ``set_era``);
    # "" for single-era plugins.  Read by the GUI to light the right pill.
    current_era: str = ""

    # Labels for the Extract/Write source-vs-destination toggle (shown only
    # when ``capabilities.direct_ssd`` is True).  Defaults match JJP's "ISO file
    # vs physical SSD" wording; override per manufacturer when the medium is
    # different (e.g. Stern Spike ships on an SD card, so it reads "SD-card
    # image" / "SD card").
    extract_iso_label: str = "From ISO"
    extract_ssd_label: str = "From SSD"
    write_iso_label: str = "Build USB ISO"
    write_ssd_label: str = "Write to SSD"

    # Human noun for the Extract input field label (and the Write "Original …"
    # label), shown in place of the raw primary extension.  ``None`` falls back
    # to "<.ext>:" (e.g. ".img:") or "Input:".  Stern sets "Card image" so the
    # field reads "Card image:" instead of the jargony ".img:".
    extract_input_label = None

    # Inserted before the extension of the built file's default name (which
    # otherwise mirrors the original's), so a build is obviously not the
    # stock file (a tester 5: "led_zeppelin…-modified.raw").  Only safe for
    # plugins whose output filename carries no meaning to the machine (a raw
    # card image you flash yourself); leave "" when the game/installer looks
    # the file up by name (e.g. BOF's .fun updates).
    write_output_suffix: str = ""

    # --- Flash-surface wording (capabilities.flash_image plugins) --------
    # The consolidated "Build / flash" button + dialog were written for
    # dd-style whole-image media (Stern SD card, CGC card/USB).  JJP reuses
    # the same surface for a *different* operation — format the stick FAT32
    # and copy the installer ISO's files onto it (a raw-imaged stick is
    # unreadable to a JJP machine) — so every user-facing word is
    # overridable.  ``None`` falls back to the dd-flavoured default (and,
    # for the noun/kind, to the Direct-SD attributes), keeping Stern/CGC
    # byte-identical.
    flash_button_text = None      # Write-tab button ("Build / flash SD card…")
    flash_button_tip = None       # its tooltip
    flash_medium_noun = None      # dialog noun -> direct_medium_noun/"SD card"
    flash_target_kind = None      # drive-pick bias -> direct_target_kind
    flash_target_label = None     # target-row label -> "Target <noun>:";
                                  # the column is 12 chars, long nouns clip
    flash_safety_text = None      # red banner -> direct_safety_text
    flash_dialog_title = None     # -> "Build / flash <noun> image"
    flash_header = None           # dialog heading -> "Build an image and/or
                                  # write one onto a <noun>"
    flash_section_label = None    # -> "Write an image onto the <noun>"
    flash_action_word = None      # Start-button verb -> "flash" ("Flash image",
                                  # "Build + flash")
    flash_confirm_verb = None     # erase-confirm clause -> "write the image
                                  # onto it"
    # File-dialog filter for the "Image file:" Browse (flash-only mode).
    flash_image_filetypes = (("SD-card image", "*.img *.raw *.bin"),
                             ("All files", "*.*"))

    # Extension (lower-case, leading dot, e.g. ".raw") the built file MUST
    # carry.  "" means the plugin pins nothing — the File Name box is used
    # verbatim.  Flash-image plugins build a raw card image the machine reads by
    # content, not by name, but the file still needs the extension the user's
    # imaging tools (and the app's own re-detection) expect — so they pin it
    # here (Stern Spike 2 = ".raw", CGC = ".img").  The GUI states this next to
    # the File Name box and Write forces it on, so a user-typed name can never
    # come out extensionless.  Era-aware plugins override as a method/property
    # (Stern only pins it for Spike 2, not the capture-only Whitestar era).
    def write_output_ext(self):
        return ""

    def force_write_ext(self, name):
        """Return *name* guaranteed to end with :meth:`write_output_ext`.

        Appends the extension when the name has none (the reported bug: an
        extensionless build), swaps a recognised input extension for the
        required one (so ``.img`` typed for a Spike 2 card becomes ``.raw``,
        not ``.img.raw``), and leaves a correctly-suffixed name untouched.  A
        no-op when the plugin pins no extension (``write_output_ext`` == "")."""
        ext = (self.write_output_ext() or "").lower()
        if not ext or not name or name.lower().endswith(ext):
            return name
        stem, cur = os.path.splitext(name)
        known = {e.lower() for e in self.input_spec.extensions
                 if e and e != "*"}
        if cur and cur.lower() in known:
            return stem + ext
        return name + ext

    # Action-button captions on the Write tab, one per destination mode, so
    # the button restates the chosen action instead of a generic "Apply".
    # Defaults match JJP's historical wording (mirrors the standalone JJP
    # decryptor); override per manufacturer to track the destination radio.
    write_build_button: str = "Build update"        # build-image / ISO mode
    write_direct_button: str = "Apply Modifications"  # write-to-medium mode

    # Generic noun for the physical medium in Direct-from-device mode, used
    # in dynamic prose (drive-pick hint, admin-required panel).  JJP ships on
    # an SSD; Stern Spike on an SD card.  Override per manufacturer.
    direct_medium_noun: str = "SSD"
    # Drive-picker bias for Direct mode: "ssd" prefers the largest external
    # (a removable game SSD, JJP); "sd_card" prefers a card reader / the
    # smallest external and never auto-trusts a multi-TB drive (Stern Spike's
    # small SD card).  Consumed by core.drives.pick_best_game_ssd.
    direct_target_kind: str = "ssd"
    # Red safety banner shown in Direct mode.  JJP's wording ("remove the SSD,
    # keep the ISO backup") is SSD/ISO-specific; override when the medium and
    # backup artifact differ (Stern reads from an SD-card image).
    direct_safety_text: str = (
        "⚠ Remove the SSD from the pinball machine before connecting. "
        "Always keep the original ISO as a backup.")

    @abstractmethod
    def detect(self, path):
        """Return a :class:`Game` if this manufacturer claims *path*, else None."""

    def title_caption(self, path, game):
        """Short human caption for the title bar once *game* was detected on
        *path* — e.g. "Led Zeppelin v1.22 LE".

        The happy-path "Detected: …" badge moved into the window title
        (feedback batch 20: repeating the game name, the platform, and "card
        image" on the tab was redundant), so this should be the leanest string
        that identifies the loaded game — no manufacturer/platform echo, plus
        a version when the plugin can recover one cheaply (filename-level;
        this runs on the Tk thread on every path change).  Default: the
        game's display name."""
        return game.display

    def image_info(self, path, assets_dir=None):
        """Platform-specific sections for the Image Info tab, as
        ``[(section_title, [(name, value), ...]), ...]``.

        Called on a worker thread with the selected input *path* (and the
        current extracted-assets folder, when one is set) after the generic
        File/Detection sections; whatever a plugin returns is appended.  Must
        stay read-only and cheap — a slow probe holds the whole tab on
        "Reading image…".  The default contributes nothing.
        """
        return []

    def compare_images(self, path_a, path_b):
        """What changed from image *path_a* to image *path_b*, in the same
        section shape as :meth:`image_info`.

        Called on a worker thread by the Compare tab; must stay read-only.
        Only meaningful for plugins advertising ``capabilities.compare`` —
        the default contributes nothing.
        """
        return []

    # ------------------------------------------------------------------
    # Pipeline factories — implement those your capabilities advertise.
    # ------------------------------------------------------------------

    def make_extract_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb):
        raise NotImplementedError(
            f"{self.display} does not implement an Extract pipeline.")

    def make_write_pipeline(self, original_path, assets_dir, output_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        raise NotImplementedError(
            f"{self.display} does not implement a Write pipeline.")

    def apply_delta(self, assets_dir, delta_path,
                    log_cb=None, progress_cb=None):
        """Returns ``(overwritten, added, total)``."""
        raise NotImplementedError(
            f"{self.display} does not implement apply-delta.")

    def make_capture_pipeline(self, input_path, output_dir,
                              log_cb, phase_cb, progress_cb, done_cb,
                              **kwargs):
        """Build the runtime-capture pipeline (emulator-driven).

        Only meaningful when ``capabilities.capture`` is True.
        ``kwargs`` carries pipeline-specific knobs (e.g.
        ``duration_seconds``); each plugin decides which it
        understands.
        """
        raise NotImplementedError(
            f"{self.display} does not implement a Capture pipeline.")

    def make_transcribe_pipeline(self, assets_dir,
                                 log_cb, phase_cb, progress_cb, done_cb,
                                 rename_after=False, model_size="tiny.en"):
        """Build the auto-transcribe pipeline (faster-whisper).

        Only meaningful when ``capabilities.transcribe`` is True.
        Walks ``assets_dir`` for .wav files, runs Whisper with VAD
        filtering to skip non-speech, and emits ``callouts.csv`` at
        the root of the assets dir.  ``model_size`` is the whisper
        model (the ⚙ menu's voice-recognition quality pick).
        """
        raise NotImplementedError(
            f"{self.display} does not implement a Transcribe pipeline.")

    def make_music_id_pipeline(self, assets_dir,
                               log_cb, phase_cb, progress_cb, done_cb,
                               rename_after=False):
        """Build the online music-ID pipeline (AcoustID + MusicBrainz).

        Only meaningful when ``capabilities.music_id`` is True.  Identifies
        each extracted music WAV under ``assets_dir`` by acoustic fingerprint
        and emits ``music_titles.csv``.
        """
        raise NotImplementedError(
            f"{self.display} does not implement a music-ID pipeline.")

    def make_direct_ssd_extract_pipeline(
            self, device_path, output_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        """Build the Direct-SSD extract pipeline.

        Only meaningful when ``capabilities.direct_ssd`` is True.
        ``device_path`` is an OS-native physical-disk path
        (``\\\\.\\PHYSICALDRIVEn`` on Windows, ``/dev/diskN`` on
        macOS, ``/dev/sdX`` on Linux).  ``partition_override`` is the
        optional escape hatch from the "Force partition #" field —
        ``None`` means let the pipeline auto-discover.
        """
        raise NotImplementedError(
            f"{self.display} does not implement a Direct-SSD "
            f"extract pipeline.")

    def make_direct_ssd_write_pipeline(
            self, device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=None):
        """Build the Direct-SSD write/modify pipeline.

        Only meaningful when ``capabilities.direct_ssd`` is True.
        See :meth:`make_direct_ssd_extract_pipeline` for parameter
        semantics; this one takes an assets folder of modified
        files instead of an output folder.
        """
        raise NotImplementedError(
            f"{self.display} does not implement a Direct-SSD "
            f"write pipeline.")

    def make_flash_pipeline(self, image_path, device_path,
                            log_cb, phase_cb, progress_cb, done_cb):
        """Build the flash-image pipeline (raw-copy a pre-built image onto a card).

        Only meaningful when ``capabilities.flash_image`` is True.
        ``image_path`` is the source ``.img``/``.raw``; ``device_path`` is an
        OS-native physical-disk path (``\\\\.\\PHYSICALDRIVEn`` / ``/dev/sdX``).
        """
        raise NotImplementedError(
            f"{self.display} does not implement a flash-image pipeline.")

    def make_read_card_pipeline(self, device_path, image_path,
                                log_cb, phase_cb, progress_cb, done_cb):
        r"""Build the read-card pipeline (raw-copy a whole card into a file).

        Only meaningful when ``capabilities.read_card_image`` is True.
        ``device_path`` is an OS-native physical-disk path
        (``\\.\PHYSICALDRIVEn`` / ``/dev/sdX``); ``image_path`` is the ``.raw``
        to create.  Unlike the other factories this has a real default: a
        sector-for-sector card dump is identical for every plugin, so plugins
        only override it if their medium needs something else.
        """
        return ReadCardPipeline(device_path, image_path,
                                log_cb, phase_cb, progress_cb, done_cb)

    def audio_slot_dirs(self, assets_dir):
        """Subdirectories of *assets_dir* that hold replaceable audio slots.

        Drives the Replace-Audio tab's scan when ``capabilities.replace_audio``
        is set.  Return ``None`` (the default) to scan the whole extract for
        loose .wav/.ogg — correct for JJP / Spooky / AP / PB / DP.  Plugins
        whose audio lives in a specific edit surface override this so the slot
        list shows only files Write can repack (CGC: the decoded ``<bnk>/``
        dirs; BoF: the ``_EDITABLE ASSETS`` folder), not unrelated decode
        derivatives elsewhere in the tree.
        """
        return None

    def audio_slot_exts(self, assets_dir):
        """Audio extensions the Replace-Audio tab should surface as slots.

        Return ``None`` (default) to use both ``.wav`` and ``.ogg``.  Override
        to narrow it when a plugin's Write can only repack some formats — BoF
        returns ``(".wav",)`` because its editable-folder re-import handles
        ``.wav`` but not ``.ogg`` yet, so surfacing ``.ogg`` slots would invite
        dead-end edits that silently vanish at Write.
        """
        return None

    def audio_length_note(self) -> str:
        """One-line guidance for the Replace-Audio tab: does a replacement
        need to match the original track's length?

        Default: length is flexible (most engines play the file as-is), so
        trimming usually isn't needed.  Plugins whose Write *forces* a length
        match (JJP) or whose engine is explicitly length-agnostic (Dutch
        Pinball) override this with a more specific message.
        """
        return ("Replacements play at their own length — trimming usually "
                "isn't needed. Tick “Trim / pad” below only if a "
                "track sounds cut off or mistimed in-game.")

    def audio_forces_length_match(self, assets_dir=None) -> bool:
        """Whether this plugin's Write ALWAYS trims/pads replacements to the
        original slot length, regardless of the "Trim / pad" checkbox.

        When True, the GUI forces the checkbox on and disables it (the toggle
        would be misleading otherwise).  Used by JJP and Spike 2, whose Write
        step matches every track to its original slot length unconditionally.

        *assets_dir* (the scanned extract folder, or None before one is
        loaded) lets a plugin answer per-extract when the constraint depends
        on the game: CGC's Pulp Fiction stores audio in fixed-length JPS bank
        slots (forced), while its WPC remakes store loose .wav the engine
        plays at any length (a free choice).  Default False."""
        return False

    def video_slot_dirs(self, assets_dir):
        """Subdirectories of *assets_dir* that hold replaceable video slots.

        Drives the Replace-Video tab's scan when ``capabilities.replace_video``
        is set.  Return ``None`` (the default) to scan the whole extract for
        loose video — correct for JJP.  Plugins override this to keep
        dead-end videos out of the list: Dutch Pinball excludes The Big
        Lebowski's decoded ``_DECODED VIDEOS`` (no .mp4->.cdmd encoder), so a
        TBL extract shows no editable video while an AAIW extract scans the
        whole tree, and Spooky excludes the ``_extracted_assets`` /
        ``_pck_contents`` folders Extract generates (nothing writes a Unity
        or Godot derivative back into its container).
        """
        return None

    def video_slot_exts(self, assets_dir):
        """Video extensions the Replace-Video tab should surface as slots.

        Return ``None`` (default) to use :data:`core.video.VIDEO_EXTS`.
        Override to narrow it when only some formats round-trip — BoF
        returns ``(".ogv",)`` because Ogg Theora is the one video form it
        ships.  Narrow by *folder* instead wherever the same extension can
        be both a shipped file and a dead-end derivative; an extension
        filter can't tell those apart (see :meth:`video_slot_dirs`).
        """
        return None

    def video_pins_byte_size(self, assets_dir=None) -> bool:
        """Whether this plugin's Write may hold a replacement clip to the
        original's exact byte length.

        When True, the staging re-encode is given that length as a byte
        budget, so a clip bound for a fixed-size slot is encoded once instead
        of being encoded to the slot's shape and then re-encoded again by the
        build's fit — two generations of loss for one replacement.  Only
        consulted when the user is also matching the slot's duration, since
        the budget is only meaningful for a clip of the slot's own length
        (see :func:`core.video_slots.stage_replacements`).

        Answering True costs nothing when the size turns out not to be pinned:
        the budget only sets the encoder's bitrate, and the build still fits
        whatever it is handed.  Default False.
        """
        return False

    def video_length_note(self) -> str:
        """One-line guidance for the Replace-Video tab: does a replacement
        need to match the original clip's length?

        Default: length is flexible (most engines play the file as-is), so
        trimming usually isn't needed.  Plugins whose engine is sensitive to
        clip length override this.
        """
        return ("Replacements play at their own length — trimming usually "
                "isn't needed. Tick “Trim / pad” below only if a clip looks "
                "cut off or mistimed in-game.")

    def image_slot_dirs(self, assets_dir):
        """Subdirectories of *assets_dir* that hold replaceable image slots.

        Drives the Replace-Image tab's scan when ``capabilities.replace_image``
        is set.  Return ``None`` (the default) to scan the whole extract for
        loose images.  Override to keep dead-end images out of the list (e.g.
        derived/decoded image folders a plugin's Write can't repack).
        """
        return None

    def image_slot_exts(self, assets_dir):
        """Image extensions the Replace-Image tab should surface as slots.

        Return ``None`` (default) to use :data:`core.image.IMAGE_EXTS`.
        Override to narrow it when only some formats round-trip.
        """
        return None

    def image_note(self) -> str:
        """One-line guidance for the Replace-Image tab.

        Default: replacements are scaled to the original's pixel dimensions.
        Plugins whose Write constrains the file further (e.g. a size-neutral
        in-place patch) override this.
        """
        return ("Replacements are scaled to the original image's pixel "
                "dimensions. Pick your extracted folder, assign an image to a "
                "slot, then build the update on the Write tab.")

    def audio_export_supported(self, path) -> bool:
        """Whether extracting *path* yields audio assets the
        transcribe pipeline can act on.

        Drives the per-game visibility of the Auto-transcribe controls
        and the "Extract audio" phase.  Default: tied to the static
        ``transcribe`` capability (path-independent).  Williams
        overrides this — only DCS-era ROMs have decodable audio.
        """
        return self.capabilities.transcribe

    def decode_dmd_applies(self, input_path) -> bool:
        """Whether the optional "decode DMD" checkbox applies to *input_path*.

        Default: tied to the static ``decode_dmd`` capability.  Multi-game
        plugins override this to hide the control for games it doesn't apply
        to (Dutch Pinball: TBL only, not the AAIW disk image).
        """
        return self.capabilities.decode_dmd

    def chain_deltas_applies(self, input_path) -> bool:
        """Whether the optional "merge updates" picker applies to *input_path*.

        Default: tied to the static ``chain_deltas`` capability.  Overridden
        by multi-game plugins (Dutch Pinball: TBL only).
        """
        return self.capabilities.chain_deltas

    def decode_dmd_label_for(self, input_path) -> str:
        """Checkbox label for the optional video-processing toggle.

        Default returns the static :attr:`decode_dmd_label`.  Multi-game
        plugins override this so the toggle reads correctly per input (Dutch
        Pinball: a dot-matrix shader for TBL, a ProRes->MP4 convert for AAIW).
        """
        return self.decode_dmd_label

    # ------------------------------------------------------------------
    # Misc UI hints — override if you want non-default phrasing.
    # ------------------------------------------------------------------

    def extract_input_help(self) -> str:
        return f"Select a {self.display} input file."

    def write_install_help(self) -> Optional[str]:
        """Optional 'How to install' text shown beneath the Write button."""
        return None

    # NOTE: the Write tab used to lead with per-manufacturer wording hooks
    # (write_intro / build_write_description / direct_write_description);
    # all of that guidance moved into the "?" tips window (feedback batches
    # 4 + 8), so the hooks are gone.


# ---------------------------------------------------------------------------
# Registry storage
# ---------------------------------------------------------------------------

_REGISTRY: List[Manufacturer] = []


def register_manufacturer(mfr: Manufacturer):
    if any(m.key == mfr.key for m in _REGISTRY):
        return  # idempotent — plugin re-imports during tests are fine
    _REGISTRY.append(mfr)


def all_manufacturers() -> List[Manufacturer]:
    """Return every registered manufacturer sorted alphabetically by display
    name (so the GUI dropdown order is stable and easy to scan)."""
    return sorted(_REGISTRY, key=lambda m: m.display.lower())


def get_manufacturer(key: str) -> Optional[Manufacturer]:
    for m in _REGISTRY:
        if m.key == key:
            return m
    return None


def load_plugins():
    """Import every plugin module so each can call register_manufacturer()."""
    for module_name in _PLUGIN_MODULES:
        try:
            mod = importlib.import_module(module_name)
            register = getattr(mod, "register", None)
            if register:
                register()
        except Exception as e:
            # A broken plugin shouldn't take down the whole app.
            # The first-time setup may have missing optional deps.
            print(f"Warning: failed to load plugin {module_name}: {e}")


def detect_manufacturer(path):
    """Walk registered manufacturers, return the first that claims *path*.

    Returns ``(manufacturer, game)`` or ``(None, None)``.
    """
    for m in _REGISTRY:
        try:
            game = m.detect(path)
        except Exception:
            continue
        if game:
            return m, game
    return None, None
