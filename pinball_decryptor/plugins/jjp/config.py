"""Constants and configuration for JJP Asset Decryptor."""

import sys

# USB dongle identification
HASP_VID_PID = "0529:0001"

# Paths inside JJP filesystem images
GAME_BASE_PATH = "/jjpe/gen1"
HASP_DAEMON_PATH = "/usr/sbin/hasplmd_x86_64"
MOUNT_PREFIX = "/mnt/jjp_"

# Timeouts (seconds)
MOUNT_TIMEOUT = 60
EXTRACT_TIMEOUT = 3600  # partclone extraction can take a while for large images
COMPILE_TIMEOUT = 60
DECRYPT_TIMEOUT = 600
COPY_TIMEOUT = 600
ISO_CONVERT_TIMEOUT = 7200  # partclone conversion can be slow for large images
ISO_BUILD_TIMEOUT = 3600    # xorriso ISO creation
DAEMON_STARTUP_WAIT = 3  # legacy, kept for reference
DAEMON_READY_TIMEOUT = 15  # seconds to poll for daemon readiness (port 1947)
USB_SETTLE_TIMEOUT = 10  # seconds to wait for USB device to appear in WSL after usbipd attach

# Clonezilla ISO structure
PARTIMAG_PATH = "/home/partimag/img"  # where partclone images live inside ISO
GAME_PARTITION = "sda3"  # partition containing the game data

# Progress reporting interval in the C decryptor
PROGRESS_INTERVAL = 100

# Known JJP games (display names)
KNOWN_GAMES = {
    "Wonka": "Willy Wonka & the Chocolate Factory",
    "GunsNRoses": "Guns N' Roses",
    "EltonJohn": "Elton John",
    "TheHobbit": "The Hobbit",
    "TheGodfather": "The Godfather",
    "Avatar": "Avatar",
}

# Stub library SONAMEs needed for the game binary to load
STUB_SONAMES = [
    "liballegro.so.5.2",
    "liballegro_primitives.so.5.2",
    "liballegro_audio.so.5.2",
    "liballegro_acodec.so.5.2",
    "liballegro_image.so.5.2",
    "liballegro_ttf.so.5.2",
    "liballegro_font.so.5.2",
    "liballegro_memfile.so.5.2",
    "libavformat.so.58",
    "libavcodec.so.58",
    "libavutil.so.56",
    "libopencv_core.so.405",
    "libopencv_imgproc.so.405",
    "libopencv_objdetect.so.405",
    "libopencv_videoio.so.405",
    "libopencv_wechat_qrcode.so.405",
]

# Bind mounts for chroot (order matters - unmount in reverse)
BIND_MOUNTS = [
    "/proc",
    "/sys",
    "/dev",
    "/dev/pts",
    "/dev/shm",
]

# Pipeline phase names
PHASES = [
    "Extract",
    "Mount",
    "Chroot",
    "Dongle",
    "Compile",
    "Decrypt",
    "Copy",
    "Cleanup",
]

# Mod pipeline phase names
MOD_PHASES = [
    "Scan",
    "Extract",
    "Mount",
    "Chroot",
    "Dongle",
    "Compile",
    "Encrypt",
    "Convert",
    "Build ISO",
    "Cleanup",
]

# Standalone pipeline phase names (no dongle/chroot/compile)
STANDALONE_PHASES = [
    "Extract",
    "Mount",
    "Decrypt",
    "Cleanup",
]

STANDALONE_MOD_PHASES = [
    "Scan",
    "Extract",
    "Prepare",
    "Encrypt",
    "Convert",
    "Build ISO",
    "Cleanup",
]

# Direct SSD pipeline phase names (no ISO extract/rebuild)
DIRECT_SSD_PHASES = [
    "Mount",
    "Decrypt",
    "Cleanup",
]

DIRECT_SSD_MOD_PHASES = [
    "Scan",
    "Mount",
    "Encrypt",
    "Cleanup",
]

RESTORE_TO_SSD_PHASES = [
    "Extract",
    "Partition",
    "Restore",
    "Cleanup",
]

# Partition number containing game data (1-indexed for wsl --mount)
GAME_PARTITION_NUMBER = 3

# Prerequisite names shown in the GUI (platform-aware)
if sys.platform == "win32":
    PREREQ_NAMES = ["WSL2", "partclone", "xorriso", "debugfs", "pigz", "ffmpeg"]
elif sys.platform == "darwin":
    PREREQ_NAMES = ["Docker", "partclone", "xorriso", "debugfs"]
else:
    PREREQ_NAMES = ["System", "partclone", "xorriso", "debugfs", "pigz", "ffmpeg"]
