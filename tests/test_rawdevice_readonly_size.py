"""PAD-1429: a read-only open of a Windows card learns the card's size.

SEEK_END reports 0 on a \\\\.\\PHYSICALDRIVEn fd, so Remote access setup said
"Couldn't tell how big the card is." for a perfectly good 32 GB card.  The fd
backend now asks the drive for its length on a Windows device path.
"""
import types

from pinball_decryptor.core import rawdevice as R


def test_fd_backend_asks_the_drive_on_a_windows_device(tmp_path, monkeypatch):
    f = tmp_path / "card.img"
    f.write_bytes(b"\0" * 4096)
    io = R._FdIO(str(f), False)
    try:
        asked = []
        monkeypatch.setattr(R, "sys", types.SimpleNamespace(platform="win32"))
        monkeypatch.setattr(R, "is_device_path", lambda p: True)
        monkeypatch.setattr(R, "_win_fd_length",
                            lambda fd: asked.append(fd) or 31914983424,
                            raising=False)
        assert io.size() == 31914983424
        assert asked == [io.fd]
    finally:
        io.close()


def test_fd_backend_still_seeks_on_a_plain_file(tmp_path):
    f = tmp_path / "card.img"
    f.write_bytes(b"\0" * 4096)
    io = R._FdIO(str(f), False)
    try:
        assert io.size() == 4096
    finally:
        io.close()


# PAD-1566: the same on a Mac.  SEEK_END reports 0 on /dev/rdiskN too, so
# Remote access setup on macOS said "Couldn't tell how big the card is."


def _mac(monkeypatch):
    monkeypatch.setattr(R, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(R, "is_device_path", lambda p: True)


def test_fd_backend_asks_the_disk_driver_on_a_mac(tmp_path, monkeypatch):
    import struct
    f = tmp_path / "card.img"
    f.write_bytes(b"\0" * 4096)
    io = R._FdIO(str(f), False)
    try:
        _mac(monkeypatch)
        asked = []

        def ioctl(fd, req, buf):
            asked.append(req)
            if req == R._DKIOCGETBLOCKSIZE:
                return struct.pack("=I", 512)
            assert req == R._DKIOCGETBLOCKCOUNT
            return struct.pack("=Q", 60450816)
        import sys as real_sys
        monkeypatch.setitem(real_sys.modules, "fcntl", types.SimpleNamespace(ioctl=ioctl))
        monkeypatch.setattr(R, "_diskutil_total_size", lambda p: 1 / 0)
        assert io.size() == 60450816 * 512
        assert asked == [R._DKIOCGETBLOCKSIZE, R._DKIOCGETBLOCKCOUNT]
    finally:
        io.close()


def test_mac_falls_back_to_diskutil_on_the_whole_disk(tmp_path, monkeypatch):
    f = tmp_path / "card.img"
    f.write_bytes(b"\0" * 4096)
    io = R._FdIO(str(f), False)
    io.path = "/dev/rdisk4"
    try:
        _mac(monkeypatch)
        monkeypatch.setattr(R, "_mac_fd_length", lambda fd: None)
        asked = []
        monkeypatch.setattr(R, "_diskutil_total_size",
                            lambda p: asked.append(p) or 30953963520)
        assert io.size() == 30953963520
        assert asked == ["/dev/disk4"]
    finally:
        io.close()


def test_remote_access_open_learns_a_mac_cards_size(tmp_path, monkeypatch):
    """The Remote access open itself (ssh_spike3.open_stream) no longer gives up."""
    from pinball_decryptor.core import ssh_spike3
    f = tmp_path / "card.img"
    f.write_bytes(b"\0" * 8192)
    _mac(monkeypatch)
    monkeypatch.setattr(R, "_rdisk_path", lambda p: p)
    monkeypatch.setattr(R, "_mac_fd_length", lambda fd: 31914983424)
    stream, size = ssh_spike3.open_stream(str(f))
    try:
        assert size == 31914983424
    finally:
        stream.close()
