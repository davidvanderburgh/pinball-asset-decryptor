"""Shared HTTPS plumbing for the app's direct network calls.

The frozen macOS builds link the CI runner's Homebrew OpenSSL, whose
compiled-in CA path (/opt/homebrew/etc/openssl@3, /usr/local/etc/openssl@3
on Intel) only exists on Macs that happen to have Homebrew installed.  On
any other Mac the default SSL context has NO trust roots, so every HTTPS
request dies with CERTIFICATE_VERIFY_FAILED — surfacing to users as
"couldn't reach GitHub" from the update check even though their internet
is fine.  certifi ships a CA bundle *inside* the app, so prefer it
everywhere; fall back to the platform default (fine on Windows, which
reads the OS cert store, and on Linux distro Pythons).
"""

import ssl
import urllib.request


def tls_context():
    """Return an SSL context whose trust roots exist on the user's machine."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def urlopen(req, timeout):
    """`urllib.request.urlopen` pinned to :func:`tls_context`."""
    return urllib.request.urlopen(req, timeout=timeout,
                                  context=tls_context())
