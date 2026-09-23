"""Partitions tab (Tk: "Partition Explorer", ``MainWindow._build_partition_tab``
and its ``_pex_*`` methods).

Open a raw Stern Spike 2 card image without mounting it, pick one of its MBR
partitions (``sda1``..``sda4``), walk the ext4 tree lazily, preview a file in
place (text, or a picture of an image/font with its real size), find a file by
path substring, extract one file / one folder / a partition / every partition,
and (the one WRITE) replace a file on the card with one of your own.

The tree lives here, not in the page: ``rows`` is the flattened list of the
visible nodes (depth, open state, the Tk columns Size / Type / Changed), and
every expand / filter / reveal rebuilds it.  All card reads go through
``plugins.stern.explorer.CardImage`` exactly as the Tk tab did; the replace
journal is ``core.card_edits``.  Worker threads never touch the store: they
fill a plain dict that a loop timer polls (the Tk tab's after()-poll shape).
"""

import os
import shutil
import tempfile
import threading

from .. import compat
from .base import TabService, rpc

#: Tk module constants (gui/main_window.py _PEX_*): the preview's file types
#: and the byte cap for the image/font render read.
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tga", ".webp")
FONT_EXTS = (".ttf", ".otf")
RENDER_CAP = 12 << 20

SHOW_CHOICES = ("All", "Changed", "Unchanged")

SHOW_TIP = ("Changed = the files you have replaced on this card image with "
            "PAD (it remembers them per image, so they are still marked next "
            "session).\nUnchanged = the rest of the tree with those files "
            "left out.")

INTRO = ("Browse a raw Stern card image (.raw / .img): view its partitions and "
         "files, preview images, fonts and text, extract any file or folder "
         "to disk, and (right-click) replace any file with one of your own — "
         "a same-size file is written straight into its slot, and a bigger or "
         "smaller one is resized on the card through the Linux filesystem "
         "driver (needs WSL2). Validation records are refreshed "
         "automatically. Browsing never changes the card; only an explicit "
         "Replace writes to it. Changed marks the files you have replaced "
         "here, remembered per card image — an edit made outside PAD leaves "
         "no trace to find.")

BTN_LABELS = {"sel": "Extract Selected", "part": "Extract Whole Partition",
              "all": "Extract All Partitions"}


class _Cancelled(Exception):
    """Extract cancelled: raised inside the worker's progress callbacks so
    the ext4 walk unwinds at its next tick (Tk ``_PexCancelled``)."""


def human(n):
    """Tk ``MainWindow._pex_human``: ``0 B`` / ``1.5 KB`` / ``6.0 GB``."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return ("%d %s" % (int(size), unit) if unit == "B"
                    else "%.1f %s" % (size, unit))
        size /= 1024.0
    return ""                                   # pragma: no cover


def decode_preview(data):
    """Tk ``_pex_decode_preview``: text, or the binary placeholder when more
    than 2% of the first 4 KB are non-printables."""
    sample = data[:4096]
    nonprint = sum(1 for b in sample if b < 9 or 13 < b < 32)
    if sample and nonprint > len(sample) * 0.02:
        return "(binary file — %d bytes; extract it to view)" % len(data)
    return data.decode("utf-8", "replace")


def _have_pil():
    try:
        import PIL  # noqa: F401
        return True
    except Exception:                           # noqa: BLE001
        return False


class PartitionsTab(TabService):
    ns = "partitions"
    key = "Partition Explorer"
    label = "Partitions"
    group = "Inspect"
    icon = "partitions"
    exports = ("partition_image_var", "partition_part_var",
               "partition_show_var", "partition_search_var",
               "_asset_find_in_partition", "find_in_partition")

    def __init__(self, window):
        super().__init__(window)
        self.partition_image_var = self.var("image")
        self.partition_part_var = self.var("part")
        self.partition_show_var = self.var("show", value="All")
        self.partition_search_var = self.var("search")
        self._card = None               # the open CardImage (browse handle)
        self._image_path = None
        self._part_index = None
        self._part_labels = {}          # label -> Partition (insertion order)
        self._nodes = {}                # path -> node dict
        self._children = {}             # dir path ("" = root) -> [paths]
        self._dirs = set()
        self._populated = set()
        self._open = set()
        self._marks = {}                # on-card path -> "replaced <date>"
        self._sel = None
        self._busy = False
        self._busy_kind = None
        self._cancel = None
        self._search_cache = None       # ((image, part), [paths])
        self._search_state = ("", -1)
        self._preview_seq = 0
        self._preview_dir = None
        self._preview_file = None
        self._props_seq = 0
        self._box = (330, 250)          # the page's preview box, in px
        self.set(intro=INTRO, show_tip=SHOW_TIP, show_choices=list(SHOW_CHOICES),
                 parts=[], rows=[], sel=None, sel_dir=False, status="",
                 preview=None, busy=None, busy_btn=None, cancelling=False,
                 can_find=False, can_part=False, can_all=False, props=None,
                 history=[], have_pil=_have_pil(), widths=None)

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        self._push_history()

    def on_show(self):
        self._push_history()
        self._default_from_extract()

    def on_close(self):
        if self._cancel is not None:
            self._cancel.set()
        self._close_card()
        if self._preview_dir:
            shutil.rmtree(self._preview_dir, ignore_errors=True)
            self._preview_dir = None

    def _push_history(self):
        self.set(history=self.window.path_history("partition_image"))

    # ------------------------------------------------------------------
    # open + partitions
    # ------------------------------------------------------------------
    def _default_from_extract(self):
        """A blank Card Image defaults to the Extract tab's input image and
        opens it (Tk ``_pex_default_from_extract``); never overrides a path
        the user already put here."""
        if self._busy or (self.partition_image_var.get() or "").strip():
            return
        var = getattr(self.window, "extract_input_var", None)
        src = ((var.get() if var is not None else "") or "").strip()
        if (src and src.lower().endswith((".raw", ".img", ".bin"))
                and os.path.isfile(src)):
            self.partition_image_var.set(os.path.normpath(src))
            self.open_image()

    @rpc
    def browse(self):
        cur = (self.partition_image_var.get() or "").strip()
        path = self.window.ask_open(
            "partition_image", "Select a card image",
            [("Card image", "*.raw *.img *.bin"), ("All files", "*.*")],
            initialdir=(os.path.dirname(cur) if cur else None))
        if path:
            self.partition_image_var.set(os.path.normpath(path))
            self.open_image()
        return path

    @rpc
    def open_image(self, path=None):
        """Open the card image at the current path (or *path*) and fill the
        partition list, selecting the first browsable ext partition."""
        if self._busy:
            compat.messagebox.showinfo(
                "Extract in progress",
                "An extract is still running — cancel it before opening "
                "another image.")
            return False
        if path is not None:
            self.partition_image_var.set(path)
        path = (self.partition_image_var.get() or "").strip()
        if not path:
            return False
        try:
            from ...core.admin import resolve_mapped_drive
            fixed = resolve_mapped_drive(path)
        except Exception:                        # noqa: BLE001
            fixed = path
        if fixed != path:
            path = fixed
            self.partition_image_var.set(path)
        if not os.path.isfile(path):
            self.log("Could not open %s: file not found." % path, "error")
            compat.messagebox.showerror("File not found",
                                        "No file at:\n\n%s" % path)
            return False
        self._close_card()
        try:
            from ...plugins.stern.explorer import CardImage
            card = CardImage(path)
        except Exception as e:                   # noqa: BLE001
            self.log("Could not open %s: %s" % (path, e), "error")
            compat.messagebox.showerror(
                "Not a card image",
                "Couldn't open this file as a raw card image:\n\n%s\n\n%s"
                % (path, e))
            return False
        self._card = card
        self._image_path = path
        cb = self.window.cb.get("on_partition_image_opened")
        if cb is not None:
            cb(path)
        self._push_history()
        parts = card.partitions()
        self._part_labels = {}
        for p in parts:
            label = "sda%d — %s (%s)%s" % (
                p.index + 1, p.label, human(p.size),
                "" if p.browsable else " — not browsable")
            self._part_labels[label] = p
        self.set(parts=[{"value": lbl, "label": lbl,
                         "browsable": bool(p.browsable)}
                        for lbl, p in self._part_labels.items()])
        first = next((lbl for lbl, p in self._part_labels.items()
                      if p.browsable), None)
        self.log("Opened %s — %d partition%s."
                 % (path, len(parts), "" if len(parts) == 1 else "s"), "info")
        if first:
            self.partition_part_var.set(first)
            self._on_partition_select()
        else:
            labels = list(self._part_labels)
            self.partition_part_var.set(labels[0] if labels else "")
            self._clear_tree()
            self.log("No browsable ext filesystem on this image.", "warning")
            compat.messagebox.showwarning(
                "Nothing to browse",
                "This image has no browsable ext filesystem.")
        return True

    @rpc
    def select_partition(self, label):
        if self._busy:
            # Mid-extract the buttons are Cancel / waiting: snap back.
            cur = next((lbl for lbl, p in self._part_labels.items()
                        if p.index == self._part_index), None)
            if cur:
                self.partition_part_var.set(cur)
            return False
        self.partition_part_var.set(label)
        self._on_partition_select()
        return True

    def _on_partition_select(self):
        p = self._part_labels.get(self.partition_part_var.get())
        if p is None or self._card is None:
            return
        self._clear_tree()
        if not p.browsable:
            self.set(status="This partition isn't a browsable ext filesystem.")
            return
        self.set(status="")
        self._part_index = p.index
        self._enable_part_actions()
        self._refresh_marks()
        if self.partition_show_var.get() == "Changed":
            self._fill_changed_only()
        else:
            self._populate_dir("", "/")
        self._publish()

    def _enable_part_actions(self):
        self.set(can_part=self._part_index is not None,
                 can_find=self._part_index is not None,
                 can_all=any(q.browsable for q in self._part_labels.values()))

    # ------------------------------------------------------------------
    # the tree
    # ------------------------------------------------------------------
    def _populate_dir(self, parent, path):
        """Load *path*'s children under *parent* ("" = the root).  Honours
        Show: Unchanged by leaving replaced files out as folders load."""
        hide_changed = self.partition_show_var.get() == "Unchanged"
        try:
            entries = self._card.list_dir(self._part_index, path)
        except Exception as e:                   # noqa: BLE001
            self.log("Could not list %s: %s" % (path, e), "error")
            self.set(status="Error: %s" % e)
            return
        kids = []
        for e in entries:
            if e.is_dir:
                self._nodes[e.path] = {"name": e.name, "dir": True,
                                       "size": "", "type": "folder",
                                       "changed": ""}
                self._dirs.add(e.path)
            else:
                mark = self._marks.get(e.path, "")
                if mark and hide_changed:
                    continue
                typ = ("symlink → " + (e.link_target or "?")
                       if e.is_symlink else "file")
                self._nodes[e.path] = {"name": e.name, "dir": False,
                                       "size": human(e.size), "type": typ,
                                       "changed": mark}
            kids.append(e.path)
        self._children[parent] = kids
        self._populated.add(parent)

    def _refresh_marks(self):
        from ...core import card_edits
        marks = {}
        if self._image_path and self._part_index is not None:
            try:
                for p, e in card_edits.replaced(
                        self._image_path, self._part_index).items():
                    when = str(e.get("when") or "")[:10]
                    marks[p] = ("replaced %s" % when) if when else "replaced"
            except Exception:                    # noqa: BLE001
                marks = {}
        self._marks = marks

    def _fill_changed_only(self):
        """Just the files replaced on this image, under their own folders,
        fully expanded, built from the journal (Tk ``_pex_fill_changed_only``)."""
        paths = sorted(self._marks)
        if not paths:
            self.set(status="Nothing replaced on this partition yet — Show: "
                            "Changed lists the files you replace here.")
            return
        made = set()
        missing = 0
        for p in paths:
            names = [n for n in p.strip("/").split("/") if n]
            if not names:
                continue
            fs = ""
            for name in names[:-1]:
                parent, fs = fs, fs + "/" + name
                if fs not in made:
                    self._nodes[fs] = {"name": name, "dir": True, "size": "",
                                       "type": "folder", "changed": ""}
                    self._children.setdefault(parent, []).append(fs)
                    self._children.setdefault(fs, [])
                    made.add(fs)
                    self._dirs.add(fs)
                    self._populated.add(fs)
                    self._open.add(fs)
            try:
                size = human(self._card.file_size(self._part_index, p))
                typ = "file"
            except Exception:                    # noqa: BLE001
                size, typ = "", "not on the card now"
                missing += 1
            self._nodes[p] = {"name": names[-1], "dir": False, "size": size,
                              "type": typ, "changed": self._marks[p]}
            self._children.setdefault(p.rsplit("/", 1)[0], []).append(p)
        self._populated.add("")
        self.set(status="%d file%s replaced on this partition%s."
                        % (len(paths), "" if len(paths) == 1 else "s",
                           " (%d no longer on the card)" % missing
                           if missing else ""))

    def _flatten(self):
        rows = []

        def walk(parent, depth):
            for path in self._children.get(parent, ()):
                n = self._nodes.get(path)
                if n is None:
                    continue
                is_open = n["dir"] and path in self._open
                rows.append({"id": path, "name": n["name"], "depth": depth,
                             "dir": n["dir"], "open": is_open,
                             "size": n["size"], "type": n["type"],
                             "changed": n["changed"]})
                if is_open:
                    walk(path, depth + 1)
        walk("", 0)
        return rows

    def _publish(self):
        self.set(rows=self._flatten())

    def _clear_tree(self):
        self._nodes = {}
        self._children = {}
        self._dirs = set()
        self._populated = set()
        self._open = set()
        self._sel = None
        self._preview_seq += 1              # drop any in-flight render
        self._search_cache = None
        self._search_state = ("", -1)
        self.set(rows=[], sel=None, sel_dir=False, preview=None,
                 can_part=False, can_find=False, can_all=False)

    @rpc
    def toggle(self, path, open_=None):
        """Expand / collapse a folder row; a folder loads on first open."""
        if path not in self._dirs:
            return False
        want = (path not in self._open) if open_ is None else bool(open_)
        if want:
            if path not in self._populated:
                self._populate_dir(path, path)
            self._open.add(path)
        else:
            self._open.discard(path)
        self._publish()
        return True

    @rpc
    def set_show(self, value):
        if value not in SHOW_CHOICES:
            return False
        self.partition_show_var.set(value)
        self._apply_show()
        return True

    def _apply_show(self):
        """Rebuild the tree for the Show filter (All / Changed / Unchanged).

        Tk refused this while busy because its rebuild re-enabled the extract
        buttons; here the page greys those from ``busy`` itself, and an
        extract runs on its own card handle, so the tree stays a live view
        mid-extract.  A Replace still waits: the image is re-opened (with the
        Show choice) the moment it ends."""
        if self._busy_kind == "replace" or self._card is None:
            return
        part = self._part_index
        if part is None:
            return
        self._refresh_marks()
        self._clear_tree()
        self._part_index = part
        self._enable_part_actions()
        self.set(status="")
        if self.partition_show_var.get() == "Changed":
            self._fill_changed_only()
        else:
            self._populate_dir("", "/")
        self._publish()

    # ------------------------------------------------------------------
    # selection + preview
    # ------------------------------------------------------------------
    @rpc
    def select(self, path, box_w=0, box_h=0):
        if path not in self._nodes:
            return False
        if box_w and box_h:
            self._box = (box_w, box_h)
        else:
            box_w, box_h = self._box
        self._sel = path
        is_dir = path in self._dirs
        self.set(sel=path, sel_dir=is_dir)
        if is_dir:
            self._set_preview("")
            return True
        self._preview_seq += 1
        ext = os.path.splitext(path)[1].lower()
        if self.get("have_pil") and ext in (IMAGE_EXTS + FONT_EXTS):
            self._render_preview(path, ext, self._preview_seq,
                                 box_w, box_h)
            return True
        try:
            data = self._card.preview(self._part_index, path)
        except Exception as e:                   # noqa: BLE001
            self._set_preview("(error: %s)" % e)
            return True
        if data is None:
            self._set_preview(
                "(binary or too large to preview — extract it to view)")
        else:
            self._set_preview(decode_preview(data))
        return True

    def _set_preview(self, text):
        self.set(preview={"kind": "text", "text": text, "caption": ""}
                 if text else None)

    def _render_preview(self, path, ext, seq, box_w, box_h):
        from ...core import image as image_mod
        card, part = self._card, self._part_index
        self._set_preview("(reading %s…)" % os.path.basename(path))
        w = max(80, int(box_w or 330) - 10)
        h = max(80, int(box_h or 250) - 10)
        is_font = ext in FONT_EXTS

        def _work():
            png = caption = err = None
            try:
                data = card.preview(part, path, cap=RENDER_CAP)
            except Exception as e:               # noqa: BLE001
                data = None
                err = "(error: %s)" % e
            if data is None and err is None:
                err = ("(too big to preview here — over %s; extract it to "
                       "view)" % human(RENDER_CAP))
            elif data is not None:
                if is_font:
                    png = image_mod.font_sample_png(data, w, h)
                    caption = "%s · %s" % (ext.lstrip(".").upper(),
                                           human(len(data)))
                    if png is None:
                        err = "(not a font Pillow can read)"
                else:
                    png = image_mod.thumbnail_png_bytes(data, w, h)
                    info = image_mod.detect_image_info_bytes(data, path)
                    if info is not None:
                        caption = "%s · %d × %d · %s" % (
                            info.fmt or ext.lstrip(".").upper(), info.width,
                            info.height, human(len(data)))
                    if png is None:
                        err = "(not an image Pillow can read)"
            try:
                self.ctx.loop.post(self._preview_done, seq, png, caption, err)
            except Exception:                    # noqa: BLE001
                pass

        threading.Thread(target=_work, daemon=True,
                         name="pad-pex-preview").start()

    def _preview_done(self, seq, png, caption, err):
        if seq != self._preview_seq:
            return                              # a later selection won
        if png is None:
            self._set_preview(err or "(nothing to preview)")
            return
        try:
            if not self._preview_dir:
                self._preview_dir = tempfile.mkdtemp(prefix="pad_pex_")
            out = os.path.join(self._preview_dir, "preview_%d.png" % seq)
            with open(out, "wb") as f:
                f.write(png)
        except OSError:
            self._set_preview("(could not draw this preview)")
            return
        old = self._preview_file
        self._preview_file = out
        if old and old != out:
            try:
                os.remove(old)
            except OSError:
                pass
        self.set(preview={"kind": "image", "src": out,
                          "caption": caption or ""})

    # ------------------------------------------------------------------
    # find
    # ------------------------------------------------------------------
    def _partition_paths(self, part_index):
        """Sorted absolute file paths in *part_index*, walked once per
        image+partition and cached (Find Next and Find in Partition share it)."""
        key = (self._image_path, part_index)
        cache = self._search_cache
        if cache and cache[0] == key:
            return cache[1]
        paths = []
        try:
            reader = self._card.reader(part_index)
            for rel, _ino, _node in reader.iter_regular_files(max_depth=64,
                                                              min_size=0):
                paths.append("/" + rel.strip("/"))
        except Exception:                        # noqa: BLE001
            pass
        paths.sort()
        self._search_cache = (key, paths)
        return paths

    @rpc
    def find_next(self, query=None):
        """Find Next (Tk ``_pex_find_next``).  Works mid-extract, as the Tk
        button did: the walk and the reveal use the browse handle, the
        extract its own."""
        if query is not None:
            self.partition_search_var.set(query)
        if self._card is None or self._part_index is None:
            return False
        raw = (self.partition_search_var.get() or "").strip()
        q = raw.lower()
        if not q:
            return False
        self._unfilter_for_reveal()
        paths = self._partition_paths(self._part_index)
        last_q, last_i = self._search_state
        start = last_i + 1 if last_q == q else 0
        order = list(range(start, len(paths))) + list(range(0, start))
        for i in order:
            if q in paths[i].lower():
                self._search_state = (q, i)
                self._reveal(paths[i])
                self.set(status="")
                return paths[i]
        self._search_state = (q, -1)
        self.set(status="No file path contains “%s”." % raw)
        return False

    def _unfilter_for_reveal(self):
        if self.partition_show_var.get() != "All":
            self.partition_show_var.set("All")
            self._apply_show()

    def _reveal(self, path):
        """Expand the lazy tree down to *path* and select it."""
        names = [p for p in path.strip("/").split("/") if p]
        fs = ""
        for name in names[:-1]:
            fs = fs + "/" + name
            if fs not in self._dirs:
                break
            if fs not in self._populated:
                self._populate_dir(fs, fs)
            self._open.add(fs)
        self._publish()
        if path in self._nodes:
            self.select(path)

    # ---- Find in Partition Explorer (from a Replace tab) ---------------
    def find_in_partition(self, kind, rel, assets_dir=None):
        """Jump from a Replace-tab row to the file it came from on the card
        (Tk ``_asset_find_in_partition``).  *kind* is "audio" / "video" /
        "image"; *assets_dir* the Replace tab's scanned folder (defaults to
        the window's ``_<kind>_scan_dir`` when a tab provides one)."""
        from ...core import card_paths
        if assets_dir is None:
            attr = {"audio": "_audio_scan_dir", "video": "_video_scan_dir"}\
                .get(kind, "_image_scan_dir")
            try:
                assets_dir = getattr(self.window, attr, "") or ""
            except Exception:                    # noqa: BLE001
                assets_dir = ""
        want_basename = None
        if kind == "video":
            target, note = card_paths.video_card_path(assets_dir, rel)
        elif kind == "image":
            target, note = card_paths.image_card_path(assets_dir, rel)
        else:
            want_basename, note = card_paths.audio_card_hint(rel)
            target = None
            if want_basename is None:
                compat.messagebox.showinfo("Find in Partition Explorer", note)
                return False
        if kind in ("video", "image") and target is None:
            compat.messagebox.showinfo("Find in Partition Explorer", note)
            return False

        self.window.select_tab(self.ns)
        if self._card is None:
            self._default_from_extract()
        if self._card is None:
            compat.messagebox.showinfo(
                "Find in Partition Explorer",
                "Pick the card image these assets were extracted from "
                "(the Card Image box at the top of this tab), then try "
                "again.")
            return False

        order = [p.index for p in self._part_labels.values() if p.browsable]
        if self._part_index in order:
            order.remove(self._part_index)
            order.insert(0, self._part_index)
        hit = hit_part = None
        for idx in order:
            paths = self._partition_paths(idx)
            if target is not None:
                if target in paths:
                    hit, hit_part = target, idx
                    break
            else:
                match = next((p for p in paths
                              if os.path.basename(p) == want_basename), None)
                if match:
                    hit, hit_part = match, idx
                    break
        if hit is None:
            missing = target or want_basename
            self.log("Find in Partition: %s isn't on %s."
                     % (missing, os.path.basename(self._image_path or "")),
                     "warning")
            compat.messagebox.showinfo(
                "Find in Partition Explorer",
                "Couldn't find\n\n%s\n\non %s.\n\nThe open card image may be "
                "a different game or firmware than these assets were "
                "extracted from." % (missing, os.path.basename(
                    self._image_path or "this image")))
            return False
        if hit_part != self._part_index:
            label = next((lbl for lbl, p in self._part_labels.items()
                          if p.index == hit_part), None)
            if label:
                self.partition_part_var.set(label)
                self._on_partition_select()
        self._unfilter_for_reveal()
        self._reveal(hit)
        self.set(status=note or "")
        self.log("Find in Partition: %s → %s%s"
                 % (rel, hit, ("  (%s)" % note) if note else ""), "info")
        return hit

    _asset_find_in_partition = find_in_partition

    # ------------------------------------------------------------------
    # context menu: properties / copy path
    # ------------------------------------------------------------------
    def _replace_history(self, card_path):
        from ...core import card_edits
        out = []
        part = self._part_index
        for e in card_edits.edits_for(self._image_path):
            if e.get("path") != card_path:
                continue
            if (part is not None and e.get("partition") is not None
                    and e.get("partition") != part):
                continue
            old, new = e.get("old_size"), e.get("new_size")
            sizes = ""
            if isinstance(old, int) and isinstance(new, int):
                sizes = " (%s → %s)" % (human(old), human(new))
            out.append({"when": "%s%s" % (e.get("when") or "?", sizes),
                        "source": e.get("source") or ""})
        return out

    @rpc
    def properties(self, path):
        """Properties… (Tk ``_pex_show_properties``): name, kind, size,
        partition, on-card path, mounted path and the replace history.  A
        folder's size is computed on a worker; the box opens when it lands."""
        node = self._nodes.get(path)
        if node is None:
            return False
        dev = ("sda%d" % (self._part_index + 1)
               if self._part_index is not None else "?")
        is_dir = path in self._dirs
        kind = "Folder" if is_dir else (node.get("type") or "File")
        name = os.path.basename(path) or path

        def _show(size_line):
            rows = [["Name:", name], ["Kind:", kind]]
            if size_line:
                rows.append(["Size:", size_line])
            rows += [["Partition:", dev], ["Path:", path],
                     ["Mounted at:", "<mount point>%s" % path]]
            self.set(props={"title": "Properties — %s" % name, "rows": rows,
                            "replaced": self._replace_history(path),
                            "path": path})

        if not is_dir:
            _show(node.get("size") or "")
            return True
        card, part = self._card, self._part_index
        self._props_seq += 1
        seq = self._props_seq
        self.set(status="Sizing %s…" % name)

        def _work():
            try:
                n, b = card.dir_stats(part, path)
                line = "%s in %d file%s" % (human(b), n, "" if n == 1 else "s")
            except Exception as e:               # noqa: BLE001
                line = "(unavailable: %s)" % e

            def _done():
                if seq != self._props_seq:
                    return
                self.set(status="")
                _show(line)
            try:
                self.ctx.loop.post(_done)
            except Exception:                    # noqa: BLE001
                pass

        threading.Thread(target=_work, daemon=True,
                         name="pad-pex-sizing").start()
        return True

    @rpc
    def set_widths(self, widths):
        """Column widths the user dragged (every ttk.Treeview header resized
        its column).  Kept for the session, as Tk did for this tree: it
        never saved them under column_widths."""
        clean = {str(k): int(v) for k, v in (widths or {}).items()
                 if k in ("name", "size", "type")
                 and isinstance(v, (int, float)) and 20 <= v <= 4000}
        self.set(widths=clean or None)
        return bool(clean)

    @rpc
    def close_props(self):
        self.set(props=None)
        return True

    @rpc
    def copy_path(self, path):
        root = getattr(self.app, "root", None)
        if root is not None:
            root.clipboard_clear()
            root.clipboard_append(path)
        return path

    # ------------------------------------------------------------------
    # extract
    # ------------------------------------------------------------------
    @rpc
    def extract_selected(self, path=None):
        if self._busy or self._card is None:
            return False
        if path is not None and path in self._nodes:
            self.select(path)
        sel = self._sel
        if not sel:
            return False
        if sel in self._dirs:
            out_dir = self.window.ask_folder(
                "pex_extract",
                "Choose a folder to extract this directory into")
            if out_dir:
                self._run_extract("dir", sel, out_dir, "sel")
                return True
        else:
            out = self.window.ask_save(
                "pex_extract", "Extract file as…",
                initialfile=(os.path.basename(sel) or "file"))
            if out:
                self._run_extract("file", sel, out, "sel")
                return True
        return False

    @rpc
    def extract_partition(self):
        if self._busy or self._part_index is None:
            return False
        out_dir = self.window.ask_folder(
            "pex_extract", "Choose a folder to extract the whole partition into")
        if out_dir:
            self._run_extract("dir", "/", out_dir, "part",
                              top_name="sda%d" % (self._part_index + 1))
            return True
        return False

    @rpc
    def extract_all(self):
        if self._busy or self._card is None:
            return False
        parts = sorted((p for p in self._part_labels.values() if p.browsable),
                       key=lambda p: p.index)
        if not parts:
            return False
        out_dir = self.window.ask_folder(
            "pex_extract", "Choose a folder to extract all partitions into")
        if out_dir:
            self._run_extract("all", parts, out_dir, "all")
            return True
        return False

    def do_extract(self, kind, path, dest, part=None, image_path=None,
                   tree_prog=None, file_prog=None, chunk_prog=None,
                   top_name=None):
        """Synchronous extract over a FRESH card handle (Tk
        ``_pex_do_extract``); runs on the worker, never touches the store."""
        from ...plugins.stern.explorer import CardImage
        part = self._part_index if part is None else part
        image_path = image_path or self._image_path
        with CardImage(image_path) as c:
            if kind == "file":
                n = c.extract_file(part, path, dest, progress=file_prog)
                return "Extracted %s (%s)." % (os.path.basename(dest),
                                               human(n))
            if kind == "all":
                nf = nb = 0
                for p in path:
                    f_, b_ = c.extract_tree(
                        p.index, "/", dest, progress=tree_prog,
                        chunk_progress=chunk_prog,
                        top_name="sda%d" % (p.index + 1))
                    nf += f_
                    nb += b_
                return ("Extracted %d partition%s — %d file%s (%s) to %s." % (
                    len(path), "" if len(path) == 1 else "s",
                    nf, "" if nf == 1 else "s", human(nb),
                    os.path.normpath(dest)))
            nf, nb = c.extract_tree(part, path, dest, progress=tree_prog,
                                    chunk_progress=chunk_prog,
                                    top_name=top_name)
            shown = os.path.normpath(
                os.path.join(dest, top_name) if top_name else dest)
            return "Extracted %d file%s (%s) to %s." % (
                nf, "" if nf == 1 else "s", human(nb), shown)

    def _run_extract(self, kind, path, dest, btn, top_name=None):
        """Extract on a worker with a live Cancel (Tk ``_pex_run_extract``)."""
        self._busy = True
        self._busy_kind = "extract"
        cancel = threading.Event()
        self._cancel = cancel
        part = self._part_index
        image_path = self._image_path
        state = {"note": "", "done": None}

        def _check():
            if cancel.is_set():
                raise _Cancelled()

        def _tree_prog(nf, nb, _rel):
            _check()
            state["note"] = "%d file%s (%s)" % (nf, "" if nf == 1 else "s",
                                               human(nb))

        def _file_prog(written, size):
            _check()
            state["note"] = "%s / %s" % (human(written), human(size))

        def _work():
            try:
                msg = self.do_extract(
                    kind, path, dest, part, image_path,
                    tree_prog=_tree_prog, file_prog=_file_prog,
                    chunk_prog=lambda _w, _s: _check(), top_name=top_name)
            except _Cancelled:
                msg = "Extract cancelled — partial files may remain."
            except Exception as e:               # noqa: BLE001
                msg = "Extract failed: %s" % e
            state["done"] = msg

        self.set(busy={"kind": "extract", "text": "Extracting…"},
                 busy_btn=btn, cancelling=False, status="")
        what = ("all %d partitions" % len(path) if kind == "all"
                else top_name if top_name
                else "%s from partition %s" % (path, part))
        self.log("Extracting %s to %s…" % (what, os.path.normpath(dest)),
                 "info")
        threading.Thread(target=_work, daemon=True,
                         name="pad-pex-extract").start()
        self._extract_tick(state)

    @rpc
    def cancel_extract(self):
        if self._cancel is not None and self._busy_kind == "extract":
            self._cancel.set()
            self.set(cancelling=True)
            return True
        return False

    def _extract_tick(self, state):
        if state["done"] is not None:
            self._finish(state["done"])
            return
        note = state["note"]
        self.set(busy={"kind": "extract",
                       "text": "Extracting…%s" % (("  " + note) if note
                                                  else "")})
        self.ctx.loop.after(90, self._extract_tick, state)

    def _finish(self, msg):
        self._busy = False
        self._busy_kind = None
        self._cancel = None
        self.set(busy=None, busy_btn=None, cancelling=False, status=msg)
        self._enable_part_actions()
        self.log(msg, "error" if ("failed" in msg.split(":")[0].lower())
                 else "info")

    # ------------------------------------------------------------------
    # replace (the one write)
    # ------------------------------------------------------------------
    @rpc
    def replace(self, path):
        """Right-click → Replace with… (Tk ``_pex_replace_selected``)."""
        if self._busy or self._card is None or path in self._dirs:
            return False
        try:
            cur_size = self._card.file_size(self._part_index, path)
        except Exception:                        # noqa: BLE001
            cur_size = None
        src = self.window.ask_open(
            "pex_replace", "Replace %s" % (os.path.basename(path) or path))
        if not src:
            return False
        try:
            new_size = os.path.getsize(src)
        except OSError:
            new_size = None
        if cur_size is None or new_size is None or new_size == cur_size:
            note = "The file's validation record is refreshed automatically."
        else:
            note = (
                "This file is a different size (%s → %s), so it is %s on the "
                "card: the card image is mounted through the Linux filesystem "
                "driver (WSL2) and the file's blocks are re-allocated, exactly "
                "like a full-size video replacement. Its validation record — "
                "digests AND stored size — is refreshed automatically."
                % (human(cur_size), human(new_size),
                   "grown" if new_size > cur_size else "shrunk"))
        if not compat.messagebox.askyesno(
                "Replace on card",
                "This WRITES to the card image:\n\n  %s\n\nreplacing\n\n"
                "  %s  (%s)\n\nwith\n\n  %s\n\n%s  Keep a backup of the image "
                "if it's precious.\n\nReplace it?"
                % (os.path.normpath(self.partition_image_var.get() or ""),
                   path,
                   human(cur_size) if cur_size is not None else "size unknown",
                   os.path.normpath(src), note),
                icon="warning"):
            return False
        self._run_replace(path, src, cur_size)
        return True

    def _run_replace(self, path, src, cur_size=None):
        """Worker-thread replace; no Cancel (Tk ``_pex_run_replace``)."""
        self._busy = True
        self._busy_kind = "replace"
        part = self._part_index
        image_path = self._image_path
        state = {"done": None, "log": []}
        self.set(busy={"kind": "replace", "text": "Replacing…"},
                 busy_btn=None, status="")
        self.log("Replacing %s on partition sda%s…"
                 % (path, (part + 1) if part is not None else "?"), "info")

        def _work():
            try:
                from ...plugins.stern.explorer import CardImage
                with CardImage(image_path) as c:
                    n, refreshed = c.replace_file(
                        part, path, src, allow_resize=True,
                        log=lambda m, lvl="info": state["log"].append(
                            (m, lvl)))
                state["n"] = n
                resized = ""
                if cur_size is not None and n != cur_size:
                    resized = (" — %s on the card from %s"
                               % ("grown" if n > cur_size else "shrunk",
                                  human(cur_size)))
                state["done"] = "Replaced %s (%s)%s%s." % (
                    path, human(n), resized,
                    ", validation record refreshed" if refreshed
                    else "; not in the validation manifest — no record to "
                         "refresh")
            except Exception as e:               # noqa: BLE001
                state["done"] = "Replace failed: %s" % e

        def _tick():
            if state["done"] is None:
                self.ctx.loop.after(90, _tick)
                return
            msg = state["done"]
            for line, lvl in state["log"]:
                self.log(line, lvl)
            self._finish(msg)
            if not msg.startswith("Replace failed"):
                from ...core import card_edits
                card_edits.record_replace(image_path, part, path, cur_size,
                                          state.get("n"), src)
                self._report_extract_impact(image_path, path)
                self.open_image()
                self.set(status=msg)

        threading.Thread(target=_work, daemon=True,
                         name="pad-pex-replace").start()
        _tick()

    def _report_extract_impact(self, image_path, card_path):
        """Say in the log whether a finished Replace makes the open extract
        stale (Tk ``_pex_report_extract_impact``)."""
        from ...core import card_paths, extract_source
        var = getattr(self.window, "write_assets_var", None)
        assets = ((var.get() if var is not None else "") or "").strip()
        if not assets:
            return
        rec = extract_source.read_extract_source(assets) or {}
        recorded = rec.get("input_path") or ""
        if (not recorded or os.path.normcase(os.path.abspath(recorded))
                != os.path.normcase(os.path.abspath(image_path))):
            return
        if card_paths.is_extract_source(assets, card_path):
            self.log("This image is where %s was extracted from, and %s is "
                     "one of the files those assets came from — re-run "
                     "Extract so the Replace tabs match the card."
                     % (os.path.basename(assets), card_path), "warning")
        else:
            self.log("This image is where %s was extracted from, but %s is "
                     "not one of the files those assets came from — no "
                     "re-Extract needed."
                     % (os.path.basename(assets), card_path), "info")

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def _close_card(self):
        if self._card is not None:
            try:
                self._card.close()
            except Exception:                    # noqa: BLE001
                pass
        self._card = None
        self._part_index = None
        self._clear_tree()


TAB = PartitionsTab
