"""The Test card tab's own list (PAD-1279, DragonRR's second round).

A TEST CARD is a small card that boots any Stern Spike 2 machine straight into a menu -
DEFAULT PAD TEST CARD, IMAGES, VIDEOS, SCENES, SOUNDS (and Color correction) - so a
colour profile, a picture, a clip or a sound can be judged on the machine without
building and burning a whole game.  What goes on it is chosen two ways:

* a TEST tick on a row of the Images, Video, Audio and Scenes tabs: that file (or that
  scene's resting frame) from that project, with the project's colour profile baked in,
  exactly as a build would put it on the machine;
* files from anywhere on the PC, added on the Test card tab: as they are, no profile.

The list is the user's, not a project's: items from several games can sit on one card.
It lives in ``testcard.json`` beside the app's settings.  The default PAD test card
patterns are always on the card (the menu draws them itself).
"""
import json
import os
import shutil
import threading

KINDS = ("image", "video", "scene", "sound")
#: what each tab's tick is called on the card, and the colour profile kind it reads
KIND_TITLE = {"image": "Images", "video": "Videos", "scene": "Scenes", "sound": "Sounds"}
PROFILE_KIND = {"image": "images", "video": "videos"}

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv",
              ".ogv", ".bik", ".gif")
SOUND_EXTS = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".wma", ".aif", ".aiff")

#: the menu takes this many items in all (codeselect conf.h CONF_MAX_TESTS)
MAX_ITEMS = 64
#: a label is one line the menu can hold (codeselect CONF_STR - 1)
LABEL_MAX = 199

_LOCK = threading.RLock()


def store_path():
    """Where the list is kept: beside the app's settings (PAD_TESTCARD_STORE for the tests)."""
    forced = os.environ.get("PAD_TESTCARD_STORE")
    if forced:
        return forced
    from pinball_decryptor.core import config
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "testcard.json")


def kind_of_file(path):
    """A file from the PC -> the list it goes in, by its name, or None (a .gif is a
    picture when it is a still and a video when it moves)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".gif":
        try:
            from PIL import Image
            with Image.open(path) as im:
                return "video" if getattr(im, "n_frames", 1) > 1 else "image"
        except Exception:                                       # noqa: BLE001
            return "image"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in SOUND_EXTS:
        return "sound"
    return None


def clean_label(label, fallback=""):
    """One line, no '|', at most LABEL_MAX bytes - what the menu's conf can carry."""
    s = " ".join(str(label or "").replace("|", "/").split()) or fallback
    while len(s.encode("utf-8")) > LABEL_MAX:
        s = s[:-1]
    return s


def norm_dir(path):
    return os.path.normcase(os.path.normpath(path)) if path else ""


class Item(object):
    """One thing on the card.  A project item has `project` (its assets folder) and `rel`
    (its row's key in that tab: a file's path under the folder, or a scene's dir); a file
    from the PC has `path` only.  `path` is also where a project file was found when it
    was ticked."""
    __slots__ = ("kind", "label", "path", "project", "rel", "game")

    def __init__(self, kind, label="", path="", project="", rel="", game=""):
        self.kind, self.label, self.path = kind, label, path
        self.project, self.rel, self.game = project, rel, game

    @property
    def from_project(self):
        return bool(self.project)

    def key(self):
        if self.project:
            return (self.kind, norm_dir(self.project), self.rel.replace("\\", "/"))
        return (self.kind, "", norm_dir(self.path))

    def to_json(self):
        return {k: getattr(self, k) for k in self.__slots__ if getattr(self, k)} | {"kind": self.kind}

    @classmethod
    def from_json(cls, d):
        if not isinstance(d, dict) or d.get("kind") not in KINDS:
            return None
        it = cls(d["kind"], *(str(d.get(k) or "") for k in ("label", "path", "project", "rel", "game")))
        if not it.project and not it.path:
            return None
        return it


class TestCardList(object):
    """The list and the card's own settings, kept in store_path()."""

    def __init__(self, path=None):
        self.path = path or store_path()
        self.items = []
        self.source = ""          # the Spike 2 card image the boot and system come from
        self.out = ""             # where the last test card was written
        self.load()

    # -- the file
    def load(self):
        with _LOCK:
            self.items = []
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                return
            for e in d.get("items") or []:
                it = Item.from_json(e)
                if it is not None and len(self.items) < MAX_ITEMS:
                    self.items.append(it)
            self.source = str(d.get("source") or "")
            self.out = str(d.get("out") or "")

    def save(self):
        with _LOCK:
            d = {"items": [it.to_json() for it in self.items], "source": self.source, "out": self.out}
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1)
            os.replace(tmp, self.path)

    # -- the ticks
    def find(self, kind, project, rel):
        k = Item(kind, project=project, rel=rel).key()
        return next((i for i, it in enumerate(self.items) if it.key() == k), -1)

    def tagged(self, kind, project):
        """{rel} of the items of this kind from this project (for a tab's TEST column)."""
        p = norm_dir(project)
        return {it.rel.replace("\\", "/") for it in self.items
                if it.kind == kind and it.project and norm_dir(it.project) == p}

    def set_tag(self, kind, project, rel, on, label="", path="", game=""):
        """Tick (on) or untick one project item -> (changed, why-not or "")."""
        if kind not in KINDS:
            return False, "not a kind the card has a list for"
        i = self.find(kind, project, rel)
        if not on:
            if i < 0:
                return False, ""
            del self.items[i]
            self.save()
            return True, ""
        if i >= 0:
            return False, ""
        if len(self.items) >= MAX_ITEMS:
            return False, "the test card takes at most %d items" % MAX_ITEMS
        name = os.path.splitext(os.path.basename(rel.rstrip("/\\")))[0]
        self.items.append(Item(kind, clean_label(label, name), path, project, rel, game))
        self.save()
        return True, ""

    # -- the tab's own list
    def add_files(self, paths):
        """Files from the PC -> (added, [(path, why) refused])."""
        added, refused = 0, []
        for p in paths or []:
            kind = kind_of_file(p)
            if not os.path.isfile(p):
                refused.append((p, "not a file"))
            elif kind is None:
                refused.append((p, "not a picture, video or sound"))
            elif len(self.items) >= MAX_ITEMS:
                refused.append((p, "the test card takes at most %d items" % MAX_ITEMS))
            elif any(it.key() == Item(kind, path=p).key() for it in self.items):
                refused.append((p, "already on the list"))
            else:
                self.items.append(Item(kind, clean_label(os.path.splitext(os.path.basename(p))[0]), p))
                added += 1
        if added:
            self.save()
        return added, refused

    def remove(self, i):
        if 0 <= i < len(self.items):
            del self.items[i]
            self.save()
            return True
        return False

    def clear(self):
        self.items = []
        self.save()

    def move(self, i, d):
        """Move item i up (d=-1) or down (d=1) within its own list (kind)."""
        if not 0 <= i < len(self.items):
            return False
        kind = self.items[i].kind
        same = [k for k, it in enumerate(self.items) if it.kind == kind]
        at = same.index(i)
        if not 0 <= at + d < len(same):
            return False
        j = same[at + d]
        self.items[i], self.items[j] = self.items[j], self.items[i]
        self.save()
        return True

    def rename(self, i, label):
        if 0 <= i < len(self.items):
            self.items[i].label = clean_label(label, self.items[i].label)
            self.save()
            return True
        return False

    def counts(self):
        return {k: sum(1 for it in self.items if it.kind == k) for k in KINDS}

    def ordered(self):
        """The items as the card's menu lists them: by list, each in the user's order."""
        return [it for k in KINDS for it in self.items if it.kind == k]


def available(mfr):
    """Whether this manufacturer gets the Test card tab and the TEST ticks: Stern Spike 2
    (a test card is made from a Spike 2 card's boot and system, and boots a Spike 2
    machine) - the multi-boot and the mode runtime both, and not the Spike 3 era."""
    caps = getattr(mfr, "capabilities", None)
    if caps is None:
        return False
    return (bool(getattr(caps, "multiboot", False)) and bool(getattr(caps, "modes", False))
            and getattr(mfr, "_era", None) != "spike3")


_SHARED = []


def shared():
    """The one list every tab ticks into (loaded from store_path() on first use)."""
    with _LOCK:
        if not _SHARED or _SHARED[0].path != store_path():
            _SHARED[:] = [TestCardList()]
        return _SHARED[0]


def changed(window):
    """The list changed: every tab's TEST column and the Test card tab show it."""
    if window is None:
        return
    svcs = list(getattr(window, "tabs", None) or [])
    text = next((t for t in svcs if getattr(t, "ns", "") == "text"), None)
    if text is not None and getattr(text, "scenes", None) is not None:
        svcs.append(text.scenes)
    for svc in svcs:
        for name in ("_tc_publish", "_tc_list_changed"):
            fn = getattr(svc, name, None)
            if fn is not None:
                try:
                    fn()
                except Exception:                               # noqa: BLE001
                    pass


def scene_png_path(project, rel):
    """Where a ticked scene's resting frame is kept between builds."""
    import hashlib
    h = hashlib.sha1(("%s|%s" % (norm_dir(project), rel)).encode("utf-8")).hexdigest()[:16]
    return os.path.join(os.path.dirname(store_path()), "testcard_scenes", h + ".png")


# ---- making the files ---------------------------------------------------------------------

def item_problem(it):
    """Why an item cannot go on a card now, or ''."""
    if it.kind == "scene":
        if it.path and os.path.isfile(it.path):
            return ""
        return "its picture is gone: tick it again in the Scenes tab"
    if not it.path or not os.path.isfile(it.path):
        return "the file is gone (%s)" % (it.path or it.rel)
    return ""


def stage(items, work, render_scene=None, log=print, cancel=None, resolver=None):
    """Each item as a file selectmedia can take -> [(kind, path, label)].

    A project's picture or video is written with that project's colour profile baked in
    (core.colour_export, the Save with color profile path), so it looks on the card as
    the project would put it on the machine; a file from the PC goes as it is; a scene is
    the picture of its resting frame drawn when it was ticked (or again before the build;
    `render_scene(item, png_path)` draws it here when given).
    An item that cannot be made is skipped and said."""
    from pinball_decryptor.core import colour_export as ce
    from pinball_decryptor.core import colour_profile as cp
    os.makedirs(work, exist_ok=True)
    resolvers = {}
    out = []
    for n, it in enumerate(items):
        if cancel and cancel():
            break
        why = item_problem(it)
        if why:
            log("test card: %s %r left out: %s" % (it.kind, it.label, why))
            continue
        try:
            if it.kind == "scene":
                if render_scene is not None:
                    dst = os.path.join(work, "scene%02d.png" % n)
                    render_scene(it, dst)
                    out.append((it.kind, dst, it.label))
                else:
                    out.append((it.kind, it.path, it.label))
                continue
            prof = None
            if it.from_project and it.kind in PROFILE_KIND:
                if resolver is not None:
                    prof = resolver(it)
                else:
                    if it.project not in resolvers:
                        resolvers[it.project] = cp.asset_resolver(it.project)
                    prof = resolvers[it.project](PROFILE_KIND[it.kind], it.rel)
            if prof is None:
                out.append((it.kind, it.path, it.label))
                continue
            if it.kind == "image":
                dst = os.path.join(work, "image%02d.png" % n)
                ce.save_image(it.path, dst, prof)
            else:
                dst = os.path.join(work, "video%02d.mp4" % n)
                ok, err = ce.save_video(it.path, dst, prof, cancel_cb=cancel)
                if not ok:
                    raise RuntimeError(err or "the clip did not convert")
            log("test card: %s %r with its color profile" % (it.kind, it.label))
            out.append((it.kind, dst, it.label))
        except Exception as exc:                                # noqa: BLE001
            log("test card: %s %r left out: %s" % (it.kind, it.label, exc))
    return out


def test_specs(staged, to_wsl=lambda p: p):
    """selectmedia's --test arguments for the staged items."""
    args = []
    for kind, path, label in staged:
        args += ["--test", "%s:%s|%s" % (kind, to_wsl(path), clean_label(label, "item"))]
    return args


def wipe(work):
    shutil.rmtree(work, ignore_errors=True)
