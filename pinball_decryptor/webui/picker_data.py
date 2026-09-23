"""The manufacturer picker's cards: each plugin's colour and letter logo,
the one-line peek of its games and the full list for the hover.

The picker itself is the page (``static/js/shell.js``); these feed it
(``tabs/shell_extras.py``).
"""


# Visual identity per plugin key.  Colors picked to evoke each
# manufacturer's actual branding:
#   pb     - Pinball Brothers: metallic / brushed-gold accents
#   spooky - Spooky Pinball:   Halloween orange
#   bof    - Barrels of Fun:   their site uses bright blue
#   jjp    - Jersey Jack:      red is their flagship colour
# These are placeholder "letter logos"; switching to actual bitmap logos
# would be straightforward once we have artwork (nominative fair use
# typically covers third-party tools like this, but a "not affiliated"
# README disclaimer is the standard hedge).
MFR_VISUALS = {
    "pb":       {"color": "#d4a017", "letter": "PB"},
    "spooky":   {"color": "#e64a19", "letter": "S"},
    "bof":      {"color": "#1565c0", "letter": "BoF"},
    "jjp":      {"color": "#c62828", "letter": "JJP"},
    # Williams classic logo is the cursive red "Williams" script; a
    # deep red mirrors that without colliding with JJP's slightly
    # brighter red.
    "williams": {"color": "#a01818", "letter": "W"},
    # CGC's brand uses a chrome/silver palette; muted blue-grey reads
    # as "premium remake" and stays distinct from BOF's saturated blue.
    "cgc":      {"color": "#37474f", "letter": "C"},
    # American Pinball's brand leans on a flag-inspired navy/red/silver
    # palette; deep navy reads patriotic without clashing with BOF's
    # brighter blue.
    "ap":       {"color": "#1a237e", "letter": "AP"},
    # Dutch Pinball's logo is a tulip-orange on black; a warm amber-orange
    # evokes the Dutch national colour and stays distinct from Spooky's
    # redder Halloween orange.
    "dp":       {"color": "#ff6f00", "letter": "DP"},
    # Stern Pinball's brand red (the "STERN" wordmark).  Shares the letter "S"
    # with Spooky but is a saturated true-red vs Spooky's orange, and the card's
    # name label disambiguates.
    "stern":    {"color": "#d9001c", "letter": "S"},
    # Data East — classic-DMD era (PinMAME).  A distinct teal keeps it clear
    # of the several reds/blues already in use.
    "data_east": {"color": "#00838f", "letter": "DE"},
    # Sega Pinball (classic Whitestar DMD, 1995-1999) — a bright Sega blue,
    # distinct from BOF's darker blue and AP's navy.
    "sega": {"color": "#0089cf", "letter": "SEGA"},
}


def peek_text(games, budget=72):
    """One-line comma-joined game names that fit within *budget* chars,
    with a "+N more" tail for the remainder.  Always shows at least the
    first name even if it alone exceeds the budget."""
    names = [g.display for g in games]
    shown, used = [], 0
    for nm in names:
        sep = 2 if shown else 0
        if shown and used + sep + len(nm) > budget:
            break
        shown.append(nm)
        used += sep + len(nm)
    text = ", ".join(shown)
    leftover = len(names) - len(shown)
    if leftover:
        text += f", +{leftover} more"
    return text


def tooltip_text(mfr):
    """Full game list for the hover tooltip — supported games marked
    with "+", unsupported with "✕" plus the reason when known."""
    lines = [mfr.display, ""]
    for g in mfr.games:
        if g.supported:
            lines.append(f"  +  {g.display}")
        else:
            reason = (f"  —  {g.unsupported_reason}"
                      if g.unsupported_reason else "")
            lines.append(f"  ✕  {g.display}{reason}")
    return "\n".join(lines)
