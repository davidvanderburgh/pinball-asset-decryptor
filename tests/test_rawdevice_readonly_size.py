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
