"""Auto-transcribe extracted audio samples to a callouts.csv.

Asset extraction yields audio as many WAVs named only by index — when
you want to mod "the callout where the witch laughs" you'd otherwise
have to open WAVs blind because nothing maps index -> spoken text.

This module runs `faster-whisper`_ (tiny.en, int8 CPU) across every
WAV under an assets directory, with the built-in Silero VAD filter
enabled so non-speech samples (sound effects, music beds, crowd
ambience) skip Whisper entirely and just get logged as ``[no speech]``.

Output: ``callouts.csv`` at the root of the assets dir, with columns:

    folder, file, seconds, classification, text

where ``classification`` is ``speech`` for transcribed WAVs and
``non-speech`` for VAD-skipped ones; ``seconds`` is the WAV's play
length (a plain numeric sort key for Excel).  Shared infrastructure — any
manufacturer plugin whose ``Capabilities.transcribe`` is True wires
this in via ``make_transcribe_pipeline``.

.. _faster-whisper: https://github.com/SYSTRAN/faster-whisper
"""

import csv
import os
import shutil

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

# Rough one-time download size per model (the GUI's quality choices), for
# the "Downloading..." log line.  Approximate on purpose.
_MODEL_APPROX_MB = {"tiny.en": 75, "small.en": 500, "medium.en": 1500}

# The files WhisperModel actually needs (mirrors faster-whisper's own
# download list) — everything else in the repo is skipped.
_MODEL_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin",
                   "tokenizer.json", "vocabulary.*"]


def _disable_hf_progress_bars():
    """huggingface_hub's tqdm progress bars write to sys.stderr, which is
    ``None`` in the windowed app — a model download then dies instantly
    with "'NoneType' object has no attribute 'write'" (David's Guardians
    run).  faster-whisper dodges this with a disabled tqdm class; this is
    the supported global equivalent.  Idempotent and cheap."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    try:
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
    except Exception:
        pass


def _local_model_dir(model_size):
    """The local snapshot dir for *model_size*, only if it's COMPLETE
    (``model.bin`` present).  Pure local check — never touches the
    network; None when huggingface_hub is missing or the cache is
    absent/partial."""
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        return None
    try:
        d = snapshot_download("Systran/faster-whisper-%s" % model_size,
                              allow_patterns=_MODEL_PATTERNS,
                              local_files_only=True)
    except Exception:
        return None
    return d if os.path.isfile(os.path.join(d, "model.bin")) else None


def whisper_model_cached(model_size):
    """True if the voice model for *model_size* is fully downloaded (the ⚙
    quality picker logs this so a quality bump doesn't silently imply a
    multi-GB download on the next extract)."""
    return _local_model_dir(model_size) is not None

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
            renames = {}            # old_rel -> new_rel, to re-point the baseline
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
                renames[rel] = new_rel
                renamed_count += 1
            rows = new_rows
            # The rename moves the WAV after Extract wrote .checksums.md5, so
            # re-point the baseline to the new names (bytes unchanged) — else the
            # Replace-Audio tab flags every auto-named track as "changed on disk".
            if renames:
                from .checksums import rename_in_baseline
                rename_in_baseline(self.assets_dir, renames)
            self._log(
                f"  Renamed {renamed_count} file(s); "
                f"{skipped_renames} skipped.",
                "success" if renamed_count else "info")

        self._set_phase(3 if self.rename_after else 2)
        out_path = os.path.join(self.assets_dir, CALLOUTS_CSV)
        self._log(f"Writing {CALLOUTS_CSV}...", "info")
        # folder + file split into their own columns and a numeric seconds
        # column (both plain sort keys in Excel — monkeybug: the combined
        # path drowned the filename, and the play length was only findable
        # inside the Length-prefix filename).
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["folder", "file", "seconds", "classification",
                        "text"])
            for rel, kind, text in rows:
                folder, _, fname = rel.rpartition("/")
                secs = _wav_seconds(
                    os.path.join(self.assets_dir, *rel.split("/")))
                w.writerow([folder, fname,
                            "" if secs is None else "%.3f" % secs,
                            kind, text])

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
            f"Each row pairs a WAV (folder / file / play seconds) with its "
            f"detected English text (or 'music'). Open in Excel / a CSV "
            f"viewer and search for the callout you want to mod.")

    # ------------------------------------------------------------------
    # transcription (serial + parallel share _transcribe_one / _emit_file_row)
    # ------------------------------------------------------------------
    def _resolve_model_dir(self):
        """Download (or reuse) the model snapshot OURSELVES and return the
        local dir to hand to ``WhisperModel`` (serial path and workers alike
        — nothing downstream ever touches the network).

        Why not let faster-whisper download?  Its downloader swallows
        Hugging Face HTTP errors (the anonymous per-IP 429 rate limit,
        dropped connections) and silently falls back to whatever partial
        snapshot is cached, so EVERY failure surfaces as "Unable to open
        file 'model.bin'" — monkeybug hit that wall repeatedly, with the
        cache self-heal powerless because each "re-download" 429'd the same
        silent way.  Doing the snapshot_download here makes the real error
        visible: 429s wait the server's suggested delay and retry, a dead
        connection says so, and a snapshot missing model.bin is verified
        before anything tries to load it.
        """
        try:
            from huggingface_hub import snapshot_download
        except Exception:
            return self.model_size   # odd env: fall back to faster-whisper
        _disable_hf_progress_bars()
        repo = "Systran/faster-whisper-%s" % self.model_size

        d = _local_model_dir(self.model_size)
        if d:
            return d                  # complete cache: zero network traffic
        approx_mb = _MODEL_APPROX_MB.get(self.model_size)
        self._log(f"  Downloading the {self.model_size} model "
                  f"(~{approx_mb or '?'} MB, one-time)...", "info")
        rate_retries = 0
        while True:
            self._check_cancel()
            err = None
            watcher = self._start_download_watcher(approx_mb)
            try:
                snapshot_download(repo, allow_patterns=_MODEL_PATTERNS)
            except Exception as e:
                err = e
            finally:
                watcher()
            if err is None:
                d = _local_model_dir(self.model_size)
                if d:
                    self._log_line("whisper-dl",
                                   f"  Model downloaded ({self.model_size}).",
                                   "success")
                    return d
                err = RuntimeError("download finished but 'model.bin' is "
                                   "missing from the snapshot")
            if _looks_like_rate_limited(err) and rate_retries < 2:
                rate_retries += 1
                wait = _rate_limit_wait_seconds(err)
                self._log(
                    f"  Hugging Face is rate-limiting model downloads "
                    f"from this IP (HTTP 429). Waiting {wait}s, then "
                    f"retrying ({rate_retries}/2)...", "info")
                self._wait_seconds(wait)
                continue
            if _looks_like_rate_limited(err):
                raise PipelineError("Transcribe",
                    f"Failed to download the Whisper model "
                    f"{self.model_size!r}: Hugging Face is rate-limiting "
                    f"downloads from your IP (HTTP 429 Too Many "
                    f"Requests).\n\n"
                    f"This is temporary — wait a few minutes and run "
                    f"Auto-transcribe again. The model is downloaded once "
                    f"and cached, so this only affects the first run.")
            raise PipelineError("Transcribe",
                f"Failed to download the Whisper model "
                f"{self.model_size!r}: {err}\n\n"
                f"Check your internet connection and try again — the "
                f"model is downloaded once and cached. (Settings ⚙ → "
                f"Voice recognition quality → Clear downloaded voice "
                f"models resets the cache.)")

    def _load_model(self):
        """Construct the single in-process WhisperModel (serial path) from
        the locally resolved snapshot.

        Self-heals a corrupt cache: if ctranslate2 can't open a snapshot
        that looked complete (truncated blob), the model's cache dir is
        moved aside and re-resolved (= clean re-download) once before
        surfacing a precise fix.  Download errors — including the 429 rate
        limit — surface from :meth:`_resolve_model_dir` with their own
        messages and never reach the corrupt-cache one.
        """
        from faster_whisper import WhisperModel
        healed = False
        while True:
            mdir = self._resolve_model_dir()
            try:
                return WhisperModel(mdir, device="cpu", compute_type="int8")
            except Exception as e:
                if not healed and _looks_like_corrupt_model(e):
                    healed = True
                    why = _heal_whisper_cache(self.model_size)
                    if why:
                        self._log(
                            f"  Cached {self.model_size} model looked corrupt "
                            f"({why}); re-downloading...", "info")
                        continue
                cache = _whisper_cache_dir(self.model_size)
                where = (cache
                         or "the huggingface cache (~/.cache/huggingface/hub)")
                raise PipelineError("Transcribe",
                    f"Failed to load Whisper model {self.model_size!r}: "
                    f"{e}\n\n"
                    f"The cached model may be incomplete or corrupt. Delete\n"
                    f"  {where}\n"
                    f"(or use Settings ⚙ → Voice recognition quality → "
                    f"Clear downloaded voice models) then try again with "
                    f"internet available — the model is downloaded once "
                    f"and cached.")

    def _start_download_watcher(self, approx_mb):
        """Live feedback while ``snapshot_download`` blocks: a daemon thread
        polls the model's growing cache dir and rewrites ONE keyed log line
        ("… 340 / 1500 MB") every couple of seconds, so a multi-GB model
        download doesn't look like a hang (David).  Returns a stop()
        callable; safe no-matter-what — any polling error just ends it."""
        import threading

        stop = threading.Event()

        def _dir_mb():
            d = _whisper_cache_dir(self.model_size)
            if not d:
                return 0
            total = 0
            for dirpath, _dirs, files in os.walk(d):
                for fn in files:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
            return total // 1_000_000

        def _watch():
            try:
                while not stop.wait(2.0):
                    mb = _dir_mb()
                    if mb <= 0:
                        continue
                    of = f" / ~{approx_mb}" if approx_mb else ""
                    self._log_line(
                        "whisper-dl",
                        f"  Downloading the {self.model_size} model... "
                        f"{mb}{of} MB", "info")
            except Exception:
                pass

        t = threading.Thread(target=_watch, daemon=True)
        t.start()

        def _stop():
            stop.set()
            t.join(timeout=0.5)

        return _stop

    def _wait_seconds(self, seconds):
        """Sleep *seconds* in 1s slices so Cancel stays responsive."""
        import time
        for _ in range(int(seconds)):
            self._check_cancel()
            time.sleep(1)

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
        # Resolve (download if needed) the model snapshot ONCE before
        # spawning workers and hand them the local PATH: on a cold cache
        # every worker would otherwise download it at once, and ~8
        # simultaneous anonymous downloads is exactly what trips Hugging
        # Face's per-IP rate limit (monkeybug's 429).  A partial cache dir
        # counts as cold — _resolve_model_dir verifies model.bin exists.
        model_ref = self._resolve_model_dir()
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
                        initargs=(model_ref, self.music_min_seconds, 1))
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


def _tw_init(model_ref, music_min_seconds, cpu_threads):
    """*model_ref* is the LOCAL snapshot dir _resolve_model_dir returned
    (workers must never download — see _transcribe_parallel); a bare model
    size still works for the odd env without huggingface_hub."""
    global _TW_MODEL, _TW_MUSIC_MIN
    from faster_whisper import WhisperModel
    _TW_MODEL = WhisperModel(model_ref, device="cpu", compute_type="int8",
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


def _looks_like_corrupt_model(exc):
    """True if *exc* from loading WhisperModel smells like a bad cache.

    Targets the interrupted-download signature ("Unable to open file
    'model.bin'") so we don't nuke a perfectly good cache over an
    unrelated failure (e.g. out of disk, ctranslate2 mismatch)."""
    msg = str(exc).lower()
    return ("model.bin" in msg
            or "unable to open file" in msg
            or "no such file or directory" in msg)


def _looks_like_rate_limited(exc):
    """True if *exc* from loading WhisperModel smells like Hugging Face's
    per-IP download rate limit (HTTP 429)."""
    msg = str(exc).lower()
    return ("429" in msg or "too many requests" in msg
            or "rate limit" in msg or "rate-limit" in msg)


def _rate_limit_wait_seconds(exc):
    """Extract the server-suggested retry delay from a 429 error message
    ("... Retry after 20 seconds ..."), clamped to [15, 300]s; 60s when the
    message carries no number."""
    import re
    m = re.search(r"retry after (\d+)", str(exc), re.IGNORECASE)
    if not m:
        m = re.search(r"(\d+)\s*seconds", str(exc))
    if m:
        return max(15, min(300, int(m.group(1)) + 5))
    return 60


def _whisper_cache_dir(model_size):
    """Best-effort path to the huggingface cache dir for *model_size*.

    Returns the dir only if it actually exists, else None.  Honours
    HF_HOME / HF_HUB_CACHE via huggingface_hub's own resolved constant
    so we point at the same place faster-whisper downloaded to."""
    repo = f"models--Systran--faster-whisper-{model_size}"
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        base = HF_HUB_CACHE
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".cache",
                            "huggingface", "hub")
    d = os.path.join(base, repo)
    return d if os.path.isdir(d) else None


def clear_whisper_cache():
    """Delete every cached faster-whisper model — all sizes, plus any
    ``.corrupt`` dirs the self-heal set aside.  Returns ``(n_dirs,
    bytes_freed)``; the next Auto-name call-outs run re-downloads its model.
    Backs the ⚙ menu's "Clear downloaded voice models" (monkeybug's ask:
    a user-friendly way out of a cache no automatic heal could recover)."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        base = HF_HUB_CACHE
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".cache",
                            "huggingface", "hub")
    if not os.path.isdir(base):
        return 0, 0
    n = freed = 0
    for fn in os.listdir(base):
        if not fn.startswith("models--Systran--faster-whisper-"):
            continue
        d = os.path.join(base, fn)
        if not os.path.isdir(d):
            continue
        size = 0
        for dirpath, _dirs, files in os.walk(d):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        shutil.rmtree(d, ignore_errors=True)
        if not os.path.isdir(d):
            n += 1
            freed += size
    return n, freed


def _heal_whisper_cache(model_size):
    """Move a corrupt cached model dir aside so the next load re-downloads.

    Returns a short human reason if it cleared something, else None.
    Renames to ``<dir>.corrupt`` first (cheap, reversible-ish); falls back
    to a hard delete if the rename is blocked."""
    d = _whisper_cache_dir(model_size)
    if not d:
        return None
    aside = d + ".corrupt"
    try:
        if os.path.exists(aside):
            shutil.rmtree(aside, ignore_errors=True)
        os.rename(d, aside)
        return f"moved {os.path.basename(d)} aside"
    except OSError:
        try:
            shutil.rmtree(d, ignore_errors=True)
            if not os.path.isdir(d):
                return f"cleared {os.path.basename(d)}"
        except OSError:
            pass
    return None


def _wav_seconds(path):
    """Play length of *path* in seconds (float), or None if unreadable."""
    import wave
    try:
        w = wave.open(path, "rb")
        try:
            n, r = w.getnframes(), w.getframerate()
        finally:
            w.close()
        return (n / float(r)) if r else None
    except Exception:
        return None


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
