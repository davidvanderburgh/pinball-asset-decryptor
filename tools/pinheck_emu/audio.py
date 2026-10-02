"""The Propeller's sound, high level: a mixer of the card's own wavs (PAD-320).

The sound packets are AMH's (github.com/benheck/AMH ``playSFX`` & co.) in
every game seen so far:

* 0x01 play: byte 0 the channel (3 = music), byte 1 the folder letter,
  bytes 2..3 the clip -> ``SFX/_F<folder>/<folder><clip>.wav``, byte 4 the
  priority (a lower one does not cut a playing clip). Music is folder Z
  (``SFX/_FZ/Zxx.wav``; AMH's own cards name them ``#xx.wav``); a group
  byte with bit 7 set plays the clip once and goes back to the music.
* 0x08 the same, queued after the channel's current clip.
* 0x0D the same, panned (bytes 5 and 6 left/right volume).
* 0x10 volume: ``f`` channel left right; ``z`` fade the music (speed,
  target; 0 0 stops it); ``r`` repeat the music (1) or not.
* 0x09 (the colour games, not AMH): play music by name, bytes 0..2
  (``ZBB`` -> ``SFX/_FZ/ZBB.wav``).

``mix(n)`` renders the next n stereo frames at ``RATE`` as int16 numpy;
the window plays them, a headless run never does. ``levels`` logs what
started and how loud the mix was, so a muted run can show its sound.
"""
import os
import threading
import wave

RATE = 44100
PLAY, QUEUE, PAN, VOLUME, MUSIC_BY_NAME = 0x01, 0x08, 0x0D, 0x10, 0x09
MUSIC = 3
FULL = 25           # the volume the games set by default ('f' ch 25 25)


def load_wav(path):
    """int16 stereo numpy at RATE, or None if the file cannot be read."""
    import numpy as np
    try:
        with wave.open(path) as w:
            rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            data = w.readframes(w.getnframes())
    except (OSError, EOFError, wave.Error):
        return None
    if width != 2:
        return None
    a = np.frombuffer(data, "<i2").reshape(-1, ch)
    if ch == 1:
        a = np.repeat(a, 2, axis=1)
    a = a[:, :2]
    if rate != RATE and len(a):
        idx = (np.arange(int(len(a) * RATE / rate)) * rate / RATE).astype(np.int64)
        a = a[np.minimum(idx, len(a) - 1)]
    return np.ascontiguousarray(a)


class Clip:
    def __init__(self, name, samples, priority, once=False):
        self.name, self.samples, self.priority, self.once = name, samples, priority, once
        self.pos = 0
        self.pan = None


class Sound:
    def __init__(self, card):
        self.card = card
        self.channels = {}          # channel -> Clip
        self.queued = {}            # channel -> [Clip]
        self.volume = {}            # channel -> (left, right), 0..~31
        self.music_repeat = True
        self.music_fade = None      # (speed, target)
        self.paused_music = None    # the music under a play-once clip
        self.levels = []            # (millis, text)
        self.master = 1.0           # the window's volume, 0..1 (0 = mute)
        self._cache = {}
        self._lock = threading.Lock()

    def path(self, folder, clip):
        d = os.path.join(self.card, "SFX", "_F" + folder)
        for name in (folder + clip, "#" + clip):
            p = os.path.join(d, name + ".wav")
            if os.path.isfile(p):
                return p
        return None

    def _clip(self, folder, clip, priority, once=False):
        p = self.path(folder, clip)
        if p is None:
            return None
        if p not in self._cache:
            self._cache[p] = load_wav(p)
        s = self._cache[p]
        return None if s is None else Clip(folder + clip, s, priority, once)

    def packet(self, pkt, millis):
        cmd = pkt[15]
        if cmd in (PLAY, QUEUE, PAN):
            ch = pkt[0]
            group, c1 = pkt[2], pkt[3]
            once = ch == MUSIC and bool(group & 0x80)
            group &= 0x7F
            folder = chr(pkt[1]) if 32 < pkt[1] < 127 else None
            if folder is None or not (32 < group < 127 and 32 < c1 < 127):
                return
            clip = self._clip(folder, chr(group) + chr(c1), pkt[4], once)
            with self._lock:
                if clip is None:
                    self.levels.append((millis, "missing %s%c%c" % (folder, group, c1)))
                    return
                if cmd == PAN:
                    clip.pan = (pkt[5], pkt[6])
                cur = self.channels.get(ch)
                if cmd == QUEUE and cur is not None:
                    self.queued.setdefault(ch, []).append(clip)
                    return
                if cur is not None and cur.pos < len(cur.samples) and clip.priority < cur.priority:
                    return
                if once and cur is not None and not cur.once:
                    self.paused_music = cur
                self.channels[ch] = clip
                if ch == MUSIC:
                    self.music_fade = None
                self.levels.append((millis, "ch%d %s" % (ch, clip.name)))
        elif cmd == MUSIC_BY_NAME:
            name = bytes(pkt[0:3]).decode("latin1")
            if not name.isalnum():
                return
            clip = self._clip(name[0], name[1:], 255)
            with self._lock:
                if clip is None:
                    self.levels.append((millis, "missing %s" % name))
                    return
                self.channels[MUSIC] = clip
                self.music_fade = None
                self.levels.append((millis, "music %s" % name))
        elif cmd == VOLUME:
            what = chr(pkt[0]) if pkt[0] < 128 else ""
            with self._lock:
                if what == "f":
                    self.volume[pkt[1]] = (pkt[2], pkt[3])
                elif what == "z":
                    if pkt[1] == 0 and pkt[2] == 0:
                        self.channels.pop(MUSIC, None)
                        self.levels.append((millis, "music stop"))
                    else:
                        self.music_fade = (pkt[1], pkt[2])
                elif what == "r":
                    self.music_repeat = bool(pkt[1])

    def _gain(self, ch, clip):
        if clip.pan is not None:
            left, right = clip.pan
        else:
            left, right = self.volume.get(ch, (FULL, FULL))
        if ch == MUSIC and self.music_fade is not None:
            target = self.music_fade[1]
            left, right = min(left, target), min(right, target)
        return min(left, 31) / FULL, min(right, 31) / FULL

    def mix(self, n):
        """The next ``n`` stereo frames, int16 numpy (n, 2)."""
        import numpy as np
        out = np.zeros((n, 2), np.float32)
        with self._lock:
            for ch in list(self.channels):
                clip = self.channels[ch]
                done = 0
                while done < n and clip is not None:
                    take = min(n - done, len(clip.samples) - clip.pos)
                    if take > 0:
                        gl, gr = self._gain(ch, clip)
                        seg = clip.samples[clip.pos:clip.pos + take].astype(np.float32)
                        out[done:done + take, 0] += seg[:, 0] * gl
                        out[done:done + take, 1] += seg[:, 1] * gr
                        clip.pos += take
                        done += take
                    if clip.pos >= len(clip.samples):
                        nxt = self.queued.get(ch)
                        if nxt:
                            clip = nxt.pop(0)
                        elif clip.once and self.paused_music is not None:
                            clip, self.paused_music = self.paused_music, None
                        elif ch == MUSIC and self.music_repeat and not clip.once:
                            clip.pos = 0
                        else:
                            clip = None
                        if clip is None:
                            self.channels.pop(ch, None)
                        else:
                            self.channels[ch] = clip
        out *= self.master
        return np.clip(out, -32768, 32767).astype(np.int16)

    def level(self, millis, n=RATE // 20):
        """Mix ``n`` frames and log their RMS (for a muted run's proof)."""
        import numpy as np
        block = self.mix(n)
        rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2))) if len(block) else 0.0
        self.levels.append((millis, "rms %.0f" % rms))
        return rms
