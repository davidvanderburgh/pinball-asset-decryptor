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


class ModesTab(TryItMixin, TabService):
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
        "changes. A card holds up to %d modes; one runs at a time." % MP.MAX_MODES)

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
               "second and every 1.6 s; Chase lights one of them at a time. Godzilla's ports "
               "name the inserts; on a title whose port does not, nothing is lit.")
    PRIORITY_TIP = ("How the mode's screen and clip sit among the game's own displays while it "
                    "runs, on the game's own scale (1-255). At 180 the game's full-screen shot "
                    "awards (LOOPS) and BATTLE IS LIT wait until the mode ends; its jackpots, "
                    "multiball and battle starts and the tilt warning still come through, and "
                    "the mode's screen is back when they end. Higher holds more back (190: "
                    "starts and jackpots wait too). 0 leaves the game's display order as it is.")
    FILM_TIP = ("Cut this mode's clip, its sound or its screen's picture from a film: pick "
                "the film, a start time and a length (up to 30 seconds), and whether to keep "
                "the film's letterbox or fill the frame. The mode keeps only the cut "
                "(clip.mp4, end.wav, art.png), never the film.")
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
        self._shot_names = [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
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
        # the title (item 148)
        self._profile = MP.GODZILLA_PRO_1_15
        self._applied_key = MP.GODZILLA_PRO_1_15.key
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
        self._init_tryit()
        self.set(project="", project_label="", title_text="", title_note="", no_port="",
                 profile=self._profile_payload(MP.GODZILLA_PRO_1_15), rows=[], sel=None,
                 cap_text="", new_ok=False, ex_ok=False, dup_ok=False, del_ok=False,
                 examples=[], open=False, editor_on=False, form=dict(self.f),
                 shots_on=[], awards=dict(self._shot_awards), shots_text="", status="",
                 save_state="", labels={}, files={}, starts_words="", preview=None,
                 reasons={}, dis={}, code=None, code_words="", cut_ok=False,
                 stock={"msg": "", "rows": [], "on": False, "sel": None, "note": "",
                        "value": "", "row_on": False},
                 film=None, about=self.ABOUT_TIP, n_form=0, n_code=0, ready=False,
                 fix_pages=[], spin=dict(self.SPINBOXES), sdk_doc=self.sdk_doc())
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
            card.trace_add("write", lambda *_a: self._post(self._show_emu))

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
        working = self._tryit["state"] in self.TRYIT_WORKING
        live = self._tryit["state"] == "live"
        if not (shown or working or live):
            self._ticker_on = False
            return
        try:
            self._tryit_tick()
            self._show_emu(quiet=True)
        except Exception:                                   # noqa: BLE001
            pass
        self._ticker_job = self.ctx.loop.after(150 if working else 1000, self._tick)

    # ------------------------------------------------------------------
    # the list
    # ------------------------------------------------------------------
    def refresh(self, select=None, select_code=None):
        """Re-read the project's modes into the list, keeping (or choosing) a selection."""
        project = self.project()
        if self._slug is not None and project != self._open_project:
            self._save_if_edited()
            self._slug, self._spec = None, None
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
            self.set(status="" if not project else
                     "No modes yet. Press New for a blank mode, or pick one under "
                     "Examples - KAIJU RUSH is the one that has run on a machine.",
                     save_state="", sel=None, code=None)
            self._note_no_port_in_status()
            self._publish_rows()
            return
        self._open(want, self._found[want])

    def _show_cap(self, project, n):
        if not project:
            text = ""
        elif n >= MP.MAX_MODES:
            text = ("%d of %d modes: delete one to add another. Modes written in C are "
                    "not counted." % (n, MP.MAX_MODES))
        else:
            text = "%d of %d modes" % (n, MP.MAX_MODES)
        self.set(cap_text=text, n_form=n, n_code=len(self._code_list))
        self._publish_examples()

    def _publish_examples(self):
        p = self._profile or MP.GODZILLA_PRO_1_15
        shown = self._examples_profile or p
        items = [{"name": name, "code": False, "disabled": bool(self._at_cap)}
                 for name, _s in MP.examples_for(shown)]
        from ...plugins.stern import code_modes as CM
        prof = self._profile if self._profile is not None else None
        if prof is None or str(getattr(prof, "game_dir", "")).startswith("godzilla"):
            for name in CM.example_names():
                items.append({"name": name, "label": name + self.CODE_EXAMPLE_SUFFIX,
                              "code": True, "disabled": False})
        self.set(examples=items, new_ok=bool(self._new_ok and not self._no_port),
                 ex_ok=bool(self._ex_ok and not self._no_port))

    _examples_profile = None
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
            rows.append({"slug": slug, "kind": "code", "name": name, "chip": "",
                         "chip_tip": ""})
        sel = ({"slug": self._code_slug, "kind": "code"} if self._code_slug else
               {"slug": self._slug, "kind": "form"} if self._slug else None)
        self.set(rows=rows, sel=sel)

    @rpc
    def select(self, slug, kind="form"):
        """A row of the list was picked."""
        if kind == "code":
            if self._code_slug == slug:
                return True
            self._save_if_edited()
            self._show_code(slug)
            return True
        if slug == self._slug and self._code_slug is None:
            return True
        self._save_if_edited()
        found = dict(MP.list_modes(self.project())[0])
        if slug in found:
            self._code_slug = None
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
        self.set(save_state="saved", code=None)
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
            "film": FCD.describe(spec) or "Nothing cut from a film yet.",
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
        """(label, name) for the events the shown title's port carries (Godzilla Pro
        1.15's until a title with events of its own is shown)."""
        p = self._events_profile or MP.GODZILLA_PRO_1_15
        events = p.events or MP.GODZILLA_PRO_1_15.events
        return [(MP.EVENT_LABELS.get(n, n), n) for n in events]

    _events_profile = None

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
        return MP.blank_spec(self._profile or MP.GODZILLA_PRO_1_15)

    # ------------------------------------------------------------------
    # the title: which card, which port (item 148)
    # ------------------------------------------------------------------
    def _profile_payload(self, p):
        """What the page needs of the shown title: its shots (and how many columns they
        take), the events the start and end lists offer, the measured callouts Pick
        offers, and the early-ending shot list (the Tk tab rebuilt each of these per
        title in _apply_profile and _apply_profile_to_advanced)."""
        names = [n for n, _m in p.shots]
        choices = [{"label": "%s (%d)" % (label, number), "number": number}
                   for label, number in MP.callout_choices(p) if number]
        events = [MP.EVENT_LABELS.get(n, n) for n in (p.events or ())] or \
            [label for label, _n in self._event_choices()]
        return {"key": p.key, "label": p.label, "port": p.port, "shots": names,
                "cols": 2 if len(names) <= self._TWO_COLUMN_SHOTS else 3,
                "callouts": choices,
                "callouts_none": ("" if choices else
                                  "(no callouts measured on %s: type an id)" % p.label),
                "events": events, "end_shots": [self.PARAM_NEVER] + names}

    def _apply_project_title(self, project):
        card = MP.project_card(project) if project else None
        profile, text, note, no_port = MP.GODZILLA_PRO_1_15, "", "", ""
        if card is None:
            if project:
                text = ("This project names no card, so its modes are made for %s."
                        % MP.GODZILLA_PRO_1_15.label)
        elif not card.game_dir:
            probed = MP.probed_card_title(card.image) if card.image else None
            if (probed is None and card.image and os.path.isfile(card.image)
                    and card.image not in self._probe_gave_up):
                self._probe_card(card.image)
                text = "Card: %s. Reading which game it is from the card..." % MP.file_name(card.image)
                no_port = "Reading which game the card is."
                profile = None
            else:
                text = ("Card: %s. Which game it is could not be read, so its modes are made for %s."
                        % (MP.file_name(card.image), MP.GODZILLA_PRO_1_15.label))
        else:
            found = MP.profile_for_card(card.game_dir, card.version)
            name = MP.file_name(card.image)
            if found is None:
                label = MP.title_label(card.game_dir, card.version)
                text = "Card: %s, %s (from %s)." % (name, label, card.source)
                no_port = MP.NO_PORT_HELP % label
                note = no_port
                profile = None
            else:
                profile = found
                text = ("Card: %s, %s (from %s). Modes run on its port, %s, with its %d shots."
                        % (name, found.label, card.source, found.port, len(found.shots)))
                note = "" if found.proven else "Unproven: " + found.proven_note
        self._title_note = note
        self._no_port = no_port
        self._profile = profile
        self._card_bound = bool(card is not None and card.game_dir and profile is not None)
        self._shown = None
        self.set(title_text=text, title_note=note, no_port=no_port,
                 title_label=profile.label if profile is not None else "",
                 title_port=profile.port if profile is not None else "",
                 title_shots=len(profile.shots) if profile is not None else 0)
        if profile is not None and profile.key != self._applied_key:
            self._apply_profile(profile)
        elif profile is None and not self._slugs and self._applied_key is not None:
            self._clear_shots()
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
        """Show title ``p``: its shots, and the ready-made modes of the project's title
        (``p`` when the project has none) under Examples."""
        names = [n for n, _m in p.shots]
        self._shot_names = names
        self._shots_on = {n for n in self._shots_on if n in names}
        self._shot_awards = {n: self._shot_awards.get(n, "") for n in names}
        self._examples_profile = self._profile or p
        self._events_profile = p if p.events else self._events_profile
        self._applied_key = p.key
        self._say(said or "modes here are for %s: %d shots, from %s" % (p.label, len(names), p.port))
        self.set(profile=self._profile_payload(p), shots_text="")
        self._publish_form()
        self._publish_examples()

    def _clear_shots(self):
        """No title to show (a card with no port and no mode open): no shot names at all."""
        self._shot_names = []
        self._shots_on = set()
        self._shot_awards = {}
        self.f["start_shot"] = ""
        self._applied_key = None
        reading = self._no_port != self._title_note
        prof = dict(self.get("profile") or {})
        prof.update(shots=[], end_shots=[self.PARAM_NEVER], key="")
        self.set(profile=prof,
                 shots_text="(no shots yet: reading which game the card is)" if reading
                 else "(no shots: this card's game has no port)")
        self._publish_form()

    def _set_editor_state(self, on):
        self._editor_open = bool(on)
        self.set(open=bool(on))
        self._grey_what_the_title_cannot(on)

    _editor_open = False

    def _grey_what_the_title_cannot(self, on=True):
        """Each part the title cannot do is greyed, with the reason in words; a card with no
        port shows the open mode read-only (Delete stays)."""
        p = self._shown or self._profile or MP.GODZILLA_PRO_1_15
        on = bool(on) and self._spec is not None
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
            sound.append("%s's port names no time-up callout, so nothing plays when time is up "
                         "and a sound of the mode's own has no call to replace." % p.label)
        elif p.why_not("own_sound"):
            sound.append(p.why_not("own_sound"))
        if sound:
            reasons["sound"] = "Not on this game: " + " ".join(sound)
        note = getattr(p, "sound_note", "")
        if note and (p.can("countdown") or p.can("own_sound")):
            reasons["sound_unheard"] = "Not heard yet: " + note
        why = "" if p.can("clip") else ("a second clip, since %s cannot add a clip (Clip says "
                                        "why)." % p.label)
        dis["clip_both"] = bool(why)
        if why:
            reasons["clip_both"] = "Not on this game: " + why
        why = p.why_not("stack")
        dis["stack"] = bool(why)
        if why:
            reasons["stack"] = "Not on this game: " + why
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
        words = []
        if old.start_shot and new.start_shot != old.start_shot:
            words.append("%s is not a shot on %s, so it starts on %s until you pick one" % (
                old.start_shot, p.label, new.start_shot))
        gone = [s for s in old.scoring_shots if s in dropped]
        if gone:
            words.append("%s %s not on %s, so %s left out of the shots that score" % (
                ", ".join(gone), "is" if len(gone) == 1 else "are", p.label,
                "it is" if len(gone) == 1 else "they are"))
        words += ModesTab._retarget_advanced_words(old, new, dropped, p)
        return "; ".join(words)

    @staticmethod
    def _retarget_advanced_words(old, new, dropped, p):
        words = []
        rows = old.shot_award if isinstance(old.shot_award, list) else []
        paid = []
        for row in rows:
            if (isinstance(row, (list, tuple)) and len(row) == 2 and row[0] in dropped
                    and row[0] not in paid):
                paid.append(row[0])
        if paid:
            words.append("%s %s not on %s, so %s own points %s left out" % (
                ", ".join(paid), "is" if len(paid) == 1 else "are", p.label,
                "its" if len(paid) == 1 else "their", "are"))
        if isinstance(old.end_shot, str) and old.end_shot and not new.end_shot:
            words.append("%s is not on %s, so no shot ends the mode early until you pick one" % (
                old.end_shot, p.label))
        calls = MP.dropped_callouts(dropped)
        if calls:
            words.append("%s %s a sound number of another game and no callout measured on %s, "
                         "so %s left out" % (", ".join(calls), "is" if len(calls) == 1 else "are each",
                                              p.label, "it is" if len(calls) == 1 else "they are"))
        before = old.callout_at if isinstance(old.callout_at, list) else []
        moved = ["callout %s is %s" % (a[1], b[1]) for a, b in zip(
            [r for r in before if isinstance(r, (list, tuple)) and len(r) == 2
             and MP.CALLOUT_DROPPED % MP._int_or_none(r[1]) not in calls],
            [r for r in new.callout_at if isinstance(r, (list, tuple)) and len(r) == 2])
            if MP._int_or_none(a[1]) != MP._int_or_none(b[1])]
        if moved:
            words.append("%s on %s, the same call" % (", ".join(moved), p.label))
        return words

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
        try:
            own = MP.profile(spec.title)
        except MP.ModeProjectError:
            own = MP.GODZILLA_PRO_1_15
        self._shown = own
        if own.key != self._applied_key:
            self._apply_profile(own, said="%s is shown with the shots of %s, the game it was made for"
                                % (spec.name, own.label))
        return spec

    def _note_no_port_in_status(self):
        no_port = self._no_port
        if no_port:
            self.set(status="Modes cannot be built for this card yet: %s%s" % (
                "it has no port (see above)." if no_port == self._title_note else no_port,
                " The mode is shown as it was saved, read-only." if self._spec is not None else ""))

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
    def new_mode(self, name="NEW MODE", spec=None):
        project = self.project()
        if not project:
            return None
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
        """A form example from the Examples menu (the title's own list)."""
        shown = self._examples_profile or self._profile or MP.GODZILLA_PRO_1_15
        spec = dict(MP.examples_for(shown)).get(name)
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
        self._save_if_edited()
        try:
            slug, _spec = MP.duplicate_mode(self.project(), self._slug)
        except MP.ModeProjectError as e:
            compat.messagebox.showinfo("Duplicate mode", str(e))
            return None
        self._say("duplicated %s as modes/%s" % (self._slug, slug))
        self.refresh(select=slug)
        return slug

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
        self.set(code_words=self.code_modes_words(project), cut_ok=bool(project))

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
                status=("Ready to build." if not problems
                        else "To fix before it can be built: " + " ".join(problems)),
                has_assets_file=os.path.isfile(os.path.join(folder, CM.ASSETS_FILE)))
        self.set(code=data, status="", save_state="")
        self._grey_what_the_title_cannot(False)
        self._publish_rows()

    @rpc
    def new_code_mode(self, name):
        """New code mode…: the page asked "What is the mode called?"."""
        if not self.project():
            self._tryit_note(MP.NO_PROJECT_HELP)
            return None
        if not name or not str(name).strip():
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
                    "the game's own sounds on a plain panel. Press Cut film assets… and pick the "
                    "folder that holds the film%s." % (name, slug, CM.missing_words(missing),
                                                       "s" if len(missing) > 1 else ""))
        return ("added the example %s as modes/%s: its code, and its own clip, picture, music and "
                "calls cut from the films. Try it builds it in; Write puts it on the card."
                % (name, slug))

    @rpc
    def code_example(self, name):
        from ...plugins.stern import code_modes as CM
        project = self.project()
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

    def recut_code_modes(self, dirs, wait=False):
        from ...plugins.stern import code_modes as CM
        project = self.project()
        if not project:
            return None
        try:
            code = [(s, c) for s, c in CM.list_code(project) if (c.film or {}).get("recipe")]
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
    def cut_films(self):
        if not self.project():
            self._tryit_note(MP.NO_PROJECT_HELP)
            return None
        got = self._ask_films_dir("Pick the folder that holds the Godzilla films")
        if not got:
            return None
        return bool(self.recut_code_modes([got]))

    # ------------------------------------------------------------------
    # Try it: the footer's calls
    # ------------------------------------------------------------------
    @rpc
    def tryit(self):
        return bool(self.on_try())

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

    def refresh_stock_modes(self):
        SM = self._SM()
        keep = (self.get("stock") or {}).get("sel")
        self._stock_rows = {}
        self._stock_order = []
        project = self.project()
        build = SM.table_for_project(project) if project else None
        self._stock_build = build
        if not project:
            self._stock_set(msg="Open or extract a card project first (Extract tab) - changes "
                                "to the game's own modes are saved in it.",
                            rows=[], on=False, sel=None, note="", value="", row_on=False)
            return
        if build is None:
            pb = SM.project_build(project)
            known = ", ".join(b.id for b in SM.tables())
            self._stock_set(
                msg="The app doesn't know the timers and awards of %s's own modes yet (it "
                    "knows %s)." % ("%s %s" % pb if pb else "this project's game", known),
                rows=[], on=False, sel=None, note="", value="", row_on=False)
            return
        rec = SM.staged(project)
        from ...core import staged_changes
        settings = staged_changes.load(project).get(SM.SETTINGS_KEY) or {}
        other_build = rec["build"] not in (None, build.id)
        seen_adj = set()
        n_changed = 0
        rows = []
        for num in build.numbers:
            if not num.is_player_facing:
                continue
            if num.kind == "adj":
                if num.adj_name in seen_adj:
                    continue
                seen_adj.add(num.adj_name)
            staged = None
            if num.is_adjustment and num.adj_name in settings:
                staged = settings[num.adj_name]
            elif num.is_word and not other_build and num.row_key in rec["values"]:
                staged = rec["values"][num.row_key]
            stock = "?" if num.value is None else format(num.value, ",")
            if not num.editable:
                value = stock
                where = "%s (read-only)" % num.where_text()
            else:
                value = format(int(staged), ",") + "  ●" if staged is not None else stock
                where = num.where_text()
            if staged is not None:
                n_changed += 1
            rows.append({"key": num.row_key, "mode": build.mode_name(num.mode_id),
                         "number": build.row_label(num), "value": value, "stock": stock,
                         "where": where, "changed": staged is not None,
                         "readonly": not num.editable})
            self._stock_rows[num.row_key] = num
            self._stock_order.append(num.row_key)
        msg = ("%s: %d number(s) of the game's own modes. %s" % (
            build.id, len(self._stock_rows),
            "%d change(s) staged for the next Write." % n_changed if n_changed else
            "Nothing changed - every number is the game's own."))
        if other_build and rec["values"]:
            msg += (" %d change(s) were staged for %s, not this card, and are not written."
                    % (len(rec["values"]), rec["build"]))
        sel = keep if keep in self._stock_rows else None
        self._stock_set(msg=msg + " Rename a mode on the Text tab.", rows=rows, on=True,
                        sel=sel, n_changed=n_changed)
        self._on_stock_select(sel)

    def _on_stock_select(self, key):
        num = self._stock_rows.get(key) if key else None
        if num is None:
            self._stock_set(sel=None, note="", value="", row_on=False)
            return
        why = num.why_read_only()
        if why:
            self._stock_set(sel=key, value="", note="Read-only: %s." % why, row_on=False)
            return
        row = next((r for r in (self.get("stock") or {}).get("rows", []) if r["key"] == key), None)
        cur = (row["value"] if row else "").replace("●", "").strip()
        if num.is_adjustment:
            rng = num.adj_range
            note = ("An operator setting (%s)%s: the same number as on the Defaults tab. A "
                    "machine still on the game's default takes the new one when it boots."
                    % (num.adj_name, ", %d to %d" % rng if rng else ""))
        else:
            note = "One word in the game program (%s)%s." % (
                num.where(), "; it is shared by %d modes, so changing it changes all of them"
                % num.shared if num.shared else "")
        self._stock_set(sel=key, value=cur, note=note, row_on=True)

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
        label = "%s %s" % (build.mode_name(num.mode_id), build.row_label(num).lower())
        if got is None:
            text = "%s is back to the game's own %s." % (label, format(num.value, ","))
        else:
            text = "%s: %s -> %s staged for the next Write." % (
                label, format(num.value, ","), format(got, ","))
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


TAB = ModesTab
