"""Plugins: optional add-ons made by other people, installed from their own project (PAD-1554).

David: "maybe a new Plugins tab, where the user can choose optional plugins to install.  they need to persist
between PAD updates too."  The first is mattlqx's Bluetooth headphones, whose author asked that the app pull his
releases at a version tag rather than carry his code.

One card a plugin, in two halves:

* **On this computer**: which release is installed, the versions its author has published, newest first and
  offered first (PAD-1647; the ones this version of the app was tested with are marked), Install / Update,
  Install from files for a computer that cannot reach
  gitlab.com, and Remove.  The store is ``core/card_plugins.py``: the settings folder, so an app update keeps it.
* **On your cards**: the project's tick, which a build acts on (``core/bluetooth_card.py``), what the picked card
  carries now, and exactly what it changes.

Downloads run on a worker and say how far they are; nothing of a plugin runs on this computer.
"""
import os
import threading

from .base import TabService, rpc
from .. import compat
from ...core import bluetooth_card, card_extras, card_plugins

INTRO = ('Optional add-ons made by other people. A plugin is downloaded from its author\'s own project, at the '
         'version you pick, and kept on this computer beside your settings, so updating this app leaves it '
         'installed. Tick one for a project and the cards you write from it carry it.')

#: PAD-1647 (David: "i want to see some instructions / screenshots of how the bluetooth feature works. otherwise,
#: I have to go to the repo page to understand it better"): how the plugin is used on the machine, in the tab.
#: Sections of steps, each with the pictures that show them (static/img/plugins/, taken from the game in the
#: emulator with the plugin's own demo headphones, which is why they are fictional).
BLUETOOTH_GUIDE = dict(
    title='How it works on the machine',
    lead="Everything is done in the game's own menus on the machine. Nothing is paired from this computer.",
    shots_note='Pictures: Godzilla with the plugin in this app\'s emulator. The headphones in them are made up.',
    sections=[
        dict(title='1. Get it onto the machine', steps=[
            'Install it here (On this computer), then tick it for your project and write the card, or use Put it '
            'on the machine now when remote access is set up.',
            'Spike 2: plug a USB Bluetooth adapter into the machine. Its author tested the StarTech USBBT2EDR4 '
            'and USBBT1EDR4. Spike 3 uses its own radio.',
        ], shots=[]),
        dict(title='2. Pair your headphones (coin door buttons)', steps=[
            'Open the coin door and press Select to enter Service. The main menu has a new last row, Bluetooth.',
            'Make the headphones ready to pair (their manual says how) and choose Search for headphones.',
            'Pick them in the list: they pair and connect, and the game sound plays in them.',
            'Headphones connected here stay connected while you play. After you leave the menu they disconnect '
            'once they have been idle for two minutes.',
        ], shots=[('bt-service-row.jpg', 'Service: Bluetooth is the last row of the main menu'),
                  ('bt-service-menu.jpg', 'The Bluetooth menu in Service'),
                  ('bt-search.jpg', 'Search for headphones')]),
        dict(title='3. Use them as a player (no coin door)', steps=[
            'At home, once: in Service, Bluetooth, turn on Unauthenticated headphones. It is off until you do.',
            'Then, with no game running, hold the left flipper button: the game selection opens and Bluetooth '
            'is its last choice (from the first choice, Left wraps round to it).',
            'With Insider Connected: hold the left flipper, sign in with your code, and choose Bluetooth. Your '
            'preferred headphones reconnect when you sign in and disconnect when you sign out.',
            'Flippers move, Action selects (both flippers on a game with no Action button), hold it to go back. '
            'Start leaves the menu and starts a game. The menu closes by itself after 60 seconds.',
        ], shots=[('bt-player-entry.jpg', 'Hold the left flipper: Bluetooth is the last choice'),
                  ('bt-player-menu.jpg', 'The Bluetooth menu a player sees')]),
        dict(title='4. Volume and the cabinet speakers', steps=[
            'Open a saved headphone to connect, disconnect, forget it, make it preferred or set its volume. '
            'Each headset has its own volume.',
            'Cabinet speakers: On plays through the speakers too, Off mutes them, Auto mutes them while '
            'headphones are playing.',
            'Cabinet volume in Service sets the game\'s own volume; a player can turn it down from there unless '
            'Allow player cabinet volume adjust is No.',
        ], shots=[('bt-device.jpg', 'A saved headphone: volume, Disconnect, Forget'),
                  ('bt-volume.jpg', 'Its volume')]),
        dict(title='Good to know', steps=[
            'Up to four headsets at once, eight saved for each account. Headsets that ask for a PIN do not work.',
            'Bluetooth adds a short delay to the sound. If the helper stops, the game goes back to its speakers.',
            'Paired headphones and their settings are kept on the machine, so a new card keeps them.',
            'If the Bluetooth row is missing after the game crashed, the plugin has switched itself off: Check '
            'it on the machine (here, with remote access) switches it back on.',
        ], shots=[]),
    ])

#: plugin key -> its card side: the module that puts it on a card, the project's choice, and the tick's words
CARDS = {
    'bluetooth': dict(card=bluetooth_card, load=card_extras.load_bluetooth, save=card_extras.save_bluetooth,
                      tick='Put Bluetooth headphones on cards I write from this project',
                      guide=BLUETOOTH_GUIDE,
                      needs={bluetooth_card.SPIKE2: 'A Spike 2 machine needs a USB Bluetooth adapter plugged '
                             'in. It works on the game versions its author lists; on any other the game '
                             'runs as Stern shipped it.',
                             bluetooth_card.SPIKE3: 'A Spike 3 machine uses its own Bluetooth radio. It works '
                             'on the game versions its author lists; on any other the game runs as Stern '
                             'shipped it.'}),
}


def offered(mfr):
    """Whether any plugin could go on *mfr*'s cards: the tab is on the rail only then."""
    return any(side['card'].offered(mfr) for side in CARDS.values())


class PluginsTab(TabService):

    def __init__(self, window):
        super().__init__(window)
        self._busy = {}                 # key -> what is running ('' when idle)
        self._said = {}                 # key -> (text, kind)
        self._releases = {}             # key -> (state, rows): '' not asked, 'loading', 'ok', or the error
        self._pick = {}                 # key -> the version chosen in the list
        self._games = {}                # (key, card, its size and time, release) -> game_check's answer
        self._games_busy = set()
        self.set(intro=INTRO, project='', running=False, plugins=[], store=card_plugins.store_root())

    def rail_needs(self):
        return 'none'                   # installing a plugin needs no project; only its tick does

    def _project(self):
        return self.window.write_assets_var.get().strip()

    def _source(self):
        return self.window.write_upd_var.get().strip()

    # ------------------------------------------------------------------ state
    def _row(self, plugin, project):
        side = CARDS[plugin.key]
        card = side['card']
        rec = card_plugins.installed(plugin)
        state, rows = self._releases.get(plugin.key, ('', []))
        if not rows:
            # before the author's list is asked for (or when it cannot be): the release the app was tested with
            rows = [{'tag': plugin.tested, 'title': plugin.tested, 'date': '', 'tested': True}]
        tags = [r['tag'] for r in rows]
        # PAD-1647 (David: "we should always promote the latest version"): the newest release its author has
        # published is the one offered first, tested with this app yet or not (the list says which)
        newest = max(tags, key=card_plugins.tag_key)
        pick = self._pick.get(plugin.key)
        if pick not in tags:
            pick = newest
        can = card.offered(self.mfr)
        platform = card.platform_of(self.mfr) or card.SPIKE2
        if not can:
            info = dict(supported=False, reason=card.NOT_SPIKE2, enabled=False)
        elif not self._source():
            info = dict(supported=True, reason='', enabled=False, unpicked=True)
        else:
            info = card.inspect_image(self._source())
        on, error = False, ''
        has_project = os.path.isdir(project or '')
        try:
            choice = side['load'](project) if has_project else None
            on = bool(choice and choice['enabled'])
        except card_extras.ExtrasError as e:
            error = str(e)
        hint = ''
        if not has_project:
            hint = 'Open a project to tick this: a card gets the plugin when it is written from a project.'
        elif on and rec is None:
            hint = ('This project asks for the plugin, and it is not installed on this computer: install it '
                    'above, or a card cannot be written.')
        elif info.get('unpicked'):
            hint = 'No card image is picked yet: the card is checked when it is written.'
        text, kind = self._said.get(plugin.key, ('', ''))
        game = self._game(plugin, card, rec) if can and info['supported'] and not info.get('unpicked') else {}
        return {
            'game_note': game.get('text', ''), 'game_kind': {True: 'ok', False: 'warn'}.get(game.get('known'), ''),
            'address': self._address(),
            'key': plugin.key, 'name': plugin.name, 'what': plugin.what, 'author': plugin.author,
            'project_url': plugin.project, 'license': plugin.license, 'tested': plugin.tested,
            'installed': rec['tag'] if rec else '', 'installed_tested': bool(rec and rec['tested']),
            'releases': rows, 'releases_state': state, 'pick': pick, 'newest': newest,
            'update': bool(rec and card_plugins.tag_key(newest) > card_plugins.tag_key(rec['tag'])),
            'guide': side.get('guide') or {},
            'busy': self._busy.get(plugin.key, ''), 'note': text, 'kind': kind,
            'offered': can, 'supported': bool(info['supported']), 'reason': info['reason'],
            'enabled': on, 'has_project': has_project, 'hint': hint, 'error': error,
            'tick': side['tick'], 'needs': side['needs'][platform],
            'details': [list(r) for r in card.details(platform)],
            'now': '' if info.get('unpicked') or not info['supported'] else card.describe(info),
        }

    def _game(self, plugin, card, rec):
        """Whether the installed release knows the picked card's game program: read on a worker (a game program
        is tens of MB, a Spike 3 one is decrypted first) and kept until the card or the release changes."""
        source = self._source()
        if rec is None or not hasattr(card, 'game_check'):
            return {}
        try:
            st = os.stat(source)
        except OSError:
            return {}
        key = (plugin.key, source, st.st_size, st.st_mtime_ns, rec['tag'])
        if key in self._games:
            return self._games[key]
        if key not in self._games_busy:
            self._games_busy.add(key)

            def work():
                try:
                    got = card.game_check(source)
                except Exception:                           # noqa: BLE001 - never raised into the UI
                    got = {'known': None, 'text': ''}

                def done():
                    self._games_busy.discard(key)
                    self._games[key] = got
                    self.publish()
                self.ctx.loop.post(done)
            threading.Thread(target=work, daemon=True, name='pad-plugin-game').start()
        return {}

    def _address(self):
        """The machine the Network tab knows ('' when none): where "Check it on the machine" asks."""
        network = self.window.service('network')
        try:
            return (network.get('address') or '') if network is not None else ''
        except Exception:                                   # noqa: BLE001
            return ''

    @rpc
    def check_machine(self, key):
        """Ask the machine (over remote access) whether the plugin is on it and switched on; its launcher
        switches itself off after a game that ended badly, and this switches it back on."""
        plugin = self._plugin(key)
        address = self._address()
        card = CARDS[key]['card'] if plugin is not None else None
        if plugin is None or not address or not hasattr(card, 'check_machine'):
            return False

        def work(say):
            from ...core import remote_send
            try:
                machine = remote_send.connect(address)
            except remote_send.SendError as e:
                raise card_plugins.PluginError(str(e)) from None
            try:
                return card.check_machine(machine)
            except (card_extras.ExtrasError, remote_send.SendError) as e:
                raise card_plugins.PluginError(str(e)) from None
            finally:
                machine.close()
        return self._start(key, 'Asking the machine at %s' % address, work, lambda text: text)

    def _to_machine(self, key, on):
        """PAD-1643: put plugin *key* on the machine the Network tab knows, or take it off, over remote access:
        no card is written.  The machine restarts, so it is asked first."""
        plugin = self._plugin(key)
        address = self._address()
        card = CARDS[key]['card'] if plugin is not None else None
        if plugin is None or not address or not hasattr(card, 'to_machine') or self._busy.get(key) \
                or self.get('running'):
            return False
        if on and card_plugins.installed(plugin) is None:
            self._said[key] = ('Install %s on this computer first (the Install button on the left): the machine '
                               'gets the version installed here.' % plugin.name, 'err')
            self.publish()
            return False
        title = 'Put it on the machine now' if on else 'Take it off the machine'
        ask = ('Put %s %s on the machine at %s now?' % (plugin.name, card_plugins.installed(plugin)['tag'], address)
               if on else 'Take %s off the machine at %s now?' % (plugin.name, address))
        if not compat.messagebox.askyesno(
                title, ask + "\n\nOnly the machine's system files change: the game, its settings and high scores "
                'stay as they are. The machine restarts when it is done (about a minute), so a game being played '
                'ends.', icon='warning'):
            return False
        project = self._project()
        try:
            choice = CARDS[key]['load'](project) if os.path.isdir(project or '') else None
        except card_extras.ExtrasError:
            choice = None
        ticked = bool(choice and choice['enabled'])

        def work(say):
            from ...core import remote_send
            try:
                machine = remote_send.connect(address)
            except remote_send.SendError as e:
                raise card_plugins.PluginError(str(e)) from None
            try:
                text = card.machine_said(card.to_machine(machine, on, log=say), on)
            except (card_extras.ExtrasError, remote_send.SendError) as e:
                raise card_plugins.PluginError(str(e)) from None
            except (OSError, EOFError) as e:
                raise card_plugins.PluginError('The connection to the machine at %s was lost (%s). Check it on '
                                               'the machine, then try again.' % (address, e)) from None
            finally:
                machine.close()
            # the project follows the machine, as Turn on remote buttons does: the next card written or sent from
            # it must not undo what was just done
            if os.path.isdir(project or '') and ticked != on and project == self._project():
                try:
                    CARDS[key]['save'](project, on)
                    text += (' This project is ticked for it now, so a card written from it carries it too.' if on
                             else ' This project is unticked for it now, so a card written from it leaves it off.')
                except card_extras.ExtrasError:
                    text += (' This project could not be ticked for it: tick it above, or a card written from '
                             'this project will not carry it.' if on else '')
            return text
        return self._start(key, ('Putting %s on the machine at %s' if on else 'Taking %s off the machine at %s')
                           % (plugin.name, address), work, lambda text: text)

    @rpc
    def put_on_machine(self, key):
        """Put the installed release on the machine over remote access, with no card to write (asked first)."""
        return self._to_machine(key, True)

    @rpc
    def take_off_machine(self, key):
        """Take the plugin off the machine over remote access (asked first)."""
        return self._to_machine(key, False)

    def publish(self):
        project = self._project()
        self.set(project=project, store=card_plugins.store_root(),
                 plugins=[self._row(p, project) for p in card_plugins.PLUGINS.values() if p.key in CARDS])

    def _plugin(self, key):
        plugin = card_plugins.PLUGINS.get(key)
        return plugin if plugin is not None and key in CARDS else None

    def on_show(self):
        for key in CARDS:
            if not self._releases.get(key, ('',))[0]:
                # the list read last time, when it is recent: gitlab.com is not asked again each time the app
                # starts (it allows a set number of requests an hour); Check for versions always asks
                rows, fresh = card_plugins.kept_releases(card_plugins.PLUGINS[key])
                if fresh:
                    self._releases[key] = ('ok', rows)
                else:
                    self.refresh_releases(key)
        self.publish()

    def on_project(self, folder):
        self.publish()

    def on_manufacturer(self, mfr):
        self.publish()

    def refresh_after_revert(self):
        self.publish()

    def on_running(self, running, mode):
        self.set(running=bool(running))

    # ------------------------------------------------------------------ the author's releases
    @rpc
    def refresh_releases(self, key):
        """Ask the author's project which versions it has published (a worker; the list says when it cannot)."""
        plugin = self._plugin(key)
        if plugin is None or self._releases.get(key, ('',))[0] == 'loading':
            return False
        self._releases[key] = ('loading', self._releases.get(key, ('', []))[1])
        self.publish()

        def work():
            # when it cannot be read now, the list read last time is still offered, under the reason
            old = card_plugins.kept_releases(plugin)[0]
            try:
                rows = card_plugins.releases(plugin)
                got = ('ok', rows) if rows else ('Its author has published no release this app can use.', [])
                if rows:
                    card_plugins.keep_releases(plugin, rows)
            except card_plugins.PluginError as e:
                got = (str(e).split('\n')[0], old)
            except Exception as e:                          # noqa: BLE001 - said on the card, never raised
                got = ('The list of versions could not be read: %s' % e, old)

            def done():
                self._releases[key] = got
                self.publish()
            self.ctx.loop.post(done)
        threading.Thread(target=work, daemon=True, name='pad-plugin-releases').start()
        return True

    @rpc
    def pick(self, key, tag):
        if self._plugin(key) is None:
            return False
        self._pick[key] = str(tag)
        self.publish()
        return True

    # ------------------------------------------------------------------ install, remove
    def _start(self, key, what, work, done_text):
        """Run ``work(say)`` on a worker; *say* puts a line under the buttons while it runs."""
        if self._busy.get(key) or self.get('running'):
            return False
        self._busy[key] = what
        self._said[key] = ('', '')
        self.publish()

        def say(text):
            def show():
                if self._busy.get(key):
                    self._busy[key] = text
                    self.publish()
            self.ctx.loop.post(show)

        def run():
            try:
                rec = work(say)
                said = (done_text(rec), 'ok')
            except card_plugins.PluginError as e:
                said = (str(e), 'err')
            except Exception as e:                          # noqa: BLE001 - said on the card, never raised
                said = ('%s did not finish: %s' % (what, e), 'err')

            def done():
                self._busy[key] = ''
                self._said[key] = said
                self.publish()
                write = self.window.service('write')
                if write is not None:                       # the installed version is part of what a build does
                    write.reload_assets_tabs()
            self.ctx.loop.post(done)
        threading.Thread(target=run, daemon=True, name='pad-plugin-install').start()
        return True

    @staticmethod
    def _installed_text(plugin, rec):
        return '%s %s is installed%s.' % (
            plugin.name, rec['tag'], '' if rec['tested'] else
            '. It is newer than this version of the app was tested with')

    @rpc
    def install(self, key, tag=''):
        """Download release *tag* (the one picked in the list when '') from the author's project and keep it."""
        plugin = self._plugin(key)
        if plugin is None:
            return False
        tags = [r['tag'] for r in self._releases.get(key, ('', []))[1]]
        tag = tag or self._pick.get(key) or (max(tags, key=card_plugins.tag_key) if tags else plugin.tested)
        last = {'at': 0}

        def work(say):
            def progress(name, done):
                if done - last['at'] >= (1 << 20) or done < last['at']:
                    last['at'] = done
                    say('Downloading %s: %.0f MB' % (name, done / 1048576.0))
            return card_plugins.install(plugin, tag, log=lambda text: self.ctx.loop.post(self.log, text),
                                        progress=progress)
        return self._start(key, 'Downloading %s %s' % (plugin.name, tag), work,
                           lambda rec: self._installed_text(plugin, rec))

    @rpc
    def install_from_files(self, key):
        """The same for a computer that cannot reach gitlab.com: the release's files, downloaded elsewhere."""
        plugin = self._plugin(key)
        if plugin is None or self._busy.get(key) or self.get('running'):
            return False
        names = list(plugin.archives.values()) + [card_plugins.SUMS]
        paths = compat.filedialog.askopenfilenames(
            title='Choose the release files: %s' % ', '.join(names),
            filetypes=[('Release files', '*.tar.gz SHA256SUMS'), ('All files', '*')])
        if isinstance(paths, str):
            paths = [paths] if paths else []
        paths = [os.path.normpath(p) for p in (paths or ()) if p]
        if not paths:
            return False
        return self._start(key, 'Checking the files', lambda say: card_plugins.install_from_files(plugin, paths),
                           lambda rec: self._installed_text(plugin, rec))

    @rpc
    def remove(self, key):
        """Take the plugin off this computer.  Cards already written keep it; a project that ticks it is told."""
        plugin = self._plugin(key)
        if plugin is None or self._busy.get(key) or self.get('running'):
            return False
        try:
            card_plugins.remove(plugin)
            self._said[key] = ('%s was removed from this computer. Cards already written keep it.' % plugin.name,
                               'ok')
        except card_plugins.PluginError as e:
            self._said[key] = (str(e), 'err')
        self.publish()
        write = self.window.service('write')
        if write is not None:
            write.reload_assets_tabs()
        return True

    # ------------------------------------------------------------------ the project's tick
    @rpc
    def configure(self, key, enabled, project):
        """Save the project's choice for plugin *key*; the next card written from it carries it."""
        plugin = self._plugin(key)
        if plugin is None or project != self._project() or self.get('running') or not os.path.isdir(project or ''):
            return False
        try:
            CARDS[key]['save'](project, bool(enabled))
        except card_extras.ExtrasError as e:
            self._said[key] = (str(e), 'err')
            self.publish()
            return False
        self._said[key] = ('', '')
        self.publish()
        write = self.window.service('write')
        if write is not None:
            write.reload_assets_tabs()
        return True

    @rpc
    def open_project(self, key):
        """Open the author's project page in the browser."""
        plugin = self._plugin(key)
        shellx = self.window.service('shellx')
        if plugin is None or shellx is None:
            return False
        shellx.open_link_checked(plugin.project, what="the plugin's project page")
        return True


TAB = PluginsTab
