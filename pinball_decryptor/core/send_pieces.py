"""PAD-1435: a Send builds a changed file from 64 KB pieces the machine already has, anywhere among the files it
rewrites, not only at the same place of the same file (the 1 MiB delta of PAD-1433).

Measured on David's Godzilla update (V2.1 Kaiju + daveyvandy modes v38 -> Heisei V2.3, /games: 9.49 GB changed or
new): the 1 MiB delta in place keeps 1.47 GB; 64 KB pieces found anywhere 2.70 GB, every one of the extra in the
old copies of files the Send rewrites anyway, which the delta reads already (no extra card read).  4 KB pieces
find only 0.05 GB more, so aligned 64 KB it is, not content-defined chunks.

The files change in place (the game stopped), so a piece is copied out of a file before that file's own piece is
overwritten: :func:`plan` orders the machine's copies so that every copy reading a place runs before the one
writing it, and a copy caught in a cycle is sent instead.  The machine's side is ``resources/pieces/padpieces``
(one process for a card's worth of pieces; busybox needs two per piece)."""
import hashlib
from collections import defaultdict

PIECE = 64 << 10
#: pieces in one copy run at most (16 MB): the bar moves between runs' batches
RUN_MAX = 256
#: sent ranges are merged up to this (the delta's 1 MiB blocks)
SEND_MAX = 1 << 20
#: the places a piece's hash is remembered at (a piece found in thousands of places - zeros - needs few)
CANDIDATES = 8


def local_pieces(tree, node, piece=None):
    """The build's file as ``[(sha1 hex, length)]``, one per *piece* (:data:`PIECE`)."""
    piece = piece or PIECE
    out, buf = [], b""
    for _off, chunk in tree.chunks(node):
        buf += bytes(chunk)
        while len(buf) >= piece:
            out.append((hashlib.sha1(buf[:piece]).hexdigest(), piece))
            buf = buf[piece:]
    if buf:
        out.append((hashlib.sha1(buf).hexdigest(), len(buf)))
    return out


def _lengths(size, n, piece):
    return [min(piece, size - i * piece) for i in range(n)]


class PiecePlan:
    """What :func:`plan` decided: ``copies`` (in order: ``(src, soff, dst, doff, nbytes)``), ``sends``
    (``{dst: [(off, nbytes)]}``) and the bytes each way goes: ``kept`` (already in place), ``copied``, ``sent``."""

    def __init__(self):
        self.copies, self.sends = [], {}
        self.kept = self.copied = self.sent = 0
        self.broken = 0                     # runs a cycle turned into sends

    def copied_to(self, dst):
        return sum(c[4] for c in self.copies if c[2] == dst)


def plan(index, files, piece=None):
    """*index*: the machine's files a Send rewrites in place, ``{path: (size, [sha1 hex per piece])}``.
    *files*: ``[(dst, [(sha1 hex, length)])]``, the new content of each file written: a *dst* in *index* changes
    in place, any other is a new file.  Returns a :class:`PiecePlan`."""
    piece = piece or PIECE
    p = PiecePlan()
    lens = {path: _lengths(size, len(hs), piece) for path, (size, hs) in index.items()}
    newh = dict(files)
    # where each piece is, the places that stay as they are first (a copy from them waits on nothing)
    rewritten = set()
    for dst, pieces in files:
        old = index.get(dst)
        if old is None:
            continue
        hs = old[1]
        for i, key in enumerate(pieces):
            if not (i < len(hs) and hs[i] == key[0] and lens[dst][i] == key[1]):
                rewritten.add((dst, i))
    where = defaultdict(list)
    for stable in (True, False):
        for path, (_size, hs) in index.items():
            for j, h in enumerate(hs):
                if ((path, j) not in rewritten) == stable:
                    lst = where[(h, lens[path][j])]
                    if len(lst) < CANDIDATES:
                        lst.append((path, j))
    # each written piece: kept, copied (from a place), or sent; copies gathered into runs of equal shift
    runs = []                               # [dst, i0, src, j0, n, bytes]
    unsent = defaultdict(list)              # dst -> piece indexes to send
    for dst, pieces in files:
        old = index.get(dst)
        run = None
        for i, key in enumerate(pieces):
            if old is not None and (dst, i) not in rewritten:
                p.kept += key[1]
                run = None
                continue
            src = None
            if run is not None:
                s, j = run[2], run[3] + run[4]
                ok = (run[5] == run[4] * piece and j < len(index[s][1]) and index[s][1][j] == key[0]
                      and lens[s][j] == key[1] and run[4] < RUN_MAX
                      and not (s == dst and run[4] >= abs(j - i)))
                if ok:
                    run[4] += 1
                    run[5] += key[1]
                    continue
            for s, j in where.get(key, ()):
                if (s, j) != (dst, i):
                    src = (s, j)
                    break
            if src is None:
                unsent[dst].append(i)
                run = None
                continue
            run = [dst, i, src[0], src[1], 1, key[1]]
            runs.append(run)
    # the order: a run writing a place waits for every other run reading it
    readers = defaultdict(list)
    for r, (_d, _i, s, j, n, _b) in enumerate(runs):
        for k in range(j, j + n):
            readers[(s, k)].append(r)
    succ = [set() for _ in runs]
    indeg = [0] * len(runs)
    for r, (d, i, _s, _j, n, _b) in enumerate(runs):
        if d not in index:
            continue
        blockers = set()
        for k in range(i, i + n):
            blockers.update(readers.get((d, k), ()))
        blockers.discard(r)
        for q in blockers:
            succ[q].add(r)
        indeg[r] = len(blockers)
    order, done = [], [False] * len(runs)
    ready = [r for r in range(len(runs)) if not indeg[r]]
    left = len(runs)
    broken = set()
    while left:
        while ready:
            r = ready.pop()
            done[r] = True
            left -= 1
            order.append(r)
            for t in succ[r]:
                indeg[t] -= 1
                if not indeg[t] and not done[t]:       # a run sent instead (a cycle's) is settled already
                    ready.append(t)
        if not left:
            break
        # a cycle: the smallest run still waiting that others wait on is sent instead
        victim = min((r for r in range(len(runs)) if not done[r] and any(not done[t] for t in succ[r])),
                     key=lambda r: runs[r][5])
        done[victim] = True
        left -= 1
        broken.add(victim)
        for t in succ[victim]:
            indeg[t] -= 1
            if not indeg[t] and not done[t]:
                ready.append(t)
    for r in order:
        d, i, s, j, n, b = runs[r]
        p.copies.append((s, j * piece, d, i * piece, b))
        p.copied += b
    for r in broken:
        d, i, _s, _j, n, _b = runs[r]
        unsent[d].extend(range(i, i + n))
    p.broken = len(broken)
    for dst, idx in unsent.items():
        pieces = newh[dst]
        out = []
        for i in sorted(idx):
            off, ln = i * piece, pieces[i][1]
            if out and out[-1][0] + out[-1][1] == off and out[-1][1] + ln <= SEND_MAX:
                out[-1] = (out[-1][0], out[-1][1] + ln)
            else:
                out.append((off, ln))
            p.sent += ln
        p.sends[dst] = out
    return p


def apply(old_files, p):
    """What the machine's files become after *p* (copies in order, then sends from *new_files*); for checking a
    plan offline.  *old_files* ``{path: bytes}`` is changed and returned; sends are left as zero bytes for the
    caller to fill (``p.sends``)."""
    files = {k: bytearray(v) for k, v in old_files.items()}
    for s, so, d, do, n in p.copies:
        data = bytes(files[s][so:so + n])
        assert len(data) == n, (s, so, n)
        f = files.setdefault(d, bytearray())
        if len(f) < do + n:
            f.extend(bytes(do + n - len(f)))
        f[do:do + n] = data
    return files
