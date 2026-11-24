from pathlib import Path
import shutil
import struct

import pytest

from pinball_decryptor.core import ssh_card as S
from pinball_decryptor.core.card_extras import ExtrasError
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
from tests.test_card_extras import key
from tests.test_ssh_card import card


def test_spike3_payload_and_buildroot_hook(card, tmp_path):
    root = tmp_path / 'root.img'
    root.write_bytes(card.read_bytes()[1 << 20:25 << 20])
    config = {'enabled': True, 'public_keys': key() + '\n'}
    S.prepare_rootfs(root, tmp_path, config, platform='stern-spike3')
    with root.open('rb') as f:
        r = Ext4Reader(f, 0, root.stat().st_size)
        assert S._read(r, '/root/.ssh/authorized_keys') == config['public_keys'].encode()
        assert S._node(r, '/root/.ssh')['mode'] == 0o40700
        assert S._node(r, '/etc/init.d/S60padsshd')['mode'] == 0o120777
        assert r.read_symlink(S._node(r, '/etc/init.d/S60padsshd')) == 'sshd'
        assert S._node(r, '/etc/init.d/sshd')['mode'] == 0o100755
        assert S._node(r, '/etc/rc5.d/S30sshd') is None
        assert struct.unpack_from('<H', S._read(r, '/usr/local/bin/dropbear', 16 << 20), 18)[0] == 183
    S.prepare_rootfs(root, tmp_path, {'enabled': False, 'public_keys': ''}, platform='stern-spike3')
    with root.open('rb') as f:
        r = Ext4Reader(f, 0, root.stat().st_size)
        assert S._node(r, '/etc/init.d/S60padsshd') is None
        # PAD-1531: off is off - the trusted keys and PAD's programs come off with the boot hook
        assert S._node(r, '/root/.ssh/authorized_keys') is None
        assert S._node(r, '/usr/local/bin/dropbear') is None and S._node(r, '/etc/init.d/sshd') is None
        assert not S.inspect_root(r, 'stern-spike3', (2,131,0,root.stat().st_size))['enabled']
    S.prepare_rootfs(root, tmp_path, config, platform='stern-spike3')
    with root.open('rb') as f:
        assert S.inspect_root(Ext4Reader(f, 0, root.stat().st_size), 'stern-spike3', ())['enabled']


def test_spike3_not_qualified_by_spike2_result(monkeypatch):
    from pinball_decryptor.core import ssh_spike3
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    assert 'stern-spike3' not in S.QUALIFIED_PLATFORMS
    assert ssh_spike3.PLATFORM == 'stern-spike3'


@pytest.mark.parametrize('change', [dict(offset='-512'), dict(offset='512'), dict(sector_size=4096),
                                    dict(iv_tweak='1'), dict(encryption='aes-cbc-essiv:sha256'),
                                    dict(type='linear')])
def test_unsafe_luks_geometry_is_rejected(change):
    from types import SimpleNamespace
    from pinball_decryptor.core import ssh_spike3 as A
    seg=dict(type='crypt', offset=str(1 << 20), size='dynamic', encryption='aes-xts-plain64', sector_size=512, iv_tweak='0')
    seg.update(change)
    header=SimpleNamespace(hdr_size=16384, json={'segments':{'0':seg},'config':{'keyslots_size':'4096'},
        'keyslots':{'0':{'area':{'offset':'32768','size':'4096'}}}},segment=lambda _:seg)
    with pytest.raises(ExtrasError):
        A.validate_geometry({'sectors':4096},header)


def test_renamed_output_retains_source_key_identity(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from pinball_decryptor.core import ssh_spike3 as A
    from pinball_decryptor.plugins.stern import engine
    src=tmp_path/'original-title.raw';src.write_bytes(b'original')
    out=tmp_path/'renamed.raw';out.write_bytes(b'copy')
    engine._write_build_manifest(str(out), {'spike3':True,'source_path':str(src),'complete':True})
    calls=[]
    source=SimpleNamespace(has_any=lambda:True)
    def discover(path,image_id=None):calls.append((path,image_id));return source
    monkeypatch.setattr(A.Spike3KeySource,'discover',discover)
    assert A.key_for(str(out)) is source
    assert calls == [(str(src),'original-title')]


def test_missing_unlock_key_error_does_not_echo_secret(tmp_path,monkeypatch):
    from pinball_decryptor.core import ssh_spike3 as A
    def fail(*a,**kw):raise ValueError('secret-key-material')
    monkeypatch.setattr(A.Spike3KeySource,'discover',fail)
    with pytest.raises(ExtrasError) as e:A.key_for(str(tmp_path/'card.raw'))
    assert 'secret-key-material' not in str(e.value)


def test_negative_keyslot_area_cannot_allow_header_overlap():
    from types import SimpleNamespace
    from pinball_decryptor.core import ssh_spike3 as A
    seg = dict(type='crypt', offset='512', size='dynamic', encryption='aes-xts-plain64', sector_size=512)
    header = SimpleNamespace(hdr_size=16384, json={'segments': {'0': seg},
        'config': {'keyslots_size': '-32768'}, 'keyslots': {}}, segment=lambda _: seg)
    with pytest.raises(ExtrasError):
        A.validate_geometry({'sectors': 4096}, header)


def test_explicit_key_source_gets_original_image_identity(tmp_path):
    from pinball_decryptor.core import ssh_spike3 as A
    keys = A.Spike3KeySource(master_keys={'original-title:rootfs': bytes(32)})
    assert A.key_for(str(tmp_path / 'original-title.raw'), keys) is keys
    assert keys._image_id == 'original-title'


@pytest.mark.parametrize('change', ['outside_image', 'outside_extended', 'overlap'])
def test_unsafe_logical_partition_is_rejected(change):
    from pinball_decryptor.core import ssh_spike3 as A
    parts = [dict(index=2, ptype=0x83, start_lba=10, sectors=20),
             dict(index=4, ptype=0x0f, start_lba=30, sectors=100),
             dict(index=5, ptype=0x83, start_lba=31, sectors=20)]
    if change == 'outside_image':
        parts[-1]['sectors'] = 200
    elif change == 'outside_extended':
        parts[1]['sectors'] = 10
    else:
        parts[-1]['start_lba'] = 20
    with pytest.raises(ExtrasError):
        A.validate_partitions(parts, 131 * 512)
