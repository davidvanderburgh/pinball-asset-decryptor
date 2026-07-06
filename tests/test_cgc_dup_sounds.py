"""Tests for the duplicate-sound scan (plugins.cgc.dup_sounds).

Builds tiny synthetic JPS banks (same builders as test_cgc_jps_bnk -- no
real PF image needed) where the same PCM deliberately appears at several
slots across banks, then exercises:

  * scan groups byte-identical audio (cross-bank zlib + within-bank RIFF)
  * groups are longest-first and carry each slot's resolved WAV
  * a stale (pre-jps_bnk_v2) decode dir drops out of grouping
  * no banks -> a clear ValueError

The Replace Audio tab consumes the groups directly; the fan-out itself
(assigning one replacement to a group's copies) lives in the GUI and is
covered by tests/test_gui_smoke.py.
"""

import wave

import pytest

from pinball_decryptor.plugins.cgc import jps_bnk
from pinball_decryptor.plugins.cgc.dup_sounds import scan_duplicate_sounds
from tests.test_cgc_jps_bnk import (_build_contiguous_riff_bnk,
                                    _build_synthetic_bnk, _sine_pcm)


PCM_A = _sine_pcm(100, 440)    # duplicated: pfspeech #0 == pfspeechBEEPD #0
PCM_B = _sine_pcm(60, 880)
PCM_C = _sine_pcm(80, 220)
PCM_D = _sine_pcm(40, 1320)
PCM_E = _sine_pcm(70, 990)     # duplicated twice inside pfmusic


def _write_wav(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(jps_bnk.CHANNELS)
        w.setsampwidth(jps_bnk.SAMPLE_WIDTH_BYTES)
        w.setframerate(jps_bnk.SAMPLE_RATE)
        w.writeframes(pcm)


@pytest.fixture
def assets(tmp_path):
    """A mini PF-shaped extract: three banks + their decoded WAV subdirs."""
    data = tmp_path / "assets" / "data"
    data.mkdir(parents=True)
    (data / "pfspeech.bnk").write_bytes(
        _build_synthetic_bnk("pfspeech.txt", [PCM_A, PCM_B, PCM_C]))
    (data / "pfspeechBEEPD.bnk").write_bytes(
        _build_synthetic_bnk("pfspeechBEEPD.txt", [PCM_A, PCM_D]))
    (data / "pfmusic.bnk").write_bytes(
        _build_contiguous_riff_bnk("pfmusic.txt", [PCM_E, PCM_E]))
    for stem in ("pfspeech", "pfspeechBEEPD", "pfmusic"):
        jps_bnk.extract_bnk(str(data / f"{stem}.bnk"), str(data / stem))
    return tmp_path / "assets"


def _group_labels(result):
    return [sorted(s.label for s in g.slots) for g in result.groups]


def test_scan_groups_identical_audio(assets):
    result = scan_duplicate_sounds(str(assets))
    assert result.total_sounds == 7
    assert [n for n, _c in result.bank_counts] == [
        "pfmusic", "pfspeech", "pfspeechBEEPD"]
    labels = _group_labels(result)
    assert len(labels) == 2
    assert ["pfspeech #000", "pfspeechBEEPD #000"] in labels
    assert ["pfmusic #000", "pfmusic #001"] in labels
    # Longest first: the 100 ms speech dup outranks the 70 ms music dup.
    assert result.groups[0].duration_seconds > result.groups[1].duration_seconds


def test_each_slot_carries_its_resolved_wav(assets):
    result = scan_duplicate_sounds(str(assets))
    grp = next(g for g in result.groups
               if any(s.bank == "pfspeech" for s in g.slots))
    for s in grp.slots:
        assert s.wav_path is not None
        assert s.wav_path.endswith(f"{s.bank}_sound_{s.index:03d}.wav")
        assert not s.stale


def test_stale_v1_decode_dir_drops_out_of_grouping(assets):
    """A decoded subdir predating jps_bnk_v2 (old sparse RIFF scanner) has a
    DIFFERENT slot->file mapping, so its slots must carry no WAV and fall out
    of any group (the GUI needs 2+ present copies to show a group)."""
    import json
    beepd_dir = assets / "data" / "pfspeechBEEPD"
    manifest = beepd_dir / "pfspeechBEEPD.manifest.json"
    m = json.loads(manifest.read_text(encoding="utf-8"))
    m["format"] = "jps_bnk_v1"
    manifest.write_text(json.dumps(m), encoding="utf-8")

    result = scan_duplicate_sounds(str(assets))
    beepd = [s for g in result.groups for s in g.slots
             if s.bank == "pfspeechBEEPD"]
    assert beepd, "the group still contains the BEEPD slot"
    assert all(s.stale and s.wav_path is None for s in beepd)
    # pfspeech #000 still lists its stale twin, but with no resolvable WAV
    # the audio tab won't render it -- surfaced via a note.
    assert any("older version" in n for n in result.notes)


def test_no_banks_raises(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="No JPS sound banks"):
        scan_duplicate_sounds(str(tmp_path / "empty"))
