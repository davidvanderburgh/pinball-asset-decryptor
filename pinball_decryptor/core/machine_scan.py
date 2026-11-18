"""Find the machine on the home network (PAD-1427).

David: "on the remote access connection, it should have a scan button and be able to easily find and remember the
machine so we don't have to manually enter the IP address."

:func:`scan` looks at every address of the home networks this computer is on (the /24 around each of its private
IPv4 addresses) for an SSH server on port 22, then tries to log in to each one as a card with remote access lets
this computer in (``pad_ssh_key``, the same login Send to machine uses) and asks it which game it runs.  Nothing
is changed on anything it finds, and no host key is remembered: the user's pick (or the only machine found) is
remembered with :func:`pad_ssh_key.remember_machine`, its identity with it, so :func:`find_moved` can find the same
machine again after the router hands it another address."""

import concurrent.futures
import ipaddress
import socket

PORT = 22
#: how long one address gets to answer on port 22; a home network answers in a few milliseconds
CONNECT_TIMEOUT = 0.6
WORKERS = 128
#: never more addresses than this in one scan (a /24 per network; a computer on many networks stops here)
MAX_HOSTS = 2048


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


def networks(addresses=None):
    """The /24 networks to scan: one around each of *addresses* (this computer's own by default)."""
    nets = []
    for ip in addresses if addresses is not None else local_addresses():
        net = ipaddress.IPv4Network("%s/24" % ip, strict=False)
        if net not in nets:
            nets.append(net)
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


def scan(nets=None, *, port=PORT, timeout=CONNECT_TIMEOUT, progress=None, cancel=None, log_in=True):
    """Every SSH server on the home networks: a list of ``{'address', 'banner', 'lets_in', 'game', 'host_key',
    'note'}``, the machines that let this computer in first.  *progress(done, total)* is called as it goes."""
    nets = networks() if nets is None else nets
    own = {str(a) for a in local_addresses()}
    hosts = []
    for net in nets:
        for h in net.hosts():
            if str(h) not in own and h not in hosts:
                hosts.append(h)
            if len(hosts) >= MAX_HOSTS:
                break
    total = len(hosts)
    found = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_banner, h, port, timeout): h for h in hosts}
        for fut in concurrent.futures.as_completed(futs):
            done += 1
            banner = fut.result()
            if banner:
                found.append(dict(address=str(futs[fut]), banner=banner, lets_in=False, game="", host_key=None,
                                  note=""))
            if progress is not None and (done % 16 == 0 or done == total):
                progress(done, total)
            if cancel is not None and cancel():
                for f in futs:
                    f.cancel()
                break
    if log_in and found:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for rec, res in zip(found, ex.map(lambda r: probe(r["address"], port), found)):
                rec.update(res)
    found.sort(key=lambda r: (not r["lets_in"], ipaddress.IPv4Address(r["address"])))
    return found


def address_of(rec, port=PORT):
    return rec["address"] if int(port) == PORT else "%s:%d" % (rec["address"], int(port))


def find_moved(host_key, port=PORT, nets=None):
    """The address the machine whose identity is *host_key* answers at now, or None: for a remembered machine
    the router has given another address since."""
    if not host_key:
        return None
    for rec in scan(nets, port=port, log_in=False):
        try:
            import paramiko
            sock = socket.create_connection((rec["address"], int(port)), timeout=5)
            t = paramiko.Transport(sock)
            try:
                t.start_client(timeout=5)
                key = t.get_remote_server_key()
                if (key.get_name(), key.get_base64()) == tuple(host_key):
                    return rec["address"]
            finally:
                t.close()
        except Exception:                               # noqa: BLE001 - not this one
            continue
    return None
