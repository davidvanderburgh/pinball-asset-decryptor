"""Pure-Python ``std::_Rb_tree_insert_and_rebalance`` for the unicorn harness.

The firmware's asset registry is a libstdc++ red-black tree; its insert helper is
an imported libstdc++ symbol.  Rather than emulate libstdc++, the harness traps
the import and runs this equivalent against emulator memory.

Node layout (``_Rb_tree_node_base``):
  +0x0 _M_color (0=red, 1=black)  +0x4 _M_parent  +0x8 _M_left  +0xc _M_right
The header node ``h`` holds: +4 = root, +8 = leftmost, +0xc = rightmost.
"""

import struct

RED = 0
BLACK = 1


def _g(mu, a):
    return struct.unpack("<I", bytes(mu.mem_read(a, 4)))[0]


def _p(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xffffffff))


def _color(mu, n):
    return _g(mu, n)


def _set_color(mu, n, c):
    _p(mu, n, c)


def _parent(mu, n):
    return _g(mu, n + 4)


def _set_parent(mu, n, v):
    _p(mu, n + 4, v)


def _left(mu, n):
    return _g(mu, n + 8)


def _set_left(mu, n, v):
    _p(mu, n + 8, v)


def _right(mu, n):
    return _g(mu, n + 0xc)


def _set_right(mu, n, v):
    _p(mu, n + 0xc, v)


def increment(mu, x):
    """``std::_Rb_tree_increment`` -- the in-order successor of node ``x``.

    Returns the header node when ``x`` is the last element, which is what ends a
    ``begin() != end()`` iteration.  Without this the harness returned 0 for the
    imported symbol, so any build that actually *iterates* a non-empty registry
    map (e.g. Led Zeppelin LE 1.22.0's master-directory decode) walked off node
    0 forever instead of stopping at the header.  The ``n`` guards are a defensive
    cap: a valid tree's depth is tiny, so they never trip on real data but stop a
    malformed tree from hanging (the derive then fails cleanly via its watchdog).
    """
    if _right(mu, x) != 0:
        x = _right(mu, x)
        n = 0
        while _left(mu, x) != 0 and n < 1_000_000:
            x = _left(mu, x); n += 1
    else:
        y = _parent(mu, x)
        n = 0
        while x == _right(mu, y) and n < 1_000_000:
            x = y; y = _parent(mu, y); n += 1
        if _right(mu, x) != y:
            x = y
    return x


def decrement(mu, x):
    """``std::_Rb_tree_decrement`` -- the in-order predecessor of node ``x``
    (mirrors :func:`increment`; the same defensive depth cap applies)."""
    if _color(mu, x) == RED and _parent(mu, _parent(mu, x)) == x:
        # x is the header (its grandparent is itself): predecessor = rightmost.
        return _right(mu, x)
    if _left(mu, x) != 0:
        y = _left(mu, x)
        n = 0
        while _right(mu, y) != 0 and n < 1_000_000:
            y = _right(mu, y); n += 1
        return y
    y = _parent(mu, x)
    n = 0
    while x == _left(mu, y) and n < 1_000_000:
        x = y; y = _parent(mu, y); n += 1
    return y


def _rotate_left(mu, x, header):
    y = _right(mu, x)
    _set_right(mu, x, _left(mu, y))
    if _left(mu, y) != 0:
        _set_parent(mu, _left(mu, y), x)
    _set_parent(mu, y, _parent(mu, x))
    if x == _g(mu, header + 4):
        _p(mu, header + 4, y)
    elif x == _left(mu, _parent(mu, x)):
        _set_left(mu, _parent(mu, x), y)
    else:
        _set_right(mu, _parent(mu, x), y)
    _set_left(mu, y, x)
    _set_parent(mu, x, y)


def _rotate_right(mu, x, header):
    y = _left(mu, x)
    _set_left(mu, x, _right(mu, y))
    if _right(mu, y) != 0:
        _set_parent(mu, _right(mu, y), x)
    _set_parent(mu, y, _parent(mu, x))
    if x == _g(mu, header + 4):
        _p(mu, header + 4, y)
    elif x == _right(mu, _parent(mu, x)):
        _set_right(mu, _parent(mu, x), y)
    else:
        _set_left(mu, _parent(mu, x), y)
    _set_right(mu, y, x)
    _set_parent(mu, x, y)


def insert_and_rebalance(mu, insert_left, x, p, header):
    """``header`` is ``&_M_header``: +4 root, +8 leftmost, +0xc rightmost."""
    _set_color(mu, x, RED)
    _set_left(mu, x, 0)
    _set_right(mu, x, 0)
    _set_parent(mu, x, p)
    if insert_left:
        _set_left(mu, p, x)
        if p == header:                 # first node
            _p(mu, header + 4, x)        # root = x
            _p(mu, header + 0xc, x)      # rightmost = x
        elif p == _g(mu, header + 8):    # p == leftmost
            _p(mu, header + 8, x)        # leftmost = x
    else:
        _set_right(mu, p, x)
        if p == _g(mu, header + 0xc):    # p == rightmost
            _p(mu, header + 0xc, x)      # rightmost = x
    while x != _g(mu, header + 4) and _color(mu, _parent(mu, x)) == RED:
        xpp = _parent(mu, _parent(mu, x))
        if _parent(mu, x) == _left(mu, xpp):
            y = _right(mu, xpp)
            if y != 0 and _color(mu, y) == RED:
                _set_color(mu, _parent(mu, x), BLACK)
                _set_color(mu, y, BLACK)
                _set_color(mu, xpp, RED)
                x = xpp
            else:
                if x == _right(mu, _parent(mu, x)):
                    x = _parent(mu, x)
                    _rotate_left(mu, x, header)
                _set_color(mu, _parent(mu, x), BLACK)
                _set_color(mu, _parent(mu, _parent(mu, x)), RED)
                _rotate_right(mu, _parent(mu, _parent(mu, x)), header)
        else:
            y = _left(mu, xpp)
            if y != 0 and _color(mu, y) == RED:
                _set_color(mu, _parent(mu, x), BLACK)
                _set_color(mu, y, BLACK)
                _set_color(mu, xpp, RED)
                x = xpp
            else:
                if x == _left(mu, _parent(mu, x)):
                    x = _parent(mu, x)
                    _rotate_right(mu, x, header)
                _set_color(mu, _parent(mu, x), BLACK)
                _set_color(mu, _parent(mu, _parent(mu, x)), RED)
                _rotate_left(mu, _parent(mu, _parent(mu, x)), header)
    _set_color(mu, _g(mu, header + 4), BLACK)
