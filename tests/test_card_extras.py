import base64
import struct
from functools import lru_cache
from Crypto.PublicKey import ECC, RSA
from Crypto.Signature import eddsa

import pytest

from pinball_decryptor.core import card_extras as E, modpack, replacement_export, staged_changes


@lru_cache
def key(kind='ssh-ed25519', seed=b'x'):
    if kind == 'ssh-ed25519':
        public = eddsa.import_private_key(seed * 32).public_key().export_key(format='OpenSSH')
    elif kind == 'ssh-rsa':
        public = RSA.generate(2048).public_key().export_key(format='OpenSSH').decode()
    else:
        public = ECC.construct(curve='P-256', d=123456 + seed[0]).public_key().export_key(format='OpenSSH')
    return public.strip() + ' test machine'


@pytest.mark.parametrize('kind', ['ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256'])
def test_keys_roundtrip_and_normalize(kind):
    pub = key(kind)
    assert E.validate_keys('\r\n# comment\r\n' + pub + '\r\n' + pub + '\n') == pub + '\n'


@pytest.mark.parametrize('text', ['', 'ssh-ed25519 AAAA example', key().replace('ssh-ed25519 ', 'ssh-rsa ', 1),
                                  'command="reboot" ' + key(), '-----BEGIN OPENSSH PRIVATE KEY-----'])
def test_invalid_keys_rejected_without_echoing_them(text):
    with pytest.raises(E.ExtrasError) as caught:
        E.validate_keys(text)
    assert 'AAAA' not in str(caught.value)
    assert 'PRIVATE KEY-----' not in str(caught.value)


def test_project_state_preserves_others_and_disabled_keys(tmp_path):
    a = tmp_path / 'a'; a.mkdir()
    b = tmp_path / 'b'; b.mkdir()
    staged_changes.save(str(a), {'settings': {'volume': 2}})
    E.save(str(a), True, key())
    assert E.configuration(str(a)) == {'enabled': True, 'public_keys': key() + '\n'}
    assert E.load(str(b)) is None
    E.save(str(a), False, key())
    assert E.configuration(str(a)) == {'enabled': False, 'public_keys': key() + '\n'}
    assert staged_changes.load(str(a))['settings'] == {'volume': 2}
    assert not modpack.project_extras(str(a)).get('extras')
    assert 'extras' not in replacement_export.record_keys()


def test_corrupt_enabled_record_is_not_silently_ignored(tmp_path):
    staged_changes.save(str(tmp_path), {'extras': {'ssh': {'enabled': 'yes', 'public_keys': key()}}})
    with pytest.raises(E.ExtrasError):
        E.configuration(str(tmp_path))


def test_private_key_never_saved_even_when_disabled(tmp_path):
    with pytest.raises(E.ExtrasError):
        E.save(str(tmp_path), False, '-----BEGIN RSA PRIVATE KEY-----')
    assert E.load(str(tmp_path)) is None


@pytest.mark.parametrize('member', ['.staged_changes.json', './.staged_changes.json', '.STAGED_CHANGES.JSON'])
def test_shared_zip_cannot_import_raw_ssh_sidecar(tmp_path, member):
    import json, zipfile
    project = tmp_path / 'recipient'; project.mkdir()
    E.save(str(project), False, key(seed=b'z'))
    before = E.load(str(project))
    pack = tmp_path / 'shared.zip'
    with zipfile.ZipFile(pack, 'w') as z:
        z.writestr(modpack.MANIFEST_NAME, json.dumps({'extras': {'extras': {'ssh': {'enabled': True, 'public_keys': key()}}}}))
        z.writestr(member, json.dumps({'extras': {'ssh': {'enabled': True, 'public_keys': key()}}}))
        z.writestr('audio.wav', b'new sound')
    modpack.import_mod_pack(str(pack), str(project))
    assert E.load(str(project)) == before
    assert (project / 'audio.wav').read_bytes() == b'new sound'


def test_invalid_curve_point_is_not_an_authorized_key():
    def wire(x): return struct.pack('>I', len(x)) + x
    blob = wire(b'ecdsa-sha2-nistp256') + wire(b'nistp256') + wire(b'\x04' + b'x' * 64)
    with pytest.raises(E.ExtrasError):
        E.validate_keys('ecdsa-sha2-nistp256 ' + base64.b64encode(blob).decode())


def test_failed_project_save_is_reported(tmp_path, monkeypatch):
    def denied(*a, **kw): raise PermissionError('read only')
    monkeypatch.setattr(staged_changes, 'write_text_atomic', denied)
    with pytest.raises(E.ExtrasError, match='could not be saved'):
        E.save(str(tmp_path), True, key())
    assert E.configuration(str(tmp_path)) is None
