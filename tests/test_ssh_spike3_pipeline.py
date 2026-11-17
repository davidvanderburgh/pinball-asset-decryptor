from pathlib import Path
import pytest
from pinball_decryptor.core import ssh_card as S, card_extras as E
from pinball_decryptor.plugins.stern import spike3_write as W, spike3
from tests.test_card_extras import key


def _symlink(link, target):
    try:
        link.symlink_to(target)
    except OSError:
        # Windows refuses symlinks without Developer Mode or elevation.
        pytest.skip('this system cannot create symlinks')


def setup(tmp_path, monkeypatch):
    source=tmp_path/'source.raw';source.write_bytes(b'original')
    out=tmp_path/'built.raw';project=tmp_path/'project';project.mkdir()
    E.save(str(project),True,key())
    monkeypatch.setattr(spike3,'is_spike3_card',lambda *a:True)
    monkeypatch.setattr(S,'validate_request',lambda *a,**kw:E.configuration(str(project)))
    events=[]
    def write(*args,**kwargs):
        assert kwargs.get('allow_empty') is True
        events.append('engine');out.write_bytes(b'copied');return (0,0,0,0)
    monkeypatch.setattr(W,'write_card',write)
    p=W.Spike3WritePipeline(str(source),str(project),str(out),lambda *a:None,lambda *a:None,lambda *a:None,
                            lambda ok,msg:events.append((ok,msg)))
    return p,out,events


def test_spike3_prepares_before_success(tmp_path,monkeypatch):
    p,out,events=setup(tmp_path,monkeypatch)
    monkeypatch.setattr(S,'apply_to_build',lambda *a,**kw:events.append('ssh') or 'SSH enabled')
    p.run()
    assert events[:2]==['engine','ssh']
    assert events[-1][0] is True and 'SSH' in events[-1][1]
    assert not S.pending_marker(out).exists()


def test_spike3_failure_is_quarantined(tmp_path,monkeypatch):
    p,out,events=setup(tmp_path,monkeypatch)
    def fail(*a,**kw):raise OSError('failed encrypted write')
    monkeypatch.setattr(S,'apply_to_build',fail)
    p.run()
    assert events[-1][0] is False and not out.exists()
    assert Path(str(out)+'.ssh-incomplete').exists()
    assert S.pending_marker(out).exists()


def test_spike3_preflight_rejects_alias_before_copy(tmp_path,monkeypatch):
    p,out,events=setup(tmp_path,monkeypatch)
    _symlink(out, p.original_path)
    p.run()
    assert 'engine' not in events and events[-1][0] is False
