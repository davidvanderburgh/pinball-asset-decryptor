"""PAD-1531: a shared image must not carry the builder's remote access.

* a build for sharing reads back with no trusted key, no SSH program and no boot hook, and with the machine's own
  partitions (Spike 2: /data, /dump) empty, as a stock card has them; nothing else on the image changes;
* remote access off really is off: the key file and PAD's programs come off, not only the boot hook;
* one-button setup takes a card's keys of other computers off by default (named), keeps the project's own;
* a build or a write says who the card lets in; the Network tab never copies a card's keys into the project.

The card tests need real e2fsprogs (mke2fs/debugfs/e2fsck): they run under WSL/Linux and skip elsewhere, as
test_ssh_card does."""
import os
import shutil
import struct
import subprocess

import pytest

from pinball_decryptor.core import card_extras, pad_ssh_key, remote_setup, share_build, staged_changes
from pinball_decryptor.core import ssh_card as S
from pinball_decryptor.core.card_extras import ExtrasError
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
from pinball_decryptor.plugins.stern.formats import parse_all_partitions_file
from tests.test_card_extras import key
from tests.test_ssh_card import TOOLS

MiB = 1 << 20
STRANGER = key(seed=b's').replace('test machine', 'builder@far-away')


@pytest.fixture(autouse=True)
def own_key_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', str(tmp_path / 'remote_access'))


@pytest.fixture
def qualified(monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})


def _fs(mk, tmp_path, name, size, files):
    tree = tmp_path / (name + '-tree')
    tree.mkdir()
    for rel, data in files.items():
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    fs = tmp_path / (name + '.img')
    with fs.open('wb') as f:
        f.truncate(size)
    subprocess.run([mk, '-q', '-t', 'ext4', '-F', '-d', str(tree), str(fs)], check=True)
    return fs.read_bytes()


def _entry(boot, ptype, start, count):
    return struct.pack('<B3sB3sII', boot, b'\0' * 3, ptype, b'\0' * 3, start, count)


@pytest.fixture
def used_card(tmp_path):
    """A Spike 2 card laid out as Stern's (p1 boot, p2 system, p3 game, p4 extended: p5 /data, p6 /dump), whose
    /data and /dump hold what a machine in use writes there: settings, a remote access host key, logs."""
    mk = shutil.which('mke2fs') or TOOLS + '/mke2fs'
    if not os.path.exists(mk):
        pytest.skip('real filesystem tools required')
    root = _fs(mk, tmp_path, 'root', 24 * MiB, {
        'etc/passwd': b'root:x:0:0:root:/home/root:/bin/sh\n',
        'etc/fstab': b'/dev/mmcblk0p5 /data ext4 defaults 0 2\n',
        'etc/init.d/game': b'SPIKE_PATH=/usr/local/spike\n# stern-spike2.dtb\n',
        'etc/inittab': b'id:5:initdefault:\nl5:5:wait:/etc/init.d/rc 5\n',
        'etc/rc5.d/.keep': b'', 'usr/local/spike/.keep': b'', 'usr/local/bin/.keep': b'',
        'usr/libexec/.keep': b'', 'home/root/.keep': b'', 'data/.keep': b''})
    data = _fs(mk, tmp_path, 'data', 4 * MiB, {
        'dropbear/dropbear_ed25519_host_key': b'HOSTKEY' * 20,
        'nv/godzilla_le/NVM': b'WIFI-NETWORK-AND-SETTINGS' * 40,
        'descriptors': b'd'})
    dump = _fs(mk, tmp_path, 'dump', 4 * MiB, {'log/connectivity/game.log': b'192.168.1.20 joined\n' * 50})
    p2, p3, ext = 2048, 2048 + 49152, 2048 + 49152 + 2048
    p5, ebr2 = ext + 2048, ext + 2048 + 8192
    p6, end = ebr2 + 2048, ebr2 + 2048 + 8192
    mbr = bytearray(512); mbr[510:] = b'\x55\xaa'
    mbr[446:510] = (_entry(0, 0x0c, 8, 2040) + _entry(0, 0x83, p2, 49152) + _entry(0, 0x83, p3, 2048)
                    + _entry(0, 0x0f, ext, end - ext))
    ebr1 = bytearray(512); ebr1[510:] = b'\x55\xaa'
    ebr1[446:478] = _entry(0, 0x83, 2048, 8192) + _entry(0, 0x05, ebr2 - ext, end - ebr2)
    ebr_2 = bytearray(512); ebr_2[510:] = b'\x55\xaa'
    ebr_2[446:462] = _entry(0, 0x83, 2048, 8192)
    image = tmp_path / 'card.raw'
    with image.open('wb') as f:
        f.truncate(end * 512)
        for lba, blob in ((0, mbr), (p2, root), (p3, b'GAME-DATA' * 1024), (ext, ebr1), (p5, data),
                          (ebr2, ebr_2), (p6, dump)):
            f.seek(lba * 512); f.write(blob)
    return image


def _names(path, index):
    with open(path, 'rb') as f:
        part = next(p for p in parse_all_partitions_file(f) if p[0] == index)
        return share_build.entries(Ext4Reader(f, part[2] * 512, part[3] * 512))


def _system_files(path):
    """What of remote access the system partition holds: the paths that exist."""
    with open(path, 'rb') as f:
        p2 = next(p for p in S._partitions(f) if p[0] == 2)
        r = Ext4Reader(f, p2[2], p2[3])
        l = S.layout('stern-spike2')
        return {p for p in list(l['files'].values()) + [l['hook']] if S._node(r, p) is not None}


def _remote_on(card, tmp_path, keys):
    out = tmp_path / 'with-remote.raw'
    shutil.copyfile(card, out)
    S.apply_to_build(str(card), str(out), {'enabled': True, 'public_keys': keys})
    return out


# ---------------------------------------------------------------- a build for sharing
def test_a_build_for_sharing_carries_no_remote_access_and_no_machine_data(used_card, qualified, tmp_path):
    builder = _remote_on(used_card, tmp_path, pad_ssh_key.public_line())   # the builder's own card, remote on
    assert S.inspect_image(str(builder))['enabled'] and _names(builder, 4) and _names(builder, 5)
    before = builder.read_bytes()
    out = tmp_path / 'shared.raw'
    shutil.copyfile(builder, out)
    notes = []
    text = S.apply_to_build(str(builder), str(out), {'enabled': False, 'public_keys': '', 'share': True},
                            log=lambda t, l='info': notes.append(t))
    # reads back with no trusted key, none of PAD's programs and no boot hook
    state = S.inspect_image(str(out))
    assert state['supported'] and not state['enabled'] and state['public_keys'] == ''
    assert _system_files(out) == set()
    # and the machine's own partitions empty, as a stock card ships them
    assert _names(out, 4) == [] and _names(out, 5) == []
    assert share_build.machine_data(str(out)) == []
    assert text.startswith(S.SHARE_TEXT) and '/data' in text and '/dump' in text
    assert any('Emptying /data' in n for n in notes)
    # the original is untouched; the image's boot and game partitions are byte for byte as they were
    assert builder.read_bytes() == before
    after = out.read_bytes()
    assert after[:1 * MiB] == before[:1 * MiB]
    assert after[(2048 + 49152) * 512:(2048 + 49152 + 2048) * 512] == before[(2048 + 49152) * 512:(2048 + 49152 + 2048) * 512]


def test_a_build_for_sharing_leaves_empty_machine_partitions_alone(used_card, qualified, tmp_path):
    shared = tmp_path / 'shared.raw'
    shutil.copyfile(used_card, shared)
    S.apply_to_build(str(used_card), str(shared), {'enabled': False, 'public_keys': '', 'share': True})
    again = tmp_path / 'again.raw'
    shutil.copyfile(shared, again)
    text = S.apply_to_build(str(shared), str(again), {'enabled': False, 'public_keys': '', 'share': True})
    assert text == S.SHARE_TEXT                       # nothing to empty, nothing said about it
    assert again.read_bytes() == shared.read_bytes()


def test_flashing_for_sharing_refuses_an_image_that_still_carries_machine_data(used_card, qualified, tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    card_extras.save_share(str(project), True)
    with pytest.raises(ExtrasError, match='Build for sharing'):
        S.guard_flash(str(project), str(used_card))
    shared = tmp_path / 'shared.raw'
    shutil.copyfile(used_card, shared)
    S.apply_to_build(str(used_card), str(shared), card_extras.configuration(str(project)))
    S.guard_flash(str(project), str(shared))


# ---------------------------------------------------------------- off is off
def test_remote_access_off_takes_the_keys_and_programs_off_too(used_card, qualified, tmp_path):
    on = _remote_on(used_card, tmp_path, key())
    assert len(_system_files(on)) == 6
    off = tmp_path / 'off.raw'
    shutil.copyfile(on, off)
    assert S.apply_to_build(str(on), str(off), {'enabled': False, 'public_keys': key()}) == S.OFF_TEXT
    assert _system_files(off) == set() and not S.inspect_image(str(off))['enabled']
    # off keeps the machine's own data: that is only a build for sharing's to empty
    assert _names(off, 4) == _names(on, 4) != []


# ---------------------------------------------------------------- one button: strangers' keys come off
def test_one_button_setup_asks_then_takes_another_computers_key_off_and_names_it(used_card, qualified, tmp_path):
    theirs = _remote_on(used_card, tmp_path, STRANGER)         # an image someone else built, remote on
    look = remote_setup.look(str(theirs))
    assert look['enabled'] and not look['lets_pad_in'] and look['others'] == ['builder@far-away']
    # nobody has said yet whether it stays: setup stops and asks, the card unchanged
    before = theirs.read_bytes()
    res = remote_setup.set_up(str(theirs))
    assert remote_setup.asked(res) == [STRANGER] and theirs.read_bytes() == before
    notes = []
    assert remote_setup.set_up(str(theirs), log=lambda t, l='info': notes.append((l, t)),
                               keep_others=False) == 'done'
    keys = S.inspect_image(str(theirs))['public_keys']
    assert keys.strip() == pad_ssh_key.public_line().strip()   # trusts only this computer's key
    assert any(l == 'warning' and 'builder@far-away' in t and 'Taking it off' in t for l, t in notes)
    assert remote_setup.look(str(theirs))['others'] == []


def test_one_button_setup_is_not_already_done_while_a_stranger_is_on_the_card(used_card, qualified, tmp_path):
    both = _remote_on(used_card, tmp_path, pad_ssh_key.public_line().strip() + '\n' + STRANGER)
    assert remote_setup.asked(remote_setup.set_up(str(both))) == [STRANGER]
    assert remote_setup.set_up(str(both), keep_others=False) == 'done'
    assert STRANGER.split()[1] not in S.inspect_image(str(both))['public_keys']
    assert remote_setup.set_up(str(both)) == 'already'


def test_one_button_setup_keeps_the_projects_own_keys_and_others_when_asked(used_card, qualified, tmp_path):
    mine = key(seed=b'm').replace('test machine', 'my-laptop')
    card = _remote_on(used_card, tmp_path, mine + '\n' + STRANGER)
    assert remote_setup.look(str(card), own=mine)['others'] == ['builder@far-away']
    kept = tmp_path / 'kept.raw'
    shutil.copyfile(card, kept)
    remote_setup.set_up(str(card), own=mine, keep_others=False)
    keys = S.inspect_image(str(card))['public_keys']
    assert mine.split()[1] in keys and STRANGER.split()[1] not in keys
    remote_setup.set_up(str(kept), own=mine, keep_others=True)
    keys = S.inspect_image(str(kept))['public_keys']
    assert mine.split()[1] in keys and STRANGER.split()[1] in keys


# ---------------------------------------------------------------- the project's record, without a card
def test_build_for_sharing_is_remote_access_off_whatever_else_is_saved(tmp_path):
    project = tmp_path / 'p'; project.mkdir()
    assert card_extras.load_share(str(project)) is False
    card_extras.save(str(project), True, key())
    plain = card_extras.digest(str(project))
    card_extras.save_share(str(project), True)
    assert card_extras.configuration(str(project)) == {'enabled': False, 'public_keys': '', 'share': True}
    assert card_extras.digest(str(project)) != plain
    card_extras.save(str(project), False, '')
    shared = card_extras.digest(str(project))
    card_extras.save_share(str(project), False)
    assert card_extras.digest(str(project)) != shared
    assert card_extras.configuration(str(project)) == {'enabled': False, 'public_keys': ''}
    data = staged_changes.load(str(project))
    data['extras']['share'] = {'enabled': 'yes'}
    staged_changes.save(str(project), data, strict=True)
    with pytest.raises(ExtrasError):
        card_extras.configuration(str(project))


def test_others_are_the_keys_neither_this_computers_nor_the_projects():
    pad = pad_ssh_key.public_line().strip()
    mine = key(seed=b'm')
    text = '\n'.join([pad, mine, STRANGER, STRANGER, '# a comment', ''])
    assert card_extras.others(text) == [mine, STRANGER]
    assert card_extras.others(text, own=mine) == [STRANGER]
    assert card_extras.key_name(STRANGER) == 'builder@far-away'
    bare = ' '.join(STRANGER.split()[:2])
    assert card_extras.key_name(bare).startswith('key SHA256:')
    # another person's PAD: its key has the same comment as ours, so it is named by its fingerprint
    named = card_extras.key_name(bare + ' ' + pad_ssh_key.COMMENT)
    assert named.startswith('PAD on another computer (key SHA256:') and named != card_extras.key_name(pad)


def test_a_build_says_who_the_card_lets_in(monkeypatch):
    pad = pad_ssh_key.public_line().strip()
    assert S.who_gets_in('x', {'enabled': True, 'public_keys': pad}) == ('warning', S.LETS_THIS_COMPUTER_IN)
    assert S.who_gets_in('x', {'enabled': False, 'public_keys': ''}) is None
    assert S.who_gets_in('x', {'enabled': False, 'public_keys': '', 'share': True}) is None
    seen = {}
    monkeypatch.setattr(S, 'inspect_image', lambda path, key_source=None: seen.get(path, {}))
    seen['theirs'] = dict(supported=True, enabled=True, public_keys=STRANGER + '\n')
    seen['mine'] = dict(supported=True, enabled=True, public_keys=pad + '\n')
    seen['stock'] = dict(supported=True, enabled=False, public_keys='')
    level, text = S.who_gets_in('theirs', None)
    assert level == 'warning' and 'another computer' in text and 'builder@far-away' in text
    assert S.who_gets_in('mine', None) == ('warning', S.LETS_THIS_COMPUTER_IN)
    assert S.who_gets_in('stock', None) is None
    logged = []
    S.say_who_gets_in('theirs', None, lambda t, l: logged.append((l, t)))
    assert logged and logged[0][0] == 'warning'


# ---------------------------------------------------------------- the Network tab and the write
def test_network_tab_never_copies_a_cards_keys_into_the_project(tmp_path, monkeypatch):
    from tests.test_webui_network import ready
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        monkeypatch.setattr(S, 'inspect_image', lambda *a, **kw: dict(
            supported=True, reason='', platform='stern-spike2', enabled=True, public_keys=STRANGER + '\n'))
        w.run(svc.on_show)
        n = w.state('network')
        assert n['public_keys'] == '' and n['others'] == ['builder@far-away'] and not n['share']
        monkeypatch.setattr('pinball_decryptor.core.remote_setup.look', lambda *a, **kw: {'lets_pad_in': False})
        assert w.call('network.take_others_off', str(project))
        assert card_extras.load(str(project)) == {'enabled': False, 'public_keys': ''}
        assert w.state('network')['others'] == []
        assert w.call('network.configure_share', True, str(project))
        assert card_extras.load_share(str(project)) and w.state('network')['share']


def test_network_tab_keeps_the_users_own_other_computers_when_told(tmp_path, monkeypatch):
    # PAD-1531, David: "I don't want to break existing remote access that people have set up for themselves"
    from tests.test_webui_network import ready
    from tests.webui_harness import web_app
    laptop = key(seed=b'l').replace('test machine', pad_ssh_key.COMMENT)      # the user's own laptop with PAD
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        monkeypatch.setattr(S, 'inspect_image', lambda *a, **kw: dict(
            supported=True, reason='', platform='stern-spike2', enabled=True,
            public_keys=pad_ssh_key.public_line().strip() + '\n' + laptop + '\n'))
        w.run(svc.on_show)
        assert w.state('network')['others'][0].startswith('PAD on another computer')
        assert w.call('network.keep_others', str(project))
        rec = card_extras.load(str(project))
        assert rec['enabled'] and laptop.split()[1] in rec['public_keys']
        assert laptop.split()[1] in card_extras.configuration(str(project))['public_keys']   # builds keep it
        assert w.state('network')['others'] == []


@pytest.mark.parametrize('answer', [True, False, None])
def test_one_button_on_a_plugged_in_card_asks_before_any_key_comes_off(tmp_path, monkeypatch, answer):
    """Yes takes the other computer off; No keeps it on the card AND in the project, so builds keep it; Cancel
    changes nothing.  The card is never changed before the answer."""
    import json
    from pinball_decryptor.webui.tabs import network as network_tab
    from tests.test_remote_setup import _settle
    from tests.test_webui_network import ready
    from tests.webui_harness import web_app
    laptop = key(seed=b'l').replace('test machine', pad_ssh_key.COMMENT)
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        svc.set(cards=[{'display': 'SD card', 'device': r'\\.\PhysicalDrive3'}], cards_state='ok')
        w.call('network.pick_card', r'\\.\PhysicalDrive3')
        monkeypatch.setattr(network_tab.compat.messagebox, 'askyesno', lambda *a, **k: True)
        asked = []
        monkeypatch.setattr(network_tab.compat.messagebox, 'askyesnocancel',
                            lambda title, message, **k: asked.append(message) or answer)
        calls = []

        def fake(path, log=None, progress=None, cancel=None, own='', keep_others=None):
            calls.append(keep_others)
            if keep_others is None:
                return remote_setup.ASK + json.dumps([laptop])
            return 'done'
        monkeypatch.setattr(remote_setup, 'set_up_with_privileges', fake)
        assert w.call('network.set_up_card') is True
        _settle(w, 'setup_busy')
        st = w.state('network')
        assert asked and 'PAD on another computer' in asked[0] and 'your own' in asked[0]
        if answer is None:
            assert calls == [None] and 'not changed' in st['setup_note']
            assert card_extras.load(str(project)) is None
            return
        assert calls == [None, not answer] and st['setup_kind'] == 'ok'
        saved = card_extras.load(str(project))['public_keys']
        assert (laptop.split()[1] in saved) is (not answer)


def test_writing_an_image_that_lets_a_stranger_in_asks_first(tmp_path, monkeypatch):
    from tests.test_webui_network import ready
    from tests.webui_harness import web_app
    import pinball_decryptor.app as app_mod
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        state = dict(supported=True, enabled=True, public_keys=STRANGER + '\n')
        monkeypatch.setattr(S, 'inspect_image', lambda *a, **kw: state)
        asked = []
        monkeypatch.setattr(app_mod.messagebox, 'askyesno',
                            lambda title, message, **kw: asked.append(message) or False)
        assert w.app._strangers_ok('img.raw') is False
        assert 'builder@far-away' in asked[-1] and 'another computer' in asked[-1]
        state['public_keys'] = pad_ssh_key.public_line()          # the user's own build: nothing asked
        assert w.app._strangers_ok('img.raw') is True and len(asked) == 1
