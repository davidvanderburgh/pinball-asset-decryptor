r"""Sound for the Multi-boot tab's boot-menu preview (item 90).

The preview draws the boot menu by RUNNING the real ARM selector under
qemu-user and showing the PPM it writes, and David wants the preview to sound
like the menu too: the highlighted image's music bed while it is highlighted,
and the move click when the highlight changes.  The selector itself cannot
help here - a ``--snapshot`` run draws one frame and exits, and its ALSA sink
is on the far side of WSL - so the app plays those same WAVs itself.

WHICH MEANS THIS FILE IS A COPY OF A MIXER THAT ALREADY EXISTS, and the copy
is deliberate: ``tools/spike2_emu/codeselect/audio.c`` is what the card will
actually do, so what the preview does is written to match it sample for
sample rather than to sound nice.  Everything the C mixer decides is decided
the same way here -

  * four voices, summed as int32, then one gain, then saturation to s16;
  * ``volume`` 0-100 is a LINEAR gain, ``volume * 256 / 100`` in 8-bit fixed
    point - so a 50 in the menu conf means the same loudness in the preview;
  * a stopped voice ramps out over 882 frames (20 ms) instead of clicking;
  * a WAV must be PCM 16-bit 44100 Hz, 1 or 2 channels (mono is duplicated),
    and a longer one is cut at 120 seconds;
  * moving to a card whose music is the SAME clip does not restart the music
    (``codeselect.c``: "its music takes over (hard switch)" only fires when
    ``media.music[hl] != music_clip``).

WHERE THE SOUND COMES OUT.  sounddevice + numpy when they are there, because
that is the only backend that can genuinely mix a one-shot OVER a loop, which
is the thing the menu does.  Windows without sounddevice falls back to
``winsound``, which can loop a file asynchronously but plays exactly ONE sound
at a time: the click interrupts the music and the music restarts from the top
after it.  That is a compromise, not a feature, and :attr:`PreviewAudio.status`
says so in words the tab can put on a label.  Anything else - macOS with no
sounddevice, a machine with no output device at all - gets a null player that
is silent and says why.

NOTHING HERE MAY RAISE INTO THE TAB, and nothing here may block the Tk thread.
A preview that cannot make a sound must still draw its picture, so every
failure becomes a sentence in :attr:`PreviewAudio.status` instead of a
traceback; and every slow step - importing sounddevice, opening the device,
reading a 20 MB music bed - happens on this player's own worker thread, so
:meth:`PreviewAudio.loop` and :meth:`PreviewAudio.play` return immediately
whatever the machine is doing.  Importing this module opens nothing and
imports neither sounddevice nor numpy; the first :meth:`loop` does.  And
because that first open is slow enough for a person to change their mind
during it, a device opened here is owned - and closed - by the one worker
that opened it, so a stop that has to give up waiting still hands the device
back rather than losing it (see :class:`_Session`).
"""

import importlib
import os
import queue
import sys
import threading
import wave

#: The selector's format, and the only one it accepts (audio.h's AUDIO_RATE).
RATE = 44100
CHANNELS = 2
#: audio.c's VOICES / FADE_FRAMES / CLIP_CAP_S, kept in step by name.
VOICES = 4
FADE_FRAMES = 882
CLIP_CAP_SECONDS = 120
#: media.json's own default (selectmedia.DEFAULT_VOLUME).
DEFAULT_VOLUME = 50
#: Frames per callback.  ~23 ms: short enough that the move click lands with
#: the keypress, long enough that a busy Tk process does not starve it.
BLOCK_FRAMES = 1024
#: How long stop() waits for the worker to finish before letting it run out on
#: its own.  A timeout here is survivable only because the worker owns its own
#: backend and closes it on the way out whatever else has happened since (see
#: :class:`_Session`); what a timeout costs is a moment of a device still being
#: held, not a device nothing can close.
STOP_JOIN_SECONDS = 2.0

_NP = None


def _numpy():
    """numpy, imported on first use.

    Module scope would cost every app start ~40 ms for a tab most runs never
    open, and would make this module unimportable on an install without it."""
    global _NP
    if _NP is None:
        import numpy
        _NP = numpy
    return _NP


class WavRefused(Exception):
    """A file this player will not play; the message is a readable sentence."""


# ---------------------------------------------------------------------------
# WAV
# ---------------------------------------------------------------------------

def wav_header(path):
    """``{'rate','channels','sampwidth','frames','seconds'}`` of a WAV.

    The standard library's :mod:`wave` and nothing else: the media directory's
    sounds were written by ``selectmedia.py``, which already normalised them,
    so a file that needs a decoder is a file the card would refuse too.
    Raises :class:`WavRefused` when it cannot be read at all."""
    try:
        with wave.open(path, "rb") as w:
            rate, ch = w.getframerate(), w.getnchannels()
            sw, n = w.getsampwidth(), w.getnframes()
    except Exception as exc:                                # noqa: BLE001
        # Everything, not just wave.Error: a truncated header surfaces as
        # struct.error, a directory as OSError, and neither may reach the tab.
        raise WavRefused("%s cannot be read as a WAV (%s)"
                         % (os.path.basename(path), exc))
    return {"rate": rate, "channels": ch, "sampwidth": sw, "frames": n,
            "seconds": n / float(rate) if rate else 0.0}


def wav_refusal(header):
    """``None`` when a :func:`wav_header` meets the selector's contract, else
    the sentence saying which part of it does not.

    The same three tests as ``selectmedia.wav_contract_error`` and
    ``audio.c``'s loader, said as prose rather than as a table cell: the
    preview refuses exactly what the card refuses, so a file that is silent
    here is a file that would be silent on the machine."""
    if header["sampwidth"] != 2:
        return ("it is %d-bit, and the selector plays only 16-bit PCM"
                % (header["sampwidth"] * 8))
    if header["rate"] != RATE:
        return "it is %d Hz, and the selector plays only %d Hz" % (
            header["rate"], RATE)
    if header["channels"] not in (1, 2):
        return ("it has %d channels, and the selector plays only mono or "
                "stereo" % header["channels"])
    return None


def read_clip(path, cap_seconds=CLIP_CAP_SECONDS):
    """A WAV as an ``(frames, 2)`` int16 numpy array, mono duplicated.

    Raises :class:`WavRefused` with a readable reason for anything the
    selector would not play.  ``cap_seconds`` is audio.c's CLIP_CAP_S: a
    longer bed is cut rather than held whole in memory."""
    np = _numpy()
    head = wav_header(path)
    why = wav_refusal(head)
    if why:
        raise WavRefused("%s will not play: %s" % (os.path.basename(path), why))
    want = head["frames"]
    if cap_seconds:
        want = min(want, int(cap_seconds * RATE))
    try:
        with wave.open(path, "rb") as w:
            raw = w.readframes(want)
    except Exception as exc:                                # noqa: BLE001
        raise WavRefused("%s stopped part way through (%s)"
                         % (os.path.basename(path), exc))
    # '<i2' and not 'int16': a WAV is little-endian wherever it is read, and
    # frombuffer on a big-endian host would otherwise decode noise.
    a = np.frombuffer(raw, dtype="<i2")
    if head["channels"] == 2:
        a = a[:(len(a) // 2) * 2].reshape(-1, 2)
    else:
        a = np.repeat(a.reshape(-1, 1), 2, axis=1)
    if not len(a):
        raise WavRefused("%s holds no samples" % os.path.basename(path))
    return np.ascontiguousarray(a, dtype=np.int16)


class ClipCache(object):
    """The decoded clips, keyed by path + mtime + size.

    move.wav is played on every flipper press and the music bed is re-asked
    for on every redraw, so without this the preview would re-read (and
    re-convert) the same megabytes on the Tk thread's behalf all evening.  A
    file that changed on disk misses, which is what a rebuilt media directory
    needs."""

    def __init__(self, limit=8):
        self.limit = limit
        self._items = {}
        self._order = []

    def key(self, path):
        st = os.stat(path)
        return (os.path.abspath(path), st.st_mtime, st.st_size)

    def get(self, path):
        try:
            k = self.key(path)
        except OSError as exc:
            raise WavRefused("%s is not there (%s)"
                             % (os.path.basename(path), exc))
        hit = self._items.get(k)
        if hit is None:
            hit = read_clip(path)
            self._items[k] = hit
            self._order.append(k)
            while len(self._order) > self.limit:
                self._items.pop(self._order.pop(0), None)
        return hit


# ---------------------------------------------------------------------------
# the mixer - audio.c's mix(), in numpy
# ---------------------------------------------------------------------------

def clamp_volume(volume, default=DEFAULT_VOLUME):
    """0-100, the way ``audio_open`` clamps it; anything unreadable is the
    default rather than an exception, because no volume is worth a traceback."""
    try:
        return max(0, min(100, int(volume)))
    except (TypeError, ValueError):
        return default


def gain_q8(volume):
    """0-100 -> audio.c's ``gain_q8``: ``volume * 256 / 100``, clamped.

    Linear, not a decibel curve, because that is what the card does; the
    number on the menu's ``volume=`` line and the number handed to
    :meth:`PreviewAudio.set_volume` must mean the same loudness."""
    return clamp_volume(volume) * 256 // 100


class Voice(object):
    """One playing clip: audio.c's ``struct voice``, same fields, same rules."""

    def __init__(self):
        self.clip = None
        self.pos = 0
        self.loop = False
        self.active = False
        self.fade_left = 0

    def start(self, clip, loop):
        self.clip, self.pos, self.loop = clip, 0, bool(loop)
        self.active, self.fade_left = True, 0

    def fade_out(self):
        """Ramp out over FADE_FRAMES.  A voice already fading is left alone -
        restarting the ramp would make a stop-during-stop louder, not quieter."""
        if self.active and not self.fade_left:
            self.fade_left = FADE_FRAMES

    def render_into(self, acc, frames):
        """Add this voice's next *frames* frames to an int32 ``(frames, 2)``
        accumulator, advancing (and wrapping, and ending) exactly as the C
        mixer's inner loop does."""
        if not self.active or self.clip is None:
            return
        np = _numpy()
        n = len(self.clip)
        buf = np.zeros((frames, 2), dtype=np.int32)
        got = 0
        while got < frames and self.active:
            take = min(frames - got, n - self.pos)
            buf[got:got + take] = self.clip[self.pos:self.pos + take]
            self.pos += take
            got += take
            if self.pos >= n:
                if self.loop:
                    self.pos = 0
                else:
                    self.active = False
        if self.fade_left:
            f = self.fade_left
            k = min(frames, f)
            ramp = np.arange(f, f - k, -1, dtype=np.int32)
            buf[:k] = buf[:k] * ramp[:, None] // FADE_FRAMES
            buf[k:] = 0
            self.fade_left = f - k
            if not self.fade_left:
                self.active = False
        acc += buf


class Mixer(object):
    """audio.c's ``struct audio`` without the sinks: voices in, one block out.

    The lock is held for the few microseconds it takes to hand a voice a new
    clip or to read the gain.  Holding a lock across an audio callback would
    be a mistake; holding one for an array assignment is how the control side
    and the device thread agree on what is playing."""

    def __init__(self, volume=DEFAULT_VOLUME, voices=VOICES):
        self.lock = threading.Lock()
        self.voices = [Voice() for _ in range(voices)]
        self.gain_q8 = gain_q8(volume)

    def set_volume(self, volume):
        with self.lock:
            self.gain_q8 = gain_q8(volume)

    def start(self, clip, loop=False):
        """Give a clip a voice and return its index, or -1.

        audio_play()'s allocation, unchanged: the first free voice, else the
        first non-looping one (a click may be stolen, the music may not), else
        voice 0."""
        if clip is None or not len(clip):
            return -1
        with self.lock:
            for i, v in enumerate(self.voices):
                if not v.active:
                    v.start(clip, loop)
                    return i
            i = next((j for j, v in enumerate(self.voices) if not v.loop), 0)
            self.voices[i].start(clip, loop)
            return i

    def fade_out(self, index):
        if 0 <= index < len(self.voices):
            with self.lock:
                self.voices[index].fade_out()

    def stop_all(self):
        with self.lock:
            for v in self.voices:
                v.clip, v.active, v.fade_left = None, False, 0

    def playing(self, index):
        return 0 <= index < len(self.voices) and self.voices[index].active

    def render(self, frames):
        """One block, int16 ``(frames, 2)``: sum the voices, then ONE gain,
        then saturate - the order audio.c mixes in, because a gain applied
        per-voice would clip differently."""
        np = _numpy()
        acc = np.zeros((frames, 2), dtype=np.int32)
        with self.lock:
            for v in self.voices:
                v.render_into(acc, frames)
            g = self.gain_q8
        acc *= g
        acc >>= 8
        np.clip(acc, -32768, 32767, out=acc)
        return acc.astype(np.int16)


# ---------------------------------------------------------------------------
# the backends
# ---------------------------------------------------------------------------
# Each one answers loop(path|None), play(path|None), set_volume(0-100) and
# close(), and each returns "" when it did the thing or a readable sentence
# when it could not.  They never raise; PreviewAudio would swallow it anyway,
# and a returned sentence is something the tab can show.

class NullBackend(object):
    """Silence, and the reason for it."""

    name = "none"
    note = ""

    def __init__(self, reason=""):
        self.reason = reason

    def loop(self, path):
        return ""

    def play(self, path):
        return ""

    def set_volume(self, volume):
        return ""

    def close(self):
        return ""


class SoundDeviceBackend(object):
    """PortAudio, mixing our own voices - the one backend that behaves like
    the card, because the click really does play over the music."""

    name = "sounddevice"

    def __init__(self, sd, volume=DEFAULT_VOLUME, blocksize=BLOCK_FRAMES,
                 candidates=None):
        self.sd = sd
        self.mixer = Mixer(volume)
        self.cache = ClipCache()
        self.stream = None
        #: Which of output_candidates() answered, as a sentence for the status.
        self.note = ""
        self._blocksize = blocksize
        self._candidates = candidates
        self._loop_voice = -1

    def start(self):
        """Open and start the output stream, trying the routes in turn.

        Returns how it got out; raises the LAST failure when none of them
        worked, so the fallback's reason names something a person can act on
        rather than "no device"."""
        last = None
        for device, extra, how in (self._candidates
                                   if self._candidates is not None
                                   else output_candidates(self.sd)):
            stream = None
            try:
                kw = {"extra_settings": extra} if extra is not None else {}
                stream = self.sd.OutputStream(
                    samplerate=RATE, channels=CHANNELS, dtype="int16",
                    blocksize=self._blocksize, device=device,
                    callback=self._callback, **kw)
                stream.start()
            except Exception as exc:                        # noqa: BLE001
                last = exc
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:                       # noqa: BLE001
                        pass
                continue
            self.stream = stream
            self.note = "It is playing through %s." % how
            return how
        raise last if last is not None else RuntimeError(
            "there is no output device to try")

    def _callback(self, outdata, frames, time_info, status):
        """PortAudio's thread, and the one place in this file where an
        exception would be heard rather than read: a raise here kills the
        stream mid-evening, so a bad block becomes silence instead."""
        try:
            outdata[:] = self.mixer.render(frames)
        except Exception:                                   # noqa: BLE001
            try:
                outdata[:] = 0
            except Exception:                               # noqa: BLE001
                pass

    def loop(self, path):
        if not path:
            if self._loop_voice >= 0:
                self.mixer.fade_out(self._loop_voice)
                self._loop_voice = -1
            return ""
        try:
            clip = self.cache.get(path)
        except WavRefused as exc:
            return str(exc)
        if self._loop_voice >= 0:
            self.mixer.fade_out(self._loop_voice)
        self._loop_voice = self.mixer.start(clip, loop=True)
        return ""

    def play(self, path):
        if not path:
            return ""
        try:
            clip = self.cache.get(path)
        except WavRefused as exc:
            return str(exc)
        self.mixer.start(clip, loop=False)
        return ""

    def set_volume(self, volume):
        self.mixer.set_volume(volume)
        return ""

    def close(self):
        self.mixer.stop_all()
        self._loop_voice = -1
        s, self.stream = self.stream, None
        if s is None:
            return ""
        try:
            s.stop()
            s.close()
        except Exception as exc:                            # noqa: BLE001
            return "the sound device did not close cleanly (%s)" % exc
        return ""


class WinsoundBackend(object):
    """Windows' own player, and a compromise.

    ``winsound.PlaySound`` will loop a file asynchronously, which is the music
    bed; what it will not do is play a second sound at the same time.  So the
    move click STOPS the music, and the music is started again - from the top,
    because winsound has no notion of a position - once the click has had its
    own duration.  It is audibly not what the card does.  It is still better
    than a preview with no sound at all on a machine that never had
    sounddevice installed, and :attr:`note` says which of the two the listener
    is hearing.

    The volume knob is inert here too: winsound has no gain, so every sound
    plays at the level the WAV was written at.  A volume of 0 is the one
    setting it can honour, and it honours it by staying quiet."""

    name = "winsound"
    note = ("winsound plays one sound at a time, so the move click stops the "
            "music and the music starts again from the top after it; the "
            "volume is the file's own except at 0, which is silence.")

    def __init__(self, winsound, volume=DEFAULT_VOLUME, schedule=None):
        self.ws = winsound
        self.volume = clamp_volume(volume)
        # A seam, so the tests can watch the resume being scheduled without
        # waiting for a real timer to fire.
        self._schedule = schedule or self._timer
        self._resume = None
        self._loop_path = None

    @staticmethod
    def _timer(delay, fn):
        t = threading.Timer(delay, fn)
        t.daemon = True
        t.start()
        return t

    def _flag(self, name, default):
        return getattr(self.ws, name, default)

    def _cancel_resume(self):
        r, self._resume = self._resume, None
        if r is not None:
            try:
                r.cancel()
            except Exception:                               # noqa: BLE001
                pass

    def _purge(self):
        try:
            self.ws.PlaySound(None, self._flag("SND_PURGE", 0x0040))
        except Exception:                                   # noqa: BLE001
            pass

    def _start_loop(self):
        if not self._loop_path or not self.volume:
            return ""
        flags = (self._flag("SND_FILENAME", 0x00020000)
                 | self._flag("SND_ASYNC", 0x0001)
                 | self._flag("SND_LOOP", 0x0008)
                 | self._flag("SND_NODEFAULT", 0x0002))
        try:
            self.ws.PlaySound(self._loop_path, flags)
        except Exception as exc:                            # noqa: BLE001
            return "%s would not play (%s)" % (
                os.path.basename(self._loop_path), exc)
        return ""

    def loop(self, path):
        self._cancel_resume()
        if not path:
            self._loop_path = None
            self._purge()
            return ""
        try:
            why = wav_refusal(wav_header(path))
        except WavRefused as exc:
            return str(exc)
        if why:
            return "%s will not play: %s" % (os.path.basename(path), why)
        self._loop_path = path
        return self._start_loop()

    def play(self, path):
        if not path:
            return ""
        try:
            head = wav_header(path)
        except WavRefused as exc:
            return str(exc)
        why = wav_refusal(head)
        if why:
            return "%s will not play: %s" % (os.path.basename(path), why)
        if not self.volume:
            return ""
        self._cancel_resume()
        flags = (self._flag("SND_FILENAME", 0x00020000)
                 | self._flag("SND_ASYNC", 0x0001)
                 | self._flag("SND_NODEFAULT", 0x0002))
        try:
            self.ws.PlaySound(path, flags)
        except Exception as exc:                            # noqa: BLE001
            return "%s would not play (%s)" % (os.path.basename(path), exc)
        if self._loop_path:
            # +50 ms so the resume does not cut the tail off the click.
            self._resume = self._schedule(head["seconds"] + 0.05,
                                          self._resume_loop)
        return ""

    def _resume_loop(self):
        self._resume = None
        self._start_loop()

    def set_volume(self, volume):
        v = clamp_volume(volume, self.volume)
        was, self.volume = self.volume, v
        if not v:
            self._cancel_resume()
            self._purge()
        elif not was:
            self._start_loop()
        return ""

    def close(self):
        self._cancel_resume()
        self._loop_path = None
        self._purge()
        return ""


def pick_output_device(sd, platform=None):
    """The WASAPI default output on Windows, else None (the system default).

    padplay.py's reasoning, and its measurement: PortAudio's default host API
    on Windows is MME, which dates to 1991 and carries ~200 ms of latency - a
    move click that arrives a fifth of a second after the flipper is a click
    that sounds like a fault.  WASAPI measures 3 ms on this machine."""
    if (platform or sys.platform) != "win32":
        return None
    try:
        for api in sd.query_hostapis():
            if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
                return api["default_output_device"]
    except Exception:                                       # noqa: BLE001
        pass
    return None


def output_candidates(sd, platform=None):
    """``[(device, extra_settings, how), ...]`` - the ways out, best first.

    WASAPI IS NOT ENOUGH ON ITS OWN, which is what this list is for.  In
    shared mode WASAPI will only open a stream at the endpoint's own mix rate,
    and David's speakers sit at 96 kHz: a plain 44100 open of the WASAPI
    default is refused outright ("Invalid sample rate", PaErrorCode -9997)
    while the SAME device opens happily with ``WasapiSettings(auto_convert=
    True)``, which puts Windows' own resampler in the path.  The selector's
    media is 44100 and nothing else, so resampling is not optional here.

    The settings object is exclusive to WASAPI - handing it to MME or the
    system default is "Incompatible host API specific stream info"
    (-9984) - so each route carries its own, and an older sounddevice with no
    ``auto_convert`` argument simply contributes one fewer route."""
    out = []
    dev = pick_output_device(sd, platform)
    if dev is not None:
        try:
            out.append((dev, sd.WasapiSettings(auto_convert=True),
                        "WASAPI with Windows' own resampler"))
        except Exception:                                   # noqa: BLE001
            pass                    # an older sounddevice; the plain try below
        out.append((dev, None, "WASAPI"))
    out.append((None, None, "the system's default output"))
    return out


def _import(name):
    return importlib.import_module(name)


def open_backend(volume=DEFAULT_VOLUME, importer=_import, platform=None):
    """``(backend, reason)`` - the best player this machine can give us.

    Tried in the order of how much like the card they sound: sounddevice with
    numpy, then winsound, then silence.  *reason* is "" when a real one
    opened, and otherwise the sentence :attr:`PreviewAudio.status` shows;
    *backend* is never None, so the caller has something to call either way.

    *importer* and *platform* are the seams the tests use to describe a
    machine that is not this one; nothing here is imported until it is
    called."""
    platform = platform or sys.platform
    try:
        sd = importer("sounddevice")
        importer("numpy")
    except Exception as exc:                                # noqa: BLE001
        sd_why = "sounddevice is not installed (%s)" % exc
    else:
        be = SoundDeviceBackend(
            sd, volume, candidates=output_candidates(sd, platform))
        try:
            be.start()
            return be, ""
        except Exception as exc:                            # noqa: BLE001
            sd_why = "sounddevice opened no output device (%s)" % exc
            be.close()      # a half-opened stream must not be left running

    if platform == "win32":
        try:
            ws = importer("winsound")
        except Exception as exc:                            # noqa: BLE001
            ws_why = "winsound would not load (%s)" % exc
        else:
            return WinsoundBackend(ws, volume), ""
    else:
        ws_why = "winsound is a Windows module and this is %s" % platform

    why = "No sound: %s, and %s." % (sd_why, ws_why)
    return NullBackend(why), why


# ---------------------------------------------------------------------------
# the player the tab holds
# ---------------------------------------------------------------------------

class _Session(object):
    """One run of the sound: a queue, the worker that drains it, and the ONE
    backend that worker opened.

    A BACKEND BELONGS TO THE SESSION THAT OPENED IT and to nothing else, which
    is the rule that makes a stop() that gives up waiting survivable.  The
    first open is slow - importing sounddevice and numpy, asking PortAudio for
    its host APIs, then up to three tries at an output stream - and a person
    who unticks Sound in the middle of it is not going to be told to wait, so
    :meth:`PreviewAudio.stop` joins for a moment and then lets the worker run
    on.  If the backend lived on the player instead, the next tick would find
    that slot still empty, open a SECOND device, and the two workers would
    race to write and to clear one shared field: whichever lost would be a
    started output stream that no later stop() could reach, still mixing its
    music bed into a device nothing short of ending the process could close.
    Owned here, the abandoned worker closes its own device on its way out
    whatever the newer session is doing.

    ``closing`` is the other half of it.  Once stop() has set it this session
    plays nothing more, so a device it is still in the middle of opening gets
    opened, found unwanted and released without ever having made a sound -
    rather than starting a bed a moment after the tick that meant to end it."""

    def __init__(self):
        self.q = queue.Queue()
        self.thread = None
        self.backend = None
        self.looping = None
        self.closing = False


class PreviewAudio(object):
    """The boot-menu preview's sound, as the tab sees it.

    Four calls - :meth:`loop`, :meth:`play`, :meth:`set_volume`, :meth:`stop` -
    and none of them raises, blocks, or needs to know which backend answered.
    Each one posts to this player's own worker thread and returns at once,
    because the slow parts (importing sounddevice, opening the device, reading
    a music bed off disk) are slow enough to be seen as a stutter if they ran
    on the Tk thread.

    That thread is also why the status is read rather than returned: when
    :meth:`loop` returns, nothing has happened yet.  Read :attr:`status` when
    you next redraw, or pass ``on_status`` to be told - on the worker thread,
    so marshal it with ``widget.after(0, ...)`` before touching a widget.

    Each stop ends a :class:`_Session` and each restart begins a new one, so
    everything that belongs to one run of the sound - the queue, the worker,
    the backend, which bed is looping - lives on the session rather than here.
    What lives here is only what the tab reads: the CURRENT session's backend,
    published for :attr:`status` and friends, and dropped the moment
    :meth:`stop` is called even though the device itself is given back a
    little later, by the worker that owns it."""

    def __init__(self, volume=DEFAULT_VOLUME, backend_factory=None,
                 threaded=True, on_status=None):
        self._factory = backend_factory or open_backend
        self._threaded = threaded
        self._on_status = on_status
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._volume = clamp_volume(volume)
        self._backend = None
        self._why = ""
        self._last_error = ""
        self._session = None

    # ---- what the tab asks --------------------------------------------
    @property
    def volume(self):
        return self._volume

    @property
    def backend_name(self):
        """"sounddevice" / "winsound" / "none", or "" before the first call."""
        be = self._backend
        return be.name if be is not None else ""

    @property
    def available(self):
        """True only when sound is actually coming out.

        False before the first :meth:`loop` too - the backend is chosen on the
        worker thread, and this property will not block the Tk thread to find
        out.  :meth:`wait_ready` is the blocking answer when a caller (or a
        test) genuinely wants one."""
        be = self._backend
        return be is not None and be.name != "none"

    @property
    def why_silent(self):
        """"" when there is sound, else one sentence saying why there is not."""
        be = self._backend
        if be is None:
            return "The sound has not been started yet."
        if be.name == "none":
            return self._why or "No sound on this machine."
        return ""

    @property
    def status(self):
        """One readable sentence for a label, whatever happened.

        Always says which backend is playing (a listener on winsound deserves
        to know why the music keeps restarting), and appends the last file
        that would not play, since a single bad WAV in an otherwise working
        media directory is the failure this preview will actually meet."""
        be = self._backend
        if be is None:
            said = "The sound has not been started yet."
        elif be.name == "none":
            said = self.why_silent
        else:
            said = "Sound plays through %s." % be.name
            if be.note:
                said += " " + be.note
        if self._last_error:
            said += " The last sound did not play: %s." % self._last_error
        return said

    def wait_ready(self, timeout=STOP_JOIN_SECONDS):
        """Block until the backend has been chosen; True if it was in time.

        For a caller that wants to show the status straight away, and for the
        tests.  Never call it from ``on_status``."""
        return self._ready.wait(timeout)

    # ---- the four calls ------------------------------------------------
    def loop(self, path):
        """Start looping *path*, replacing whatever was looping.

        ``None`` (or "") stops the music and leaves the device open.  Asking
        for the file that is ALREADY looping does nothing at all - that is
        codeselect.c's rule, and it is what stops the bed from restarting
        every time the highlight moves between two cards that share it."""
        self._post(("loop", path or None))

    def play(self, path):
        """Fire *path* once, over the loop - the move click."""
        self._post(("play", path or None))

    def set_volume(self, volume):
        """0-100, the menu's own number and the same loudness it means there."""
        v = clamp_volume(volume, self._volume)
        with self._lock:
            self._volume = v
        self._post(("volume", v))

    def stop(self):
        """Silence, release the device, and let the worker go.

        Safe from anywhere, including twice, including from ``on_status`` (the
        join is skipped when the caller IS the worker), and including before
        anything ever played.  A later :meth:`loop` starts the whole thing up
        again - as a NEW session, because this one is finished the moment this
        returns whether or not its worker has caught up.

        The join is a courtesy and not the mechanism: it is here so that a stop
        which can be immediate is immediate.  What actually gives the device
        back is the session that owns it (:class:`_Session`), which is why a
        first open still in flight - the one case where the join really does
        time out - ends with that device closed rather than stranded."""
        with self._lock:
            ses, self._session = self._session, None
            self._backend, self._why = None, ""
        self._ready.clear()
        if ses is None:
            return              # nothing was ever opened; nothing to release
        # Set before the sentinel goes in, so that everything still queued
        # ahead of it - and an open still running - is dropped rather than
        # played to a device this call has already promised is silent.
        ses.closing = True
        if ses.thread is None:
            self._release(ses)  # unthreaded: this call is the one that closes
            return
        ses.q.put(None)
        if threading.current_thread() is not ses.thread:
            # A timeout is survivable and blocking the Tk thread is not: the
            # sentinel is queued and the worker is a daemon that closes its own
            # device before it goes, so waiting longer would buy nothing but a
            # frozen window.
            ses.thread.join(STOP_JOIN_SECONDS)

    # ---- the machinery -------------------------------------------------
    def _post(self, cmd):
        with self._lock:
            ses = self._session
            if ses is None:
                ses = self._session = _Session()
                if self._threaded:
                    ses.thread = threading.Thread(
                        target=self._run, args=(ses,),
                        name="preview-audio", daemon=True)
                    ses.thread.start()
        if ses.thread is None:
            self._apply(cmd, ses)       # unthreaded: the caller does the work
            return
        ses.q.put(cmd)

    def _run(self, ses):
        try:
            while True:
                cmd = ses.q.get()
                if cmd is None:
                    return
                self._apply(cmd, ses)
        finally:
            # The close lives here rather than in a queued command because a
            # queued command is only run by a worker that gets that far, and
            # because it closes THIS session's backend rather than whatever
            # the player's field happens to hold by the time it runs.  However
            # this loop ends - a stop, a sentinel, an unthinkable raise - the
            # device this thread opened is handed back before the thread goes.
            self._release(ses)

    def _apply(self, cmd, ses):
        kind, arg = cmd
        if ses.closing:
            return              # stopped: this session makes no more sound
        be = ses.backend
        if be is None:
            be = self._open(ses)
            if ses.closing:
                # The stop landed while the device was opening.  What we just
                # opened is ours and :meth:`_release` will close it; what must
                # not happen is this now-stale command being heard, a bed
                # starting up a second after the tick that meant to end it.
                return
        err = ""
        try:
            if kind == "loop":
                if arg is not None and arg == ses.looping:
                    return
                ses.looping = arg
                err = be.loop(arg)
            elif kind == "play":
                err = be.play(arg)
            elif kind == "volume":
                err = be.set_volume(arg)
        except Exception as exc:                            # noqa: BLE001
            # The hard rule: a preview that cannot make a sound still draws.
            err = "%s (%s)" % (exc, kind)
        if self._session is ses:
            # A stop can still land between the check above and here, and a
            # session nobody is listening to any more does not get to write
            # the label - least of all to CLEAR an error the live one just put
            # there.
            self._note_error(err or "")

    def _open(self, ses):
        """Choose this session's backend, once, on its own worker.

        A factory that raises is itself a "no sound, because ..." - the whole
        point of this player is that the tab never has to catch anything.

        The backend is written to the session before it is published, because
        from the instant it exists it is something that must be closed, and
        the session is what closes it.  Publishing is only how the status line
        and :attr:`available` get to see it, and a session that :meth:`stop`
        has already let go of does not get to do that: its backend's name on
        the label would describe a device that is on its way out."""
        try:
            be, why = self._factory(self._volume)
        except Exception as exc:                            # noqa: BLE001
            why = "No sound: choosing a player failed (%s)." % exc
            be = NullBackend(why)
        if be is None:
            why = why or "No sound on this machine."
            be = NullBackend(why)
        ses.backend = be
        with self._lock:
            mine = self._session is ses
            if mine:
                self._backend, self._why = be, why
        if mine:
            self._ready.set()
            self._say()
        return be

    def _release(self, ses):
        """Close this session's backend, however late and whoever is asking.

        Idempotent, because a session can be stopped twice and because both an
        unthreaded stop and a worker's exit come through here."""
        be, ses.backend = ses.backend, None
        ses.looping = None
        if be is None:
            return
        err = ""
        try:
            err = be.close()
        except Exception as exc:                            # noqa: BLE001
            err = "%s (close)" % exc
        if err:
            # Only a real complaint, and never the empty string: this can run
            # long after a new session has started playing, and clearing that
            # session's error would be reporting a device that is already gone.
            self._note_error(err)

    def _note_error(self, err):
        if err == self._last_error:
            return
        self._last_error = err
        self._say()

    def _say(self):
        cb = self._on_status
        if cb is None:
            return
        try:
            cb(self)
        except Exception:                                   # noqa: BLE001
            pass                # a status callback must not break the sound
