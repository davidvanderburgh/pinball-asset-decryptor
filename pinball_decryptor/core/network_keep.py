"""Keep my network settings: a card image flashed as it is still gets the project's network options (PAD-1467).

David: "when a user flashes an sd card again outside of the network page, they'll lose their remote access and wifi
and score feed settings, right? is there a way for PAD to flash an image on the write page and maintain the network
settings?" ... "yes, do a 'keep my network settings' tick".

A build from the project carries the options; an image flashed as it is (a new code version, someone else's card)
does not.  With the tick, the flash first makes a copy of the image with the project's options on it - a build from
a project that holds nothing but them - writes that copy, and removes it.  The options are the ones that are files
on the card's system partition: remote access, the Wi-Fi start-up and adapter driver, and remote buttons.  The
score feed is part of PAD's mode runtime and needs a build of the project itself, so it is not one of them, and
the dialog says so.
"""
import json
import os

from . import card_extras, staged_changes

#: the project's ``extras`` records that are carried, and what each is called
CARRIED = (('ssh', 'remote access'), ('wifi', 'Wi-Fi start-up'), ('buttons', 'remote buttons'))
LABEL = 'Keep my network settings on this card'
NOTE = ('This image is written with %s from this project put on it first (a copy is made, written and removed; '
        'the image file itself is not changed). A score feed is not carried: it needs a build of the project.')


def options(project):
    """``{'ssh': {...}, 'wifi': {...}, 'buttons': {...}}``: the project's network options that are ON, as saved."""
    if not project or not os.path.isdir(project):
        return {}
    try:
        got = {'ssh': card_extras.load(project), 'wifi': card_extras.load_wifi(project),
               'buttons': card_extras.load_buttons(project)}
    except card_extras.ExtrasError:
        return {}
    return {key: rec for key, rec in got.items() if rec and rec.get('enabled')}


def names(project):
    """What would be kept, in words: ``['remote access', 'Wi-Fi start-up (5 GHz driver too)', ...]``."""
    on = options(project)
    out = []
    for key, name in CARRIED:
        if key in on:
            out.append(name + (' (and the newer adapter driver for 5 GHz)' if key == 'wifi' and on[key].get('band5') else ''))
    return out


def said(project):
    got = names(project)
    return got[0] if len(got) == 1 else ', '.join(got[:-1]) + ' and ' + got[-1] if got else ''


def stage_project(project, folder):
    """Write into the empty *folder* a project that holds nothing but *project*'s network options; the names."""
    on = options(project)
    if not on:
        raise card_extras.ExtrasError('This project has no network settings to keep.')
    saved = staged_changes.load(project).get('extras') or {}
    extras = {key: saved[key] for key in on if key in saved}
    with open(os.path.join(folder, '.staged_changes.json'), 'w', encoding='utf-8') as f:
        json.dump({'extras': extras}, f)
    return names(project)


def staged_path(image):
    """Where the copy with the options on is made: beside the image (the same drive has the room it needs)."""
    folder, name = os.path.split(os.path.abspath(image))
    stem, ext = os.path.splitext(name)
    return os.path.join(folder, '.%s.pad-network%s' % (stem, ext or '.raw'))


def clean(path):
    """Remove the copy and everything a build left beside it."""
    folder, name = os.path.split(path)
    try:
        listing = os.listdir(folder)
    except OSError:
        return
    for entry in listing:
        if entry == name or entry.startswith(name + '.'):
            try:
                os.remove(os.path.join(folder, entry))
            except OSError:
                pass
