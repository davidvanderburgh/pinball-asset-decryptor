from pathlib import Path
from types import SimpleNamespace

import pytest

from pinball_decryptor.core import card_extras, ssh_card
from pinball_decryptor.plugins.stern import pipeline as P
from tests.test_card_extras import key


def setup_pipeline(tmp_path, monkeypatch):
    source = tmp_path / 'source.raw'; source.write_bytes(b'original')
    out = tmp_path / 'out.raw'
    project = tmp_path / 'project'; project.mkdir()
    card_extras.save(str(project), True, key())
    events = []
    monkeypatch.setattr(ssh_card, 'validate_request', lambda *a: card_extras.configuration(str(project)))
    monkeypatch.setattr(P, 'detect_game', lambda *a: 'spike2')
    monkeypatch.setattr(P, '_require_engine', lambda: None)
    monkeypatch.setattr(P, '_log_multi_image', lambda *a: None)
    monkeypatch.setattr(P, '_note_build_lineage', lambda *a: None)
    def write(*a, **kw):
        events.append('engine'); out.write_bytes(b'built'); return ((0, 0, 0, 0), '', '')
    fake = SimpleNamespace(write_image=write, read_build_manifest=lambda *a: {}, CardSizeError=RuntimeError)
    monkeypatch.setattr(P, 'engine', fake)
    pipe = P.SternWritePipeline(str(source), str(project), str(out),
                               lambda *a: None, lambda *a: None, lambda *a: None,
                               lambda ok, msg: events.append((ok, msg)))
    return pipe, events, out


def test_prepares_extras_before_success(tmp_path, monkeypatch):
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(ssh_card, 'apply_to_build', lambda *a, **kw: events.append('ssh') or 'SSH enabled.')
    pipe.run()
    assert events[:2] == ['engine', 'ssh']
    assert events[-1][0] is True and 'SSH' in events[-1][1]


def test_ssh_failure_prevents_success_and_quarantines_output(tmp_path, monkeypatch):
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    def fail(*a, **kw):
        raise card_extras.ExtrasError('filesystem failed')
    monkeypatch.setattr(ssh_card, 'apply_to_build', fail)
    pipe.run()
    assert events[-1][0] is False
    assert not out.exists()
    assert Path(str(out) + '.ssh-incomplete').exists()


def test_invalid_request_prevents_engine(tmp_path, monkeypatch):
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(ssh_card, 'validate_request', lambda *a: (_ for _ in ()).throw(card_extras.ExtrasError('unsupported')))
    pipe.run()
    assert events == [(False, 'unsupported')]
    assert not out.exists()


def test_ssh_only_build_allows_empty_asset_patch_set(monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    def empty(*args, **kwargs):
        raise engine._NothingToWrite('no asset replacements')
    monkeypatch.setattr(engine, '_compute_patches', empty)
    writes, counts, *rest = engine._compute_patches_or_restore(False, lambda *a: None, allow_empty=True)
    assert writes == [] and tuple(counts) == (0, 0, 0, 0)
    assert not counts.restored


def test_alias_is_refused_before_engine_mutation(tmp_path, monkeypatch):
    import os
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    os.link(pipe.original_path, out)
    pipe.run()
    assert events[-1][0] is False and 'engine' not in events
    assert Path(pipe.original_path).read_bytes() == b'original'


def test_oserror_preparation_failure_is_quarantined(tmp_path, monkeypatch):
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    def fail(*a, **kw):
        out.write_bytes(b'partial system partition')
        raise OSError('disk error')
    monkeypatch.setattr(ssh_card, 'apply_to_build', fail)
    pipe.run()
    assert events[-1][0] is False and not out.exists()
    assert Path(str(out) + '.ssh-incomplete').exists()


def test_complete_rebuild_without_extras_clears_stale_marker(tmp_path, monkeypatch):
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(ssh_card, 'validate_request', lambda *a: None)
    monkeypatch.setattr(P.engine, 'read_build_manifest', lambda *a: {'complete': True})
    marker = Path(str(out) + '.ssh-pending'); marker.write_text('old failure')
    pipe.run()
    assert events[-1][0] is True
    assert not marker.exists()
    assert pipe.update is False
