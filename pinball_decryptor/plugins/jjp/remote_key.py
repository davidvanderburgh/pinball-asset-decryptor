"""The JJP security key on ANOTHER PC, over the network (USB/IP, PAD-529).

The purple Sentinel key normally sits in this PC and usbipd-win hands it to
WSL.  Someone who also runs their games on the real machine moves that key
back and forth all day.  This keeps it in one always-on PC (the "key server",
running usbipd-win or Linux usbipd) and attaches it into WSL over the LAN.

THE MECHANISM IS THE ONE WE ALREADY USE.  ``usbipd attach --wsl`` is itself a
USB/IP client run inside WSL against the Windows host: the device lands on
the WSL kernel's vhci-hcd and shows in /sys/bus/usb/devices like any local
one.  Here that client is pointed at another server.  usbipd-win cannot pull
from a remote server (it is a server only), so the attach runs INSIDE WSL
with the static ``usbip`` client usbipd-win ships in its ``WSL`` folder, or
the distro's own ``usbip`` where that is all there is.  Everything after the
attach - the sysfs probe, aksusbd/hasplmd, the game - is unchanged.

ONE KEY, SEVERAL USERS.  An extract and an emulator run can both want the
key, and a retry or the cleanup of one must never pull it out from under the
other.  So nobody detaches by hardware id or with ``--port=all``: every user
holds a LEASE (a file under /mnt/wsl, which every distro shares and a WSL
restart clears together with the attachments themselves) and the port is
detached only when the last lease goes.  A key that was already attached
when we came - by hand, or by something that is not us - gets a lease no one
ever gives back, so it is left exactly as it was found.

All HASP keys are 0529:0001, so a server with several titles' keys on a hub
is told apart by BUS ID, never by hardware id.
"""

import base64
import json
import os
import re
import shlex
from collections import namedtuple

#: settings.json key: {"where": "local"|"usbip", "server": "host[:port]",
#: "busid": "1-4"}
SETTINGS_KEY = "jjp_remote_key"
#: Overrides the settings, for a headless run: "host[:port]/busid".
ENV = "JJP_DONGLE_REMOTE"
#: The USB/IP port both usbipd-win and Linux usbipd listen on.
DEFAULT_PORT = 3240
#: Where usbipd-win keeps its static Linux client.
USBIPD_WIN_CLIENT = r"C:\Program Files\usbipd-win\WSL\usbip"

Remote = namedtuple("Remote", "host port busid")

_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252}[A-Za-z0-9])?$")
_BUSID = re.compile(r"^[0-9]{1,3}-[0-9]{1,3}(?:\.[0-9]{1,3}){0,6}$")
_TAG = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class RemoteKeyError(Exception):
    """An attach or release that did not happen.  ``kind`` says which fault
    it was, so the caller can word it: ``noclient``, ``novhci``,
    ``unreachable``, ``busy`` (the key is in use by another PC),
    ``notexported`` (the server does not offer that bus id) or ``failed``."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def parse_server(text):
    """``"host"`` or ``"host:port"`` -> (host, port).  ValueError with a
    sentence for the user when it is not one.  Only names and IPv4 addresses:
    the value travels through a shell, so nothing else gets in."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Type the key server's name or IP address.")
    host, sep, port = text.rpartition(":")
    if not sep:
        host, port = text, ""
    if not _HOST.match(host) or ".." in host:
        raise ValueError("%r is not a computer name or IPv4 address." % host)
    if port:
        if not port.isdigit() or not 0 < int(port) < 65536:
            raise ValueError("%r is not a port number." % port)
        return host, int(port)
    return host, DEFAULT_PORT


def parse_busid(text):
    """A USB/IP bus id as the server lists it: ``1-4``, ``3-1.2``."""
    text = (text or "").strip()
    if not _BUSID.match(text):
        raise ValueError("Type the key's bus ID as the server lists it, "
                         "like 1-4.")
    return text


def from_settings(entry):
    """The Remote a settings entry names, or None for the key in this PC (and
    for an entry that is not complete or not valid: a half-typed server never
    sends an extract off to a host that does not exist)."""
    if not isinstance(entry, dict) or entry.get("where") != "usbip":
        return None
    try:
        host, port = parse_server(entry.get("server"))
        return Remote(host, port, parse_busid(entry.get("busid")))
    except ValueError:
        return None


_current = {"set": False, "remote": None}


def configure(entry):
    """What the app's settings say, handed over by the window that owns them
    (the Emulate JJP tab), so an extract in this process uses the same key
    without reading the settings file behind the app's back."""
    _current["set"] = True
    _current["remote"] = from_settings(entry)
    return _current["remote"]


def current():
    """The key server to use, or None for the key in this PC.

    ``JJP_DONGLE_REMOTE=host[:port]/busid`` wins; then what :func:`configure`
    was given; then the saved settings, for a process with no window."""
    env = os.environ.get(ENV, "").strip()
    if env:
        server, _, busid = env.rpartition("/")
        return from_settings({"where": "usbip", "server": server,
                              "busid": busid})
    if _current["set"]:
        return _current["remote"]
    try:
        from ...core.config import SETTINGS_FILE
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return from_settings(json.load(f).get(SETTINGS_KEY))
    except (OSError, ValueError, AttributeError):
        return None


def describe(remote):
    """``bus 1-4 on 192.168.1.20`` (the port only when it is not the usual)."""
    where = remote.host if remote.port == DEFAULT_PORT else \
        "%s:%d" % (remote.host, remote.port)
    return "bus %s on %s" % (remote.busid, where)


def client_path():
    """The ``usbip`` client to run inside WSL: usbipd-win's static one when it
    is installed (a WSL path), else the distro's own (empty: found on PATH)."""
    if os.path.isfile(USBIPD_WIN_CLIENT):
        p = USBIPD_WIN_CLIENT.replace("\\", "/")
        return "/mnt/" + p[0].lower() + p[2:]
    return ""


# The one script every verb runs.  Piped in as base64 (see command()): a
# command handed to wsl.exe is parsed by a shell on the way in, which eats
# $var expansions, so a script with variables cannot be passed as text.
_SCRIPT = r'''
set -u
VERB=$1; U=$2; HOST=$3; PORT=$4; BUSID=$5; TAG=${6:-}
if [ -z "$U" ] || [ ! -x "$U" ]; then U=$(command -v usbip 2>/dev/null); fi
[ -n "$U" ] || { echo "RESULT noclient"; exit 0; }
LEASES=/mnt/wsl/pad-remotekey
[ -d /mnt/wsl ] || LEASES=/run/pad-remotekey
LEASES=${PAD_REMOTEKEY_LEASES:-$LEASES}
L="$LEASES/$HOST,$PORT,$BUSID"
WANT="usbip://$HOST:$PORT/$BUSID"

port_of() {
    "$U" port 2>/dev/null | awk -v want="$WANT" '
        /^Port [0-9]+:/ { p = $2; sub(":", "", p); p += 0 }
        index($0, "-> " want) && $NF == want { print p; exit }'
}

case "$VERB" in
attach)
    modprobe vhci_hcd 2>/dev/null
    N=$(port_of)
    mkdir -p "$L"
    if [ -n "$N" ]; then
        # already here: ours (a lease says so) or someone else's, which is
        # then kept for good - we did not attach it, we never detach it
        [ -n "$(ls -A "$L" 2>/dev/null)" ] || : > "$L/external"
        : > "$L/$TAG"
        echo "RESULT borrowed $N"; exit 0
    fi
    rm -f "$L"/* 2>/dev/null        # leases of an attachment that is gone
    OUT=$("$U" --tcp-port "$PORT" attach -r "$HOST" -b "$BUSID" 2>&1); RC=$?
    printf '%s\n' "$OUT" | grep -v 'usb.ids' | sed 's/^/usbip: /'
    if [ $RC -ne 0 ]; then
        rmdir "$L" 2>/dev/null
        case "$OUT" in
            *"Device busy"*|*"busy"*) echo "RESULT busy" ;;
            *"Device not found"*|*"not found"*|*"No such"*|*"unavailable"*) echo "RESULT notexported" ;;
            *vhci*) echo "RESULT novhci" ;;
            *"tcp connect"*|*"connect"*|*"resolve"*|*"refused"*|*"timed out"*|*"unreachable"*) echo "RESULT unreachable" ;;
            *) echo "RESULT failed" ;;
        esac
        exit 0
    fi
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        N=$(port_of); [ -n "$N" ] && break; sleep 0.5
    done
    : > "$L/$TAG"
    echo "RESULT attached ${N:-?}" ;;
release)
    rm -f "$L/$TAG" 2>/dev/null
    LEFT=$(ls -A "$L" 2>/dev/null | tr '\n' ' ')
    N=$(port_of)
    if [ -z "$N" ]; then rm -rf "$L"; echo "RESULT gone"; exit 0; fi
    if [ -n "$LEFT" ]; then echo "RESULT kept $LEFT"; exit 0; fi
    "$U" detach -p "$N" 2>&1 | grep -v 'usb.ids' | sed 's/^/usbip: /'
    rmdir "$L" 2>/dev/null
    echo "RESULT detached $N" ;;
probe)
    N=$(port_of)
    [ -n "$N" ] && { echo "RESULT attached $N"; exit 0; }
    OUT=$("$U" --tcp-port "$PORT" list -r "$HOST" 2>&1); RC=$?
    if printf '%s\n' "$OUT" | grep -q "^ *$BUSID:"; then echo "RESULT offered"
    elif [ $RC -ne 0 ]; then echo "RESULT unreachable"
    else echo "RESULT notexported"; fi ;;
esac
'''


def command(verb, remote, tag="", client=None):
    """The bash command line for *verb* (attach / release / probe)."""
    if verb not in ("attach", "release", "probe"):
        raise ValueError(verb)
    if tag and not _TAG.match(tag):
        raise ValueError(tag)
    # re-checked here: these are the only words that reach a shell
    parse_server("%s:%d" % (remote.host, remote.port))
    parse_busid(remote.busid)
    b64 = base64.b64encode(_SCRIPT.encode("utf-8")).decode("ascii")
    args = [verb, client_path() if client is None else client,
            remote.host, str(remote.port), remote.busid, tag]
    return ("echo %s | base64 -d | bash -s -- %s"
            % (b64, " ".join(shlex.quote(a) for a in args)))


def _result(out):
    for line in reversed((out or "").splitlines()):
        if line.startswith("RESULT "):
            return line[7:].split()
    return ["failed"]


def _detail(out):
    return "\n".join(line[7:] for line in (out or "").splitlines()
                     if line.startswith("usbip: ")).strip()


MESSAGES = {
    "noclient": "There is no USB/IP client to reach the key server with. "
                "Install usbipd-win on this PC (it brings one along).",
    "novhci": "WSL's USB/IP driver (vhci_hcd) would not load, so a key from "
              "another PC cannot be attached here.",
    "unreachable": "The key server %(where)s is not answering. Check that "
                   "it is on, that usbipd runs there, and that TCP port "
                   "%(port)d is open to this PC.",
    "busy": "The key (%(what)s) is in use by another PC. Free it there "
            "first: only one PC can use a key at a time.",
    "notexported": "%(where)s does not offer a key on bus %(busid)s. Check "
                   "the bus ID, and share the key on the server (Windows: "
                   "usbipd bind --busid %(busid)s, Linux: usbip bind -b "
                   "%(busid)s).",
    "failed": "Could not attach the key (%(what)s).",
}


def message(kind, remote):
    where = remote.host if remote.port == DEFAULT_PORT else \
        "%s:%d" % (remote.host, remote.port)
    return MESSAGES.get(kind, MESSAGES["failed"]) % {
        "where": where, "port": remote.port, "busid": remote.busid,
        "what": describe(remote)}


def attach(run, remote, tag):
    """Attach *remote*'s key into WSL and take a lease on it for *tag*.

    *run(cmd)* runs a bash command as root in the app's WSL and returns its
    output (raising on failure is fine).  Returns ("attached"|"borrowed",
    vhci port).  Raises RemoteKeyError naming the fault."""
    out = run(command("attach", remote, tag))
    res = _result(out)
    if res[0] in ("attached", "borrowed"):
        return res[0], (res[1] if len(res) > 1 else "?")
    msg = message(res[0], remote)
    detail = _detail(out)
    if res[0] == "failed" and detail:
        msg += "\n" + detail
    raise RemoteKeyError(res[0], msg)


def release(run, remote, tag):
    """Give back *tag*'s lease; the key is detached only if no one else holds
    one.  Returns ("detached"|"kept"|"gone", detail).  Never raises."""
    try:
        res = _result(run(command("release", remote, tag)))
    except Exception as exc:                               # noqa: BLE001
        return "failed", str(exc)
    return res[0], " ".join(res[1:])


def probe(run, remote):
    """"attached" (already in WSL), "offered" (the server has it free),
    "unreachable", "notexported" or "noclient"."""
    try:
        return _result(run(command("probe", remote)))[0]
    except Exception:                                      # noqa: BLE001
        return "failed"
