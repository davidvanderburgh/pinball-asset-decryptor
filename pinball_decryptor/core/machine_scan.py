"""Find the machine on the home network (PAD-1427).

David: "on the remote access connection, it should have a scan button and be able to easily find and remember the
machine so we don't have to manually enter the IP address."

:func:`scan` looks at every address of the home networks this computer is on (the /24 around each of its private
IPv4 addresses) for an SSH server on port 22, then tries to log in to each one as a card with remote access lets
this computer in (``pad_ssh_key``, the same login Send to machine uses) and asks it which game it runs.  Nothing
is changed on anything it finds, and no host key is remembered: the user's pick (or the only machine found) is
remembered with :func:`pad_ssh_key.remember_machine`, its identity with it, so :func:`find_moved` can find the same
machine again after the router hands it another address.

PAD-1430: a mesh network (eero and the like) is often bigger than a /24 (192.168.4.0/22 on David's), so the network
the computer's default route is on is scanned at its real size, down to a /22; and an address that did not answer
the first pass is asked once more, slower, because one pass missed a machine that was there (three back-to-back
passes found three different sets of devices on David's mesh).

PAD-1456: that second pass only asks again what the sweep showed is there (it is in the neighbour table now), and a
device this computer has not talked to yet is exactly what the sweep misses: its hundreds of ARP broadcasts at once
lose replies (on David's mesh the sweep found 42 of 64 devices; a gentle pass over the rest found the other 22).  A
machine just switched on is always such a device, so Find my machine missed David's Godzilla at its new address.  So
when the sweep finds no machine that lets this computer in, every address that did not answer is asked once more,
:data:`CAREFUL_WORKERS` at a time (the pace that found all 22), this computer's own /24 first."""

import concurrent.futures
import ipaddress
import re
import socket
import struct
import subprocess
import sys

PORT = 22
#: how long one address gets to answer on port 22; a home network answers in a few milliseconds
CONNECT_TIMEOUT = 0.6
#: the second pass, over the addresses that did not answer the first: a device slow to answer once is not a miss
RETRY_TIMEOUT = 3.0
WORKERS = 128
#: never more addresses than this in one scan (a /22 for the home network, a /24 for any other)
MAX_HOSTS = 2048
#: the widest network scanned at its real size (1022 addresses); a wider one is scanned as the /22 around us
WIDEST_PREFIX = 22
#: how long a device this computer already knows is there gets to answer (asked before the sweep, unhurried)
NEAR_TIMEOUT = 3.0
#: PAD-1456: the careful pass, over every address that did not answer when nothing was found: few at a time, so
#: the ARP broadcasts that find a device this computer has not talked to yet are not lost in a burst
CAREFUL_WORKERS = 16
CAREFUL_TIMEOUT = 1.5

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def neighbours():
    """The addresses this computer has lately talked to on its networks (the ARP / neighbour table): devices
    that are there.  Empty when the system won't say."""
    found = []
    for cmd in ((["arp", "-a"],) if sys.platform in ("win32", "darwin") else (["ip", "neigh"], ["arp", "-an"])):
        try:
            text = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                                  creationflags=_NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for ip, mac in re.findall(r"\(?(\d+\.\d+\.\d+\.\d+)\)?\s+(?:at\s+|dev \S+ lladdr\s+)?"
                                  r"([0-9a-fA-F]{1,2}(?:[-:][0-9a-fA-F]{1,2}){5})", text):
            m = mac.lower().replace("-", ":")
            if m.startswith(("ff:ff:ff", "01:00:5e")) or m == "0:0:0:0:0:0" or m == "00:00:00:00:00:00":
                continue
            if ip not in found:
                found.append(ip)
        if found:
            break
    return found


def _private(ip):
    return ip.is_private and not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified)


def local_addresses():
    """This computer's own private IPv4 addresses (each network it is on), the default route's first."""
    found = []

    def add(a):
        try:
            ip = ipaddress.IPv4Address(a)
        except ValueError:
            return
        if _private(ip) and ip not in found:
            found.append(ip)

    for target in ("192.168.1.1", "10.255.255.255", "172.16.0.1"):
        # the address this computer would send from: a UDP "connect" sends nothing
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 9))
            add(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return found


def _prefixes_windows():
    """``{address: prefix length}`` from the IP address table (iphlpapi GetIpAddrTable)."""
    import ctypes
    from ctypes import wintypes

    class Row(ctypes.Structure):
        _fields_ = [("addr", wintypes.DWORD), ("index", wintypes.DWORD), ("mask", wintypes.DWORD),
                    ("bcast", wintypes.DWORD), ("reasm", wintypes.DWORD), ("unused", wintypes.USHORT),
                    ("type", wintypes.USHORT)]
    get = ctypes.windll.iphlpapi.GetIpAddrTable
    size = wintypes.ULONG(0)
    get(None, ctypes.byref(size), False)
    if not size.value:
        return {}
    buf = ctypes.create_string_buffer(size.value)
    if get(buf, ctypes.byref(size), False) != 0:
        return {}
    (count,) = struct.unpack_from("<I", buf.raw, 0)
    rows = (Row * count).from_buffer_copy(buf.raw[4:4 + count * ctypes.sizeof(Row)])
    out = {}
    for r in rows:
        ip = socket.inet_ntoa(struct.pack("<I", r.addr))
        out[ip] = bin(r.mask).count("1")
    return out


def _prefixes_text(text):
    """``{address: prefix length}`` from ``ip -4 -o addr`` (``inet a.b.c.d/22``) or ``ifconfig``
    (``inet a.b.c.d netmask 0xfffffc00`` / ``netmask 255.255.252.0``)."""
    out = {}
    for ip, plen in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", text):
        out[ip] = int(plen)
    for ip, mask in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)\s+netmask\s+(0x[0-9a-fA-F]+|\d+\.\d+\.\d+\.\d+)", text):
        m = int(mask, 16) if mask.startswith("0x") else int(ipaddress.IPv4Address(mask))
        out[ip] = bin(m).count("1")
    return out


def prefixes():
    """This computer's IPv4 addresses with the size of the network each is on, ``{address: prefix}``; empty when
    the system won't say (then every network is taken as a /24)."""
    try:
        if sys.platform == "win32":
            return _prefixes_windows()
        for cmd in (["ip", "-4", "-o", "addr", "show"], ["ifconfig"]):
            try:
                text = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
            except (OSError, subprocess.SubprocessError):
                continue
            got = _prefixes_text(text)
            if got:
                return got
    except Exception:                                   # noqa: BLE001 - a /24 is the fallback, never an error
        pass
    return {}


def networks(addresses=None, sizes=None):
    """The networks to scan: one around each of *addresses* (this computer's own by default).  The first address
    (the default route's) is scanned at the size of its network from *sizes* (``{address: prefix}``, the system's
    by default), no wider than a /22; every other network as a /24."""
    if addresses is None:
        addresses = local_addresses()
        if sizes is None:
            sizes = prefixes()
    sizes = sizes or {}
    nets = []
    for i, ip in enumerate(addresses):
        plen = 24
        if i == 0 and str(ip) in sizes:
            plen = min(24, max(WIDEST_PREFIX, int(sizes[str(ip)])))
        net = ipaddress.IPv4Network("%s/%d" % (ip, plen), strict=False)
        if not any(net.subnet_of(n) for n in nets):
            nets = [n for n in nets if not n.subnet_of(net)] + [net]
    return nets


def _banner(host, port, timeout):
    """The SSH server's first line on *host*, or None when nothing answers there."""
    try:
        with socket.create_connection((str(host), port), timeout=timeout) as s:
            s.settimeout(max(timeout, 1.5))
            data = b""
            while b"\n" not in data and len(data) < 256:
                got = s.recv(256)
                if not got:
                    break
                data += got
    except OSError:
        return None
    line = data.split(b"\n", 1)[0].strip().decode("ascii", "replace")
    return line if line.startswith("SSH-") else None


def online(host, port=PORT, timeout=1.5):
    """PAD-1585: True when *host*'s SSH server answers right now (My machines' green light). It reads the banner
    only: nothing logs in, nothing is remembered."""
    return _banner(host, port, timeout) is not None


def game_of(describe_out):
    """The game a machine runs, from ``SshMachine.describe()``'s first line: the ``/games/game`` link, which
    names ``<game>/game`` (Spike 2 links it relative) or ``/games/<game>/game``."""
    out = (describe_out or "").split()
    parts = out[0].strip("/").split("/") if out else []
    return parts[-2] if len(parts) >= 2 else ""


def probe(host, port=PORT, timeout=8):
    """Log in to *host* with this computer's key: ``{'lets_in', 'game', 'host_key', 'note'}``.  Nothing is
    remembered or changed."""
    import paramiko
    from . import pad_ssh_key
    res = dict(lets_in=False, game="", host_key=None, note="")
    try:
        sock = socket.create_connection((str(host), int(port)), timeout=timeout)
    except OSError as e:
        res["note"] = str(e)
        return res
    t = paramiko.Transport(sock)
    try:
        t.start_client(timeout=timeout)
        key = t.get_remote_server_key()
        res["host_key"] = (key.get_name(), key.get_base64())
        try:
            t.auth_publickey("root", pad_ssh_key.load_private())
        except paramiko.AuthenticationException:
            res["note"] = "doesn't let this computer in"
            return res
        res["lets_in"] = True
        ch = t.open_session(timeout=timeout)
        ch.settimeout(timeout)
        ch.exec_command("readlink /games/game")
        out = b""
        while True:
            got = ch.recv(4096)
            if not got:
                break
            out += got
        res["game"] = game_of(out.decode("utf-8", "replace"))
    except Exception as e:                              # noqa: BLE001 - a scan says what it found, never raises
        res["note"] = res["note"] or str(e) or e.__class__.__name__
    finally:
        t.close()
    return res


def careful_seconds(count):
    """About how long the careful pass over *count* addresses takes when nothing answers."""
    return -(-count // CAREFUL_WORKERS) * CAREFUL_TIMEOUT


def _own_first(hosts, own):
    """*hosts* with those on this computer's own /24s first (where the router most likely put the machine)."""
    near = [ipaddress.IPv4Network("%s/24" % a, strict=False) for a in own]
    return sorted(hosts, key=lambda h: not any(h in n for n in near))


def scan(nets=None, *, port=PORT, timeout=CONNECT_TIMEOUT, progress=None, cancel=None, log_in=True,
         retry_timeout=RETRY_TIMEOUT, report=None, near_first=True, remembered=None, careful=None, note=None):
    """Every SSH server on the home networks: a list of ``{'address', 'banner', 'lets_in', 'game', 'host_key',
    'note'}``, the machines that let this computer in first.  *progress(done, total)* is called as it goes.

    The addresses this computer already knows a device at (:func:`neighbours`, plus *remembered*, by default the
    machines it remembers) are asked first with a long timeout; the rest are swept, and what did not answer is asked
    once more with *retry_timeout* (``None``: no second pass).  *report*, a dict, is filled with what was looked
    at: ``networks`` (their names), ``addresses`` (how many), ``known`` (asked first), ``passes`` (sweeps) and
    ``careful`` (how many addresses the careful pass asked again).

    PAD-1456: *careful* says whether every address that still did not answer is asked once more, slowly: ``None``
    (when logging in and no machine let this computer in), True, False, or a function of the records found so far
    that says whether to.  *note(count)* is told when that pass starts, with how many addresses it asks."""
    nets = networks() if nets is None else nets
    if remembered is None:
        try:
            from . import pad_ssh_key
            remembered = [m["address"].split(":")[0] for m in pad_ssh_key.machines()]
        except Exception:                               # noqa: BLE001 - only a head start
            remembered = []
    own_ips = local_addresses()
    own = {str(a) for a in own_ips}
    hosts = []
    seen = set()
    for net in nets:
        for h in net.hosts():
            if len(hosts) >= MAX_HOSTS:
                break
            if str(h) not in own and h not in seen:
                seen.add(h)
                hosts.append(h)
    # PAD-1430: the devices this computer already knows are there (its neighbour table, and the machines it
    # remembers) are asked first, alone and unhurried: a sweep of a /22 sends a thousand ARP broadcasts at once,
    # and on a mesh's Wi-Fi the machine's answer can queue behind them past the sweep's timeout
    near = set(neighbours()) | set(remembered or ())
    first = [h for h in hosts if str(h) in near] if near_first else []
    rest = [h for h in hosts if str(h) not in near] if near_first else hosts
    if report is not None:
        report.update(networks=[str(n) for n in nets], addresses=len(hosts), passes=0, known=len(first),
                      careful=0)
    stages = [(first, NEAR_TIMEOUT, False), (rest, timeout, bool(retry_timeout))]
    total = len(hosts) + (len(rest) if retry_timeout else 0)
    found = []
    done = 0
    for todo, stage_timeout, retry in stages:
        while todo and not (cancel is not None and cancel()):
            if report is not None and todo is not first:
                report["passes"] += 1
            missed = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
                futs = {ex.submit(_banner, h, port, stage_timeout): h for h in todo}
                for fut in concurrent.futures.as_completed(futs):
                    done += 1
                    banner = fut.result()
                    if banner:
                        found.append(dict(address=str(futs[fut]), banner=banner, lets_in=False, game="",
                                          host_key=None, note=""))
                    else:
                        missed.append(futs[fut])
                    if progress is not None and (done % 16 == 0 or done == total):
                        progress(done, total)
                    if cancel is not None and cancel():
                        for f in futs:
                            f.cancel()
                        break
            if not retry:
                break
            # the second pass asks again only what did not answer AND the sweep showed is there (it answered the
            # sweep's ARP, so it is in the neighbour table now): a device, not an empty address
            alive = set(neighbours())
            missed = [h for h in missed if str(h) in alive]
            total = done + len(missed)
            todo, stage_timeout, retry = missed, retry_timeout, False

    def log_in_to(recs):
        if log_in and recs:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                for rec, res in zip(recs, ex.map(lambda r: probe(r["address"], port), recs)):
                    rec.update(res)

    log_in_to(found)

    def wanted(recs):
        """Whether the careful pass is (still) wanted, given the records found so far."""
        if callable(careful):
            return bool(careful(list(recs)))
        if careful is None:
            return log_in and not any(r["lets_in"] for r in recs)
        return bool(careful)

    if wanted(found) and not (cancel is not None and cancel()):
        answered = {r["address"] for r in found}
        todo = _own_first([h for h in hosts if str(h) not in answered], own_ips)
        if report is not None:
            report["careful"] = len(todo)
        if todo and note is not None:
            note(len(todo))
        total = done + len(todo)
        more = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=CAREFUL_WORKERS) as ex:
            futs = {ex.submit(_banner, h, port, CAREFUL_TIMEOUT): h for h in todo}
            for fut in concurrent.futures.as_completed(futs):
                done += 1
                banner = fut.result()
                if banner:
                    rec = dict(address=str(futs[fut]), banner=banner, lets_in=False, game="", host_key=None,
                               note="")
                    log_in_to([rec])
                    more.append(rec)
                if progress is not None and (done % 16 == 0 or done == total):
                    progress(done, total)
                # what it was asked to find is found (the machine, this computer's own /24 first): no need to
                # wait out the rest of the network
                if (cancel is not None and cancel()) or (banner and not wanted(found + more)):
                    for f in futs:
                        f.cancel()
                    if progress is not None:
                        progress(total, total)
                    break
        found += more
    found.sort(key=lambda r: (not r["lets_in"], ipaddress.IPv4Address(r["address"])))
    return found


def address_of(rec, port=PORT):
    return rec["address"] if int(port) == PORT else "%s:%d" % (rec["address"], int(port))


def find_moved(host_key, port=PORT, nets=None):
    """The address the machine whose identity is *host_key* answers at now, or None: for a remembered machine
    the router has given another address since."""
    if not host_key:
        return None
    keys = {}

    def key_at(address):
        if address not in keys:
            keys[address] = None
            try:
                import paramiko
                sock = socket.create_connection((address, int(port)), timeout=5)
                t = paramiko.Transport(sock)
                try:
                    t.start_client(timeout=5)
                    key = t.get_remote_server_key()
                    keys[address] = (key.get_name(), key.get_base64())
                finally:
                    t.close()
            except Exception:                           # noqa: BLE001 - not this one
                pass
        return keys[address]

    want = tuple(host_key)
    # PAD-1456: the careful pass too when the quick one didn't find it (a machine just switched on is missed)
    for rec in scan(nets, port=port, log_in=False,
                    careful=lambda recs: not any(key_at(r["address"]) == want for r in recs)):
        if key_at(rec["address"]) == want:
            return rec["address"]
    return None
