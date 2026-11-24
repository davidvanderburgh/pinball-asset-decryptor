"""Plugins: optional add-ons made by other people, installed from their own project (PAD-1554).

David: "maybe a new Plugins tab, where the user can choose optional plugins to install.  they need to persist
between PAD updates too."  The first is Matt Kulka's Bluetooth headphones, whose author asked that the app pull his
releases at a version tag rather than carry his code.

One card a plugin, in two halves:

* **On this computer**: which release is installed, the versions its author has published (the one this version
  of the app was tested with is marked), Install / Update, Install from files for a computer that cannot reach
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

#: plugin key -> its card side: the module that puts it on a card, the project's choice, and the tick's words
CARDS = {
    'bluetooth': dict(card=bluetooth_card, load=card_extras.load_bluetooth, save=card_extras.save_bluetooth,
                      tick='Put Bluetooth headphones on cards I write from this project',
                      needs='A Spike 2 machine needs a USB Bluetooth adapter plugged in. It works on the exact '
                            'game versions its author lists; on any other the game runs as Stern shipped it.'),
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
        pick = self._pick.get(plugin.key)
        if pick not in tags:
            pick = plugin.tested if plugin.tested in tags else tags[0]
        can = card.offered(self.mfr)
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
        return {
            'key': plugin.key, 'name': plugin.name, 'what': plugin.what, 'author': plugin.author,
            'project_url': plugin.project, 'license': plugin.license, 'tested': plugin.tested,
            'installed': rec['tag'] if rec else '', 'installed_tested': bool(rec and rec['tested']),
            'releases': rows, 'releases_state': state, 'pick': pick,
            'busy': self._busy.get(plugin.key, ''), 'note': text, 'kind': kind,
            'offered': can, 'supported': bool(info['supported']), 'reason': info['reason'],
            'enabled': on, 'has_project': has_project, 'hint': hint, 'error': error,
            'tick': side['tick'], 'needs': side['needs'],
            'details': [list(r) for r in card.DETAILS],
            'now': '' if info.get('unpicked') or not info['supported'] else card.describe(info),
        }

    def publish(self):
        project = self._project()
        self.set(project=project, store=card_plugins.store_root(),
                 plugins=[self._row(p, project) for p in card_plugins.PLUGINS.values() if p.key in CARDS])

    def _plugin(self, key):
        plugin = card_plugins.PLUGINS.get(key)
        return plugin if plugin is not None and key in CARDS else None

    def on_show(self):
        self.publish()
        for key in CARDS:
            if not self._releases.get(key, ('',))[0]:
                self.refresh_releases(key)

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
            try:
                rows = card_plugins.releases(plugin)
                got = ('ok', rows) if rows else ('Its author has published no release this app can use.', [])
            except card_plugins.PluginError as e:
                got = (str(e).split('\n')[0], [])
            except Exception as e:                          # noqa: BLE001 - said on the card, never raised
                got = ('The list of versions could not be read: %s' % e, [])

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
        tag = tag or self._pick.get(key) or plugin.tested
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
