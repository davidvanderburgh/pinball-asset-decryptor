import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from pinball_decryptor.core import ssh_card as S
from pinball_decryptor.core.card_extras import ExtrasError
from tests.test_card_extras import key


def _symlink(link, target):
    try:
        link.symlink_to(target)
    except OSError:
        # Windows refuses symlinks without Developer Mode or elevation.
        pytest.skip('this system cannot create symlinks')

TOOLS = '/opt/homebrew/opt/e2fsprogs/sbin'


@pytest.fixture
def card(tmp_path):
    mk = shutil.which('mke2fs') or TOOLS + '/mke2fs'
    if not os.path.exists(mk):
        pytest.skip('real filesystem tools required')
    tree = tmp_path / 'tree'
    for d in ['etc/init.d', 'etc/rc5.d', 'usr/local/spike', 'usr/local/bin', 'usr/libexec', 'home/root', 'data']:
        (tree / d).mkdir(parents=True, exist_ok=True)
    (tree / 'etc/passwd').write_text('root:x:0:0:root:/home/root:/bin/sh\n')
    (tree / 'etc/fstab').write_text('/dev/mmcblk0p5 /data ext4 defaults 0 2\n')
    (tree / 'etc/init.d/game').write_text('SPIKE_PATH=/usr/local/spike\n# stern-spike2.dtb\n')
    (tree / 'etc/inittab').write_text('id:5:initdefault:\nl5:5:wait:/etc/init.d/rc 5\n')
    fs = tmp_path / 'root.img'
    with fs.open('wb') as f:
        f.truncate(24 << 20)
    subprocess.run([mk, '-q', '-t', 'ext3', '-F', '-d', str(tree), str(fs)], check=True)
    image = tmp_path / 'card.raw'
    mbr = bytearray(512); mbr[510:] = b'\x55\xaa'
    struct.pack_into('<B3sB3sII', mbr, 446, 0, b'\0'*3, 0x0c, b'\0'*3, 8, 2040)
    struct.pack_into('<B3sB3sII', mbr, 462, 0, b'\0'*3, 0x83, b'\0'*3, 2048, fs.stat().st_size // 512)
    with image.open('wb') as f:
        f.write(mbr); f.seek(1 << 20); f.write(fs.read_bytes()); f.write(b'GAME-DATA' * 1024)
    return image


def test_checked_enable_replace_disable_preserves_source_and_other_bytes(card, tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    before = card.read_bytes()
    out = tmp_path / 'out.raw'; shutil.copyfile(card, out)
    assert S.inspect_image(str(card))['supported']
    S.apply_to_build(str(card), str(out), {'enabled': True, 'public_keys': key()})
    state = S.inspect_image(str(out))
    assert state['enabled'] and state['public_keys'] == key() + '\n'
    second = key(seed=b'y')
    S.apply_to_build(str(card), str(out), {'enabled': True, 'public_keys': second})
    assert S.inspect_image(str(out))['public_keys'] == second + '\n'
    S.apply_to_build(str(card), str(out), {'enabled': False, 'public_keys': second})
    assert not S.inspect_image(str(out))['enabled']
    assert card.read_bytes() == before
    assert out.read_bytes()[:1 << 20] == before[:1 << 20]
    assert out.read_bytes()[25 << 20:] == before[25 << 20:]


def test_no_qualification_means_no_enablement(card, monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', set())
    assert not S.inspect_image(str(card))['supported']


def test_same_file_and_cancellation_leave_source_untouched(card, tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    before = card.read_bytes()
    alias = tmp_path / 'alias'; os.link(card, alias)
    with pytest.raises(ExtrasError):
        S.apply_to_build(str(card), str(alias), {'enabled': True, 'public_keys': key()})
    alias.unlink()
    out = tmp_path / 'out.raw'; shutil.copyfile(card, out)
    with pytest.raises(ExtrasError, match='cancel'):
        S.apply_to_build(str(card), str(out), {'enabled': True, 'public_keys': key()}, cancel=lambda: True)
    assert card.read_bytes() == before and out.read_bytes() == before


def test_bad_partition_bounds_are_refused(card, monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    with card.open('r+b') as f:
        f.seek(462 + 12); f.write(struct.pack('<I', 0xffffffff))
    assert not S.inspect_image(str(card))['supported']


def test_flash_guard_requires_matching_built_image(card, tmp_path, monkeypatch):
    from pinball_decryptor.core import card_extras
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    project = tmp_path / 'project'; project.mkdir()
    card_extras.save(str(project), True, key())
    with pytest.raises(ExtrasError, match='Build'):
        S.guard_flash(str(project), str(card))
    output = tmp_path / 'output.raw'; shutil.copyfile(card, output)
    S.apply_to_build(str(card), str(output), card_extras.configuration(str(project)))
    S.guard_flash(str(project), str(output))
    card_extras.save(str(project), False, key())
    with pytest.raises(ExtrasError, match='Build'):
        S.guard_flash(str(project), str(output))


def mutate_root(card, tmp_path, commands):
    offset, size = 1 << 20, 24 << 20
    root = tmp_path / 'mutation.img'; root.write_bytes(card.read_bytes()[offset:offset + size])
    script = tmp_path / 'mutation.commands'; script.write_text(commands)
    debug = shutil.which('debugfs') or TOOLS + '/debugfs'
    subprocess.run([debug, '-w', '-f', str(script), str(root)], check=True, capture_output=True)
    with card.open('r+b') as f:
        f.seek(offset); f.write(root.read_bytes())


def test_foreign_binary_is_not_claimed_without_recognized_service(card, tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    foreign = tmp_path / 'foreign'; foreign.write_text('foreign server')
    mutate_root(card, tmp_path, f'write {foreign} /usr/local/bin/dropbear\n')
    assert not S.inspect_image(str(card))['supported']


def test_payload_tampering_stops_before_output_write(card, tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    monkeypatch.setattr(S, 'HASHES', dict(S.HASHES, dropbear='0' * 64))
    out = tmp_path / 'output.raw'; shutil.copyfile(card, out)
    before = out.read_bytes()
    with pytest.raises(ExtrasError, match='hash'):
        S.apply_to_build(str(card), str(out), {'enabled': True, 'public_keys': key()})
    assert out.read_bytes() == before


def test_alternate_startup_service_is_refused(card, tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})
    daemon = tmp_path / 'dropbear'; daemon.write_text('#!/bin/sh\nforeign daemon\n')
    mutate_root(card, tmp_path, f'write {daemon} /etc/init.d/dropbear\nsymlink /etc/rc5.d/S20dropbear ../init.d/dropbear\n')
    assert not S.inspect_image(str(card))['supported']


def test_incomplete_image_cannot_be_flashed_without_project_options(card, tmp_path):
    marker = Path(str(card) + '.ssh-pending')
    marker.write_text('not complete')
    with pytest.raises(ExtrasError, match='incomplete'):
        S.guard_flash('', str(card))


def test_symlink_cannot_hide_incomplete_image(card, tmp_path):
    Path(str(card) + '.ssh-pending').write_text('pending')
    alias = tmp_path / 'alias.raw'; _symlink(alias, card)
    with pytest.raises(ExtrasError, match='incomplete'):
        S.guard_flash('', str(alias))
    with pytest.raises(ExtrasError, match='incomplete'):
        S.validate_request(str(alias), '')


def test_output_links_are_refused_before_any_write(card, tmp_path):
    target = tmp_path / 'target.raw'; shutil.copyfile(card, target)
    alias = tmp_path / 'alias.raw'; _symlink(alias, target)
    with pytest.raises(ExtrasError):
        S.validate_output(str(card), str(alias))


def test_hardlink_cannot_hide_pending_image(card, tmp_path):
    Path(str(card) + '.ssh-pending').write_text('pending')
    alias = tmp_path / 'hard-alias.raw'; os.link(card, alias)
    from pinball_decryptor.core import card_extras
    project = tmp_path / 'project'; project.mkdir()
    card_extras.save(str(project), True, key())
    with pytest.raises(ExtrasError):
        S.guard_flash(str(project), str(alias))


def test_hard_linked_source_is_read_and_builds_without_ssh(card, tmp_path):
    # PR #38 review: a card library often shares one file between two
    # folders. Reading it, or building/emulating with no SSH set, must not be
    # refused: every Stern build and Emulate run passes these guards.
    from pinball_decryptor.core import card_extras
    other = tmp_path / 'library-name.raw'; os.link(card, other)
    plain = tmp_path / 'plain'; plain.mkdir()
    assert S.validate_request(str(card), str(plain)) is None
    S.guard_flash(str(plain), str(card))
    assert S.inspect_image(str(card))['supported']
    project = tmp_path / 'project'; project.mkdir()
    card_extras.save(str(project), True, key())
    assert S.validate_request(str(card), str(project))['enabled']
    out = tmp_path / 'out.raw'; shutil.copyfile(card, out)
    S.apply_to_build(str(card), str(out), card_extras.configuration(str(project)))
    assert S.inspect_image(str(out))['enabled']
    with pytest.raises(ExtrasError, match='hard-linked'):
        S.guard_flash(str(project), str(card))
