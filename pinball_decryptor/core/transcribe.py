"""Auto-transcribe extracted audio samples to a callouts.csv.

Asset extraction yields audio as many WAVs named only by index — when
you want to mod "the callout where the witch laughs" you'd otherwise
have to open WAVs blind because nothing maps index -> spoken text.

This module runs `faster-whisper`_ (tiny.en, int8 CPU) across every
WAV under an assets directory, with the built-in Silero VAD filter
enabled so non-speech samples (sound effects, music beds, crowd
ambience) skip Whisper entirely and just get logged as ``[no speech]``.

Output: ``callouts.csv`` at the root of the assets dir, with columns:

    relative_path, classification, text

where ``classification`` is ``speech`` for transcribed WAVs and
``non-speech`` for VAD-skipped ones.  Shared infrastructure — any
manufacturer plugin whose ``Capabilities.transcribe`` is True wires
this in via ``make_transcribe_pipeline``.

.. _faster-whisper: https://github.com/SYSTRAN/faster-whisper
"""

import csv
import os

from .pipeline_base import BasePipeline, PipelineError


WHISPER_IMPORT_HINT = (
    "Auto-transcribe needs `faster-whisper` (optional dependency).\n\n"
    "Install with:\n"
    "  pip install faster-whisper\n\n"
    "On first run it downloads the tiny.en model (~75 MB) to\n"
    "  %USERPROFILE%\\.cache\\huggingface\\hub\\\n"
    "Subsequent runs reuse the cached model offline."
)

CALLOUTS_CSV = "callouts.csv"

# Transcribe in parallel (one Whisper model per process) only once there are at
# least this many WAVs — below it the per-worker model load costs more than it
# saves, so the single-process loop wins.
_PARALLEL_MIN_WAVS = 16

# Non-speech WAVs at least this long are tagged ``music`` (renamed
# ``<stem> - music.<ext>``) so the music tracks are isolated from the SFX in
# the same pass — they're exactly the clips a fingerprint match can then title.
# Songs run minutes; SFX/ambience beds are short.  0 disables the tag.
DEFAULT_MUSIC_MIN_SECONDS = 20.0


class TranscribePipeline(BasePipeline):
    """Walk an extracted assets dir, transcribe speech-bearing WAVs.

    Phase 0: Locate WAVs + load model.
    Phase 1: Run Whisper+VAD on each WAV.
    Phase 2: Write callouts.csv.
    Phase 3: (optional) Rename speech WAVs to ``<stem> - <text>.<ext>`` and
             long non-speech WAVs to ``<stem> - music.<ext>``.

    The rename step keeps the original filename as a prefix so the
    extract -> write round trip still works: the Write pipeline's
    ``_diff_assets`` uses prefix-matching to map renamed files back
    to their original inner-ext4 path (see [[option_a_rename_aware_write]]).
    """

    def __init__(self, assets_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 model_size="tiny.en", rename_after=False,
                 music_min_seconds=DEFAULT_MUSIC_MIN_SECONDS):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.assets_dir = assets_dir
        self.model_size = model_size
        self.rename_after = rename_after
        self.music_min_seconds = float(music_min_seconds)

    def _run(self):
        self._set_phase(0)
        try:
            from faster_whisper import WhisperModel  # noqa: F401 (probe only)
        except ImportError:
            raise PipelineError("Transcribe", WHISPER_IMPORT_HINT)

        if not os.path.isdir(self.assets_dir):
            raise PipelineError("Transcribe",
                f"Assets folder not found: {self.assets_dir}")

        wavs = _find_wavs(self.assets_dir)
        if not wavs:
            raise PipelineError("Transcribe",
                f"No .wav files under {self.assets_dir}.\n"
                f"Run the Extract tab first.")
        self._log(f"  Found {len(wavs)} WAV file(s) to scan.", "info")
        self._check_cancel()

        # Whisper-on-CPU is the slow part — fan the per-file transcription out
        # across processes (one model per worker) when there's enough work to
        # amortise the per-worker model load.  Below the threshold, or if a
        # pool can't start, fall back to the single-process loop.  Both paths
        # produce the SAME rows (same VAD + music tag + ordering) so the
        # callouts.csv is identical.  Each loads the model under phase 0 ("Load
        # model"), then advances to phase 1 ("Transcribe") for the per-file loop.
        result = None
        if len(wavs) >= _PARALLEL_MIN_WAVS and (os.cpu_count() or 1) > 1:
            try:
                result = self._transcribe_parallel(wavs)
            except PipelineError:
                raise                       # cancel / fatal — don't retry
            except Exception as e:
                self._log(f"  Parallel transcribe unavailable ({e}); using a "
                          f"single process.", "info")
                result = None
        if result is None:
            result = self._transcribe_serial(wavs)
        rows, speech_count, non_speech_count, music_count = result

        # Optional Phase 3: rename speech files using their transcripts
        # so the file explorer view shows the spoken text inline.
        # Mutates ``rows`` in place so the CSV reflects the new names.
        renamed_count = 0
        skipped_renames = 0
        if self.rename_after:
            self._set_phase(2)
            self._log("Renaming speech + music files...", "info")
            new_rows = []
            for rel, kind, text in rows:
                self._check_cancel()
                # speech -> spoken text; music -> the literal tag "music".
                label = text if kind == "speech" else (
                    "music" if kind == "music" else "")
                if not label:
                    new_rows.append((rel, kind, text))
                    continue
                new_rel = _renamed_rel_path(rel, label)
                if new_rel == rel:
                    new_rows.append((rel, kind, text))
                    skipped_renames += 1
                    continue
                src_abs = os.path.join(self.assets_dir, rel)
                dst_abs = os.path.join(self.assets_dir, new_rel)
                if os.path.exists(dst_abs):
                    self._log(
                        f"  Skipping rename of {rel}: "
                        f"target already exists ({os.path.basename(new_rel)})",
                        "info")
                    new_rows.append((rel, kind, text))
                    skipped_renames += 1
                    continue
                try:
                    os.replace(src_abs, dst_abs)
                except OSError as e:
                    self._log(f"  Rename failed for {rel}: {e}", "error")
                    new_rows.append((rel, kind, text))
                    skipped_renames += 1
                    continue
                new_rows.append((new_rel, kind, text))
                renamed_count += 1
            rows = new_rows
            self._log(
                f"  Renamed {renamed_count} file(s); "
                f"{skipped_renames} skipped.",
                "success" if renamed_count else "info")

        self._set_phase(3 if self.rename_after else 2)
        out_path = os.path.join(self.assets_dir, CALLOUTS_CSV)
        self._log(f"Writing {CALLOUTS_CSV}...", "info")
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["relative_path", "classification", "text"])
            for row in rows:
                w.writerow(row)

        rename_summary = (
            f"\nRenamed {renamed_count} file(s) using transcripts."
            if self.rename_after else "")

        music_summary = (f" Tagged {music_count} long clip(s) as music."
                         if music_count else "")
        self._log("Done.", "success")
        self._done(True,
            f"Transcribed {speech_count} speech sample(s); "
            f"skipped {non_speech_count} non-speech sample(s).{music_summary}"
            f"{rename_summary}\n\n"
            f"Output: {out_path}\n\n"
            f"Each row pairs a relative WAV path with its detected "
            f"English text (or 'music'). Open in Excel / a CSV viewer and "
            f"search for the callout you want to mod.")

    # ------------------------------------------------------------------
    # transcription (serial + parallel share _transcribe_one / _emit_file_row)
    # ------------------------------------------------------------------
    def _load_model(self):
        """Construct the single in-process WhisperModel (serial path) with the
        friendly load-failure hint."""
        from faster_whisper import WhisperModel
        try:
            return WhisperModel(self.model_size, device="cpu",
                                compute_type="int8")
        except Exception as e:
            raise PipelineError("Transcribe",
                f"Failed to load Whisper model {self.model_size!r}: {e}\n\n"
                f"If this is a network error, try again with internet "
                f"available — the model is downloaded once and cached.")

    def _emit_file_row(self, n, total, rel, kind, text, errored, counts):
        """Tally one transcribed file, drive progress, and log its line.
        ``n`` is the 1-based completion count; ``counts`` is a mutable
        ``{'speech','music','non'}`` dict.  Returns the ``(rel, kind, text)``
        CSV row.  Shared by the serial + parallel paths so they report alike."""
        if errored:
            self._log(f"  {rel}: transcribe error ({errored}); marking as "
                      f"non-speech.", "info")
        if kind == "speech":
            counts["speech"] += 1
        elif kind == "music":
            counts["music"] += 1
        else:
            counts["non"] += 1
        self._progress(n, total,
                       f"{counts['speech']} speech / {counts['music']} music / "
                       f"{counts['non']} skipped")
        display = text if len(text) <= 80 else text[:77] + "..."
        tag = ("[music]" if kind == "music"
               else (display if display else "[no speech]"))
        self._log(f"  [{n}/{total}] {rel}: {tag}", "info")
        return (rel, kind, text)

    def _transcribe_serial(self, wavs):
        """Single-process transcription loop (the original path; also the
        fallback when a pool can't start).  Returns
        ``(rows, speech_count, non_speech_count, music_count)``."""
        self._log("Loading faster-whisper model...", "info")
        model = self._load_model()
        self._log(f"  Model loaded ({self.model_size}, int8 CPU).", "success")
        self._set_phase(1)
        self._log(f"Transcribing {len(wavs)} sample(s) "
                  f"(non-speech files skip Whisper via VAD)...", "info")
        counts = {"speech": 0, "music": 0, "non": 0}
        rows = []
        total = len(wavs)
        for i, abs_path in enumerate(wavs):
            self._check_cancel()
            rel = os.path.relpath(abs_path, self.assets_dir).replace("\\", "/")
            _rel, kind, text, errored = _transcribe_one(
                model, rel, abs_path, self.music_min_seconds)
            rows.append(self._emit_file_row(i + 1, total, rel, kind, text,
                                            errored, counts))
        return rows, counts["speech"], counts["non"], counts["music"]

    def _transcribe_parallel(self, wavs):
        """Transcribe across a spawn pool — one WhisperModel per worker, one task
        per WAV — streaming each file's result back as it lands (the log keeps
        animating) and reassembling rows in the original wav order so the CSV is
        identical to the serial path.  Raises if the pool can't start so the
        caller can fall back to one process."""
        import multiprocessing as mp
        ncpu = os.cpu_count() or 2
        # Cap at 8: each worker loads its own model (~1-2 s), so more workers is
        # more fixed start-up tax for diminishing parallelism — 8 amortises well
        # without flooding a 16+ core box with model loads.
        nworkers = max(1, min(ncpu - 1, len(wavs), 8))
        # One ctranslate2 thread per worker: nworkers models otherwise each grab
        # every core (N× oversubscription that erases the parallelism win).
        ctx = mp.get_context("spawn")
        self._log(f"  Loading {nworkers} model(s) across {nworkers} "
                  f"process(es)...", "info")
        pool = ctx.Pool(nworkers, initializer=_tw_init,
                        initargs=(self.model_size, self.music_min_seconds, 1))
        tasks = []
        for i, abs_path in enumerate(wavs):
            rel = os.path.relpath(abs_path, self.assets_dir).replace("\\", "/")
            tasks.append((i, rel, abs_path))
        rows_by_idx = [None] * len(wavs)
        counts = {"speech": 0, "music": 0, "non": 0}
        total = len(wavs)
        done = 0
        try:
            # Confirm a worker booted (model loaded) before committing — a
            # generous window because the very first run downloads tiny.en
            # (~75 MB); cached runs load in a second or two.
            pool.apply_async(_tw_probe).get(timeout=600)
            self._log(f"  Model(s) loaded ({self.model_size}, int8 CPU).",
                      "success")
            self._set_phase(1)
            self._log(f"Transcribing {len(wavs)} sample(s) "
                      f"(non-speech files skip Whisper via VAD)...", "info")
            for idx, rel, kind, text, errored in pool.imap_unordered(
                    _tw_worker, tasks):
                self._check_cancel()
                done += 1
                rows_by_idx[idx] = self._emit_file_row(
                    done, total, rel, kind, text, errored, counts)
            pool.close()
        finally:
            pool.terminate()
            pool.join()
        rows = [r for r in rows_by_idx if r is not None]
        return rows, counts["speech"], counts["non"], counts["music"]


def _transcribe_one(model, rel, abs_path, music_min_seconds):
    """Transcribe one WAV with VAD and classify it as speech / music /
    non-speech.  Returns ``(rel, kind, text, errored)`` where ``errored`` is
    ``None`` or the error string.  Module-level with the model passed in so the
    serial loop AND the spawned workers run the IDENTICAL logic → identical rows.
    """
    try:
        segments, info = model.transcribe(
            abs_path,
            language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 250},
            beam_size=1,
            best_of=1,
            condition_on_previous_text=False,
        )
        segments = list(segments)
    except Exception as e:
        return (rel, "non-speech", "", str(e))

    text = " ".join(s.text.strip() for s in segments).strip()
    if text:
        return (rel, "speech", text, None)
    # No speech.  A long non-speech clip is almost always music (songs run
    # minutes; SFX/ambience beds are short) — tag it so the music corpus is
    # isolated for fingerprint-titling.
    dur = float(getattr(info, "duration", 0.0) or 0.0)
    if music_min_seconds and dur >= music_min_seconds:
        return (rel, "music", "", None)
    return (rel, "non-speech", "", None)


# --------------------------------------------------------------------------
# spawn-pool workers (one WhisperModel per process; top-level so they pickle)
# --------------------------------------------------------------------------
_TW_MODEL = None
_TW_MUSIC_MIN = None


def _tw_init(model_size, music_min_seconds, cpu_threads):
    global _TW_MODEL, _TW_MUSIC_MIN
    from faster_whisper import WhisperModel
    _TW_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8",
                             cpu_threads=cpu_threads)
    _TW_MUSIC_MIN = music_min_seconds


def _tw_probe():
    """Cheap task confirming a worker's model loaded (init ran)."""
    return _TW_MODEL is not None


def _tw_worker(task):
    """task = (idx, rel, abs_path).  Returns (idx, rel, kind, text, errored)."""
    idx, rel, abs_path = task
    rel, kind, text, errored = _transcribe_one(
        _TW_MODEL, rel, abs_path, _TW_MUSIC_MIN)
    return (idx, rel, kind, text, errored)


def _find_wavs(root):
    """Walk *root* and return sorted absolute paths of every .wav."""
    found = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".wav") and not fn.startswith("."):
                found.append(os.path.join(dirpath, fn))
    found.sort()
    return found


# Characters not allowed in Windows filenames + the path separators that
# would let a malicious transcript escape the dir.  Replaced with '_'.
_FORBIDDEN_FILENAME_CHARS = r'<>:"|?*/\\'
# Cap the renamed filename's stem at this many chars.  Windows MAX_PATH
# is 260; we leave headroom for the parent dir, extension, and the
# original stem prefix.
_MAX_TEXT_LEN = 80


def _renamed_rel_path(rel_path, text):
    """Compute the renamed relative path for a transcribed file.

    ``original.wav`` + ``"Joust champion!"`` -> ``original - Joust champion!.wav``.

    Sanitizes the transcript so the new name is safe on Windows + macOS
    + Linux: strips path separators, replaces reserved chars, collapses
    whitespace, truncates over-long transcripts, and trims trailing
    periods (which Windows quietly drops, breaking exact-name lookups).
    """
    parent, base = os.path.split(rel_path)
    stem, ext = os.path.splitext(base)
    if not text:
        return rel_path

    safe = []
    for ch in text:
        if ch in _FORBIDDEN_FILENAME_CHARS:
            safe.append("_")
        elif ch == "\n" or ch == "\r" or ch == "\t":
            safe.append(" ")
        else:
            safe.append(ch)
    cleaned = "".join(safe).strip()
    # Collapse runs of whitespace introduced by char replacements.
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > _MAX_TEXT_LEN:
        cleaned = cleaned[:_MAX_TEXT_LEN].rstrip() + "..."
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        return rel_path

    new_base = f"{stem} - {cleaned}{ext}"
    return os.path.join(parent, new_base).replace("\\", "/")
