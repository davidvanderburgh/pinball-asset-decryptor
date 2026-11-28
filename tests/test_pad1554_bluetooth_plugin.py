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

    def __init__(self, releases, source=None):
        self.releases, self.asked, self.source = releases, [], source

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
        if '/-/archive/' in url:
            if self.source is None:
                raise OSError('no source archive')
            return io.BytesIO(self.source)
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
    fake = P.Plugin(**dict(BT.PLUGIN.__dict__, pinned=pinned, tested='v0.3.0'))
    monkeypatch.setattr(BT, 'PLUGIN', fake)
    return fake, blobs, sums


# ------------------------------------------------------------------ the plugin and its store
def test_the_plugin_names_its_author_project_and_the_release_it_was_tested_with():
    p = BT.PLUGIN
    assert P.PLUGINS['bluetooth'] is p and p.project == 'https://gitlab.com/mattlqx/spike-pinball-bluetooth'
    # PAD-1647: the newest release proven with the app is the tested one; every one proven stays pinned
    assert p.author == 'mattlqx' and p.license == 'GPL-2.0' and p.tested == 'v0.4.4'
    assert p.tested == max(p.pinned, key=P.tag_key) and 'v0.3.0' in p.pinned
    for pin in p.pinned.values():
        assert set(pin) == {ARMV7, ARM64} and all(len(h) == 64 for h in pin.values())
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
        # PAD-1647: the newest release is the one offered first, tested with the app yet or not
        assert row['pick'] == 'v0.4.0' and row['newest'] == 'v0.4.0' and not row['update']
        assert not row['installed'] and row['offered'] and row['supported']
        assert [t['title'][:2] for t in row['guide']['sections']][:4] == ['1.', '2.', '3.', '4.']
        for sec in row['guide']['sections']:
            assert sec['steps'] and all((ROOT / 'pinball_decryptor/webui/static/img/plugins' / f).is_file()
                                        for f, _cap in sec['shots'])
        assert row['now'] == 'no Bluetooth headphones (as shipped)' and any(r[0] == 'To undo' for r in row['details'])
        # ticked before it is installed: said, in the words that tell the user what to do
        assert w.call('plugins.configure', 'bluetooth', True, str(project))
        assert card_extras.load_bluetooth(str(project)) == {'enabled': True}
        row = w.state('plugins')['plugins'][0]
        assert row['enabled'] and 'not installed on this computer' in row['hint']
        assert w.call('plugins.configure', 'bluetooth', True, str(tmp_path)) is False     # not this tab's project
        # install the tested version, then a newer one
        assert w.call('plugins.install', 'bluetooth', 'v0.3.0')
        row = _settle(w, lambda r: not r['busy'])
        assert row['installed'] == 'v0.3.0' and row['installed_tested'] and row['kind'] == 'ok' and not row['hint']
        assert row['update'] and row['newest'] == 'v0.4.0'           # a newer one is out: said, and offered
        assert P.installed(fake)['tag'] == 'v0.3.0' and (store / 'bluetooth' / 'installed.json').is_file()
        assert w.call('plugins.install', 'bluetooth', '')            # with no version named: the newest
        row = _settle(w, lambda r: not r['busy'])
        assert row['installed'] == 'v0.4.0' and not row['installed_tested'] and 'newer than this version' in row['note']
        assert not row['update']
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


# ------------------------------------------------------------------ which games the release knows
def source_archive(games2, games3):
    """The project's source tree as GitLab packs it: one top folder, the two places the game lists are."""
    files = {'spike-pinball-bluetooth-v0.3.0/README.md': b'# readme\n',
             'spike-pinball-bluetooth-v0.3.0/native/menu.c': b'int x;\n',
             'spike-pinball-bluetooth-v0.3.0/profiles/supported-games.json': json.dumps(
                 {'games': [{'id': 'g', 'title': t, 'version': '1', 'executable_sha256': h} for h, t in games2.items()]}
             ).encode()}
    for k, (h, t) in enumerate(games3.items()):
        files['spike-pinball-bluetooth-v0.3.0/profiles/spike3/g%d.json' % k] = json.dumps(
            {'title': t, 'version': '0.82.0', 'executable_sha256': h}).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue(), mtime=0)


def test_install_keeps_the_authors_list_of_games_and_only_that(store, plugin):
    fake, blobs, sums = plugin
    fake = P.Plugin(**dict(fake.__dict__, source_keep=BT.PLUGIN.source_keep))
    assert BT.PLUGIN.source_keep == ('profiles/supported-games.json', 'profiles/spike3/')
    assert P.source_url(fake, 'v0.3.0') == (
        'https://gitlab.com/mattlqx/spike-pinball-bluetooth/-/archive/v0.3.0/spike-pinball-bluetooth-v0.3.0.tar.gz')
    src = source_archive({'a' * 64: 'Godzilla Pro'}, {'b' * 64: 'Fallout LE'})
    P.install(fake, opener=Web({'v0.3.0': (blobs, sums)}, source=src))
    kept = P.source_texts(fake)
    assert sorted(kept) == ['profiles/spike3/g0.json', 'profiles/supported-games.json']    # no code, no readme
    # a list that cannot be fetched costs a sentence, never the install
    said = []
    rec = P.install(fake, log=said.append, opener=Web({'v0.3.0': (blobs, sums)}))
    assert rec['tag'] == 'v0.3.0' and P.source_texts(fake) == {}
    assert any('list of supported games could not be read' in line for line in said)
    assert said[-1] == 'Bluetooth headphones v0.3.0 installed.'


def test_the_card_is_told_whether_the_release_knows_its_game(tmp_path, store, plugin, monkeypatch):
    fake, blobs, sums = plugin
    fake = P.Plugin(**dict(fake.__dict__, source_keep=BT.PLUGIN.source_keep))
    monkeypatch.setattr(BT, 'PLUGIN', fake)
    assert BT.game_check(str(tmp_path / 'nothing.raw')) == {'known': None, 'text': ''}       # not installed
    game = b'\x7fELF the game program' * 100
    digest = hashlib.sha256(game).hexdigest()
    P.install(fake, opener=Web({'v0.3.0': (blobs, sums)},
                               source=source_archive({digest: 'Godzilla Pro - v1.16.0'}, {'c' * 64: 'Fallout LE'})))
    assert BT.known_games(BT.SPIKE2) == {digest: 'Godzilla Pro - v1.16.0'}
    assert BT.known_games(BT.SPIKE3) == {'c' * 64: 'Fallout LE 0.82.0'}
    monkeypatch.setattr(BT, 'game_program_sha256', lambda path, key_source=None: (BT.SPIKE2, digest))
    got = BT.game_check('card.raw')
    assert got['known'] is True and 'v0.3.0 knows: Godzilla Pro - v1.16.0.' in got['text']
    monkeypatch.setattr(BT, 'game_program_sha256', lambda path, key_source=None: (BT.SPIKE2, 'd' * 64))
    got = BT.game_check('card.raw')
    assert got['known'] is False and 'with no Bluetooth entry' in got['text'] and 'this app has changed' in got['text']

    def cannot(path, key_source=None):
        raise ExtrasError('a multi-boot card starts several')
    monkeypatch.setattr(BT, 'game_program_sha256', cannot)
    assert BT.game_check('card.raw') == {'known': None, 'text': ''}
    # installed without the list (from files, or the list could not be fetched): nothing is said either way
    P.install(fake, opener=Web({'v0.3.0': (blobs, sums)}))
    monkeypatch.setattr(BT, 'game_program_sha256', lambda path, key_source=None: (BT.SPIKE2, digest))
    assert BT.known_games(BT.SPIKE2) is None and BT.game_check('card.raw')['known'] is None


def test_a_spike2_cards_game_program_is_read_through_its_link(tmp_path):
    import struct as _struct
    import subprocess
    from tests.test_wifi_card import TOOLS
    import os as _os
    mk = shutil.which('mke2fs') or TOOLS + '/mke2fs'
    if not _os.path.exists(mk):
        pytest.skip('real filesystem tools required')
    image = _card(tmp_path)
    game = b'\x7fELF game ' * 5000
    tree = tmp_path / 'games'
    (tree / 'godzilla_pro').mkdir(parents=True)
    (tree / 'godzilla_pro' / 'game').write_bytes(game)
    (tree / 'game').symlink_to('godzilla_pro/game')
    fs = tmp_path / 'games.img'
    with fs.open('wb') as f:
        f.truncate(8 << 20)
    subprocess.run([mk, '-q', '-t', 'ext4', '-F', '-d', str(tree), str(fs)], check=True)
    data = bytearray(image.read_bytes()[:25 << 20])
    _struct.pack_into('<B3sB3sII', data, 478, 0, b'\0' * 3, 0x83, b'\0' * 3, (26 << 20) // 512, (8 << 20) // 512)
    card = tmp_path / 'both.raw'
    with card.open('wb') as f:
        f.write(data)
        f.seek(26 << 20)
        f.write(fs.read_bytes())
    assert BT.game_program_sha256(str(card)) == (BT.SPIKE2, hashlib.sha256(game).hexdigest())


# ------------------------------------------------------------------ on the machine
class Machine:
    """A machine over remote access: what its card and its own data hold."""

    def __init__(self, files, stuck=False):
        self.files, self.ran, self.stuck, self.closed = set(files), [], stuck, False

    def sh(self, script, timeout=20, check=True):
        self.ran.append(script)
        if script.startswith('rm -f '):
            if not self.stuck:
                self.files.discard(script[6:])
            return 0, ''
        out = []
        if BT.ENABLED in self.files:
            out.append('on-card')
        if BT.DISABLED in self.files:
            out.append('switched-off')
        out.append('release v0.3.0' if BT.RELEASE in self.files else 'release ')
        if 'helper' in self.files:
            out.append('helper-running')
        return 0, '\n'.join(out) + '\n'

    def close(self):
        self.closed = True


def test_a_plugin_that_switched_itself_off_is_switched_back_on_from_here():
    assert BT.parse_status('on-card\nswitched-off\nrelease v0.3.0\n') == dict(
        on_card=True, switched_off=True, release='v0.3.0', helper=False)
    assert BT.parse_status('release \n') == dict(on_card=False, switched_off=False, release='', helper=False)
    assert BT.parse_status('release ; rm -rf /\n')['release'] == ''
    assert 'has no Bluetooth headphones on it' in BT.check_machine(Machine([]))
    m = Machine([BT.ENABLED, BT.RELEASE, 'helper'])
    assert BT.check_machine(m) == 'spike-pinball-bluetooth v0.3.0 is on the machine and switched on, and its helper is running.'
    assert not any(x.startswith('rm') for x in m.ran)                # nothing is touched when nothing is wrong
    m = Machine([BT.ENABLED, BT.RELEASE, BT.DISABLED])
    said = BT.check_machine(m)
    assert 'had switched itself off after a game that ended badly; it is switched back on' in said
    assert 'rm -f /dump/spikebt/disabled' in m.ran and BT.DISABLED not in m.files
    with pytest.raises(ExtrasError, match='could not be taken away'):
        BT.check_machine(Machine([BT.ENABLED, BT.RELEASE, BT.DISABLED], stuck=True))


def test_the_plugins_tab_checks_the_machine_the_network_tab_knows(tmp_path, monkeypatch, store, plugin):
    from pinball_decryptor.core import pad_ssh_key, remote_send
    from tests.webui_harness import web_app
    fake, blobs, sums = plugin
    monkeypatch.setitem(P.PLUGINS, 'bluetooth', fake)
    monkeypatch.setattr(P.net, 'urlopen', Web({'v0.3.0': (blobs, sums)}))
    monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', tmp_path / 'keys')
    with web_app(tmp_path, mfr='stern') as w:
        w.window.current_mfr._era = 'spike2'
        svc = w.window.service('plugins')
        w.run(svc.on_show)
        _settle(w, lambda r: r['releases_state'] == 'ok')
        assert w.state('plugins')['plugins'][0]['address'] == '' and w.call('plugins.check_machine', 'bluetooth') is False
        w.call('network.set_address', '192.168.1.40')
        w.run(svc.publish)
        assert w.state('plugins')['plugins'][0]['address'] == '192.168.1.40'
        m = Machine([BT.ENABLED, BT.RELEASE, BT.DISABLED])
        monkeypatch.setattr(remote_send, 'connect', lambda address: m)
        assert w.call('plugins.check_machine', 'bluetooth')
        row = _settle(w, lambda r: not r['busy'] and r['note'])
        assert row['kind'] == 'ok' and 'it is switched back on' in row['note'] and m.closed

        def down(address):
            raise remote_send.SendError('Nothing answered at 192.168.1.40.')
        monkeypatch.setattr(remote_send, 'connect', down)
        assert w.call('plugins.check_machine', 'bluetooth')
        row = _settle(w, lambda r: not r['busy'] and r['kind'] == 'err')
        assert row['note'] == 'Nothing answered at 192.168.1.40.'


# ------------------------------------------------------------------ PAD-1643: straight onto the machine
class Live:
    """A running machine over remote access: its files (path -> [bytes, mode]), its links, and the shell words
    the app sends answered from them, as busybox would."""

    def __init__(self, files=None, arch='armv7l', links=None, free_kb=200000, spike3=False):
        self.files = {p: [d, 0o644] for p, d in (files or {}).items()}
        self.links, self.arch, self.free_kb, self.spike3 = dict(links or {}), arch, free_kb, spike3
        self.ran, self.rebooted, self.closed, self.rw, self.sftp = [], 0, False, False, self
        self.corrupt, self.refuse_rw, self.wrote_ro = '', False, []

    def _real(self, path):
        for _ in range(8):
            if path not in self.links:
                break
            path = self.links[path]
        return path

    def open(self, path, mode):
        m, path = self, self._real(path)
        if 'r' in mode:
            if path not in m.files:
                raise IOError(path)
            return io.BytesIO(m.files[path][0])

        class F:
            def __init__(s):
                s.buf = b''

            def write(s, data):
                s.buf += data

            def __enter__(s):
                return s

            def __exit__(s, *a):
                if not m.rw:
                    m.wrote_ro.append(path)
                m.files[path] = [s.buf + (b'!' if m.corrupt and path.startswith(m.corrupt) else b''), 0o600]
        return F()

    def sh(self, script, timeout=60, check=True):
        self.ran.append(script)
        words = script.replace("'", '').split()
        if script.startswith('echo "arch'):
            out = ['arch ' + self.arch] + (['spike3'] if self.spike3 else [])
            real = self._real(BT.MONITOR)
            if real in self.files:
                out.append('monitor ' + real)
            out += ['have ' + p for p in (B.MENU_SO, B.SO, B.MODE_SO, BT.WRAPPER, BT.S40, BT.S40_KEPT)
                    if p in self.files]
            if any(x.startswith('mkdir -p') and BT.S40_KEPT_DIR in x for x in self.ran) and not getattr(
                    self, 'kept_gone', False):
                out.append('keptdir %d' % sum(p.startswith(BT.S40_KEPT_DIR + '/') for p in self.files))
            inside = sorted(p for p in self.files if p.startswith(BT.DIR + '/'))
            if inside or getattr(self, 'empty_dir', False):
                out += ['dir'] + ['file ' + p.rsplit('/', 1)[1] for p in inside]
            out.append('free /dev/root 500000 300000 %d 60%% /' % self.free_kb)
            return 0, '\n'.join(out) + '\n'
        if script.startswith('p='):                         # network_apply._real: where a path's links lead
            real = self._real(words[0][2:].rstrip(';'))
            return 0, ('real %s\n' % real) if real in self.files else ''
        if script.startswith('sha1sum '):
            return 0, ''.join('%s  %s\n' % (hashlib.sha1(self.files[p][0]).hexdigest(), p)
                              for p in words[1:] if p in self.files)
        if 'remount,rw' in script:
            if self.refuse_rw:
                return 1, 'mount: permission denied\n'
            self.rw = True
            return 0, 'PAD_RW\n'
        if 'remount,ro' in script:
            self.rw = False
            return 0, ''
        if script.startswith('mkdir -p '):
            return 0, ''
        if 'PAD_PUT' in script:
            assert self.rw, 'the card was changed while it was read-only'
            for step in script.split(' && '):
                w = step.replace("'", '').split()
                if w[:1] == ['chmod']:
                    self.files[w[2]][1] = int(w[1], 8)
                elif w[:2] == ['mv', '-f']:
                    self.files[w[3]] = self.files.pop(w[2])
                elif w[:2] == ['rm', '-f']:
                    self.files.pop(w[2], None)
                elif w[:1] == ['rmdir']:
                    assert not [p for p in self.files if p.startswith(w[1] + '/')], 'rmdir of a folder with files'
                    if w[1] == BT.S40_KEPT_DIR:
                        self.kept_gone = True
            return 0, 'PAD_PUT\n'
        if script.startswith('rm -f '):
            for p in words[2:]:
                self.files.pop(p, None)
        return 0, ''

    def reboot(self):
        self.rebooted += 1

    def close(self):
        self.closed = True


def _on_computer(store, plugin, monkeypatch, source=None):
    fake, blobs, sums = plugin
    P.install(fake, 'v0.3.0', opener=Web({'v0.3.0': (blobs, sums)}, source=source))
    return fake


def test_the_plugin_goes_straight_onto_a_running_machine_and_comes_off_again(store, plugin, monkeypatch):
    fake = _on_computer(store, plugin, monkeypatch)
    tag, members = P.files(fake, 'armv7')
    game = b'\x7fELF the game'
    m = Live({BT.MONITOR: STOCK.encode(), '/games/godzilla/game': game, BT.DISABLED: b''},
             links={'/games/game': '/games/godzilla/game'})
    said = []
    res = BT.to_machine(m, True, log=said.append)
    assert (res['result'], res['platform'], res['tag']) == ('done', BT.SPIKE2, 'v0.3.0') and m.rebooted == 1
    # every file of the release as its archive holds it, the two of ours, the wrapper, and the block
    for name, (data, mode) in BT.card_files(members, tag).items():
        assert m.files[BT.DIR + '/' + name] == [data, mode], name
    assert m.files[BT.DIR + '/run-live.sh'][1] == 0o755 and m.files[BT.DIR + '/pad-release'][0] == b'v0.3.0\n'
    assert m.files[BT.WRAPPER] == [BT.WRAPPER_TEXT.encode(), 0o755]
    assert m.files[BT.MONITOR] == [B.monitor_text(STOCK, False, bluetooth=True).encode(), 0o755]
    assert B.has_block(m.files[BT.MONITOR][0], B.BT_HOOK_LINES)
    # written only while the card was open for writing, closed again after, nothing left on its way
    assert not m.wrote_ro and not m.rw and not [p for p in m.files if p.endswith(BT.NEW)]
    # the files went into place before the script that starts them
    put = next(s for s in m.ran if 'PAD_PUT' in s)
    assert put.index(BT.DIR + '/run-live.sh') < put.index("mv -f '%s%s'" % (BT.MONITOR, BT.NEW))
    # a launcher that had switched itself off is switched back on, and the progress was said
    assert BT.DISABLED not in m.files and any('file 3 of' in s for s in said) and said[-1] == 'Restarting the machine'
    assert 'is restarting' in BT.machine_said(res, True) and 'USB Bluetooth adapter' in BT.machine_said(res, True)
    # again: nothing to do, nothing written, no restart
    before = len(m.ran)
    res = BT.to_machine(m, True)
    assert res['result'] == 'already' and m.rebooted == 1 and not any('remount' in s for s in m.ran[before:])
    assert 'already has spike-pinball-bluetooth v0.3.0; nothing was changed' in BT.machine_said(res, True)
    assert BT.parse_status('on-card\nrelease v0.3.0\n')['on_card']
    # off: the script first, then every file, the folder and the wrapper; the game's own data is not touched
    m.files['/dump/spikebt/prefs'] = [b'paired', 0o644]
    res = BT.to_machine(m, False)
    assert res['result'] == 'done' and m.rebooted == 2
    assert m.files[BT.MONITOR] == [STOCK.encode(), 0o755] and '/dump/spikebt/prefs' in m.files
    assert not [p for p in m.files if p.startswith(BT.DIR + '/')] and BT.WRAPPER not in m.files
    off = [s for s in m.ran if 'PAD_PUT' in s][-1]
    assert off.index("mv -f '%s%s'" % (BT.MONITOR, BT.NEW)) < off.index('rm -f') and off.count('rmdir') == 1
    assert 'off the machine and it is restarting' in BT.machine_said(res, False)
    res = BT.to_machine(m, False)
    assert res['result'] == 'already' and m.rebooted == 2 and 'nothing was changed' in BT.machine_said(res, False)


def test_on_the_machine_the_other_preloads_and_a_linked_script_are_kept(store, plugin, monkeypatch):
    _on_computer(store, plugin, monkeypatch)
    # remote buttons and a boot menu on the card, and Stern's updater has left game_monitor a link (PAD-1619)
    real = '/spk/packages/spike-1.16.0/etc/init.d/game_monitor'
    script = B.monitor_text(STOCK, True, menu=True)
    m = Live({real: script.encode(), B.SO: b'so', B.MENU_SO: b'menu', B.MODE_SO: b'mode'}, links={BT.MONITOR: real})
    assert BT.to_machine(m, True)['result'] == 'done'
    assert m.links == {BT.MONITOR: real} and BT.MONITOR not in m.files          # the link stays; its file changed
    assert m.files[real][0].decode() == B.monitor_text(script, True, mode=True, menu=True, bluetooth=True)
    assert B.SO in m.files[real][0].decode() and B.BT_GAME in m.files[real][0].decode()
    assert BT.to_machine(m, False)['result'] == 'done'
    assert m.files[real][0].decode() == script and m.links == {BT.MONITOR: real}  # back to the buttons block
    # another release on the machine: its stray file goes, the changed ones are replaced, the same ones are not sent
    assert BT.to_machine(m, True, restart=False)['result'] == 'done' and m.rebooted == 2
    m.files[BT.DIR + '/old-helper'] = [b'old', 0o755]
    m.files[BT.DIR + '/menu.so'][0] = b'another release'
    m.files[BT.DIR + '/pad-release'][0] = b'v0.2.0\n'
    plan = BT.plan_machine(m, True)
    assert sorted(plan['puts']) == [BT.DIR + '/menu.so', BT.DIR + '/pad-release'] and plan['script'] is None
    assert plan['removes'] == [BT.DIR + '/old-helper']
    assert BT.to_machine(m, True)['result'] == 'done' and BT.DIR + '/old-helper' not in m.files
    # the Network tab's own direct route rewrites the link's file too, and keeps the Bluetooth block
    from pinball_decryptor.core import network_apply as A
    assert A._real(m, BT.MONITOR) == real and A._real(Live({BT.MONITOR: b'x'}), BT.MONITOR) == BT.MONITOR


def test_a_machine_that_cannot_take_it_is_left_exactly_as_it_was(store, plugin, monkeypatch):
    fake = _on_computer(store, plugin, monkeypatch)
    base = {BT.MONITOR: STOCK.encode()}

    def same(m):
        return {p: v[0] for p, v in m.files.items()} == base and m.rebooted == 0 and not m.rw

    for m, words in (
            (Live(base, arch='x86_64'), 'not a Stern Spike 2 or Spike 3 machine'),            # a JJP
            (Live(base, arch='aarch64'), 'not a Stern Spike 2 or Spike 3 machine'),           # arm64, not Stern's
            (Live({}), "This machine's game start-up script"),
            (Live({BT.MONITOR: b'#!/bin/sh\nexec /games/game\n'}), "This machine's game start-up script"),
            (Live(base, free_kb=100), 'MB free and Bluetooth headphones needs'),
    ):
        was = {p: v[0] for p, v in m.files.items()}
        with pytest.raises(ExtrasError, match=words):
            BT.to_machine(m, True)
        assert {p: v[0] for p, v in m.files.items()} == was and m.rebooted == 0 and not m.rw
    m = Live(base)
    m.refuse_rw = True
    with pytest.raises(ExtrasError, match='could not be opened for writing: mount: permission denied'):
        BT.to_machine(m, True)
    assert same(m)
    # a file that arrives changed: nothing is moved into place, what was sent is cleared away
    m = Live(base)
    m.corrupt = BT.DIR + '/spikebt'
    with pytest.raises(ExtrasError, match='spikebt did not arrive on the machine as sent; nothing was changed'):
        BT.to_machine(m, True)
    assert same(m)
    # the plugin is not on this computer: said, before the machine is touched
    P.remove(fake)
    m = Live(base)
    with pytest.raises(ExtrasError, match='is not installed'):
        BT.to_machine(m, True)
    assert same(m) and BT.to_machine(m, False)['result'] == 'already'              # off needs no release


def test_a_spike3_machine_takes_the_arm64_release_and_its_own_block(store, plugin, monkeypatch):
    fake = _on_computer(store, plugin, monkeypatch)
    tag, members = P.files(fake, 'arm64')
    m = Live({BT.MONITOR: S3_STOCK.encode()}, arch='aarch64', spike3=True)
    res = BT.to_machine(m, True)
    assert (res['result'], res['platform']) == ('done', BT.SPIKE3) and res['game'] == {'known': None, 'text': ''}
    assert m.files[BT.MONITOR][0].decode() == BT.s3_monitor_text(S3_STOCK, True)
    assert sorted(p.rsplit('/', 1)[1] for p in m.files if p.startswith(BT.DIR + '/')) == sorted(
        BT.card_files(members, tag))
    assert BT.WRAPPER not in m.files and BT.DIR + '/btusb.ko' not in m.files       # no wrapper, no driver
    assert "machine's own Bluetooth radio" in BT.machine_said(res, True)
    assert BT.to_machine(m, False)['result'] == 'done' and m.files[BT.MONITOR][0] == S3_STOCK.encode()


def test_the_machine_is_told_whether_the_release_knows_its_game(store, plugin, monkeypatch):
    game = b'\x7fELF the game'
    monkeypatch.setattr(BT, 'known_games', lambda platform: {hashlib.sha256(game).hexdigest(): 'Godzilla Premium 1.16.0'}
                        if platform == BT.SPIKE2 else None)
    _on_computer(store, plugin, monkeypatch)
    m = Live({BT.MONITOR: STOCK.encode(), '/games/gz/game': game}, links={'/games/game': '/games/gz/game'})
    res = BT.to_machine(m, True)
    assert res['game'] == {'known': True, 'text': "This machine's game is one spike-pinball-bluetooth v0.3.0 "
                                                  'knows: Godzilla Premium 1.16.0.'}
    m.files['/games/gz/game'][0] = game + b' changed by a build'
    res = BT.to_machine(m, True)
    assert res['result'] == 'already' and res['game']['known'] is False
    assert 'with no Bluetooth entry' in BT.machine_said(res, True)
    del m.files['/games/gz/game']                       # it cannot be read: nothing is said either way
    assert BT.to_machine(m, True)['game'] == {'known': None, 'text': ''}


def test_the_plugins_tab_puts_it_on_the_machine_and_takes_it_off(tmp_path, monkeypatch, store, plugin):
    from pinball_decryptor.core import pad_ssh_key, remote_send
    from tests.webui_harness import web_app
    fake, blobs, sums = plugin
    monkeypatch.setitem(P.PLUGINS, 'bluetooth', fake)
    monkeypatch.setattr(P.net, 'urlopen', Web({'v0.3.0': (blobs, sums)}))
    monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', tmp_path / 'keys')
    js = (ROOT / 'pinball_decryptor/webui/static/js/tabs/plugins.js').read_text(encoding='utf-8')
    for words in ('plugins.put_on_machine', 'plugins.take_off_machine', 'Put it on the machine now',
                  'Take it off the machine', 'On your machine'):
        assert words in js, words
    assert any(r[0] == 'Straight onto the machine' for r in BT.details(BT.SPIKE2))
    assert any(r[0] == 'Straight onto the machine' for r in BT.details(BT.SPIKE3))
    with web_app(tmp_path, mfr='stern') as w:
        w.window.current_mfr._era = 'spike2'
        svc = w.window.service('plugins')
        project = tmp_path / 'project'
        project.mkdir()
        w.window.write_assets_var.set(str(project))
        w.run(svc.on_show)
        _settle(w, lambda r: r['releases_state'] == 'ok')
        m = Live({BT.MONITOR: STOCK.encode()})
        monkeypatch.setattr(remote_send, 'connect', lambda address: m)
        assert w.call('plugins.put_on_machine', 'bluetooth') is False              # no machine known yet
        w.call('network.set_address', '192.168.1.40')
        w.run(svc.publish)
        # not installed on this computer: said, nothing asked, the machine not touched
        assert w.call('plugins.put_on_machine', 'bluetooth') is False
        row = w.state('plugins')['plugins'][0]
        assert row['kind'] == 'err' and 'on this computer first' in row['note'] and not m.ran
        assert w.call('plugins.install', 'bluetooth', 'v0.3.0')
        _settle(w, lambda r: not r['busy'] and r['installed'] == 'v0.3.0')
        # not without a yes
        w.answers.append('no')
        assert w.call('plugins.put_on_machine', 'bluetooth') is False and not m.ran
        assert 'restarts' in w.asked[-1]['message'] and '192.168.1.40' in w.asked[-1]['message']
        assert 'v0.3.0' in w.asked[-1]['message']
        w.answers.append('yes')
        assert w.call('plugins.put_on_machine', 'bluetooth')
        row = _settle(w, lambda r: not r['busy'] and r['note'])
        assert row['kind'] == 'ok' and 'The machine has spike-pinball-bluetooth v0.3.0 now and is restarting' in row['note']
        assert m.rebooted == 1 and m.closed and BT.DIR + '/menu.so' in m.files
        # the project follows, so the next card written from it carries the plugin too
        assert card_extras.load_bluetooth(str(project)) == {'enabled': True} and row['enabled']
        assert 'This project is ticked for it now' in row['note']
        w.answers.append('yes')
        assert w.call('plugins.take_off_machine', 'bluetooth')
        row = _settle(w, lambda r: not r['busy'] and 'off the machine' in r['note'])
        assert row['kind'] == 'ok' and m.rebooted == 2 and BT.DIR + '/menu.so' not in m.files
        assert card_extras.load_bluetooth(str(project)) == {'enabled': False} and not row['enabled']
        # a machine that cannot take it: its reason, in red
        monkeypatch.setattr(remote_send, 'connect', lambda address: Live({BT.MONITOR: STOCK.encode()}, arch='x86_64'))
        w.answers.append('yes')
        assert w.call('plugins.put_on_machine', 'bluetooth')
        row = _settle(w, lambda r: not r['busy'] and r['kind'] == 'err')
        assert row['note'] == BT.NOT_A_MACHINE


# ------------------------------------------------------------------ PAD-1647: the newest release, v0.4.4
KEEP_INSTALLER = b"""#!/bin/sh
marker=spikebt-owned-bond-retention
original='if grep -q "Trusted=true" "info"; then'
replacement='if grep -q "Trusted=true" "info" || /usr/local/spikebt/spikebt --keep="$PWD" 2>/dev/null; then # spikebt-owned-bond-retention'
"""
S40_STOCK = ('#!/bin/sh\ncase "$1" in\n  start)\n\tfor d in /var/lib/bluetooth/*/*; do\n\t\tcd "$d"\n'
             '\t\t\tif grep -q "Trusted=true" "info"; then\n\t\t\t\ttrue\n\t\t\telse\n\t\t\t\trm -rf "$d"\n'
             '\t\t\tfi\n\tdone\n\t;;\nesac\n')


def test_a_busy_gitlab_says_when_to_try_again(store, plugin):
    """gitlab.com allows a computer that is not signed in so many requests an hour: its 429 is said in words,
    with the wait it names, and nothing is installed."""
    import urllib.error
    fake, _blobs, _sums = plugin

    def busy(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, 'Too Many Requests', {'Retry-After': '1876'}, None)
    with pytest.raises(PluginError) as e:
        P.install(fake, opener=busy)
    said = str(e.value)
    assert 'asking this computer to wait' in said and '(about 32 minutes)' in said and 'Install from files' in said
    assert '429' not in said and P.installed(fake) is None
    with pytest.raises(PluginError, match='asking this computer to wait before'):
        P.releases(fake, opener=lambda req, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(req.full_url, 429, 'Too Many Requests', {}, None)))
    with pytest.raises(PluginError, match='Could not download'):       # any other answer: as before
        P.install(fake, opener=lambda req, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(req.full_url, 404, 'Not Found', {}, None)))


def test_from_v0_4_a_game_its_author_does_not_list_is_not_said_to_lose_the_entry(store, plugin, monkeypatch):
    """v0.4.0 on, the menu finds what it needs in the game when the game starts: a program that is not on its
    author's list (one this app changed) is no longer told it will have no Bluetooth entry."""
    assert not BT.finds_games('v0.3.1') and BT.finds_games('v0.4.0') and BT.finds_games('v0.4.4')
    assert not BT.finds_games('') and not BT.finds_games('nightly')
    old = BT._not_listed("This card's", 'v0.3.0', 61)
    assert old['known'] is False and 'with no Bluetooth entry' in old['text']
    new = BT._not_listed("This card's", 'v0.4.4', 61)
    assert new['known'] is None and 'no Bluetooth entry' not in new['text']
    assert 'looks for what it needs in the game each time the game starts' in new['text'] and '61' in new['text']
    monkeypatch.setattr(P, 'installed', lambda plugin: {'tag': 'v0.4.4', 'tested': True, 'files': {}})
    monkeypatch.setattr(BT, 'game_program_sha256', lambda path, key_source=None: (BT.SPIKE2, 'f' * 64))
    monkeypatch.setattr(BT, 'known_games', lambda platform: {'a' * 64: 'Godzilla Pro'})
    assert BT.game_check('card.raw') == BT._not_listed("This card's", 'v0.4.4', 1)
    monkeypatch.setattr(BT, 'known_games', lambda platform: {'f' * 64: 'Godzilla Pro'})
    assert BT.game_check('card.raw')['known'] is True


def test_the_saved_pairings_line_is_changed_as_the_releases_own_installer_says():
    rule = BT.keep_bonds_rule(KEEP_INSTALLER)
    assert rule[0] == 'if grep -q "Trusted=true" "info"; then' and rule[1].endswith('# ' + BT.KEEP_MARK)
    # an installer this app does not read: nothing is done
    assert BT.keep_bonds_rule(b'#!/bin/sh\necho hello\n') is None and BT.keep_bonds_rule(None) is None
    assert BT.keep_bonds_rule(KEEP_INSTALLER.replace(b'# spikebt-owned', b'# other')) is None
    assert BT.keep_bonds_rule(KEEP_INSTALLER + b"original='again'\n") is None
    assert BT.keep_bonds_rule(KEEP_INSTALLER.replace(b'replacement=\'if grep', b'replacement=\'rm -rf /; if grep')) is None
    new = BT.s3_keep_bonds_text(S40_STOCK, rule)
    assert new.count(BT.KEEP_MARK) == 1 and '\t\t\t' + rule[1] + '\n' in new          # its indent kept
    assert new.replace('\t\t\t' + rule[1], '\t\t\t' + rule[0]) == S40_STOCK          # nothing else changed
    assert BT.s3_keep_bonds_text(new, rule) is None                                     # already made
    assert BT.s3_keep_bonds_text(S40_STOCK.replace('Trusted=true', 'Trusted=yes'), rule) is None   # not the script
    assert BT.s3_keep_bonds_text(S40_STOCK + S40_STOCK, rule) is None                   # two such lines
    assert BT.s3_keep_bonds_text(S40_STOCK, None) is None
    assert BT.s3_forget_bonds_text(new, S40_STOCK) == S40_STOCK and BT.s3_forget_bonds_text(new) == S40_STOCK
    assert BT.s3_forget_bonds_text(new, new) == S40_STOCK              # a copy that is itself changed is not used
    assert BT.s3_forget_bonds_text(S40_STOCK) is None


def _keep_release():
    """A made-up release whose arm64 archive carries the saved-pairings installer, as v0.4.4's does."""
    common = {'menu.so': b'\x7fELF menu keep', 'spikebt': b'\x7fELF helper ' + b'keep' * 4000,
              'run-live.sh': b'#!/bin/sh\n# launcher\n', 'rollback.sh': b'#!/bin/sh\n',
              'LICENSE': b'GPL 2\n', 'NOTICE.md': b'notice\n'}
    blobs = {ARMV7: archive(dict(common, **{'radio-start.sh': b'#!/bin/sh\n# radio\n', 'btusb.ko': b'ko'})),
             ARM64: archive(dict(common, **{BT.KEEP_SCRIPT: KEEP_INSTALLER}))}
    sums = ''.join('%s  %s\n' % (hashlib.sha256(d).hexdigest(), n) for n, d in blobs.items()).encode()
    return blobs, sums


def test_a_spike3_card_keeps_its_pairings_and_gives_the_script_back(tmp_path, store, plugin):
    from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
    fake, _blobs, _sums = plugin
    blobs, sums = _keep_release()
    P.install(fake, 'v0.4.4', opener=Web({'v0.4.4': (blobs, sums)}))
    tag, members = P.files(fake, 'arm64')
    image = build(tmp_path, extra={'etc/init.d/game_monitor': S3_STOCK.encode(),
                                   'etc/issue': b'Welcome to Stern Pinball Spike 3\n',
                                   'etc/init.d/S40bluetoothd': S40_STOCK.encode()})
    root = tmp_path / 'rootfs.img'
    root.write_bytes(image.read_bytes()[1 << 20:25 << 20])
    work = tmp_path / 'work'
    work.mkdir()

    def info():
        with open(root, 'rb') as f:
            return BT.inspect_root(Ext4Reader(f, 0, root.stat().st_size), BT.SPIKE3)
    before_mode = _s3_node(root, BT.S40)['mode'] & 0o7777
    BT.prepare_rootfs(root, work, True, members, tag, platform=BT.SPIKE3)
    assert info() == dict(enabled=True, hooked=True, files=True, release='v0.4.4')
    want = BT.s3_keep_bonds_text(S40_STOCK, BT.keep_bonds_rule(KEEP_INSTALLER)).encode()
    got = _s3_node(root, BT.S40)
    assert got['data'] == want and got['mode'] & 0o7777 == before_mode and got['uid'] == 0
    kept = _s3_node(root, BT.S40_KEPT)
    assert kept['data'] == S40_STOCK.encode() and _s3_node(root, BT.S40_KEPT_DIR)['mode'] & 0o7777 == 0o700
    BT.prepare_rootfs(root, work, True, members, tag, platform=BT.SPIKE3)          # again: nothing to do
    assert _s3_node(root, BT.S40)['data'] == want and _s3_node(root, BT.S40_KEPT)['data'] == S40_STOCK.encode()
    # a card with the release on it and the line not changed is not the whole install: a build finishes it
    with open(root, 'rb') as f:
        r = Ext4Reader(f, 0, root.stat().st_size)
        assert BT.keep_bonds_state(r)['state'] == 'done'
    BT.prepare_rootfs(root, work, False, platform=BT.SPIKE3)
    assert _s3_node(root, BT.S40)['data'] == S40_STOCK.encode() and _s3_node(root, BT.S40_KEPT_DIR) is None
    assert _s3_node(root, BT.DIR) is None and info() == dict(enabled=False, hooked=False, files=False, release='')


def test_a_spike3_machine_keeps_its_pairings_over_remote_access(store, plugin, monkeypatch):
    fake, _blobs, _sums = plugin
    blobs, sums = _keep_release()
    monkeypatch.setattr(P.net, 'urlopen', Web({'v0.4.4': (blobs, sums)}))
    P.install(fake, 'v0.4.4')
    m = Live({BT.MONITOR: S3_STOCK.encode(), BT.S40: S40_STOCK.encode()}, arch='aarch64', spike3=True)
    res = BT.to_machine(m, True)
    assert (res['result'], res['tag']) == ('done', 'v0.4.4')
    want = BT.s3_keep_bonds_text(S40_STOCK, BT.keep_bonds_rule(KEEP_INSTALLER)).encode()
    assert m.files[BT.S40] == [want, 0o755] and m.files[BT.S40_KEPT][0] == S40_STOCK.encode()
    assert any(x.startswith('mkdir -p') and BT.S40_KEPT_DIR in x and 'chmod 700' in x for x in m.ran)
    assert not m.wrote_ro and BT.to_machine(m, True)['result'] == 'already'
    assert BT.to_machine(m, False)['result'] == 'done'
    assert m.files[BT.S40][0] == S40_STOCK.encode() and BT.S40_KEPT not in m.files
    assert any('rmdir' in x and BT.S40_KEPT_DIR in x for x in m.ran)
    assert BT.to_machine(m, False)['result'] == 'already'
    # a script that is not the one the installer takes is left alone, and the plugin still goes on
    other = S40_STOCK.replace('Trusted=true', 'Trusted=yes').encode()
    m = Live({BT.MONITOR: S3_STOCK.encode(), BT.S40: other}, arch='aarch64', spike3=True)
    assert BT.to_machine(m, True)['result'] == 'done' and m.files[BT.S40][0] == other and BT.S40_KEPT not in m.files


def test_the_list_of_versions_is_kept_so_gitlab_is_not_asked_each_time(store, plugin):
    fake, blobs, sums = plugin
    assert P.kept_releases(fake) == ([], False)
    rows = P.releases(fake, opener=Web({'v0.3.0': (blobs, sums), 'v0.4.0': release(b'two')}))
    P.keep_releases(fake, rows, now=1000)
    assert P.kept_releases(fake, now=1000 + 60) == (rows, True)                  # recent: not asked again
    assert P.kept_releases(fake, now=1000 + P.RELEASES_FRESH + 1) == (rows, False)   # old: asked, and still shown
    assert not (store / 'bluetooth').exists() and (store / 'bluetooth.releases.json').is_file()
    P.install(fake, opener=Web({'v0.3.0': (blobs, sums)}))                       # an install does not lose it
    assert P.kept_releases(fake, now=1000)[0] == rows
    (store / 'bluetooth.releases.json').write_text('{"at": 1, "rows": [{"tag": "; rm", "title": "", "date": ""}]}')
    assert P.kept_releases(fake) == ([], False)                                  # not one this app wrote
