"""Animal shelter donations (PAD-754): the running total PAD users report.

The app takes no money.  It asks people who got something out of it to give
to an animal shelter near them, then say so in the app; this module talks to
the service that keeps the total (tools/donations_worker, a Cloudflare
Worker) and turns its answer into what the paw chip and the Animal shelters
window show.  It is the honor system: an entry is what someone typed.

Three parts, none of them touching the UI:

* the entry: :func:`validate_entry` cleans and bounds what the form sends;
* the wire: :func:`fetch_summary` and :func:`submit` (core/net.py HTTPS);
* the cache: the last summary and any entries that could not be sent, in a
  JSON file beside settings.json, so the chip draws at once with no
  network and a failed entry goes the next time the app starts.

:func:`view` is the one shape the page renders, built from the cached
summary, so the chip, the thermometer and the list never compute money.
"""

import json
import os
import time
import urllib.error
import urllib.request

from .atomic_file import write_json_atomic
from .net import urlopen

#: the ladder the thermometer climbs (tools/donations_worker/worker.js
#: MILESTONES is the same list; change both)
MILESTONES = (100, 200, 500, 1000, 2500, 5000, 10000, 25000, 50000,
              100000, 250000, 500000, 1000000)
#: an entry worth more than this (USD) is held by the service until David
#: approves it (the Worker's HOLD_OVER_USD; change both)
HOLD_OVER_USD = 299

#: code -> what goes before the amount in the list
CURRENCIES = (
    ("USD", "$"), ("EUR", "€"), ("GBP", "£"), ("CAD", "CA$"), ("AUD", "A$"),
    ("NZD", "NZ$"), ("CHF", "CHF "), ("SEK", "SEK "), ("NOK", "NOK "),
    ("DKK", "DKK "), ("JPY", "¥"), ("PLN", "PLN "), ("CZK", "CZK "),
    ("BRL", "R$"), ("MXN", "MX$"),
)
SYMBOLS = dict(CURRENCIES)
#: where the shelter is (optional): ISO code -> name, for the Top places
#: board.  The first entry is "not saying".
COUNTRIES = (
    ("", "Country (optional)"),
    ("US", "United States"), ("CA", "Canada"), ("GB", "United Kingdom"),
    ("AU", "Australia"), ("NZ", "New Zealand"), ("IE", "Ireland"),
    ("DE", "Germany"), ("FR", "France"), ("NL", "Netherlands"),
    ("BE", "Belgium"), ("ES", "Spain"), ("IT", "Italy"), ("PT", "Portugal"),
    ("AT", "Austria"), ("CH", "Switzerland"), ("SE", "Sweden"),
    ("NO", "Norway"), ("DK", "Denmark"), ("FI", "Finland"), ("PL", "Poland"),
    ("CZ", "Czechia"), ("HU", "Hungary"), ("GR", "Greece"), ("JP", "Japan"),
    ("KR", "South Korea"), ("SG", "Singapore"), ("BR", "Brazil"),
    ("MX", "Mexico"), ("AR", "Argentina"), ("ZA", "South Africa"),
    ("IL", "Israel"), ("AE", "United Arab Emirates"), ("IN", "India"),
    ("XX", "Somewhere else"),
)
COUNTRY_NAMES = dict(COUNTRIES)
#: the US states (and DC) the window's United States tile map draws: a
#: typed state or province is matched here by code or name
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}
_STATE_BY_NAME.update({"washington dc": "DC", "washington d c": "DC",
                       "d c": "DC"})
MAX_AMOUNT = 10000          # one entry, in its own currency (the Worker agrees)
MAX_SHELTER = 80
MAX_NAME = 40
MAX_REGION = 40
TIMEOUT = 8                 # seconds per request
# Every request names the app: Cloudflare's browser integrity check in
# front of the Worker refuses Python's default agent (403, error 1010),
# which the local wrangler proof could never show.
USER_AGENT = "Pinball-Asset-Decryptor-Donations"


def _headers(**extra):
    h = {"Accept": "application/json", "User-Agent": USER_AGENT}
    h.update(extra)
    return h
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
           "Oct", "Nov", "Dec")


class DonationsError(Exception):
    """The service refused the entry, with a message meant for the user."""


# ------------------------------------------------------------------ entry
def _clean(text, limit):
    return " ".join(str(text or "").split())[:limit]


def validate_entry(amount, currency="USD", shelter="", name="",
                   show_name=True, app_version="", country="", region=""):
    """What the form sends, cleaned, or :class:`ValueError` with the words
    the form shows.  A country the list does not know is dropped, not
    refused: where the shelter is stays optional."""
    raw = str(amount or "").strip().replace(",", "")
    for sym in sorted(SYMBOLS.values(), key=len, reverse=True):
        if raw.upper().startswith(sym.strip().upper()) and sym.strip():
            raw = raw[len(sym.strip()):].strip()
            break
    try:
        n = float(raw)
    except ValueError:
        raise ValueError("Enter the amount you gave.")
    if not n > 0 or n != n or n == float("inf"):
        raise ValueError("Enter the amount you gave.")
    if n > MAX_AMOUNT:
        raise ValueError("That is more than one entry can hold (10,000).")
    code = str(currency or "USD").upper()
    if code not in SYMBOLS:
        raise ValueError("Unknown currency.")
    where = str(country or "").strip().upper()
    if where not in COUNTRY_NAMES:
        where = ""
    return {"amount": round(n, 2), "currency": code,
            "shelter": _clean(shelter, MAX_SHELTER),
            "country": where,
            "region": _clean(region, MAX_REGION) if where else "",
            "name": _clean(name, MAX_NAME), "show_name": bool(show_name),
            "app_version": _clean(app_version, 24)}


def state_code(region):
    """"TX" for "Texas", "tx", "TX." or "texas "; "" when the typed state
    is not one of the fifty (or DC)."""
    r = " ".join(str(region or "").replace(".", " ").replace(",", " ").split())
    if not r:
        return ""
    if r.upper() in US_STATES:
        return r.upper()
    return _STATE_BY_NAME.get(r.lower(), "")


def fmt_place(country, region=""):
    """"Texas, US", "Ontario, Canada", "United Kingdom", "": the board's and
    the list's words for where a shelter is.  Only the US is shortened:
    "CA" after a province reads as California."""
    country = str(country or "").upper()
    if country not in COUNTRY_NAMES or not country:
        return ""
    region = _clean(region, MAX_REGION)
    if region:
        return "%s, %s" % (region, "US" if country == "US"
                           else COUNTRY_NAMES[country])
    return COUNTRY_NAMES[country]


# --------------------------------------------------------------- figures
def next_milestone(total):
    for m in MILESTONES:
        if total < m:
            return m
    return None


def last_milestone(total):
    last = 0
    for m in MILESTONES:
        if total >= m:
            last = m
    return last


def fmt_usd(n):
    """"$4,320" (whole dollars; the total is a headline, not a ledger)."""
    return "$%s" % format(int(round(float(n or 0))), ",")


def fmt_short(n):
    """"$500", "$2.5k", "$10k", "$1M": a milestone on the ladder."""
    n = float(n or 0)
    if n >= 1_000_000:
        v = n / 1_000_000
        unit = "M"
    elif n >= 1000:
        v = n / 1000
        unit = "k"
    else:
        return "$%d" % n
    text = ("%d" % v) if v == int(v) else ("%.1f" % v)
    return "$%s%s" % (text, unit)


def fmt_amount(amount, currency):
    """"$50", "£40", "CA$25", "€12.50": the donation in its own money."""
    amount = float(amount or 0)
    text = format(int(amount), ",") if amount == int(amount) \
        else format(amount, ",.2f")
    return "%s%s" % (SYMBOLS.get(currency, currency + " "), text)


def fmt_date_full(ts):
    """"Sep 3, 2026": a row of the All donations list."""
    try:
        t = time.localtime(float(ts))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    return "%s %d, %d" % (_MONTHS[t.tm_mon - 1], t.tm_mday, t.tm_year)


def history_rows(rows):
    """The All donations list's rows, from the service's ``/v1/all`` rows."""
    out = []
    for r in rows or ():
        if not isinstance(r, dict):
            continue
        out.append({"date": fmt_date_full(r.get("at")),
                    "name": _clean(r.get("name"), MAX_NAME) or "Anonymous",
                    "shelter": _clean(r.get("shelter"), MAX_SHELTER),
                    "where": fmt_place(r.get("country"), r.get("region")),
                    "amount": fmt_amount(r.get("amount"), r.get("currency"))})
    return out


def map_data(places):
    """What the tile maps light: every country, every US state a typed
    region matched, and what fell outside both."""
    world, states = {}, {}
    elsewhere = {"usd": 0.0, "count": 0}
    for p in places or ():
        if not isinstance(p, dict):
            continue
        code = str(p.get("country") or "").upper()
        usd = float(p.get("usd") or 0)
        n = int(p.get("count") or 0)
        if code not in COUNTRY_NAMES or not code:
            continue
        if code == "XX":
            elsewhere["usd"] += usd
            elsewhere["count"] += n
            continue
        w = world.setdefault(code, {"code": code, "label": COUNTRY_NAMES[code],
                                    "usd": 0.0, "count": 0})
        w["usd"] += usd
        w["count"] += n
        if code == "US":
            st = state_code(p.get("region"))
            if st:
                s = states.setdefault(st, {"code": st, "label": US_STATES[st],
                                           "usd": 0.0, "count": 0})
                s["usd"] += usd
                s["count"] += n
    for d in list(world.values()) + list(states.values()):
        d["amount"] = fmt_usd(d["usd"])
    return {"world": sorted(world.values(), key=lambda d: -d["usd"]),
            "us": sorted(states.values(), key=lambda d: -d["usd"]),
            "elsewhere": (dict(elsewhere, amount=fmt_usd(elsewhere["usd"]))
                          if elsewhere["count"] else None)}


def fmt_date(ts):
    """"Sep 3": the day a milestone fell, in the user's local time."""
    try:
        t = time.localtime(float(ts))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    return "%s %d" % (_MONTHS[t.tm_mon - 1], t.tm_mday)


def mine_row(entry, key, pending=False, held=False):
    """One of this install's own entries as the window lists it: the sent
    ones (``key`` is the service's id) and the ones still waiting to go
    (``key`` names the pending slot)."""
    return {"key": key, "pending": bool(pending), "held": bool(held),
            "amount": fmt_amount(entry.get("amount"), entry.get("currency")),
            "shelter": _clean(entry.get("shelter"), MAX_SHELTER),
            "where": fmt_place(entry.get("country"), entry.get("region")),
            "name": _clean(entry.get("name"), MAX_NAME),
            "entry": {k: entry.get(k, "") for k in (
                "amount", "currency", "shelter", "country", "region",
                "name", "show_name")}}


def view(summary, pending=(), currency="USD", name="", offline=False,
         country="", region="", mine=()):
    """What the page renders: the chip, the thermometer, the list, this
    install's own entries and the form's remembered choices.  ``summary``
    is the service's answer (or the cached one), ``None`` when nothing has
    ever been fetched; ``mine`` the sent entries with their ids and tokens
    (newest last)."""
    known = bool(summary) and summary.get("total_usd") is not None
    total = float(summary.get("total_usd") or 0) if known else 0.0
    count = int(summary.get("count") or 0) if known else 0
    nxt = next_milestone(total)
    last = last_milestone(total)
    if nxt is None:
        pct = 100
    else:
        pct = int(round(100.0 * (total - last) / (nxt - last)))
        pct = max(0, min(100, pct))
    reached = None
    fell = []
    if known:
        fell = [m for m in summary.get("milestones") or ()
                if isinstance(m, dict) and m.get("usd") is not None]
        if fell:
            top = fell[-1]
            reached = "%s reached %s" % (fmt_usd(top["usd"]),
                                         fmt_date(top.get("at")))
    # the ladder the window draws: every milestone with its state, and the
    # day the reached ones fell.  The window shows a few around "next".
    when = {}
    for m in fell:
        try:
            when[float(m["usd"])] = fmt_date(m.get("at"))
        except (TypeError, ValueError):
            pass
    ladder = []
    for m in MILESTONES:
        state = ("reached" if known and total >= m
                 else "next" if m == nxt else "ahead")
        ladder.append({"usd": m, "text": fmt_short(m), "state": state,
                       "date": when.get(float(m), "") if state == "reached"
                       else ""})
    i_next = next((i for i, c in enumerate(ladder) if c["state"] == "next"),
                  len(ladder))
    ladder = ladder[max(0, i_next - 2):i_next + 3]
    recent = []
    if known:
        for r in summary.get("recent") or ():
            if not isinstance(r, dict):
                continue
            recent.append({
                "name": _clean(r.get("name"), MAX_NAME) or "Anonymous",
                "shelter": _clean(r.get("shelter"), MAX_SHELTER),
                "where": fmt_place(r.get("country"), r.get("region")),
                "amount": fmt_amount(r.get("amount"), r.get("currency")),
            })
    places = []
    if known:
        for p in summary.get("places") or ():
            if not isinstance(p, dict):
                continue
            where = fmt_place(p.get("country"), p.get("region"))
            if not where:
                continue
            places.append({"where": where,
                           "usd": float(p.get("usd") or 0),
                           "count": int(p.get("count") or 0),
                           "amount": fmt_usd(p.get("usd"))})
    pending = [p for p in pending if isinstance(p, dict)]
    pending_usd = sum(float(p.get("amount") or 0) for p in pending
                      if p.get("currency") == "USD")
    own = [mine_row(m.get("entry") or {}, m.get("id"), held=m.get("held"))
           for m in reversed(list(mine))
           if isinstance(m, dict) and m.get("id")]
    own = [mine_row(p, "pending:%d" % i, pending=True)
           for i, p in reversed(list(enumerate(pending)))] + own
    chip = ("%s to shelters" % fmt_usd(total)) if known else "Animal shelters"
    if known:
        tip = ("PAD users have given %s to animal shelters, %d donation%s. "
               "Click to add yours." % (fmt_usd(total), count,
                                        "" if count == 1 else "s"))
    else:
        tip = "What PAD users have given to animal shelters. Click to add yours."
    return {
        "known": known,
        "total_usd": total,
        "total_text": fmt_usd(total) if known else "—",
        "last_text": fmt_short(last) if last else "$0",
        "ladder": ladder,
        "count": count,
        "count_text": ("%d donation%s" % (count, "" if count == 1 else "s"))
        if known else "",
        "pct": pct,
        "next_text": fmt_usd(nxt) if nxt else "",
        "next_short": fmt_short(nxt) if nxt else "",
        "reached_text": reached,
        "recent": recent,
        "places": places,
        "map": map_data(summary.get("places") if known else ()),
        "pending": len(pending),
        "pending_usd": pending_usd,
        "mine": own[:10],
        "hold_over": HOLD_OVER_USD,
        "rates": {k: v for k, v in ((summary or {}).get("rates") or {}).items()
                  if isinstance(v, (int, float))} if known else {},
        "offline": bool(offline),
        "chip": chip,
        "tip": tip,
        "currencies": [c for c, _ in CURRENCIES],
        "currency": currency if currency in SYMBOLS else "USD",
        "countries": [{"value": c, "label": n} for c, n in COUNTRIES],
        "country": country if country in COUNTRY_NAMES else "",
        "region": _clean(region, MAX_REGION),
        "name": _clean(name, MAX_NAME),
        "max_amount": MAX_AMOUNT,
    }


# ------------------------------------------------------------------ wire
def _read_json(resp):
    data = resp.read()
    try:
        out = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise DonationsError("The total did not answer properly.")
    if not isinstance(out, dict):
        raise DonationsError("The total did not answer properly.")
    return out


def fetch_summary(url, timeout=TIMEOUT):
    """The service's summary (raises on any failure: the caller keeps the
    cached one)."""
    if not url:
        raise DonationsError("No donations service is configured.")
    req = urllib.request.Request(url.rstrip("/") + "/v1/summary",
                                 headers=_headers())
    with urlopen(req, timeout) as resp:
        out = _read_json(resp)
    if not out.get("ok"):
        raise DonationsError(out.get("error") or "The total did not answer.")
    return out


def fetch_all(url, offset=0, limit=100, timeout=TIMEOUT):
    """A page of every donation, newest first (``/v1/all``)."""
    if not url:
        raise DonationsError("No donations service is configured.")
    req = urllib.request.Request(
        "%s/v1/all?offset=%d&limit=%d" % (url.rstrip("/"), max(0, int(offset)),
                                          max(1, int(limit))),
        headers=_headers())
    with urlopen(req, timeout) as resp:
        out = _read_json(resp)
    if not out.get("ok"):
        raise DonationsError(out.get("error") or "The list did not answer.")
    return out


def submit(url, key, entry, timeout=TIMEOUT):
    """Add ``entry`` (a :func:`validate_entry` dict).  Returns the fresh
    summary.  A refusal by the service (a bad entry, too many in an hour)
    is :class:`DonationsError` with its words; a network failure is the
    urllib error, so the caller can tell "keep it for later" from "wrong"."""
    if not url:
        raise DonationsError("No donations service is configured.")
    body = json.dumps(entry).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/donate", data=body, method="POST",
        headers=_headers(**{"Content-Type": "application/json",
                            "X-PAD-Key": key or ""}))
    try:
        with urlopen(req, timeout) as resp:
            out = _read_json(resp)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            try:
                msg = _read_json(e).get("error")
            except Exception:                           # noqa: BLE001
                msg = None
            raise DonationsError(msg or "The total refused that entry.")
        raise
    if not out.get("ok"):
        raise DonationsError(out.get("error") or "The total refused that entry.")
    return out


def remove(url, key, entry_id, token, timeout=TIMEOUT):
    """Take back an entry this app added: its id and the token the service
    answered when it was sent.  Returns the fresh summary.  An entry the
    service no longer has (hidden already) is :class:`DonationsError`; a
    network failure is the urllib error."""
    if not url:
        raise DonationsError("No donations service is configured.")
    req = urllib.request.Request(
        "%s/v1/donate/%s" % (url.rstrip("/"), entry_id), method="DELETE",
        headers=_headers(**{"X-PAD-Key": key or "", "X-PAD-Edit": token or ""}))
    try:
        with urlopen(req, timeout) as resp:
            out = _read_json(resp)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            try:
                msg = _read_json(e).get("error")
            except Exception:                           # noqa: BLE001
                msg = None
            raise DonationsError(msg or "That entry is already gone.")
        raise
    if not out.get("ok"):
        raise DonationsError(out.get("error") or "That entry is already gone.")
    return out


# ----------------------------------------------------------------- cache
def cache_path(settings_file):
    return os.path.join(os.path.dirname(settings_file), "donations_cache.json")


def load_cache(path):
    """``{"summary": dict|None, "fetched_at": float, "pending": [entries]}``;
    a missing or broken file is an empty cache."""
    out = {"summary": None, "fetched_at": 0.0, "pending": [], "mine": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    if isinstance(data.get("summary"), dict):
        out["summary"] = data["summary"]
    try:
        out["fetched_at"] = float(data.get("fetched_at") or 0)
    except (TypeError, ValueError):
        pass
    if isinstance(data.get("pending"), list):
        out["pending"] = [p for p in data["pending"] if isinstance(p, dict)]
    if isinstance(data.get("mine"), list):
        out["mine"] = [m for m in data["mine"]
                       if isinstance(m, dict) and m.get("id")]
    return out


def save_cache(path, cache):
    """Never raises: a cache that cannot be written is only a slower chip."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json_atomic(path, cache)
    except OSError:
        pass


def flush_pending(url, key, pending, timeout=TIMEOUT):
    """Send the entries kept from earlier.  Returns ``(remaining, summary)``:
    what still could not be sent (the service unreachable: the rest wait
    too) and the last summary the service answered with, or ``None``.  An
    entry the service refuses is dropped, not kept forever."""
    remaining = list(pending)
    summary = None
    while remaining:
        entry = remaining[0]
        try:
            summary = submit(url, key, entry, timeout)
        except DonationsError:
            remaining.pop(0)
            continue
        except (urllib.error.URLError, OSError, ValueError):
            break
        remaining.pop(0)
    return remaining, summary
