"""Duplicate-sound detection across JPS banks (Pulp Fiction).

Pulp Fiction ships the same recorded take at multiple slots, sometimes in
different banks: pfspeechBEEPD is a censored parallel copy of pfspeech, and
several lines repeat again in pfsndui / pfsndfx (e.g. pfspeech #152 ==
pfspeechBEEPD #152 == pfsndui #11).  A user who replaces one slot can still
hear the stock recording on the machine because the game triggers a
different slot carrying the same audio -- which looks exactly like a broken
build.

Detection decodes every buffer of every stock ``.bnk`` to raw PCM and MD5s
it; identical digests = identical audio.  The ``.bnk`` files in an extract
stay factory-stock (edits live in the decoded ``<bnk>/`` WAVs and are only
spliced into a *copy* of the bank at Write time), so the digests reflect
factory audio no matter what the user has already modded.

The Replace Audio tab consumes the groups directly: "Group duplicates"
clusters each group's slots under one row, and the per-slot right-click
"Apply to all copies" fans one replacement onto its group so every copy the
game might play carries the edit.  Because slots in one group share
byte-identical stock PCM (hence identical slot length + format), a
replacement that fits one fits them all.
"""

import hashlib
import json
import os
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .jps_bnk import (JPS_BUFFER_HEADER_SIZE, _resolve_wav_path,
                      _riff_data_span, _scan_buffers)


@dataclass
class DupSlot:
    """One bank slot inside a duplicate group."""
    bank: str                     # bnk basename, e.g. "pfspeech"
    index: int                    # buffer index within the bank
    storage: str                  # "zlib" or "riff"
    duration_seconds: float
    wavs_dir: str                 # the bank's decoded <bnk>/ subdir
    wav_path: Optional[str]       # resolved current WAV (None if stale/missing)
    stale: bool = False           # decoded subdir predates jps_bnk_v2

    @property
    def label(self) -> str:
        return f"{self.bank} #{self.index:03d}"


@dataclass
class DupGroup:
    """Slots whose stock decoded PCM is byte-identical."""
    digest: str
    duration_seconds: float
    storage: str
    slots: List[DupSlot] = field(default_factory=list)


@dataclass
class DupScanResult:
    assets_dir: str
    bank_counts: List[Tuple[str, int]]        # (bank, sound count) in scan order
    total_sounds: int
    groups: List[DupGroup]                    # only groups of >= 2, longest first
    notes: List[str]


def _walk_bnks(assets_dir: str) -> List[str]:
    """Every .bnk under *assets_dir*, in a stable order (same discovery rule
    as the Write pipeline's _repack_modified_jps_bnks)."""
    found = []
    for root, _dirs, files in os.walk(assets_dir):
        for fn in sorted(files):
            if fn.lower().endswith(".bnk"):
                found.append(os.path.join(root, fn))
    return sorted(found, key=lambda p: os.path.basename(p).lower())


def _decode_dir_is_stale(wavs_dir: str, basename: str) -> bool:
    """True when the decoded subdir predates the corrected RIFF scanner
    (manifest ``format`` != ``jps_bnk_v2`` -- same rule as the Write
    pipeline's _guard_stale_jps_extract).  Such a dir's WAV filenames map
    to DIFFERENT streams than the current scanner enumerates (pfmusic
    exposed 24 of 49), so resolving its files against current slot indices
    would point an edit at the wrong stream.  A missing/unreadable manifest
    is tolerated, matching the pipeline."""
    manifest_path = os.path.join(wavs_dir, f"{basename}.manifest.json")
    if not os.path.isfile(manifest_path):
        return False
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            fmt = json.load(f).get("format")
    except (OSError, ValueError):
        return False
    return fmt != "jps_bnk_v2"


def scan_duplicate_sounds(assets_dir: str, log=None) -> DupScanResult:
    """Decode + hash every sound in every JPS bank under *assets_dir* and
    group slots whose stock audio is byte-identical.

    Each slot carries its resolved decoded WAV (``wav_path``), or None when
    its bank's decoded folder is stale (predates jps_bnk_v2, so its
    filenames map to different streams) -- the GUI drops slots without a
    WAV, so a stale bank simply doesn't participate.

    Raises ValueError when no banks exist (WPC-remake extracts store each
    sound once as a loose WAV, so there is nothing to cross-reference).
    """
    def _log(msg):
        if log:
            log(msg)

    bnk_paths = _walk_bnks(assets_dir)
    if not bnk_paths:
        raise ValueError(
            "No JPS sound banks (.bnk) found under this folder. Duplicate "
            "detection applies to Pulp Fiction extracts -- the WPC remakes "
            "(MM / AFM / MB) store each sound once as a loose WAV, so "
            "there are no hidden copies to find.")

    notes: List[str] = []
    bank_counts: List[Tuple[str, int]] = []
    by_digest: Dict[str, List[DupSlot]] = {}
    total = 0

    for bnk_path in bnk_paths:
        basename = os.path.splitext(os.path.basename(bnk_path))[0]
        _log(f"Hashing {os.path.basename(bnk_path)} …")
        with open(bnk_path, "rb") as f:
            data = f.read()
        buffers = _scan_buffers(data)
        if not buffers:
            notes.append(f"{os.path.basename(bnk_path)}: no JPS sound "
                         f"buffers found -- skipped.")
            continue
        wavs_dir = os.path.join(os.path.dirname(bnk_path), basename)
        stale = _decode_dir_is_stale(wavs_dir, basename)
        if stale:
            notes.append(
                f"{basename}/: its decoded WAVs are from an older version "
                f"of this app and no longer line up with the bank's "
                f"streams -- grouping is disabled for this bank. "
                f"Re-extract to fix.")
        for buf in buffers:
            payload = data[buf.bnk_offset:buf.bnk_offset + buf.compressed_size]
            if buf.storage == "zlib":
                out = zlib.decompressobj().decompress(payload)
                stock_pcm = out[JPS_BUFFER_HEADER_SIZE:
                                JPS_BUFFER_HEADER_SIZE + buf.pcm_size]
            else:
                off, plen = _riff_data_span(payload)
                if off is None:
                    notes.append(f"{basename} #{buf.index:03d}: unparseable "
                                 f"RIFF payload -- skipped.")
                    continue
                stock_pcm = payload[off:off + plen]
            if not stock_pcm:
                continue
            total += 1
            params = (f"{buf.sample_rate}:{buf.channels}:"
                      f"{buf.sample_width_bytes}:").encode("ascii")
            digest = hashlib.md5(params + stock_pcm).hexdigest()

            wav_path = (None if stale else
                        _resolve_wav_path(wavs_dir, basename, buf.index))
            by_digest.setdefault(digest, []).append(DupSlot(
                bank=basename, index=buf.index, storage=buf.storage,
                duration_seconds=buf.duration_seconds, wavs_dir=wavs_dir,
                wav_path=wav_path, stale=stale))
        bank_counts.append((basename, len(buffers)))
        _log(f"  {basename}: {len(buffers)} sounds")

    groups: List[DupGroup] = []
    for digest, slots in by_digest.items():
        if len(slots) < 2:
            continue
        slots.sort(key=lambda s: (s.bank.lower(), s.index))
        groups.append(DupGroup(
            digest=digest, duration_seconds=slots[0].duration_seconds,
            storage=slots[0].storage, slots=slots))

    # Longest first: the meaningful callouts/music surface above the
    # dozens of tiny shared blips.
    groups.sort(key=lambda g: (-g.duration_seconds,
                               g.slots[0].bank.lower(), g.slots[0].index))

    return DupScanResult(assets_dir=assets_dir, bank_counts=bank_counts,
                         total_sounds=total, groups=groups, notes=notes)
