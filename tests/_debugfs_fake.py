"""Shared test helper: debugfs's session protocol (``ext4_grow._debugfs_session``)
over an in-memory tree, so the debugfs delivery's own logic is tested where
e2fsprogs is not installed (the macOS runner).  The real tool is exercised by the
tests marked as needing e2fsprogs.

What it keeps of the real thing: each command is echoed to stdout as
``debugfs: <command>`` ahead of what it prints, ``stat`` prints ``Inode:`` and
``User: ... Size: N`` lines, and a failed command says so on stderr without
naming the command it was.

Not a test module itself (no ``test_*`` name) so pytest won't collect it.
"""

import os
import shlex

#: the commands that change the filesystem, which a session must be writable for
WRITES = ("write", "kill_file", "rm", "mkdir", "set_inode_field")


class FakeDebugfs:
    """Stands in for ``ext4_grow._debugfs_session``.  *files* maps a card path
    (``"/a/b"``) to its size, *dirs* names the directories (``"/"`` is always
    there).  *fail* maps a card path to the complaint its ``write`` gives instead
    of writing, and *short* a card path to the size its ``write`` comes out at.
    Every session is kept in ``sessions`` as ``(writable, [commands], dev)``,
    and every ``set_inode_field`` in ``fields``."""

    def __init__(self, files=(), dirs=(), fail=None, short=None):
        self.files = dict(files)
        self.dirs = set(dirs) | {"/"}
        self.fail = dict(fail or {})
        self.short = dict(short or {})
        self.fields = {}
        self.sessions = []

    def __call__(self, tools, dev, commands, timeout, writable=False):
        self.sessions.append((writable, list(commands), dev))
        out, err = [], ["debugfs 1.47.0 (5-Feb-2023)"]
        for cmd in commands:
            out.append("debugfs: " + cmd)
            verb, *args = shlex.split(cmd)
            assert writable or verb not in WRITES, "%s in a read-only session" % cmd
            getattr(self, "_" + verb)(args, out, err)
        return 0, "".join(line + "\n" for line in out), \
            [line for line in err if not line.startswith("debugfs ")]

    @staticmethod
    def _parent(p):
        return p.rsplit("/", 1)[0] or "/"

    def _stat(self, args, out, err):
        p = args[0]
        if p in self.files:
            out += ["Inode: 12   Type: regular    Mode:  0644   Flags: 0x80000",
                    "User:     0   Group:     0   Project:     0   Size: %d"
                    % self.files[p]]
        elif p in self.dirs:
            out += ["Inode: 11   Type: directory    Mode:  0755   Flags: 0x80000",
                    "User:     0   Group:     0   Project:     0   Size: 4096"]
        else:
            err.append("%s: File not found by ext2_lookup " % p)

    def _write(self, args, out, err):
        src, p = args
        if p in self.files or p in self.dirs:
            err.append("write: Ext2 file already exists ")
        elif self._parent(p) not in self.dirs:
            err.append("write: Ext2 inode is not a directory ")
        elif p in self.fail:
            err.append(self.fail[p])
        else:
            self.files[p] = self.short.get(p, os.path.getsize(src))
            out.append("Allocated inode: 13")

    def _kill_file(self, args, out, err):
        if args[0] not in self.files:
            err.append("kill_file: File not found by ext2_lookup ")

    def _rm(self, args, out, err):
        if self.files.pop(args[0], None) is None:
            err.append("rm: File not found by ext2_lookup ")

    def _mkdir(self, args, out, err):
        p = args[0]
        if self._parent(p) not in self.dirs:
            err.append("mkdir: File not found by ext2_lookup ")
        else:
            self.dirs.add(p)

    def _set_inode_field(self, args, out, err):
        p, field, value = args
        self.fields[(p, field)] = value
