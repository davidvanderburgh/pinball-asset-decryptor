"""PAD-749: the Partitions tab lists the partitions inside a card's extended
one (sda5, sda6), where a Spike 2 machine keeps its own logs; every other
caller of CardImage keeps seeing the primaries only."""
import struct

from pinball_decryptor.plugins.stern import explorer
from pinball_decryptor.plugins.stern.explorer import CardImage


def _entry(ptype, lba, sectors):
    return struct.pack("<B3sB3sII", 0, b"\0\0\0", ptype, b"\0\0\0", lba, sectors)


def _table(entries):
    out = bytearray(512)
    for i, e in enumerate(entries):
        out[446 + 16 * i:446 + 16 * (i + 1)] = e
    out[510:512] = b"\x55\xaa"
    return bytes(out)


def _card(path):
    """sda1 FAT, sda2 ext4, sda4 extended (LBA 300, 200 sectors) holding
    sda5 (EBR at 300, data +1, 40 sectors) and sda6 (EBR at 350, +1, 100)."""
    disk = bytearray(512 * 600)
    disk[0:512] = _table([_entry(0x0C, 10, 50), _entry(0x83, 100, 150),
                          b"\0" * 16, _entry(0x05, 300, 200)])
    disk[300 * 512:301 * 512] = _table([_entry(0x83, 1, 40), _entry(0x05, 50, 150)])
    disk[350 * 512:351 * 512] = _table([_entry(0x83, 1, 100)])
    path.write_bytes(bytes(disk))
    return str(path)


class _Reader:
    def __init__(self, f, offset, size):
        self.offset, self.size = offset, size


def test_logical_partitions_listed_for_the_partitions_tab(tmp_path, monkeypatch):
    monkeypatch.setattr(explorer, "Ext4Reader", _Reader)
    card = _card(tmp_path / "card.raw")
    with CardImage(card, logical=True) as c:
        parts = c.partitions()
        assert [(p.index + 1, p.kind, p.browsable) for p in parts] == [
            (1, "fat", False), (2, "ext", True), (4, "extended", False),
            (5, "ext", True), (6, "ext", True)]
        assert [(p.offset, p.size) for p in parts[3:]] == [(301 * 512, 40 * 512), (351 * 512, 100 * 512)]
        assert c.reader(5).offset == 351 * 512


def test_other_callers_see_the_primaries_only(tmp_path, monkeypatch):
    monkeypatch.setattr(explorer, "Ext4Reader", _Reader)
    card = _card(tmp_path / "card.raw")
    with CardImage(card) as c:
        assert [p.index + 1 for p in c.partitions()] == [1, 2, 4]


def test_the_partitions_tab_opens_cards_with_logical_partitions():
    import inspect
    from pinball_decryptor.webui.tabs import partitions
    src = inspect.getsource(partitions)
    assert src.count("CardImage(") == src.count("logical=True)") == 3
