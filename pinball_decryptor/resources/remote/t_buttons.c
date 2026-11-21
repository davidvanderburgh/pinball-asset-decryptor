/* PAD-1467: the shim's logic under qemu. The real ioctl fails here (no SPI device), so this calls the part that
 * handles the word directly through a second entry, with the files in the current folder. */
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef unsigned char u8;
int shim_ioctl(int fd, unsigned long req, void *arg);
/* padbtn.c is compiled into this program, so its static worker is reached through this small door */
void test_word(u8 *rx);

static unsigned now_cs(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned)t.tv_sec * 100u + (unsigned)(t.tv_nsec / 10000000L);
}

static void ctl(const char *fmt, unsigned long long mask, unsigned until, int nb, int nv)
{
    FILE *f = fopen("./ctl", "w");
    fprintf(f, fmt, mask, until, nb, nv);
    fclose(f);
    usleep(40000);                       /* the shim re-reads at most every 20 ms */
}

static int fails;
#define CHECK(what, cond) do { if (!(cond)) { fails++; printf("FAIL %s\n", what); } else printf("ok   %s\n", what); } while (0)

int main(void)
{
    u8 w[8];
    /* a transfer that is not the cabinet word is passed through: here it fails, as it would without the shim */
    CHECK("other ioctl passes through and fails as the real one", shim_ioctl(-1, 0x5401, 0) == -1);

    memset(w, 0xff, 8); test_word(w);
    CHECK("nothing asked: word untouched", w[1] == 0xff);
    {
        char line[64] = "";
        FILE *f = fopen("./state", "r");
        if (f) { if (!fgets(line, sizeof line, f)) line[0] = 0; fclose(f); }
        CHECK("the state file says it is alive and what the real word is", strstr(line, " ffffffffffffffff\n") != NULL);
    }

    /* press bit 8 for 0.5 s, needing bit 20 to read 0 (door open) */
    ctl("%llx %u %d %d\n", 1ULL << 8, now_cs() + 50, 20, 0);
    memset(w, 0xff, 8); test_word(w);
    CHECK("door closed (bit 20 reads 1): no press", w[1] == 0xff);
    memset(w, 0xff, 8); w[2] &= ~(1 << 4); test_word(w);
    CHECK("door open (bit 20 reads 0): bit 8 pressed", w[1] == 0xfe && w[2] == (u8)~(1 << 4));
    usleep(600000);
    memset(w, 0xff, 8); w[2] &= ~(1 << 4); test_word(w);
    CHECK("after the deadline: released", w[1] == 0xff);

    ctl("%llx %u %d %d\n", 1ULL << 9, now_cs() + 5000, 20, 0);
    memset(w, 0xff, 8); w[2] &= ~(1 << 4); test_word(w);
    CHECK("a deadline further ahead than 3 s is refused", w[1] == 0xff);

    ctl("%llx %u %d %d\n", (1ULL << 9) | (1ULL << 11), now_cs() + 50, -1, 0);
    memset(w, 0xff, 8); test_word(w);
    CHECK("no door condition asked (-1): two bits pressed", w[1] == (u8)~((1 << 1) | (1 << 3)));

    { FILE *f = fopen("./ctl", "w"); fputs("garbage here\n", f); fclose(f); usleep(40000); }
    memset(w, 0xff, 8); test_word(w);
    CHECK("a control line that is not one: no press", w[1] == 0xff);
    unlink("./ctl"); usleep(40000);
    memset(w, 0xff, 8); test_word(w);
    CHECK("no control file: no press", w[1] == 0xff);
    printf(fails ? "FAILED %d\n" : "ALL OK\n", fails);
    return fails != 0;
}
