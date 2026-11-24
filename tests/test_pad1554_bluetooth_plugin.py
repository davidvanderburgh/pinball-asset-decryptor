"""PAD-1554: the Bluetooth headphones plugin (mattlqx's spike-pinball-bluetooth): pulled from its author's
project at a version tag, kept outside the app, and put on a Spike 2 card unchanged by a build."""
import gzip
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

from pinball_decryptor.core import bluetooth_card as BT, card_extras, card_plugins as P, remote_buttons as B
from pinball_decryptor.core.card_extras import ExtrasError
from pinball_decryptor.core.card_plugins import PluginError
from tests.test_wifi_card import build, node, sha

STOCK = ('#!/bin/sh\n\nulimit -c unlimited\n\nwhile [ true ] ;\ndo\n\t$1\n\t/usr/local/bin/boot_display&\n'
         '\tsleep 1\n\tpkill boot_display\ndone\n')
ROOT = Path(BT.__file__).resolve().parents[2]
ARMV7, ARM64 = BT.PLUGIN.archives['armv7'], BT.PLUGIN.archives['arm64']


def _modehook():
    spec = importlib.util.spec_from_file_location('modehook_for_bt', ROOT / 'tools/spike2_emu/modehook.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def archive(files, sums=True, extra=None):
    """A release archive as the author's packaging makes one: a flat gzip tar with its own SHA256SUMS."""
    files = dict(files)
    if sums:
        files['SHA256SUMS'] = ''.join('%s  %s\n' % (hashlib.sha256(d).hexdigest(), n)
                                      for n, d in sorted(files.items())).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755 if name.endswith('.sh') or name == 'spikebt' else 0o644
            tar.addfile(info, io.BytesIO(data))
        for info in extra or ():
            tar.addfile(info)
    return gzip.compress(buf.getvalue(), mtime=0)


def release(mark=b'one'):
    """The two archives and the release's SHA256SUMS of a made-up release."""
    common = {'menu.so': b'\x7fELF menu ' + mark, 'spikebt': b'\x7fELF helper ' + mark * 4000,
              'run-live.sh': b'#!/bin/sh\n# launcher ' + mark + b'\n', 'rollback.sh': b'#!/bin/sh\n',
              'LICENSE': b'GPL 2\n', 'NOTICE.md': b'notice\n'}
    blobs = {ARMV7: archive(dict(common, **{'radio-start.sh': b'#!/bin/sh\n# radio\n', 'btusb.ko': b'ko ' + mark})),
             ARM64: archive(common)}
    sums = ''.join('%s  %s\n' % (hashlib.sha256(d).hexdigest(), n) for n, d in blobs.items()).encode()
    return blobs, sums


class Web:
    """gitlab.com for the tests: the releases list and each release's assets."""

    def __init__(self, releases):
        self.releases, self.asked = releases, []

    def __call__(self, req, timeout):
        url = req.full_url
        self.asked.append(url)
        if '/api/v4/projects/mattlqx%2Fspike-pinball-bluetooth/releases' in url:
            rows = [{'tag_name': t, 'name': t + ' title', 'released_at': '2026-11-23T21:49:22.358Z',
                     'assets': {'links': [{'name': n} for n in list(blobs) + ['SHA256SUMS', 'btusb.ko']]}}
                    for t, (blobs, _s) in self.releases.items()]
            rows.append({'tag_name': 'nightly', 'assets': {'links': []}})
            rows.append({'tag_name': 'v9.9.9', 'assets': {'links': [{'name': ARMV7}]}})     # an asset short
            return io.BytesIO(json.dumps(rows).encode())
        tag, name = url.split('/-/releases/')[1].split('/downloads/')
        blobs, sums = self.releases[tag]
        return io.BytesIO(sums if name == 'SHA256SUMS' else blobs[name])


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('PAD_PLUGIN_DIR', str(tmp_path / 'plugins'))
    return tmp_path / 'plugins'


@pytest.fixture
def plugin(monkeypatch):
    """The plugin with a made-up release as its tested one (the real one's archives are not in this repo)."""
    blobs, sums = release()
    pinned = {'v0.3.0': {n: hashlib.sha256(d).hexdigest() for n, d in blobs.items()}}
    fake = P.Plugin(**dict(BT.PLUGIN.__dict__, pinned=pinned))
    monkeypatch.setattr(BT, 'PLUGIN', fake)
    return fake, blobs, sums


# ------------------------------------------------------------------ the plugin and its store
def test_the_plugin_names_its_author_project_and_the_release_it_was_tested_with():
    p = BT.PLUGIN
    assert P.PLUGINS['bluetooth'] is p and p.project == 'https://gitlab.com/mattlqx/spike-pinball-bluetooth'
    assert p.author == 'mattlqx' and p.license == 'GPL-2.0' and p.tested == 'v0.3.0'
    assert set(p.pinned['v0.3.0']) == {ARMV7, ARM64} and all(len(h) == 64 for h in p.pinned['v0.3.0'].values())
    assert P.asset_url(p, 'v0.3.0', ARMV7) == (
        'https://gitlab.com/mattlqx/spike-pinball-bluetooth/-/releases/v0.3.0/downloads/' + ARMV7)
    assert 'projects/mattlqx%2Fspike-pinball-bluetooth/releases' in P.releases_url(p)
    with pytest.raises(PluginError):
        P.asset_url(p, '../../x', ARMV7)
    # none of the author's code is in this repository: the app only knows where to get it
    assert not [f for f in (ROOT / 'pinball_decryptor').rglob('*') if f.name in ('spikebt', 'btusb.ko', 'run-live.sh')]


def test_install_keeps_the_release_outside_the_app_and_refuses_a_wrong_file(store, plugin):
    fake, blobs, sums = plugin
    web = Web({'v0.3.0': (blobs, sums)})
    assert P.installed(fake) is None
    said = []
    rec = P.install(fake, log=said.append, opener=web)
    assert rec['tag'] == 'v0.3.0' and rec['tested'] and P.installed(fake) == rec
    assert sorted(f.name for f in (store / 'bluetooth').iterdir()) == sorted([ARMV7, ARM64, 'SHA256SUMS',
                                                                               'installed.json'])
    assert 'gitlab.com/mattlqx' in said[0] and said[-1] == 'Bluetooth headphones v0.3.0 installed.'
    tag, members = P.files(fake, 'armv7')
    assert tag == 'v0.3.0' and members['run-live.sh'][1] == 0o755 and members['menu.so'][1] == 0o644
    assert 'btusb.ko' in members and 'btusb.ko' not in P.files(fake, 'arm64')[1]
    # a file that is not the one the app was tested with is not installed, and what was there stays
    bad = dict(blobs, **{ARMV7: archive({'menu.so': b'evil', 'spikebt': b'x', 'run-live.sh': b'x',
                                         'radio-start.sh': b'x', 'btusb.ko': b'x'})})
    bad_sums = ''.join('%s  %s\n' % (hashlib.sha256(d).hexdigest(), n) for n, d in bad.items()).encode()
    with pytest.raises(PluginError, match='is not the file release v0.3.0 published'):
        P.install(fake, opener=Web({'v0.3.0': (bad, bad_sums)}))
    assert P.installed(fake) == rec
    # the store changed behind the app's back: nothing is read from it
    (store / 'bluetooth' / ARMV7).write_bytes(bad[ARMV7])
    with pytest.raises(PluginError, match='Install it'):
        P.files(fake, 'armv7')
    P.remove(fake)
    assert P.installed(fake) is None and not (store / 'bluetooth').exists()
    with pytest.raises(PluginError, match='Install it on the Plugins tab first'):
        P.files(fake, 'armv7')


def test_a_newer_tag_is_taken_on_the_releases_own_checksums_and_said_to_be_untested(store, plugin):
    fake, blobs, sums = plugin
    newer = release(b'two')
    web = Web({'v0.3.0': (blobs, sums), 'v0.4.0': newer})
    assert [(r['tag'], r['tested'], r['date']) for r in P.releases(fake, opener=web)] == [
        ('v0.4.0', False, '2026-11-23'), ('v0.3.0', True, '2026-11-23')]        # no nightly, no v9.9.9
    said = []
    rec = P.install(fake, 'v0.4.0', log=said.append, opener=web)
    assert rec['tag'] == 'v0.4.0' and not rec['tested'] and 'newer than this version of the app' in said[-1]
    assert b'launcher two' in P.files(fake, 'armv7')[1]['run-live.sh'][0]
    # its checksum list is what is believed, so an archive that does not match it is refused
    broken = (dict(newer[0], **{ARM64: blobs[ARM64]}), newer[1])
    with pytest.raises(PluginError, match='is not the file release v0.5.0 published'):
        P.install(fake, 'v0.5.0', opener=Web({'v0.5.0': broken}))
    assert P.installed(fake)['tag'] == 'v0.4.0'

    def down(req, timeout):
        raise OSError('no route to host')
    with pytest.raises(PluginError, match='Could not download .*gitlab.com'):
        P.install(fake, opener=down)
    with pytest.raises(PluginError, match='Could not download'):
        P.releases(fake, opener=down)


def test_install_from_files_takes_only_a_release_the_app_knows(store, plugin, tmp_path):
    fake, blobs, sums = plugin
    got = tmp_path / 'downloads'
    got.mkdir()
    for name, data in dict(blobs, SHA256SUMS=sums).items():
        (got / name).write_bytes(data)
    with pytest.raises(PluginError, match='Choose .*SHA256SUMS'):
        P.install_from_files(fake, [str(got / ARMV7), str(got / ARM64)])
    assert P.install_from_files(fake, [str(p) for p in got.iterdir()])['tag'] == 'v0.3.0'
    (got / ARM64).write_bytes(release(b'two')[0][ARM64])
    with pytest.raises(PluginError, match='not a Bluetooth headphones release this version of the app knows'):
        P.install_from_files(fake, [str(p) for p in got.iterdir()])


def test_an_archive_must_be_plain_files_that_match_their_own_checksums():
    p = BT.PLUGIN
    good = {'menu.so': b'm', 'spikebt': b's', 'run-live.sh': b'r'}
    assert set(P.unpack(p, 'arm64', archive(good))) == set(good) | {'SHA256SUMS'}
    with pytest.raises(PluginError, match='has no radio-start.sh, btusb.ko'):
        P.unpack(p, 'armv7', archive(good))
    with pytest.raises(PluginError, match='no SHA256SUMS of its own'):
        P.unpack(p, 'arm64', archive(good, sums=False))
    lying = dict(good, SHA256SUMS=b'%s  menu.so\n' % (b'0' * 64))
    with pytest.raises(PluginError, match='do not match its own SHA256SUMS'):
        P.unpack(p, 'arm64', archive(lying, sums=False))
    link = tarfile.TarInfo('evil')
    link.type, link.linkname = tarfile.SYMTYPE, '/etc/passwd'
    path = tarfile.TarInfo('../up')
    for extra in ([link], [path]):
        with pytest.raises(PluginError, match='not a plain file at its top level'):
            P.unpack(p, 'arm64', archive(good, extra=extra))
    with pytest.raises(PluginError, match='not a readable .tar.gz'):
        P.unpack(p, 'arm64', b'not an archive')
    with pytest.raises(PluginError, match='does not read'):
        P.parse_sums('rm -rf /\n')


# ------------------------------------------------------------------ the start-up script
def test_the_start_up_block_calls_the_authors_launcher_and_keeps_every_other_preload():
    mh = _modehook()
    assert (B.BT_HOOK_LINES, B.BT_RUN, B.BT_ENABLED, B.BT_GAME) == (
        mh.BT_HOOK_LINES, mh.BT_RUN, mh.BT_ENABLED, mh.BT_GAME)                 # one definition, twice
    assert B.BLOCKS[0] is B.BT_HOOK_LINES and mh.BLOCKS[0] is mh.BT_HOOK_LINES
    on = B.monitor_text(STOCK, False, bluetooth=True)
    text = '\n'.join(B.BT_HOOK_LINES)
    assert text in on and '\t\t\t/usr/local/spikebt/run-live.sh $1\n' in on
    assert 'PADGAME=$1 PADPRE=$PADPRE /usr/local/spikebt/run-live.sh /usr/local/bin/pad-bt-game' in on
    # the launcher is used only when its files and its `enabled` file are there; else the block is the old one
    assert '[ -f /usr/local/spikebt/enabled ] && [ -x /usr/local/spikebt/run-live.sh ]' in text
    assert text.index('run-live.sh $1') < text.index('LD_PRELOAD=$PADPRE $1') < text.index('\t\t\t$1')
    # every earlier form takes it, and it goes back to each
    modes, menu = mh.hook_game_monitor(STOCK, menu=False), mh.hook_game_monitor(STOCK, menu=True)
    buttons = B.monitor_text(STOCK, True)
    for was in (modes, menu, buttons, on):
        assert B.monitor_text(was, False, bluetooth=True) == on
    assert B.monitor_text(on, False, bluetooth=False) == STOCK
    assert B.monitor_text(on, False, mode=True, bluetooth=False) == modes
    assert B.monitor_text(on, False, mode=True, menu=True, bluetooth=False) == menu
    assert B.monitor_text(on, True, bluetooth=False) == buttons
    # remote buttons going on or off, and a mode install, leave a Bluetooth card's block alone
    assert B.monitor_text(on, True) == on == B.monitor_text(on, False) == mh.hook_game_monitor(on)
    assert mh.has_bluetooth_hook(on) and mh.has_hook(on) and mh.strip_hook(on) == STOCK
    assert 'Bluetooth hook present' in mh.describe(on) and not mh.has_bluetooth_hook(buttons)
    # the file the launcher is handed in place of the game puts this app's objects first and starts the game
    assert BT.WRAPPER_TEXT.startswith('#!/bin/sh\n') and BT.WRAPPER_TEXT.endswith('exec "$PADGAME"\n')
    assert 'LD_PRELOAD="$PADPRE${LD_PRELOAD:+:$LD_PRELOAD}"\nexport LD_PRELOAD\n' in BT.WRAPPER_TEXT


def test_project_choice_roundtrip_and_digest(tmp_path, store, plugin):
    fake, blobs, sums = plugin
    project = tmp_path / 'project'
    project.mkdir()
    assert card_extras.load_bluetooth(str(project)) is None and card_extras.digest(str(project)) is None
    assert card_extras.save_bluetooth(str(project), True) == {'enabled': True}
    assert card_extras.load_bluetooth(str(project)) == {'enabled': True}
    not_installed = card_extras.digest(str(project))
    P.install(fake, opener=Web({'v0.3.0': (blobs, sums)}))
    with_release = card_extras.digest(str(project))
    assert not_installed and with_release and with_release != not_installed      # the release is part of a build
    card_extras.save_bluetooth(str(project), False)
    assert card_extras.digest(str(project)) not in (not_installed, with_release)
    with pytest.raises(ExtrasError):
        card_extras.save_bluetooth(str(project), 'yes')
    with pytest.raises(ExtrasError):
        card_extras.save_bluetooth(str(tmp_path / 'nowhere'), True)


# ------------------------------------------------------------------ the card (real filesystem tools)
def _card(tmp_path, script=STOCK, extra=None):
    files = {'etc/init.d/game_monitor': script.encode()}
    files.update(extra or {})
    return build(tmp_path, extra=files)


def _installed(plugin, mark=None, tag='v0.3.0'):
    fake, blobs, sums = plugin
    if mark:
        blobs, sums = release(mark)
    P.install(fake, tag, opener=Web({tag: (blobs, sums)}))
    return P.files(fake, 'armv7')[1]


def test_on_puts_the_release_on_the_card_unchanged_and_off_takes_it_all_back(tmp_path, store, plugin):
    image = _card(tmp_path)
    assert BT.inspect_image(str(image)) == dict(BT.inspect_image(str(image)), supported=True, enabled=False,
                                                release='')
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    before = sha(image)
    with pytest.raises(ExtrasError, match='Install it on the Plugins tab first'):
        BT.apply_to_build(str(image), str(out), {'enabled': True})
    members = _installed(plugin)
    text = BT.apply_to_build(str(image), str(out), {'enabled': True})
    assert 'spike-pinball-bluetooth v0.3.0 is on the card' in text and 'USB Bluetooth adapter' in text
    assert sha(image) == before
    info = BT.inspect_image(str(out))
    assert info['enabled'] and info['release'] == 'v0.3.0' and 'v0.3.0' in BT.describe(info)
    for name, (data, mode) in members.items():                       # the author's files, byte for byte
        got = node(out, BT.DIR + '/' + name)
        assert got['data'] == data and got['mode'] & 0o7777 == mode and got['uid'] == 0, name
    assert members['run-live.sh'][1] == members['spikebt'][1] == 0o755
    assert node(out, BT.ENABLED)['data'] == b'' and node(out, BT.RELEASE)['data'] == b'v0.3.0\n'
    wrapper, mon = node(out, BT.WRAPPER), node(out, BT.MONITOR)
    assert wrapper['data'].decode() == BT.WRAPPER_TEXT and wrapper['mode'] & 0o7777 == 0o755
    assert mon['data'].decode() == B.monitor_text(STOCK, False, bluetooth=True) and mon['mode'] & 0o7777 == 0o755
    assert BT.apply_to_build(str(image), str(out), {'enabled': True}) == text          # already there: no rewrite
    assert BT.apply_to_build(str(image), str(out), {'enabled': False}) == BT.note(False)
    assert node(out, BT.DIR) is None and node(out, BT.WRAPPER) is None
    assert node(out, BT.MONITOR)['data'].decode() == STOCK and not BT.inspect_image(str(out))['enabled']


def test_another_release_replaces_the_one_on_the_card(tmp_path, store, plugin):
    image = _card(tmp_path)
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    _installed(plugin)
    BT.apply_to_build(str(image), str(out), {'enabled': True})
    newer = _installed(plugin, mark=b'two', tag='v0.4.0')
    assert 'v0.4.0' in BT.apply_to_build(str(image), str(out), {'enabled': True})
    assert BT.inspect_image(str(out))['release'] == 'v0.4.0'
    assert node(out, BT.DIR + '/menu.so')['data'] == newer['menu.so'][0]


def test_bluetooth_and_remote_buttons_and_modes_share_the_one_block(tmp_path, store, plugin):
    mh = _modehook()
    image = _card(tmp_path, script=mh.hook_game_monitor(STOCK, menu=False),
                  extra={'usr/local/padmode/mode.so': b'\x7fELF mode'})
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    _installed(plugin)
    B.apply_to_build(str(image), str(out), {'enabled': True})
    BT.apply_to_build(str(image), str(out), {'enabled': True})
    both = B.inspect_image(str(out)), BT.inspect_image(str(out))
    assert both[0]['enabled'] and both[1]['enabled']
    assert node(out, BT.MONITOR)['data'].decode() == B.monitor_text(STOCK, False, bluetooth=True)
    # buttons off: the shim goes, Bluetooth stays; and Bluetooth off on a card with buttons gives their block back
    B.apply_to_build(str(image), str(out), {'enabled': False})
    assert node(out, B.SO) is None and BT.inspect_image(str(out))['enabled']
    B.apply_to_build(str(image), str(out), {'enabled': True})
    BT.apply_to_build(str(image), str(out), {'enabled': False})
    assert node(out, BT.MONITOR)['data'].decode() == B.monitor_text(STOCK, True)
    assert B.inspect_image(str(out))['enabled'] and node(out, BT.DIR) is None
    # and with neither, a card with modes has the mode block it started with
    B.apply_to_build(str(image), str(out), {'enabled': False})
    assert node(out, BT.MONITOR)['data'].decode() == mh.hook_game_monitor(STOCK, menu=False)


def test_a_card_that_is_not_one_this_app_knows_is_left_alone(tmp_path, store, plugin):
    image = _card(tmp_path, script='#!/bin/sh\nexec /games/game\n')
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    _installed(plugin)
    assert not BT.inspect_image(str(image))['supported']
    with pytest.raises(ExtrasError, match='not one this app knows'):
        BT.apply_to_build(str(image), str(out), {'enabled': True})
    assert BT.apply_to_build(str(image), str(out), {'enabled': False}) == ''
    assert sha(out) == sha(image)
    assert BT.offered(type('M', (), {'key': 'stern', '_era': 'spike2'})())
    assert BT.platform_of(type('M', (), {'key': 'stern', '_era': 'spike3'})()) == BT.SPIKE3
    assert not BT.offered(type('M', (), {'key': 'stern', '_era': 'spike1'})())
    assert not BT.offered(type('M', (), {'key': 'jjp', '_era': ''})()) and not BT.offered(None)


def test_flash_only_needs_a_build_that_carries_the_choice(tmp_path, store, plugin):
    image = _card(tmp_path)
    project = tmp_path / 'project'
    project.mkdir()
    BT.guard_flash(str(project), str(image))                         # never set: nothing to ask
    card_extras.save_bluetooth(str(project), True)
    with pytest.raises(ExtrasError, match='not installed on this computer'):
        BT.guard_flash(str(project), str(image))
    _installed(plugin)
    with pytest.raises(ExtrasError, match='Build the complete image first'):
        BT.guard_flash(str(project), str(image))
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    BT.apply_to_build(str(image), str(out), BT.validate_request(str(image), str(project)))
    BT.guard_flash(str(project), str(out))


# ------------------------------------------------------------------ the build
def test_a_build_puts_the_plugin_on_after_the_others_and_names_it(tmp_path, monkeypatch):
    from pinball_decryptor.core import ssh_card
    from tests.test_extras_pipeline import setup_pipeline
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(ssh_card, 'validate_request', lambda *a: None)
    monkeypatch.setattr(ssh_card, 'note_build', lambda *a: events.append('noted'))
    monkeypatch.setattr(BT, 'validate_request', lambda *a: {'enabled': True})
    monkeypatch.setattr(B, 'validate_request', lambda *a: {'enabled': True})
    monkeypatch.setattr(B, 'apply_to_build', lambda *a, **kw: events.append('buttons') or 'Remote buttons: on.')
    monkeypatch.setattr(BT, 'apply_to_build', lambda *a, **kw: events.append('bluetooth') or BT.note(True, 'v0.3.0'))
    pipe.run()
    assert events[:4] == ['engine', 'buttons', 'bluetooth', 'noted']
    ok, msg = events[-1]
    assert ok is True and msg.startswith('Wrote remote buttons and Bluetooth headphones to ')
    assert msg.endswith('Remote buttons: on.\n' + BT.note(True, 'v0.3.0'))
    assert not Path(str(out) + '.ssh-pending').exists()

    def fail(*a, **kw):
        raise ExtrasError('the card has no room')
    monkeypatch.setattr(BT, 'apply_to_build', fail)
    events.clear()
    pipe.run()
    assert events[-1] == (False, 'the card has no room')
    assert not out.exists() and Path(str(out) + '.ssh-incomplete').exists()   # never left where a flash finds it


def test_a_ticked_plugin_that_is_not_installed_stops_the_build_before_it_starts(tmp_path, monkeypatch, store):
    from pinball_decryptor.core import ssh_card
    from tests.test_extras_pipeline import setup_pipeline
    pipe, events, out = setup_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(ssh_card, 'validate_request', lambda *a: None)
    monkeypatch.setattr(BT, 'inspect_image', lambda *a, **kw: {'supported': True, 'enabled': False, 'release': ''})
    card_extras.save_bluetooth(str(tmp_path / 'project'), True)
    pipe.run()
    assert events == [(False, BT.NOT_INSTALLED)] and not out.exists()


def test_the_write_tab_lists_the_pending_choice(tmp_path, monkeypatch, store, plugin):
    from pinball_decryptor.webui import write_scan
    project = tmp_path / 'project'
    project.mkdir()
    assert write_scan.bluetooth_rows(None, str(project)) == []
    card_extras.save_bluetooth(str(project), True)
    assert 'the plugin is not installed' in write_scan.bluetooth_rows(None, str(project))[0][0]
    fake, blobs, sums = plugin
    P.install(fake, opener=Web({'v0.3.0': (blobs, sums)}))
    row = write_scan.bluetooth_rows(None, str(project))[0]
    assert row[0] == 'Bluetooth headphones \u2014 spike-pinball-bluetooth v0.3.0' and 'Plugins tab' in row[2]
    card_extras.save_bluetooth(str(project), False)
    assert write_scan.bluetooth_rows(None, str(project)) == []                # off on a card without it: nothing


# ------------------------------------------------------------------ the Plugins tab
def _settle(w, done):
    import time
    for _ in range(300):
        w.drain()
        if done(w.state('plugins')['plugins'][0]):
            return w.state('plugins')['plugins'][0]
        time.sleep(0.02)
    raise AssertionError('never settled')


def test_the_plugins_tab_is_on_the_rail_where_a_plugin_could_go():
    from pinball_decryptor.webui import help_content as HD, tabs as T
    from pinball_decryptor.webui.tabs import plugins as TP
    assert ("plugins", "plugins", "Plugins", "Plugins", "Make", "blocks") in T.TABS
    assert len([t for t in T.TABS if t[0] == 'plugins']) == 1
    win = (ROOT / 'pinball_decryptor/webui/window.py').read_text(encoding='utf-8')
    assert '"Plugins": _plugins_offered(mfr),' in win and '"Plugins": None' in win
    assert TP.offered(type('M', (), {'key': 'stern', '_era': 'spike2'})())
    assert not TP.offered(type('M', (), {'key': 'jjp', '_era': ''})()) and not TP.offered(None)
    assert [t for t, _b in HD.sections_for('Plugins')] == ["What it's for", 'Versions', 'Bluetooth headphones']
    js = (ROOT / 'pinball_decryptor/webui/static/js/tabs/plugins.js').read_text(encoding='utf-8')
    assert 'title=""' not in js and 'export const css = true' in js
    assert (ROOT / 'pinball_decryptor/webui/static/css/tabs/plugins.css').is_file()


def test_the_plugins_tab_installs_a_version_and_saves_the_projects_tick(tmp_path, monkeypatch, store, plugin):
    from pinball_decryptor.webui.tabs import plugins as TP
    from tests.webui_harness import web_app
    fake, blobs, sums = plugin
    monkeypatch.setitem(P.PLUGINS, 'bluetooth', fake)
    web = Web({'v0.3.0': (blobs, sums), 'v0.4.0': release(b'two')})
    monkeypatch.setattr(P.net, 'urlopen', web)
    with web_app(tmp_path, mfr='stern') as w:
        w.window.current_mfr._era = 'spike2'
        project = tmp_path / 'project'
        project.mkdir()
        image = tmp_path / 'source.raw'
        image.write_bytes(b'card')
        monkeypatch.setattr(BT, 'inspect_image', lambda path, **k: dict(supported=True, reason='', enabled=False,
                                                                        release='', hooked=False, files=False))
        w.run(w.window.write_assets_var.set, str(project))
        w.run(w.window.write_upd_var.set, str(image))
        svc = w.window.service('plugins')
        assert svc.rail_needs() == 'none'
        w.run(svc.on_show)
        row = _settle(w, lambda r: r['releases_state'] == 'ok')
        st = w.state('plugins')
        assert st['store'] == str(store) and 'updating this app leaves it installed' in st['intro']
        assert row['name'] == 'Bluetooth headphones' and row['author'] == 'mattlqx'
        assert row['project_url'] == 'https://gitlab.com/mattlqx/spike-pinball-bluetooth' and row['license'] == 'GPL-2.0'
        assert [(r['tag'], r['tested']) for r in row['releases']] == [('v0.4.0', False), ('v0.3.0', True)]
        assert row['pick'] == 'v0.3.0' and not row['installed'] and row['offered'] and row['supported']
        assert row['now'] == 'no Bluetooth headphones (as shipped)' and any(r[0] == 'To undo' for r in row['details'])
        # ticked before it is installed: said, in the words that tell the user what to do
        assert w.call('plugins.configure', 'bluetooth', True, str(project))
        assert card_extras.load_bluetooth(str(project)) == {'enabled': True}
        row = w.state('plugins')['plugins'][0]
        assert row['enabled'] and 'not installed on this computer' in row['hint']
        assert w.call('plugins.configure', 'bluetooth', True, str(tmp_path)) is False     # not this tab's project
        # install the tested version, then a newer one
        assert w.call('plugins.install', 'bluetooth', '')
        row = _settle(w, lambda r: not r['busy'])
        assert row['installed'] == 'v0.3.0' and row['installed_tested'] and row['kind'] == 'ok' and not row['hint']
        assert P.installed(fake)['tag'] == 'v0.3.0' and (store / 'bluetooth' / 'installed.json').is_file()
        assert w.call('plugins.pick', 'bluetooth', 'v0.4.0') and w.call('plugins.install', 'bluetooth', 'v0.4.0')
        row = _settle(w, lambda r: not r['busy'])
        assert row['installed'] == 'v0.4.0' and not row['installed_tested'] and 'newer than this version' in row['note']
        # a download that fails says so and leaves what was installed
        monkeypatch.setattr(P.net, 'urlopen', lambda req, timeout: (_ for _ in ()).throw(OSError('offline')))
        assert w.call('plugins.install', 'bluetooth', 'v0.3.0')
        row = _settle(w, lambda r: not r['busy'])
        assert row['kind'] == 'err' and 'Could not download' in row['note'] and row['installed'] == 'v0.4.0'
        assert w.call('plugins.remove', 'bluetooth')
        row = w.state('plugins')['plugins'][0]
        assert not row['installed'] and 'Cards already written keep it' in row['note'] and P.installed(fake) is None
        assert w.call('plugins.install', 'nothing', '') is False and w.call('plugins.remove', 'nothing') is False
        # a Spike 3 card: offered too, with its own words (no adapter, how an encrypted partition is changed)
        w.window.current_mfr._era = 'spike3'
        w.run(svc.publish)
        row = w.state('plugins')['plugins'][0]
        assert row['offered'] and 'its own Bluetooth radio' in row['needs']
        assert any(r[0] == 'Normal power-off' for r in row['details'])
        assert not any('pad-bt-game' in r[1] or 'btusb.ko' in r[1] for r in row['details'])
        # an era the plugin does not go on: nothing to tick
        w.window.current_mfr._era = 'spike1'
        w.run(svc.publish)
        row = w.state('plugins')['plugins'][0]
        assert not row['offered'] and row['reason'] == BT.NOT_OFFERED


# ------------------------------------------------------------------ Spike 3
#: Stern's Spike 3 game_monitor, the part around the line that starts the game (read off a Fallout LE 0.82 card;
#: the same file on every Spike 3 card in the library)
S3_STOCK = ('#!/bin/sh\n\nsource /etc/init.d/shared\n\nPOWER_LOSS="3"\n\nif [ -x $GAME ]; then\n'
            '\tpkill boot_display \n\n\twhile [ true ] ;\n\tdo\n\t\t# start game\n\t\t$GAME\n'
            '\t\tGAME_EXIT_REASON="$?"\n\n\t\tif [ "$GAME_EXIT_REASON" -eq "$POWER_LOSS" ]; then\n'
            '\t\t\tsync_and_hang\n\t\tfi\n\t\tsleep 1\n\tdone\nfi\n')


def test_the_spike3_block_runs_the_launcher_with_bluez5_and_hands_on_the_games_exit_code():
    on = BT.s3_monitor_text(S3_STOCK, True)
    block = '\n'.join(BT.S3_HOOK_LINES)
    assert block in on and BT.s3_monitor_text(on, True) == on and BT.s3_monitor_text(on, False) == S3_STOCK
    # exactly the spelling his launcher knows: any other value makes it exit without starting the game
    assert '\t\t\tSPIKEBT_BACKEND=bluez5 /usr/local/spikebt/run-live.sh $GAME\n' in on
    assert '[ -f /usr/local/spikebt/enabled ] && [ -x /usr/local/spikebt/run-live.sh ]' in block
    # Stern's script reads $? on the next line: the block ends by setting it to the game's own code
    assert on.index('(exit "$PADBT")') < on.index('GAME_EXIT_REASON="$?"')
    assert on.split('(exit "$PADBT")\n')[1].startswith('\t\tGAME_EXIT_REASON="$?"')
    assert block.count('PADBT=$?') == 2
    # a normal end (reboot asked for, power off, deep sleep) does not leave the launcher switched off
    assert 'case "$PADBT" in 1|3|6) rm -f /dump/spikebt/disabled ;; esac' in block
    for bad in ('#!/bin/sh\nexec /games/game\n', S3_STOCK.replace('\t\tGAME_EXIT_REASON="$?"\n', ''),
                S3_STOCK + '\t\t$GAME\n\t\tGAME_EXIT_REASON="$?"\n'):
        with pytest.raises(ExtrasError, match='not one this app knows'):
            BT.s3_monitor_text(bad, True)


def test_the_block_sets_the_exit_code_in_a_real_shell(tmp_path):
    """The block run by sh with stand-ins for the launcher and the game: Stern's line reads the game's code."""
    import subprocess
    sh = shutil.which('sh')
    if not sh or sys.platform == 'win32':
        pytest.skip('a POSIX sh is required')
    run = tmp_path / 'run-live.sh'
    run.write_text('#!/bin/sh\n"$1"; r=$?; [ $r -ne 0 ] && touch %s/disabled; exit $r\n' % tmp_path)
    game = tmp_path / 'game'
    (tmp_path / 'enabled').write_text('')
    for f in (run,):
        f.chmod(0o755)
    block = '\n'.join(BT.S3_HOOK_LINES).replace('/usr/local/spikebt', str(tmp_path)).replace(
        '/dump/spikebt', str(tmp_path))
    for code, kept in ((0, False), (3, False), (1, False), (6, False), (4, True), (139, True)):
        game.write_text('#!/bin/sh\nexit %d\n' % code)
        game.chmod(0o755)
        (tmp_path / 'disabled').unlink(missing_ok=True)
        out = subprocess.run([sh, '-c', 'GAME=%s\n%s\necho "reason=$?"' % (game, block)], capture_output=True,
                             text=True)
        assert out.stdout.strip() == 'reason=%d' % code, (code, out)
        assert (tmp_path / 'disabled').exists() is kept, code
    (tmp_path / 'enabled').unlink()                                   # no plugin: the plain game, the same code
    game.write_text('#!/bin/sh\nexit 5\n')
    out = subprocess.run([sh, '-c', 'GAME=%s\n%s\necho "reason=$?"' % (game, block)], capture_output=True, text=True)
    assert out.stdout.strip() == 'reason=5'


def _s3_root(tmp_path):
    """A plain ext filesystem shaped like a Spike 3 system partition (the encryption is ssh_spike3's)."""
    image = build(tmp_path, extra={'etc/init.d/game_monitor': S3_STOCK.encode(),
                                   'etc/issue': b'Welcome to Stern Pinball Spike 3\n'})
    root = tmp_path / 'rootfs.img'
    root.write_bytes(image.read_bytes()[1 << 20:25 << 20])
    return root


def _s3_node(root, path):
    from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
    from pinball_decryptor.core import ssh_card
    with open(root, 'rb') as f:
        r = Ext4Reader(f, 0, root.stat().st_size)
        n = ssh_card._node(r, path)
        return n and dict(n, data=r.read_file_bytes(n) if n['mode'] & 0o100000 else None)


def test_spike3_takes_the_arm64_release_and_no_driver_and_gives_it_all_back(tmp_path, store, plugin):
    from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
    fake, blobs, sums = plugin
    P.install(fake, opener=Web({'v0.3.0': (blobs, sums)}))
    tag, members = P.files(fake, 'arm64')
    root = _s3_root(tmp_path)
    work = tmp_path / 'work'
    work.mkdir()
    BT.prepare_rootfs(root, work, True, members, tag, platform=BT.SPIKE3)
    with open(root, 'rb') as f:
        info = BT.inspect_root(Ext4Reader(f, 0, root.stat().st_size), BT.SPIKE3)
    assert info == dict(enabled=True, hooked=True, files=True, release='v0.3.0')
    for name, (data, mode) in members.items():
        got = _s3_node(root, BT.DIR + '/' + name)
        assert got['data'] == data and got['mode'] & 0o7777 == mode and got['uid'] == 0, name
    assert _s3_node(root, BT.DIR + '/btusb.ko') is None and _s3_node(root, BT.DIR + '/radio-start.sh') is None
    assert _s3_node(root, BT.WRAPPER) is None                        # Spike 3 has no other preload to carry
    mon = _s3_node(root, BT.MONITOR)
    assert mon['data'].decode() == BT.s3_monitor_text(S3_STOCK, True) and mon['mode'] & 0o7777 == 0o755
    BT.prepare_rootfs(root, work, False, platform=BT.SPIKE3)
    assert _s3_node(root, BT.DIR) is None and _s3_node(root, BT.MONITOR)['data'].decode() == S3_STOCK
    # a Spike 2 card's script on it, or a system that is not Spike 3's: left alone
    other = tmp_path / 'other'
    other.mkdir()
    plain = build(other, extra={'etc/init.d/game_monitor': STOCK.encode(), 'etc/issue': b'Stern Pinball Spike 3'})
    bad = other / 'rootfs.img'
    bad.write_bytes(plain.read_bytes()[1 << 20:25 << 20])
    with pytest.raises(ExtrasError, match='not one this app knows'):
        BT.prepare_rootfs(bad, work, True, members, tag, platform=BT.SPIKE3)


def test_a_spike3_build_puts_the_plugin_on_after_remote_access(tmp_path, monkeypatch):
    from pinball_decryptor.core import ssh_card
    from pinball_decryptor.plugins.stern import spike3, spike3_write as W
    source = tmp_path / 'source.raw'
    source.write_bytes(b'original')
    out = tmp_path / 'out.raw'
    project = tmp_path / 'project'
    project.mkdir()
    events = []
    monkeypatch.setattr(spike3, 'is_spike3_card', lambda path: True)
    monkeypatch.setattr(ssh_card, 'validate_request', lambda *a, **k: None)
    monkeypatch.setattr(ssh_card, 'validate_output', lambda *a, **k: None)
    monkeypatch.setattr(ssh_card, 'say_who_gets_in', lambda *a, **k: None)
    monkeypatch.setattr(ssh_card, 'note_build', lambda *a: events.append('noted'))
    monkeypatch.setattr(BT, 'validate_request', lambda original, assets, key_source=None: {'enabled': True})

    def write(*a, **kw):
        assert kw.get('allow_empty') is True                         # the plugin alone is a card to write
        events.append('engine')
        out.write_bytes(b'copied')
        return (0, 0, 0, 0)
    monkeypatch.setattr(W, 'write_card', write)

    def apply(original, output, config, log=None, cancel=None, key_source=None):
        events.append(('bluetooth', key_source))
        return BT.note(True, 'v0.3.0', BT.SPIKE3)
    monkeypatch.setattr(BT, 'apply_to_build', apply)
    pipe = W.Spike3WritePipeline(str(source), str(project), str(out), lambda *a: None, lambda *a: None,
                                 lambda *a: None, lambda ok, msg: events.append((ok, msg)), key_source='KEYS')
    pipe.run()
    assert events[:3] == ['engine', ('bluetooth', 'KEYS'), 'noted']
    ok, msg = events[-1]
    assert ok is True and msg.startswith('Wrote Bluetooth headphones to ')
    assert msg.endswith("It uses the machine's own Bluetooth radio.")
    assert not ssh_card.pending_marker(str(out)).exists()

    def fail(*a, **kw):
        raise ExtrasError('the key does not open this card')
    monkeypatch.setattr(BT, 'apply_to_build', fail)
    events.clear()
    pipe.run()
    assert events[-1] == (False, 'the key does not open this card')
    assert not out.exists() and Path(str(out) + '.ssh-incomplete').exists()
    # ticked on a card that cannot take it: stopped before anything is written
    monkeypatch.setattr(BT, 'validate_request',
                        lambda *a, **k: (_ for _ in ()).throw(ExtrasError(BT.NO_KEY)))
    events.clear()
    pipe.run()
    assert events == [(False, BT.NO_KEY)]
