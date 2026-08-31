/* s1criu.c — criu ext-file plugin for the Spike 1 rig's CUSE devices (item 87).
 *
 * The pivoted Spike 1 guest holds ~8 open fds to CUSE character devices
 * (/dev/s1dmd, s1spi0, s1spi1, s1adc, s1amp, s1i2s, s1i2c0, s1gpio — bound
 * into the guest's /dev as dmd, spi0, …).  criu cannot dump an unknown chr
 * device: dump_chrdev() falls through to dump_unsupp_fd() → ext_dump_ops →
 * run_plugins(DUMP_EXT_FILE) — this plugin is that handler.
 *
 * Dump:    identify the device by st_rdev against the host's own /dev/s1*
 *          nodes (criu runs in the host namespace, where the CUSE server
 *          created them), and append "id rdev path flags" to s1cuse.map in
 *          the image directory.  Only fds whose rdev matches a live /dev/s1*
 *          node are claimed; anything else stays unsupported (-ENOTSUP), so
 *          criu's honest refusal is preserved for genuinely foreign fds.
 * Restore: reopen the recorded path with the recorded access mode and hand
 *          the fd back; criu dup2s it into the restored task.  A reopen is a
 *          fresh CUSE session, which is correct here: the s1hwshim models are
 *          stateless per-open (pacing clocks are global), and the guest's
 *          blocked reads/writes/ioctls resume via kernel syscall restart
 *          against the new fd.
 *
 * The CUSE server (s1hwshim) is NOT part of the checkpoint — a restore lands
 * in a freshly started rig whose devices already exist.  If they don't, the
 * reopen fails loudly and criu aborts the restore, which is the right answer.
 *
 * Build:  gcc -shared -fPIC -O2 -o s1criu.so s1criu.c -I<criu>/criu/include
 * Use:    criu dump/restore ... -L <dir containing s1criu.so>
 */
#include <errno.h>
#include <fcntl.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#include "criu-plugin.h"

/* criu exports this when built export-dynamic (it is, for the amdgpu/cuda
 * plugins); the weak reference keeps the plugin loadable against a criu that
 * doesn't, falling back to $S1CRIU_DIR. */
extern int criu_get_image_dir(void) __attribute__((weak));

#define MAPFILE "s1cuse.map"
#define MAXDEV 32

static struct {
	dev_t rdev;
	char path[64];
} devs[MAXDEV];
static int ndevs = -1;

/* emu_root.sh's bind_dev table: host CUSE node -> the guest's /dev name. */
static const char *const bind_pairs[][2] = {
	{ "/dev/s1dmd", "/dev/dmd" },   { "/dev/s1spi0", "/dev/spi0" },
	{ "/dev/s1spi1", "/dev/spi1" }, { "/dev/s1adc", "/dev/adc" },
	{ "/dev/s1amp", "/dev/amp" },   { "/dev/s1i2s", "/dev/i2s" },
	{ "/dev/s1i2c0", "/dev/i2c-0" }, { "/dev/s1gpio", "/dev/gpio" },
};

static const char *guest_name(const char *host)
{
	size_t i;

	for (i = 0; i < sizeof(bind_pairs) / sizeof(bind_pairs[0]); i++)
		if (!strcmp(bind_pairs[i][0], host))
			return bind_pairs[i][1];
	return host;
}

static void scan_devs(void)
{
	DIR *d;
	struct dirent *e;

	ndevs = 0;
	d = opendir("/dev");
	if (!d)
		return;
	while ((e = readdir(d)) && ndevs < MAXDEV) {
		char p[80];
		struct stat st;

		if (strncmp(e->d_name, "s1", 2))
			continue;
		snprintf(p, sizeof(p), "/dev/%s", e->d_name);
		if (stat(p, &st) || !S_ISCHR(st.st_mode))
			continue;
		devs[ndevs].rdev = st.st_rdev;
		snprintf(devs[ndevs].path, sizeof(devs[ndevs].path), "%s", p);
		ndevs++;
	}
	closedir(d);
}

static int map_dir_fd(void)
{
	const char *dir;

	if (criu_get_image_dir)
		return criu_get_image_dir();
	dir = getenv("S1CRIU_DIR");
	if (!dir)
		return -1;
	return open(dir, O_DIRECTORY | O_RDONLY);
}

static int s1_dump_file(int fd, int id)
{
	struct stat st;
	int i, dfd, mfd, flags;
	char line[160];
	ssize_t n;

	if (fstat(fd, &st) || !S_ISCHR(st.st_mode))
		return -ENOTSUP;
	if (ndevs < 0)
		scan_devs();
	for (i = 0; i < ndevs; i++)
		if (devs[i].rdev == st.st_rdev)
			break;
	if (i == ndevs)
		return -ENOTSUP;

	flags = fcntl(fd, F_GETFL);
	if (flags < 0)
		flags = O_RDWR;

	dfd = map_dir_fd();
	if (dfd < 0) {
		fprintf(stderr, "s1criu: no image dir for %s\n", MAPFILE);
		return -1;
	}
	mfd = openat(dfd, MAPFILE, O_WRONLY | O_CREAT | O_APPEND, 0644);
	if (!criu_get_image_dir)
		close(dfd);
	if (mfd < 0)
		return -1;
	n = snprintf(line, sizeof(line), "%d %llu %s %d\n", id,
		     (unsigned long long)st.st_rdev, devs[i].path, flags);
	if (write(mfd, line, n) != n) {
		close(mfd);
		return -1;
	}
	close(mfd);
	return 0;
}
CR_PLUGIN_REGISTER_HOOK(CR_PLUGIN_HOOK__DUMP_EXT_FILE, s1_dump_file)

static int s1_restore_file(int id)
{
	int dfd, want_id, flags, fd;
	FILE *f;
	char path[64];
	unsigned long long rdev;
	char line[160];

	dfd = map_dir_fd();
	if (dfd < 0)
		return -ENOTSUP;
	{
		int mfd = openat(dfd, MAPFILE, O_RDONLY);

		if (!criu_get_image_dir)
			close(dfd);
		if (mfd < 0)
			return -ENOTSUP;
		f = fdopen(mfd, "r");
		if (!f) {
			close(mfd);
			return -1;
		}
	}
	while (fgets(line, sizeof(line), f)) {
		if (sscanf(line, "%d %llu %63s %d", &want_id, &rdev, path, &flags) != 4)
			continue;
		if (want_id != id)
			continue;
		fclose(f);
		flags &= (O_ACCMODE | O_NONBLOCK | O_APPEND);
		/* The hook runs in the RESTORED task's rebuilt mount namespace,
		 * where the device is its guest bind name (/dev/dmd), not the
		 * host CUSE name (/dev/s1dmd) the dump recorded.  Try the
		 * guest name first, the host name second — whichever namespace
		 * this criu build runs the hook in, one of the two resolves. */
		fd = open(guest_name(path), flags);
		if (fd < 0)
			fd = open(path, flags);
		if (fd < 0) {
			fprintf(stderr, "s1criu: reopen %s (or %s): %s (is the rig up?)\n",
				guest_name(path), path, strerror(errno));
			return -1;
		}
		return fd;
	}
	fclose(f);
	return -ENOTSUP;
}
CR_PLUGIN_REGISTER_HOOK(CR_PLUGIN_HOOK__RESTORE_EXT_FILE, s1_restore_file)

static int s1_init(int stage)
{
	(void)stage;
	return 0;
}

static void s1_exit(int stage, int ret)
{
	(void)stage;
	(void)ret;
}

CR_PLUGIN_REGISTER("s1cuse", s1_init, s1_exit)
