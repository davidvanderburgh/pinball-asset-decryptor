"""The JJP stick maker copies the BOOT FILES FIRST (plugins/jjp/usbstick.py).

A fresh FAT32 volume hands out clusters in copy order, and the machine's
firmware reads the loader, the kernel and the initrd through the BIOS.  A
plain sorted() copy put those files behind 13 GB of home/partimag image
pieces on the GNR multi-boot stick, and the machine sat on syslinux's
"Automatic boot in 1 second..." instead of booting (item 121, 2026-09-14).
The copy order is now syslinux/, then live/vmlinuz + live/initrd.img, then the
other boot trees, then everything else."""
import os

from pinball_decryptor.plugins.jjp import usbstick

FILES = (
    ("home", "partimag", "img", "sda3.ext4-ptcl-img.gz.aa"),
    ("home", "partimag", "img", "sda5.ext4-ptcl-img.gz.aa"),
    ("utils", "win64", "syslinux64.exe"),
    ("live", "filesystem.squashfs"),
    ("live", "vmlinuz"),
    ("live", "initrd.img"),
    ("EFI", "boot", "bootx64.efi"),
    ("boot", "grub", "grub.cfg"),
    ("syslinux", "syslinux.cfg"),
    ("syslinux", "vesamenu.c32"),
    ("syslinux", "ldlinux.c32"),
    ("syslinux", "JJP_Recovery_1024_Blank_0bars.png"),
    ("jjp", "pad_install.sh"),
    ("Clonezilla-Live-Version",),
)


def _iso(tmp_path):
    iso = tmp_path / "iso"
    for parts in FILES:
        p = iso.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * (len(parts) * 7))
    return iso


def test_the_loader_then_the_kernel_then_the_rest():
    ranks = {rel: usbstick._copy_rank(rel) for rel in (
        "syslinux/ldlinux.c32", "syslinux\\vesamenu.c32", "SYSLINUX/syslinux.cfg",
        "syslinux/JJP_Recovery_1024_Blank_0bars.png", "isolinux/isolinux.bin",
        "live/vmlinuz", "live\\initrd.img", "LIVE/VMLINUZ",
        "live/filesystem.squashfs", "EFI/boot/bootx64.efi", "boot/grub/grub.cfg",
        "home/partimag/img/sda3.ext4-ptcl-img.gz.aa", "jjp/pad_install.sh",
        "utils/win64/syslinux64.exe", "Clonezilla-Live-Version")}
    assert [r for r, k in ranks.items() if k == 0] == [
        "syslinux/ldlinux.c32", "syslinux\\vesamenu.c32", "SYSLINUX/syslinux.cfg",
        "syslinux/JJP_Recovery_1024_Blank_0bars.png", "isolinux/isolinux.bin"]
    assert [r for r, k in ranks.items() if k == 1] == ["live/vmlinuz", "live\\initrd.img", "LIVE/VMLINUZ"]
    assert [r for r, k in ranks.items() if k == 2] == [
        "live/filesystem.squashfs", "EFI/boot/bootx64.efi", "boot/grub/grub.cfg"]
    assert all(k == 3 for r, k in ranks.items() if r.startswith(("home", "jjp", "utils", "Clonezilla")))


def test_copy_order_puts_every_boot_file_before_the_first_image_piece(tmp_path):
    iso = _iso(tmp_path)
    order = [os.path.relpath(p, str(iso)).replace("\\", "/")
             for p in usbstick._copy_order(str(iso), usbstick._iter_files(str(iso)))]
    assert order[:4] == ["syslinux/JJP_Recovery_1024_Blank_0bars.png", "syslinux/ldlinux.c32",
                         "syslinux/syslinux.cfg", "syslinux/vesamenu.c32"]
    assert order[4:6] == ["live/initrd.img", "live/vmlinuz"]
    assert set(order[6:9]) == {"EFI/boot/bootx64.efi", "boot/grub/grub.cfg", "live/filesystem.squashfs"}
    first_piece = order.index("home/partimag/img/sda3.ext4-ptcl-img.gz.aa")
    assert first_piece > order.index("live/vmlinuz")
    assert first_piece > order.index("live/initrd.img")
    assert first_piece > order.index("syslinux/ldlinux.c32")
    assert len(order) == len(FILES)


def test_the_pipeline_copies_in_that_order_and_still_verifies(tmp_path):
    """Folder mode: the progress text names each file as it is copied."""
    iso = _iso(tmp_path)
    dev = tmp_path / "dev"
    dev.mkdir()
    copied, logs, done = [], [], {}

    def progress(value, total=100, desc=""):
        if desc.startswith("Copying ") and desc[8:] not in copied:
            copied.append(desc[8:])
    p = usbstick.UsbStickPreparePipeline(
        str(iso), str(dev), lambda m, lvl="info": logs.append(m),
        lambda i: None, progress, lambda ok, msg="": done.update(ok=ok, msg=msg))
    p.run()
    assert done.get("ok") is True, done
    copied = [c.replace("\\", "/") for c in copied]
    assert copied[0].startswith("syslinux/")
    assert copied.index("live/vmlinuz") < copied.index("home/partimag/img/sda3.ext4-ptcl-img.gz.aa")
    assert copied.index("live/initrd.img") < copied.index("EFI/boot/bootx64.efi")
    assert any("the boot files first" in m for m in logs)
    for parts in FILES:
        assert os.path.isfile(dev.joinpath(*parts))
