"""Update check must use the bundled-CA TLS path (core/net.py).

Regression guard for the macOS "Update Check Failed — couldn't reach
GitHub" report (flippermeister, v0.41.0): the frozen mac app's OpenSSL
has no default CA path on non-Homebrew Macs, so any direct
``urllib.request.urlopen`` HTTPS call fails certificate verification.
Every direct HTTPS call site must go through ``net.urlopen``, which
pins the context to certifi's bundled CA file.
"""

import io
import json
import ssl

from pinball_decryptor.core import musicid, net, updater


def test_tls_context_has_trust_roots():
    ctx = net.tls_context()
    assert isinstance(ctx, ssl.SSLContext)
    # certifi is a hard dependency (requirements.txt) precisely so the
    # frozen builds always have trust roots — with it installed the
    # context must actually contain CA certs, not be an empty store.
    import certifi  # noqa: F401
    assert ctx.get_ca_certs()


def test_check_for_update_routes_through_net_urlopen(monkeypatch):
    calls = []

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        body = json.dumps({
            "tag_name": "v99.0.0",
            "html_url": "https://example.com/rel",
            "body": "notes",
        }).encode()
        return FakeResp(body)

    monkeypatch.setattr(net, "urlopen", fake_urlopen)
    result = updater.check_for_update("0.1.0")
    assert calls and "api.github.com" in calls[0]
    assert result == ("99.0.0", "https://example.com/rel", "notes")


def test_musicid_default_opener_is_pinned():
    # The injectable-default pattern means the pinned opener is only used
    # when tests don't override it — make sure the default IS the pinned
    # one, not a bare urllib.request.urlopen.
    assert musicid.lookup.__defaults__[-1] is net.urlopen
