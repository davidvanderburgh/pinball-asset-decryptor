"""Modes tab - make a game mode of your own, as part of the card project (item 127).

The web port of ``gui/modes_tab.py`` (``ModesPanel``) in the audit's re-hang design: one
list of both kinds (modes made in the form, and modes written in C with a [C] pill), a
five-page editor (Mode | Show | Lights | Sounds | Scoring) holding every control the Tk
tab's sixteen boxes had, a code mode's Code and Assets panes, the game's own modes in a
dialog, the film cutter as a dialog, and a pinned Try it footer ("Try it on" is the
Emulate tab's own card box, ``emulate_card_var``).

WHAT A MODE IS HERE. A folder in the project, ``<project>/modes/<name>/``, holding
``mode.json`` and the mode's own art, clip and sound (:mod:`..plugins.stern.mode_project`).

HOW IT SAVES. Exactly as the Tk tab: every change saves itself half a second after the
person stops typing, to the PROJECT the mode was opened from, and only an EDIT is saved
(opening a mode on another title's card retargets it in the form, never on disk, until the
person edits it; item 148).

The form is ``self.f``: the Tk tab's ``self.v`` variables by the same keys, as plain values
mirrored at ``modes.form`` in the store. The page edits ``modes.f:<key>`` (``ui.set``), a
ticked shot ``shot:<name>``, a shot's own points ``award:<name>``. Everything the tab
decides (open, collect, the retarget words, the greying per title, the stock table, Try it)
is the Tk tab's code, ported; every rule a mode obeys is the plugins' (mode_project,
mode_tryit, code_modes, stock_modes, film_cut), called as the Tk tab called them.
"""

import os
import re
import shutil
import tempfile
import threading

from ...plugins.stern import mode_assets as MA
from ...plugins.stern import mode_project as MP
from ...plugins.stern import mode_tryit as MT
from .. import compat
from .. import modes_filmcut as FCD
from ..modes_reading import TitleReadMixin
from ..modes_stock_remap import StockRemapMixin
from ..modes_stock_rewrite import StockRewriteMixin   # item 161
from ..modes_check import GameCheckMixin
from ..modes_tryit import TryItMixin
from .base import TabService, rpc

SAVE_DELAY_MS = 500

#: the form's fields (the Tk tab's ``self.v`` keys) and their kind
_BOOL_FIELDS = ("screen", "countdown", "lights", "advanced", "stack", "light_shots_on")
_STR_FIELDS = (
    "name", "start_shot", "start_count", "seconds", "award", "screen_title", "panel_color",
    "title_color", "clip", "clip_title", "clip_when", "light_color", "light_on_raw",
    "light_off_raw", "clip_seconds", "art_mode", "end_mode", "start_sound_mode",
    "shot_sound_mode", "music_mode", "sound_shot_every", "starts_policy", "starts_count",
    "cooldown", "light_shots_color", "light_shots_pattern", "priority", "starts_kind",
    "start_event", "ends_kind", "end_event", "award_ladder", "end_shot", "clip_both",
    "clip_both_title", "clip_both_seconds", "restore_after",
    "callout_secs_0", "callout_id_0", "callout_secs_1", "callout_id_1",
    "callout_secs_2", "callout_id_2", "callout_secs_3", "callout_id_3")
_DEFAULTS = {
    "screen": True, "countdown": True, "lights": False, "advanced": False, "stack": True,
    "light_shots_on": False, "panel_color": "#000000", "title_color": "#000000",
    "light_color": "#000000", "light_shots_color": "#000000", "clip": "none",
    "clip_when": "start", "art_mode": "panel", "end_mode": "game",
    "start_sound_mode": "none", "shot_sound_mode": "none", "music_mode": "none",
    "sound_shot_every": "1", "starts_policy": "unlimited", "starts_count": "2",
    "cooldown": "0", "light_shots_pattern": "Blink", "priority": "0", "starts_kind": "shot",
    "ends_kind": "drain", "award_ladder": "rising", "end_shot": "(only when time runs out)",
    "clip_both": "none", "clip_both_seconds": "4", "restore_after": "6",
}


def _blank_form():
    f = {k: "" for k in _STR_FIELDS}
    f.update({k: False for k in _BOOL_FIELDS})
    f.update(_DEFAULTS)
    return f


#: The editor's pages, in the order the page shows them (static/js/tabs/modes.js PAGES).
PAGES = (("mode", "Mode"), ("show", "Show"), ("lights", "Lights"), ("sounds", "Sounds"),
         ("scoring", "Scoring"))

#: Which editor page holds the field each of ``mode_project.validate``'s sentences is about
#: (first match wins, so the specific ones come first). A sentence none of these match (a
#: title the app does not know) names no page.
_PROBLEM_PAGES = tuple((re.compile(rx), page) for rx, page in (
    # Scoring: the first shot's points, the ladder, a shot's own points, the early end
    (r"^The first shot has to be worth something", "scoring"),
    (r"^The award ladder", "scoring"),
    (r"^The per-shot awards|^A per-shot award|own points", "scoring"),
    (r"to end the mode\.$", "scoring"),
    # Sounds: the end sound, the mode's own sounds, the callouts, a sound cut from a film
    (r"^The (end sound|start sound|shot sound|music) file", "sounds"),
    (r"^The shot sound plays", "sounds"),
    (r"^The sound's time in the film|^A sound cut from a film", "sounds"),
    (r"(?i)callout", "sounds"),
    # Lights: the sweep's colour, the lit shots
    (r"^The light colour|lit shots", "lights"),
    # Show: the screen, its colours and picture, both clips, the screen's time, priority
    (r"^The (panel|title) colour|^The screen art file|^The picture's", "show"),
    (r"clip", "show"),
    (r"^The film .* is in the mode's folder", "show"),
    (r"^The screen stays up|^The display priority", "show"),
    # Mode: name, start, time, the shots that score, how often, the events
    (r"^The mode needs a name|^Pick the shot that starts|^It has to (take|run)", "mode"),
    (r"^Pick at least one shot that scores|has no shot called", "mode"),
    (r"^How often it can start|^The wait after it ends", "mode"),
    (r"^A mode (starts|ends) on|^Pick the event that|has no event ", "mode"),
))


def problem_pages(problems):
    """The editor pages (``PAGES`` keys, in page order) that hold what ``problems`` (the
    sentences of ``mode_project.validate``) are about."""
    found = set()
    for text in problems or ():
        for rx, page in _PROBLEM_PAGES:
            if rx.search(text):
                found.add(page)
                break
    return [k for k, _l in PAGES if k in found]


def fix_chip(problems):
    """The list's mark for a mode that cannot be built: the page to open, as the design
    names it ("Show •", "Show +1 •" when another page has something too), or "to fix" when
    no page holds it."""
    pages = problem_pages(problems)
    if not pages:
        return "to fix"
    return dict(PAGES)[pages[0]] + (" •" if len(pages) == 1 else " +%d •" % (len(pages) - 1))


class ModesTab(TitleReadMixin, TryItMixin, GameCheckMixin, StockRemapMixin, StockRewriteMixin, TabService):
    ns = "modes"
    key = "Modes"
    label = "Modes"
    group = "Make"
    icon = "modes"
    #: nothing of this tab is read by the run logic (app.py); the Emulate service calls
    #: :meth:`run_ended`, and the Defaults service may answer ``modes_settings_staged``.
    exports = ()

    LOG_TAG = "[modes] "

    ABOUT_TIP = (
        "Make a game mode of your own: what starts it, how long it runs, which shots "
        "score, and what the display, lights and speakers do while it runs. Modes are "
        "saved in this project and put on the card by Write, like the other tabs' "
        "changes. One runs at a time. With modes on the card, players still log in "
        "to Insider Connected, but the machine sends it no scores, high scores or "
        "achievements: a mode's points are not the game's stock scoring.")

    NAME_TIP = ("What the mode is called. It is the title on its screen and clip unless you "
                "give those their own.")
    AWARD_TIP = ("Points for the first scoring shot. The second pays twice this, the third "
                 "three times, and so on. The game's own scoring is used, so its playfield "
                 "multiplier applies. Advanced can change this: Award ladder Fixed pays every "
                 "shot once, and Points per shot gives a shot its own points.")
    RAW_TIP = ("Replace the colour sweep with light commands of your own, in the game's own "
               "light language. Leave both empty to use the colour above.")
    START_EVENT_TIP = ("Something the game itself does: a ball starting, a multiball starting, "
                       "the skill shot being made. The mode starts the moment the game does it.")
    END_EVENT_TIP = ("The mode ends when the game does this, when its time runs out, or when "
                     "the ball drains, whichever comes first.")
    SCREEN_TITLE_TIP = ("The title on the panel. Empty uses the mode's name. Under it, the "
                        "mode writes what each shot paid, and the total at the end.")
    CLIP_TITLE_TIP = ("The title card's words, over the panel colour with a sweep in the title "
                      "colour. Empty uses the mode's name.")
    COOLDOWN_TIP = ("0 = no wait. The wait runs from the moment the mode ends, and carries on "
                    "through the end of a ball.")
    STARTS_TIP = ("Counted for each player. Once a ball starts again on the player's next "
                  "ball; once a game, and up to N times, start again in the next game.")
    STACK_TIP = ("On: the mode starts whenever its shot is made, even during one of the "
                 "game's own battles or multiballs. Off: it waits until the game's own battle "
                 "or multiball ends, and the next start shot after that starts it.")
    LIT_TIP = ("While the mode runs, the insert in front of every shot that scores (and every "
               "shot with its own points) shows this colour and pattern, over the game's own "
               "light shows; every other insert keeps doing what the game wants. They go back "
               "to the game the moment the mode ends. Blink and Pulse repeat about twice a "
               "second and every 1.6 s; Chase lights one of them at a time.")
    PRIORITY_TIP = ("How the mode's screen and clip sit among the game's own displays while it "
                    "runs, on the game's own scale (1-255). At 180 the game's full-screen shot "
                    "awards wait until the mode ends (on Godzilla: LOOPS and BATTLE IS LIT); its "
                    "jackpots, multiball and battle starts and the tilt warning still come "
                    "through, and the mode's screen is back when they end. Higher holds more "
                    "back (190: starts and jackpots wait too). 0 leaves the game's display order "
                    "as it is.")
    FILM_TIP = ("Cut this mode's clip, its sound or its screen's picture from a video file of "
                "your own (a film, an episode, anything): pick the video, a start time and a "
                "length (up to 30 seconds), and whether to keep its letterbox or fill the "
                "frame. The mode keeps only the cut (clip.mp4, end.wav, art.png), never the "
                "video.")
    STOCK_TIP = (
        "The timers and awards of the modes the game shipped with. Pick a row, type a new "
        "value and press Set. Changes are saved with this project and put on the card by "
        "Write, like the Defaults tab. A timer that is an operator setting is the same number "
        "the Defaults tab shows (a machine still on the game's default takes the new one when "
        "it boots). A "
        "number the game works out in code can't be changed here; the row says why. To rename "
        "a mode, edit its title on the Text tab.")
    SHOW_PARAMS_TIP = ("What each shot pays, a shot that ends the mode early, a clip at both "
                       "ends, callouts at chosen seconds, and how long the screen stays up.")
    SECOND_CLIP_TIP = ("A clip at the OTHER end from the one under Clip: at the end when that "
                       "one plays at the start, and the other way round.")
    CALLOUTS_TIP = ("One of the game's own callouts, by number, when that many seconds are "
                    "left. Pick names the ones measured to play on this game; the countdown "
                    "under Sound adds its own.")
    RESTORE_TIP = ("How long the mode's own screen (Screen, above) shows its total after the "
                   "mode ends. With no screen of its own this does nothing.")

    _OWN_SOUNDS = (("sound_start", "start_sound_mode", "When it starts", "start"),
                   ("sound_shot", "shot_sound_mode", "On a scoring shot", "shot"),
                   ("music", "music_mode", "Music underneath", "music"))
    _LIGHT_PATTERN_WORDS = (("solid", "Solid"), ("blink", "Blink"), ("pulse", "Pulse"),
                            ("chase", "Chase"))
    _PART_SECTIONS = ("lights", "screen", "clip")
    _TWO_COLUMN_SHOTS = 18
    _PROBE_TRIES = 240
    _FILM_PARTS = (("clip", "clip", "a clip"), ("still", "screen", "a picture for the screen"),
                   ("sound", "own_sound", "a sound"))
    PARAM_CALLOUT_ROWS = 4
    PARAM_NEVER = "(only when time runs out)"
    PARAM_SECOND_CLIP = (("none", "None"), ("same", "The same clip"), ("title", "A title card"),
                         ("file", "My video…"))
    CODE_EXAMPLE_SUFFIX = " (code mode)"
    VIDEO_TYPES = [("Videos", "*.mp4 *.mov *.m4v *.mkv *.avi *.webm"), ("All files", "*.*")]
    #: the Tk tab's ttk.Spinbox bounds (from_, to[, step]), keyed by the form field; the
    #: page draws each as a number field with arrows. ``callout_secs`` is the four callout
    #: rows' seconds. (The film dialog's length is bounded by its own ``film.max``.)
    SPINBOXES = {
        "start_count": [1, 20], "seconds": [1, 300], "clip_seconds": [1, 30, "any"],
        "sound_shot_every": [1, 20], "starts_count": [1, MP.STARTS_MAX],
        "cooldown": [0, MP.COOLDOWN_MAX], "priority": [0, 255],
        "clip_both_seconds": [1, 30, "any"], "callout_secs": [0, 300],
        "restore_after": [1, MP.RESTORE_AFTER_MAX],
    }

    def __init__(self, window):
        super().__init__(window)
        self.f = _blank_form()
        self._shot_names = []              # the shown title's shots; none until a card says
        self._shots_on = set()
        self._shot_awards = {n: "" for n in self._shot_names}
        self._slugs = []
        self._found = {}
        self._code_list = []           # [(slug, name)] of the project's code modes
        self._slug = None              # the form mode open in the editor
        self._spec = None
        self._code_slug = None         # the code mode shown instead, or None
        self._open_project = ""
        self._loading = False
        self._dirty = False
        self._save_job = None
        self._params_raw = {}
        self._params_kept_awards = []
        self._params_kept_callouts = []
        self._clip2_file = ""
        self._retarget_note = ""
        self._retarget_saved = None
        self._retarget_refuses = True
        self._at_cap = False
        # the title (item 148): the CARD's, and none until a card says which game it is
        self._profile = None
        self._applied_key = None
        self._card_bound = False
        self._shown = None
        self._no_port = ""
        self._title_note = ""
        self._probing = set()
        self._probe_gave_up = set()
        # the page
        self._tmp = None
        self._preview_rev = 0
        self._preview_path = ""
        self._project_hooked = None
        self._card_hooked = None
        self._ticker_job = None
        self._ticker_on = False
        self._film = None              # the open film dialog's state
        self._film_seq = 0
        self._stock_rows = {}
        self._stock_build = None
        self._stock_order = []
        self._game_mode = None         # the game's own mode shown instead (its id), or None
        self._title_read = None        # the finished read of the shown card, or None
        self._init_tryit()
        self._init_check()
        self._init_reading()
        self.set(project="", project_label="", title_text="", title_note="", no_port="",
                 profile=self._profile_payload(None), rows=[], sel=None, game_rows=[],
                 game_mode=None, title_origin="",
                 cap_text="", new_ok=False, ex_ok=False, dup_ok=False, del_ok=False, copy_ok=False,
                 examples=[], open=False, editor_on=False, form=dict(self.f),
                 shots_on=[], awards=dict(self._shot_awards), shots_text="", status="",
                 save_state="", labels={}, files={}, starts_words="", preview=None,
                 reasons={}, dis={}, code=None, code_words="", cut_ok=False,
                 stock={"msg": "", "rows": [], "on": False, "sel": None, "note": "",
                        "value": "", "row_on": False},
                 film=None, about=self.ABOUT_TIP, n_form=0, n_code=0, ready=False,
                 fix_pages=[], spin=dict(self.SPINBOXES), sdk_doc=self.sdk_doc(),
                 no_port_details="", ex_tip="", own_extra_ok=True, write_waits=False,
                 game_hidden=0, check_offer=False, check_wanted=False, check_done=None,
                 check_tip=self.CHECK_TIP, insider_note="")
        self._show_starts_words()

    # ------------------------------------------------------------------
    # the project and the window
    # ------------------------------------------------------------------
    def _export(self, name):
        """A window attribute another tab EXPORTS, or None: never the window's stand-in
        (asking the window for a missing ``*_var`` would record a gap that is not ours)."""
        svc = (getattr(self.window, "_exports", None) or {}).get(name)
        return getattr(svc, name, None) if svc is not None else None

    def _project_var(self):
        return self._export("write_assets_var") or self._export("extract_output_var")

    def project(self):
        var = self._project_var()
        p = (var.get() if var is not None else "") or ""
        p = p.strip()
        return p if p and os.path.isdir(p) else ""

    def _preview_on(self):
        try:
            return bool(self.window.modes_preview_on())
        except Exception:                                   # noqa: BLE001
            return False

    def _say(self, text):
        msg = self.LOG_TAG + text
        if self._on_loop():
            self.window.append_log(msg)
        else:
            self.ctx.loop.post(self.window.append_log, msg)

    def _hook_vars(self):
        """Follow the project folder and the Emulate tab's card box, as the Tk window's
        traces did. Looked up once every tab exists (after the first manufacturer)."""
        var = self._project_var()
        if var is not None and var is not self._project_hooked:
            self._project_hooked = var
            var.trace_add("write", lambda *_a: self._on_project_changed())
        card = self._export("emulate_card_var")
        if card is not None and card is not self._card_hooked:
            self._card_hooked = card
            card.trace_add("write", lambda *_a: self._post(self._on_try_on_changed))

    def _on_try_on_changed(self):
        """The Emulate tab's card changed: the footer's verdict, and, for a project that
        names no card of its own, which game its modes are for (_title_card)."""
        self._show_emu()
        project = self.project()
        if (project and getattr(self, "_visible", False) and self._preview_on()
                and MP.project_card(project) is None):
            self._save_if_edited()
            self.refresh()
            self.refresh_stock_modes()

    def _post(self, fn, *args):
        if self._on_loop():
            fn(*args)
        else:
            self.ctx.loop.post(fn, *args)

    def _on_project_changed(self):
        if not getattr(self, "_visible", False) or not self._preview_on():
            return
        self._post(self._refresh_all)

    def _refresh_all(self):
        self.refresh()
        self.refresh_stock_modes()
        self.refresh_stock_remap()             # item 160: the counts-as table
        self.refresh_stock_rewrite()           # item 161: the rewrite rows

    # -- hooks ------------------------------------------------------------
    def on_manufacturer(self, mfr):
        self._hook_vars()
        if getattr(self, "_visible", False):
            self._refresh_all()
            self._show_emu()

    def on_show(self):
        """The tab came forward: the list, the code modes and the stock table read again
        (another tab or the person may have changed the modes folder); the open mode is
        reopened only when the project changed or it is gone."""
        self._hook_vars()
        if self.project() != (self.get("project") or "") or (
                self._slug is not None and not os.path.isfile(
                    os.path.join(MP.mode_folder(self._open_project, self._slug), MP.MODE_FILE))):
            self._save_if_edited()
            self.refresh()
        else:
            self._refresh_list()
        self.refresh_stock_modes()
        self._show_emu()
        self._kick_ticker()

    def on_project(self, folder):
        self._on_project_changed()

    def on_close(self):
        self._ticker_on = False
        if self._save_job is not None:
            try:
                self.ctx.loop.after_cancel(self._save_job)
            except Exception:                               # noqa: BLE001
                pass
            self._save_job = None
            if self._dirty:
                try:
                    self.save_now()
                except Exception:                           # noqa: BLE001
                    pass
        if self._film is not None:
            self._film_close()
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)

    def on_field(self, key, value):
        if key.startswith("f:"):
            self._edit(key[2:], value)
        elif key.startswith("shot:"):
            self._edit_shot(key[5:], bool(value))
        elif key.startswith("award:"):
            self._edit_award(key[6:], "" if value is None else str(value))
        elif key == "try_on":
            self._set_try_on(str(value or ""))
        elif key == "leave_out":
            self.set(leave_out=bool(value))
        elif key == "stock_value":
            st = dict(self.get("stock") or {})
            st["value"] = "" if value is None else str(value)
            self.set(stock=st)
        elif key.startswith("film:"):
            self._film_field(key[5:], value)
        else:
            self.set(**{key: value})

    # -- the ticker: Try it's starting -> live, and the emulator's state for the buttons
    def _kick_ticker(self):
        if self._ticker_on:
            return
        self._ticker_on = True
        self._ticker_job = self.ctx.loop.after(150, self._tick)

    def _tick(self):
        self._ticker_job = None
        shown = self.window.ctx.store.get("shell", "tab") == self.ns
        working = self._tryit["state"] in self.TRYIT_WORKING or self._check_working()
        live = self._tryit["state"] == "live"
        if not (shown or working or live):
            self._ticker_on = False
            return
        try:
            self._tryit_tick()
            self._check_tick()
            self._show_emu(quiet=True)
        except Exception:                                   # noqa: BLE001
            pass
        self._ticker_job = self.ctx.loop.after(150 if working else 1000, self._tick)

    # ------------------------------------------------------------------
    # the list
    # ------------------------------------------------------------------
    def refresh(self, select=None, select_code=None, select_game=None):
        """Re-read the project's modes into the list, keeping (or choosing) a selection."""
        project = self.project()
        if self._slug is not None and project != self._open_project:
            self._save_if_edited()
            self._slug, self._spec = None, None
        if project != (self.get("project") or ""):
            self._game_mode = None
        self.set(project=project,
                 project_label=("Saved in %s" % os.path.join(project, MP.MODES_DIRNAME))
                 if project else
                 "Open or extract a card project first (Extract tab) - modes are saved in it.")
        found, broken = MP.list_modes(project) if project else ([], [])
        for slug, err in broken:
            self._say("could not read the mode in %s: %s" % (slug, err))
        self._slugs = [s for s, _ in found]
        self._found = dict(found)
        self._code_list = [(s, n) for s, kind, n in (MT.list_all(project) if project else [])
                           if kind == "code"]
        self._refresh_code_modes(project)
        self._at_cap = bool(project) and len(found) >= MP.MAX_MODES
        self._new_ok = bool(project) and len(found) < MP.MAX_MODES
        self._ex_ok = bool(project)
        self._apply_project_title(project)
        self._show_cap(project, len(found))
        codes = [s for s, _n in self._code_list]
        game = self._game_ids()
        if select_game is not None and select_game in game:
            self._show_game_mode(select_game)
            return
        if (select is None and select_code is None and self._game_mode is not None
                and self._game_mode in game):
            self._show_game_mode(self._game_mode)
            return
        self._game_mode = None
        if select_code in codes:
            self._show_code(select_code)
            return
        if select is None and self._code_slug in codes:
            self._show_code(self._code_slug)
            return
        self._code_slug = None
        want = select if select in self._slugs else (
            self._slug if self._slug in self._slugs else None)
        if want is None and self._slugs:
            want = self._slugs[0]
        if want is None and codes and select is None:
            self._show_code(codes[0])
            return
        if want is None:
            self._slug, self._spec = None, None
            self._blank_form()
            self._set_editor_state(False)
            self.set(status="" if not project else self._no_modes_words(),
                     save_state="", sel=None, code=None, game_mode=None)
            self._note_no_port_in_status()
            self._publish_rows()
            return
        self._open(want, self._found[want])

    def _no_modes_words(self):
        """The empty editor's sentence: what to press, for the shown title."""
        p = self._profile
        if p is None:
            text = "No modes of your own yet."
        elif any(n == "KAIJU RUSH" for n, _s in MP.examples_for(p)):
            text = ("No modes yet. Start from an example (KAIJU RUSH is the one that has run on "
                    "a machine), or make a blank one.")
        else:
            text = "No modes yet. Start from an example, or make a blank one."
        if self._game_ids():
            text += (" The game's own modes are listed under yours: pick one to see and change "
                     "its timers and awards.")
        return text

    def _show_cap(self, project, n):
        if not project:
            text = ""
        elif n >= MP.MAX_MODES:
            text = ("%d of %d modes: delete one to add another. Modes written in C are "
                    "not counted." % (n, MP.MAX_MODES))
        else:
            text = ""                       # the head says "N modes"
        self.set(cap_text=text, n_form=n, n_code=len(self._code_list))
        self._publish_examples()

    def _publish_examples(self):
        """The Examples menu for the CARD's title: Godzilla's four (and its code examples)
        only on Godzilla, a plain starter mode on any other title, nothing with no title."""
        p = self._profile
        items = [{"name": name, "code": False, "disabled": bool(self._at_cap)}
                 for name, _s in (MP.examples_for(p) if p is not None else ())]
        from ...plugins.stern import code_modes as CM
        if self._code_examples_ok():
            for name in CM.example_names():
                items.append({"name": name, "label": name + self.CODE_EXAMPLE_SUFFIX,
                              "code": True, "disabled": False})
        ex_ok = bool(self._ex_ok and not self._no_port)
        self.set(examples=items, new_ok=bool(self._new_ok and not self._no_port), ex_ok=ex_ok,
                 ex_tip="" if ex_ok else (self._no_port or MP.NO_PROJECT_HELP))

    def _code_examples_ok(self):
        """The code examples are Godzilla's (their shots, films and sounds): offered, and
        accepted by the server, only when the card's title is Godzilla."""
        p = self._profile
        return p is not None and str(getattr(p, "game_dir", "")).startswith("godzilla")

    _new_ok = False
    _ex_ok = False
    _ready = False
    _problems = ()

    def _row_chip(self, slug, spec):
        """The list's mark for one form mode, ``(chip, tip)``: the page that holds what
        stops it being built as it would be (retargeted to the card's title the way opening
        it would; the design's "Show •"), "to fix" when no page does, else nothing."""
        if self._no_port or not self._open_project and not self.project():
            return "", ""
        project = self._open_project or self.project()
        try:
            if self._card_bound and self._profile is not None:
                spec, dropped = MP.retarget(spec, self._profile)
                if dropped:
                    # the open mode's own words (_note_retarget_in_status)
                    return "to fix", ("Ready to build once saved: open it, and any edit "
                                      "saves it. Until then its file is unchanged, and a "
                                      "build refuses it.")
            problems = MP.validate(spec, MP.mode_folder(project, slug))
        except Exception:                                   # noqa: BLE001
            return "", ""
        if not problems:
            return "", ""
        return fix_chip(problems), "To fix before it can be built: " + " ".join(problems)

    def _publish_rows(self):
        rows = []
        for slug in self._slugs:
            spec = self._found.get(slug)
            if slug == self._slug and self._spec is not None:
                name = self._spec.name
                if self._no_port:
                    chip, tip = "", ""
                elif self._ready:
                    chip, tip = "ready", "Ready to build."
                else:
                    chip = fix_chip(self._problems) if self._problems else "to fix"
                    tip = self.get("status") or ""
            else:
                name = spec.name if spec is not None else slug
                chip, tip = self._row_chip(slug, spec) if spec is not None else ("", "")
            rows.append({"slug": slug, "kind": "form", "name": name, "chip": chip,
                         "chip_tip": tip})
        for slug, name in self._code_list:
            chip, tip = "", ""
            try:                                   # item 161: a code mode that rewrites one of the game's rules
                from ...plugins.stern import stock_rewrite as SW
                port = self._remap_port()[0] if self.project() else ""
                tip = SW.describe_suffix(self.project(), slug, port or None).strip(" -")
                chip = "rewrite" if tip else ""
            except Exception:                      # noqa: BLE001 - the list must never fail on a chip
                chip, tip = "", ""
            rows.append({"slug": slug, "kind": "code", "name": name, "chip": chip,
                         "chip_tip": tip})
        sel = ({"slug": str(self._game_mode), "kind": "game"} if self._game_mode is not None else
               {"slug": self._code_slug, "kind": "code"} if self._code_slug else
               {"slug": self._slug, "kind": "form"} if self._slug else None)
        self.set(rows=rows, sel=sel, game_rows=self._game_rows())

    @rpc
    def select(self, slug, kind="form"):
        """A row of the list was picked: one of the person's modes (``form``), a code mode
        (``code``) or one of the game's own modes (``game``, ``slug`` its id)."""
        if kind == "game":
            try:
                mode_id = int(slug)
            except (TypeError, ValueError):
                return False
            if mode_id not in self._game_ids():
                return False
            if self._game_mode == mode_id:
                return True
            self._save_if_edited()
            self._show_game_mode(mode_id)
            return True
        if kind == "code":
            if self._code_slug == slug:
                return True
            self._save_if_edited()
            self._show_code(slug)
            return True
        if slug == self._slug and self._code_slug is None and self._game_mode is None:
            return True
        self._save_if_edited()
        found = dict(MP.list_modes(self.project())[0])
        if slug in found:
            self._code_slug = None
            self._game_mode = None
            self._open(slug, found[slug])
        return True

    @rpc
    def refresh_now(self):
        self._save_if_edited()
        self._refresh_all()
        return True

    # ------------------------------------------------------------------
    # the form <-> the spec
    # ------------------------------------------------------------------
    def _publish_form(self):
        self.set(form=dict(self.f), shots_on=[n for n in self._shot_names if n in self._shots_on],
                 awards=dict(self._shot_awards))

    def _open(self, slug, spec):
        spec = self._retarget_for_title(spec)
        self._slug, self._spec = slug, spec
        self._code_slug = None
        self._game_mode = None
        self._open_project = self.project()
        self._loading = True
        try:
            f = self.f
            for key in ("name", "start_shot", "screen_title", "panel_color", "title_color",
                        "clip", "clip_title", "clip_when", "light_color", "light_on_raw",
                        "light_off_raw"):
                f[key] = str(getattr(spec, key) or "")
            for key in ("start_count", "seconds", "award"):
                try:
                    f[key] = str(int(getattr(spec, key)))
                except (TypeError, ValueError):
                    f[key] = str(getattr(spec, key))
            try:
                f["clip_seconds"] = "%g" % float(spec.clip_seconds)
            except (TypeError, ValueError):
                f["clip_seconds"] = str(spec.clip_seconds)
            for key in ("screen", "countdown", "lights"):
                f[key] = bool(getattr(spec, key))
            f["art_mode"] = "file" if spec.screen_art else "panel"
            f["end_mode"] = "file" if spec.end_sound else "game"
            f["advanced"] = bool(spec.light_on_raw or spec.light_off_raw)
            self._shots_on = {n for n in self._shot_names if n in spec.scoring_shots}
            self._open_own_sounds(spec)
            self._open_starts(spec)
            f["stack"] = bool(getattr(spec, "stack", True))
            self._open_advanced(spec)
            self._open_trigger(spec)
            self._open_display_lights(spec)
        finally:
            self._loading = False
        self._publish_form()
        self._set_editor_state(True)
        self._dirty = False
        self.set(save_state="saved", code=None, game_mode=None)
        self._after_change()

    def collect(self):
        """The form as a ModeSpec (the one being edited, updated in place)."""
        spec = self._spec
        if spec is None:
            return None

        def num(key, cast=int):
            try:
                return cast(str(self.f[key]).replace(",", "").strip())
            except ValueError:
                return 0

        for key in ("name", "start_shot", "screen_title", "panel_color", "title_color", "clip",
                    "clip_title", "clip_when", "light_color", "light_on_raw", "light_off_raw"):
            setattr(spec, key, self.f[key])
        spec.start_count, spec.seconds, spec.award = num("start_count"), num("seconds"), num("award")
        spec.clip_seconds = num("clip_seconds", float)
        for key in ("screen", "countdown", "lights"):
            setattr(spec, key, bool(self.f[key]))
        spec.scoring_shots = [n for n in self._shot_names if n in self._shots_on]
        if self.f["art_mode"] != "file":
            spec.screen_art = ""
        if self.f["end_mode"] != "file":
            spec.end_sound = ""
        if not self.f["advanced"]:
            spec.light_on_raw = spec.light_off_raw = ""
        self._collect_own_sounds(spec)
        spec.starts, spec.cooldown = self._form_starts()
        spec.stack = bool(self.f["stack"])
        self._collect_advanced(spec)
        self._collect_trigger(spec)
        self._collect_display_lights(spec)
        return spec

    # -- one edit from the page (a Tk variable's trace) ---------------------------------
    def _edit(self, key, value):
        if key not in self.f:
            return False
        if key in _BOOL_FIELDS:
            value = bool(value)
        else:
            value = "" if value is None else str(value)
        if self.f.get(key) == value:
            # the page re-sends a field on blur; a Tk entry wrote its variable only when the
            # text changed, and only an EDIT is saved (item 148)
            return False
        self.f[key] = value
        self._publish_form()
        if key in ("award_ladder", "end_shot", "clip_both"):
            self._params_raw.pop(key, None)       # a control the user sets forgets its raw value
        if key in ("starts_policy", "starts_count", "cooldown"):
            self._show_starts_words()
        self._changed()
        return True

    def _edit_shot(self, name, on):
        if name not in self._shot_names or (name in self._shots_on) == bool(on):
            return False
        if on:
            self._shots_on.add(name)
        else:
            self._shots_on.discard(name)
        self._publish_form()
        self._changed()
        return True

    def _edit_award(self, name, text):
        if name not in self._shot_awards or self._shot_awards[name] == text:
            return False
        self._shot_awards[name] = text
        self._publish_form()
        self._changed()
        return True

    @rpc
    def set_shots(self, names):
        """All / None over the shots that score (one edit)."""
        want = {n for n in (names or []) if n in self._shot_names}
        if want == self._shots_on:
            return False
        self._shots_on = want
        self._publish_form()
        self._changed()
        return True

    def _changed(self):
        if self._loading or self._spec is None:
            return
        self._dirty = True
        self.set(save_state="editing")
        if self._save_job is not None:
            self.ctx.loop.after_cancel(self._save_job)
        self._save_job = self.ctx.loop.after(SAVE_DELAY_MS, self.save_now)

    def save_now(self):
        """Save the mode being edited, now. Called by the debounce and before switching."""
        if self._save_job is not None:
            try:
                self.ctx.loop.after_cancel(self._save_job)
            except Exception:                               # noqa: BLE001
                pass
        self._save_job = None
        project = self._open_project
        if not project or not os.path.isdir(project) or self._slug is None or self._spec is None:
            return
        if self._no_port:
            return                          # item 148: shown read-only, nothing to save
        spec = self.collect()
        MP.save(project, self._slug, spec)
        self._dirty = False
        self.set(save_state="saved")
        if self._retarget_note:
            self._retarget_saved = self._slug
        self._found[self._slug] = spec
        self._after_change()
        self._tryit_saved(project, self._slug, spec)

    def _save_if_edited(self):
        if self._dirty:
            self.save_now()
        elif self._save_job is not None:
            self.ctx.loop.after_cancel(self._save_job)
            self._save_job = None

    def _after_change(self):
        spec = self.collect()
        folder = (MP.mode_folder(self._open_project, self._slug)
                  if self._open_project and self._slug else None)
        problems = MP.validate(spec, folder) if spec else []
        status = ("Ready to build." if not problems
                  else "To fix before it can be built: " + " ".join(problems))
        self._problems = list(problems)
        # buildable as it is on disk: no problem, and not a retargeted mode whose file a
        # build refuses until an edit saves it (a moved callout alone refuses nothing)
        self._ready = bool(spec is not None and not problems and not (
            self._retarget_note and self._retarget_refuses
            and self._retarget_saved != self._slug))
        labels = {
            "art": spec.screen_art and "Picture: %s" % spec.screen_art or "",
            "clip": spec.clip == "file" and spec.clip_file and "Video: %s" % spec.clip_file or "",
            "sound": self._end_sound_words(spec),
            "clip2": self._clip2_file and "Video: %s" % self._clip2_file or "",
            "film": FCD.describe(spec) or "Nothing cut from a video yet.",
        }
        for attr, _mv, _w, _s in self._OWN_SOUNDS:
            name = getattr(spec, attr)
            labels[attr] = name and "Sound: %s" % name or ""
        files = {}
        if folder:
            for key, name in (("art", spec.screen_art), ("clip", spec.clip_file),
                              ("end", spec.end_sound), ("sound_start", spec.sound_start),
                              ("sound_shot", spec.sound_shot), ("music", spec.music),
                              ("clip2", self._clip2_file)):
                path = os.path.join(folder, name) if name else ""
                files[key] = path if path and os.path.isfile(path) else ""
        self.set(status=status, labels=labels, files=files, folder=folder or "",
                 ready=bool(self._ready and not self._no_port),
                 fix_pages=[] if self._no_port else problem_pages(problems))
        self._update_preview(spec, folder)
        self._note_no_port_in_status()
        self._note_retarget_in_status()
        self._publish_rows()

    def _end_sound_words(self, spec):
        if spec is None or not spec.end_sound:
            return ""
        carried = None
        project = self._open_project
        if project and self._slug:
            try:
                from ...plugins.stern import mode_write as MW
                modes = [(slug, spec if slug == self._slug else s)
                         for slug, s in MP.list_modes(project)[0]]
                if self._slug not in dict(modes):
                    modes.append((self._slug, spec))
                carried = MW.choose_end_sound(project, modes, (True, ""),
                                              log=lambda *a, **k: None)
            except Exception:                               # noqa: BLE001
                carried = None
        if carried is None or carried.get("slug") == self._slug:
            return "Sound: %s (put on the card by Write)" % spec.end_sound
        return ("Sound: %s (not on the card: a card carries one end sound, and %s's is it)"
                % (spec.end_sound, carried.get("name") or carried.get("slug")))

    def _tmpdir(self):
        if not self._tmp or not os.path.isdir(self._tmp):
            self._tmp = tempfile.mkdtemp(prefix="pad-modes-")
        return self._tmp

    def _update_preview(self, spec, folder):
        """The screen's thumbnail: the generated panel or the picture, as a PNG the page
        shows (the Tk tab's 360x120 thumbnail, drawn at twice that for sharp screens)."""
        old = self._preview_path
        try:
            from PIL import Image
            if not spec.screen:
                self.set(preview=None)
                self._preview_path = ""
                return
            if spec.screen_art and folder and os.path.isfile(os.path.join(folder, spec.screen_art)):
                arr = MA.load_art(os.path.join(folder, spec.screen_art))
            else:
                arr = MA.panel_art(spec.screen_title or spec.name, spec.panel_color, spec.title_color)
            img = Image.fromarray(arr)
            img.thumbnail((720, 240))
            self._preview_rev += 1
            path = os.path.join(self._tmpdir(), "preview-%d.png" % self._preview_rev)
            img.save(path)
            self._preview_path = path
            self.set(preview={"path": path, "w": img.width, "h": img.height})
        except (ValueError, OSError, ImportError):
            self._preview_path = ""
            self.set(preview={"path": "", "text": "(no preview)"})
        if old and old != self._preview_path:
            try:
                os.remove(old)
            except OSError:
                pass

    # -- the parts of the form (the Tk tab's _open_* / _collect_* pairs) ----------------
    def _open_own_sounds(self, spec):
        for attr, mode_var, _words, _stem in self._OWN_SOUNDS:
            self.f[mode_var] = "file" if getattr(spec, attr) else "none"
        try:
            self.f["sound_shot_every"] = str(max(1, int(spec.sound_shot_every or 1)))
        except (TypeError, ValueError):
            self.f["sound_shot_every"] = str(spec.sound_shot_every)

    def _collect_own_sounds(self, spec):
        for attr, mode_var, _words, _stem in self._OWN_SOUNDS:
            if self.f[mode_var] != "file":
                setattr(spec, attr, "")
        try:
            spec.sound_shot_every = int(str(self.f["sound_shot_every"]).strip())
        except ValueError:
            spec.sound_shot_every = 0

    def _form_starts(self):
        policy = self.f["starts_policy"]
        if policy == "count":
            text = str(self.f["starts_count"]).strip()
            starts = int(text) if text.isdigit() else text
        else:
            starts = policy
        text = str(self.f["cooldown"]).strip()
        cooldown = int(text) if text.isdigit() else (text or 0)
        return starts, cooldown

    def _show_starts_words(self):
        starts, cooldown = self._form_starts()
        self.set(starts_words=MP.starts_words(MP.ModeSpec(starts=starts, cooldown=cooldown)))

    def _open_starts(self, spec):
        starts = spec.starts
        if isinstance(starts, int) and not isinstance(starts, bool):
            self.f["starts_policy"] = "count"
            self.f["starts_count"] = str(starts)
        else:
            self.f["starts_policy"] = starts if starts in MP.STARTS_POLICIES else "unlimited"
        self.f["cooldown"] = str(spec.cooldown)
        self._show_starts_words()

    def _open_display_lights(self, spec):
        colour = spec.light_shots if isinstance(spec.light_shots, str) else ""
        self.f["light_shots_on"] = bool(colour)
        self.f["light_shots_color"] = colour or "#ff6000"
        words = dict(self._LIGHT_PATTERN_WORDS)
        self.f["light_shots_pattern"] = words.get(spec.light_shots_pattern, spec.light_shots_pattern)
        self.f["priority"] = str(spec.priority)

    def _collect_display_lights(self, spec):
        keys = {w: k for k, w in self._LIGHT_PATTERN_WORDS}
        spec.light_shots = self.f["light_shots_color"] if self.f["light_shots_on"] else ""
        shown = self.f["light_shots_pattern"]
        spec.light_shots_pattern = keys.get(shown, shown)
        text = str(self.f["priority"]).strip()
        spec.priority = int(text) if text.isdigit() else (text or 0)

    # item 147: what starts it and what ends it
    def _event_choices(self):
        """(label, name) for the events the shown title's port carries; none when no title
        is shown or its port names none (another title's events are never offered)."""
        p = self._shown or self._profile
        events = p.events if p is not None else ()
        return [(MP.EVENT_LABELS.get(n, n), n) for n in events or ()]

    def _open_trigger(self, spec):
        by_name = {n: label for label, n in self._event_choices()}
        by_name.update({n: label for n, label in MP.EVENT_LABELS.items() if n not in by_name})
        start = MP.starts_on_event(spec)
        self.f["starts_kind"] = "event" if start else "shot"
        self.f["start_event"] = by_name.get(start, start or "")
        kind, name = MP.ends_on_parts(spec)
        self.f["ends_kind"] = kind if kind in ("drain", "clock", "event") else "drain"
        self.f["end_event"] = by_name.get(name, name or "")

    def _collect_trigger(self, spec):
        by_label = {label: n for n, label in MP.EVENT_LABELS.items()}
        by_label.update({label: n for label, n in self._event_choices()})

        def name_of(key):
            value = str(self.f[key]).strip()
            return by_label.get(value, value)

        if self.f["starts_kind"] == "event":
            spec.starts_on = ("event %s" % name_of("start_event")).strip()
        else:
            spec.starts_on = "shot"
        kind = self.f["ends_kind"]
        spec.ends_on = ("event %s" % name_of("end_event")).strip() if kind == "event" \
            else (kind or "drain")

    # item 141: every other parameter the runtime has
    def _open_advanced(self, spec):
        names = set(self._shot_names)

        def named(shot):
            return isinstance(shot, str) and shot in names

        raw = {}
        self._params_raw = {}
        if spec.award_ladder not in MP.AWARD_LADDERS:
            raw["award_ladder"] = spec.award_ladder
        self.f["award_ladder"] = spec.award_ladder if spec.award_ladder in MP.AWARD_LADDERS \
            else "rising"
        awards = spec.shot_award if isinstance(spec.shot_award, list) else []
        shown, self._params_kept_awards = {}, []
        for r in awards:
            if isinstance(r, (list, tuple)) and len(r) == 2 and named(r[0]) and r[0] not in shown:
                shown[r[0]] = r[1]
            else:
                self._params_kept_awards.append(r)
        self._shot_awards = {n: ("" if n not in shown else str(shown[n]))
                             for n in self._shot_names}
        if spec.end_shot and not named(spec.end_shot):
            raw["end_shot"] = spec.end_shot
        self.f["end_shot"] = spec.end_shot if named(spec.end_shot) else self.PARAM_NEVER
        both = spec.clip_both if isinstance(spec.clip_both, dict) else {}
        kind = both.get("clip") if both.get("clip") in MP.SECOND_CLIP_KINDS else "none"
        if spec.clip_both and kind == "none":
            raw["clip_both"] = spec.clip_both
        self.f["clip_both"] = kind
        self.f["clip_both_title"] = str(both.get("title", "") or "")
        secs = both.get("seconds", 4.0)
        self.f["clip_both_seconds"] = ("%g" % float(secs) if isinstance(secs, (int, float))
                                       else str(secs))
        self._clip2_file = both.get("file", "") or ""
        calls = spec.callout_at if isinstance(spec.callout_at, list) else []
        rows = [r for r in calls if isinstance(r, (list, tuple)) and len(r) == 2][
            :self.PARAM_CALLOUT_ROWS]
        self._params_kept_callouts = [r for r in calls if not any(r is s for s in rows)]
        for i in range(self.PARAM_CALLOUT_ROWS):
            row = rows[i] if i < len(rows) else ("", "")
            self.f["callout_secs_%d" % i] = str(row[0])
            self.f["callout_id_%d" % i] = str(row[1])
        self.f["restore_after"] = str(spec.restore_after)
        self._params_raw = raw

    def _collect_advanced(self, spec):
        def number(text, cast=int):
            s = str(text).replace(",", "").strip()
            try:
                return cast(s)
            except ValueError:
                return s

        spec.award_ladder = self.f["award_ladder"]
        spec.shot_award = [[name, number(self._shot_awards.get(name, ""))]
                           for name in self._shot_names
                           if str(self._shot_awards.get(name, "")).strip()] \
            + list(self._params_kept_awards)
        end = self.f["end_shot"]
        spec.end_shot = "" if end == self.PARAM_NEVER else end
        kind = self.f["clip_both"]
        if kind == "same":
            spec.clip_both = {"clip": "same"}
        elif kind == "title":
            spec.clip_both = {"clip": "title", "title": self.f["clip_both_title"],
                              "seconds": number(self.f["clip_both_seconds"], float)}
        elif kind == "file":
            spec.clip_both = {"clip": "file", "file": self._clip2_file}
        else:
            spec.clip_both = {}
        rows = []
        for i in range(self.PARAM_CALLOUT_ROWS):
            secs, cid = self.f["callout_secs_%d" % i], self.f["callout_id_%d" % i]
            if str(secs).strip() or str(cid).strip():
                rows.append([number(secs), number(cid)])
        spec.callout_at = rows + list(self._params_kept_callouts)
        spec.restore_after = number(self.f["restore_after"])
        for key, raw in self._params_raw.items():
            setattr(spec, key, raw)

    def _blank_form(self):
        """No mode open: the greyed form shows no values of the mode that was open before."""
        for key in ("name", "start_shot", "start_count", "seconds", "award", "screen_title",
                    "clip_title", "clip_seconds", "light_on_raw", "light_off_raw",
                    "clip_both_title"):
            self.f[key] = ""
        for i in range(self.PARAM_CALLOUT_ROWS):
            self.f["callout_secs_%d" % i] = ""
            self.f["callout_id_%d" % i] = ""
        self._shots_on = set()
        self._shot_awards = {n: "" for n in self._shot_names}
        self._clip2_file = ""
        self._publish_form()
        self.set(labels={}, files={}, preview=None)
        self._preview_path = ""

    def _blank_spec(self):
        """A new mode for the CARD's title. There is no default game: with no title (no
        card, or a card whose build has no port) the refusal says why."""
        if self._profile is None or self._no_port:
            raise MP.ModeProjectError(self._no_port or MP.NO_CARD_HELP)
        return MP.blank_spec(self._profile)

    # ------------------------------------------------------------------
    # the title: which card, which port (item 148)
    # ------------------------------------------------------------------
    def _profile_payload(self, p):
        """What the page needs of the shown title: its shots (and how many columns they
        take), the events the start and end lists offer, the measured callouts Pick
        offers, and the early-ending shot list (the Tk tab rebuilt each of these per
        title in _apply_profile and _apply_profile_to_advanced). ``p`` None: no title."""
        if p is None:
            return {"key": "", "label": "", "port": "", "shots": [], "cols": 2,
                    "callouts": [], "callouts_none": "", "events": [],
                    "end_shots": [self.PARAM_NEVER]}
        names = [n for n, _m in p.shots]
        choices = [{"label": "%s (%d)" % (label, number), "number": number}
                   for label, number in MP.callout_choices(p) if number]
        events = [MP.EVENT_LABELS.get(n, n) for n in (p.events or ())]
        return {"key": p.key, "label": p.label, "port": p.port, "shots": names,
                "cols": 2 if len(names) <= self._TWO_COLUMN_SHOTS else 3,
                "callouts": choices,
                "callouts_none": ("" if choices else
                                  "(no callouts measured on %s: type an id)" % p.label),
                "events": events, "end_shots": [self.PARAM_NEVER] + names}

    #: the note on a port the app worked out itself and no Try it has run yet: Write leaves
    #: the modes off a card until one has (mode_write.card_refusal)
    DERIVED_UNPROVEN = ("Check this game (or press Try it) once first: the app worked out by "
                        "itself how to run modes on %s, and until the game has run with them on "
                        "this PC, Write leaves them off the card.")
    #: ... and once a Try it ran the game with it live
    DERIVED_RAN = ("The app worked out by itself how to run modes on %s, and the game has run "
                   "with them on this PC (Check this game or Try it), so Write puts them on the "
                   "card. Try each mode before you trust it on a machine.")
    #: the status and the grey form's words while the card is being read
    READING_WORDS = "Reading which game build the card is, and what it offers (see above)."

    def _title_card(self, project):
        """``(card, via)``: the card whose game the modes are for. The project's own card
        (mode_project.project_card); a project that names none takes the "Try it on" card
        (the Emulate tab's), so a bare folder can still be pointed at a game. Never opens
        an image."""
        card = MP.project_card(project) if project else None
        if card is not None or not project:
            return card, "project"
        var = self._export("emulate_card_var")
        path = ((var.get() if var is not None else "") or "").strip().strip('"')
        if not path:
            return None, ""
        try:
            _made, run = MP.project_cards(project, path)
        except Exception:                                   # noqa: BLE001
            run = None
        if run is None or not run.game_dir:
            return None, ""
        return MP.ProjectCard(run.image, run.game_dir, run.version,
                              "the \"Try it on\" card's %s" % (run.source or "file name")), "try_on"

    def _profile_of_read(self, tr, label):
        """``(profile, why, note)`` from a finished read: the profile of the port it found
        (shipped or worked out on this machine), else None and why in words."""
        if not tr.port_path:
            return None, MP.no_port_words(label, tr.port_missing), ""
        try:
            prof = MP.remember_profile(MP.profile_from_port(tr.port_path))
        except MP.ModeProjectError as e:
            self._say("the app's port for %s cannot be used: %s" % (label, e))
            return None, ("Modes of your own can't be made for %s yet: what the app worked out "
                          "for it cannot be used (the log says why)." % label), ""
        if tr.port_origin == "derived" and not tr.port_proven:
            return prof, "", self._with_switch_note(self._derived_words(prof), prof)
        return prof, "", self._port_note(prof)

    def _derived_words(self, profile):
        from ...plugins.stern import mode_write as MW
        return (self.DERIVED_UNPROVEN if MW.derived_not_run(profile)
                else self.DERIVED_RAN) % profile.label

    def _port_note(self, profile):
        """The unproven note for a port found before (or without) a read: a port outside the
        shipped folder was worked out on this machine, and nothing has run it yet, whatever
        its header says."""
        if os.path.isabs(profile.port or ""):
            note = self._derived_words(profile)
        else:
            checked = self._check_record(profile)
            note = ("" if profile.proven or (checked is not None and checked.ok)
                    else "Unproven: " + profile.proven_note)
        return self._with_switch_note(note, profile)

    @staticmethod
    def _with_switch_note(note, profile):
        """*note* with the port's own word on its switch-line shots, when it has one."""
        extra = str(getattr(profile, "switch_shots_note", "") or "").strip()
        if not extra:
            return note
        return (note + " " + extra).strip() if note else "Unproven: " + extra

    def _apply_project_title(self, project):
        """Which game the modes are for, from the CARD, and what that build offers. There is
        no default game: a project with no card, a card that cannot be read and a build with
        no port all leave the form greyed with the reason in words."""
        card, via = self._title_card(project)
        profile, text, note, no_port = None, "", "", ""
        self._title_read = None
        origin = ""
        if card is None:
            if project:
                no_port = note = MP.NO_CARD_HELP     # said once, in the note (the head: counts)
            self._clear_reading()
        elif not card.game_dir:
            probed = MP.probed_card_title(card.image) if card.image else None
            if (probed is None and card.image and os.path.isfile(card.image)
                    and card.image not in self._probe_gave_up):
                self._probe_card(card.image)
                text = "Card: %s. Reading which game it is from the card..." % MP.file_name(card.image)
                no_port = "Reading which game the card is."
            else:
                text = ("Card: %s. Which game it is could not be read, so modes cannot be made "
                        "for it." % MP.file_name(card.image))
                no_port = note = text
        else:
            name = MP.file_name(card.image)
            label = MP.title_label(card.game_dir, card.version)
            kind, got = self.title_read(card)
            why = ""
            if kind == "done":
                self._title_read = got
                profile, why, note = self._profile_of_read(got, label)
                origin = got.port_origin
            else:
                # a port already on this machine (shipped, or worked out earlier) is used at
                # once; a read that runs meanwhile only adds what it finds
                profile = MP.profile_for_card(card.game_dir, card.version)
                if profile is not None:
                    note = self._port_note(profile)
                    origin = "shipped" if not os.path.isabs(profile.port) else "derived"
                elif kind == "reading":
                    why = self.READING_WORDS
                elif kind == "failed":
                    why = "The card could not be read, so modes cannot be made for it: %s" % got
                elif kind == "cancelled":
                    why = ("Reading %s was stopped, so which build it is and what it offers is "
                           "not known yet. Press Read again to finish it." % label)
                else:
                    why = MP.no_port_words(label)
            if profile is None:
                text = "Card: %s, %s (from %s)." % (name, label, card.source)
                no_port = why
                note = "" if kind in ("reading", "cancelled", "failed") else why
            else:
                text = ("Card: %s, %s (from %s). Modes of your own use its %d shots."
                        % (name, profile.label, card.source, len(profile.shots)))
            if kind == "none" or (self.get("reading") or {}).get("card") not in ("", None, name):
                self._clear_reading()          # nothing read here, or another card's words
        insider_note = ""
        if profile is not None and not profile.insider_gate:
            no_port = note = MP.insider_gate_words(profile.label)   # item 166: no gate, no modes
        elif profile is not None:
            insider_note = MP.INSIDER_NOTE
        self._no_port = no_port
        self._profile = profile
        self._card_bound = bool(card is not None and card.game_dir and profile is not None)
        self._shown = None
        self._stock_build = self._stock_build_for(project)
        details = ""
        if (no_port and no_port == note and card is not None and card.game_dir
                and kind not in ("reading", "cancelled", "failed")):
            # a card with no port: what still works, and the SDK pointer in a tooltip
            details = MP.NO_PORT_DETAILS
            if self._game_ids():
                note = "%s %s" % (note, MP.NO_PORT_STILL)
        self._title_note = note
        from ...plugins.stern import mode_write as MW
        checked = self._check_record(profile)
        self.set(check_offer=bool(profile is not None and not no_port),
                 check_wanted=bool(profile is not None and not no_port and (
                     MW.derived_not_run(profile) or not (profile.proven or (
                         checked is not None and checked.ok)))),
                 check_done=(None if checked is None else {
                     "ok": checked.ok, "when": checked.when,
                     "text": checked.summary(profile.label)}))
        self.set(title_text=text, title_note=note, no_port=no_port, title_origin=origin,
                 no_port_details=details,
                 own_extra_ok=bool(profile is not None and not self._own_extra_why(profile)),
                 card_label=(MP.title_label(card.game_dir, card.version)
                             if card is not None and card.game_dir else ""),
                 write_waits=bool(profile is not None and MW.derived_not_run(profile)),
                 title_via=via, no_card=no_port == MP.NO_CARD_HELP,
                 title_label=profile.label if profile is not None else "",
                 title_port=MP.file_name(profile.port) if profile is not None else "",
                 title_shots=len(profile.shots) if profile is not None else 0,
                 insider_note=insider_note)
        if profile is not None and profile.key != self._applied_key:
            self._apply_profile(profile)
        elif profile is None:
            self._clear_shots()         # an open mode shows its own title again (_open)
        self._grey_what_the_title_cannot(self._spec is not None)

    def _probe_card(self, image):
        """Read a renamed card's title from its own index, OFF the UI loop (it opens the
        image), then refresh. The answer is cached in mode_project."""
        if image in self._probing:
            return
        self._probing.add(image)
        threading.Thread(target=MP.probe_card_title, args=(image,), daemon=True,
                         name="modes-card-probe").start()
        self.ctx.loop.after(250, self._poll_probe, image, 0)

    def _poll_probe(self, image, tries=0):
        if (MP.probed_card_title(image) is None and os.path.isfile(image)
                and tries < self._PROBE_TRIES):
            self.ctx.loop.after(250, self._poll_probe, image, tries + 1)
            return
        self._probing.discard(image)
        if MP.probed_card_title(image) is None:
            self._probe_gave_up.add(image)
        self.refresh()

    def _apply_profile(self, p, said=None):
        """Show title ``p``: its shots, and the ready-made modes of the card's title under
        Examples."""
        names = [n for n, _m in p.shots]
        self._shot_names = names
        self._shots_on = {n for n in self._shots_on if n in names}
        self._shot_awards = {n: self._shot_awards.get(n, "") for n in names}
        self._applied_key = p.key
        self._say(said or "modes here are for %s: %d shots, from %s" % (p.label, len(names), p.port))
        self.set(profile=self._profile_payload(p), shots_text="")
        self._publish_form()
        self._publish_examples()

    def _clear_shots(self):
        """No title to show (no card, a card being read, or a build with no port): no shot
        names at all, no events, no callouts."""
        self._shot_names = []
        self._shots_on = set()
        self._shot_awards = {}
        self.f["start_shot"] = ""
        self._applied_key = None
        if self._no_port in (self.READING_WORDS, "Reading which game the card is."):
            words = "(no shots yet: reading which game the card is)"
        elif self._no_port == MP.NO_CARD_HELP:
            words = "(no shots: this project names no card)"
        else:
            words = "(no shots: modes of your own can't be made for this card yet)"
        self.set(profile=self._profile_payload(None), shots_text=words)
        self._publish_form()
        self._publish_examples()

    def _set_editor_state(self, on):
        self._editor_open = bool(on)
        self.set(open=bool(on))
        self._grey_what_the_title_cannot(on)

    _editor_open = False

    def _grey_what_the_title_cannot(self, on=True):
        """Each part the title cannot do is greyed, with the reason in words; a card with no
        port shows the open mode read-only (Delete stays). No title at all greys every part."""
        p = self._shown or self._profile
        on = bool(on) and self._spec is not None
        if p is None:
            dis = {k: True for k in ("screen", "clip", "lights", "countdown", "own_sound",
                                     "end_game", "clip_both", "stack", "events", "film_clip",
                                     "film_still", "film_sound", "own_extra", "lit_shots",
                                     "show_order")}
            self.set(reasons={}, dis=dis, editor_on=False, dup_ok=False,
                     del_ok=bool(on or self._code_slug))
            return
        reasons, dis = {}, {}
        for part in self._PART_SECTIONS:
            why = p.why_not(part)
            dis[part] = bool(why)
            if why:
                reasons[part] = "Not on this game: " + why
        sound = []
        dis["countdown"] = bool(p.why_not("countdown"))
        if dis["countdown"]:
            sound.append(p.why_not("countdown"))
        dis["own_sound"] = bool(p.why_not("own_sound"))
        dis["end_game"] = not p.callout_time_up
        if not p.callout_time_up:
            sound.append("The app does not know %s's time-up callout, so nothing plays when time "
                         "is up and a sound of the mode's own has no call to replace." % p.label)
        elif p.why_not("own_sound"):
            sound.append(p.why_not("own_sound"))
        if sound:
            reasons["sound"] = "Not on this game: " + " ".join(sound)
        why = self._own_extra_why(p)
        dis["own_extra"] = bool(why)
        if why:
            reasons["own_extra"] = "Not on this game yet: " + why
        why = "" if why else self._own_music_why(p)
        dis["own_music"] = bool(why)
        if why:
            reasons["own_music"] = "Not on this game yet: " + why
        dis["lit_shots"] = getattr(p, "lamps", -1) == 0
        if dis["lit_shots"]:
            reasons["lit_shots"] = ("Not on this game yet: the app does not know which light is in "
                                    "front of each of %s's shots, so none can be lit." % p.label)
        # a mode's screen and clip are what "stays up" and "priority" act on: with neither,
        # the whole Show page is one sentence and those two grey with it
        dis["show_order"] = bool(dis["screen"] and dis["clip"])
        if dis["show_order"]:
            reasons["show_all"] = (
                "Not on this game yet: a mode cannot show a screen or a clip of its own on %s. "
                "It still scores, counts down and ends as set on the other pages." % p.label)
            reasons["show_order"] = ("Not on this game yet: these act on a mode's own screen and "
                                     "clip, and %s cannot show either." % p.label)
        note = getattr(p, "sound_note", "")
        if note and (p.can("countdown") or p.can("own_sound")):
            reasons["sound_unheard"] = "Not heard yet: " + note
        why = "" if p.can("clip") else ("a second clip, since a mode cannot add a clip on %s "
                                        "(Clip says why)." % p.label)
        dis["clip_both"] = bool(why)
        if why:
            reasons["clip_both"] = "Not on this game: " + why
        why = p.why_not("stack")
        dis["stack"] = bool(why)
        if why:
            reasons["stack"] = "Not on this game: " + why
        elif getattr(p, "stack_note", ""):
            reasons["stack"] = p.stack_note         # item 164: live, but multiballs only
        off = []
        for take, part, words in self._FILM_PARTS:
            dis["film_" + take] = not p.can(part)
            if not p.can(part):
                off.append(words)
        if off:
            what = off[0] if len(off) == 1 else ", ".join(off[:-1]) + " or " + off[-1]
            reasons["film"] = ("Not on this game: cutting %s from a film, because %s cannot use "
                               "%s (the sections above say why)."
                               % (what, p.label, "it" if len(off) == 1 else "them"))
        why = p.why_not("events")
        dis["events"] = bool(why)
        if why:
            reasons["events"] = "Not on this game: " + why
        editor_on = on and not self._no_port
        self.set(reasons=reasons, dis=dis, editor_on=editor_on,
                 dup_ok=bool(editor_on or (self._code_slug and not self._no_port)),
                 del_ok=bool(on or self._code_slug))

    @staticmethod
    def _own_extra_why(p):
        """Why the mode's start sound, shot sound and music cannot be carried on title ``p``
        ("" when they can): each rides on a stock sound the game never plays (a carrier,
        mode_sounds), and only titles whose carriers were measured have any. Without them a
        Write and a Try it would drop the three with only a log line."""
        from ...plugins.stern import mode_sounds as MS
        if p is None:
            return ""
        game, version = MS.title_version(p.key)
        if game and MS.carriers(game, version) is not None:
            return ""
        return ("the app has not found spare sounds on %s to carry a mode's own start sound, "
                "shot sound and music, so they cannot be picked here." % p.label)

    @staticmethod
    def _own_music_why(p):
        """Why a mode's own MUSIC cannot be carried on title ``p`` when its calls can ("" when it
        can): item 163, a title whose music plays another way has no stock tune to carry it."""
        from ...plugins.stern import mode_sounds as MS
        if p is None:
            return ""
        c = MS.carriers(*MS.title_version(p.key))
        if c is None or c.music:
            return ""
        return ("the app has not found a stock tune on %s to carry a mode's own music, so it "
                "cannot be picked here." % p.label)

    def _retarget_for_title(self, spec):
        p = self._profile
        self._retarget_note, self._retarget_saved = "", None
        if spec is None:
            return spec
        if not self._card_bound:
            return self._show_on_its_own_title(spec)
        new, dropped = MP.retarget(spec, p)
        self._retarget_refuses = bool(dropped)
        self._retarget_note = self._retarget_words(spec, new, dropped, p)
        if spec.title != p.key or dropped:
            self._say("%s now runs on %s%s" % (
                spec.name, p.label,
                "; " + self._retarget_note if self._retarget_note else ""))
        return new

    @staticmethod
    def _retarget_words(old, new, dropped, p):
        """What opening ``old`` on this card changed, in words: :func:`.mode_project.retarget_words`
        (the same words Copy to... reports)."""
        return MP.retarget_words(old, new, dropped, p)

    @staticmethod
    def _retarget_advanced_words(old, new, dropped, p):
        return MP.retarget_advanced_words(old, new, dropped, p)

    def _note_retarget_in_status(self):
        note = self._retarget_note
        if not note or self._spec is None or self._no_port:
            return
        text = self.get("status") or ""
        saved = self._retarget_saved == self._slug
        ready = "Ready to build."
        refuses = self._retarget_refuses
        if not saved and refuses and text.startswith(ready):
            text = "Ready to build once saved: any edit here saves it." + text[len(ready):]
        tail = ("Its file now has this card's shots." if saved
                else "Until then its file is unchanged, and a build refuses it." if refuses
                else "Its file is unchanged until an edit; a build uses this card's numbers.")
        self.set(status="%s %s%s. %s" % (text, note[0].upper(), note[1:], tail))

    def _show_on_its_own_title(self, spec):
        """No card says which game: the mode is shown on the title its own file names. A
        title this app has no port for leaves it read-only, with the reason."""
        try:
            own = MP.profile(spec.title)
        except MP.ModeProjectError:
            own = None
        if own is None:
            self._shown = None
            if not self._no_port:
                self._no_port = ("%s was made for %s, a game the app can't run modes on here, so "
                                 "it is shown read-only." % (spec.name, spec.title or "another game"))
            return spec
        self._shown = own
        if own.key != self._applied_key:
            self._apply_profile(own, said="%s is shown with the shots of %s, the game it was made for"
                                % (spec.name, own.label))
        return spec

    def _note_no_port_in_status(self):
        no_port = self._no_port
        if no_port:
            if no_port == MP.NO_CARD_HELP:
                head = "Modes cannot be built yet: this project names no card (see above)."
            elif no_port == self.READING_WORDS:
                head = "Modes cannot be built for this card yet: " + no_port[:1].lower() + \
                    no_port[1:]
            elif self._title_note.startswith(no_port):
                head = "Modes of your own can't be built for this card yet (see above)."
            else:
                head = "Modes cannot be built for this card yet: " + no_port
            self.set(status=head + (" The mode is shown as it was saved, read-only."
                                    if self._spec is not None else ""))

    # ------------------------------------------------------------------
    # files into the mode folder
    # ------------------------------------------------------------------
    def _copy_in(self, src, dest_name):
        folder = MP.mode_folder(self._open_project, self._slug)
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, dest_name)
        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copyfile(src, dest)
        return dest_name

    def _choose(self, title, types, dest_stem, attr, mode_var, fallback):
        if self._spec is None or not self.get("editor_on"):
            return None
        if mode_var is not None and self.f.get(mode_var) != "file":
            self._edit(mode_var, "file")            # the radio the person clicked
        path = self.window.ask_open("modes_file", title, types)
        if not path:
            if not getattr(self._spec, attr) and mode_var is not None:
                self._edit(mode_var, fallback)
            return None
        name = self._copy_in(path, dest_stem + os.path.splitext(path)[1].lower())
        setattr(self._spec, attr, name)
        self._say("%s: copied %s into the mode's folder" % (self._spec.name, os.path.basename(path)))
        self.save_now()
        return name

    @rpc
    def choose(self, what):
        """"My picture…", "My video…", "My sound…" and the second clip's video."""
        if what == "art":
            return self._choose("Choose the screen's picture", [("PNG pictures", "*.png")], "art",
                                "screen_art", "art_mode", "panel")
        if what == "clip":
            return self._choose("Choose a video", self.VIDEO_TYPES, "clip", "clip_file", "clip",
                                "none")
        if what == "end":
            return self._choose("Choose the sound", [("WAV sounds", "*.wav")], "end", "end_sound",
                                "end_mode", "game")
        for attr, mode_var, words, stem in self._OWN_SOUNDS:
            if what == attr:
                why = self._own_extra_why(self._shown or self._profile)
                if not why and attr == "music":
                    why = self._own_music_why(self._shown or self._profile)
                if why:
                    # the page greys these three; a call made anyway picks nothing
                    self._say("%s: %s" % (words, why))
                    return None
                return self._choose("Choose the sound: %s" % words.lower(),
                                    [("WAV sounds", "*.wav")], stem, attr, mode_var, "none")
        if what == "clip2":
            return self._choose_second_clip()
        return None

    def _choose_second_clip(self):
        if self._spec is None or not self.get("editor_on"):
            return None
        if self.f["clip_both"] != "file":
            self._edit("clip_both", "file")
        path = self.window.ask_open("modes_file", "Choose the second clip's video",
                                    self.VIDEO_TYPES)
        if not path:
            if not self._clip2_file:
                self._edit("clip_both", "none")
            return None
        self._clip2_file = self._copy_in(path, "clip2" + os.path.splitext(path)[1].lower())
        self._say("%s: copied %s into the mode's folder" % (self._spec.name, os.path.basename(path)))
        self.save_now()
        return self._clip2_file

    # ------------------------------------------------------------------
    # New / Examples / Duplicate / Delete
    # ------------------------------------------------------------------
    def _refusal(self):
        """Why no mode can be added here now ("" when one can): no title (no card, a card
        being read, a build with no port). The page greys the buttons; this is the server's
        own check, so a call made anyway writes nothing."""
        if self._no_port:
            return self._no_port
        if self._profile is None:
            return MP.NO_CARD_HELP
        return ""

    def new_mode(self, name="NEW MODE", spec=None):
        project = self.project()
        if not project:
            return None
        why = self._refusal()
        if why:
            raise MP.ModeProjectError(why)
        self._save_if_edited()
        slug, _spec = MP.new_mode(project, name, spec if spec is not None else self._blank_spec())
        self._say("%s (modes/%s)" % ("added the example" if spec else "made a new mode", slug))
        self._code_slug = None
        self.refresh(select=slug)
        return slug

    @rpc
    def new(self):
        try:
            return self.new_mode()
        except MP.ModeProjectError as e:
            compat.messagebox.showinfo("New mode", str(e))
            return None

    @rpc
    def example(self, name):
        """A form example from the Examples menu (the card's title's own list)."""
        why = self._refusal()
        if why:
            compat.messagebox.showinfo("Example mode", why)
            return None
        spec = dict(MP.examples_for(self._profile)).get(name)
        if spec is None:
            compat.messagebox.showinfo("Example mode", "%s is not an example for %s."
                                       % (name, self._profile.label))
            return None
        try:
            return self.new_mode(name, spec)
        except MP.ModeProjectError as e:
            compat.messagebox.showinfo("Example mode", str(e))
            return None

    @rpc
    def duplicate(self):
        if self._code_slug:
            return self._duplicate_code(self._code_slug)
        if self._slug is None:
            return None
        why = self._refusal()
        if why:
            compat.messagebox.showinfo("Duplicate mode", why)
            return None
        self._save_if_edited()
        try:
            slug, _spec = MP.duplicate_mode(self.project(), self._slug)
        except MP.ModeProjectError as e:
            compat.messagebox.showinfo("Duplicate mode", str(e))
            return None
        self._say("duplicated %s as modes/%s" % (self._slug, slug))
        self.refresh(select=slug)
        return slug

    @rpc
    def copy_to(self, dest=None):
        """Copy to..., under the list: this project's modes go into another card's project
        (``dest``, else its folder is asked for), each matched to that card's title as opening
        it there would match it (:func:`.mode_project.copy_modes`). A message box sums it up
        and the log gets a line per mode; the copies are looked at in THAT project's Modes
        tab, so nothing here changes. Returns the report, or None."""
        project = self.project()
        if not project:
            return None
        self._save_if_edited()
        if not dest:
            dest = self.window.ask_folder(
                "modes_copy_to", "Copy the modes to another card's project: pick its folder",
                initialdir=os.path.dirname(os.path.normpath(project)))
        if not dest:
            return None
        try:
            report = MP.copy_modes(project, os.path.normpath(str(dest)))
        except MP.ModeProjectError as e:
            compat.messagebox.showinfo("Copy modes", str(e))
            return None
        for line in report.lines():
            self._say("copied to %s: %s" % (report.dest, line))
        compat.messagebox.showinfo("Copy modes", report.summary())
        return report.to_json()

    def delete_mode(self, slug):
        MP.delete_mode(self.project(), slug)
        self._say("deleted modes/%s" % slug)
        if slug == self._slug:
            self._slug, self._spec = None, None
        self.refresh()

    @rpc
    def delete(self):
        if self._code_slug:
            return self._delete_code(self._code_slug)
        if self._slug is None:
            return False
        name = self._spec.name if self._spec else self._slug
        if compat.messagebox.askyesno("Delete mode",
                                      "Delete %s, with its picture, clip and sound?" % name):
            if self._save_job is not None:
                self.ctx.loop.after_cancel(self._save_job)
                self._save_job = None
            self._dirty = False
            self.delete_mode(self._slug)
            return True
        return False

    # ------------------------------------------------------------------
    # code modes (modes written in C against the Mode SDK)
    # ------------------------------------------------------------------
    def code_modes_words(self, project):
        from ...plugins.stern import code_modes as CM
        try:
            code = CM.list_code(project) if project else []
        except CM.CodeModeError as e:
            return str(e)
        if not code:
            return ("No code modes in this project. New code mode… starts one from the SDK's "
                    "template; Examples has five written in C, with clips, music and calls cut "
                    "from the films.")
        parts = []
        for slug, spec in code:
            parts.append(self._code_words_one(spec))
        return ("Code modes: %s. Try it and Write carry each one's own clip, picture, music and "
                "calls; edit a mode in modes/<folder>/<folder>.c." % "; ".join(parts))

    @staticmethod
    def _code_words_one(spec):
        have = [w for w, on in (("clip", spec.clip), ("picture", spec.screen_art),
                                ("music", spec.music)) if on]
        if spec.calls:
            have.append("%d call(s)" % len(spec.calls))
        recipe = (spec.film or {}).get("recipe")
        if have:
            return "%s (%s)" % (spec.name, ", ".join(have))
        if recipe:
            return "%s (its film assets are not cut yet)" % spec.name
        return "%s (the game's own sounds)" % spec.name

    def _refresh_code_modes(self, project):
        self.set(code_words=self.code_modes_words(project), cut_ok=bool(project),
                 copy_ok=bool(project) and bool(self._slugs or self._code_list))

    def _show_code(self, slug):
        """The code mode ``slug`` in the editor's place: its Code and Assets panes."""
        from ...plugins.stern import code_modes as CM
        project = self.project()
        self._save_if_edited()
        self._slug, self._spec = None, None
        self._code_slug = slug
        self._set_editor_state(False)
        try:
            spec = CM.load(project, slug)
            err = ""
        except (OSError, ValueError) as e:
            spec, err = None, str(e)
        folder = MP.mode_folder(project, slug)
        src = CM.source_path(project, slug)
        data = {"slug": slug, "source": src, "folder": folder, "error": err,
                "trigger": ("/dump/%s.start" % slug) if MT.code_trigger_name(slug) else "",
                "name": slug.upper()}
        if spec is not None:
            problems = []
            try:
                problems = CM.validate(spec, folder)
            except Exception:                               # noqa: BLE001
                problems = []
            files = {}
            for key, name in (("art", spec.screen_art), ("clip", spec.clip), ("music", spec.music)):
                path = os.path.join(folder, name) if name else ""
                files[key] = path if path and os.path.isfile(path) else ""
            calls = []
            for cue, wav, prio in spec.call_list():
                path = os.path.join(folder, wav) if wav else ""
                calls.append({"cue": cue, "wav": wav, "priority": prio,
                              "path": path if path and os.path.isfile(path) else ""})
            film = spec.film or {}
            needs, needs_files = self._films_needed(spec, folder)
            try:
                words = CM.describe(slug, spec, prof=self._profile)
            except Exception:                               # noqa: BLE001
                words = ""
            data.update(
                name=spec.name, seconds=spec.seconds, screen=bool(spec.screen),
                screen_art=spec.screen_art, words_on_art=bool(spec.words_on_art),
                panel_color=spec.panel_color, title_color=spec.title_color, clip=spec.clip,
                music=spec.music, calls=calls, files=files, describe=words,
                summary=self._code_words_one(spec),
                recipe=str(film.get("recipe") or ""),
                needs_films=needs, needs_files=needs_files,
                status=("Cannot be built for this card yet: " + self._refusal()
                        if self._refusal() else
                        "Ready to build." if not problems
                        else "To fix before it can be built: " + " ".join(problems)),
                has_assets_file=os.path.isfile(os.path.join(folder, CM.ASSETS_FILE)))
        self._game_mode = None
        self.set(code=data, status="", save_state="", game_mode=None)
        self._grey_what_the_title_cannot(False)
        self._publish_rows()

    @staticmethod
    def _films_needed(spec, folder):
        """``(titles, files)``: the films a C example's recipe cuts from ("Godzilla (1954) and
        ...") and the file names looked for, while a part it names (clip, picture, music, calls)
        is not in its folder yet; ``("", "")`` once it is cut, or with no recipe."""
        from ...plugins.stern import code_modes as CM
        r = (spec.film or {}).get("recipe") or {}
        if not r:
            return "", ""
        have = {"clip": spec.clip, "art": spec.screen_art, "music": spec.music}
        cut = all(have[k] and os.path.isfile(os.path.join(folder, have[k]))
                  for k in ("clip", "art", "music") if r.get(k))
        if r.get("calls"):
            cut = cut and bool(spec.calls) and all(
                wav and os.path.isfile(os.path.join(folder, wav)) for _c, wav, _p in spec.call_list())
        if cut:
            return "", ""
        keys = CM.recipe_films({"recipe": r})
        titles = [CM.FILM_TITLES.get(k, k) for k in keys]
        words = titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " and " + titles[-1]
        return words, ", ".join(CM.FILMS.get(k, k) for k in keys)

    @rpc
    def new_code_mode(self, name):
        """New code mode…: the page asked "What is the mode called?"."""
        if not self.project():
            self._tryit_note(MP.NO_PROJECT_HELP)
            return None
        if not name or not str(name).strip():
            return None
        why = self._refusal()
        if why:
            self._tryit_note(why)
            return None
        self._save_if_edited()
        try:
            slug, path = self.make_code_mode(str(name).strip())
        except (MT.TryItError, OSError) as e:
            self._tryit_note(str(e))
            return None
        self.refresh(select_code=slug)
        self.open_path(path)
        return path

    @rpc
    def open_code(self):
        """Open the selected code mode's C file with the OS opener."""
        if not self._code_slug:
            return False
        from ...plugins.stern import code_modes as CM
        self.open_path(CM.source_path(self.project(), self._code_slug))
        return True

    @rpc
    def open_sdk_doc(self):
        self.open_path(self.sdk_doc())
        return True

    def _duplicate_code(self, slug):
        why = self._refusal()
        if why:
            compat.messagebox.showinfo("Duplicate mode", why)
            return None
        try:
            new_slug, _path = MT.duplicate_code_mode(self.project(), slug)
        except (MT.TryItError, OSError) as e:
            compat.messagebox.showinfo("Duplicate mode", str(e))
            return None
        self._say("duplicated %s as modes/%s" % (slug, new_slug))
        self.refresh(select_code=new_slug)
        return new_slug

    def _delete_code(self, slug):
        name = (self.get("code") or {}).get("name") or slug
        if not compat.messagebox.askyesno(
                "Delete mode", "Delete %s, with its code, picture, clip and sounds?" % name):
            return False
        try:
            MT.delete_code_mode(self.project(), slug)
        except (MT.TryItError, OSError) as e:
            compat.messagebox.showinfo("Delete mode", str(e))
            return False
        self._say("deleted modes/%s" % slug)
        self._code_slug = None
        self.refresh()
        return True

    def _ask_films_dir(self, why):
        return self.window.ask_folder("modes_films", why) or ""

    def add_code_example(self, name, dirs=None, wait=False):
        from ...plugins.stern import code_modes as CM
        project = self.project()
        if not project:
            self._tryit_note(MP.NO_PROJECT_HELP)
            return None
        ex = CM.example(name)
        if ex is None:
            return None
        if not self._code_examples_ok():
            self._tryit_note("%s is an example for Godzilla; this card is not." % name)
            return None
        title = self._profile.key
        if os.path.exists(MP.mode_folder(project, ex["slug"])):
            self._tryit_note("%s is already in this project (modes/%s)." % (name, ex["slug"]))
            return None
        dirs = list(dirs or ()) + CM.film_dirs(project)
        ffmpeg = self._ffmpeg_path()
        self._tryit_note("adding the example %s (code mode)…" % name)

        def work():
            try:
                slug, missing = CM.add_example(project, name, dirs=dirs, ffmpeg=ffmpeg,
                                               log=lambda m, *a: self._say(m))
            except Exception as e:                          # noqa: BLE001
                self._tryit_note("%s could not be added: %s" % (name, e))
                self._post_refresh_code()
                return
            self.stamp_code_title(project, slug, title)
            self._tryit_note(self._code_example_note(name, slug, missing, CM))
            self._post_refresh_code(slug)

        t = threading.Thread(target=work, daemon=True, name="modes-code-example")
        t.start()
        if wait:
            t.join()
        return t

    def _post_refresh_code(self, select_code=None):
        def again():
            if self.project():
                self.refresh(select_code=select_code) if select_code else self._refresh_list()
        self.ctx.loop.post(again)

    def _refresh_list(self):
        """The list and the code-mode words again, without reopening the open mode."""
        project = self.project()
        found, _broken = MP.list_modes(project) if project else ([], [])
        if self._slug is not None and self._slug not in dict(found):
            self.refresh()
            return
        self._slugs = [s for s, _ in found]
        self._found = dict(found)
        if self._slug is not None and self._spec is not None:
            self._found[self._slug] = self._spec
        self._at_cap = bool(project) and len(found) >= MP.MAX_MODES
        self._new_ok = bool(project) and len(found) < MP.MAX_MODES
        self._ex_ok = bool(project)
        self._code_list = [(s, n) for s, kind, n in (MT.list_all(project) if project else [])
                           if kind == "code"]
        self._refresh_code_modes(project)
        if self._code_slug and self._code_slug not in [s for s, _n in self._code_list]:
            self.refresh()
            return
        if self._slug is None and self._code_slug is None and (self._slugs or self._code_list):
            self.refresh()                   # nothing was open and there is something now
            return
        if self._code_slug:
            self._show_code(self._code_slug)
        self._show_cap(project, len(self._slugs))
        self._publish_rows()

    @staticmethod
    def _code_example_note(name, slug, missing, CM):
        if missing:
            return ("added the example %s as modes/%s with its code. Its clip, picture, music and "
                    "calls are cut from your copy of %s, which was not found, so for now it plays "
                    "the game's own sounds on a plain panel. On its page, press Choose your films "
                    "folder… and pick the folder that holds the film%s." % (name, slug, CM.missing_words(missing),
                                                       "s" if len(missing) > 1 else ""))
        return ("added the example %s as modes/%s: its code, and its own clip, picture, music and "
                "calls cut from the films. Try it builds it in; Write puts it on the card."
                % (name, slug))

    @rpc
    def code_example(self, name):
        from ...plugins.stern import code_modes as CM
        project = self.project()
        why = self._refusal() if project else ""
        if not why and project and not self._code_examples_ok():
            why = ("%s is an example for Godzilla; this card is %s."
                   % (name, self._profile.label if self._profile is not None else "not Godzilla"))
        if why:
            self._tryit_note(why)
            return False
        ex = CM.example(name)
        if not project or ex is None:
            return bool(self.add_code_example(name))
        dirs = CM.film_dirs(project)
        missing = [k for k in CM.recipe_films(ex) if not CM.find_film(k, dirs)]
        extra = []
        if missing:
            got = self._ask_films_dir("Where are the films? %s's assets are cut from %s"
                                      % (name, CM.missing_words(missing)))
            if got:
                extra = [got]
        return bool(self.add_code_example(name, dirs=extra))

    def recut_code_modes(self, dirs, wait=False, only=None):
        from ...plugins.stern import code_modes as CM
        project = self.project()
        if not project:
            return None
        try:
            code = [(s, c) for s, c in CM.list_code(project) if (c.film or {}).get("recipe")
                    and (only is None or s == only)]
        except CM.CodeModeError as e:
            self._tryit_note(str(e))
            return None
        if not code:
            self._tryit_note("no code mode here has a film recipe to cut from.")
            return None
        ffmpeg = self._ffmpeg_path()

        def work():
            done, left = [], {}
            for slug, spec in code:
                try:
                    missing = CM.recut_example(project, slug, list(dirs) + CM.film_dirs(project),
                                               ffmpeg=ffmpeg, log=lambda m, *a: self._say(m))
                except Exception as e:                      # noqa: BLE001
                    self._tryit_note("%s could not be cut: %s" % (spec.name, e))
                    continue
                if missing:
                    left[spec.name] = missing
                else:
                    done.append(spec.name)
            words = []
            if done:
                words.append("cut the film assets of %s" % ", ".join(done))
            for n, m in left.items():
                words.append("%s needs %s, which is not in that folder" % (n, CM.missing_words(m)))
            self._tryit_note("; ".join(words) + ".")
            self._post_refresh_code()

        t = threading.Thread(target=work, daemon=True, name="modes-recut")
        t.start()
        if wait:
            t.join()
        return t

    @rpc
    def cut_films(self, slug=None):
        """Choose your films folder… on a C example's page (``slug``), or every C example's
        film assets at once (no slug)."""
        if not self.project():
            self._tryit_note(MP.NO_PROJECT_HELP)
            return None
        got = self._ask_films_dir("Pick the folder that holds the Godzilla films")
        if not got:
            return None
        return bool(self.recut_code_modes([got], only=slug or None))

    # ------------------------------------------------------------------
    # Try it: the footer's calls
    # ------------------------------------------------------------------
    @rpc
    def tryit(self):
        return bool(self.on_try())

    @rpc
    def check_game(self):
        return bool(self.on_check())

    @rpc
    def start_now(self):
        return self.on_start_now() is not None

    @rpc
    def end_now(self):
        return self.on_end_now() is not None

    @rpc
    def goto_emulate(self):
        if self.window.service("emulate") is not None:
            self.window.select_tab("emulate")
        return True

    def _show_emu(self, quiet=False):
        """The footer's "Try it on" box (the Emulate tab's own card, ``emulate_card_var``)
        and what that card is next to the project's."""
        card_var = self._export("emulate_card_var")
        emu = self._emu()
        card = (card_var.get() if card_var is not None else "") or ""
        if not card:
            st = self._emulate_state() if not quiet else None
            card = (st or {}).get("card") or card
        card = card.strip().strip('"')
        verdict, kind, tip = self._card_verdict(card)
        self.set(emu={"have": emu is not None and callable(getattr(emu, "launch_with", None)),
                      "box": card_var is not None, "up": self._running_fn(),
                      "busy": False, "card": card, "verdict": verdict,
                      "verdict_kind": kind, "verdict_tip": tip})

    _verdict_cache = (None, None)

    def _card_verdict(self, card):
        """A short word on the card Try it would boot, next to the one the project was made
        from (mode_project.project_cards). Never opens an image."""
        project = self.project()
        key = (project, card)
        if self._verdict_cache[0] == key:
            return self._verdict_cache[1]
        out = ("", "", "")
        if card and project:
            try:
                made_for, run = MP.project_cards(project, card)
            except Exception:                               # noqa: BLE001
                made_for, run = None, None
            if not os.path.isfile(card):
                out = ("not found", "err", "There is no file at %s." % card)
            elif made_for is not None and made_for.image and \
                    os.path.normcase(os.path.abspath(made_for.image)) == \
                    os.path.normcase(os.path.abspath(card)):
                out = ("the project's own card", "ok", "")
            elif (run is not None and not run.game_dir and made_for is not None
                  and made_for.game_dir):
                # a renamed image: read which game it is from its own index, off the loop
                self._probe_try_on(card)
                return ("", "", "")
            elif made_for is not None and run is not None and made_for.game_dir and run.game_dir:
                if made_for.game_dir == run.game_dir and \
                        MP.version_key(made_for.version) == MP.version_key(run.version):
                    out = ("same game build, a different image", "info",
                           "The project was made from %s; Try it builds from it and boots this "
                           "image." % MP.file_name(made_for.image))
                else:
                    prof = self._profile
                    tip = ""
                    if prof is not None:
                        try:
                            MT.check_title(prof, run.game_dir, run.version)
                        except MT.TryItError as e:
                            tip = str(e)
                    out = ("another game build", "warn", tip)
        self._verdict_cache = (key, out)
        return out

    _try_on_probing = None

    def _probe_try_on(self, card):
        """The "Try it on" card's title from its own index (a renamed image), once per path,
        on a worker (it opens the image, read-only); the verdict is asked again after."""
        if self._try_on_probing is None:
            self._try_on_probing = set()
        if card in self._try_on_probing or MP.probed_card_title(card) is not None:
            return
        self._try_on_probing.add(card)

        def work():
            try:
                MP.probe_card_title(card)
            except Exception:                               # noqa: BLE001
                pass
            self._verdict_cache = (None, None)
            self.ctx.loop.post(self._show_emu)
        threading.Thread(target=work, daemon=True, name="modes-try-on-probe").start()

    def _set_try_on(self, path):
        var = self._export("emulate_card_var")
        if var is not None:
            var.set(path)
        self._show_emu()

    @rpc
    def browse_card(self):
        var = self._export("emulate_card_var")
        path = self.window.ask_open(
            "emulate_card", "Pick a Spike 2 card image",
            [("Card images", "*.raw *.img"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(var.get() if var is not None else ""))
        if path:
            self._set_try_on(os.path.normpath(path))
        return path

    # ------------------------------------------------------------------
    # From a film (item 142): the page's dialog over a FilmCutForm
    # ------------------------------------------------------------------
    _FILM_TEXT = ("film", "start", "length", "sound_start", "sound_length", "still_at", "crop")
    _FILM_BOOL = ("take_clip", "take_sound", "take_still")

    @rpc
    def film_open(self, take):
        """The "From a film" dialog for the open mode, on the film and times it last used."""
        if self._spec is None or not self._open_project or not self.get("editor_on"):
            return False
        self._save_if_edited()
        form = FCD.FilmCutForm.from_spec(self._spec, take)
        self._film_seq += 1
        self._film = {"form": form, "folder": MP.mode_folder(self._open_project, self._slug),
                      "seq": self._film_seq, "job": None, "tokens": {}}
        self._film_publish(info="", status="The mode keeps only the cut, never the film.",
                           error=False, preview="", busy=False)
        if form.film:
            self.film_probe()
        return True

    def _film_publish(self, **kw):
        if self._film is None:
            self.set(film=None)
            return
        f = self._film["form"]
        cur = dict(self.get("film") or {})
        cur.update({"film": f.film, "start": f.start, "length": f.length, "crop": f.crop,
                    "take_clip": f.take_clip, "take_sound": f.take_sound,
                    "take_still": f.take_still, "sound_same": f.sound_same,
                    "sound_start": f.sound_start, "sound_length": f.sound_length,
                    "still_at": f.still_at, "max": int(FCD.FC.MAX_SECONDS),
                    "seq": self._film["seq"]})
        cur.update(kw)
        self.set(film=cur)

    def _film_field(self, key, value):
        if self._film is None:
            return
        f = self._film["form"]
        if key in self._FILM_TEXT:
            setattr(f, key, "" if value is None else str(value))
        elif key in self._FILM_BOOL:
            setattr(f, key, bool(value))
        elif key == "sound_same":
            f.sound_same = bool(value) if isinstance(value, bool) else value == "same"
        else:
            return
        self._film_publish()

    def _film_run(self, kind, fn, done):
        """Run ``fn`` on a worker; its answer comes back on the UI loop, dropped when a newer
        request of the same kind (or another dialog) has superseded it."""
        film = self._film
        if film is None:
            return None
        token = film["tokens"].get(kind, 0) + 1
        film["tokens"][kind] = token
        seq = film["seq"]

        def land(ok, value):
            cur = self._film
            if kind != "cut" and (cur is None or cur["seq"] != seq
                                  or cur["tokens"].get(kind) != token):
                return
            done(ok, value)

        def work():
            try:
                value = fn()
                ok = True
            except Exception as e:                          # noqa: BLE001
                value, ok = e, False
            self.ctx.loop.post(land, ok, value)
        t = threading.Thread(target=work, daemon=True, name="modes-film-" + kind)
        t.start()
        return t

    def _ffmpeg_fn_for_film(self):
        return self._ffmpeg_fn if self._ffmpeg_fn is not None else self._find_ffmpeg

    @staticmethod
    def _find_ffmpeg():
        from ...core.audio import find_ffmpeg
        return find_ffmpeg()

    def _film_sync(self, fields):
        """The page's copy of the dialog's fields into the form (the Tk dialog's sync())."""
        if self._film is None or not isinstance(fields, dict):
            return
        f = self._film["form"]
        for key in self._FILM_TEXT:
            if key in fields:
                setattr(f, key, "" if fields[key] is None else str(fields[key]))
        for key in self._FILM_BOOL:
            if key in fields:
                setattr(f, key, bool(fields[key]))
        if "sound_same" in fields:
            f.sound_same = bool(fields["sound_same"])
        f.film = (f.film or "").strip()

    @rpc
    def film_choose(self, fields=None):
        if self._film is None:
            return None
        self._film_sync(fields)
        f = self._film["form"]
        start = os.path.dirname(f.film or "") or None
        path = self.window.ask_open("modes_film", "Choose a film", FCD.FILM_TYPES,
                                    initialdir=start)
        if path:
            f.film = path
            self._film_publish()
            self.film_probe()
        return path

    @rpc
    def film_probe(self, fields=None):
        if self._film is None:
            return False
        self._film_sync(fields)
        self._film_publish()
        form = self._film["form"].snapshot()
        form.film = (form.film or "").strip()
        if not form.film:
            return False
        self._film_publish(info="Reading the film…")
        ffmpeg = self._ffmpeg_fn_for_film()
        self._film_run("probe", lambda: form.describe_film(ffmpeg()),
                       lambda ok, value: self._film_publish(info=value if ok else str(value)))
        return True

    @rpc
    def film_preview(self, fields=None):
        if self._film is None:
            return False
        self._film_sync(fields)
        form = self._film["form"].snapshot()
        self._film_publish(status="Drawing the frame at the start…", error=False)
        ffmpeg = self._ffmpeg_fn_for_film()
        box = (480, 270)
        tmp = self._tmpdir()
        self._preview_rev += 1
        n = self._preview_rev

        def draw():
            image = form.preview(ffmpeg(), box)
            path = os.path.join(tmp, "film-%d.png" % n)
            image.save(path)
            return form.start.strip(), path

        def done(ok, value):
            if not ok:
                self._film_publish(status=str(value), error=True)
                return
            start, path = value
            self._film_publish(preview=path,
                               status="The frame at %s, as the clip will show it." % start,
                               error=False)
        self._film_run("preview", draw, done)
        return True

    @rpc
    def film_cut(self, fields=None):
        film = self._film
        if film is None or film.get("job") is not None:
            return False
        self._film_sync(fields)
        form = film["form"].snapshot()
        job = {"state": "cutting", "lock": threading.Lock()}
        film["job"] = job
        self._film_publish(busy=True, status="Cutting… a clip takes a few seconds.", error=False)
        folder = film["folder"]
        ffmpeg = self._ffmpeg_fn_for_film()

        def cut():
            stage = FCD.stage_folder()
            try:
                result = form.apply(stage, ffmpeg())
                with job["lock"]:
                    if job["state"] == "cancelled":
                        return None
                    job["state"] = "committing"
                return FCD.commit_cut(result, folder)
            finally:
                FCD.discard_stage(stage)

        def done(ok, value):
            with job["lock"]:
                state, job["state"] = job["state"], None
            cur = self._film
            closed = cur is None or cur.get("job") is not job
            if closed:
                if ok and value is not None and state == "committing":
                    self.apply_film_cut(value)
                return
            cur["job"] = None
            if not ok:
                self._film_publish(busy=False, status=str(value), error=True)
                return
            self._film = None
            self.set(film=None)
            if value is not None:
                self.apply_film_cut(value)
        self._film_run("cut", cut, done)
        return True

    @rpc
    def film_close(self):
        self._film_close()
        return True

    def _film_close(self):
        film = self._film
        if film is None:
            return
        job = film.get("job")
        if job is not None:
            with job["lock"]:
                if job["state"] == "cutting":
                    job["state"] = "cancelled"
        self._film = None
        self.set(film=None)

    @staticmethod
    def _film_cut_into(spec, result):
        if result.get("clip_file"):
            spec.clip, spec.clip_file = "file", result["clip_file"]
        if result.get("end_sound"):
            spec.end_sound = result["end_sound"]
        if result.get("screen_art"):
            spec.screen_art = result["screen_art"]
        for key in FCD.PROVENANCE:
            if key in result:
                setattr(spec, key, result[key])

    def apply_film_cut(self, result):
        """Make a cut the mode's clip, end sound and picture, with where each came from, and
        save. A cut made for a mode that is no longer open goes into THAT mode's file."""
        folder = result.get("mode_folder") or ""
        here = (MP.mode_folder(self._open_project, self._slug)
                if self._open_project and self._slug else "")
        if folder and os.path.normcase(os.path.abspath(folder)) != \
                os.path.normcase(os.path.abspath(here or "")):
            path = os.path.join(folder, MP.MODE_FILE)
            if os.path.isfile(path):
                spec = MP.load(path)
                self._film_cut_into(spec, result)
                MP.save(os.path.dirname(os.path.dirname(folder)), os.path.basename(folder), spec)
            return
        if self._spec is None:
            return
        self._loading = True
        try:
            if result.get("clip_file"):
                self.f["clip"] = "file"
            if result.get("end_sound"):
                self.f["end_mode"] = "file"
            if result.get("screen_art"):
                self.f["art_mode"] = "file"
        finally:
            self._loading = False
        self._publish_form()
        self._film_cut_into(self._spec, result)
        self._say("%s: %s" % (self._spec.name, result.get("summary") or "cut from a film"))
        self.save_now()

    # ------------------------------------------------------------------
    # the game's own modes (item 145): a dialog on the web
    # ------------------------------------------------------------------
    def _SM(self):
        from ...plugins.stern import stock_modes as SM
        return SM

    def _stock_set(self, **kw):
        st = dict(self.get("stock") or {})
        st.update(kw)
        self.set(stock=st)

    def _stock_build_for(self, project):
        """The game's own modes of the shown card: what reading it found (a hand table, or
        one worked out on this machine), else the table for the project's recorded build."""
        tr = self._title_read
        if tr is not None and getattr(tr, "stock_build", None) is not None:
            return tr.stock_build
        return self._SM().table_for_project(project) if project else None

    def _known_builds_words(self):
        labels = [MP.title_label(b.game, b.version) for b in self._SM().tables()]
        if not labels:
            return ""
        return " (it knows %s)" % (labels[0] if len(labels) == 1
                                   else ", ".join(labels[:-1]) + " and " + labels[-1])

    def _caption(self, num):
        """The operator menu's own words for a setting (the Defaults tab's), in title case, or
        "" when the card's read did not give them."""
        tr = self._title_read
        cap = ((getattr(tr, "captions", None) or {}).get(num.adj_name, "")
               if num.is_adjustment or num.kind == "adj" else "")
        return _title_case(cap) if cap else ""

    def _number_words(self, build, num):
        """A number's label under its mode's name: an operator setting's menu caption, else
        its words; one that starts with the mode's own name (``AD_MODE_DRIVE_MY_CAR_TIMER``
        -> "Mode Drive My Car Timer"), which the list and the page already say, keeps only
        "Timer"."""
        label = self._caption(num) or build.row_label(num)
        mode = build.mode_name(num.mode_id)

        def flat(t):
            return re.sub(r"[^a-z0-9 ]", "", t.lower())
        for head in ("mode %s " % flat(mode), "%s " % flat(mode)):
            if flat(label).startswith(head) and len(flat(label)) > len(head):
                n = len(head.split())
                rest = " ".join(label.split()[n:])
                if rest:
                    return rest[:1].upper() + rest[1:]
        return label

    def _stock_row(self, build, num, settings, rec, other_build):
        SM = self._SM()
        staged = None
        if num.is_adjustment and num.adj_name in settings:
            staged = settings[num.adj_name]
        elif num.is_word and not other_build and num.row_key in rec["values"]:
            staged = rec["values"][num.row_key]
        stock = "?" if num.value is None else SM.display(build, num, num.value)
        if not num.editable:
            value = stock
        else:
            value = SM.display(build, num, int(staged)) + "  ●" if staged is not None else stock
        row = {"key": num.row_key, "mode_id": num.mode_id, "mode": build.mode_name(num.mode_id),
               "number": self._number_words(build, num), "value": value, "stock": stock,
               "current": SM.display(build, num, int(staged)) if staged is not None else stock,
               "where": _where_words(num), "changed": staged is not None,
               "readonly": not num.editable, "why": _why_words(num),
               "hint": self._stock_hint(num)}
        if num.kind == "path" and num.editable:
            # item 159: a tank position is picked by shot name, not typed as a number
            row["choices"] = [{"value": str(v), "label": label}
                              for v, label in SM.path_choices(build, num, rec["values"])]
            row["raw"] = str(int(staged) if staged is not None else num.value)
        return row

    def _stock_hint(self, num):
        """What a number is, in words, with where it lives for whoever wants it (the row's
        tooltip and the dialog's note): the setting's name, the program address."""
        if not num.editable:
            return "%s. %s" % (num.where_text()[:1].upper() + num.where_text()[1:],
                               num.why_read_only()[:1].upper() + num.why_read_only()[1:] + ".")
        if num.is_adjustment:
            rng = num.adj_range
            cap = self._caption(num)
            return ("An operator setting%s (%s)%s: the same number as on the Defaults tab. A "
                    "machine still on the game's default takes the new one when it boots."
                    % (" the menu calls %s" % cap.upper() if cap else "", num.adj_name,
                       ", %d to %d" % rng if rng else ""))
        return "One word in the game program (%s)%s." % (
            num.where(), "; it is shared by %d modes, so changing it changes all of them"
            % num.shared if num.shared else "")

    def refresh_stock_modes(self):
        SM = self._SM()
        keep = (self.get("stock") or {}).get("sel")
        self._stock_rows = {}
        self._stock_order = []
        project = self.project()
        build = self._stock_build_for(project)
        self._stock_build = build
        if not project:
            self._stock_set(msg="Open or extract a card project first (Extract tab) - changes "
                                "to the game's own modes are saved in it.",
                            rows=[], on=False, sel=None, note="", value="", row_on=False,
                            choices=None)
            self._after_stock()
            return
        if build is None:
            pb = SM.project_build(project)
            what = (MP.title_label(pb[0], pb[1]) if pb else
                    (self.get("title_label") or "this project's game"))
            if self._no_port == self.READING_WORDS:
                msg = ("Reading the game's own rules from the card (see above): its modes are "
                       "listed here when that is done.")
            else:
                msg = ("The app doesn't know the timers and awards of %s's own modes yet%s."
                       % (what, self._known_builds_words()))
            self._stock_set(msg=msg, rows=[], on=False, sel=None, note="", value="",
                            row_on=False)
            self._after_stock()
            return
        rec = SM.staged_for(project, build)
        from ...core import staged_changes
        settings = staged_changes.load(project).get(SM.SETTINGS_KEY) or {}
        other_build = rec["build"] not in (None, build.id)
        seen_adj = set()
        rows = []
        for num in build.numbers:
            if not num.is_player_facing:
                continue
            if num.kind == "adj":
                if num.adj_name in seen_adj:
                    continue
                seen_adj.add(num.adj_name)
            rows.append(self._stock_row(build, num, settings, rec, other_build))
            self._stock_rows[num.row_key] = num
            self._stock_order.append(num.row_key)
        n_changed = sum(1 for r in rows if r["changed"])
        msg = ("%s: %d number(s) of the game's own modes. %s" % (
            MP.title_label(build.game, build.version), len(self._stock_rows),
            "%d change(s) staged for the next Write." % n_changed if n_changed else
            "Nothing changed - every number is the game's own."))
        if other_build and rec["values"]:
            msg += (" %d change(s) were staged for %s, not this card, and are not written."
                    % (len(rec["values"]), rec["build"]))
        sel = keep if keep in self._stock_rows else None
        caveat = self._stock_caveat()
        self._stock_set(msg=msg + (" " + caveat if caveat else "") + " Rename a mode on the "
                        "Text tab.", rows=rows, on=True, sel=sel, n_changed=n_changed)
        self._on_stock_select(sel)
        self._after_stock()

    def _stock_caveat(self):
        """The table's own caveat on its numbers (a program the app has not seen from Stern,
        or a card this app changed read through its original's table), or ""."""
        tr = self._title_read
        notes = [str(n) for n in (getattr(tr, "stock_notes", None) or ())]
        keep = [n for n in notes if "seen from Stern" in n or "changed" in n]
        return " ".join(keep)

    # -- the game's own modes in the list, and a page for each ---------------------------
    def _game_ids(self):
        """The ids of the game's own modes the list shows, in the game's order: the ones with
        a number the person can change, and the rules the card's port names (their page takes
        another shot or a rewrite in C). A mode with neither has nothing to do here and is left
        out; the stock dialog still lists every row."""
        build = self._stock_build
        if build is None:
            return []
        editable = {n.mode_id for n in build.numbers if n.is_player_facing and n.editable}
        editable |= self._port_rule_ids()
        return sorted(m for m in build.modes if m in editable)

    def _port_rule_ids(self):
        """The ids of the game's rules the card's port names (``rule`` lines), when its runtime
        can take another shot for them or a rewrite; an empty set otherwise."""
        if not self.project():
            return set()
        try:
            from ...plugins.stern import stock_remap as SR
            port = self._remap_port()[0]
            if not port:
                return set()
            key = (port, os.path.getmtime(port))
            if self._rule_ids_cache[0] != key:
                ids = ({int(rid) for rid, _label, _v in SR.port_rules(port)}
                       if SR.port_can(port) else set())
                self._rule_ids_cache = (key, ids)
            return set(self._rule_ids_cache[1])
        except Exception:                                   # noqa: BLE001 - the list must never fail on it
            return set()

    _rule_ids_cache = (None, set())

    def _game_rows(self):
        build = self._stock_build
        if build is None:
            return []
        rows = {r["key"]: r for r in (self.get("stock") or {}).get("rows", [])}
        out = []
        self.set(game_hidden=max(0, len(build.modes) - len(self._game_ids())))
        for mid in self._game_ids():
            mine = [r for r in rows.values() if r.get("mode_id") == mid]
            changed = sum(1 for r in mine if r["changed"])
            n = len(mine)
            out.append({"slug": str(mid), "kind": "game", "name": build.mode_name(mid),
                        "chip": "%d changed" % changed if changed else "",
                        "chip_tip": ("%d of its numbers are staged for the next Write"
                                     % changed) if changed else "",
                        "n": n})
        return out

    def _after_stock(self):
        """The stock table changed: the list's group and the open game mode's page follow."""
        if self._game_mode is not None and self._game_mode not in self._game_ids():
            self._game_mode = None
            self.set(game_mode=None)
            self.refresh()
            return
        if self._game_mode is not None:
            self._publish_game_mode()
        self._publish_rows()

    def _show_game_mode(self, mode_id):
        """One of the game's own modes in the editor's place: its numbers, each with its
        stock value, a new value, Set and Stock; read-only ones greyed with the reason."""
        self._save_if_edited()
        self._slug, self._spec = None, None
        self._code_slug = None
        self._game_mode = mode_id
        self._set_editor_state(False)
        self.set(code=None, status="", save_state="")
        if mode_id in self._port_rule_ids():     # its Shots and Advanced sections
            self.refresh_stock_remap()
            self.refresh_stock_rewrite()
        self._publish_game_mode()
        self._publish_rows()

    def _publish_game_mode(self, note=None):
        build = self._stock_build
        mid = self._game_mode
        if build is None or mid is None:
            self.set(game_mode=None)
            return
        rows = [r for r in (self.get("stock") or {}).get("rows", []) if r.get("mode_id") == mid]
        cur = self.get("game_mode") or {}
        keep_note = cur.get("note", "") if cur.get("id") == mid else ""
        mode = build.modes.get(mid)
        n_edit = sum(1 for r in rows if not r["readonly"])
        rule = mid in self._port_rule_ids()
        if not rows and rule:
            about = ("The app found none of this mode's timers, shot counts or awards in the "
                     "game program. Its shots can still be changed, below.")
        elif not rows:
            about = ("The app found none of this mode's timers, shot counts or awards in the "
                     "game program, so there is nothing of it to change here.")
        elif not n_edit:
            about = "Every number of this mode is read-only here; each row says why."
        else:
            about = ("Type a new value and press Set. Write puts it on the card; Stock puts the "
                     "game's own value back.")
        caveat = self._stock_caveat()
        if caveat:
            about += " " + caveat
        self.set(game_mode={
            "id": mid, "name": build.mode_name(mid), "rows": rows, "rule": rule,
            "build": MP.title_label(build.game, build.version),
            "about": about, "starts": list(getattr(mode, "starts", []) or [])[:3],
            "note": keep_note if note is None else note,
            "n_changed": sum(1 for r in rows if r["changed"])})

    @rpc
    def game_set(self, key, value):
        """New value + Set on a row of the game's mode page."""
        if key not in self._stock_rows:
            return ""
        text = self.stage_stock_value(key, value)
        self._publish_game_mode(note=text)
        return text

    @rpc
    def game_stock(self, key):
        """Stock on a row of the game's mode page: the game's own value again."""
        num = self._stock_rows.get(key)
        if num is None or not num.editable:
            return ""
        text = self.stage_stock_value(key, num.value)
        self._publish_game_mode(note=text)
        return text

    # -- the card's read ------------------------------------------------------------------
    @rpc
    def read_cancel(self):
        return self.reading_cancel()

    @rpc
    def read_again(self):
        return self.reading_again()

    def _on_stock_select(self, key):
        num = self._stock_rows.get(key) if key else None
        if num is None:
            self._stock_set(sel=None, note="", value="", row_on=False)
            return
        why = num.why_read_only()
        if why:
            self._stock_set(sel=key, value="", note="Read-only: %s." % why, row_on=False,
                            choices=None)
            return
        row = next((r for r in (self.get("stock") or {}).get("rows", []) if r["key"] == key), None)
        cur = (row["value"] if row else "").replace("●", "").strip()
        choices = None
        note = self._stock_hint(num)
        if num.kind == "path":
            # item 159: which shot this tank position is; the picker lists the shots the
            # switches send alone, and none (the tanks then skip the position)
            choices = (row or {}).get("choices") or []
            cur = (row or {}).get("raw", "")
            note = ("Which shot this tank position is (game program, %s). Pick another shot "
                    "the switches send alone, or none: the tanks then skip this position. "
                    "The counted shots and the spot list follow it." % num.where())
        elif num.kind == "insn":
            note = ("How many spins this spinner needs (game program, %s): the load of the "
                    "game's own count becomes this number, 1 to 255." % num.where())
        self._stock_set(sel=key, value=cur, note=note, row_on=True, choices=choices)

    @rpc
    def stock_refresh(self):
        self.refresh_stock_modes()
        return True

    @rpc
    def stock_select(self, key):
        self._on_stock_select(key)
        return True

    def _settings_staged_fn(self, name):
        """Tk's ``main_window._modes_settings_staged``: the Defaults form adopts an operator
        setting this tab staged (its autostage REPLACES the project's staged settings)."""
        svc = self.window.service("defaults")
        for attr in ("modes_settings_staged", "_modes_settings_staged"):
            fn = getattr(svc, attr, None) if svc is not None else None
            if callable(fn):
                fn(name)
                return True
        return False

    def stage_stock_value(self, row_key, value):
        """Stage *value* for the row; returns the message shown."""
        SM = self._SM()
        num = self._stock_rows.get(row_key)
        build = self._stock_build
        if num is None or build is None:
            return ""
        try:
            got = SM.stage(self.project(), build, num, value)
        except SM.StockModeError as e:
            self._stock_set(note=str(e))
            return str(e)
        label = "%s %s" % (build.mode_name(num.mode_id), self._number_words(build, num).lower())
        if got is None and num.value is None:
            text = "%s is back to the game's own." % label
        elif got is None:
            text = "%s is back to the game's own %s." % (label, SM.display(build, num, num.value))
        else:
            text = "%s: %s -> %s staged for the next Write." % (
                label, SM.display(build, num, num.value), SM.display(build, num, got))
        self._say(text)
        if num.is_adjustment:
            try:
                self._settings_staged_fn(num.adj_name)
            except Exception:                               # noqa: BLE001
                pass
        self.refresh_stock_modes()
        self._stock_set(note=text)
        return text

    @rpc
    def stock_set(self, value=None):
        st = self.get("stock") or {}
        key = st.get("sel")
        if key is None:
            return ""
        return self.stage_stock_value(key, st.get("value", "") if value is None else value)

    @rpc
    def stock_reset(self):
        key = (self.get("stock") or {}).get("sel")
        num = self._stock_rows.get(key) if key else None
        if num is not None and num.editable:
            return self.stage_stock_value(num.row_key, num.value)
        return ""

    @rpc
    def stock_all(self):
        build = self._stock_build
        project = self.project()
        if build is None or not project:
            return 0
        n = self._SM().unstage_all(project, build)
        self._say("the game's own modes: %d change(s) put back to stock" % n)
        for name in build.adjustment_numbers():
            try:
                self._settings_staged_fn(name)
            except Exception:                               # noqa: BLE001
                pass
        self.refresh_stock_modes()
        self._stock_set(note="Every number is back to the game's own (%d change(s) "
                             "undone)." % n)
        return n



_SMALL = ("a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs")


def _title_case(caption):
    """An operator menu caption (``MULTIBALL BALL SAVE TIME``) in title case, as the tab
    writes names: ``Multiball Ball Save Time``; a word with a digit keeps its capitals."""
    out = []
    for i, w in enumerate(str(caption).split()):
        low = w.lower()
        if any(c.isdigit() for c in w):
            out.append(w)
        elif i and low in _SMALL:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)


def _where_words(num):
    """Where a number lives, as a person reads it (the tooltip has the setting's name or the
    address): an operator setting with its range, or built into the game."""
    if num.kind == "adj" or num.is_adjustment:
        rng = num.adj_range
        return ("Operator setting, %d to %d (also on the Defaults tab)" % rng if rng
                else "Operator setting (also on the Defaults tab)")
    if num.shared and num.editable:
        return "Built into the game, shared by %d modes" % num.shared
    return "Built into the game"


def _why_words(num):
    """Why a number cannot be changed here, in plain words ("" when it can); the exact reason
    is in the row's tooltip."""
    if num.editable:
        return ""
    if num.klass == "code" or num.kind == "code":
        return "The game works this out as it plays, so it cannot be changed here."
    if num.is_adjustment and num.range_inverted:
        return num.why_read_only()[:1].upper() + num.why_read_only()[1:] + "."
    if num.klass == "uncertain":
        return ("The app can't be sure what the game does with this number, so it is not "
                "changed here.")
    if num.klass == "scene":
        return "It lives in a scene file, not in the game program."
    if num.value is None:
        return "Its value hasn't been read, so it is not changed here."
    return "The app can't change this number in place safely, so it is not changed here."


TAB = ModesTab
