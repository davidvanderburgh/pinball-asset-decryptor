"""The user's own Spike 3 OTP key - where PAD keeps it, and whether it has
one (PAD-1090).

Everything Spike 3 needs that key: Extract decrypts the card with it, the
Emulate tab's first run of a card decrypts it into the Spike 3 store, Compare
reads both cards' files. PAD never ships it; the user brings their own, once:
the Extract tab's unlock, or the key gate on every other Spike 3 tab, verifies
it against a card and saves it to ONE per-user file,
``~/.pad/spike3_padkeys.json`` - kept across projects and app restarts, which
the old project-folder copy was not (David: "why don't I have the OTP key in
my local?").

A padkeys.json counts only when it carries an ``otp_keyfile``: a file beside
the cards may hold only the fleet .spk package key (``spk_keyfile``), and the
Emulate tab once handed exactly that one to the store, which refused it.
"""
import json
import os


def user_keyfile():
    """The per-user padkeys.json (it need not exist yet)."""
    return os.path.join(os.path.expanduser("~"), ".pad", "spike3_padkeys.json")


def has_otp(path):
    """True if *path* is a padkeys.json naming an OTP key (64 hex characters,
    or a key file that exists - a bare name is beside the padkeys.json)."""
    try:
        with open(path, "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        return False
    v = doc.get("otp_keyfile") if isinstance(doc, dict) else None
    if not isinstance(v, str) or not v.strip():
        return False
    s = v.strip().replace(" ", "")
    if len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s):
        return True
    return os.path.isfile(v) or os.path.isfile(
        os.path.join(os.path.dirname(os.path.abspath(path)), v))


def find_keyfile(card=None, project=None):
    """The padkeys.json holding the user's OTP key, or None: the one the
    Extract unlock named in this process ($PAD_SPIKE3_KEYFILE), one beside the
    card, the project folder's, then the per-user file. Only the PATH ever
    leaves this process (the key itself is never on a command line)."""
    cands = [os.environ.get("PAD_SPIKE3_KEYFILE") or ""]
    if card:
        c = os.path.abspath(card)
        cands += [c + ".padkeys.json", os.path.join(os.path.dirname(c), "padkeys.json")]
    if project:
        cands.append(os.path.join(project, "padkeys.json"))
    cands.append(user_keyfile())
    for c in cands:
        if c and os.path.isfile(c) and has_otp(c):
            return c
    return None


def save_key(key_path, card):
    """Verify the key file at *key_path* (OTP_KEY.TXT, a SPIKE3_KEY= line, 64
    hex characters or the raw 32 bytes) against *card* and, when it unlocks
    it, save it to the per-user file. ``(ok, message, keyfile)``."""
    from ..plugins.stern import spike3_selfextract as SX
    out = user_keyfile()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    res = SX.ingest_otp_key(key_path, card, out_path=out)
    if not res.verified:
        return False, res.message, None
    os.environ["PAD_SPIKE3_KEYFILE"] = res.sidecar
    return (True, "Your OTP key unlocks this card, and PAD has kept it (%s): "
            "every Spike 3 tab can use it now." % res.sidecar, res.sidecar)
