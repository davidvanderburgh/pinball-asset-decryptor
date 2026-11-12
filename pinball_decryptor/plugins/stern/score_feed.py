"""The score feed: each game's final scores posted to the owner's own server (PAD-1204; sdk/MODE_SDK.md "The score
feed", pad_mode_runtime.c "the score feed").

C0untDeM0net (Pinside): "a high score display external from the games running on a TV ... capture the end game scores
and user info if logged in, then push them to an external server separate from IC". The mode runtime does it on the
machine: at the end of each game it posts one JSON object, the players' final scores and the Insider Connected login
of each player who was logged in, to the address the owner gives (plain HTTP to an IPv4 address on their network).

The Play options tab's Score feed (the project sidecar's ``score_feed: {"on": true, "url": "http://..."}``) puts
``scorefeed.cfg`` beside the runtime, so a card with no modes of its own carries it too. It changes no score: a card
with nothing else on it stays on Insider Connected."""
import re

#: the project sidecar's key: ``{"on": true, "url": "http://192.168.1.50:8080/scores"}``
STAGED_KEY = "score_feed"
#: the runtime's file beside it on the card
CFG_NAME = "scorefeed.cfg"
#: what the runtime needs of the port (pad_mode_runtime.c feed_arm)
PORT_SITES = ("tick", "hook_dispatch")
PORT_EVENTS = ("game_start", "ball_start")
#: the runtime's limits (FEED_HOST_MAX, FEED_PATH_MAX less their NUL)
HOST_MAX, PATH_MAX = 95, 159

LABEL = "Score feed"
NO_TITLE = "The app cannot tell which game this project is for."
NO_PORT = "The app does not know %s well enough to see when its games end."
#: what the card does, for the tab and the log (%s: the address)
HOW = ("at the end of each game the players' final scores, and the Insider Connected login of each player who was "
       "logged in, are posted to %s")
#: the Modes tab's line under the tick
NOTE = "After each game the machine posts the final scores here."
#: the box's hint
PLACEHOLDER = "http://192.168.1.50:8080/scores"

_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


class ScoreFeedError(ValueError):
    """An address the machine cannot post to."""


def url_problem(url):
    """Why the machine cannot post to *url*, or ``""``: an ``http://`` address with an IPv4 host (the machine looks
    no names up: that would hold the game up), an optional port and path."""
    url = (url or "").strip()
    if not url:
        return "Type the address of your server, like %s." % PLACEHOLDER
    low = url.lower()
    if low.startswith("https://"):
        return ("The machine posts plain http://, not https://: give your server's http:// address on your own "
                "network.")
    if not low.startswith("http://"):
        return "The address starts with http://, like %s." % PLACEHOLDER
    rest = url[7:]
    m = re.match(r"^([^/:?]*)(?::([^/?]*))?([/?].*)?$", rest)
    if not m or not m.group(1):
        return "The address has no server in it, like %s." % PLACEHOLDER
    host, port, path = m.group(1), m.group(2), m.group(3) or "/"
    ip = _IPV4.match(host)
    if not ip or any(int(x) > 255 for x in ip.groups()):
        return ("Give the server as its IP address (like 192.168.1.50), not a name: the machine does not look names "
                "up.")
    if host in ("0.0.0.0", "255.255.255.255"):
        return "%s is not a server's address." % host
    if host.startswith("127."):
        return ("%s is the machine itself: give the IP address of the computer that runs your server." % host)
    if port is not None and (not port.isdigit() or not 0 < int(port) < 65536):
        return "The port after the colon is a number from 1 to 65535."
    if len(host) > HOST_MAX or len(path) > PATH_MAX:
        return "The address is too long for the machine (up to %d characters after the server)." % PATH_MAX
    if any(c.isspace() for c in path) or any(ord(c) < 0x20 or ord(c) > 0x7e for c in path):
        return "The address has a space or a character the machine cannot send in it."
    return ""


def load(project):
    """``(on, url)`` from the project's sidecar."""
    if not project:
        return False, ""
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: off
        return False, ""
    if not isinstance(raw, dict):
        return False, ""
    url = raw.get("url") if isinstance(raw.get("url"), str) else ""
    return bool(raw.get("on")), url


def save(project, on, url=None):
    """Ask (or stop asking) for it; *url* None keeps the address there was. Returns ``(on, url)`` as it was. The
    address is kept when the tick goes off, so ticking it again needs no retyping."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    raw = data.get(STAGED_KEY) if isinstance(data.get(STAGED_KEY), dict) else {}
    was = (bool(raw.get("on")), raw.get("url") if isinstance(raw.get("url"), str) else "")
    new_url = was[1] if url is None else (url or "").strip()
    if on or new_url:
        data[STAGED_KEY] = {"on": bool(on), "url": new_url}
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def wanted(project):
    """The address when the project asks for the feed and it is one the machine can post to, else ``""``."""
    on, url = load(project)
    return url.strip() if on and not url_problem(url) else ""


def port_ok(port):
    """1 when a parsed port names what the runtime watches a game's end by."""
    if not port:
        return False
    events = {e[0] for e in port.get("event", ()) if len(e) > 1 and e[1] == "bus"}
    return all(s in port.get("site", {}) for s in PORT_SITES) and all(e in events for e in PORT_EVENTS) \
        and ("scores" in port.get("data", {}) or "scores32" in port.get("data", {}))


def title_refusal(prof):
    """Why ``prof``'s game cannot carry the feed, or ``""``."""
    if prof is None:
        return NO_TITLE
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label
    return "" if port_ok(port) else NO_PORT % prof.label


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def users_line(game_elf):
    """``users <manager> <A> <B>``: where the game keeps its players' Insider logins (coop_play.insider_users), or
    ``""`` when the finder does not see them in this program (the reports then name no logins)."""
    from . import coop_play as CP
    try:
        u = CP.insider_users(game_elf) if game_elf else None
    except Exception:                                   # noqa: BLE001 - a build the finder cannot read
        u = None
    return "users 0x%08x 0x%x 0x%x" % u if u else ""


def cfg_text(url, title, game_elf, only):
    """``scorefeed.cfg``: the address, the game's name for the reports, the logins' tables when *game_elf* shows them;
    *only* when the card carries no modes (the runtime then arms this and nothing else)."""
    why = url_problem(url)
    if why:
        raise ScoreFeedError(why)
    title = " ".join((title or "").split())[:63]
    users = users_line(game_elf)
    return ("# PAD-1204: each game's final scores, posted to the owner's own server\n"
            "feed %s\n" % url.strip() + ("title %s\n" % title if title else "") + (users + "\n" if users else "")
            + ("only\n" if only else ""))


#: PAD-1204 (David: "I'd like to see the sample API contract for the scores API"): what the machine sends and what it
#: expects back, as the Play options tab shows it. The fields are pad_mode_runtime.c feed_json's, in its order.
FIELDS = (
    ("source", "string", 'always "PAD score feed"'),
    ("game", "string", "the game and its version, as the app names the card"),
    ("port", "string", "the same in the app's short form (game key and version)"),
    ("game_number", "integer", "games sent since the machine was switched on: 1, 2, 3..."),
    ("time", "integer or null", "the machine's clock in Unix seconds; null when the clock was never set"),
    ("players", "integer", "how many played, 1 to 4"),
    ("scores", "array of integers", "each player's final score, player 1 first (one per player)"),
    ("insider", "array of strings or null",
     "each player's Insider Connected account id (8-4-4-4-12 hex, the same every game); null for a player who was "
     "not logged in"),
)
#: a game's report as the machine sends it (two players, player 1 logged in)
SAMPLE = {"source": "PAD score feed", "game": "Godzilla Premium/LE 1.16", "port": "godzilla_le 1.16",
          "game_number": 3, "time": 1794510083, "players": 2, "scores": [123456780, 98765430],
          "insider": ["3f2a9c1e-5b7d-4e20-8a61-0c9d2b4f7e13", None]}
#: what the server answers, and what the machine does when it does not
ANSWER = ("Answer with any 2xx status (200 or 204); the body is not read. Anything else, no answer within 5 s, or a "
          "refused connection counts as not taken: the machine tries again 10 s later, 3 tries in all, then lets that "
          "game go. The game never waits for your server.")


def sample_request(url=PLACEHOLDER):
    """The request the machine sends to *url* for :data:`SAMPLE`, as text (HTTP/1.0, one line of JSON)."""
    import json
    m = re.match(r"^http://([^/:?]+)(?::(\d+))?([/?].*)?$", (url or "").strip()) or \
        re.match(r"^http://([^/:?]+)(?::(\d+))?([/?].*)?$", PLACEHOLDER)
    host, port, path = m.group(1), m.group(2), m.group(3) or "/"
    if not path.startswith("/"):
        path = "/" + path
    body = json.dumps(SAMPLE, separators=(",", ":"))
    return ("POST %s HTTP/1.0\nHost: %s\nUser-Agent: PAD-score-feed\nContent-Type: application/json\n"
            "Content-Length: %d\nConnection: close\n\n%s"
            % (path, host + (":" + port if port and port != "80" else ""), len(body), body))


def contract(url=""):
    """The Play options tab's API contract for the score feed, for *url* (or the example address)."""
    import json
    good = url and not url_problem(url)
    return {"request": sample_request(url.strip() if good else PLACEHOLDER),
            "body": json.dumps(SAMPLE, indent=2),
            "fields": [{"name": n, "type": t, "what": w} for n, t, w in FIELDS],
            "answer": ANSWER}
