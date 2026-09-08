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
import urllib.error
import urllib.request


def tls_context():
    """Return an SSL context whose trust roots exist on the user's machine."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def urlopen(req, timeout):
    """`urllib.request.urlopen` pinned to :func:`tls_context`.

    With ONE fallback, for the case certifi gets exactly backwards: a managed
    machine behind a TLS-intercepting proxy is served a certificate signed by
    the company's own CA, which is installed in the OS trust store and is not
    in certifi's bundle — so the bundled roots, which exist to make HTTPS work
    on a Mac with no Homebrew, are what makes it fail at the office.  A
    verification failure (and only a verification failure) is retried against
    the platform's default trust, which on Windows is the OS store.  Anything
    else — DNS, refused, timeout, HTTP status — is raised as it happened, so a
    blocked host still reads as a blocked host.

    urllib's default opener reads ``HTTPS_PROXY``/``HTTP_PROXY`` from the
    environment on its own, so an explicit proxy needs nothing here.
    """
    try:
        return urllib.request.urlopen(req, timeout=timeout,
                                      context=tls_context())
    except urllib.error.URLError as exc:
        if not isinstance(getattr(exc, "reason", None),
                          ssl.SSLCertVerificationError):
            raise
        return urllib.request.urlopen(req, timeout=timeout,
                                      context=ssl.create_default_context())
