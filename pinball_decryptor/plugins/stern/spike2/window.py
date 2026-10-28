"""Card files mapped into the emulator without committing their size (PAD-777).

The emulator hands the game ``image.bin`` (and a sound bank) as ONE region backed
straight by a view of the file.  That view was a private copy-on-write map
(``mmap.ACCESS_COPY``), and Windows charges a copy-on-write view's whole size against
the commit limit (RAM plus page file) the moment it is mapped, whether or not a page
is ever written: an Iron Maiden emulator committed 1.9 GB and touched 43 MB of it, and
three bank encoders side by side ran a user's PC out of commit (``UC_ERR_NOMEM``).

A read-only view commits nothing: its pages are the file's.  The game never writes the
card (Iron Maiden LE 1.18's boot, params derive, decodes and play-table walk write it
0 times), and most emulators never write it either.  The few that do (the Write's
integrity check lays the re-encoded sounds over image.bin; a bank's encode writes the
bank's bodies into its window) need private pages, so :class:`WindowUc` swaps a window
for a copy-on-write view of the same file the first time anything writes it, the whole
window at once, and only that emulator pays for it:

* a host-side ``mem_write`` into a read-only window swaps it first;
* a guest store into one stops the run with ``UC_ERR_WRITE_PROT`` (Unicorn cannot
  remap from inside a store: its TLB still names the old page);
  :meth:`WindowUc.emu_start` swaps the window and resumes at the faulting instruction,
  which QEMU leaves exactly as it was before the store (an STM across two pages, a
  Thumb store: each runs once).

Not page by page: a window Unicorn has split runs every later guest access on a slower
path (one private page anywhere in Iron Maiden's image.bin window took its params
derive from 11 s to 28-31 s), and a bank encode's 56 MB body made a region a page.
Nor, where it can be helped, by swapping: a window unmapped and mapped again, even
whole and with nothing written, ran the same derive at 25 s.  So an emulator that is
going to write a window maps it copy-on-write from the start (``copy=True``: the
Write's integrity check, a bank's window), and the swap is only the safety net that
keeps an unforeseen write from failing.
"""

import ctypes
import mmap

from unicorn import UC_ERR_WRITE_PROT, UC_HOOK_MEM_WRITE_PROT, UC_PROT_ALL, Uc, UcError
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_PC

PAGE = 0x1000


class _PyBuffer(ctypes.Structure):
    _fields_ = [("buf", ctypes.c_void_p), ("obj", ctypes.py_object),
                ("len", ctypes.c_ssize_t), ("itemsize", ctypes.c_ssize_t),
                ("readonly", ctypes.c_int), ("ndim", ctypes.c_int),
                ("format", ctypes.c_char_p), ("shape", ctypes.c_void_p),
                ("strides", ctypes.c_void_p), ("suboffsets", ctypes.c_void_p),
                ("internal", ctypes.c_void_p)]


_get_buffer = ctypes.pythonapi.PyObject_GetBuffer
_get_buffer.argtypes = [ctypes.py_object, ctypes.POINTER(_PyBuffer), ctypes.c_int]
_get_buffer.restype = ctypes.c_int
_release_buffer = ctypes.pythonapi.PyBuffer_Release
_release_buffer.argtypes = [ctypes.POINTER(_PyBuffer)]
_release_buffer.restype = None


class FileView(object):
    """A view of the open file *fileobj* and the address it is mapped at:
    read-only (no commit) or, with *copy*, private copy-on-write.  ``ctypes``
    will not take the address of a read-only buffer, so the buffer protocol is
    asked for it.  :meth:`close` drops the exported pointer, then the view."""

    def __init__(self, fileobj, copy=False):
        self.mm = mmap.mmap(fileobj.fileno(), 0,
                            access=mmap.ACCESS_COPY if copy else mmap.ACCESS_READ)
        self._pb = _PyBuffer()
        if _get_buffer(self.mm, ctypes.byref(self._pb), 0) != 0:
            self.mm.close()
            raise OSError("no address for the file view")
        self.address = self._pb.buf

    def close(self):
        if self._pb is not None:
            _release_buffer(ctypes.byref(self._pb))
            self._pb = None
        try:
            self.mm.close()
        except Exception:                               # noqa: BLE001
            pass


class _Window(object):
    __slots__ = ("lo", "size", "fileobj", "perms", "view", "copied")

    def __init__(self, lo, size, fileobj, perms, view):
        self.lo, self.size, self.fileobj, self.perms = lo, size, fileobj, perms
        self.view, self.copied = view, False

    @property
    def hi(self):
        return self.lo + self.size


class WindowUc(object):
    """A Unicorn engine (``Uc(arch, mode)``) whose card windows
    (:meth:`map_window`) are read-only views of their files until something
    writes one.  Everything else is the engine's: an attribute it does not
    define is looked up on the engine once and kept, so a hot ``reg_read``
    costs what it did."""

    def __init__(self, arch, mode):
        self._uc = Uc(arch, mode)
        self._windows = []
        self._fault = None
        #: windows swapped for a copy-on-write view (a write reached them)
        self.copied_windows = 0

        def on_write_prot(uc, access, address, size, value, ud):
            if self._window_of(address) is not None:
                self._fault = address
            return False
        self._uc.hook_add(UC_HOOK_MEM_WRITE_PROT, on_write_prot)

    def __getattr__(self, name):
        v = getattr(self._uc, name)
        setattr(self, name, v)
        return v

    # ---- the windows ---------------------------------------------------------
    def map_window(self, lo, size, fileobj, perms, copy=False):
        """Map the first *size* bytes of the open file *fileobj* at *lo*: a
        read-only view the guest reads with *perms* (less write), which a write
        swaps for a copy-on-write view (:meth:`copy_window`); with *copy*, a
        copy-on-write view from the start, for an emulator that will write it."""
        view = FileView(fileobj, copy=copy)
        if copy:
            perms = UC_PROT_ALL
        try:
            self._uc.mem_map_ptr(lo, size, perms, view.address)
        except Exception:
            view.close()
            raise
        w = _Window(lo, size, fileobj, perms, view)
        w.copied = bool(copy)
        self._windows.append(w)

    def unmap_window(self, lo):
        """Unmap the window at *lo* and close its view."""
        for w in [w for w in self._windows if w.lo == lo]:
            self._windows.remove(w)
            try:
                self._uc.mem_unmap(w.lo, w.size)
            finally:
                w.view.close()

    def _window_of(self, addr):
        for w in self._windows:
            if w.lo <= addr < w.hi:
                return w
        return None

    def copy_window(self, w):
        """Swap window *w* for a private copy-on-write view of its file, in
        one piece (outside a running store: see the module notes)."""
        if w.copied:
            return
        cow = FileView(w.fileobj, copy=True)
        try:
            self._uc.mem_unmap(w.lo, w.size)
            self._uc.mem_map_ptr(w.lo, w.size, UC_PROT_ALL, cow.address)
        except Exception:
            cow.close()
            raise
        w.view.close()
        w.view, w.copied, w.perms = cow, True, UC_PROT_ALL
        self.copied_windows += 1

    # ---- the engine calls that can write a window -----------------------------
    def mem_write(self, address, data):
        if self._windows:
            end = address + len(data)
            for w in self._windows:
                if not w.copied and address < w.hi and end > w.lo:
                    self.copy_window(w)
        return self._uc.mem_write(address, data)

    def emu_start(self, begin, until, timeout=0, count=0):
        while True:
            self._fault = None
            try:
                return self._uc.emu_start(begin, until, timeout, count)
            except UcError as e:
                if e.errno != UC_ERR_WRITE_PROT or self._fault is None:
                    raise
                w = self._window_of(self._fault)
                if w is None or w.copied:
                    raise
                self.copy_window(w)
                # QEMU leaves the faulting store as it was: run it again
                pc = self._uc.reg_read(UC_ARM_REG_PC)
                begin = pc | (1 if self._uc.reg_read(UC_ARM_REG_CPSR) & 0x20 else 0)
