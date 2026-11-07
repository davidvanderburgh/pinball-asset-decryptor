"""Expression Lights tab (PAD-1040): the cabinet's expression light shows of a Stern Spike 2 card.

BEN (Discord): "if songs are swapped out, the expression lighting is no longer in sync with the replaced audio track"
(Led Zeppelin). David: "an expression light show creator just like the playfield light show creator", and "we should
be able to create and edit these light shows without having to disable IC for users since it does not affect gameplay
scoring".

The page makes the card's own shows for the blades down the cabinet's sides and the backbox speaker lights: the shows
down the left (new from a ready-made one or blank, duplicate, delete), a drawing of THIS game's cabinet in the middle
PLAYING the show picked (its lights read off the card's game program, painted by the runtime's own arithmetic,
static/js/tabs/cabfx.js) with the song it goes with playing under it, and on the right the show's song, its two lanes
of steps on a timeline over the song's waveform, and the step picked. Everything is the project's (``cab_shows`` in
``.staged_changes.json``, :mod:`...plugins.stern.cab_shows`); Write puts ``cabshow.cfg`` beside the mode runtime and
the game plays each show whenever it plays its song. Not a part of the mode maker: a card carrying only these shows
stays on Insider Connected (the runtime arms them before the score gate and never reaches it).
"""

import hashlib
import json
import os
import threading

from .base import TabService, rpc

INTRO = ("Light shows of your own for the cabinet's expression lights - the blades down its sides and the speaker "
         "lights - each played with the song it goes with, so a song you replaced gets lights that follow it.")
INSIDER = ("These shows change only the cabinet's lights, not the game or its scores: a card that carries only these "
           "shows stays on Insider Connected.")
#: the shortest sound the song list offers (audio_categories' music length)
SONG_MIN_SECONDS = 20.0
PEAKS = 600


def _songs(audio):
    """The project's songs, from the Audio tab's scan: ``[{slot, rel, name, seconds, path, replaced}]`` - every sound
    of a sound-bank record at least :data:`SONG_MIN_SECONDS` long (its replacement's length and file when it has
    one)."""
    from ...core import audio as _A
    from ...plugins.stern import sound_modes as SM
    if audio is None:
        return []
    assign = getattr(audio, "_assign", {}) or {}
    out = []
    for s in getattr(audio, "_slots", ()) or ():
        slot = SM.slot_idx(s.rel_path)
        if slot is None:
            continue
        path, secs, repl = s.abs_path, s.duration, assign.get(s.rel_path)
        if s.info is None:                              # the scan reads no headers: this one's length, now
            try:
                got = _A.detect_audio_info(s.abs_path)
                secs = got.duration if got is not None else 0.0
            except Exception:                           # noqa: BLE001 - unknown length: not offered
                secs = 0.0
        own = secs
        if repl and os.path.isfile(repl):
            try:
                info = _A.detect_audio_info(repl)
                secs = info.duration if info is not None else secs
            except Exception:                           # noqa: BLE001 - its own length unknown: the slot's
                pass
            path = repl
        if max(secs, own) < SONG_MIN_SECONDS:
            continue
        name = os.path.splitext(os.path.basename(s.rel_path))[0]
        out.append({"slot": slot, "rel": s.rel_path, "name": name, "seconds": round(secs, 3), "path": path,
                    "replaced": bool(repl), "file": os.path.basename(repl) if repl else ""})
    out.sort(key=lambda r: r["slot"])
    return out


def peaks(path, n=PEAKS):
    """The waveform of a WAV for the timeline: ``n`` loudness values 0..255 (empty when it cannot be read)."""
    import wave
    try:
        with wave.open(path, "rb") as w:
            ch, width, frames = w.getnchannels(), w.getsampwidth(), w.getnframes()
            if width != 2 or not frames:
                return []
            raw = w.readframes(frames)
    except (OSError, EOFError, wave.Error):
        return []
    import array
    a = array.array("h")
    a.frombytes(raw[:len(raw) - len(raw) % 2])
    step = max(1, len(a) // (n * 64))                  # a sample in every few, enough to see the beats
    per = max(1, len(a) // n)
    out = []
    for k in range(n):
        seg = a[k * per:(k + 1) * per:step]
        out.append(min(255, max((abs(v) for v in seg), default=0) >> 7))
    _ = ch
    return out


def _auto_styles():
    from ...plugins.stern import cab_auto as CA
    return CA.STYLES


class LightsTab(TabService):
    ns = "lights"
    key = "Expression Lights"
    label = "Expression lights"
    group = "Make"
    icon = "lights"

    def __init__(self, window):
        super().__init__(window)
        self._project = ""
        self._shows = []
        self._read_id = 0
        from ...plugins.stern import cab_shows as CS
        self.set(project="", available=False, why="", reading=False, lights=[], songs=[], shows=[], intro=INTRO,
                 insider=INSIDER, running=False, peaks={}, problems=[], max=CS.SHOWS_MAX, making=False, auto_note="",
                 fx=[{"key": k, "label": v[0], "group": v[1], "uses": v[2]} for k, v in CS.FX.items()],
                 presets=[{"key": p[0], "label": p[1]} for p in CS.PRESETS],
                 styles=[{"key": k, "label": v[0]} for k, v in _auto_styles().items()],
                 limits={"steps": CS.STEPS_MAX, "ms": [CS.STEP_MS_MIN, CS.STEP_MS_MAX], "rate": CS.RATE_MAX,
                         "name": CS.NAME_MAX})

    # -- the project ---------------------------------------------------------------------------------------------
    def _folder(self):
        var = getattr(self.window, "write_assets_var", None)
        return ((var.get() if var is not None else "") or "").strip()

    def on_project(self, folder):
        if getattr(self, "_visible", False) or self.window.current_tab_key() == self.key:
            self._read()

    def on_show(self):
        self._visible = True
        if self._folder() != self._project:
            self._read()
        else:
            self._songs_now()
        self._audio_ready()

    def on_running(self, running, mode):
        self.set(running=bool(running))

    def _audio_ready(self):
        """The songs are the Audio tab's scan of this project: start one when it has not read it."""
        audio = self.window.service("audio")
        folder = self._folder()
        if audio is None or not folder:
            return
        if getattr(audio, "_scan_dir", "") != folder and not getattr(audio, "_scanning", False):
            try:
                audio.scan()
            except Exception:                           # noqa: BLE001 - the list just stays empty
                pass

        def wait():                                     # the song list once the scan is in
            import time
            for _ in range(240):
                time.sleep(0.5)
                if getattr(audio, "_scan_dir", "") == folder and not getattr(audio, "_scanning", False):
                    break
            self.ctx.loop.post(self._songs_now)
        threading.Thread(target=wait, daemon=True, name="lights-songs").start()

    def _songs_now(self):
        songs = _songs(self.window.service("audio"))
        self.set(songs=songs)
        self._paint(songs)

    def _read(self):
        """The project's shows now, and the cabinet's lights off its card (a worker: it may open the card)."""
        from ...core import staged_changes
        from ...plugins.stern import cab_shows as CS
        folder = self._folder()
        self._project = folder
        self._read_id += 1
        rid = self._read_id
        if not folder:
            self._shows = []
            self.set(project="", available=False, reading=False, lights=[],
                     why="Set the project folder on the Extract tab first: the shows are the project's.")
            return
        try:
            self._shows = CS.norm(staged_changes.load(folder).get(CS.STAGED_KEY))["shows"]
        except Exception:                               # noqa: BLE001 - an unreadable sidecar: none yet
            self._shows = []
        self.set(project=folder, reading=True)

        def work():
            why, lights = "", []
            try:
                why, lights = project_layout(folder)
            except Exception as e:                      # noqa: BLE001 - said on the page
                why = "The game's cabinet lights could not be read: %s" % e
            self.ctx.loop.post(lambda: self._read_done(rid, lights, why))
        threading.Thread(target=work, daemon=True, name="lights-read").start()

    def _read_done(self, rid, lights, why):
        if rid != self._read_id:
            return
        self.set(reading=False, available=not why, why=why, lights=lights)
        self._songs_now()

    def _paint(self, songs=None):
        from ...plugins.stern import cab_shows as CS
        slots = {s["slot"] for s in (songs if songs is not None else self.get("songs") or [])}
        self.set(shows=[dict(s, length=CS.length_ms(s)) for s in self._shows],
                 problems=[CS.problems(s, slots if slots else None) for s in self._shows])

    def _save(self, what=""):
        from ...core import history_log, staged_changes
        from ...plugins.stern import cab_shows as CS
        if not self._project:
            return False
        data = staged_changes.load(self._project)
        before = json.dumps(data.get(CS.STAGED_KEY), sort_keys=True)
        if self._shows:
            data[CS.STAGED_KEY] = {"shows": self._shows}
        else:
            data.pop(CS.STAGED_KEY, None)
        staged_changes.save(self._project, data)
        if what and before != json.dumps(data.get(CS.STAGED_KEY), sort_keys=True):
            history_log.record(self._project, ["expression lights  %s" % what])
            self.log("Expression lights: %s." % what, "info")
        self._paint()
        return True

    # -- the buttons -----------------------------------------------------------------------------------------------
    @rpc
    def refresh(self):
        self._read()
        self._audio_ready()
        return True

    @rpc
    def new_show(self, preset="blank", slot=None):
        """A new show from a ready-made one (or blank), for the song in *slot* when given; returns its index."""
        from ...plugins.stern import cab_shows as CS
        if not self._project or len(self._shows) >= CS.SHOWS_MAX:
            return -1
        s = CS.norm_show(CS.preset(str(preset)))
        if isinstance(slot, int) and slot >= 0:
            s["slot"] = slot
            song = next((x for x in self.get("songs") or [] if x["slot"] == slot), None)
            if song:
                s["name"] = song["name"].split(" - ")[-1][:CS.NAME_MAX] or s["name"]
        names = {x["name"] for x in self._shows}
        base, n = s["name"], 2
        while s["name"] in names:
            s["name"] = ("%s %d" % (base, n))[:CS.NAME_MAX]
            n += 1
        self._shows.append(s)
        self._save("show \"%s\" added" % s["name"])
        return len(self._shows) - 1

    @rpc
    def duplicate(self, i):
        from ...plugins.stern import cab_shows as CS
        i = int(i)
        if not 0 <= i < len(self._shows) or len(self._shows) >= CS.SHOWS_MAX:
            return -1
        s = CS.norm_show(json.loads(json.dumps(self._shows[i])))
        s["name"] = ("%s copy" % s["name"])[:CS.NAME_MAX]
        self._shows.insert(i + 1, s)
        self._save("show \"%s\" added" % s["name"])
        return i + 1

    @rpc
    def delete(self, i):
        i = int(i)
        if not 0 <= i < len(self._shows):
            return False
        s = self._shows.pop(i)
        return self._save("show \"%s\" taken out" % s["name"])

    @rpc
    def save_show(self, i, show):
        """The page's edit of show *i*, whole (normalized here: what is saved is what the card gets)."""
        from ...plugins.stern import cab_shows as CS
        i = int(i)
        if not 0 <= i < len(self._shows) or not isinstance(show, dict):
            return False
        s = CS.norm_show(show)
        if s == self._shows[i]:
            return False
        self._shows[i] = s
        return self._save("show \"%s\" changed" % s["name"])

    @rpc
    def song_peaks(self, slot):
        """The waveform of the song in *slot* (its replacement's when it has one), for the timeline."""
        slot = int(slot)
        song = next((x for x in self.get("songs") or [] if x["slot"] == slot), None)
        if not song:
            return False
        got = dict(self.get("peaks") or {})
        key = str(slot)
        if got.get(key, {}).get("path") == song["path"]:
            return True

        def work():
            p = peaks(song["path"])
            self.ctx.loop.post(lambda: self._peaks_done(key, song["path"], p))
        threading.Thread(target=work, daemon=True, name="lights-peaks").start()
        return True

    def _peaks_done(self, key, path, p):
        got = dict(self.get("peaks") or {})
        got[key] = {"path": path, "v": p}
        self.set(peaks=got)

    @rpc
    def auto_show(self, i, style):
        """Make show *i*'s steps from its song (cab_auto, a worker: it reads the whole song), in *style*; its old
        steps are replaced (one step of the project's history)."""
        from ...plugins.stern import cab_auto as CA
        i = int(i)
        if not 0 <= i < len(self._shows) or self.get("making"):
            return False
        show = self._shows[i]
        song = next((x for x in self.get("songs") or [] if x["slot"] == show["slot"]), None)
        if not song:
            self.set(auto_note="Pick the show's song first: the show is made from it.")
            return False
        style = style if style in CA.STYLES else CA.DEFAULT_STYLE
        self.set(making=True, auto_note="Listening to %s..." % song["name"])
        name, slot = show["name"], show["slot"]

        def work():
            note, made = "", None
            try:
                wav = _wav_for(song["path"])
                made, info = CA.make(wav, style, name=name, slot=slot)
                note = "Made from the song: %s, %d blade step(s), %d speaker step(s)." % (
                    CA.describe(info), len(made["blades"]), len(made["speakers"]))
            except CA.AutoError as e:
                note = "The show could not be made from the song: %s." % e
            except Exception as e:                      # noqa: BLE001 - said on the page
                note = "The show could not be made from the song: %s" % e
            self.ctx.loop.post(lambda: self._auto_done(i, name, made, note))
        threading.Thread(target=work, daemon=True, name="lights-auto").start()
        return True

    def _auto_done(self, i, name, made, note):
        self.set(making=False, auto_note=note)
        if made is None or not 0 <= i < len(self._shows) or self._shows[i]["name"] != name:
            return
        self._shows[i]["blades"], self._shows[i]["speakers"] = made["blades"], made["speakers"]
        self._shows[i]["loop"] = False
        self._save("show \"%s\" made from its song" % name)

    @rpc
    def try_it(self):
        """Run in emulator: the Emulate tab, started with the project's changes (the shows among them)."""
        emu = self.window.service("emulate")
        if emu is None:
            return False
        var = getattr(emu, "emulate_overrides_var", None)
        if var is not None and not var.get():
            var.set(True)
        self.window.select_tab("emulate")
        try:
            return bool(emu.toggle()) if not (getattr(emu, "_last_up", False) or emu._launched()) else True
        except Exception:                               # noqa: BLE001 - the Emulate tab says why
            return False


def _wav_for(path):
    """A WAV of the song to measure: the file itself, or (a replacement in another format) one ffmpeg makes, kept
    beside the app's other caches by the source's name, size and time."""
    if path.lower().endswith(".wav"):
        return path
    import subprocess
    from ...core import audio as _A
    from ...plugins.stern import title_reader as TR
    key = "%s|%d|%d" % (path, os.path.getsize(path), int(os.path.getmtime(path)))
    out = os.path.join(TR.cache_dir("cab_auto"), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".wav")
    if os.path.isfile(out):
        return out
    ff = _A.find_ffmpeg()
    if not ff:
        from ...plugins.stern.cab_auto import AutoError
        raise AutoError("the song is not a WAV and ffmpeg was not found to read it")
    subprocess.run([ff, "-y", "-v", "error", "-i", path, "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out],
                   check=True, capture_output=True, timeout=300)
    return out


def project_layout(project):
    """``(why, lights)``: the cabinet's expression lights of the card *project* was made from (cab_shows.layout),
    cached per card; ``why`` says why there are none ("" when there are)."""
    from ...plugins.stern import cab_shows as CS
    from ...plugins.stern import mode_project as MP
    from ...plugins.stern import title_reader as TR
    got = MP.project_card(project) if project else None
    card = getattr(got, "image", "") if got is not None else ""
    if not card or not os.path.isfile(card):
        return ("The card this project was extracted from is not on this PC, so the app cannot read its cabinet's "
                "lights. Point the project at its card on the Extract tab."), []
    key = "%s|%d|%d" % (card, os.path.getsize(card), int(os.path.getmtime(card)))
    cache = os.path.join(TR.cache_dir("cab_layout"), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("key") == key and raw.get("v") == 1:
            lights = raw["lights"]
            return ("" if lights else CS.NO_LIGHTS), lights
    except (OSError, ValueError, KeyError, TypeError):
        pass
    lights = CS.layout(TR.game_program(card)[2])
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "key": key, "lights": lights}, f)
    except OSError:
        pass
    return ("" if lights else CS.NO_LIGHTS), lights


TAB = LightsTab
