"""THE JUKEBOX (PAD-685): the song modes play a song drawn at random, each with its own intro video.

An owner rebuilding The Beatles (1.29) kept a card per album and asked for one image instead: 60 and more
songs, "a weighted song selection for the majority of casual Beatles fans" (the common songs often, the
obscure ones now and then), never the same song twice in a game, no choosing ("You boot it up and throw
the dice"), and each song "one audio file and one video file": the song and its intro video with the
song's name in it, the mode screens and the rest made the same for every song.

The project lists its songs (``jukebox`` in ``.staged_changes.json``: ``{"songs": [{"audio": file,
"video": file, "weight": 1..3}, ...]}``, at most :data:`MAX_SONGS`), and a Write does three things:

1. each song's audio is made into the song modes' own format and goes into the sound bank WHOLE as a
   record of its own (the sounds in turn's road, :mod:`.sound_modes`, under a pseudo mode of its own,
   :func:`.sound_modes.juke_mode`, never cut: the game plays a record it is handed whole, whatever the
   length its descriptor gives the part it stands in for - emulator, Beatles 1.29);
2. each song's video is made into the intro clips' format and added to the title's in-game video bank
   as a clip of its own, ``PadJukebox<k>`` (the random clips' road, :mod:`.clip_variants`);
3. ``sounds.cfg`` beside the mode runtime names, for each song mode of the title (:data:`TITLES`), its
   start (a port site), its intro clips and its records, and for each song its weight, its record's key
   and its clip (``jmode`` / ``jsong`` lines). The runtime (pad_mode_runtime.c "the jukebox") draws a
   song at each song mode's start - weighted, never one of the last five drawn - and until the mode's
   next start every record of the mode plays that song and every intro of it shows that song's clip.

Emulator-proven on Beatles 1.29 with the stock songs dealt among their own modes (Drive My Car's start
drew It Won't Be Long: its intro and its audio, r 0.992 against the stock capture).

POOLS (PAD-1007): the same owner asked for "X pools, each with its own song/audio list", which "drive and
restrict which audio clips are rotated based on the original audio track": the five song modes draw from one
list, the two special modes from another, the two background songs from a third, and a song wanted in two
pools is added to each (each pool has its own songs). A song's ``pool`` is the key of one of its title's
:data:`POOLS` (:data:`DEFAULT_POOL` when it names none: a jukebox made before pools is the song modes');
every music of the title (:data:`TITLES`) belongs to one pool, and a Write ends each ``jmode`` / ``jsong``
line with its pool's number (its place in the title's pools): a music's start draws one of its own pool's
songs, and a music whose pool has no song plays its own.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

#: the project sidecar's key: ``{"songs": [{"audio": file, "video": file, "weight": 1..3, "pool": key}, ...]}``
STAGED_KEY = "jukebox"
#: songs a card may carry (pad_mode_runtime.c JUKE_SONGS)
MAX_SONGS = 128
#: a song's weight: a Common song comes up three times as often as a Rare one
WEIGHTS = ((3, "Common"), (2, "Normal"), (1, "Rare"))
DEFAULT_WEIGHT = 2
#: what an added intro clip is called in the bank (k = the song's number, 1..)
CLIP_NAME = "PadJukebox%d"
#: PAD-1007: the pool of a song that names none (a jukebox made before pools): the song modes'
DEFAULT_POOL = "songs"
#: pools a card may have (pad_mode_runtime.c JUKE_POOLS)
MAX_POOLS = 8


@dataclass(frozen=True)
class SongMode:
    """A song mode of a title: its name, its start (a port site the runtime hooks, ``""`` for none:
    it draws when the game first asks for its music), its intro clips (the project's video slots, its
    own first: the songs' clips are made into its format), their names in the video bank, its music's
    records (the sound bank's idx numbers, its opening first) and (PAD-1007) its pool."""
    name: str
    site: str
    intros: tuple
    clips: tuple
    records: tuple
    pool: str = DEFAULT_POOL


@dataclass(frozen=True)
class Pool:
    """PAD-1007: one of a title's pools of music: its key (a song's ``pool``), its name in the Jukebox
    window and what plays its songs (the window's line under it)."""
    key: str
    name: str
    about: str


#: ``<game>-<version>``: the song modes, read off the emulator (each song mode started and its
#: start, its intro clip on the bank's surface and its records' lookups logged) and the song
#: descriptor table (Beatles 1.29: 0x4b60e0, 0x38 a song, the start at +0xc, the music request at
#: +0x34: 89, 87, 85, 83, 84)
TITLES = {
    "beatles-1.29": (
        SongMode("All My Loving", "block_start_0",
                 ("video/FeatureStarts_Frenzy_Start.mov",
                  "video/Feature_Starts_Short_Frenzy_Start_Short.mov"),
                 ("FeatureStarts.Frenzy_Start", "Feature_Starts_Short.Frenzy_Start_Short"), (419, 848)),
        SongMode("Drive My Car", "block_start_1",
                 ("video/FeatureStarts_Orbits_Start.mov",
                  "video/Feature_Starts_Short_Orbits_Start_Short.mov"),
                 ("FeatureStarts.Orbits_Start", "Feature_Starts_Short.Orbits_Start_Short"), (200, 417)),
        SongMode("I Should Have Known Better", "block_start_2",
                 ("video/FeatureStarts_DropTarget_Start.mov",
                  "video/Feature_Starts_Short_DropTarget_Start_Short.mov"),
                 ("FeatureStarts.DropTarget_Start", "Feature_Starts_Short.DropTarget_Start_Short"), (753, 669)),
        SongMode("Ticket to Ride", "block_start_3",
                 ("video/FeatureStarts_Spinner_Start.mov",
                  "video/Feature_Starts_Short_Spinner_Start_Short.mov"),
                 ("FeatureStarts.Spinner_Start", "Feature_Starts_Short.Spinner_Start_Short"), (722, 431)),
        SongMode("It Won't Be Long", "block_start_4",
                 ("video/FeatureStarts_POP_Start.mov",
                  "video/Feature_Starts_Short_POP_Bumper_Start_Short.mov"),
                 ("FeatureStarts.POP_Start", "Feature_Starts_Short.POP_Bumper_Start_Short"), (42, 667)),
        # PAD-1007: the game's other four musics (sound ids 952-960 are its nine, one record pair each; the
        # request table). The two multiballs' (the special modes): Beatlemania Multiball, the four-ball one
        # (emulator: its own start, wizard_go_1, showed Taxman_Start and looked up sid 952's records, request
        # 90 "MUSIC: TAXMAN MULTIBALL"), and the jackpot multiball (sid 955, request 82 "MUSIC: MULTIBALL
        # 1", called from the multiball start's other branch and beside the Multiball_A clips: its intro
        # Multiball_feature.Multiball_A_Start). The other two, 958 ("MUSIC: MULTIBALL READY") and 956, are
        # the background songs, with no intro of their own. No start site: each draws when the game first
        # asks for it (again at the next game, or after JUKE_GAP without it)
        SongMode("Beatlemania Multiball", "", ("video/Taxman_Start.mov",), ("Taxman_Start",), (461, 370),
                 "special"),
        SongMode("Jackpot multiball", "", ("video/Multiball_feature_Multiball_A_Start.mov",),
                 ("Multiball_feature.Multiball_A_Start",), (574, 797), "special"),
        SongMode("Background song (multiball ready)", "", (), (), (148, 311), "background"),
        SongMode("Background song", "", (), (), (294, 494), "background"),
    ),
}

#: PAD-1007: ``<game>-<version>``: its pools, in the order the Jukebox window shows them (a title with no
#: entry has one: the song modes)
POOLS = {
    "beatles-1.29": (
        Pool("songs", "Song modes", "The five song modes: each start draws one of these songs."),
        Pool("special", "Special modes", "The two multiballs (the four-ball one and the jackpot one): "
                                         "each start draws one of these songs, with its own intro video."),
        Pool("background", "Background music", "The two background songs: each game draws one of these in "
                                               "the place of each. They open with no intro video."),
    ),
}
SONG_MODES_POOL = Pool(DEFAULT_POOL, "Song modes", "The song modes: each start draws one of these songs.")

NO_TITLE = "The app cannot tell which game this project is for, so it cannot give it a jukebox."
NOT_OFFERED = ("A jukebox is not offered on %s. It is made for the song modes of The Beatles 1.29.")
#: ``PAD_STERN_JUKEBOX=0`` leaves the jukebox out of a build
GATE_ENV = "PAD_STERN_JUKEBOX"


def enabled():
    return os.environ.get(GATE_ENV, "1") != "0"


@dataclass
class Song:
    audio: str
    video: str = ""
    weight: int = DEFAULT_WEIGHT
    pool: str = DEFAULT_POOL


@dataclass
class Jukebox:
    songs: list = field(default_factory=list)

    @property
    def any(self):
        return bool(self.songs)


def clean_weight(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return DEFAULT_WEIGHT
    return max(1, min(3, v))


def clean_pool(v):
    """PAD-1007: a song's pool key (:data:`DEFAULT_POOL` when it names none)."""
    v = str(v).strip() if isinstance(v, str) else ""
    return v[:40] if v else DEFAULT_POOL


def clean(raw):
    """A :class:`Jukebox` from a sidecar's value: songs with an audio file, at most
    :data:`MAX_SONGS`, each in its pool (PAD-1007)."""
    out = Jukebox()
    songs = raw.get("songs") if isinstance(raw, dict) else None
    for s in (songs if isinstance(songs, (list, tuple)) else ()):
        if not isinstance(s, dict):
            continue
        audio = s.get("audio")
        if not isinstance(audio, str) or not audio.strip():
            continue
        video = s.get("video") if isinstance(s.get("video"), str) else ""
        out.songs.append(Song(audio=audio, video=video.strip(), weight=clean_weight(s.get("weight")),
                              pool=clean_pool(s.get("pool"))))
        if len(out.songs) >= MAX_SONGS:
            break
    return out


#: PAD-999: the files Add songs takes as a song's intro video (every other file is a song's audio)
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".mpg", ".mpeg")


def song_key(path):
    """A song's name for pairing and for telling a song already in the jukebox: its file's name
    without the extension, case ignored (``Hey Jude.wav`` and ``hey jude.MP4`` are one song)."""
    return os.path.splitext(os.path.basename(str(path)))[0].strip().casefold()


def pair_files(paths):
    """PAD-999: Add songs with audio and video files picked together. ``(songs, lone_videos)``:
    *songs* is ``[(key, [audio files], [video files])]`` in the order their names first came, a
    song's files named alike but for the extension; *lone_videos* the videos with no audio file of
    their name, which make no song (a song is its audio; a video is only its intro)."""
    groups = {}
    for p in paths:
        k = song_key(p)
        g = groups.setdefault(k, ([], []))
        kind = 1 if os.path.splitext(str(p))[1].lower() in VIDEO_EXTS else 0
        if p not in g[kind]:
            g[kind].append(p)
    songs = [(k, a, v) for k, (a, v) in groups.items() if a]
    lone = [p for _k, (a, v) in groups.items() if not a for p in v]
    return songs, lone


def to_json(box):
    """The sidecar value for *box* (``None`` when it has no song)."""
    if not box.songs:
        return None
    return {"songs": [dict({"audio": s.audio, "weight": int(s.weight)}, **({"video": s.video} if s.video else {}),
                           **({"pool": s.pool} if s.pool != DEFAULT_POOL else {}))
                      for s in box.songs]}


def load(project):
    """The project's jukebox (empty when it has none)."""
    if not project:
        return Jukebox()
    from ...core import staged_changes
    try:
        return clean(staged_changes.load(project).get(STAGED_KEY))
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return Jukebox()


def save(project, box):
    from ...core import staged_changes
    side = staged_changes.load(project)
    value = to_json(box)
    if value is None:
        side.pop(STAGED_KEY, None)
    else:
        side[STAGED_KEY] = value
    staged_changes.save(project, side)


# ---- which titles -------------------------------------------------------------------------------
def title_key(prof):
    return "%s-%s" % (prof.game_dir, prof.version) if prof is not None else ""


def song_modes(prof):
    """The title's song modes (:data:`TITLES`), ``()`` when it has none."""
    return TITLES.get(title_key(prof), ())


def pools(prof):
    """PAD-1007: the title's pools (:data:`POOLS`), in the Jukebox window's order: the song modes' alone on a
    title with no entry, ``()`` on a title with no song modes."""
    if not song_modes(prof):
        return ()
    return POOLS.get(title_key(prof), (SONG_MODES_POOL,))


def pool_number(prof, key):
    """PAD-1007: the pool *key*'s number on *prof*'s card (its place in :func:`pools`), None when the title
    has no such pool."""
    for n, p in enumerate(pools(prof)):
        if p.key == key:
            return n
    return None


def pool_modes(prof, key):
    """PAD-1007: the title's musics that play pool *key*'s songs."""
    return tuple(m for m in song_modes(prof) if m.pool == key)


def pool_intro(prof, key):
    """PAD-1007: the intro slot (``video/...``) pool *key*'s songs' intro videos are made like, ``""`` when
    none of its musics has an intro the jukebox can show a song's in place of."""
    for m in pool_modes(prof, key):
        if m.intros:
            return m.intros[0]
    return ""


def title_refusal(prof):
    """Why *prof*'s card cannot have a jukebox, or ``""``."""
    if prof is None:
        return NO_TITLE
    if not song_modes(prof):
        return NOT_OFFERED % prof.label
    return ""


def project_title(project, probe=False):
    from . import sound_modes as SM
    return SM.project_title(project, probe=probe)


def offer(project, probe=True):
    """The Audio tab's Jukebox button: ``""`` when the project's game has song modes a jukebox plays,
    why not when the project has songs anyway (made for this game elsewhere), ``None`` (no button) on
    every other game. *probe* may open the card image, so never on the UI thread."""
    if not enabled():
        return None
    why = title_refusal(project_title(project, probe=probe))
    if not why:
        return ""
    return why if load(project).any else None


def pool_rows(project, probe=True):
    """PAD-1007: the Jukebox window's pools for the project's game: ``[{"key", "name", "about", "intro"}]``
    (*intro*: its musics have an intro a song's video shows in place of), the title's own in its order, then
    any pool the project's songs name that the game does not have (made for another game: they stay listed,
    so they can be moved or taken out). *probe* as :func:`offer`."""
    prof = project_title(project, probe=probe)
    rows = [{"key": p.key, "name": p.name, "about": p.about, "intro": bool(pool_intro(prof, p.key))}
            for p in pools(prof)] or [{"key": DEFAULT_POOL, "name": SONG_MODES_POOL.name,
                                       "about": SONG_MODES_POOL.about, "intro": True}]
    have = {r["key"] for r in rows}
    for s in load(project).songs:
        if s.pool not in have:
            have.add(s.pool)
            rows.append({"key": s.pool, "name": s.pool, "intro": False,
                         "about": "This game has no pool of this name: these songs are left out of a build."})
    return rows


def slot_rel(project, idx):
    """The project's audio slot of record *idx* (``audio/idx0848.wav`` or however its file is named
    there), ``""`` when it has none."""
    from . import sound_modes as SM
    audio = os.path.join(project, "audio")
    try:
        names = sorted(os.listdir(audio))
    except OSError:
        return ""
    for n in names:
        if n.lower().endswith(".wav") and SM.slot_idx(n) == int(idx):
            return "audio/" + n
    return ""


def host_slot(project, prof):
    """The slot whose format the songs' audio is made into: the longest song mode record of the title
    the project has (every song mode's records share one format). PAD-1007: the first pool's records
    (the song modes', as before pools), another pool's only when the project has none of those."""
    first = pools(prof)[0].key if pools(prof) else DEFAULT_POOL
    return _longest(project, pool_modes(prof, first)) or _longest(project, song_modes(prof))


def _longest(project, modes):
    best = ("", -1)
    for m in modes:
        for idx in m.records:
            rel = slot_rel(project, idx)
            if not rel:
                continue
            try:
                size = os.path.getsize(os.path.join(project, *rel.split("/")))
            except OSError:
                continue
            if size > best[1]:
                best = (rel, size)
    return best[0]


def clip_name(k):
    """The bank name of song *k*'s intro clip (1..)."""
    return CLIP_NAME % int(k)
