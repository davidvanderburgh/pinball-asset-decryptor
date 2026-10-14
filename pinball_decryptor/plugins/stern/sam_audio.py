"""Stern S.A.M. (2006-2014) audio: Extract every sound of a code update to
WAVs, and Write edited ones back into a copy of it.

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


# The art written alongside the sounds: stern modules with
# ``patch(image, data, assets_dir, log, progress, cancel) -> (changes,
# written, skipped)`` and ``revert(data, assets_dir, rels, log) ->
# (reverted, failed)``, each owning a top folder of the project.
_ART_PARTS = ("sam_anim_assets",)
_REVERT_PARTS = {"animations": "sam_anim_assets"}
_ART_KEYS = {"sam_anim_assets": "animations"}


def _part(name):
    return importlib.import_module("." + name, __package__)


_IDX_RE = re.compile(r"idx(\d{4,5})(?![0-9])", re.IGNORECASE)


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


def _write_wav(path, data, sample):
    pcm = sam_sound.decode(data, sample)
    tmp = path + ".part"
    with wave.open(_lp(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample.rate)
        w.writeframes(pcm.tobytes())
    os.replace(_lp(tmp), _lp(path))


def extract_all(path, output_dir, log=None, progress=None, cancel=None,
                duration_names=False):
    """Decode every sample to ``output_dir/audio``.  Returns
    ``{"samples", "sounds", "seconds", "engine"}``."""
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
    return {"samples": n, "sounds": bank.entries, "seconds": bank.seconds,
            "engine": bank.engine}


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


def _slot_gains(assets_dir):
    out = {}
    for rel, db in (staged_changes.load(assets_dir).get("audio_levels")
                    or {}).items():
        idx = parse_wav_stem(os.path.splitext(os.path.basename(rel))[0])
        if idx is None:
            continue
        try:
            out[idx] = float(db)
        except (TypeError, ValueError):
            pass
    return out


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
    gains = _slot_gains(assets_dir)
    log("Changed sounds: %d" % len(changed))
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
    items = sorted(changed.items())
    for n, (idx, wav_path) in enumerate(items):
        if check():
            raise SamAudioCancelled("cancelled")
        name = os.path.basename(wav_path)
        if idx >= len(bank.samples):
            skipped.append(name)
            log("  ! %s: no such sound in this file - skipped" % name)
            continue
        s = bank.samples[idx]
        try:
            rep, rep_rate = _s1._load_wav(wav_path)
            rep = _s1._mix_channels(_s1._resample(rep, rep_rate, s.rate), 1)
            rep = _s1._fit_frames(rep, s.count)
            orig = np.asarray(sam_sound.decode(data, s),
                              dtype=np.float32).reshape(-1, 1)
            if match_on and not orig.any():
                log("  note: %s replaces a silent slot - the original "
                    "gives no level reference, keeping the replacement's "
                    "own level" % name)
            db = max(min(build_db + gains.get(idx, 0.0),
                         _s1._MATCH_GAIN_DB_MAX), -_s1._MATCH_GAIN_DB_MAX)
            rep = _s1._match_level(rep, orig, db, match=match_on)
        except Exception as e:
            skipped.append(name)
            log("  ! %s could not be encoded (%s) - skipped, the slot keeps "
                "its original sound" % (name, e), "warning")
            continue
        pcm = np.rint(rep[:, 0]).astype(np.int16).tolist()
        delta = sam_sound.replace(image, s, pcm)
        changes.append((s.data_offset, s.data_offset + s.data_size, delta))
        log("  idx%04d <- %s (%.2f s, %d Hz)" % (idx, name, s.seconds,
                                                 s.rate))
        if progress:
            progress(n + 1, len(items), "Encoding audio")

    counts = {"audio": len(changes)}
    for name in _ART_PARTS:
        try:
            part_changes, written, part_skipped = _part(name).patch(
                image, data, assets_dir, log=log, progress=progress,
                cancel=check)
        except Exception as e:
            if check():
                raise SamAudioCancelled("cancelled")
            raise SamAudioError(str(e))
        changes += part_changes
        skipped += part_skipped
        counts[_ART_KEYS[name]] = written
    if not any(counts.values()):
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
    counts["skipped"] = skipped
    return counts


def revert_assets(source_path, assets_dir, rels, log=None, progress=None,
                  cancel=None):
    """Re-decode the originals for *rels* from the source file: WAVs
    (``audio/idxNNNN.wav``, renamed forms too), and the art parts' files
    by their top folder.  Returns ``(reverted, failed)``."""
    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    data, _match = read_image(source_path)
    reverted, failed = [], []
    art = {}
    for rel in rels:
        top = rel.replace("\\", "/").split("/", 1)[0]
        if top in _REVERT_PARTS:
            art.setdefault(_REVERT_PARTS[top], []).append(rel)
    for name, part_rels in art.items():
        done, bad = _part(name).revert(data, assets_dir, part_rels, log=log)
        reverted += done
        failed += bad
    rels = [r for r in rels
            if r.replace("\\", "/").split("/", 1)[0] not in _REVERT_PARTS]
    if not rels:
        return reverted, failed
    bank = _bank(data)
    for n, rel in enumerate(rels):
        if check():
            break
        idx = parse_wav_stem(os.path.splitext(os.path.basename(rel))[0])
        if idx is None or idx >= len(bank.samples):
            failed.append(rel)
            log("  ! %s: no matching sound in the source file" % rel)
            continue
        _write_wav(os.path.join(assets_dir, rel.replace("/", os.sep)), data,
                   bank.samples[idx])
        reverted.append(rel)
        log("  restored %s" % rel)
        if progress:
            progress(n + 1, len(rels), "Restoring originals")
    return reverted, failed
