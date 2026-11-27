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

#: Simon (2026-11-22): a test card updated over the network.  The card is kept small so it
#: writes fast; "Allow additional space on the test card for network updates?" makes its
#: test files partition bigger (ROOM_GB_DEFAULT, or any size: "the user can make it whatever
#: size they want, completely unfettered"), and remote access / Wi-Fi start-up go on it as on a
#: game card (Network tab), so Send to machine can reach it.
ROOM_GB_DEFAULT = 2
NETWORK_DEFAULTS = {"room": False, "room_gb": ROOM_GB_DEFAULT, "ssh": False, "wifi": False, "band5": False}
# Simon (2026-11-26): the Wi-Fi the test card joins with no game is core/menu_network.saved() - one for the Test card
# and Multi-boot tabs


def clean_network(d):
    """The tab's network settings, each of its own type (a bad value falls back)."""
    out = dict(NETWORK_DEFAULTS)
    if isinstance(d, dict):
        for k in ("room", "ssh", "wifi", "band5"):
            if isinstance(d.get(k), bool):
                out[k] = d[k]
        try:
            gb = float(d.get("room_gb", ROOM_GB_DEFAULT))
            if gb > 0:
                out["room_gb"] = round(gb, 2)
        except (TypeError, ValueError):
            pass
    return out


def room_mib(net):
    """--p3-mib for the build: the extra space asked for, or 0 (just what the files need)."""
    net = clean_network(net)
    return int(net["room_gb"] * 1024) if net["room"] else 0


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
    was ticked.

    THE LAYERED TEST (Simon, 2026-11-22/26): a video item with `layers` - the project's scenes drawn over the clip
    (plugins/stern/layered_test.py specs, ``HASH`` or ``HASH@FRAME``, the lowest first), made on the Scenes tab's
    Layered test… button.  `player` (Simon, 2026-11-26: the number "is in the wrong place"): the state of the game's
    video player the clip is shown in (a label of layered_test.clip_states, e.g. ScoreFrame); empty = the default.
    `plain` (Simon, 2026-11-26, an A/B test of the overlay's colour on the table): its scenes drawn from the pictures
    as extracted, without each file's own colour profile."""
    __slots__ = ("kind", "label", "path", "project", "rel", "game", "layers", "player", "plain")

    def __init__(self, kind, label="", path="", project="", rel="", game="", layers=(), player="", plain=False):
        self.kind, self.label, self.path = kind, label, path
        self.project, self.rel, self.game = project, rel, game
        self.layers = tuple(str(x) for x in (layers or ()) if str(x).strip())
        self.player = str(player or "").strip() if self.layers else ""
        self.plain = bool(plain) and bool(self.layers)

    @property
    def from_project(self):
        return bool(self.project)

    @property
    def shown_kind(self):
        """The list it is in on the card and the Test card tab: a layered test has its own (Simon, 2026-11-26)."""
        return "layered" if self.layers else self.kind

    def key(self):
        tail = self.layers + ((self.player,) if self.player else ()) + (("plain",) if self.plain else ())
        if self.project:
            return (self.kind, norm_dir(self.project), self.rel.replace("\\", "/")) + tail
        return (self.kind, "", norm_dir(self.path)) + tail

    def to_json(self):
        d = {k: getattr(self, k) for k in self.__slots__ if getattr(self, k)} | {"kind": self.kind}
        if self.layers:
            d["layers"] = list(self.layers)
        return d

    @classmethod
    def from_json(cls, d):
        if not isinstance(d, dict) or d.get("kind") not in KINDS:
            return None
        it = cls(d["kind"], *(str(d.get(k) or "") for k in ("label", "path", "project", "rel", "game")),
                 layers=d.get("layers") if isinstance(d.get("layers"), list) and d["kind"] == "video" else (),
                 player=str(d.get("player") or ""), plain=d.get("plain") is True)
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
        self.network = dict(NETWORK_DEFAULTS)   # space for network updates, remote access, Wi-Fi
        self.built = {}           # the last card built: {out, sig, size, mtime} (built_card)
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
            self.network = clean_network(d.get("network"))
            self.built = d.get("built") if isinstance(d.get("built"), dict) else {}

    def save(self):
        with _LOCK:
            d = {"items": [it.to_json() for it in self.items], "source": self.source, "out": self.out,
                 "network": self.network, "built": self.built}
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

    def layered(self):
        """[(index, item)] of the layered tests, in the list's order."""
        return [(i, it) for i, it in enumerate(self.items) if it.kind == "video" and it.layers]

    def add_layered(self, item, replace=None):
        """A layered test (Simon, 2026-11-26: the Scenes tab's Layered test… button) -> '' or why not.  *replace*:
        the index of the layered test it takes the place of (Edit).  Simon: "lets max that at 5"."""
        mine = [i for i, _it in self.layered()]
        if replace is not None and replace not in mine:
            return "that layered test is no longer on the list"
        if replace is None and len(mine) >= MAX_LAYERED:
            return "the test card takes at most %d layered tests: remove one first" % MAX_LAYERED
        if replace is None and len(self.items) >= MAX_ITEMS:
            return "the test card takes at most %d items" % MAX_ITEMS
        if any(it.key() == item.key() for i, it in enumerate(self.items) if i != replace):
            return "that layered test is already on the list"
        if replace is None:
            self.items.append(item)
        else:
            self.items[replace] = item
        self.save()
        return ""

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
        kind = self.items[i].shown_kind
        same = [k for k, it in enumerate(self.items) if it.shown_kind == kind]
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
        out = {k: sum(1 for it in self.items if it.shown_kind == k) for k in KINDS}
        n = sum(1 for it in self.items if it.layers)
        if n:                                           # the layered tests' own list (Simon, 2026-11-26)
            out["layered"] = n
        return out

    def ordered(self):
        """The items as the card's menu lists them: by list, each in the user's order."""
        return [it for k in KINDS for it in self.items if it.kind == k]


def available(mfr):
    """Whether this manufacturer gets the Test card tab and the TEST ticks: Stern Spike 2
    (a test card is made from a Spike 2 card's boot and system, and boots a Spike 2
    machine) - the multi-boot and the mode runtime both - and Stern Spike 3 (PAD-1586: a
    Spike 3 card's own, laid out by mks3multi.py testcard; the same menu, built for the Pi)."""
    caps = getattr(mfr, "capabilities", None)
    if caps is None:
        return False
    if getattr(mfr, "_era", None) == "spike3":
        return bool(getattr(caps, "multiboot", False))
    return bool(getattr(caps, "multiboot", False)) and bool(getattr(caps, "modes", False))


#: is_spike3_source()'s answers, by (path, size, mtime)
_S3_SOURCE = {}


def is_spike3_source(path):
    """Is the card image a test card is made from a Stern Spike 3 card (PAD-1586)? Its
    partition table says (a few sectors, read once per file); a missing file is not."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return False
    k = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime)
    got = _S3_SOURCE.get(k)
    if got is None:
        from ..plugins.stern import spike3
        got = _S3_SOURCE[k] = bool(spike3.is_spike3_card(path))
    return got


#: what a Spike 3 test card leaves off, in the words the build says
S3_NO_SOUND = ("a Spike 3 machine's menu plays no sound (the cabinet amplifier is the game's to "
               "start), so the sounds are left off this card")
S3_NO_NETWORK = ("remote access, Wi-Fi start-up and extra room are for a Spike 2 test card; a "
                 "Spike 3 one is the size of the card it is made from")


_SHARED = []


#: Simon (2026-11-26): "lets max that at 5 for the UI"
MAX_LAYERED = 5


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


#: Simon (2026-11-26): a Spike 2 test card's videos play through the machine's own decoder (codeselect gstclip.c:
#: GStreamer 0.10, vpudec, the graphics chip converts - 30 fps on the table) instead of JPEG frames (.padv: 0.1-0.5 fps
#: on the table). The decoder takes H.264 up to 1920x1088 (the VPU's), in these containers; anything else is made into
#: one first. A GIF stays frames: it is a short animation, not a clip.
CLIP_EXTS = (".mp4", ".mov", ".m4v")
CLIP_MAX = (1920, 1088)


def as_clip(path, work, n, log=print, cancel=None):
    """The file the machine's decoder plays for the test video *path*: *path* itself when it already is one (H.264
    in .mp4/.mov/.m4v, 8-bit 4:2:0 at an even size, no bigger than :data:`CLIP_MAX`), else an H.264 .mp4 made from it in *work*, fitted inside
    CLIP_MAX. ``None`` for a GIF or a file no video tool can read: it stays frames."""
    from pinball_decryptor.core import video
    ext = os.path.splitext(path)[1].lower()
    if ext == ".gif":
        return None
    info = video.detect_video_info(path)
    if info is None or not (info.width > 0 and info.height > 0):
        return None
    w, h = info.width, info.height
    # the VPU decodes 8-bit 4:2:0 only, and the menu's conversion reads chroma at half the even size: a 10-bit or
    # 4:4:4 H.264, or an odd width or height, is made into one like any other file (an unknown format goes as it is)
    fmt_ok = (info.pix_fmt or "yuv420p").lower() in ("yuv420p", "yuvj420p")
    if (ext in CLIP_EXTS and (info.vcodec or "").lower() == "h264" and fmt_ok
            and w % 2 == 0 and h % 2 == 0 and w <= CLIP_MAX[0] and h <= CLIP_MAX[1]):
        return path
    s = min(1.0, CLIP_MAX[0] / float(w), CLIP_MAX[1] / float(h))
    target = video.VideoInfo(path, vcodec="h264", width=max(2, int(w * s) // 2 * 2),
                             height=max(2, int(h * s) // 2 * 2), fps=info.fps, duration=info.duration,
                             has_audio=info.has_audio, pix_fmt="yuv420p", container="mp4")
    dst = os.path.join(work, "clip%02d.mp4" % n)
    ok, err = video.transcode_video_to(path, dst, target, best_quality=True, cancel_cb=cancel)
    if not ok:
        raise RuntimeError(err or "the clip did not convert")
    log("test card: %s made into an H.264 clip at %dx%d for the machine's decoder"
        % (os.path.basename(path), target.width, target.height))
    return dst


def stage(items, work, render_scene=None, log=print, cancel=None, resolver=None, clips=False):
    """Each item as a file selectmedia can take -> [(kind, path, label)].

    A project's picture or video is written with that project's colour profile baked in
    (core.colour_export, the Save with color profile path), so it looks on the card as
    the project would put it on the machine; a file from the PC goes as it is; a scene is
    the picture of its resting frame drawn when it was ticked (or again before the build;
    `render_scene(item, png_path)` draws it here when given).
    An item that cannot be made is skipped and said.

    *clips* (a Spike 2 card): each video goes as a clip the machine's own decoder plays (:func:`as_clip`, kind
    ``clip``), not as frames; one that cannot be made a clip stays a video (frames)."""
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
                    out.append((it, it.kind, dst, it.label))
                else:
                    out.append((it, it.kind, it.path, it.label))
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
                out.append((it, it.kind, it.path, it.label))
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
            out.append((it, it.kind, dst, it.label))
        except Exception as exc:                                # noqa: BLE001
            log("test card: %s %r left out: %s" % (it.kind, it.label, exc))
    layered = {id(it): it for it in items if it.kind == "video" and it.layers}
    if clips:
        made = []
        for n, (src, kind, path, label) in enumerate(out):
            if kind == "video":
                try:
                    clip = as_clip(path, work, n, log=log, cancel=cancel)
                except Exception as exc:                        # noqa: BLE001
                    log("test card: video %r stays frames: %s" % (label, exc))
                    clip = None
                if clip:
                    kind, path = "clip", clip
            if src is not None and id(src) in layered:
                if kind != "clip":
                    log("test card: layered test %r left out: its video cannot play as a clip" % label)
                    continue
                try:
                    placed, ovl = layered_files(src, path, work, n, log=log, cancel=cancel)
                    made.append((kind, placed, label, ovl))
                except Exception as exc:                        # noqa: BLE001
                    log("test card: layered test %r left out: %s" % (label, exc))
                continue
            made.append((kind, path, label))
        out = made
    else:
        for it in layered.values():
            log("test card: layered test %r left out: a Spike 3 test card plays no clips" % it.label)
        out = [o[1:] for o in out if id(o[0]) not in layered]
    return out


#: Simon (2026-11-26): "It takes a really long time to make the test card with no feedback that anything is going
#: on. It should be a fast process?" - a layered test's placed clip and overlay are kept here, by what made them, and
#: a build whose test, clip, project scenes and drawing code have not changed takes them as they are
LAYERED_CACHE = "testcard_layered"
#: the newest this many tests' files are kept
LAYERED_KEEP = 12


def _layered_key(item, clip):
    """What a layered test's files are made from: the test, its clip, the project's scenes and edits, and the
    code that draws them (a file's size and time)."""
    import hashlib
    from pinball_decryptor.plugins.stern import layered_test as LT
    from pinball_decryptor.plugins.stern import scene_render as SR

    def stamp(p):
        try:
            st = os.stat(p)
            return [p, st.st_size, int(st.st_mtime)]
        except OSError:
            return [p, None]
    def contents(p):
        # the clip by what is in it: a build hands it over from a new temporary folder each time
        h = hashlib.sha1()
        try:
            with open(p, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
        except OSError:
            return None
        return h.hexdigest()
    parts = [list(item.layers), getattr(item, "player", ""), bool(getattr(item, "plain", False)), contents(clip),
             stamp(os.path.join(item.project, "images", "scene_textures", "scene_tree.json")),
             stamp(os.path.join(item.project, ".staged_changes.json")),
             stamp(LT.__file__), stamp(SR.__file__), stamp(__file__)]
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def layered_files(item, clip, work, n, log=print, cancel=None):
    """``(clip, overlay)`` for layered test *item* over *clip*: from the cache when nothing that makes them has
    changed (:data:`LAYERED_CACHE`), else made (:func:`place_layered_clip`, :func:`layer_overlay`) and kept."""
    home = os.path.join(os.path.dirname(store_path()), LAYERED_CACHE)
    key = _layered_key(item, clip)
    kept_clip, kept_ovl = (os.path.join(home, key + ext) for ext in (".mp4", ".pado"))
    cached = os.path.isfile(kept_ovl) and (os.path.isfile(kept_clip) or os.path.isfile(kept_ovl + ".asis"))
    if cached:
        log("test card: layered test %r unchanged since it was last made: kept as it was" % item.label)
        placed = kept_clip if os.path.isfile(kept_clip) else clip
        got = (placed, kept_ovl)
        try:
            for p in got:
                os.utime(p)
        except OSError:
            pass
    else:
        log("test card: making layered test %r" % item.label)
        placed = place_layered_clip(item, clip, work, n, log=log, cancel=cancel)
        ovl = layer_overlay(item, placed, work, n, log=log)
        got = (placed, ovl)
        try:
            os.makedirs(home, exist_ok=True)
            shutil.copyfile(ovl, kept_ovl)
            if placed != clip:
                shutil.copyfile(placed, kept_clip)
            else:
                open(kept_ovl + ".asis", "w").close()
            _prune_layered(home)
        except OSError as exc:
            log("test card: layered test %r could not be kept for the next build: %s" % (item.label, exc))
    return got


def _prune_layered(home):
    """Only the newest :data:`LAYERED_KEEP` tests' files stay in *home*."""
    try:
        names = [f for f in os.listdir(home) if f.endswith(".pado")]
    except OSError:
        return
    names.sort(key=lambda f: os.path.getmtime(os.path.join(home, f)), reverse=True)
    for f in names[LAYERED_KEEP:]:
        stem = f[:-len(".pado")]
        for g in (stem + ".pado", stem + ".mp4", stem + ".pado.asis"):
            try:
                os.remove(os.path.join(home, g))
            except OSError:
                pass


def _stamp(path):
    try:
        st = os.stat(path)
        return [path, st.st_size, int(st.st_mtime)]
    except (OSError, TypeError, ValueError):
        return [path, None]


def build_signature(lst, items=None):
    """What a test card is built from: the list, the card image, the network settings, each item's file and each
    project's scenes and edits (a file's size and time).  Two builds with the same signature make the same card."""
    import hashlib
    items = list(lst.ordered() if items is None else items)
    projects = sorted({it.project for it in items if it.project})
    parts = [[it.to_json() for it in items], _stamp(lst.source), clean_network(lst.network),
             [_stamp(it.path) for it in items],
             [[_stamp(os.path.join(p, ".staged_changes.json")),
               _stamp(os.path.join(p, "images", "scene_textures", "scene_tree.json"))] for p in projects]]
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def note_built(lst, out, sig):
    """Remember *out* as the card built from *sig* (:func:`build_signature` taken when the build started)."""
    st = os.stat(out)
    lst.built = {"out": out, "sig": sig, "size": st.st_size, "mtime": int(st.st_mtime)}
    lst.save()


def built_card(lst):
    """Simon (2026-11-27): "if I "build" the card... it asks me to save it. If I send the card it also asks me to save
    it.. Seems that Sending doesn't check to see if it is already built?" - the card last built, when it is still
    on disk as it was written and nothing it was built from has changed since; else ''."""
    b = lst.built or {}
    out = b.get("out") or ""
    if not out or not os.path.isfile(out) or os.path.exists(str(out) + ".ssh-pending"):
        return ""
    st = os.stat(out)
    if st.st_size != b.get("size") or int(st.st_mtime) != b.get("mtime"):
        return ""
    return out if b.get("sig") == build_signature(lst) else ""


def place_layered_clip(item, clip, work, n, log=print, cancel=None):
    """Simon (2026-11-26): "the number overlay ... is in the wrong place" - a layered test's clip as the game's video
    player shows it (plugins/stern/layered_test.clip_placement: Godzilla's draws a 1360x768 clip zoomed 1.32x about
    the centre), so the clip's own pictures sit under the scenes where the game puts them; *clip* itself when no
    scene of the project plays it or the player shows it 1:1."""
    from pinball_decryptor.plugins.stern import layered_test as LT
    name = os.path.splitext(os.path.basename(item.rel or item.path or ""))[0]
    place = LT.clip_placement(item.project, name, getattr(item, "player", ""))
    if place is None:
        return clip
    stage = (1360, 768)
    try:
        spec = LT.parse_scene(item.layers[0])[0]
        stage = tuple(int(x) for x in LT.find_scene(LT.scene_tree(item.project), spec)[1]["stage"][:2])
    except Exception:                                           # noqa: BLE001 - Spike 2's screen
        pass
    _frames, fps = LT.clip_frames(clip)
    dst = os.path.join(work, "placed%02d.mp4" % n)
    LT.place_clip(clip, dst, place, stage, fps=fps, cancel=cancel)
    log("test card: %s placed as the game's player shows it (%.2fx, corner at %d,%d)"
        % (name, place[0], round(place[2]), round(place[3])))
    return dst


def layer_overlay(item, clip, work, n, log=print):
    """The ``.pado`` for layered test *item* over *clip* (plugins/stern/layered_test.py): its scenes drawn one
    picture per clip frame, timed by the clip's own frames."""
    from pinball_decryptor.plugins.stern import layered_test as LT
    frames, fps = LT.clip_frames(clip)
    out = os.path.join(work, "clip%02d.pado" % n)

    def progress(done, total):
        log("test card: layered test %r: drawing frame %d of %d" % (item.label, done, total))
    LT.make_overlay(item.project, list(item.layers), out, frames, fps, log=lambda m: log("test card: " + m.strip()),
                    profiles=not getattr(item, "plain", False), progress=progress)
    return out


def test_specs(staged, to_wsl=lambda p: p):
    """selectmedia's --test arguments for the staged items."""
    args = []
    for k, entry in enumerate(staged):
        kind, path, label = entry[:3]
        args += ["--test", "%s:%s|%s" % (kind, to_wsl(path), clean_label(label, "item"))]
        if len(entry) > 3 and entry[3]:                 # a layered test's overlay, by the test's number
            args += ["--test-overlay", "%d=%s" % (k, to_wsl(entry[3]))]
    return args


def wipe(work):
    shutil.rmtree(work, ignore_errors=True)
