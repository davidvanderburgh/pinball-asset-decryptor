"""PAD-613: the app keeps its disk use in check on its own
(core/space_keeper.py) - what it removes, what it never touches, when it
runs, and what the Manage disk space window says about it."""

import os
import time

import pytest

from pinball_decryptor.core import host_temp, space_keeper as sk, wsl_disk

DAY = 86400
GB = 1024 ** 3
NOW = 2_000_000_000


def scan(staging=(), cache=(), live=(), held=(), deps=None,
         free=100 * GB, used=10 * GB):
    return {"free": free, "used": used, "live": set(live), "held": set(held),
            "staging": [dict(path=p, size=s, last=NOW - age)
                        for p, s, age in staging],
            "cache": [dict(root=r, path=p, size=s, last=NOW - age)
                      for r, p, s, age in cache],
            "deps": dict(deps or {})}


def paths(plan):
    return [p["path"] for p in plan]


# ---------------------------------------------------------------- the scan
def test_parse_scan_reads_every_line_kind():
    text = "\n".join([
        "D\t17481355264\t81685553152",
        "L\tpad_spooky",
        "H\t/var/tmp/jjp_x/sda3.raw",
        "S\t388532691\t1727700000\t/var/tmp/jjp_raw_GnR.img",
        "C\tpad_dp\t3769889532\t1727600000\t"
        "/var/tmp/pad_dp/cache/TBL_justin_113_v10+TBL-v1.15",
        "B\t/var/tmp/pad_pbio/cache/build-a+b\t/var/tmp/pad_pbio/cache/os-a",
        "garbage", "S\tnot-a-number\t1\t/x"])
    s = sk.parse_scan(text)
    assert (s["free"], s["used"]) == (17481355264, 81685553152)
    assert s["live"] == {"pad_spooky"}
    assert s["held"] == {"/var/tmp/jjp_x/sda3.raw"}
    assert s["staging"] == [{"path": "/var/tmp/jjp_raw_GnR.img",
                             "size": 388532691, "last": 1727700000}]
    assert s["cache"][0]["root"] == "pad_dp"
    assert s["deps"] == {"/var/tmp/pad_pbio/cache/os-a":
                         ["/var/tmp/pad_pbio/cache/build-a+b"]}


def test_the_scan_script_has_no_unfilled_placeholders():
    assert "@MIN@" not in sk._SCAN and "@BOFMULTI@" not in sk._SCAN
    assert "/var/tmp/pad_bofmulti_cache/*/" in sk._SCAN


# ---------------------------------------------------------------- leftovers
def test_a_leftover_goes_once_a_day_has_passed_without_change():
    s = scan(staging=[("/var/tmp/jjp_raw_GnR.img", GB, 2 * DAY),
                      ("/tmp/cgc_stage_pulp_fiction_77", GB, 3600),
                      ("/tmp/bof_lab_extracted", GB, DAY + 1)])
    plan = sk.plan_wsl(s, NOW)
    assert paths(plan) == ["/var/tmp/jjp_raw_GnR.img",
                           "/tmp/bof_lab_extracted"]
    assert {p["why"] for p in plan} == {"leftover"}


def test_a_leftover_something_has_open_stays():
    s = scan(staging=[("/var/tmp/jjp_iso_GnR_0a1b2c3d", GB, 5 * DAY)],
             held=["/var/tmp/jjp_iso_GnR_0a1b2c3d/iso/sda3.ext4"])
    assert sk.plan_wsl(s, NOW) == []


def test_the_jjp_emulators_own_files_are_never_leftovers():
    """/var/tmp/jjp_<iso> is the JJP emulator's restored machine, and
    jjp_devices.json its settings: the old window called both "extract /
    write staging"."""
    s = scan(staging=[("/var/tmp/jjp_GunsNRoses-v03.03", GB, 60 * DAY),
                      ("/var/tmp/jjp_devices.json", 2 << 20, 60 * DAY),
                      ("/var/tmp/jjp_run", GB, 60 * DAY)])
    assert sk.plan_wsl(s, NOW) == []
    assert wsl_disk._jjp_detail("jjp_GunsNRoses-v03.03") == \
        "Emulator image: GunsNRoses-v03.03"
    assert wsl_disk._jjp_detail("jjp_devices.json") == \
        "the emulator's own files"
    assert wsl_disk._jjp_detail("jjp_verify_ab12") == "extract / write staging"


def test_a_path_outside_staging_is_never_planned():
    s = scan(staging=[("/var/tmp/other_thing", GB, 90 * DAY),
                      ("/var/tmp/jjp_raw_x;rm -rf /", GB, 90 * DAY)])
    assert sk.plan_wsl(s, NOW) == []


# ---------------------------------------------------------------- emulators
def test_an_emulator_game_goes_after_30_days_unplayed():
    s = scan(cache=[
        ("pad_ap", "/var/tmp/pad_ap/cache/tank", 7 * GB, 31 * DAY),
        ("pad_ap", "/var/tmp/pad_ap/cache/hotwheels", 6 * GB, 29 * DAY),
        ("pad_dp", "/var/tmp/pad_dp/cache/TBL_justin_113_v10+TBL-v1.15",
         3 * GB, 40 * DAY),
        ("jjp", "/var/tmp/jjp_GunsNRoses-v03.03", GB, 45 * DAY),
        ("pad_bofmulti_cache",
         "/var/tmp/pad_bofmulti_cache/BoF_lab.fun-29-17", 4 * GB, 35 * DAY)])
    plan = sk.plan_wsl(s, NOW)
    assert paths(plan) == [
        "/var/tmp/pad_ap/cache/tank",
        "/var/tmp/pad_dp/cache/TBL_justin_113_v10+TBL-v1.15",
        "/var/tmp/jjp_GunsNRoses-v03.03",
        "/var/tmp/pad_bofmulti_cache/BoF_lab.fun-29-17"]
    assert {p["why"] for p in plan} == {"unused"}
    assert plan[2]["what"] == \
        "Jersey Jack Pinball: emulator image GunsNRoses-v03.03"


def test_nothing_of_a_running_or_open_emulator_goes():
    s = scan(cache=[
        ("pad_spooky", "/var/tmp/pad_spooky/cache/um_v1_18", GB, 90 * DAY),
        ("pad_pb", "/var/tmp/pad_pb/cache/predator_1_0", GB, 90 * DAY),
        ("jjp", "/var/tmp/jjp_Wonka", GB, 90 * DAY)],
        live=["pad_spooky"],
        held=["/var/tmp/pad_pb/cache/predator_1_0/game/x.so",
              "/var/tmp/jjp_Wonka/root"])
    assert sk.plan_wsl(s, NOW) == []


def test_a_half_unpacked_game_goes_after_a_day():
    s = scan(cache=[
        ("pad_spooky", "/var/tmp/pad_spooky/cache/um_v1_18.partial", GB,
         2 * DAY),
        ("pad_bof", "/var/tmp/pad_bof/cache/lab.partial", GB, 3600)])
    plan = sk.plan_wsl(s, NOW)
    assert paths(plan) == ["/var/tmp/pad_spooky/cache/um_v1_18.partial"]
    assert plan[0]["why"] == "leftover"


def test_a_pbio_os_image_takes_the_builds_stacked_on_it():
    os_img = "/var/tmp/pad_pbio/cache/os-clonezilla-live-alien40"
    build = "/var/tmp/pad_pbio/cache/build-clonezilla-live-alien40+x"
    s = scan(cache=[("pad_pbio", os_img, 5 * GB, 31 * DAY)],
             deps={os_img: [build]})
    plan = sk.plan_wsl(s, NOW)
    assert plan[0]["extra"] == [build]
    assert wsl_disk._is_rig_path(build)


def test_low_room_takes_the_least_recently_played_first_until_the_floor():
    s = scan(cache=[
        ("pad_ap", "/var/tmp/pad_ap/cache/a", 4 * GB, 10 * DAY),
        ("pad_ap", "/var/tmp/pad_ap/cache/b", 4 * GB, 20 * DAY),
        ("pad_pb", "/var/tmp/pad_pb/cache/c", 4 * GB, 5 * DAY),
        ("pad_pb", "/var/tmp/pad_pb/cache/now", 9 * GB, 600)])
    plan = sk.plan_wsl(s, NOW, room=8 * GB, floor=15 * GB)
    assert paths(plan) == ["/var/tmp/pad_ap/cache/b", "/var/tmp/pad_ap/cache/a"]
    assert {p["why"] for p in plan} == {"room"}
    # however short the room, a game started in the last hour stays
    plan = sk.plan_wsl(s, NOW, room=0, floor=100 * GB)
    assert "/var/tmp/pad_pb/cache/now" not in paths(plan)
    # and with room to spare nothing goes for room
    assert sk.plan_wsl(s, NOW, room=50 * GB) == []


def test_room_counts_what_age_already_frees():
    s = scan(cache=[("pad_ap", "/var/tmp/pad_ap/cache/old", 10 * GB, 40 * DAY),
                    ("pad_ap", "/var/tmp/pad_ap/cache/b", 4 * GB, 2 * DAY)])
    plan = sk.plan_wsl(s, NOW, room=8 * GB, floor=15 * GB)
    assert paths(plan) == ["/var/tmp/pad_ap/cache/old"]


def test_room_left_is_the_windows_drive_behind_the_disk_too():
    # the Linux sees 900 GB free on a 1 TB virtual disk, but the disk file
    # is 60 GB holding 55 GB, and the drive behind it has 4 GB left
    assert sk.room_left(900 * GB, 55 * GB, 60 * GB, 4 * GB) == 9 * GB
    assert sk.room_left(16 * GB, 80 * GB, 90 * GB, 300 * GB) == 16 * GB
    assert sk.room_left(16 * GB, 80 * GB) == 16 * GB
    assert sk.room_left(None, None) is None


# ---------------------------------------------------------------- Windows temp
def _aged(path, age):
    t = time.time() - age
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            os.utime(os.path.join(root, n), (t, t))
    os.utime(path, (t, t))


def test_temp_folder_leftovers_go_after_a_day_not_the_stern_caches(tmp_path):
    entries = []
    for name, age in (("spike2_godzilla_0a1b2c3d", 2 * DAY),
                      ("spike2_jaws_11111111", 3600),
                      ("spike2_card_cache", 30 * DAY),
                      ("pad-ffmpeg-abc", 5 * DAY)):
        d = tmp_path / name
        d.mkdir()
        (d / "f.bin").write_bytes(b"x" * (2 << 20))
        _aged(str(d), age)
        entries.append({"path": str(d), "size": 2 << 20,
                        "manufacturer": "Stern Pinball", "detail": name})
    # a file changed a minute ago inside an old folder keeps it
    busy = tmp_path / "spike2_tmnt_22222222"
    busy.mkdir()
    (busy / "old.bin").write_bytes(b"x" * (2 << 20))
    _aged(str(busy), 5 * DAY)
    (busy / "new.bin").write_bytes(b"y")
    entries.append({"path": str(busy), "size": 2 << 20,
                    "manufacturer": "Stern Pinball", "detail": "tmnt"})
    plan = sk.plan_host(entries, time.time())
    assert sorted(os.path.basename(p) for p in paths(plan)) == [
        "pad-ffmpeg-abc", "spike2_godzilla_0a1b2c3d"]


# ---------------------------------------------------------------- Spike 2 cards
def test_a_card_not_booted_for_30_days_goes_a_never_booted_one_stays():
    rows = [{"label": "gz", "real_kb": 7 << 20, "boot": NOW - 31 * DAY},
            {"label": "jaws", "real_kb": 7 << 20, "boot": NOW - 3 * DAY},
            {"label": "new", "real_kb": 7 << 20, "boot": 0}]
    plan = sk.plan_cards(rows, NOW)
    assert paths(plan) == ["gz"] and plan[0]["size"] == 7 * GB


# ---------------------------------------------------------------- the run
@pytest.fixture
def keeper(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SPACE_STATE", str(tmp_path / "keeper.json"))
    for v in ("PAD_UI_CAPTURE", "PAD_UI_NO_RIG", "PAD_SPACE_KEEPER"):
        monkeypatch.delenv(v, raising=False)
    calls = {"scan": 0, "deleted": [], "host": []}
    text = "\n".join([
        "D\t%d\t%d" % (100 * GB, 10 * GB),
        "S\t%d\t%d\t/var/tmp/jjp_raw_GnR.img" % (GB, NOW - 2 * DAY),
        "C\tpad_ap\t%d\t%d\t/var/tmp/pad_ap/cache/tank"
        % (7 * GB, NOW - 40 * DAY),
        "C\tpad_spooky\t%d\t%d\t/var/tmp/pad_spooky/cache/um"
        % (GB, NOW - 40 * DAY),
        "L\tpad_spooky"])

    def script(_s, timeout=0):
        calls["scan"] += 1
        return text

    def delete(ps):
        if any("pad_ap" in p for p in ps) and calls.get("refuse_ap"):
            raise wsl_disk.WslDiskError("A game is running")
        calls["deleted"] += ps
        return 0

    monkeypatch.setattr(wsl_disk, "_wsl_script", script)
    monkeypatch.setattr(wsl_disk, "delete", delete)
    monkeypatch.setattr(wsl_disk, "usage", lambda: {
        "free": 100 * GB, "used": 10 * GB, "total": 110 * GB, "pct": 9})
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx",
                        lambda: (None, None))
    monkeypatch.setattr(host_temp, "scan", lambda: [])
    return calls


def test_tidy_removes_the_plan_records_it_and_waits_six_hours(keeper):
    rec = sk.tidy(now=NOW, wsl=True)
    assert keeper["deleted"] == ["/var/tmp/jjp_raw_GnR.img",
                                 "/var/tmp/pad_ap/cache/tank"]
    assert rec["count"] == 2 and rec["freed"] == 8 * GB
    st = sk.load_state()
    assert st["checked"] == NOW and st["freed_total"] == 8 * GB
    assert sk.summary(st, NOW + 120).startswith(
        "Last clean-up 2 minutes ago removed 2 items and freed 8.0 GiB.")
    # not due again for six hours: only the cheap room check runs
    keeper["deleted"].clear()
    assert sk.tidy(now=NOW + 3600, wsl=True) is None
    assert keeper["scan"] == 1 and keeper["deleted"] == []
    assert sk.tidy(now=NOW + 7 * 3600, wsl=True) is not None
    assert keeper["scan"] == 2


def test_tidy_runs_early_when_room_is_short(keeper, monkeypatch):
    sk.tidy(now=NOW, wsl=True)
    monkeypatch.setattr(wsl_disk, "usage", lambda: {
        "free": 5 * GB, "used": 95 * GB, "total": 100 * GB, "pct": 95})
    assert sk.tidy(now=NOW + 600, wsl=True) is not None
    assert keeper["scan"] == 2


def test_one_emulator_refusing_keeps_only_its_own(keeper):
    keeper["refuse_ap"] = True
    rec = sk.tidy(now=NOW, wsl=True)
    assert keeper["deleted"] == ["/var/tmp/jjp_raw_GnR.img"]
    assert rec["count"] == 1


def test_one_stuck_leftover_does_not_keep_the_others(monkeypatch):
    done = []

    def delete(ps):
        if ps == ["/tmp/bof_stuck"]:
            raise wsl_disk.WslDiskError("still in use")
        if len(ps) > 1:
            raise wsl_disk.WslDiskError("still in use")
        done.extend(ps)

    monkeypatch.setattr(wsl_disk, "delete", delete)
    plan = [{"path": p, "size": 1, "extra": []}
            for p in ("/tmp/bof_stuck", "/tmp/bof_ok", "/var/tmp/jjp_raw_a")]
    kept = sk._remove_wsl(plan)
    assert done == ["/tmp/bof_ok", "/var/tmp/jjp_raw_a"]
    assert [p["path"] for p in kept] == done


def test_tidy_never_starts_wsl_and_never_runs_in_captures(keeper,
                                                          monkeypatch):
    monkeypatch.setattr(wsl_disk, "is_running", lambda: False)
    monkeypatch.setattr(wsl_disk, "is_supported", lambda: True)
    rec = sk.tidy(now=NOW)
    assert keeper["scan"] == 0 and rec["wsl"] is False
    monkeypatch.setenv("PAD_UI_CAPTURE", "1")
    assert sk.tidy(force=True, now=NOW, wsl=True) is None
    assert keeper["scan"] == 0


def test_a_dry_run_decides_but_deletes_and_saves_nothing(keeper):
    rec = sk.tidy(dry_run=True, now=NOW, wsl=True)
    assert len(rec["removed"]) == 2 and keeper["deleted"] == []
    assert sk.load_state() == {}


def test_summary_before_any_run_and_after_a_quiet_one(keeper):
    assert sk.summary({}, NOW) == "It has not run on this PC yet."
    assert sk.summary({"checked": NOW - 7200}, NOW) == \
        "Last checked 2 hours ago: nothing needed removing."


# ---------------------------------------------------------------- the window
def test_the_window_explains_the_automatic_clean_up_and_runs_it(
        tmp_path, monkeypatch):
    from tests.test_webui_shellx import until
    from tests.webui_harness import web_app
    monkeypatch.setattr(host_temp, "usage", lambda: None)
    monkeypatch.setattr(host_temp, "scan", lambda: [])
    ran = []
    monkeypatch.setattr(sk, "disabled", lambda: False)
    monkeypatch.setattr(sk, "tidy", lambda **kw: ran.append(kw) or {
        "count": 1})
    monkeypatch.setattr(sk, "summary", lambda *a: "Last clean-up just now "
                        "removed 1 item and freed 7.0 GiB.")
    with web_app(tmp_path, mfr="stern") as w:
        w.call("shellx.disk_open")
        assert until(w, lambda: not w.state("shellx")["disk"]["busy"])
        d = w.state("shellx")["disk"]
        assert "after 30 days unplayed" in d["auto_note"]
        assert "under 15 GB of room" in d["auto_note"]
        assert d["can_tidy"] is True
        assert w.call("shellx.disk_tidy_now") is True
        assert until(w, lambda: ran and not w.state("shellx")["disk"]["busy"])
        assert ran[0]["force"] is True
        assert w.state("shellx")["disk"]["auto_summary"].startswith(
            "Last clean-up just now")
        w.call("shellx.disk_close")


def test_wsl_disk_lists_names_with_a_plus_and_the_multiboot_cache():
    assert wsl_disk._is_rig_path(
        "/var/tmp/pad_dp/cache/TBL_justin_113_v10+TBL-v1.15")
    assert wsl_disk._rig_detail(wsl_disk.BOFMULTI_ROOT, None,
                                "BoF_lab.fun-29-17") == (
        "Unpacked for a multi-boot image: BoF_lab.fun-29-17", "game")
    assert wsl_disk.RIG_MAKERS[wsl_disk.BOFMULTI_ROOT] == "Barrels of Fun"
    assert wsl_disk.is_jjp_image("/var/tmp/jjp_Wonka-v03.03")
    assert not wsl_disk.is_jjp_image("/var/tmp/jjp_run")
    assert not wsl_disk.is_jjp_image("/var/tmp/jjp_raw_x.img")
