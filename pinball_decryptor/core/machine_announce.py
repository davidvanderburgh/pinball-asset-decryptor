"""Machines that say where they are (PAD-1627).

David: "the IP address is pretty much going to change every time the machine boots on. we need the machine to
reach out to the app when it gets its IP ... remembering IP is not enough clearly and we won't be requiring users
to modify their routers to set a static IP".

A card with remote access starts the announce service its own system ships (avahi, on a Spike 2 card: Stern left
it switched off) and says it is a PAD machine: the service ``_pad-machine._tcp`` with its game and its SSH
identity (``resources/ssh/sshd``).  The app never has to remember an address: :func:`ask` puts one question to
the home network ("which PAD machines are here?") and every machine that is on answers within a fraction of a
second, wherever the router put it.

The question is one multicast DNS packet from an ordinary socket, asking for answers sent straight back to it, so
nothing listens on this computer and no firewall rule is needed.  A card set up before this, or one whose system
has no announce service, does not answer: the address scan (:mod:`machine_scan`) still finds those.
"""
import socket
import struct
import time

SERVICE = "_pad-machine._tcp.local"
GROUP, PORT = "224.0.0.251", 5353
#: PAD-1627, measured on David's mesh: one multicast question reached his Godzilla about half the time (the
#: machine's Wi-Fi radio sleeps, and a mesh drops multicast to a sleeping device), asked every quarter second it
#: always got through but took up to 2.7 s; a question sent straight to the machine's address always got through
#: in under 0.3 s.  So the question is repeated every :data:`AGAIN` seconds for up to :data:`WAIT`, sent straight
#: to the addresses the machines were last at as well, and the asking ends early once all of those have answered.
WAIT = 3.5
AGAIN = 0.25
#: never sooner than this, so a machine nobody knew of yet has its chance too
AT_LEAST = 0.6
PTR, TXT, SRV, ANY_IN_UNICAST = 12, 16, 33, 0x8001


def question(name=SERVICE):
    """The packet that asks who offers *name*, answers wanted straight back (the "unicast response" bit)."""
    labels = b"".join(bytes([len(p)]) + p.encode("ascii") for p in name.split(".") if p)
    return struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + labels + b"\0" + struct.pack(">HH", PTR, ANY_IN_UNICAST)


def _name(data, at, hops=0):
    """``(name, next offset)`` of the (possibly compressed) name at *at*."""
    parts = []
    end = None
    while True:
        if at >= len(data) or hops > 32:
            raise ValueError("bad name")
        n = data[at]
        if n == 0:
            at += 1
            break
        if n & 0xC0 == 0xC0:
            if at + 1 >= len(data):
                raise ValueError("bad pointer")
            if end is None:
                end = at + 2
            at = ((n & 0x3F) << 8) | data[at + 1]
            hops += 1
            continue
        parts.append(data[at + 1:at + 1 + n].decode("utf-8", "replace"))
        at += 1 + n
    return ".".join(parts), (at if end is None else end)


def parse(data, service=SERVICE):
    """What one answer says of *service*: ``{'game', 'host_key', 'port', 'name'}``, or ``None`` when the packet
    is not an answer about it.  ``host_key`` is ``(kind, base64)`` or ``None``."""
    try:
        _id, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
        if not flags & 0x8000:
            return None
        at = 12
        for _ in range(qd):
            _n, at = _name(data, at)
            at += 4
        got = {"game": "", "host_key": None, "port": 22, "name": ""}
        ours = False
        for _ in range(an + ns + ar):
            name, at = _name(data, at)
            rtype, _cls, _ttl, size = struct.unpack(">HHIH", data[at:at + 10])
            at += 10
            body, at = data[at:at + size], at + size
            mine = name.lower().endswith(service.lower())
            if rtype == PTR and name.lower() == service.lower():
                ours = True
                inst, _ = _name(data, at - size)
                got["name"] = inst[:-len(service) - 1] if inst.lower().endswith("." + service.lower()) else inst
            elif rtype == SRV and mine and size >= 6:
                got["port"] = struct.unpack(">H", body[4:6])[0]
            elif rtype == TXT and mine:
                i = 0
                while i < len(body):
                    n = body[i]
                    key, _eq, value = body[i + 1:i + 1 + n].decode("utf-8", "replace").partition("=")
                    i += 1 + n
                    if key == "game":
                        got["game"] = value.strip()
                    elif key == "key":
                        kind, _sp, b64 = value.strip().partition(" ")
                        if kind.startswith(("ssh-", "ecdsa-")) and b64:
                            got["host_key"] = (kind, b64.split()[0])
        return got if ours else None
    except (ValueError, struct.error, IndexError):
        return None


def ask(wait=WAIT, addresses=None, service=SERVICE, also=()):
    """Every PAD machine that answers on the home networks right now: ``[{'address', 'game', 'host_key', 'port',
    'name'}]``, in address order.  ``[]`` when none does (or this computer has no network): never raises.

    *also*: addresses machines were last at; each is asked directly too, and once all of them have answered (and
    :data:`AT_LEAST` has passed) the asking is over."""
    if addresses is None:
        try:
            from . import machine_scan
            addresses = [str(a) for a in machine_scan.local_addresses()]
        except Exception:                               # noqa: BLE001 - no network to ask
            addresses = []
    also = [a.split(":")[0] for a in also or () if a]
    socks = []
    packet = question(service)
    for a in addresses:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((a, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(a))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            s.setblocking(False)
            socks.append(s)
        except OSError:
            continue
    # the direct questions go from a socket of their own: one sent to an address nothing is at any more comes
    # back as an error on its socket (Windows), which must not cost the multicast socket its answers
    direct = None
    if also and socks:
        try:
            direct = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            direct.setblocking(False)
            socks.append(direct)
        except OSError:
            direct = None

    def put():
        for s in socks:
            try:
                if s is direct:
                    for dest in also:
                        s.sendto(packet, (dest, PORT))
                else:
                    s.sendto(packet, (GROUP, PORT))
            except OSError:
                pass
    found = {}
    start = time.monotonic()
    again = 0.0
    try:
        while socks and time.monotonic() - start < wait:
            spent = time.monotonic() - start
            if spent >= again:
                put()
                again += AGAIN
            if also and spent >= AT_LEAST and all(a in found and found[a]["host_key"] for a in also):
                break
            idle = True
            for s in socks:
                try:
                    data, src = s.recvfrom(9000)
                except OSError:
                    continue
                idle = False
                got = parse(data, service)
                if got is not None and src[0] not in addresses:
                    # a machine whose service has only just started answers with its name alone at first:
                    # the answer that carries its identity is the one kept
                    if src[0] not in found or (got["host_key"] and not found[src[0]]["host_key"]):
                        found[src[0]] = dict(got, address=src[0])
            if idle:
                time.sleep(0.02)
    finally:
        for s in socks:
            s.close()
    return [found[a] for a in sorted(found, key=lambda x: tuple(int(p) for p in x.split(".")))]
