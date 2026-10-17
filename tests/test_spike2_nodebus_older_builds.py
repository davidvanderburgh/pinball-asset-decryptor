"""PAD-603: the node bus answers older builds' way of asking.

deadpool_le 0.99 (2019) talks to the bus master differently from every build
the rig was written against, and each difference left it at "bringing up node
boards" (or, once past that, "LOCATING NODE BOARDS - 1 8 9 NODES NOT FOUND"):

* its ASYNCSERIAL_ReadBytes waits in select(1024, ...) before every read. The
  fd under /dev/ttymxc1 is a pty nobody writes to, so the real select timed
  out, read() was never called, and every exchange came back "short response
  (got 0, expected N)". The shim answers reads itself, so the bus fd is now
  reported readable by select, pselect, poll and ppoll; other fds are asked
  without waiting.
* it asks for the 0xfe identity with a 10-byte payload - from before the
  variant byte at [10] existed - and the shim filled identities only for 11.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")


def _shim():
    with open(os.path.join(RIG, "hwshim.c"), encoding="utf-8",
              errors="replace") as fh:
        return fh.read()


def _func(src, head):
    at = src.index(head)
    return src[at:src.index("\n}\n", at) + 3]


@pytest.mark.parametrize("head,helper", [
    ("int shim_select(int n, void *r, void *w, void *e, struct shim_tv *tv)\n{",
     "nb_select_ready("),
    ("int shim_pselect(int n, void *r, void *w, void *e, const struct shim_ts *ts,\n"
     "                 const void *mask)\n{", "nb_select_ready("),
    ("int shim_poll(void *fds, unsigned long nfds, int ms)\n{", "nb_poll_ready("),
    ("int shim_ppoll(void *fds, unsigned long nfds, const struct shim_ts *ts,\n"
     "               const void *mask)\n{", "nb_poll_ready("),
])
def test_every_wait_asks_about_the_bus_first(head, helper):
    body = _func(_shim(), head)
    assert helper in body
    # before any real call can block on the pty
    first_real = min(i for i in (body.find("real("), body.find("real_ppoll("))
                     if i >= 0)
    assert body.index(helper) < first_real


def test_identity_answers_the_ten_byte_ask():
    src = _shim()
    assert "nb_req[2] == 0xfe && plen >= 10" in src
    assert "if (plen >= 11) p[10] = (unsigned char)var;" in src
    assert "nb_req[2] == 0xfe && plen >= 11" not in src


_HARNESS = r"""
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/select.h>
#include <poll.h>
#define MAXFD 4096
static char faked[MAXFD];
struct shim_tv { long s; long us; };
static int real_select(int n, void *r, void *w, void *e, struct shim_tv *tv)
{
    struct timeval t = { tv->s, tv->us };
    int k = select(n, r, w, e, &t);
    tv->s = t.tv_sec; tv->us = t.tv_usec;
    return k;
}
static int real_poll_ms(void *fds, unsigned long nfds, int ms)
{
    return poll(fds, nfds, ms);
}
%s
int main(void)
{
    int bus[2], other[2], done, k;
    fd_set r;
    struct pollfd p[2];
    /* FD_ISSET is a truth value: glibc gives 1, macOS gives the fd's bit */
    pipe(bus); pipe(other);
    faked[bus[0]] = 'T';
    /* the bus fd alone: reported ready although nothing was written */
    FD_ZERO(&r); FD_SET(bus[0], &r);
    k = nb_select_ready(1024, &r, 0, 0, real_select, &done);
    printf("bus select done=%%d ret=%%d set=%%d\n", done, k, !!FD_ISSET(bus[0], &r));
    /* bus + an idle other fd: the other stays clear */
    FD_ZERO(&r); FD_SET(bus[0], &r); FD_SET(other[0], &r);
    k = nb_select_ready(1024, &r, 0, 0, real_select, &done);
    printf("mixed select ret=%%d bus=%%d other=%%d\n", k, !!FD_ISSET(bus[0], &r),
           !!FD_ISSET(other[0], &r));
    /* no bus fd: not handled, the caller takes its own path */
    FD_ZERO(&r); FD_SET(other[0], &r);
    nb_select_ready(1024, &r, 0, 0, real_select, &done);
    printf("plain select done=%%d\n", done);
    p[0].fd = bus[0]; p[0].events = POLLIN; p[0].revents = 0;
    p[1].fd = other[0]; p[1].events = POLLIN; p[1].revents = 0;
    k = nb_poll_ready(p, 2, real_poll_ms, &done);
    printf("poll done=%%d ret=%%d bus=%%d other=%%d\n", done, k,
           p[0].revents & POLLIN, p[1].revents & POLLIN);
    return 0;
}
"""


@pytest.mark.skipif(not shutil.which("gcc") or sys.platform == "win32",
                    reason="needs gcc and a POSIX system")
def test_the_bus_fd_is_ready_and_nothing_else_is(tmp_path):
    src = _shim()
    start = src.index("static int nb_fd_set_has(")
    end = src.index("static int real_poll_ms(")
    c = tmp_path / "h.c"
    c.write_text(_HARNESS % src[start:end])
    exe = tmp_path / "h"
    subprocess.run(["gcc", "-o", str(exe), str(c)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True,
                         check=True, timeout=30).stdout.splitlines()
    assert out == [
        "bus select done=1 ret=1 set=1",
        "mixed select ret=1 bus=1 other=0",
        "plain select done=0",
        "poll done=1 ret=1 bus=1 other=0",
    ], out
