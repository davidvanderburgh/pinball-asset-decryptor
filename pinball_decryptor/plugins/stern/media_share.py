"""PAD-553: music modes and random clips as files of their own, and back out of a card.

A tester who keeps one Godzilla project on two PCs asked that "both audio modes and video random
variants can be saved as separate items (like the scene edits)", and that "when a raw file is read
back by pad it will put the modes back in correctly so the user can visually see what the modes
are", and the same for the random clips.

FILES. The Audio tab's Save the music modes to a file... writes one .zip: the modes' names, each
slot's file for each mode with its loudness, and those files; the Video tab's Save the random
clips to a file... the same for every slot's random clips. Loading one copies its files into the
project's own folder for them (:data:`MUSIC_DIR`, :data:`CLIPS_DIR`; one of the same name and
other bytes already there keeps its name and this one gets a free one) and gives them to the
slots here. A slot is the one at the same path when the game's own sound or clip in it is the
one the file was saved beside; else the slot here holding that sound or clip (a Pro project's
file loaded into a Premium/LE one: the idx numbers differ, the sounds do not); a clip also by
where the card keeps it. Failing those, the same path on a card of the same title. Anything else
is left out and named.

FROM A CARD. A Write records the music modes in the card's ``sounds.cfg``
(:func:`.sound_modes.card_record`): each mode's name, and for each slot's file the sound-bank
record that holds it. An extract of that card has that record as one of its sounds, so
:func:`readback` copies it into :data:`MUSIC_DIR` and gives it back to its slot, with its mode's
name and loudness. Random clips need no record: the card's video bank calls each one
``<the slot's name>__PadVar<k>`` (:data:`.clip_variants.NAME_FORMAT`), so the extract's own files
say which slot they vary (:func:`..core.mod_transfer.baked_variants`). A card written before
cards carried the record gives its music modes back only from the project it was built from,
while that is still on this PC (its build record names it).
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile

from ...core.checksums import MUSIC_MODE_FILES_DIR, RANDOM_CLIP_FILES_DIR
from . import clip_variants as CV
from . import sound_modes as SMo

#: where loaded and read-back files go, in the project (never slots of their own)
MUSIC_DIR = MUSIC_MODE_FILES_DIR
CLIPS_DIR = RANDOM_CLIP_FILES_DIR
#: the manifest inside a file of either kind
MANIFEST = "pad_share.json"
MUSIC_KIND = "pad-music-modes"
CLIPS_KIND = "pad-random-clips"
#: the zip folder their files sit in
FILES = "files"
_VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".bk2")


class ShareError(ValueError):
    """A file that cannot be saved or loaded; the message says why."""


# ---- the slots here -----------------------------------------------------------------------------
def _rels(project, top):
    """The project's slot rels under its ``top`` folder (``audio`` / ``video``), ``/``-separated."""
    out = []
    base = os.path.join(project, top)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for fn in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fn), project).replace(os.sep, "/")
            out.append(rel)
    return out


def _pristine(project, rel):
    """The game's own file in slot *rel*: its ``.orig`` snapshot when a build replaced it."""
    from ...core import staged_originals
    return (staged_originals.snapshot_path(project, rel)
            or os.path.join(project, *rel.split("/")))


def _sig(project, rel):
    """``[size, digest]`` of the game's own file in slot *rel* (:func:`..core.mod_transfer.
    content_signature`), or None."""
    from ...core.mod_transfer import content_signature
    s = content_signature(_pristine(project, rel))
    return list(s) if s else None


class _Slots:
    """The slots of one kind here, found the ways :func:`match` tries."""

    def __init__(self, project, top, video=False):
        self.project = project
        self.rels = [r for r in _rels(project, top)
                     if not video or os.path.splitext(r)[1].lower() in _VIDEO_EXTS]
        self.have = set(self.rels)
        self._sigs = {}
        self.cards = {}
        if video:
            self.cards = {card: rel for rel, card in CV.manifest(project).items()}

    def sig(self, rel):
        if rel not in self._sigs:
            self._sigs[rel] = _sig(self.project, rel)
        return self._sigs[rel]

    def by_sig(self, sig):
        """The slot holding the sound or clip *sig* (``[size, digest]``), or None."""
        if not sig:
            return None
        size = int(sig[0])
        for rel in self.rels:
            try:
                if os.path.getsize(_pristine(self.project, rel)) != size:
                    continue
            except OSError:
                continue
            if self.sig(rel) == list(sig):
                return rel
        return None

    def match(self, rel, sig, card="", same_title=False):
        """``(rel here, how)`` for the file's slot *rel* (its game file *sig*, its card path
        *card*), or ``(None, why)``. On a card of the same title the path is the slot (one whose
        file the card changed included, and never a twin of its sound elsewhere); on another the
        path only while its game file is the same, since idx numbers mean other sounds there."""
        if rel in self.have and (same_title or (sig and self.sig(rel) == list(sig))):
            return rel, ""
        here = self.by_sig(sig)
        if here:
            return here, "found by its sound" if rel.startswith("audio/") else "found by its clip"
        if card and card in self.cards:
            return self.cards[card], "found by where the card keeps it"
        if rel in self.have and not sig:
            return rel, ""
        return None, "this card has no such %s" % ("sound" if rel.startswith("audio/") else "clip")


# ---- copying files in ---------------------------------------------------------------------------
def _safe_name(name, fallback):
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    if not name or name in (".", "..") or ":" in name:
        name = fallback
    return name


def _put(folder, name, data=None, src=None):
    """Write *data* (or copy file *src*) into *folder* as *name*, or the existing file of that
    name holding the same bytes; another of the same name gets ``name (2)``... Returns its path."""
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(name)
    size = len(data) if data is not None else os.path.getsize(src)
    dest, k = os.path.join(folder, name), 2
    while os.path.isfile(dest):
        if os.path.getsize(dest) == size and _same(dest, data, src):
            return dest
        dest = os.path.join(folder, "%s (%d)%s" % (stem, k, ext))
        k += 1
    if data is not None:
        with open(dest, "wb") as f:
            f.write(data)
    else:
        shutil.copyfile(src, dest)
    return dest


def _same(path, data, src):
    with open(path, "rb") as f:
        if data is not None:
            return f.read() == data
        with open(src, "rb") as g:
            while True:
                a, b = f.read(1 << 20), g.read(1 << 20)
                if a != b:
                    return False
                if not a:
                    return True


# ---- writing a file -----------------------------------------------------------------------------
def _about(project):
    from . import mode_project as MP
    try:
        return MP.card_about(project)
    except Exception:                                   # noqa: BLE001 - a nicety in the manifest
        return {}


def _write_zip(path, head, files):
    """*files* ``[(member, source path)]``; sounds deflated, clips stored (already packed)."""
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(head, indent=1))
        for member, src in files:
            packed = os.path.splitext(src)[1].lower() in _VIDEO_EXTS + (".mp3", ".ogg", ".flac")
            z.write(src, member, compress_type=zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED)
    os.replace(tmp, path)


def _members(paths):
    """``{path: member}``, one member per file however often it is named, and the ones gone."""
    members, gone = {}, []
    for p in paths:
        key = os.path.normcase(os.path.abspath(p))
        if key in members:
            continue
        if not os.path.isfile(p):
            gone.append(p)
            continue
        members[key] = "%s/%d/%s" % (FILES, len(members), _safe_name(p, "file"))
    return members, gone


def _member(members, p):
    return members.get(os.path.normcase(os.path.abspath(p)))


def _carried_key(m):
    """How a file under mode *m* is keyed in a carried record: "2" for music mode 2, "t2" for a
    slot's file 2 in turn (PAD-565, :data:`.staged_changes.TURN_KEY`)."""
    from ...core.staged_changes import TURN_KEY
    if SMo.is_mode_turn(m):                             # PAD-638: "m2t3"
        return "m%dt%d" % SMo.mode_turn_of(m)
    return "%s%d" % (TURN_KEY, SMo.turn_of(m)) if SMo.is_turn(m) else str(int(m))


def _key_ok(m):
    """A carried record's mode key this app takes: a music mode 2..MAX_MODES or a file k in turn
    (2..TURN_MAX)."""
    from ...core.staged_changes import _mode_turn_k, _turn_k
    k = _turn_k(m)
    if k is not None:
        return 2 <= k <= SMo.TURN_MAX
    mk = _mode_turn_k(m)
    if mk is not None:
        return 2 <= mk[0] <= SMo.MAX_MODES and 2 <= mk[1] <= SMo.TURN_MAX
    try:
        return 2 <= int(m) <= SMo.MAX_MODES
    except (TypeError, ValueError):
        return False


def save_music_modes(project, path):
    """The project's music modes in one file at *path*. Returns ``{"slots", "files", "gone"}``
    (*gone*: ``[(rel, mode, file)]`` no longer on this PC, left out). Raises :class:`ShareError`
    when there is nothing to save."""
    modes = SMo.load(project)
    if not modes.any:
        raise ShareError("This project has no music modes to save: no sound has a file for "
                         "another mode yet.")
    from ...core import staged_changes
    # a project saved before mode files had a loudness of their own: its files take their
    # sound's, as a mod pack carries them
    own = (staged_changes.sound_modes_of(staged_changes.load(project)) or {}).get("levels") or {}
    members, _g = _members([f for _r, _m, f in modes.files()] + list(modes.attract))
    gone = [(r, m, f) for r, m, f in modes.files() if not _member(members, f)]
    # PAD-641: the flipper buttons' sounds in attract, in their order
    attract = [_member(members, f) for f in modes.attract if _member(members, f)]
    gone += [("", SMo.attract_mode(k), f) for k, f in enumerate(modes.attract, 1)
             if not _member(members, f)]
    slots, levels, sigs = {}, {}, {}
    for rel, m, f in modes.files():
        mem = _member(members, f)
        if not mem:
            continue
        slots.setdefault(rel, {})[_carried_key(m)] = mem
        db = SMo.clean_level((own.get(rel) or {}).get(_carried_key(m)))
        if db:
            levels.setdefault(rel, {})[_carried_key(m)] = int(db)
        sigs[rel] = _sig(project, rel)
    if not slots and not attract:
        raise ShareError("None of this project's music mode files is on this PC any more, so "
                         "there is nothing to save.")
    head = {"kind": MUSIC_KIND, "version": 1, "from": _about(project), "names": list(modes.names),
            "slots": slots, "levels": levels, "sigs": sigs}
    rnd = sorted(rel for rel in modes.random if rel in slots)
    if rnd:
        head["random"] = rnd                            # PAD-638: files in turn at random
    mrnd = {rel: sorted(str(m) for m in ms) for rel, ms in sorted(modes.mode_random.items())
            if rel in slots and ms}
    if mrnd:
        head["mode_random"] = mrnd                      # PAD-638: a music mode's own, at random
    if attract:
        head["attract"] = attract
        if modes.attract_gap:
            head["attract_gap"] = int(modes.attract_gap)
    every = {f for _r, _m, f in modes.files()} | set(modes.attract)
    _write_zip(path, head, [(mem, f) for f, mem in ((f, _member(members, f)) for f in every) if mem])
    out = {"slots": len(slots), "files": len(members), "gone": gone}
    if attract:
        out["attract"] = len(attract)
    return out


def save_random_clips(project, path):
    """Every slot's random clips in one file at *path*. Returns ``{"slots", "files", "gone"}``.
    Raises :class:`ShareError` when there is nothing to save."""
    variants = CV.load(project)
    if not variants:
        raise ShareError("This project has no random clips to save: no clip plays one of "
                         "several yet.")
    members, _g = _members(f for files in variants.values() for f in files)
    cards = CV.manifest(project)
    slots, sigs, where, gone = {}, {}, {}, []
    for rel, files in sorted(variants.items()):
        keep = []
        for f in files:
            mem = _member(members, f)
            if mem:
                keep.append(mem)
            else:
                gone.append((rel, f))
        if keep:
            slots[rel] = keep
            sigs[rel] = _sig(project, rel)
            if cards.get(rel):
                where[rel] = cards[rel]
    if not slots:
        raise ShareError("None of this project's random clips is on this PC any more, so there "
                         "is nothing to save.")
    head = {"kind": CLIPS_KIND, "version": 1, "from": _about(project), "slots": slots,
            "sigs": sigs, "cards": where}
    used = {m for v in slots.values() for m in v}
    files = []
    for f in {f for v in variants.values() for f in v}:
        mem = _member(members, f)
        if mem in used:
            files.append((mem, f))
            used.discard(mem)
    _write_zip(path, head, files)
    return {"slots": len(slots), "files": len(files), "gone": gone}


# ---- reading a file -----------------------------------------------------------------------------
def _read_head(z, kind, path):
    try:
        head = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError):
        head = None
    if not isinstance(head, dict) or head.get("kind") != kind:
        other = {MUSIC_KIND: "music modes", CLIPS_KIND: "random clips"}
        got = other.get(head.get("kind")) if isinstance(head, dict) else None
        raise ShareError("%s is not a file of %s%s." % (
            os.path.basename(path), other[kind],
            " (it is a file of %s; load it on the %s tab)" % (
                got, "Audio" if got == "music modes" else "Video") if got else ""))
    return head


def _member_ok(member):
    parts = str(member or "").split("/")
    return (len(parts) == 3 and parts[0] == FILES and ":" not in member
            and all(p not in ("", ".", "..") for p in parts))


def _same_title(project, head):
    here = _about(project).get("title")
    return bool(here) and here == (head.get("from") or {}).get("title")


def _unpack(z, member, folder, cache):
    """*member* of zip *z* as a file in *folder* (:func:`_put`), streamed: a clip runs to
    hundreds of MB."""
    if member not in cache:
        os.makedirs(folder, exist_ok=True)
        part = os.path.join(folder, ".loading.part")
        with z.open(member) as src, open(part, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        try:
            cache[member] = _put(folder, _safe_name(member, "file"), src=part)
        finally:
            os.remove(part)
    return cache[member]


def load_music_modes(project, path):
    """Read a file of music modes for *project*: its files copied into :data:`MUSIC_DIR`.
    Returns ``{"record", "loaded", "files", "found", "left", "about"}``: *record* the sidecar
    record (``{"names", "slots", "levels"}``, local paths), *found* ``[(file's rel, rel here,
    how)]`` for slots found other than by path, *left* ``[(rel, why)]``. Raises
    :class:`ShareError`."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ShareError("%s could not be read (%s)." % (os.path.basename(path), e)) from None
    with z:
        head = _read_head(z, MUSIC_KIND, path)
        slots_in = head.get("slots") if isinstance(head.get("slots"), dict) else {}
        sigs = head.get("sigs") if isinstance(head.get("sigs"), dict) else {}
        levels_in = head.get("levels")
        here = _Slots(project, "audio")
        same = _same_title(project, head)
        names = set(z.namelist())
        slots, levels, found, left, cache = {}, {}, [], [], {}
        rnd_in = head.get("random") if isinstance(head.get("random"), list) else []
        rnd = []
        mrnd_in = head.get("mode_random") if isinstance(head.get("mode_random"), dict) else {}
        mrnd = {}
        folder = os.path.join(project, MUSIC_DIR)
        for rel in sorted(slots_in):
            by_mode = slots_in[rel]
            if not isinstance(rel, str) or not isinstance(by_mode, dict):
                continue
            to, how = here.match(rel, sigs.get(rel), same_title=same)
            if to is None:
                left.append((rel, how))
                continue
            if SMo.slot_idx(to) is None:
                left.append((rel, SMo.NOT_SOUND))
                continue
            keep = {}
            for m, member in sorted(by_mode.items()):
                if not _key_ok(m) or not _member_ok(member) or member not in names:
                    continue
                keep[str(m)] = _unpack(z, member, folder, cache)
                db = SMo.clean_level(((levels_in or {}).get(rel) or {}).get(str(m)))
                if db:
                    levels.setdefault(to, {})[str(m)] = db
            if not keep:
                left.append((rel, "the file holds none of its sounds"))
                continue
            if to in slots:
                left.append((rel, "its sound is the same as %s's here, which the file also has"
                             % os.path.basename(to)))
                continue
            slots[to] = keep
            if rel in rnd_in:
                rnd.append(to)
            if isinstance(mrnd_in.get(rel), list) and mrnd_in[rel]:
                mrnd[to] = [str(m) for m in mrnd_in[rel]]
            if how:
                found.append((rel, to, how))
        # PAD-641: the flipper buttons' sounds in attract, which belong to no sound of the card
        attract = [_unpack(z, m, folder, cache) for m in (head.get("attract") or [])
                   if isinstance(head.get("attract"), list) and _member_ok(m) and m in names
                   ][:SMo.ATTRACT_MAX]
    names_in = head.get("names") if isinstance(head.get("names"), list) else []
    record = {"names": [str(n) if isinstance(n, str) else "" for n in names_in][:SMo.MAX_MODES],
              "slots": slots, "levels": levels}
    if rnd:
        record["random"] = sorted(rnd)
    if mrnd:
        record["mode_random"] = mrnd
    if attract:
        record["attract"] = attract
        if SMo.clean_gap(head.get("attract_gap")):
            record["attract_gap"] = SMo.clean_gap(head.get("attract_gap"))
    return {"record": record, "loaded": len(slots), "files": len(cache), "found": found,
            "left": left, "about": head.get("from") or {}}


def load_random_clips(project, path):
    """Read a file of random clips for *project*: its clips copied into :data:`CLIPS_DIR`.
    Returns ``{"variants", "loaded", "files", "found", "left", "about"}`` (*variants*
    ``{rel here: [clip, ...]}``). Raises :class:`ShareError`."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ShareError("%s could not be read (%s)." % (os.path.basename(path), e)) from None
    with z:
        head = _read_head(z, CLIPS_KIND, path)
        slots_in = head.get("slots") if isinstance(head.get("slots"), dict) else {}
        sigs = head.get("sigs") if isinstance(head.get("sigs"), dict) else {}
        cards = head.get("cards") if isinstance(head.get("cards"), dict) else {}
        here = _Slots(project, "video", video=True)
        same = _same_title(project, head)
        names = set(z.namelist())
        out, found, left, cache = {}, [], [], {}
        folder = os.path.join(project, CLIPS_DIR)
        for rel in sorted(slots_in):
            members = slots_in[rel]
            if not isinstance(rel, str) or not isinstance(members, list):
                continue
            to, how = here.match(rel, sigs.get(rel), cards.get(rel) or "", same_title=same)
            if to is None:
                left.append((rel, how))
                continue
            keep = [_unpack(z, m, folder, cache) for m in members
                    if _member_ok(m) and m in names][:CV.MAX_EXTRA]
            if not keep:
                left.append((rel, "the file holds none of its clips"))
                continue
            if to in out:
                left.append((rel, "its clip is the same as %s's here, which the file also has"
                             % os.path.basename(to)))
                continue
            out[to] = keep
            if how:
                found.append((rel, to, how))
    return {"variants": out, "loaded": len(out), "files": len(cache), "found": found,
            "left": left, "about": head.get("from") or {}}


# ---- into the project ---------------------------------------------------------------------------
def replaced_music(project, record):
    """``[(rel, mode)]`` the project already gives a file that *record* would replace."""
    have = SMo.load(project).slots
    return [(rel, int(m)) for rel, by in sorted(record.get("slots", {}).items())
            for m in sorted((m for m in by if str(m).isdigit()), key=int)
            if int(m) in (have.get(rel) or {})]


def put_music(project, record, keep_own=False):
    """Merge *record* into the project's music modes. A slot's file for a mode the record names
    replaces this project's (with its loudness), unless *keep_own*: then only slots and modes
    the project gives no file come in. The project's own mode names win where it has them.
    Returns how many slots got files."""
    from ...core import staged_changes
    from ...core.staged_changes import _mode_turn_k
    rec = dict(record)
    if keep_own:
        now = SMo.load(project)
        have = now.slots
        # PAD-565: a slot's files in turn come in only where it has none
        rec["slots"] = {rel: {m: f for m, f in by.items()
                              if (int(m) not in (have.get(rel) or {}) if str(m).isdigit()
                                  else not ((now.mode_turns.get(rel) or {}).get(_mode_turn_k(m)[0]))
                                  if _mode_turn_k(m) else not now.turns.get(rel))}
                        for rel, by in record.get("slots", {}).items()}
        rec["slots"] = {rel: by for rel, by in rec["slots"].items() if by}
        if now.attract:                     # PAD-641: its own flipper sounds in attract stay
            rec.pop("attract", None)
            rec.pop("attract_gap", None)
    data = staged_changes.load(project)
    n = staged_changes.merge_sound_modes(data, rec)
    if n:
        staged_changes.save(project, data)
    return n


def put_clips(project, variants, keep_own=False):
    """Give each slot of *variants* those random clips (in place of its own, or with *keep_own*
    only a slot that has none). Returns how many slots got them."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    now = CV.clean(data.get(CV.STAGED_KEY))
    n = 0
    for rel, files in sorted(variants.items()):
        if keep_own and now.get(rel):
            continue
        now[rel] = list(files)[:CV.MAX_EXTRA]
        n += 1
    if n:
        data[CV.STAGED_KEY] = now
        staged_changes.save(project, data)
    return n


# ---- back out of a card -------------------------------------------------------------------------
def _card_idx(project):
    """``{record idx: slot rel}`` of the project's sounds (the first file of each record)."""
    out = {}
    for rel in _rels(project, "audio"):
        i = SMo.slot_idx(rel)
        if i is not None and rel.lower().endswith(".wav"):
            out.setdefault(i, rel)
    return out


#: PAD-608: the folder (in :data:`MUSIC_DIR`) an extract decodes the music modes' files kept in
#: the app's own sound banks into (``engine._PAD_BANK_FILES``)
FROM_CARD_DIR = ".from_card"


def _card_host(project, idx, f):
    """The project rel of the record holding record line *f*'s file: a sound of the extract, or
    (PAD-608: ``bank`` set) the file the extract decoded out of that sound bank; None when the
    extract has neither."""
    if f.get("bank") is None:
        return idx.get(f["host"])
    rel = "%s/%s/music_cat%02d_%04d.wav" % (MUSIC_DIR, FROM_CARD_DIR, int(f["bank"]), int(f["host"]))
    return rel if os.path.isfile(os.path.join(project, *rel.split("/"))) else None


def _card_missing(f, slot):
    """Why record line *f*'s file is not back (:func:`_card_host` found nothing)."""
    if slot is None:
        return "this extract has no sound idx %d" % f["slot"]
    if f.get("bank") is not None:
        return "this extract could not decode record %d of sound bank image-sc%02d.bin" % (
            int(f["host"]), int(f["bank"]))
    return "this extract has no sound idx %d" % f["host"]


def music_from_card(project, cfg_text):
    """The music modes a card's ``sounds.cfg`` (*cfg_text*) records, out of *project*, an extract
    of that card: each mode's file copied from the record holding it into :data:`MUSIC_DIR`.
    Returns ``(record, left)`` (*record* None when the card carries no record; *left* ``[(slot
    rel, mode, why)]``)."""
    rec = SMo.read_card_record(cfg_text)
    if rec is None:
        return None, []
    idx = _card_idx(project)
    folder = os.path.join(project, MUSIC_DIR)
    slots, levels, left, copied = {}, {}, [], {}
    for f in rec["files"]:
        slot, host = idx.get(f["slot"]), _card_host(project, idx, f)
        if slot is None or host is None:
            left.append((f["rel"], f["mode"], _card_missing(f, slot)))
            continue
        if host not in copied:
            stem = os.path.splitext(_safe_name(f["name"], ""))[0] or "%s - mode %d" % (
                os.path.splitext(os.path.basename(slot))[0], f["mode"])
            copied[host] = _put(folder, stem + ".wav", src=os.path.join(project, *host.split("/")))
        slots.setdefault(slot, {})[str(f["mode"])] = copied[host]
        if f["db"]:
            levels.setdefault(slot, {})[str(f["mode"])] = int(f["db"])
    # PAD-565: a slot's files in turn, each from the record holding it
    for f in rec.get("turns") or ():
        slot, host = idx.get(f["slot"]), _card_host(project, idx, f)
        if slot is None or host is None:
            left.append((f["rel"], SMo.turn_mode(f["turn"]), _card_missing(f, slot)))
            continue
        if host not in copied:
            stem = os.path.splitext(_safe_name(f["name"], ""))[0] or "%s - in turn %d" % (
                os.path.splitext(os.path.basename(slot))[0], f["turn"])
            copied[host] = _put(folder, stem + ".wav", src=os.path.join(project, *host.split("/")))
        slots.setdefault(slot, {})[_carried_key(SMo.turn_mode(f["turn"]))] = copied[host]
        if f["db"]:                                   # PAD-638: its own loudness
            levels.setdefault(slot, {})[_carried_key(SMo.turn_mode(f["turn"]))] = int(f["db"])
    # PAD-641: the flipper buttons' sounds in attract, in their order
    attract = []
    for f in rec.get("attract") or ():
        slot, host = idx.get(f["slot"]), _card_host(project, idx, f)
        if host is None:
            left.append((f["rel"], SMo.attract_mode(f["k"]), _card_missing(f, slot or f["rel"])))
            continue
        if host not in copied:
            stem = os.path.splitext(_safe_name(f["name"], ""))[0] or "attract flipper sound %d" % f["k"]
            copied[host] = _put(folder, stem + ".wav", src=os.path.join(project, *host.split("/")))
        attract.append(copied[host])
    # PAD-638: a music mode's own files in turn, each from the record holding it
    for f in rec.get("mode_turns") or ():
        slot, host = idx.get(f["slot"]), _card_host(project, idx, f)
        mt = SMo.mode_turn(f["mode"], f["turn"])
        if slot is None or host is None:
            left.append((f["rel"], mt, _card_missing(f, slot)))
            continue
        if host not in copied:
            stem = os.path.splitext(_safe_name(f["name"], ""))[0] or "%s - mode %d in turn %d" % (
                os.path.splitext(os.path.basename(slot))[0], f["mode"], f["turn"])
            copied[host] = _put(folder, stem + ".wav", src=os.path.join(project, *host.split("/")))
        slots.setdefault(slot, {})[_carried_key(mt)] = copied[host]
        if f["db"]:
            levels.setdefault(slot, {})[_carried_key(mt)] = int(f["db"])
    out = {"names": rec["names"], "slots": slots, "levels": levels}
    mrnd = {}
    for f in rec.get("mode_random") or ():
        rel = idx.get(f["slot"])
        if rel in slots and any(k.startswith("m%dt" % f["mode"]) for k in slots[rel]):
            mrnd.setdefault(rel, set()).add(str(f["mode"]))
    if mrnd:
        out["mode_random"] = {rel: sorted(ms) for rel, ms in mrnd.items()}
    # PAD-638: the slots whose files in turn play at random
    rnd = sorted({idx[f["slot"]] for f in rec.get("random") or () if idx.get(f["slot"]) in slots})
    if rnd:
        out["random"] = rnd
    if attract:
        out["attract"] = attract
        if rec.get("attract_gap"):
            out["attract_gap"] = rec["attract_gap"]
    return out, left


def _built_project_modes(card):
    """The music modes of the project the build record beside *card* names, while that folder
    and its files are still on this PC (a card written before cards carried them); else None."""
    from ...core import extract_source
    try:
        src = extract_source._build_project(str(card)) or ""
    except Exception:                                   # noqa: BLE001
        return None
    if not src or not os.path.isdir(src):
        return None
    modes = SMo.load(src)
    files = {}
    for rel, mode, f in modes.files():
        if os.path.isfile(f):
            files.setdefault(rel, {})[_carried_key(mode)] = f
    if not files and not any(os.path.isfile(f) for f in modes.attract):
        return None
    rec = {"names": list(modes.names), "slots": files}
    if modes.random & set(files):
        rec["random"] = sorted(modes.random & set(files))
    attract = [f for f in modes.attract if os.path.isfile(f)]      # PAD-641
    if attract:
        rec["attract"] = attract
        if modes.attract_gap:
            rec["attract_gap"] = int(modes.attract_gap)
    if modes.levels is not None:
        rec["levels"] = {rel: {str(m): db for m, db in v.items() if str(m) in files.get(rel, {})}
                         for rel, v in modes.levels.items()}
    for rel, v in modes.turn_levels.items():          # PAD-638: files in turn's own loudness
        for k, db in v.items():
            key = _carried_key(SMo.turn_mode(k))
            if db and key in files.get(rel, {}):
                rec.setdefault("levels", {}).setdefault(rel, {})[key] = int(db)
    for rel, by in modes.mode_turn_levels.items():    # PAD-638: a music mode's own, theirs
        for m, v in by.items():
            for k, db in v.items():
                key = _carried_key(SMo.mode_turn(m, k))
                if db and key in files.get(rel, {}):
                    rec.setdefault("levels", {}).setdefault(rel, {})[key] = int(db)
    mrnd = {rel: sorted(str(m) for m in ms) for rel, ms in modes.mode_random.items()
            if rel in files and ms}
    if mrnd:
        rec["mode_random"] = mrnd
    return rec


def readback(card, project, log=None, padmode=None):
    """After an extract of *card* into *project*: the music modes and random clips the card was
    written with, back in the project, beside any it already gives (its own win). *padmode* is
    the card's ``/usr/local/padmode`` files when the caller read them (:func:`.mode_from_card.
    read_padmode`); else they are read here. Returns ``{"music": slots, "clips": slots}``."""
    from ...core import mod_transfer
    log = log or (lambda *a, **k: None)
    done = {"music": 0, "clips": 0}
    if padmode is None:
        from . import mode_from_card as MFC
        try:
            padmode = MFC.read_padmode(card)
        except Exception:                               # noqa: BLE001 - not a card we can read
            padmode = {}
    cfg = padmode.get(SMo.CFG_NAME)
    if cfg:
        try:
            record, left = music_from_card(project, cfg.decode("utf-8", "replace"))
        finally:
            # PAD-608: the files the extract decoded out of the sound banks are copied
            shutil.rmtree(os.path.join(project, MUSIC_DIR, FROM_CARD_DIR), ignore_errors=True)
        where = " (their files are in the \"%s\" folder)" % MUSIC_DIR
        if record is None:
            record, left = _built_project_modes(card), []
            where = ", from the project it was built from"
            if record is None:
                log("Music modes: this card has music modes, but it was written by an earlier "
                    "version of this app, which did not say on the card which files they are, "
                    "so they cannot be brought back from it. A card written now says it.",
                    "warning")
        if record is not None:
            for rel, m, why in left:
                log("%s: %s is not back: %s." % (
                    SMo.who(m), SMo.what(rel, m) if SMo.is_turn(m) else "%s's file for mode %d"
                    % (os.path.basename(rel), m), why), "warning")
            had_attract = bool(SMo.load(project).attract)
            done["music"] = put_music(project, record, keep_own=True)
            if done["music"] and record.get("attract") and not had_attract:
                log("Attract flipper sounds: this card's flipper buttons play %d sound(s) in attract "
                    "mode; they are back in the Audio tab%s." % (len(record["attract"]), where),
                    "success")
            if done["music"] and record["slots"]:
                names = SMo.clean(record)
                log("Music modes: %d sound(s) of this card have files for other music modes (%s); "
                    "they are back in the Audio tab%s." % (
                        len(record["slots"]), ", ".join(
                            "%d %s" % (m, names.name(m)) for m in range(1, names.count + 1)),
                        where), "success")
    variants = {rel: files[:CV.MAX_EXTRA]
                for rel, files in mod_transfer.baked_variants(project).items()}
    if variants:
        done["clips"] = put_clips(project, variants, keep_own=True)
        if done["clips"]:
            log("Random clips: %d clip(s) of this card play one of several at random (%s); "
                "they are back in the Video tab." % (
                    len(variants), ", ".join(os.path.basename(r) for r in sorted(variants))),
                "success")
    return done
