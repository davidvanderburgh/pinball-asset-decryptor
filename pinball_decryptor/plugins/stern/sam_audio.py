"""Stern S.A.M. (2006-2014) audio: Extract every sound of a code update to
WAVs, and Write edited ones -- and the edited pictures (PAD-583,
:mod:`.sam_images`) -- back into a copy of it.

The format lives in :mod:`..pinmame_classic.sam_sound`; this is the
Extract / Write / Revert contract the Spike 1 engine has, over it:

* Extract decodes each sample to ``audio/idxNNNN.wav`` (``NNNN`` = the
  sample's place in the file, from 0) at its own rate: 24 kHz for
  effects and music, 12 or 8 kHz for most speech.  Mono, 16-bit.
* Write takes the WAVs that differ from the extract's checksum baseline,
  fits each to its slot (same rate, same length: longer is trimmed,
  shorter padded), loudness-matches it to the original the way Spike 1
  does, re-encodes it into the slot and fixes the image's checksums.  The
  output is the same size as the input, so it updates a machine by USB
  like Stern's own file.
* Songs stored in pieces (PAD-587: AC/DC, Metallica - a few hundred
  bar-length samples one script plays back to back) are also stitched
  whole into ``music/songNN - soundNNNN.wav``.  An edited song is split
  back across its pieces on Write, loudness-matched as one; a piece
  edited on its own in ``audio/`` wins over the song for that piece.

The input is the ``.bin`` (The Walking Dead 1.05: ``.ebi``) as Stern
ships it, or any zip holding one (``pinmame_classic.sam.identify``).
"""

import importlib
import os
import re
import wave
import zipfile

from ...core import checksums, staged_changes
from ...core.longpath import ext as _lp
from ..pinmame_classic import sam as sam_id
from ..pinmame_classic import sam_sound
from . import spike1 as _s1


class SamAudioError(Exception):
    pass


class SamAudioCancelled(SamAudioError):
    pass


#: the game file's other parts Write takes edits for, after the sounds:
#: modules here with ``patch(image, data, assets_dir, log, progress,
#: cancel) -> (changes, written, skipped)``
_ART_PARTS = ("sam_images", "sam_anim_assets")
#: project top folder -> the module whose ``revert(data, assets_dir, rels,
#: log)`` restores its files
_REVERT_PARTS = {"images": "sam_images", "animations": "sam_anim_assets"}


def _part(name):
    return importlib.import_module("." + name, __package__)


_IDX_RE = re.compile(r"idx(\d{4,5})(?![0-9])", re.IGNORECASE)
#: the whole songs' folder, and the sound number in a song's file name
#: (Music ID appends " - Artist - Title" and keeps it)
SONG_DIR = "music"
_SONG_RE = re.compile(r"^song\d+ - sound(\d{4,5})(?![0-9])", re.IGNORECASE)


def wav_name(idx, sample, duration_names=False):
    stem = "idx%04d" % idx
    if duration_names:
        total_ms = int(round(sample.seconds * 1000.0))
        m, rem = divmod(total_ms, 60000)
        s, ms = divmod(rem, 1000)
        stem = "%02dm%02ds%03d - %s" % (m, s, ms, stem)
    return stem + ".wav"


def parse_wav_stem(stem):
    """The sample index in an extracted-WAV stem (renames by Auto-
    transcribe / Music ID keep the ``idxNNNN`` token), or None."""
    m = _IDX_RE.search(stem)
    return int(m.group(1)) if m else None


def song_name(n, song):
    return "song%02d - sound%04d.wav" % (n, song.sound)


def parse_song_stem(stem):
    """The sound number in a whole-song WAV's stem, or None."""
    m = _SONG_RE.match(stem)
    return int(m.group(1)) if m else None


def _song_pcm(data, bank, song):
    import numpy as np
    return np.concatenate([np.asarray(sam_sound.decode(data, bank.samples[k]),
                                      dtype=np.int16) for k in song.pieces])


def read_image(path):
    """The game file's bytes: a bare ``.bin`` / ``.ebi``, or the one in a
    zip :func:`sam.identify` picks."""
    match = sam_id.identify(path)
    if match is None:
        raise SamAudioError("%s is not a Stern SAM game file"
                            % os.path.basename(path))
    try:
        if match.member:
            with zipfile.ZipFile(_lp(path)) as zf:
                return zf.read(match.member), match
        with open(_lp(path), "rb") as f:
            return f.read(), match
    except (OSError, zipfile.BadZipFile) as e:
        raise SamAudioError("reading %s failed: %s"
                            % (os.path.basename(path), e))


def _bank(data):
    try:
        return sam_sound.read_bank(data)
    except sam_sound.SamSoundError as e:
        raise SamAudioError("this file's sound table can't be read (%s)" % e)


def _write_pcm(path, pcm, rate):
    tmp = path + ".part"
    with wave.open(_lp(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    os.replace(_lp(tmp), _lp(path))


def _write_wav(path, data, sample):
    _write_pcm(path, sam_sound.decode(data, sample), sample.rate)


def _write_songs(data, bank, output_dir, log, check):
    """Stitch every song stored in pieces into ``music/``; returns them."""
    found = sam_sound.songs(data, bank)
    if not found:
        return []
    song_dir = os.path.join(output_dir, SONG_DIR)
    os.makedirs(song_dir, exist_ok=True)
    for n, song in enumerate(found, 1):
        if check():
            raise SamAudioCancelled("cancelled")
        _write_pcm(os.path.join(song_dir, song_name(n, song)),
                   _song_pcm(data, bank, song),
                   bank.samples[song.pieces[0]].rate)
    log("Music: %d song(s) stored as short pieces, %.1f minutes - each "
        "stitched whole into %s/ (an edited song is split back into its "
        "pieces on Write)" % (len(found),
                              sum(s.seconds(bank) for s in found) / 60.0,
                              SONG_DIR))
    return found


def extract_all(path, output_dir, log=None, progress=None, cancel=None,
                duration_names=False):
    """Decode every sample to ``output_dir/audio``, and every song stored
    in pieces whole to ``output_dir/music``.  Returns ``{"samples",
    "sounds", "seconds", "engine", "songs"}``."""
    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    data, _match = read_image(path)
    bank = _bank(data)
    log("Sound table: %d entries, %d samples (%.1f minutes), script "
        "engine %s" % (bank.entries, len(bank.samples), bank.seconds / 60.0,
                       bank.engine))
    audio_dir = os.path.join(output_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    n = len(bank.samples)
    for i, s in enumerate(bank.samples):
        if check():
            raise SamAudioCancelled("cancelled")
        _write_wav(os.path.join(audio_dir, wav_name(i, s, duration_names)),
                   data, s)
        if progress and (i % 16 == 0 or i == n - 1):
            progress(i + 1, n, "Decoding audio (%d/%d)" % (i + 1, n))
    log("Decoded %d WAVs" % n)
    found = _write_songs(data, bank, output_dir, log, check)
    return {"samples": n, "sounds": bank.entries, "seconds": bank.seconds,
            "engine": bank.engine, "songs": len(found)}


def _select_changed_wavs(assets_dir, log):
    """``{sample index: path}`` for every audio WAV changed vs baseline."""
    baseline = checksums.read_checksums(assets_dir)
    out = {}
    audio_dir = os.path.join(assets_dir, "audio")
    if not os.path.isdir(audio_dir):
        return out
    for fn in sorted(os.listdir(audio_dir)):
        if not fn.lower().endswith(".wav") or ".stage." in fn:
            continue
        idx = parse_wav_stem(os.path.splitext(fn)[0])
        if idx is None:
            continue
        p = os.path.join(audio_dir, fn)
        base = baseline.get("audio/" + fn)
        if base is None or checksums.md5_file(p) != base:
            if idx in out:
                log("  note: %s and %s are the same sound; using %s"
                    % (os.path.basename(out[idx]), fn,
                       os.path.basename(out[idx])))
            else:
                out[idx] = p
    return out


def _select_changed_songs(assets_dir, log):
    """``{sound number: path}`` for every whole-song WAV changed vs
    baseline."""
    baseline = checksums.read_checksums(assets_dir)
    out = {}
    song_dir = os.path.join(assets_dir, SONG_DIR)
    if not os.path.isdir(song_dir):
        return out
    for fn in sorted(os.listdir(song_dir)):
        if not fn.lower().endswith(".wav") or ".stage." in fn:
            continue
        sound = parse_song_stem(os.path.splitext(fn)[0])
        if sound is None:
            continue
        p = os.path.join(song_dir, fn)
        base = baseline.get(SONG_DIR + "/" + fn)
        if base is None or checksums.md5_file(p) != base:
            if sound in out:
                log("  note: %s and %s are the same song; using %s"
                    % (os.path.basename(out[sound]), fn,
                       os.path.basename(out[sound])))
            else:
                out[sound] = p
    return out


def _level_gains(assets_dir):
    """``({sample index: dB}, {song sound number: dB})`` from the staged
    per-file level offsets."""
    pieces, songs = {}, {}
    for rel, db in (staged_changes.load(assets_dir).get("audio_levels")
                    or {}).items():
        stem = os.path.splitext(os.path.basename(rel))[0]
        top = rel.replace("\\", "/").split("/", 1)[0]
        key = parse_song_stem(stem) if top == SONG_DIR \
            else parse_wav_stem(stem)
        if key is None:
            continue
        try:
            (songs if top == SONG_DIR else pieces)[key] = float(db)
        except (TypeError, ValueError):
            pass
    return pieces, songs


def _fit_and_level(rep, orig, frames, db, match_on, name, log):
    """*rep* cut to *frames* (with an edge fade), level-matched to *orig*,
    then padded with silence to *frames*.  The match measures only what
    plays: padding measured with it would read a short replacement as
    quiet and boost it (half the length = +3 dB too loud)."""
    if len(rep) > frames:
        rep = _s1._fit_frames(rep, frames)
    if match_on and not orig.any():
        log("  note: %s replaces a silent slot - the original gives no level "
            "reference, keeping the replacement's own level" % name)
    db = max(min(db, _s1._MATCH_GAIN_DB_MAX), -_s1._MATCH_GAIN_DB_MAX)
    rep = _s1._match_level(rep, orig, db, match=match_on)
    return _s1._fit_frames(rep, frames)


def _split_songs(data, bank, edits, pieces_edited, gains, build_db, match_on,
                 log, check):
    """Cut each edited whole song back into its pieces.  Returns
    ``({sample index: (pcm float [n, 1], song file name)}, n_songs,
    skipped)``: the song is fit to its own length and level-matched to the
    original song as ONE clip, so its pieces keep their balance."""
    import numpy as np

    by_sound = {s.sound: s for s in sam_sound.songs(data, bank)}
    out, skipped, n_songs = {}, [], 0
    for sound, wav_path in sorted(edits.items()):
        if check():
            raise SamAudioCancelled("cancelled")
        name = os.path.basename(wav_path)
        song = by_sound.get(sound)
        if song is None:
            skipped.append(name)
            log("  ! %s: no song in pieces with that sound number in this "
                "file - skipped" % name)
            continue
        rate = bank.samples[song.pieces[0]].rate
        frames = song.frames(bank)
        try:
            rep, rep_rate = _s1._load_wav(wav_path)
            rep = _s1._mix_channels(_s1._resample(rep, rep_rate, rate), 1)
            if len(rep) != frames:
                log("  note: %s is %.1f s, the song's slots hold %.1f s - "
                    "%s" % (name, len(rep) / rate, frames / rate,
                            "cut to fit" if len(rep) > frames
                            else "the rest is silence"))
            orig = np.asarray(_song_pcm(data, bank, song),
                              dtype=np.float32).reshape(-1, 1)
            rep = _fit_and_level(rep, orig, frames,
                                 build_db + gains.get(sound, 0.0),
                                 match_on, name, log)
        except Exception as e:                          # noqa: BLE001
            skipped.append(name)
            log("  ! %s could not be encoded (%s) - skipped, the song keeps "
                "its original pieces" % (name, e), "warning")
            continue
        at, own = 0, 0
        for k in song.pieces:
            cnt = bank.samples[k].count
            part = rep[at:at + cnt]
            at += cnt
            if k in pieces_edited:
                own += 1
                continue
            # a piece the song plays twice keeps its first place's audio
            out.setdefault(k, (part, name))
        if own:
            log("  note: %d piece(s) of %s were edited on their own in "
                "audio/ - those keep that edit" % (own, name))
        n_songs += 1
        log("  %s -> %d piece(s), idx%04d-idx%04d (%.1f s)"
            % (name, len(song.pieces), min(song.pieces), max(song.pieces),
               frames / rate))
    return out, n_songs, skipped


def write_image(original_path, assets_dir, output_path, log=None,
                progress=None, cancel=None, phase=None):
    """Write *original_path* with the changed WAVs in to *output_path*.
    Returns ``{"audio": n_patched, "skipped": [names]}``.  The image is
    built in memory and written in one go, so an error or cancel leaves no
    partial output."""
    import numpy as np

    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    data, _match = read_image(original_path)
    bank = _bank(data)
    changed = _select_changed_wavs(assets_dir, log)
    song_edits = _select_changed_songs(assets_dir, log)
    gains, song_gains = _level_gains(assets_dir)
    log("Changed sounds: %d" % len(changed))
    if song_edits:
        log("Changed whole songs: %d" % len(song_edits))
    build_db = _s1._build_gain_db()
    match_on = _s1._match_loudness_enabled()
    if build_db:
        log("Build-wide loudness offset: %+.1f dB" % build_db)
    if not match_on:
        log("Loudness match: off (Advanced audio options)")
    if phase:
        phase(2)

    image = bytearray(data)
    trailer = sam_sound.has_trailer(data)
    changes = []
    skipped = []
    from_songs, n_songs = {}, 0
    if song_edits:
        from_songs, n_songs, skipped = _split_songs(
            data, bank, song_edits, set(changed), song_gains, build_db,
            match_on, log, check)
    items = sorted(set(changed) | set(from_songs))
    for n, idx in enumerate(items):
        if check():
            raise SamAudioCancelled("cancelled")
        if idx in from_songs:
            rep, name = from_songs[idx]
            s = bank.samples[idx]
        else:
            wav_path = changed[idx]
            name = os.path.basename(wav_path)
            if idx >= len(bank.samples):
                skipped.append(name)
                log("  ! %s: no such sound in this file - skipped" % name)
                continue
            s = bank.samples[idx]
            try:
                rep, rep_rate = _s1._load_wav(wav_path)
                rep = _s1._mix_channels(_s1._resample(rep, rep_rate, s.rate),
                                        1)
                orig = np.asarray(sam_sound.decode(data, s),
                                  dtype=np.float32).reshape(-1, 1)
                rep = _fit_and_level(rep, orig, s.count,
                                     build_db + gains.get(idx, 0.0),
                                     match_on, name, log)
            except Exception as e:
                skipped.append(name)
                log("  ! %s could not be encoded (%s) - skipped, the slot "
                    "keeps its original sound" % (name, e), "warning")
                continue
        pcm = np.rint(rep[:, 0]).astype(np.int16).tolist()
        delta = sam_sound.replace(image, s, pcm)
        changes.append((s.data_offset, s.data_offset + s.data_size, delta))
        if idx not in from_songs:
            log("  idx%04d <- %s (%.2f s, %d Hz)" % (idx, name, s.seconds,
                                                     s.rate))
        if progress:
            progress(n + 1, len(items), "Encoding audio")

    # a song counts once, not as the hundreds of pieces it went into
    n_audio = len(changes) - sum(1 for k in items if k in from_songs) \
        + n_songs
    written = {}
    for name in _ART_PARTS:
        part = _part(name)
        try:
            more, n_written, more_skipped = part.patch(
                image, data, assets_dir, log=log, progress=progress,
                cancel=cancel)
        except Exception as e:                       # noqa: BLE001
            if check():
                raise SamAudioCancelled("cancelled")
            raise SamAudioError(str(e))
        changes += more
        skipped += more_skipped
        written[name] = n_written
    if not changes:
        log("  ! nothing changed vs the extract baseline - the build will "
            "be an unmodified copy of the original", "warning")

    if phase:
        phase(3)
    try:
        sam_sound.fix_checksums(image, changes, trailer)
    except sam_sound.SamSoundError as e:
        raise SamAudioError(str(e))
    if trailer:
        log("File checksum updated (the machine's USB update checks it)")
    if check():
        raise SamAudioCancelled("cancelled")
    tmp = output_path + ".part"
    try:
        with open(_lp(tmp), "wb") as f:
            f.write(image)
        os.replace(_lp(tmp), _lp(output_path))
    except BaseException:
        # only the half-written copy: an earlier build at output_path stays
        try:
            os.remove(_lp(tmp))
        except OSError:
            pass
        raise
    return {"audio": n_audio, "songs": n_songs,
            "images": written.get("sam_images", 0),
            "animations": written.get("sam_anim_assets", 0),
            "skipped": skipped}


def revert_assets(source_path, assets_dir, rels, log=None, progress=None,
                  cancel=None):
    """Re-decode the original WAVs for *rels* (``audio/idxNNNN.wav``, renamed
    forms too, and whole songs under ``music/``) -- and the original pictures (``images/...``) and animation
    frames (``animations/...``) -- from the source file.  Returns ``(reverted, failed)``."""
    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    data, _match = read_image(source_path)
    reverted, failed = [], []
    by_part = {}
    sounds = []
    for rel in rels:
        top = rel.replace("\\", "/").split("/", 1)[0]
        if top in _REVERT_PARTS:
            by_part.setdefault(_REVERT_PARTS[top], []).append(rel)
        else:
            sounds.append(rel)
    for name, part_rels in by_part.items():
        try:
            r, f = _part(name).revert(data, assets_dir, part_rels, log=log)
        except Exception as e:                       # noqa: BLE001
            log("  ! %s" % e)
            r, f = [], part_rels
        reverted += r
        failed += f
    if not sounds:
        return reverted, failed
    bank = _bank(data)
    by_sound = None
    for n, rel in enumerate(sounds):
        if check():
            break
        stem = os.path.splitext(os.path.basename(rel))[0]
        if rel.replace("\\", "/").split("/", 1)[0] == SONG_DIR:
            if by_sound is None:
                by_sound = {s.sound: s for s in sam_sound.songs(data, bank)}
            song = by_sound.get(parse_song_stem(stem))
            if song is None:
                failed.append(rel)
                log("  ! %s: no matching song in the source file" % rel)
                continue
            _write_pcm(os.path.join(assets_dir, rel.replace("/", os.sep)),
                       _song_pcm(data, bank, song),
                       bank.samples[song.pieces[0]].rate)
            reverted.append(rel)
            log("  restored %s" % rel)
            continue
        idx = parse_wav_stem(stem)
        if idx is None or idx >= len(bank.samples):
            failed.append(rel)
            log("  ! %s: no matching sound in the source file" % rel)
            continue
        _write_wav(os.path.join(assets_dir, rel.replace("/", os.sep)), data,
                   bank.samples[idx])
        reverted.append(rel)
        log("  restored %s" % rel)
        if progress:
            progress(n + 1, len(sounds), "Restoring originals")
    return reverted, failed
