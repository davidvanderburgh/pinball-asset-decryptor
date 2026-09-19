#!/usr/bin/env python3
"""Make and read PREVIEW CODES (pinball_decryptor/core/preview.py).

    python tools/preview_code.py init
        Make David's signing key pair, ONCE. The private key goes to a file OUTSIDE the
        repo (default %APPDATA%\\pinball_decryptor_signing\\preview_signing_key.txt on
        Windows, ~/.config/pinball_decryptor_signing/ elsewhere); it is never printed.
        The public key is printed, to paste into PUBLIC_KEYS in core/preview.py.
        Refuses to overwrite a key that is already there, and refuses any path inside a
        git checkout.

    python tools/preview_code.py issue --name "Test Person" --days 90 [--feature modes]
        Print a code for that person, good through today (UTC) + DAYS. Signed with the
        key file; refused when that key is not one the app ships (a code the app would
        reject is worse than none).

    python tools/preview_code.py show <code>
        Decode a code and say whether this checkout's app accepts it.

BACK UP THE KEY FILE. Codes can only be made with it: if it is lost, no new code will
ever unlock a copy of the app that shipped its public key, and the fix is a new key pair
and a release carrying the new public key.

RUN init FROM AN ORDINARY TERMINAL. A process started by a packaged Windows app (a Store
or MSIX app, the Claude desktop app among them) has every NEW file it makes under
%APPDATA% silently redirected into that app's own folder,
%LOCALAPPDATA%\\Packages\\<app>\\LocalCache\\Roaming, where Explorer and other programs
cannot see it. That is how the first key was lost from view (2026-09-18). init refuses
the default path from such a process; issue looks in those folders when the key is not
at its ordinary place, and says where it found it.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import secrets
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pinball_decryptor.core import ed25519, preview  # noqa: E402

#: The first line of every key file, and what a test looks for in the repo.
KEY_MARKER = "# PAD PREVIEW SIGNING KEY - PRIVATE. Never commit, never share, back it up."
KEY_NAME = "preview_signing_key.txt"


def default_key_path():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "pinball_decryptor_signing", KEY_NAME)


def appdata_redirect_target():
    """The folder Windows really puts a NEW file made under %APPDATA% in, when this
    process runs in a packaged app's container, or ``""`` when it lands where it says.

    Asked by doing it: a probe file is made under %APPDATA% and looked for under every
    %LOCALAPPDATA%\\Packages\\<app>\\LocalCache\\Roaming. (Asking Windows for the
    process's package identity is not enough: the Claude desktop app's child processes
    have none, and their files are redirected all the same.)"""
    appdata = os.environ.get("APPDATA")
    local = os.environ.get("LOCALAPPDATA")
    if sys.platform != "win32" or not appdata or not local:
        return ""
    name = "pad_redirect_probe_%s.tmp" % secrets.token_hex(4)
    probe = os.path.join(appdata, name)
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("probe\n")
    except OSError:
        return ""
    try:
        root = os.path.join(local, "Packages")
        try:
            apps = os.listdir(root)
        except OSError:
            apps = []
        for app in apps:
            real = os.path.join(root, app, "LocalCache", "Roaming")
            if os.path.isfile(os.path.join(real, name)):
                return real
        return ""
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def redirected_keys():
    """Key files Windows redirected into a packaged app's private Roaming folder."""
    base = os.environ.get("LOCALAPPDATA")
    if sys.platform != "win32" or not base:
        return []
    root = os.path.join(base, "Packages")
    try:
        apps = sorted(os.listdir(root))
    except OSError:
        return []
    found = []
    for app in apps:
        cand = os.path.join(root, app, "LocalCache", "Roaming", "pinball_decryptor_signing",
                            KEY_NAME)
        if os.path.isfile(cand):
            found.append(cand)
    return found


def _under_appdata(path):
    base = os.environ.get("APPDATA")
    if not base:
        return False
    base = os.path.normcase(os.path.abspath(base)) + os.sep
    return os.path.normcase(os.path.abspath(path)).startswith(base)


def inside_git_checkout(path):
    """The checkout *path* would land in, or ``""``: a key file must never sit where a
    ``git add`` could pick it up."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return ""
        d = up


def read_secret(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError as e:
        raise SystemExit("Cannot read the signing key %s: %s" % (path, e))
    for ln in lines:
        if ln.startswith("secret="):
            raw = bytes.fromhex(ln.split("=", 1)[1])
            if len(raw) == ed25519.SECRET_SIZE:
                return raw
    raise SystemExit("%s is not a preview signing key file." % path)


def cmd_init(args):
    path = os.path.abspath(args.key)
    repo = inside_git_checkout(path)
    if repo:
        raise SystemExit("Refused: %s is inside the git checkout %s. The private key must "
                         "live outside every repository." % (path, repo))
    real = appdata_redirect_target() if _under_appdata(path) else ""
    if real:
        raise SystemExit("Refused: this command runs inside a packaged app's container, and "
                         "Windows would put a new file under %%APPDATA%% in %s instead, where "
                         "Explorer cannot see it. Run it from an ordinary terminal (Windows "
                         "Terminal, PowerShell), or pass --key with a path outside AppData."
                         % real)
    if os.path.exists(path):
        raise SystemExit("Refused: %s already exists. A new key would void every code the "
                         "shipped app accepts; move the old file away first if that is "
                         "really what you want." % path)
    secret = secrets.token_bytes(ed25519.SECRET_SIZE)
    pub = ed25519.public_key(secret).hex()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # created exclusively: never over a file that appeared meanwhile
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(KEY_MARKER + "\n")
        f.write("# Made %s by tools/preview_code.py init.\n"
                % _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        f.write("public=%s\n" % pub)
        f.write("secret=%s\n" % secret.hex())
    print("Private key written to %s" % path)
    print("BACK IT UP: without it no new code can be made for an app that ships this key.")
    print("Public key (paste into PUBLIC_KEYS in pinball_decryptor/core/preview.py):")
    print(pub)
    return 0


def cmd_issue(args):
    name = " ".join(str(args.name).split())
    if not name:
        raise SystemExit("--name is empty.")
    if args.days < 1:
        raise SystemExit("--days must be at least 1.")
    feats = args.feature or ["modes"]
    unknown = [f for f in feats if f not in preview.FEATURES]
    if unknown:
        raise SystemExit("Unknown feature(s) %s; this app has %s."
                         % (", ".join(unknown), ", ".join(sorted(preview.FEATURES))))
    key = os.path.abspath(args.key)
    if not os.path.isfile(key) and os.path.abspath(args.key) == os.path.abspath(default_key_path()):
        moved = redirected_keys()
        if len(moved) == 1:
            print("(the key is not at %s; using the copy Windows redirected to %s. Copy its "
                  "folder into %%APPDATA%% so it is where this tool and Explorer look.)"
                  % (key, moved[0]), file=sys.stderr)
            key = moved[0]
        elif len(moved) > 1:
            raise SystemExit("The key is not at %s, and there are %d redirected copies: %s. "
                             "Pass --key with the right one." % (key, len(moved), "; ".join(moved)))
    secret = read_secret(key)
    pub = ed25519.public_key(secret).hex()
    if pub not in preview.PUBLIC_KEYS:
        raise SystemExit("Refused: the key in %s is not one this app ships (PUBLIC_KEYS in "
                         "pinball_decryptor/core/preview.py), so the app would reject "
                         "every code it signs." % args.key)
    today = preview.utc_today()
    payload = preview.payload_bytes(feats, name, today, today + _dt.timedelta(days=args.days),
                                    secrets.token_hex(3))
    code = preview.encode(payload, ed25519.sign(secret, preview.CONTEXT + payload))
    grant = preview.check(code)             # the app's own check, before it is handed out
    print(code)
    print("(%s)" % "; ".join(preview.describe(grant)), file=sys.stderr)
    return 0


def cmd_show(args):
    text = " ".join(args.code)
    try:
        grant = preview.decode(text)
    except preview.PreviewCodeError as e:
        print("Not accepted: %s" % e)
        return 1
    print("id %s, for %s, issued %s, features %s"
          % (grant.id, grant.name, grant.issued.isoformat(), ", ".join(grant.features)))
    for line in preview.describe(grant):
        print(line)
    try:
        preview.check(text)
        print("This checkout's app accepts it.")
        return 0
    except preview.PreviewCodeError as e:
        print("Not accepted: %s" % e)
        return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="make the signing key pair (once)")
    p.add_argument("--key", default=default_key_path(), help="where the private key goes")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("issue", help="print a code for one person")
    p.add_argument("--name", required=True)
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--feature", action="append", help="a feature id (default: modes)")
    p.add_argument("--key", default=default_key_path(), help="the private key file")
    p.set_defaults(fn=cmd_issue)
    p = sub.add_parser("show", help="decode and check a code")
    p.add_argument("code", nargs="+")
    p.set_defaults(fn=cmd_show)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
