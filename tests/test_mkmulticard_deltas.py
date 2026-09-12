"""mkmulticard's delta half (item 107), pure python: the work partition in the store plan,
its sizing from the deltas, the plan rows, and the selector-dir refusal.  The real ext4
(the delta blob in .blobs/, the tree's index, verify's rebuild, update's gc, the formatted
p7) is the tool's `selftest` part 6d under WSL as root."""
import os
import sys

import pytest

from tests.test_mkmulticard import RIG, extra_8g, stock_8g  # noqa: F401 - the fixtures' helpers

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(RIG, "mkmulticard.py")),
                                reason="mkmulticard.py not present")


@pytest.fixture()
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


def test_a_store_plan_with_work_sectors_lays_p7_after_p6_and_without_none(mk):
    g = stock_8g(mk)
    _t, s3, c3 = g.part(3)
    plain = mk.Plan(g, [extra_8g(mk, "x.raw")], "a.raw", ["x.raw"], "store", store_sectors=c3 + 4096000)
    assert plain.work_part is None and [p.num for p in plain.logs] == [5, 6]
    work = mk.Plan(g, [extra_8g(mk, "x.raw")], "a.raw", ["x.raw"], "store", store_sectors=c3 + 4096000,
                   work_sectors=8192)
    assert [p.num for p in work.logs] == [5, 6, 7] and work.work_part is work.logs[2]
    p6, p7 = work.logs[1], work.logs[2]
    assert p7.ebr == p6.start + p6.count and p7.start == mk.align_up(p7.ebr + 1) and p7.count == 8192
    assert p7.src is None and p7.ptype == 0x83
    assert work.total == p7.start + p7.count + mk.TAIL and work.total > plain.total
    assert work.table()[-1] == (7, 0x83, p7.start, 8192) and work.images == [work.prims[2]]
    assert work.unreachable() == [] and work.trees == plain.trees and work.devices() == plain.devices()
    # p5/p6 sit exactly where the plain plan puts them: the work partition only ever follows
    assert [(p.num, p.start, p.count) for p in work.logs[:2]] == [(p.num, p.start, p.count) for p in plain.logs]


def test_work_sectors_come_from_the_largest_delta_file(mk):
    ts = mk._treesync()
    a, _ = ts.mem_source_from({"t/image.bin": b"a" * 5000, "t/big.bin": b"b" * 9000})
    b, _ = ts.mem_source_from({"t/image.bin": b"c" * 5000, "t/big.bin": b"d" * 9000})
    mans = [ts.SourceManifest(a, {"size": 1, "mtime_ns": 1}, "u"), ts.SourceManifest(b, {"size": 1, "mtime_ns": 1}, "u")]
    assert mk.work_sectors_for(mans, [{}, {}]) == 0
    n = mk.work_sectors_for(mans, [{}, {"t/image.bin": {"bytes": 10}, "t/big.bin": {"bytes": 20}}])
    assert n % mk.ALIGN == 0 and n * mk.SECTOR >= int(9000 * (1 + mk.WORK_SLACK)) + mk.WORK_HEADROOM
    assert n == mk.work_sectors_for(mans, [{}, {"t/big.bin": {"bytes": 20}}])


def test_store_sectors_for_class_leaves_room_for_the_work_partition(mk):
    g = stock_8g(mk)
    c3 = g.part(3)[2]
    no_work = mk.store_sectors_for_class(g, [], "a.raw", [], [], "16G")
    with_work = mk.store_sectors_for_class(g, [], "a.raw", [], [], "16G", work_sectors=1 << 20)
    assert with_work < no_work and with_work >= c3
    plan = mk.Plan(g, [], "a.raw", [], "store", store_sectors=with_work, work_sectors=1 << 20)
    assert plan.total * mk.SECTOR <= mk.STERN_SIZES["16G"]
    assert mk.Plan(g, [], "a.raw", [], "store", store_sectors=with_work + mk.ALIGN, work_sectors=1 << 20).total * mk.SECTOR > mk.STERN_SIZES["16G"]


#: The work partition a 380 MB image.bin delta asks for - the file in C FB's six-image
#: Beatles card (PAD-135), and the reason that card's size check died.
BEATLES_WORK = 884736


def test_store_class_for_never_picks_a_class_the_planner_refuses(mk):
    """PAD-135: a stock 8G card's p3 fills the 8G class to the last sector, so the
    deltas' work partition puts it over - and the size class must be chosen by the
    planner rather than by an estimate that does not know that floor."""
    g = stock_8g(mk)
    XG = [extra_8g(mk, "x%d.raw" % i) for i in range(5)]
    xs = ["x%d.raw" % i for i in range(5)]
    subs = ["img%d" % (i + 1) for i in range(5)]
    with pytest.raises(mk.Refused):                # the class the estimate used to pick
        mk.store_sectors_for_class(g, XG, "a.raw", xs, subs, "8G", BEATLES_WORK)
    # ...over the whole run of unique-content totals that fit an 8G card at all: six
    # images that share nearly everything land here, and none of them may come back 8G
    for need in (5_000_000_000, 6_000_000_000, 6_300_000_000, 6_400_000_000):
        cls, cnt = mk.store_class_for(g, XG, "a.raw", xs, subs, need, BEATLES_WORK)
        assert cls == "16G" and cnt * mk.SECTOR >= need
        plan = mk.Plan(g, XG, "a.raw", xs, "store", multi_subdirs=subs,
                       store_sectors=cnt, work_sectors=BEATLES_WORK)
        assert plan.total_bytes <= mk.STERN_SIZES[cls]
    # with no deltas the same content still fits the 8G class, exactly as before
    assert mk.store_class_for(g, XG, "a.raw", xs, subs, 6_000_000_000)[0] == "8G"
    # ...and content no class can hold is refused for THAT reason, not for the layout's
    with pytest.raises(mk.Refused, match="biggest Stern image size"):
        mk.store_class_for(g, XG, "a.raw", xs, subs, 40_000_000_000)


def test_store_sectors_for_class_refusal_names_the_work_partition(mk):
    """The sentence the app's size strip now shows: what did not fit, and by how much."""
    g = stock_8g(mk)
    with pytest.raises(mk.Refused) as exc:
        mk.store_sectors_for_class(g, [], "a.raw", [], [], "8G", BEATLES_WORK)
    said = str(exc.value)
    assert "work partition" in said and "bigger card" in said and "over by" in said
    # ...and without deltas there is no work partition to blame
    with pytest.raises(mk.Refused) as exc:
        mk.store_sectors_for_class(g, [], "a.raw", [], [], "8G", 1 << 22)
    assert "work partition" in str(exc.value)


def test_print_plan_names_the_work_partition_and_the_deltas(mk, capsys):
    g = stock_8g(mk)
    c3 = g.part(3)[2]
    plan = mk.Plan(g, [extra_8g(mk, "x.raw")], "a.raw", ["x.raw"], "store", store_sectors=c3 + 4096000, work_sectors=8192)
    ts = mk._treesync()
    a, _ = ts.mem_source_from({"t/image.bin": b"a" * 5000})
    b, _ = ts.mem_source_from({"t/image.bin": b"c" * 5000})
    plan.manifests = [ts.SourceManifest(a, {"size": 1, "mtime_ns": 1}, "u"), ts.SourceManifest(b, {"size": 1, "mtime_ns": 1}, "u")]
    plan.store_deltas = [{}, {"t/image.bin": {"base": "k", "ranges": [(0, 4096)], "bytes": 4096}}]
    plan.store_unique = [5000, 4096]
    plan.store_shared = 904
    mk.print_plan(plan)
    out = capsys.readouterr().out
    assert "p7   0x83" in out and "work partition: empty ext4 made at build" in out
    assert "1 file(s) stored as byte-range DELTAS of an earlier image's, %s saved" % mk._gb(904) in out
    assert "image-size 1 /dev/mmcblk0p3:img1 4096" in out


def test_need_materializer_refuses_only_when_a_delta_is_planned(mk, tmp_path):
    g = stock_8g(mk)
    plan = mk.Plan(g, [extra_8g(mk, "x.raw")], "a.raw", ["x.raw"], "store", store_sectors=g.part(3)[2] + 4096000)
    sel = tmp_path / "sel"
    sel.mkdir()
    mk.need_materializer(plan, str(sel))                       # no deltas: nothing to need
    plan.store_deltas = [{}, {"t/image.bin": {"base": "k", "ranges": [(0, 4096)], "bytes": 4096}}]
    with pytest.raises(mk.Refused) as e:
        mk.need_materializer(plan, str(sel))
    assert "materialize.py" in str(e.value) and "buildselect.sh" in str(e.value)
    with pytest.raises(mk.Refused) as e:
        mk.need_materializer(plan, None)
    assert "--no-inject" in str(e.value)
    (sel / "materialize.py").write_text("#")
    mk.need_materializer(plan, str(sel))


def test_selector_files_ship_materialize_py_as_optional(mk):
    name, (card, mode, required) = "materialize.py", mk.SELECTOR_FILES["materialize.py"]
    assert card == "materialize.py" and mode == 0o755 and required is False
    assert list(mk.SELECTOR_FILES) == ["codeselect", "select.sh", "font.ttf", "materialize.py"]
