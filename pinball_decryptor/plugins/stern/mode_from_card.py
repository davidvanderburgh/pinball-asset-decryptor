"""PAD-432: the modes of a card image, as a file of modes another project loads.

Three places, best first (:func:`card_modes_file`):

1. A card PAD built on this PC has its build record beside it, naming the project it was built
   from; when that folder is still here its modes are taken from it, whole.
2. A Write that puts modes on a card leaves the project's modes beside ``mode.so`` as the file
   the Modes tab's Save to a file writes (``/usr/local/padmode/pad_modes.zip``,
   :data:`.mode_project.CARD_BUNDLE`): every form and code mode's settings and sources (the code
   modes' C too) and the title they were made for, with their pictures, clips and sounds while
   those stay small (``mode_write.CARD_BUNDLE_MEDIA``; the file names the ones it left out). It
   is read straight out of the image (the read-only ext4 reader, no Linux needed).
3. Otherwise, the recovery below.

Either way the modes go into a project of another version, model or custom image in one load,
matched there as Copy to... matches them.

A card written before that carries only what the runtime reads: ``mode.so``, the mode files
and the port. Then the form modes are recovered from their mode files - name, what starts it,
how long it runs, the shots that score and the points, as the card's own port names the shots
- and every sentence of :func:`card_modes_file`'s notes says what did not come back (the
pictures, clips and sounds, the Advanced settings; a code mode's C is not on the card at all).
"""

import json
import os
import re
import tempfile

from . import mode_project as MP

#: where a Write puts the modes, on the card's system partition (mode_write.P2_DIR)
PADMODE = "usr/local/padmode"
#: the mode files mode.so reads, in slot order: mode.cfg, mode1.cfg .. mode63.cfg
_SLOT = re.compile(r"^mode(\d*)\.cfg$")


class CardModesError(MP.ModeProjectError):
    pass


def read_padmode(image):
    """``{name: bytes}``: every file of ``/usr/local/padmode`` on the card image ``image``, or
    ``{}`` when no partition of it has that folder (a card with no modes). Raises
    :class:`CardModesError` when ``image`` is not a card image the app can read."""
    from .ext4 import S_IFDIR, S_IFMT, S_IFREG, Ext4Reader
    from .formats import linux_partitions
    from . import mode_write as MW
    name = os.path.basename(str(image))
    try:
        parts = linux_partitions(image)
    except (OSError, ValueError) as e:
        raise CardModesError("%s could not be read as a card image (%s)" % (name, e)) from None
    if not parts:
        raise CardModesError("%s is not a card image: it has no Linux partitions" % name)
    with open(image, "rb") as f:
        for off, size in parts:
            try:
                reader = Ext4Reader(f, off, size)
                node = MW.lookup(reader, PADMODE)
            except Exception:                           # noqa: BLE001 - not an ext partition
                continue
            if node is None or (node["mode"] & S_IFMT) != S_IFDIR:
                continue
            out = {}
            for entry, child, _t in reader._iter_dir(node):
                if entry in (".", ".."):
                    continue
                inode = reader.read_inode(child)
                if (inode["mode"] & S_IFMT) == S_IFREG:
                    out[entry] = bytes(reader.read_file_bytes(inode))
            return out
    return {}


def bundle_about(data):
    """The ``"from"`` of a file of modes (:func:`.mode_project.card_about`), ``{}`` when it has
    none or is not one."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            head = json.loads(z.read(MP.SHARE_MANIFEST).decode("utf-8"))
    except (KeyError, ValueError, zipfile.BadZipFile):
        return {}
    about = head.get("from") if isinstance(head, dict) else None
    return about if isinstance(about, dict) else {}


def _cfg_rows(text):
    """``{key: [words]}`` of a mode file (first row of each key; ``#`` lines skipped)."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _sp, rest = line.partition(" ")
        out.setdefault(key, rest.split())
    return out


def _mask_names(p, mask):
    """The port's shots whose masks make up ``mask``, in the port's order."""
    return [n for n, m in p.shots if m and (mask & m) == m]


#: mode-file keys the recovery carries over; any other one names a part that did not come back
_RECOVERED_KEYS = {"name", "trigger", "seconds", "shots", "award", "stack", "light_all", "screen_scene",
                   "screen_node", "screen_text", "restore_after", "callout_at", "callout_count",
                   "callout_end", "sound_callout", "starts", "cooldown"}


def recover_spec(text, p):
    """A :class:`.mode_project.ModeSpec` for title ``p`` (the card's own port) from one of its
    mode files, and the sentence saying what of it did not come back ("" when nothing was lost
    but the pictures, clips and sounds every recovered mode loses)."""
    rows = _cfg_rows(text)
    spec = MP.blank_spec(p, " ".join(rows.get("name") or ["MODE"]))
    spec.title = p.key
    lost = []
    trig = rows.get("trigger") or []
    try:
        names = _mask_names(p, int(trig[0], 16))
        if names:
            spec.start_shot = names[0]
            spec.start_count = int(trig[1]) if len(trig) > 1 else 1
            if len(names) > 1:
                lost.append("it started on any of %s; it starts on %s now" % (", ".join(names), names[0]))
    except (IndexError, ValueError):
        lost.append("what starts it")
    for key, attr in (("seconds", "seconds"), ("award", "award")):
        try:
            setattr(spec, attr, int(rows[key][0]))
        except (KeyError, IndexError, ValueError):
            pass
    try:
        spec.scoring_shots = _mask_names(p, int(rows["shots"][0], 16))
    except (KeyError, IndexError, ValueError):
        pass
    spec.stack = (rows.get("stack") or ["yes"])[0] != "no"
    spec.countdown = "callout_count" in rows
    spec.screen = "screen_scene" in rows
    spec.clip, spec.end_sound = "none", ""
    if "light_all" in rows:
        spec.lights, spec.light_color = True, "#" + rows["light_all"][0].lower()
    else:
        spec.lights = "light_on" in rows
        if spec.lights:
            spec.light_on_raw = " ".join(rows["light_on"])
            spec.light_off_raw = " ".join(rows.get("light_off") or [])
    for key in ("starts", "cooldown"):
        if key in rows:
            v = rows[key][0]
            setattr(spec, key, int(v) if v.isdigit() else v)
    other = sorted(k for k in rows if k not in _RECOVERED_KEYS
                   and not k.startswith(("light_", "clip_", "sound_", "own_")))
    if other:
        lost.append("its Advanced settings (%s)" % ", ".join(other))
    return spec, "; ".join(lost)


def recover(files, project):
    """Put the form modes of the card's mode files (``files``, :func:`read_padmode`) in
    ``project``'s modes, as its own port names the shots. Returns ``(slugs, notes)``: the folder
    names made, and a sentence for each thing that did not come back."""
    port = files.get("game.port")
    if not port:
        raise CardModesError("its modes have no port beside them, so the app cannot tell which "
                             "shots they name")
    path = os.path.join(project, "game.port")
    with open(path, "wb") as f:
        f.write(port)
    p = MP.profile_from_port(path)
    slots = sorted((int(m.group(1) or 0), n) for n in files for m in [_SLOT.match(n)] if m)
    slugs, notes = [], []
    taken = set()
    for _i, name in slots:
        spec, lost = recover_spec(files[name].decode("utf-8", "replace"), p)
        slug = MP._free_slug(project, MP.slugify(spec.name), taken)
        taken.add(slug)
        MP.save(project, slug, spec)
        slugs.append(slug)
        if lost:
            notes.append("%s: %s did not come back" % (spec.name, lost))
    from . import code_modes as CM
    codes = sorted(n[:-len(".assets")] for n in files if n.endswith(".assets"))
    known = {e["slug"]: e["name"] for e in CM.EXAMPLES}
    examples, lost = [], []
    for slug in codes:
        if slug in known and slug not in taken:
            try:
                CM.add_example(project, known[slug])
            except (CM.CodeModeError, OSError):
                lost.append(slug.upper())
                continue
            taken.add(slug)
            slugs.append(slug)
            examples.append(known[slug])
        else:
            lost.append(slug.upper())
    if examples:
        notes.append("%s %s the app's own example%s: %s C came back as the app ships it (any edit "
                     "made to it is not on the card), and Cut from films makes %s clips and sounds"
                     % (", ".join(examples), "is" if len(examples) == 1 else "are",
                        "" if len(examples) == 1 else "s", "its" if len(examples) == 1 else "their",
                        "its" if len(examples) == 1 else "their"))
    if lost:
        notes.append("%s %s a code mode: %s C is not on the card, so it cannot be loaded from it"
                     % (", ".join(lost), "is" if len(lost) == 1 else "are",
                        "its" if len(lost) == 1 else "their"))
    return slugs, notes


def built_from(image):
    """The project folder the build record beside ``image`` names, when it is still here and
    holds modes; else ""."""
    from ...core import extract_source
    from . import code_modes as CM
    try:
        project = extract_source._build_project(str(image)) or ""
    except Exception:                                   # noqa: BLE001
        return ""
    if not project or not os.path.isdir(project):
        return ""
    try:
        return project if (MP.list_modes(project)[0] or CM.code_slugs(project)) else ""
    except (OSError, ValueError):
        return ""


def left_out_notes(data):
    """A sentence for each mode of a card's file of modes whose pictures, clips or sounds were
    too big to travel with it (its manifest's ``"left_out"``)."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            head = json.loads(z.read(MP.SHARE_MANIFEST).decode("utf-8"))
            left = [a for a in head.get("left_out") or () if isinstance(a, str)]
            by = {}
            for arc in left:
                parts = arc.split("/")
                if len(parts) >= 3:
                    by.setdefault(parts[1], []).append("/".join(parts[2:]))
            out = []
            for slug, names in sorted(by.items()):
                try:
                    mode = json.loads(z.read("%s/%s/%s" % (MP.MODES_DIRNAME, slug, MP.MODE_FILE)))
                    who, code = str(mode.get("name") or slug.upper()), False
                except (KeyError, ValueError, AttributeError):
                    who, code = slug.upper(), True
                one = len(names) == 1
                out.append("%s: %s %s too big to travel on the card; %s" % (
                    who, ", ".join(names), "was" if one else "were",
                    ("Cut from films makes %s again" % ("it" if one else "them")) if code else
                    ("pick or cut %s again (a build refuses the mode until then)"
                     % ("it" if one else "them"))))
            return out
    except (KeyError, ValueError, zipfile.BadZipFile):
        return []


def _arc_parts(arc):
    """``modes/<slug>/<file...>`` of a manifest's ``left_out`` entry as its parts, or None for
    anything else (a path that could leave the modes folder included: the manifest is the
    card's, and a card is anyone's)."""
    parts = str(arc).replace("\\", "/").split("/")
    if (len(parts) < 3 or parts[0] != MP.MODES_DIRNAME or ":" in arc
            or any(p in ("", ".", "..") for p in parts)):
        return None
    return parts


def fill_left_out(path, project):
    """The pictures, clips and sounds a card's file of modes (``path``) left out, put back from
    ``project`` - the project the card was built from - wherever that project still has the
    file under the same mode folder; the manifest's ``left_out`` then names only what is still
    missing. Returns the arcs added."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        head = json.loads(z.read(MP.SHARE_MANIFEST).decode("utf-8"))
        left = [a for a in head.get("left_out") or () if isinstance(a, str)]
        kept = [(i.filename, z.read(i.filename)) for i in z.infolist()
                if i.filename != MP.SHARE_MANIFEST and not i.is_dir()]
    still, added = [], []
    for arc in left:
        parts = _arc_parts(arc)
        src = os.path.join(project, *parts) if parts else ""
        if src and os.path.isfile(src):
            added.append((arc, src))
        else:
            still.append(arc)
    if not added:
        return []
    if still:
        head["left_out"] = still
    else:
        head.pop("left_out", None)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MP.SHARE_MANIFEST, json.dumps(head, indent=1))
        for arc, data in kept:
            z.writestr(arc, data)
        for arc, src in added:
            z.write(src, arc)
    os.replace(tmp, path)
    return [a for a, _s in added]


def card_modes_file(image, out_dir):
    """The modes on the card image ``image`` as a file :func:`.mode_project.import_modes` loads,
    written into ``out_dir`` as ``<image name> modes.zip``. Returns ``(path, about, notes)``:
    ``about`` the card the modes were made for (``{"title", "label", "card"}``, plus
    ``"project"`` when the project the card was built from, still on this PC, supplied any of
    it; ``{}`` when not known), and ``notes`` the sentences of what did not come back - ``[]``
    when they all did. Raises :class:`CardModesError` when the card has no modes, or none that
    can be brought back.

    What is ON THE CARD comes first: its own file of modes (a Write since PAD-432) is the
    modes as they were written, and the build-record project only puts back the pictures,
    clips and sounds that file was too small to carry. A card written before cards carried
    one takes that project's modes as the project is NOW (said in the notes); with no project
    either, :func:`recover` rebuilds what the card holds."""
    name = os.path.basename(str(image))
    stem = re.sub(r'[\\/:*?"<>|]+', "_", os.path.splitext(name)[0]).strip(" .") or "card"
    path = os.path.join(out_dir, "%s modes.zip" % stem)
    files = read_padmode(image)
    if not files or "mode.so" not in files:
        raise CardModesError("%s carries no modes: a card the app put modes on has them in "
                             "/usr/local/padmode" % name)
    project = built_from(image)
    data = files.get(MP.CARD_BUNDLE)
    if data:
        with open(path, "wb") as f:
            f.write(data)
        about = bundle_about(data)
        if project and fill_left_out(path, project):
            about = dict(about, project=project)
        with open(path, "rb") as f:
            data = f.read()
        return path, about, left_out_notes(data)
    if project:
        about = dict(MP.card_about(project), project=project)
        MP.export_modes(project, path, about=about)
        return path, about, [
            "%s was written before cards carried their modes whole, so its modes are taken from "
            "the project it was built from (%s), as that project is now" % (name, project)]
    with tempfile.TemporaryDirectory(prefix="pad-card-modes-") as tmp:
        slugs, notes = recover(files, tmp)
        if not slugs:
            raise CardModesError("%s carries no modes the app can bring back. %s" % (
                name, " ".join(n[0].upper() + n[1:] + "." for n in notes)))
        p = MP.profile_from_port(os.path.join(tmp, "game.port"))
        MP.export_modes(tmp, path, slugs, about={"title": p.key, "label": p.label, "card": name})
    notes.insert(0, "%s was written before cards carried their modes whole, so %s brought back from "
                    "what the card holds: no picture, clip or sound of %s came back"
                 % (name, "this mode was" if len(slugs) == 1 else "these %d modes were" % len(slugs),
                    "it" if len(slugs) == 1 else "theirs"))
    return path, {"title": p.key, "label": p.label, "card": name}, notes
