/* pad_nosync.c - the guest's sync() made harmless under WSL2 (2026-09-17).
 *
 * THE WEDGE. The Godzilla game (Pro 1.15, Premium 1.16) imports sync@GLIBC_2.4 and its NVRAM
 * thread calls it after writing a new NVM generation (a changed adjustment default, a wiped
 * NVRAM, Guided Setup's Save & Exit, an operator-menu save). qemu-user passes the call straight
 * to the host kernel, where sync(2) is GLOBAL: it also flushes the WSLg virtiofs superblock,
 * waits on the Windows side (fuse_sync_fs -> request_wait_answer) and never returns. The thread
 * sits in D state, SIGKILL cannot finish it, alive.sh counts the dead guest for ever, and the
 * only cure is `wsl --shutdown`. On 2026-09-17 two such guests from one run blocked every
 * emulator run for over an hour (C:\tmp\pad_parallel\RIG_WEDGED_2026-09-17_0110.txt).
 *
 * THE FIX. Preloaded ahead of libc (the rootfs's /etc/ld.so.preload, so every guest process and
 * every worktree's rig gets it), this definition interposes on the game's sync@GLIBC_2.4
 * reference and does nothing. Nothing is lost that the rig relied on: a guest sync never reached
 * fuse2fs (FUSE forwards no global sync to a userspace filesystem), the rootfs is an ext4 the
 * kernel writes back on its own within seconds, and syncfs() - which the game also imports and
 * which flushes ONE filesystem - is left alone.
 *
 * -nostdlib, no dependencies, so any dynamically linked guest binary can load it.
 */
__attribute__((visibility("default")))
void sync(void)
{
}
