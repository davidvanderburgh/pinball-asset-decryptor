"""The Spike 2 rig's helpers, as the web Emulate tab calls them.

The rig's module-level functions (``setup_state``, ``state_text``,
``watch_cmd``, ``kill_cmd``, ``parse_cache_list``...) live in
:mod:`pinball_decryptor.webui.emulate_core`, which is Tk-free; this module
re-exports the ones the tab calls, under the names it calls them by.

The tab's word lists and numbers (the countries, the power choices, the
tooltips, the poll periods) and three small helpers were class attributes
of the Tk ``EmulatePanel`` until the cut-over.  They are defined HERE now,
word for word, as plain module constants and functions: nothing in this
module needs a window.

``runtime_prompt`` (the old ``_runtime_ui``) is imported for ``notice``,
``ensure``, its state sets and ``ask_before_replacing`` (the consent that
names the save states: ONE wording, asked on the page).  Only
``offer_from_file`` is not called, because it runs ``runtime.install`` on
the calling thread; its question sentence is below as
:func:`from_file_question`.
"""

import json
import os

from ..core import runtime
from pinball_decryptor.webui import runtime_prompt as _runtime_ui  # noqa: F401  (re-exported)
from .emulate_core import (  # noqa: F401  (re-exported)
    MULTI_IMAGE_NOTE, _ADVANCING_HINT, _CARD_COPY_RE, _COPY_EXPLAIN,
    _CREATE_FLAGS as CREATE_FLAGS, _MODES_EXPLAIN, _MULTIBOOT_PROBE_S,
    _NEEDS_WSL_RESTART, _OVERRIDE_EXPLAIN, _WSL_BOOT_TEXT, _WSL_BOOT_TICKS,
    DOCKER_URL, assets_fingerprint, cache_boot_text, card_copy_progress,
    docker_cli, docker_engine, docker_state, engine_setup_plan, human_size,
    kill_cmd, load_cmd, multiboot_cmd, overrides_dir, overrides_reason,
    override_base_card, parse_cache_list, parse_multiboot, parse_status,
    playfield_launch, preview_modes_reason, rig_available, rig_cmd,
    rig_cmd_root, rig_dir, setup_fix_steps, setup_fixable, setup_notice,
    setup_ok, setup_report, setup_report_darwin, setup_settled, setup_state,
    state_text, watch_cmd, which_tool, windows_python, wsl_home,
)
from .emulate_core import _wsl_path as wsl_path  # noqa: F401

#: Wall-clock cap handed to ``watch.sh``.  A forgotten window must not be
#: able to burn a core all night; the rig enforces it, this only chooses it.
BACKSTOP_MIN = 120

#: Status poll period.  Each poll is one ``wsl.exe`` round trip, so this is
#: slow enough to cost nothing and fast enough to feel live.
POLL_MS = 2000

#: Poll period when the rig is IDLE.  A run in progress is worth a
#: two-second heartbeat; a machine with no emulator on it is not worth a
#: `wsl.exe` spawn every two seconds for as long as the app is open — that
#: is 1,800 WSL round trips an hour to be told "off" each time, and after
#: a Windows reboot the first of them boots the whole WSL VM.  A run this
#: app starts flips to POLL_MS immediately (the status says so), so the
#: only thing this delays is noticing a run somebody started in a
#: terminal, by a few seconds.
POLL_IDLE_MS = 10000

#: The game's own country table, IN ITS ORDER, because the position is the
#: number: a Spike 2 CPU board's DIP bank (SW1) reports an index into this
#: list, and the game's country init reads ``(switches >> 8) & 0x7f`` off
#: the cabinet word.  Decoded from stranger_things 1.12.0 (message ids
#: 1421..1450, table 0x731aac); the names are the game's, written in
#: ordinary case.  Index 0 is all switches OFF - a US machine from the
#: factory, and what the emulator has always reported.
#:
#: The same number goes into the country the machine is SET to (the
#: shim's PAD_COUNTRY, EEPROM 0x140), because that - not the switches - is
#: what the game shows on its boot screen: David picked Denmark and D&D
#: still said U.S.A., since the switches only ever flag the stored country
#: for an operator to confirm.
COUNTRIES = (
    "U.S.A.", "Austria", "Belgium", "Canada 1", "Netherlands", "Finland",
    "France", "Germany", "Italy", "Denmark", "Norway", "Sweden",
    "Switzerland", "Australia", "U.K.", "Greece", "New Zealand",
    "Portugal", "Spain", "Chuck E. Cheese", "South Africa", "Japan",
    "Croatia", "Middle East", "Taiwan", "Russia", "Canada 2", "Lithuania",
    "China", "Indonesia")

#: The row's untouched choice, and it is NOT "U.S.A.": the country is
#: saved in the machine, so a U.S.A. that sent nothing could never undo a
#: Denmark picked last week.  This one sends nothing and leaves the
#: machine as the game has it - including a country changed in the game's
#: own setup - which is how the emulator ran before the row existed.
COUNTRY_GAME = "As set in the game"

#: (label, what Start adds).  A Spike 2 CPU board was made in a 60 Hz
#: version for US games and a 50 Hz version for European ones, and the
#: game refuses to run a 60 Hz board on 50 Hz mains.  PAD_MAINS_HZ is the
#: mains (run_game.sh), PAD_FACTORY_HZ the board (hwshim.c).  The first
#: choice adds nothing: it is the bench the emulator has always been.
POWER_CHOICES = (
    ("60 Hz mains", ()),
    ("50 Hz mains, European machine",
     ("PAD_MAINS_HZ=50", "PAD_FACTORY_HZ=50")),
    ("50 Hz mains, US machine",
     ("PAD_MAINS_HZ=50", "PAD_FACTORY_HZ=60")),
)

COUNTRY_TIP = (
    "The country the machine is set to: the one on the boot screen, and "
    "the coin settings that go with it. A real Spike 2 CPU board also has "
    "a bank of eight DIP switches (SW1) for the country, and those are set "
    "to match.\n\n“As set in the game” leaves both alone, which "
    "is how the emulator has always run: the game keeps the country it "
    "has stored, U.S.A. unless it was changed in its own setup. A country "
    "picked here stays set in the machine. Takes effect at the next Start.")

POWER_TIP = (
    "Spike 2 CPU boards were made in a 60 Hz version for US games and a "
    "50 Hz version for European ones, and a US board on 50 Hz mains "
    "refuses to run: “this machine will not operate in this "
    "country”.\n\n60 Hz is how the emulator has always run. "
    "European machine is a 50 Hz board on 50 Hz mains. US machine is the "
    "refusal a US game gives on European power, and the emulator leaves "
    "it on screen rather than pressing past it. Takes effect at the next "
    "Start.")

#: The cost, spelled out beside the section it belongs to.
#:
#: IT WAS A CHECKBOX UNTIL 2026-08-10, and David removed it: "remove the
#: checkbox for 'enable save state' and just keep the tooltip, but put it
#: on the save states title with a blue (i) button to the right of it like
#: we normally do."  So the feature is simply ON, and this text stopped
#: being a warning attached to a choice and became a description of what
#: the section does — the cost is still stated, because a save really does
#: freeze the game for a few seconds and every slot really is disk.
STATES_TIP = (
    "Save states snapshot the WHOLE running game so you can jump back "
    "to that exact moment later - including in a future session, or "
    "after replacing assets, to compare how a mode looks.\n\n"
    "The cost:\n"
    "• each slot stores roughly 50-150 MB on the WSL disk "
    "(snapshots compress ~20x; a save briefly needs ~1.5 GB free "
    "while it packs)\n"
    "• saving freezes the game and its sound for a few seconds "
    "while the snapshot is written\n"
    "• slots stay on disk until deleted below\n\n"
    "The virtual playfield window carries the Save/Load state controls "
    "for these 10 slots, and Launch above starts the emulator straight "
    "into one.")

#: The Launch button's honest timeline — from cold, the boot comes
#: first and the save takes over only once the game is up.
LAUNCH_TIP = (
    "Starts the emulator straight into the selected slot.\n\n"
    "From cold, the emulator has to boot first: the game comes up on "
    "screen and runs for a little while (roughly half a minute with "
    "everything warm) before the save state takes over. If the "
    "emulator is already running, the slot loads into it right away — "
    "a load takes about 10–15 seconds either way.")

#: What the box says before any card has been looked at — the same
#: sentence it carried when it was a plain switch.
SELECT_TIP_IDLE = (
    "A multi-image card carries a boot menu: the machine shows it at "
    "power-up and you pick which build to boot with the flipper "
    "buttons.\n\nPick a card and this box fills itself in — ticked when "
    "the card carries a menu, and left alone when it does not.")

#: While the answer is on its way.  Said out loud because the box is
#: showing the PREVIOUS card's answer until it lands.
SELECT_TIP_BUSY = "Looking at the card for a boot menu…"

#: What the opt-in says when it is off, and when it is on.  Two sentences
#: each, and the ON one names the cost: preparing the edits happens at
#: Start and a re-encode is not instant, so a user who ticks this and then
#: waits should have been told that it would happen.
OVR_OFF = ("The card runs exactly as it is. Tick the box to hear and see "
           "the edits in your assets folder without building a new card "
           "image first.")

OVR_ON = ("Your edits are patched into copies of just the card files they "
          "live in, and the emulator reads those instead — the card image "
          "is never written to and nothing is rebuilt. Start prepares "
          "them first, which takes as long as the edits need to be "
          "re-encoded; a set that is already current is reused. A "
          "replacement you picked on a Replace tab counts as an edit "
          "here: Start applies it to your project folder exactly as a "
          "build would, so you do not have to build a card image first.")

OVR_NO_ASSETS = ("There is no assets folder set. Extract the card on the "
                 "Extract tab (or point the Write tab at an existing "
                 "extract) and the edits in it can be run here.")

#: Item 149: where the rig preloads a set's mode runtime from (modes/tryit.sh install).
OVERRIDE_MODE_OBJECT = "/lib/pad_mode.so"

#: playfield.py's own state file, by the same rule playfield.py builds it
#: (``~/.pad_playfield.json``).  Named here rather than imported because
#: that module is a rig script the app never loads - it runs as its own
#: process, on the other side of an interop hop.
PF_STATE = os.path.join(os.path.expanduser("~"), ".pad_playfield.json")


def human(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 1 << 30:
        return "%.1f GB" % (n / float(1 << 30))
    if n >= 1 << 20:
        return "%d MB" % (n // (1 << 20))
    return "%d KB" % max(1, n // (1 << 10))


def plan_sentence(plan):
    """What “Set up emulator…” will do, in one sentence for the notice.

    Built from the plan and not typed out beside it, so the words under the
    button cannot promise something other than what the button runs.
    """
    return ("\nPress “Set up emulator…” and this app will install %s with "
            "%s and start it%s. Colima is the Linux machine that runs the "
            "container, and it works on the macOS versions Docker Desktop "
            "no longer supports."
            % (plan["label"], plan["manager"],
               ", asking for your password once" if plan["admin"] else ""))


def forget_playfield_pos():
    """Drop ``playfield_pos`` from the WINDOWS-side playfield state.

    THE HALF winreset.sh CANNOT REACH, and the split is a property of the
    machine rather than a choice.  Under WSL there is no Tk inside the
    distro at all, so watch.sh launches playfield.py as a *Windows*
    process through interop - its ``~`` is the Windows profile, a home no
    script running inside WSL can see.  On a Linux desktop and in the
    macOS container the playfield is a local Tk process instead, its state
    file sits in the rig's own home, and winreset.sh clears it there; this
    then finds a file that does not exist and does nothing.  So exactly
    one side acts on each platform, and neither has to know which.

    Only that one key: the file holds other playfield state, and taking it
    all would be a second reset nobody asked for.  Returns a line for the
    log, or None when there was nothing to forget.
    """
    try:
        with open(PF_STATE) as f:
            st = json.load(f)
    except Exception:                                   # noqa: BLE001
        return None      # absent, unreadable, or not JSON: leave it alone
    if not isinstance(st, dict):
        return None
    pos = st.pop("playfield_pos", None)
    if pos is None:
        return None
    try:
        with open(PF_STATE, "w") as f:
            json.dump(st, f, indent=1)
    except Exception as exc:                            # noqa: BLE001
        return "could not rewrite %s: %s" % (PF_STATE, exc)
    return "forgot the playfield window position %s" % (pos,)


#: The topper tooltip (a literal in the Tk panel's ``_build_source``).
TOPPER_TIP = (
    "The second screen a topper adds — a Mandalorian's hologram, "
    "a Venom's, a Stranger Things projector. Untick it to run the "
    "machine without one: the window stays shut, and the game "
    "behaves as it does on a cabinet where the topper is not "
    "fitted, which on some titles also takes its topper-only "
    "modes out of play.")

#: The Stern ladder under the notebook while this tab shows
#: (the Tk ``MainWindow.EMULATE_PHASES``).
EMULATE_PHASES = ("Copy card", "Boot", "Node boards", "Ready")


def from_file_question(exc):
    """``runtime_prompt.offer_from_file``'s question and its picker title (the
    same words; that function also installs on the calling thread, so the
    web tab asks with these and installs on a worker)."""
    return ("Install the runtime from a file",
            "%s\n\nIf you can copy %s onto this machine another way, choose "
            "it now - it is checked against the same checksum before "
            "anything is installed.\n\nChoose a file?"
            % (exc, runtime.IMAGE.filename),
            "Choose the downloaded %s" % runtime.IMAGE.filename,
            runtime.IMAGE.filename)
