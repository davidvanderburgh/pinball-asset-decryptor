"""Online co-op: machines in different places playing toward one shared goal (PAD-1479; MODE_SDK.md "Online co-op",
docs/plans/pad1479-online-coop.md).

Captain Gordon (Discord): "A peer to peer mode for spike 2 co op mode, where asynchronous gameplay effects a shared
target like a high score" - separate machines over the internet, teams (Team Godzilla vs Team King Ghidorah taking
over cities as they reach score targets), a Pokemon island that fills up with every Pokemon rescued. David: "give
flexibility to the users to design their own online coop modes ... a bare minimum baseline of online coop that works
across all titles that is vanilla."

It rides on the score feed (:mod:`.score_feed`, PAD-1204): at the end of each game the card posts its report to the
campaign's server, and with online co-op on that report names the CAMPAIGN, the machine's TEAM, the MACHINE and the
campaign's join KEY, and carries the game's online COUNTS - numbers the owner's own modes add to (a mode file's
``online`` lines, a blocks mode's "Add to online count", ``pm_online_add`` in C). The server
(:mod:`pinball_decryptor.online_coop_server`) adds every machine's games up per team, hands out the campaign's
regions as the totals pass their targets, draws the map and posts it to a Discord channel.

The vanilla campaign (:func:`vanilla_design`) needs nothing designed: every machine is on one team, each game's
score counts, and five goals of rising size are the shared high-score target. A designed campaign names its teams,
what counts (the game's score, or one of the online counts), and its regions with their targets.

The project sidecar's ``online_coop``: ``{"on", "url", "campaign", "team", "machine", "key", "design"}``. The address
is the score feed's: with online co-op on, the card's feed posts to the campaign's server (an owner's own score feed
address is kept for when online co-op is off again)."""
import json
import re

from . import score_feed as SF

STAGED_KEY = "online_coop"
LABEL = "Online co-op"
#: the runtime's limits (FEED_WORD_MAX, FEED_KEY_MAX, FEED_NAME_MAX less their NUL; FEED_COUNTS)
WORD_MAX, KEY_MAX, COUNT_NAME_MAX, COUNTS_MAX = 31, 47, 23, 8
#: a design's limits (the server's map)
TEAMS_MAX, REGIONS_MAX = 8, 24
TARGET_MAX = 10 ** 15
PLACEHOLDER = "http://203.0.113.10:8090/"
#: what the card does, for the tab and the log (%s: campaign, team, address)
HOW = ("each game's report names campaign \"%s\" and team \"%s\" and is posted to the campaign's server at %s, with "
       "the game's online counts")
NOTE = ("Every game played on this machine counts toward its team in the campaign: the server adds all the machines' "
        "games up, takes the regions as the team's total passes their targets, and posts the map to Discord.")

_COUNT = re.compile(r"^[A-Za-z0-9_.\-]{1,%d}$" % COUNT_NAME_MAX)
#: a team's colour on the map
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOURS = ("#e5484d", "#3e63dd", "#30a46c", "#f5a524", "#8e4ec6", "#12a594", "#e93d82", "#978365")


class OnlineCoopError(ValueError):
    """Settings the card or the server cannot use."""


def word_problem(what, s, cap=WORD_MAX, empty_ok=False):
    """Why *s* cannot be the card's *what* (a campaign, team or machine name; the join key), or ``""``."""
    s = s if isinstance(s, str) else ""
    if not s.strip():
        return "" if empty_ok else "Give the %s a name." % what
    if len(s.strip()) > cap:
        return "The %s is up to %d characters." % (what, cap)
    if any(ord(c) < 0x20 or ord(c) > 0x7e for c in s):
        return "The %s is letters, digits, spaces and plain punctuation (no accents or emoji)." % what
    return ""


def count_problem(name):
    """Why *name* cannot be an online count's name, or ``""``."""
    if not isinstance(name, str) or not name:
        return "Give the count a name, like pokemon_rescued."
    if not _COUNT.match(name):
        return ("A count's name is up to %d letters, digits and _ - . (no spaces), like pokemon_rescued."
                % COUNT_NAME_MAX)
    return ""


def vanilla_design():
    """The campaign with nothing designed: one team, every game's score counting, five goals of rising size - the
    shared high score every machine plays toward."""
    return {"title": "Shared high score", "teams": [{"name": "Everyone", "colour": COLOURS[1]}],
            "goal": {"kind": "score"},
            "regions": [{"name": "Goal %d" % (i + 1), "target": t}
                        for i, t in enumerate((10 ** 7, 25 * 10 ** 6, 5 * 10 ** 7, 10 ** 8, 25 * 10 ** 7))]}


#: designs to start from (the Network tab's Design... dialog), each a whole design
EXAMPLES = {
    "vanilla": vanilla_design(),
    "kaiju_war": {"title": "Kaiju War",
                  "teams": [{"name": "Team Godzilla", "colour": "#30a46c"},
                            {"name": "Team King Ghidorah", "colour": "#f5a524"}],
                  "goal": {"kind": "score"},
                  "regions": [{"name": n, "target": t} for n, t in (
                      ("Tokyo", 10 ** 9), ("Osaka", 10 ** 9), ("San Francisco", 2 * 10 ** 9), ("London", 2 * 10 ** 9),
                      ("Paris", 3 * 10 ** 9), ("New York", 5 * 10 ** 9), ("Monster Island", 10 ** 10))]},
    "rescue_island": {"title": "Rescue Island",
                      "teams": [{"name": "Rescuers", "colour": "#3e63dd"}],
                      "goal": {"kind": "count", "count": "rescued"},
                      "regions": [{"name": n, "target": t} for n, t in (
                          ("The beach", 25), ("The forest", 75), ("The lake", 150), ("The caves", 300),
                          ("The volcano", 500))]},
}


def design_problems(design):
    """Every reason *design* is not one the server can run (``[]`` when it is)."""
    out = []
    if not isinstance(design, dict):
        return ["The campaign has no design."]
    w = word_problem("campaign's title", design.get("title"), 63)
    if w:
        out.append(w)
    teams = design.get("teams")
    if not isinstance(teams, list) or not teams:
        out.append("A campaign has at least one team.")
        teams = []
    elif len(teams) > TEAMS_MAX:
        out.append("A campaign has up to %d teams." % TEAMS_MAX)
    names = []
    for t in teams:
        if not isinstance(t, dict):
            out.append("A team is a name and a color.")
            continue
        w = word_problem("team", t.get("name"))
        if w:
            out.append(w)
        elif t["name"].strip().lower() in names:
            out.append("Two teams are called %s." % t["name"].strip())
        else:
            names.append(t["name"].strip().lower())
        if not _COLOUR.match(str(t.get("colour", ""))):
            out.append("%s's colour is a #rrggbb colour." % (t.get("name") or "A team"))
    goal = design.get("goal")
    if not isinstance(goal, dict) or goal.get("kind") not in ("score", "count"):
        out.append("A campaign counts the game's score or one of the online counts.")
    elif goal["kind"] == "count":
        w = count_problem(goal.get("count"))
        if w:
            out.append(w)
    regions = design.get("regions")
    if not isinstance(regions, list) or not regions:
        out.append("A campaign has at least one region to take.")
        regions = []
    elif len(regions) > REGIONS_MAX:
        out.append("A campaign has up to %d regions." % REGIONS_MAX)
    seen = []
    for r in regions:
        if not isinstance(r, dict):
            out.append("A region is a name and a target.")
            continue
        w = word_problem("region", r.get("name"), 31)
        if w:
            out.append(w)
        elif r["name"].strip().lower() in seen:
            out.append("Two regions are called %s." % r["name"].strip())
        else:
            seen.append(r["name"].strip().lower())
        t = r.get("target")
        if isinstance(t, bool) or not isinstance(t, int) or not 0 < t <= TARGET_MAX:
            out.append("%s's target is a whole number from 1 up." % (r.get("name") or "A region"))
    return out


def _clean_design(design):
    """*design* as it is kept: names stripped, numbers as ints."""
    d = json.loads(json.dumps(design))
    d["title"] = " ".join(str(d.get("title", "")).split())
    for t in d.get("teams", []):
        t["name"] = " ".join(str(t.get("name", "")).split())
        t["colour"] = str(t.get("colour", "")).lower()
    for r in d.get("regions", []):
        r["name"] = " ".join(str(r.get("name", "")).split())
    return d


def load(project):
    """The project's online co-op settings, every key there (off and the vanilla design when it has none)."""
    raw = {}
    if project:
        from ...core import staged_changes
        try:
            got = staged_changes.load(project).get(STAGED_KEY)
        except Exception:                                   # noqa: BLE001 - an unreadable sidecar: off
            got = None
        raw = got if isinstance(got, dict) else {}
    out = {"on": bool(raw.get("on"))}
    for k in ("url", "campaign", "team", "machine", "key"):
        out[k] = raw.get(k) if isinstance(raw.get(k), str) else ""
    out["design"] = raw["design"] if isinstance(raw.get("design"), dict) else vanilla_design()
    return out


def problems(settings):
    """Every reason *settings* (on) cannot go on a card, the address's first (``[]`` when they can)."""
    out = []
    why = SF.url_problem(settings.get("url"))
    if why:
        out.append(why.replace("your server", "the campaign's server"))
    for what, k, cap, empty in (("campaign", "campaign", WORD_MAX, False), ("machine", "machine", WORD_MAX, False),
                                ("join key", "key", KEY_MAX, True)):
        w = word_problem(what, settings.get(k), cap, empty)
        if w:
            out.append(w)
    design = settings.get("design") or {}
    teams = [t.get("name", "") for t in design.get("teams", []) if isinstance(t, dict)]
    if not settings.get("team", "").strip():
        out.append("Pick the machine's team.")
    elif settings["team"].strip() not in [" ".join(t.split()) for t in teams]:
        out.append("%s is not one of the campaign's teams." % settings["team"].strip())
    out += design_problems(design)
    return out


def save(project, **changes):
    """Change the project's settings (``on``, ``url``, ``campaign``, ``team``, ``machine``, ``key``, ``design``; the
    rest kept). Turning it on (or changing settings in the same call) with settings that cannot go on a card raises
    :class:`OnlineCoopError` and keeps what there was; a change while it is on is kept, and :func:`problems` says what
    keeps it off the card. Returns the settings now kept."""
    from ...core import staged_changes
    cur = load(project)
    new = dict(cur)
    for k, v in changes.items():
        if k not in cur:
            raise OnlineCoopError("No online co-op setting is called %s." % k)
        if k == "on":
            new[k] = bool(v)
        elif k == "design":
            if design_problems(v):
                raise OnlineCoopError(design_problems(v)[0])
            new[k] = _clean_design(v)
        else:
            new[k] = " ".join(str(v or "").split()) if k != "url" else str(v or "").strip()
            why = (SF.url_problem(new[k]).replace("your server", "the campaign's server") if k == "url" and new[k]
                   else word_problem({"key": "join key"}.get(k, k), new[k], KEY_MAX if k == "key" else WORD_MAX,
                                     True) if k != "url" else "")
            if why:
                raise OnlineCoopError(why)
            if k == "team" and new[k] and new[k] not in [t["name"] for t in new["design"]["teams"]]:
                raise OnlineCoopError("%s is not one of the campaign's teams." % new[k])
    if new["team"] and new["team"] not in [t["name"] for t in new["design"]["teams"]]:
        new["team"] = ""                                    # a team the design no longer has
    if not new["team"] and len(new["design"]["teams"]) == 1:
        new["team"] = new["design"]["teams"][0]["name"]     # one team: the machine is on it
    if changes.get("on"):                                   # switched on: everything must be right
        why = problems(new)
        if why:
            raise OnlineCoopError(why[0])
    data = staged_changes.load(project)
    data[STAGED_KEY] = new
    staged_changes.save(project, data)
    return new


def wanted(project):
    """The settings when the project asks for online co-op and the card can carry them, else None."""
    s = load(project)
    return s if s["on"] and not problems(s) else None


def cfg_lines(settings):
    """``scorefeed.cfg``'s online co-op lines for *settings*."""
    out = ["# PAD-1479: online co-op - the campaign this machine plays in",
           "online %s" % settings["campaign"].strip(), "team %s" % settings["team"].strip(),
           "machine %s" % settings["machine"].strip()]
    if settings.get("key", "").strip():
        out.append("key %s" % settings["key"].strip())
    return out


def campaign_file(settings):
    """The campaign file the server runs (``--campaign``): the design, the campaign's name and its join key."""
    d = _clean_design(settings.get("design") or vanilla_design())
    d["campaign"] = " ".join(str(settings.get("campaign", "")).split())
    d["key"] = str(settings.get("key", "")).strip()
    d["source"] = "PAD online co-op campaign"
    return d


def counts_in_modes(project):
    """The online counts the project's modes add to, sorted (a campaign counting one of them can name it)."""
    import os
    names = set()
    root = os.path.join(project or "", "modes")
    if not os.path.isdir(root):
        return []
    for slug in sorted(os.listdir(root)):
        folder = os.path.join(root, slug)
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, fn), encoding="utf-8") as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                continue
            if fn == "mode.json" and isinstance(doc, dict):
                for r in doc.get("online") or []:
                    if isinstance(r, list) and len(r) == 4 and not count_problem(r[1]):
                        names.add(r[1])
            for b in _ops(doc):
                if b.get("op") == "online_add" and not count_problem(b.get("count")):
                    names.add(b["count"])
    return sorted(names)


def _ops(node):
    """Every op dict under a blocks tree."""
    if isinstance(node, dict):
        if "op" in node:
            yield node
        for v in node.values():
            yield from _ops(v)
    elif isinstance(node, list):
        for v in node:
            yield from _ops(v)
