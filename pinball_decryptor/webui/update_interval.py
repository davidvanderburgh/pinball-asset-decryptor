"""How often the running app re-checks for updates (Settings, the gear,
> Check automatically)."""

# "Check for updates" choices in the ⚙ settings menu: how often the app
# re-checks the release feed while it is running.  (hours, label); the app
# always checks once at startup, so these only govern the RE-check — a session
# left open for days used to never notice a new version until the user went
# looking (a tester, batch 34).  ``UPDATE_INTERVAL_DEFAULT`` must be one of
# these values.
UPDATE_INTERVAL_CHOICES = (
    (0, "Only at startup"),
    (1, "Every hour"),
    (6, "Every 6 hours"),
    (24, "Once a day"),
)
UPDATE_INTERVAL_DEFAULT = 6


def normalize_update_interval(value):
    """The stored update-check interval as one of :data:`UPDATE_INTERVAL_CHOICES`.

    Anything missing, unparseable or not on the menu falls back to
    :data:`UPDATE_INTERVAL_DEFAULT` — a settings.json hand-edited to ``"6h"``
    or to a value a later version dropped must not leave the app with a timer
    it can't show the user.  ``0`` (startup only) is a real choice, not a
    missing one, so it survives.
    """
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return UPDATE_INTERVAL_DEFAULT
    return hours if hours in {h for h, _ in UPDATE_INTERVAL_CHOICES} \
        else UPDATE_INTERVAL_DEFAULT
