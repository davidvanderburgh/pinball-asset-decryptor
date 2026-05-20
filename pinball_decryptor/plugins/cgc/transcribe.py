"""Auto-transcribe extracted CGC audio samples to a callouts.csv.

CGC's WPC remakes (MM, AFM, MB) ship per-game audio as several hundred
WAVs named purely by sample index (``MM_40DEB2.wav``, ``S0007-LP.wav``,
...).  When you want to mod "the callout where the witch laughs" you
have to open WAVs blind because nothing in the .img maps index ->
spoken text.

This module runs `faster-whisper`_ (tiny.en, int8 CPU) across the
extracted samples, with the built-in Silero VAD filter enabled so
non-speech samples (sound effects, music beds, crowd ambience) skip
Whisper entirely and just get logged as ``[no speech]`` in the CSV.

Output: ``callouts.csv`` at the root of the assets dir, with columns:

    relative_path, classification, text

where ``classification`` is ``speech`` for transcribed WAVs and
``non-speech`` for VAD-skipped ones.

.. _faster-whisper: https://github.com/SYSTRAN/faster-whisper
"""

import csv
import os

from ...core.pipeline_base import BasePipeline, PipelineError


WHISPER_IMPORT_HINT = (
    "Auto-transcribe needs `faster-whisper` (optional dependency).\n\n"
    "Install with:\n"
    "  pip install faster-whisper\n\n"
    "On first run it downloads the tiny.en model (~75 MB) to\n"
    "  %USERPROFILE%\\.cache\\huggingface\\hub\\\n"
    "Subsequent runs reuse the cached model offline."
)

CALLOUTS_CSV = "callouts.csv"


class TranscribePipeline(BasePipeline):
    """Walk an extracted CGC assets dir, transcribe speech-bearing WAVs.

    Phase 0: Locate WAVs + load model.
    Phase 1: Run Whisper+VAD on each WAV.
    Phase 2: Write callouts.csv.
    Phase 3: (optional) Rename speech WAVs to ``<stem> - <text>.<ext>``.

    The rename step keeps the original filename as a prefix so the
    extract -> write round trip still works: the Write pipeline's
    ``_diff_assets`` uses prefix-matching to map renamed files back
    to their original inner-ext4 path (see [[option_a_rename_aware_write]]).
    """

    def __init__(self, assets_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 model_size="tiny.en", rename_after=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.assets_dir = assets_dir
        self.model_size = model_size
        self.rename_after = rename_after

    def _run(self):
        self._set_phase(0)
        self._log("Loading faster-whisper model...", "info")
        try:
            from faster_whisper import WhisperModel
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

        # int8 keeps memory low + runs entirely on CPU.  tiny.en is
        # ~75 MB downloaded; en-only variant avoids the bigger
        # multilingual download.
        try:
            model = WhisperModel(self.model_size,
                                 device="cpu", compute_type="int8")
        except Exception as e:
            raise PipelineError("Transcribe",
                f"Failed to load Whisper model {self.model_size!r}: {e}\n\n"
                f"If this is a network error, try again with internet "
                f"available — the model is downloaded once and cached.")

        self._log(f"  Model loaded ({self.model_size}, int8 CPU).",
                  "success")
        self._check_cancel()

        self._set_phase(1)
        self._log(f"Transcribing {len(wavs)} sample(s) "
                  f"(non-speech files skip Whisper via VAD)...", "info")

        rows = []
        speech_count = 0
        non_speech_count = 0
        for i, abs_path in enumerate(wavs):
            self._check_cancel()
            rel = os.path.relpath(abs_path, self.assets_dir).replace("\\", "/")
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
                self._log(f"  {rel}: transcribe error ({e}); marking as "
                          f"non-speech.", "info")
                rows.append((rel, "non-speech", ""))
                non_speech_count += 1
                continue

            text = " ".join(s.text.strip() for s in segments).strip()
            if text:
                rows.append((rel, "speech", text))
                speech_count += 1
            else:
                rows.append((rel, "non-speech", ""))
                non_speech_count += 1

            # Log every file (truncate long transcripts to keep the
            # log readable); progress bar still ticks every file.
            self._progress(i + 1, len(wavs),
                           f"{speech_count} speech / "
                           f"{non_speech_count} skipped")
            display = text if len(text) <= 80 else text[:77] + "..."
            self._log(
                f"  [{i + 1}/{len(wavs)}] {rel}: "
                f"{display if display else '[no speech]'}",
                "info")

        # Optional Phase 3: rename speech files using their transcripts
        # so the file explorer view shows the spoken text inline.
        # Mutates ``rows`` in place so the CSV reflects the new names.
        renamed_count = 0
        skipped_renames = 0
        if self.rename_after:
            self._set_phase(2)
            self._log("Renaming speech files using transcripts...", "info")
            new_rows = []
            for rel, kind, text in rows:
                self._check_cancel()
                if kind != "speech" or not text:
                    new_rows.append((rel, kind, text))
                    continue
                new_rel = _renamed_rel_path(rel, text)
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

        self._log("Done.", "success")
        self._done(True,
            f"Transcribed {speech_count} speech sample(s); "
            f"skipped {non_speech_count} non-speech sample(s)."
            f"{rename_summary}\n\n"
            f"Output: {out_path}\n\n"
            f"Each row pairs a relative WAV path with its detected "
            f"English text. Open in Excel / a CSV viewer and search "
            f"for the callout you want to mod.")


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
