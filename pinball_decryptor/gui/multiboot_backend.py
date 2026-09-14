"""The Multi-boot tab's PLATFORMS (item 118): what the tab hard-coded for
Stern, gathered into one object per manufacturer, so the same tab builds a
Jersey Jack multi-boot install ISO with the same rows, the same preview and
the same green button.

The tab (:mod:`multiboot_tab`) was written for ONE card: the Stern Spike 2
SD card, ``tools/spike2_emu/mkmulticard.py`` behind it.  The 2026-09-12
audit found everything about that card baked into the module - the tool
paths, the selector's home inside the rootfs, the ``p3``/``p7`` device
tokens the preview writes, the ``fits Stern 16G`` line the size strip reads,
the three card sizes it offers, the ``.sdcard.raw`` default name, the words
"SD card" in every sentence, qemu for the preview.  A JJP install is the same
menu on a different medium: two install ISOs in, one ISO out
(``tools/jjp_emu/mkjjpmulti.py``), a FAT32 USB stick rather than an SD card,
``rootA``/``rootB`` for the devices, a natively built ``jjpselect`` that
draws the preview without qemu, and no in-place update, no validator bypass,
no random groups and no compact layout - the A/B slots hold exactly two.

Everything here is DATA or a pure function of a path.  The tab's command
builders take the platform from the form (``MultibootForm.platform``), the
panel from the manufacturer the app switched to (``MultibootPanel.set_platform``),
and the default is Stern, so every argv the Stern tests pin is unchanged.
"""
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MultibootBackend:
    #: ``stern`` / ``jjp`` - the manufacturer plugin's own key.
    key: str
    label: str
    # ---- the tools, relative to the checkout root the command line cd's into
    tool_dir: str
    tool: str                         # the card / ISO builder
    media_tool: tuple                 # argv prefix of the media step
    selector_src: str                 # the selector's sources (themes.json lives there)
    ensure_tool: str                  # the script that installs the menu program
    # ---- what a finished multi-boot thing is called, and the images it holds
    card_flag: str                    # --card / --iso: how the builder is told which one
    image_exts: tuple                 # what an image file ends in
    image_types: tuple                # the file dialog's filter
    image_noun: str                   # "card image" / "install ISO"
    image_pick_title: str
    out_ext: str                      # the output's extension
    out_suffix: str                   # <stem> + this = the default output name
    out_noun: str                     # "card" / "install ISO": the thing built
    out_label: str                    # the label beside the path box
    empty_path_text: str
    medium: str                       # "SD card" / "USB stick": what it is written onto
    medium_needed: str                # the size strip's label
    medium_holds: str                 # "...than a 32 GB card holds" / "stick holds"
    flash_frame: str                  # the Build / flash modal's second frame
    flash_tick: str
    flash_detail: str
    build_flash_text: str             # the green button
    overhead_label: str               # the size strip's last band
    sizes: tuple                      # ((key, label), ...) the plan measures against
    fits_re: re.Pattern               # the plan's fits line
    total_re: re.Pattern              # the plan's total line
    status_checks: tuple              # ((key, label), ...) the status row
    # ---- what the card can hold
    max_cards: int
    groups: bool                      # random groups
    compact: bool                     # the store layout
    machine_volume: bool              # volume=machine (the card's /data/nv mirror)
    #: THE MENU'S VOLUME, 0-volume_max, and what a new form starts at (item
    #: 120).  A JJP machine keeps its amplifiers at full and turns only the
    #: game's own stream down, so the menu's number is the level the speakers
    #: get: 50 was "very high" on the first GNR.  The builder refuses above
    #: the cap too, and the selector's JJP build cannot pass it.
    volume_default: int
    volume_max: int
    update: bool                      # in-place update of a loaded card
    bypass: bool                      # the validator bypass
    extract: bool                     # Recover images…
    read_card: bool                   # From SD card…
    # ---- the menu program
    selector_default: str             # where the installed menu program lives
    selector_suffix: str              # what marks a directory as the menu program's home
    selector_binary: str              # the binary, relative to that directory
    preview_native: bool              # run the binary itself (no qemu -L rootfs)
    conf_font: str                    # font= in the preview's conf
    #: steps of a writing run that need root
    root_steps: frozenset

    # ---- pure helpers -----------------------------------------------------
    def device(self, img):
        """images.conf's device token for image *img* (0 = the primary)."""
        if self.key == "jjp":
            return "rootA" if img == 0 else ("rootB" if img == 1 else "rootB:img%d" % img)
        return "p3" if img == 0 else ("p7" if img == 1 else "p7:img%d" % img)

    def suggest_title(self, path):
        """``(title, subtitle)`` a fresh row starts with - a suggestion, not
        a fact.  Stern's card names carry a version and a build tag
        (``turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw``); a JJP ISO's
        name is the whole title (``CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso``)."""
        b = os.path.basename(path or "")
        if self.key == "jjp":
            b = re.sub(r"\.(iso|raw|img)$", "", b, flags=re.I)
            return re.sub(r"[_\s]+", " ", b).strip(), ""
        b = re.sub(r"\.(raw|img|bin|iso)$", "", b, flags=re.I)
        b = re.sub(r"\.\d+G\.sdcard$", "", b, flags=re.I)
        b = re.sub(r"\.sdcard$", "", b, flags=re.I)
        head, _, tail = b.partition(".")
        return head, tail

    def output_name(self, primary):
        """The default output's file name for a primary image."""
        base = os.path.basename(primary or "")
        stem = re.sub(r"\.(raw|img|iso)$", "", base, flags=re.I)
        return stem + self.out_suffix

    def is_image(self, path):
        return (path or "").strip().strip('"').lower().endswith(self.image_exts)


_SPIKE2 = "tools/spike2_emu"
_JJP = "tools/jjp_emu"

STERN = MultibootBackend(
    key="stern", label="Stern Spike 2",
    tool_dir=_SPIKE2, tool=_SPIKE2 + "/mkmulticard.py",
    media_tool=(_SPIKE2 + "/selectmedia.py", "prepare"),
    selector_src=_SPIKE2 + "/codeselect", ensure_tool=_SPIKE2 + "/ensureselect.sh",
    card_flag="--card",
    image_exts=(".raw", ".img"),
    image_types=(("Card images", "*.raw *.img"), ("All files", "*.*")),
    image_noun="card image", image_pick_title="Pick a Spike 2 card image for the card",
    out_ext=".raw", out_suffix=".multi.raw", out_noun="card",
    out_label="Multi-boot card image:",
    empty_path_text=("No card yet. Add the images below - the path fills "
                     "itself in from the first one - or type where the card "
                     "should be written."),
    medium="SD card", medium_needed="SD card needed:", medium_holds="card holds",
    flash_frame="Flash to an SD card", flash_tick="Write the card onto an SD card",
    flash_detail=("Flashing the whole image erases and replaces the "
                  "whole SD card, and needs Administrator (approved "
                  "when the write starts). Tick this with the write "
                  "above to build and flash in one step.\n\n"
                  "CHANGED ONLY THE MENU? The next dialog offers "
                  "'Only the boot menu' - it writes the menu partition "
                  "and nothing else, which is about a minute instead of "
                  "the whole image, and the machine keeps its settings "
                  "and scores. It checks the card first and refuses if "
                  "this image was not the one flashed onto it."),
    build_flash_text="Build / flash card…",
    overhead_label="Boot, rootfs, /data, /dump and metadata",
    sizes=(("8G", "8 GB"), ("16G", "16 GB"), ("32G", "32 GB")),
    fits_re=re.compile(r"fits Stern\s+(\d+G)\s+image size\s+\d+:\s+(YES|NO)\s*\(spare\s+(-?\d+)\)"),
    total_re=re.compile(r"^image:\s+\d+\s+sectors\s+=\s+(\d+)\s+bytes"),
    status_checks=(("card", "Card image"), ("images", "Images"),
                   ("built", "Built"), ("ready", "Ready to flash")),
    max_cards=16, groups=True, compact=True, machine_volume=True,
    volume_default=50, volume_max=100,
    update=True, bypass=True, extract=True, read_card=True,
    selector_default="~/spike2root/usr/local/codeselect",
    selector_suffix="/usr/local/codeselect", selector_binary="codeselect",
    preview_native=False, conf_font="/usr/local/codeselect/font.ttf",
    root_steps=frozenset(("build", "update")))

#: JJP: every writing step mounts something (the ISOs, the scratch root) and
#: the restored roots the emulator shares are root's, so the media step (it
#: reads a root for the logo), the build, the inject and the verify run as
#: root; the plan reads the ISOs through xorriso as the user.  The preview
#: draws with jjpselect itself - a native x86-64 binary - so no qemu, no
#: rootfs, and the font is the one the selector's install put beside it.
JJP = MultibootBackend(
    key="jjp", label="Jersey Jack",
    tool_dir=_JJP, tool=_JJP + "/mkjjpmulti.py",
    media_tool=(_JJP + "/mkjjpmulti.py", "media"),
    selector_src=_SPIKE2 + "/codeselect", ensure_tool=_JJP + "/ensurejjpselect.sh",
    card_flag="--iso",
    image_exts=(".iso",),
    image_types=(("JJP install ISOs", "*.iso"), ("All files", "*.*")),
    image_noun="install ISO", image_pick_title="Pick a JJP install ISO for the stick",
    out_ext=".iso", out_suffix=".multi.iso", out_noun="install ISO",
    out_label="Multi-boot install ISO:",
    empty_path_text=("No ISO yet. Add the two install ISOs below - the path "
                     "fills itself in from the first one - or type where the "
                     "multi-boot ISO should be written."),
    medium="USB stick", medium_needed="USB stick needed:", medium_holds="stick holds",
    flash_frame="Make a USB install stick",
    flash_tick="Turn the ISO into a USB install stick",
    flash_detail=("The stick is formatted FAT32 and the ISO's files are copied "
                  "onto it - the only stick layout a JJP machine reads - which "
                  "ERASES the stick and needs Administrator (approved when it "
                  "starts). Tick this with the write above to build and make "
                  "the stick in one step. Installing from the stick wipes the "
                  "machine's settings and scores (JJP's own installer always "
                  "re-partitions); both images then share one set."),
    build_flash_text="Build / make stick…",
    overhead_label="Installer, EFI, boot and perm pieces",
    sizes=(("8G", "8 GB"), ("16G", "16 GB"), ("32G", "32 GB"), ("64G", "64 GB")),
    fits_re=re.compile(r"fits USB\s+(\d+G)\s+stick size\s+\d+:\s+(YES|NO)\s*\(spare\s+(-?\d+)\)"),
    total_re=re.compile(r"^iso-size\s+(\d+)"),
    status_checks=(("card", "Install ISO"), ("images", "Images"),
                   ("built", "Built"), ("ready", "Ready for the stick")),
    max_cards=2, groups=False, compact=False, machine_volume=False,
    volume_default=20, volume_max=40,
    update=False, bypass=False, extract=False, read_card=False,
    selector_default="/var/tmp/jjpselect",
    selector_suffix="/jjpe/gen1/padselect", selector_binary="jjpe/gen1/padselect/jjpselect",
    preview_native=True, conf_font="/var/tmp/jjpselect/jjpe/gen1/padselect/font.ttf",
    root_steps=frozenset(("selector", "prepare", "build", "verify", "inject")))

BACKENDS = {STERN.key: STERN, JJP.key: JJP}


def backend_for(what):
    """The backend for a key (``'jjp'``), a form (its ``platform``), a
    backend itself, or nothing - Stern, the tab's original platform."""
    if isinstance(what, MultibootBackend):
        return what
    key = what if isinstance(what, str) else getattr(what, "platform", None)
    return BACKENDS.get((key or "stern").strip().lower(), STERN)
