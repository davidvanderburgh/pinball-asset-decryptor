"""PAD-1190: the song a long video clip plays with, found by name and length.

A JJP song video carries no sound of its own: the game plays the song from a
separate file while the clip runs.  Guns N' Roses names the pair after the
song (``graphics/Songs/CivilWar/live_edited_CivilWar.webm`` and
``sound/music/CivilWar/BG_GnR_BEAT_MAP_CivilWar.ogg``) and cuts them to the
same length (7:35 both).  The game's program is not read here (JJP's is
encrypted native code), so the pairing is the files' own: a clip and a sound
whose names END the same way, both long enough to be a song, of near enough
the same length.

Measured on GnR 3.03 (every clip against every sound): with both at least
30 s and within 20% of each other, all 23 ``live_edited_<song>`` clips, the 7
Slash solos and the easter-egg promo pair with their song, every
``stage_video_<song>`` cut with the same song at its own length, and nothing
else.  Shorter clips are left alone: their names end in words like ``Intro``,
``Loop`` or ``gold`` that many unrelated short sounds share.
"""
import os
import re

#: a clip or a sound shorter than this is not paired (seconds)
MIN_SECONDS = 30.0
#: the most a paired sound's length may differ from the clip's, as a share
MAX_DIFF = 0.20
#: a difference this small (seconds) is "the same length"
SAME_SECONDS = 2.0

AUDIO_EXTS = (".ogg", ".wav", ".mp3", ".flac")
#: folders a project keeps that are not the game's own files
_SKIP_DIRS = ("_replacements",)

_TOKEN = re.compile(r"[_\-. ]+")


def tokens(name):
    """The words of a file name, without its extension."""
    stem = os.path.splitext(os.path.basename(name))[0]
    return [t.lower() for t in _TOKEN.split(stem) if t]


def _common_tail(a, b):
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return a[len(a) - n:]


def _tail_is_a_name(tail):
    """A shared ending says something only when it holds a real word."""
    return any(len(t) >= 4 and not t.isdigit() for t in tail)


def names_match(clip, sound):
    """Whether *sound*'s name ends the way *clip*'s does.  A clip's short last
    word (``_expl``, ``.a``) is a variant mark and may be left off."""
    ct, st = tokens(clip), tokens(sound)
    if _tail_is_a_name(_common_tail(ct, st)):
        return True
    if len(ct) > 1 and len(ct[-1]) <= 4 and ct[-1].isalpha():
        return _tail_is_a_name(_common_tail(ct[:-1], st))
    return False


def audio_files(project):
    """Every sound file under *project* (project-relative, ``/``-separated),
    leaving out the folders the user keeps their own files in."""
    out = []
    if not project or not os.path.isdir(project):
        return out
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d.lower() not in _SKIP_DIRS]
        for f in files:
            if f.lower().endswith(AUDIO_EXTS):
                rel = os.path.relpath(os.path.join(root, f), project)
                out.append(rel.replace(os.sep, "/"))
    out.sort()
    return out


def lengths_match(clip_s, sound_s):
    if clip_s < MIN_SECONDS or sound_s < MIN_SECONDS:
        return False
    # of the longer one: GnR's Civil War stage cut is 6:10 against its 7:35 song (18.5%)
    return abs(sound_s - clip_s) <= MAX_DIFF * max(clip_s, sound_s)


def songs_for(project, clip_rel, clip_s, audio=None, duration=None):
    """``[(sound rel, its seconds)]`` that play with the clip *clip_rel* of
    *clip_s* seconds, nearest length first.  *audio* is :func:`audio_files`
    of the project (read when not given); *duration(path)* measures a sound
    (``core.audio.probe_duration`` by default)."""
    if not clip_rel or not clip_s or clip_s < MIN_SECONDS:
        return []
    if audio is None:
        audio = audio_files(project)
    if duration is None:
        from .audio import probe_duration as duration
    out = []
    for rel in audio:
        if not names_match(clip_rel, rel):
            continue
        secs = duration(os.path.join(project, *rel.split("/"))) or 0.0
        if lengths_match(clip_s, secs):
            out.append((rel, secs))
    out.sort(key=lambda p: (abs(p[1] - clip_s), p[0]))
    return out


def clock(seconds):
    s = int(round(seconds))
    return "%d:%02d" % (s // 60, s % 60)


def how_words(clip_s, sound_s):
    """How the sound's length sits against the clip's, in words."""
    d = sound_s - clip_s
    if abs(d) <= SAME_SECONDS:
        return "same song name, same length (%s)" % clock(sound_s)
    return "same song name; the sound is %s, %s %s than the clip" % (
        clock(sound_s), clock(abs(d)), "longer" if d > 0 else "shorter")
