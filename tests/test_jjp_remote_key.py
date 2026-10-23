"""The JJP security key on another PC, over USB/IP (PAD-529).

plugins/jjp/remote_key.py: the setting, the one shell script every verb runs
(driven here against a fake ``usbip`` client, so the lease rules are tested
without a kernel), the extract pipeline's branch and the Emulate tab's.  The
real transport - a USB/IP server, vhci-hcd, the key in sysfs - is proven by
tools/jjp_emu/usbip_standin.py, which needs WSL and is not run here.
"""

import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.jjp import remote_key as rk

R = rk.Remote("192.168.1.20", 3240, "1-4")


# ------------------------------------------------------------- the setting
@pytest.mark.parametrize("text,want", [
    ("192.168.1.20", ("192.168.1.20", 3240)),
    ("keybox", ("keybox", 3240)),
    ("keybox.lan:3241", ("keybox.lan", 3241)),
    (" 10.0.0.5 ", ("10.0.0.5", 3240)),
])
def test_server_takes_a_name_or_ipv4_and_an_optional_port(text, want):
    assert rk.parse_server(text) == want


@pytest.mark.parametrize("text", [
    "", "a b", "host;reboot", "$(id)", "host:0", "host:99999", "host:x",
    "-r", "a..b", "'q'", "host`x`",
])
def test_server_refuses_anything_a_shell_could_read_as_more(text):
    with pytest.raises(ValueError):
        rk.parse_server(text)


@pytest.mark.parametrize("ok", ["1-4", "3-1.2", "12-10.1.3"])
def test_busid_as_servers_list_it(ok):
    assert rk.parse_busid(ok) == ok


@pytest.mark.parametrize("bad", ["", "1", "1-", "a-1", "1-4;x", "0529:0001"])
def test_busid_refuses_the_rest(bad):
    with pytest.raises(ValueError):
        rk.parse_busid(bad)


def test_only_a_complete_valid_entry_is_a_key_server():
    assert rk.from_settings(None) is None
    assert rk.from_settings({"where": "local", "server": "h",
                             "busid": "1-4"}) is None
    assert rk.from_settings({"where": "usbip", "server": "",
                             "busid": "1-4"}) is None
    assert rk.from_settings({"where": "usbip", "server": "h",
                             "busid": ""}) is None
    assert rk.from_settings({"where": "usbip", "server": "h:3241",
                             "busid": "2-1"}) == rk.Remote("h", 3241, "2-1")


def test_env_overrides_the_setting(monkeypatch):
    rk.configure({"where": "local"})
    assert rk.current() is None
    monkeypatch.setenv(rk.ENV, "keybox:3241/1-5")
    assert rk.current() == rk.Remote("keybox", 3241, "1-5")
    monkeypatch.setenv(rk.ENV, "bad host/1-5")
    assert rk.current() is None


def test_describe_leaves_the_usual_port_out():
    assert rk.describe(R) == "bus 1-4 on 192.168.1.20"
    assert rk.describe(rk.Remote("h", 3241, "1-4")) == "bus 1-4 on h:3241"


def test_the_command_carries_no_dollar_for_wsl_to_eat():
    cmd = rk.command("attach", R, "extract",
                     client="/mnt/c/Program Files/usbipd-win/WSL/usbip")
    assert "$" not in cmd and "`" not in cmd
    assert cmd.endswith("-- attach '/mnt/c/Program Files/usbipd-win/WSL/usbip'"
                        " 192.168.1.20 3240 1-4 extract")


def test_the_command_rechecks_what_reaches_the_shell():
    with pytest.raises(ValueError):
        rk.command("attach", rk.Remote("h;id", 3240, "1-4"), "extract")
    with pytest.raises(ValueError):
        rk.command("attach", R, "Bad Tag")
    with pytest.raises(ValueError):
        rk.command("rm", R, "extract")


# ------------------------------------------ the script, on a fake client
# The fake client keeps "imported" ports in a state dir and answers port /
# attach / detach / list the way usbip-utils prints them.  Its server offers
# 1-4 and 1-5; 1-5 is "in use by another PC"; host "deadhost" never answers.
FAKE = r'''
S=$FAKE_STATE
case "$1" in --tcp-port) PORT=$2; shift 2;; *) PORT=3240;; esac
case "$1" in
port)
    echo "Imported USB devices"; echo "===================="
    for f in "$S"/port*; do [ -e "$f" ] || continue
        n=${f##*/port}; read -r url < "$f"
        echo "Port 0$n: <Port in Use> at Full Speed(12Mbps)"
        echo "       unknown vendor : unknown product (0529:0001)"
        echo "       3-1 -> $url"
        echo "           -> remote bus/dev 001/004"
    done ;;
attach)
    HOST=$3; BUS=$5
    [ "$HOST" = deadhost ] && { echo "usbip: error: tcp connect"; exit 1; }
    [ "$BUS" = 1-5 ] && { echo "usbip: error: Attach Request for 1-5 failed - Device busy (exported)"; exit 1; }
    [ "$BUS" = 1-4 ] || { echo "usbip: error: Attach Request for $BUS failed - Device not found"; exit 1; }
    n=0; while [ -e "$S/port$n" ]; do n=$((n+1)); done
    echo "usbip://$HOST:$PORT/$BUS" > "$S/port$n" ;;
detach)
    rm -f "$S/port$3"; echo "usbip: info: Port $3 is now detached!" ;;
list)
    [ "$3" = deadhost ] && { echo "usbip: error: could not connect"; exit 1; }
    echo "Exportable USB devices"; echo " - $3"
    echo "        1-4: unknown vendor : unknown product (0529:0001)" ;;
esac
'''


def _bash_head():
    """How to reach bash: here, on Windows, ``bash`` is WSL's and the
    environment does not cross into it, so the variables ride in the
    command itself (and the paths are WSL paths)."""
    if sys.platform == "win32":
        if not shutil.which("wsl.exe"):
            pytest.skip("no WSL")
        return ["wsl.exe", "-e", "bash", "-c"], True
    b = shutil.which("bash")
    if not b:
        pytest.skip("no bash")
    return [b, "-c"], False


def _posix(path):
    p = str(path).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


@pytest.fixture
def sh(tmp_path):
    """run(cmd) -> output, with the fake client and a private lease dir."""
    head, wsl = _bash_head()
    client = tmp_path / "usbip"
    client.write_bytes(("#!/bin/bash\n" + FAKE).encode())
    client.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    pre = "export PATH=/usr/bin:/bin FAKE_STATE=%s PAD_REMOTEKEY_LEASES=%s; " \
        % (_posix(state), _posix(tmp_path / "leases"))
    if wsl:
        pre += "chmod +x %s 2>/dev/null; " % _posix(client)

    def run(cmd):
        # the fake client stands in for usbipd-win's
        for verb in ("attach", "release", "probe"):
            cmd = cmd.replace(" -- %s '' " % verb,
                              " -- %s %s " % (verb, _posix(client)))
        out = subprocess.run(head + [pre + cmd], timeout=60,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return out.stdout.decode()

    run.state = state
    return run


@pytest.fixture(autouse=True)
def _no_usbipd_win_client(monkeypatch):
    monkeypatch.setattr(rk, "client_path", lambda: "")


K4 = rk.Remote("keybox", 3240, "1-4")


def test_attach_then_release_detaches(sh):
    assert rk.probe(sh, K4) == "offered"
    assert rk.attach(sh, K4, "extract") == ("attached", "0")
    assert rk.probe(sh, K4) == "attached"
    assert rk.release(sh, K4, "extract") == ("detached", "0")
    assert not list(sh.state.iterdir())


def test_a_second_user_borrows_and_the_last_one_out_detaches(sh):
    rk.attach(sh, K4, "extract")
    assert rk.attach(sh, K4, "emulate") == ("borrowed", "0")
    assert rk.release(sh, K4, "extract") == ("kept", "emulate")
    assert (sh.state / "port0").exists()
    assert rk.release(sh, K4, "emulate")[0] == "detached"


def test_a_retry_release_and_attach_keeps_the_other_users_key(sh):
    rk.attach(sh, K4, "emulate")
    rk.attach(sh, K4, "extract")
    # the extract's retry: give back its lease and attach again
    rk.release(sh, K4, "extract")
    assert rk.attach(sh, K4, "extract") == ("borrowed", "0")
    assert (sh.state / "port0").read_text().strip() \
        == "usbip://keybox:3240/1-4"


def test_a_key_attached_before_us_is_never_detached(sh):
    (sh.state / "port0").write_bytes(b"usbip://keybox:3240/1-4\n")
    assert rk.attach(sh, K4, "extract") == ("borrowed", "0")
    assert rk.release(sh, K4, "extract") == ("kept", "external")
    assert (sh.state / "port0").exists()


def test_only_the_named_bus_on_the_named_server_is_ours(sh):
    (sh.state / "port0").write_bytes(b"usbip://otherbox:3240/1-4\n")
    assert rk.attach(sh, K4, "extract") == ("attached", "1")
    rk.release(sh, K4, "extract")
    assert (sh.state / "port0").exists() and not \
        (sh.state / "port1").exists()


@pytest.mark.parametrize("remote,kind", [
    (rk.Remote("keybox", 3240, "1-5"), "busy"),
    (rk.Remote("keybox", 3240, "1-9"), "notexported"),
    (rk.Remote("deadhost", 3240, "1-4"), "unreachable"),
])
def test_each_fault_is_named(sh, remote, kind):
    with pytest.raises(rk.RemoteKeyError) as e:
        rk.attach(sh, remote, "extract")
    assert e.value.kind == kind
    assert remote.busid in str(e.value) or remote.host in str(e.value)


def test_probe_faults(sh):
    assert rk.probe(sh, rk.Remote("deadhost", 3240, "1-4")) == "unreachable"
    assert rk.probe(sh, rk.Remote("keybox", 3240, "1-9")) == "notexported"


def test_release_of_a_key_that_is_gone_is_quiet(sh):
    assert rk.release(sh, K4, "extract")[0] == "gone"


# --------------------------------------------------- the extract pipeline
def _pipeline(monkeypatch):
    from pinball_decryptor.plugins.jjp import pipeline as P
    logs = []
    pl = P.DecryptionPipeline("x.iso", "out",
                              lambda t, lv: logs.append(t),
                              lambda i: None, lambda *a: None,
                              lambda *a: None)

    def no_win(*a, **k):
        raise AssertionError("usbipd-win in remote mode: %r" % (a,))

    pl.executor.run_win = no_win
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    monkeypatch.setattr(pl, "_dongle_visible", lambda: True)
    monkeypatch.setattr(pl, "_start_hasp_daemon", lambda *a, **k: None)
    return P, pl, logs


def test_pipeline_attaches_from_the_server_and_releases_only_its_lease(
        monkeypatch):
    P, pl, logs = _pipeline(monkeypatch)
    monkeypatch.setenv(rk.ENV, "keybox/1-4")
    calls = []
    monkeypatch.setattr(rk, "attach", lambda run, r, tag: (
        calls.append(("attach", r, tag)) or ("attached", "0")))
    monkeypatch.setattr(rk, "release", lambda run, r, tag: (
        calls.append(("release", r, tag)) or ("kept", "emulate")))
    pl._phase_dongle()
    assert calls == [("attach", K4, "extract")]
    pl._reattach_dongle()
    assert calls[1:] == [("release", K4, "extract"),
                         ("attach", K4, "extract")]
    pl._detach_dongle()
    pl._detach_dongle()             # a second cleanup has nothing to give
    assert calls[3:] == [("release", K4, "extract")]
    assert any("still in use (emulate)" in t for t in logs)


def test_pipeline_names_the_fault_as_a_dongle_error(monkeypatch):
    P, pl, _ = _pipeline(monkeypatch)
    monkeypatch.setenv(rk.ENV, "keybox/1-5")

    def busy(run, r, tag):
        raise rk.RemoteKeyError("busy", rk.message("busy", r))

    monkeypatch.setattr(rk, "attach", busy)
    with pytest.raises(P.PipelineError) as e:
        pl._phase_dongle()
    assert "in use by another PC" in str(e.value)
    assert pl._remote_key is None


def test_pipeline_cleanup_in_remote_mode_never_detaches_by_hardware_id(
        monkeypatch):
    P, pl, _ = _pipeline(monkeypatch)
    monkeypatch.setenv(rk.ENV, "keybox/1-4")
    pl._detach_dongle()             # nothing attached by this run


def test_pipeline_local_mode_is_unchanged(monkeypatch):
    P, pl, _ = _pipeline(monkeypatch)
    monkeypatch.delenv(rk.ENV, raising=False)
    rk.configure({"where": "local"})
    seen = []
    pl.executor.run_win = lambda argv, timeout=0: (
        seen.append(argv[1:]) or (0, "", ""))
    pl._detach_dongle()
    assert seen == [["detach", "--hardware-id", "0529:0001"]]
