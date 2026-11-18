/* padunity.c - load PAD's managed mode runtime into a Spooky Unity (Mono)
 * game without touching the game's files (PAD-1387 proof of concept).
 *
 * LD_PRELOADed into main.x86_64.  A constructor starts one thread that waits
 * for the game's Mono (libmonobdwgc-2.0.so, dlopen'd by UnityPlayer) to have
 * a domain with Assembly-CSharp in it, attaches to that domain, opens
 * PadModes.dll and calls PadModes.Loader.Init().  Everything after that is
 * managed code (PadModes.cs).
 *
 *   PADUNITY_DLL   the assembly (default: PadModes.dll beside this .so, then
 *                  PADUNITY_DLL_DEFAULT)
 *   PADUNITY_LOG   log file (default /game/logs/padunity.log)
 *
 * Children the game forks (bash, its housekeeping) inherit LD_PRELOAD; the
 * constructor does nothing unless the program is a Unity player.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifndef PADUNITY_DLL_DEFAULT
#define PADUNITY_DLL_DEFAULT "/var/tmp/pad_spooky/padunity/PadModes.dll"
#endif

typedef void MonoDomain, MonoImage, MonoAssembly, MonoClass, MonoMethod,
    MonoObject, MonoThread, MonoString;

static MonoDomain *(*p_root_domain)(void);
static MonoImage *(*p_image_loaded)(const char *);
static void (*p_domain_foreach)(void (*)(MonoDomain *, void *), void *);
static MonoThread *(*p_thread_attach)(MonoDomain *);
static int (*p_domain_set)(MonoDomain *, int);
static MonoAssembly *(*p_assembly_open)(MonoDomain *, const char *);
static MonoImage *(*p_assembly_image)(MonoAssembly *);
static MonoClass *(*p_class_from_name)(MonoImage *, const char *, const char *);
static MonoMethod *(*p_method_from_name)(MonoClass *, const char *, int);
static MonoObject *(*p_runtime_invoke)(MonoMethod *, void *, void **, MonoObject **);
static MonoString *(*p_object_to_string)(MonoObject *, MonoObject **);
static char *(*p_string_to_utf8)(MonoString *);
static const char *(*p_domain_name)(MonoDomain *);

static char log_path[512] = "/game/logs/padunity.log";
static char so_dir[512];

static void plog(const char *fmt, ...)
{
    FILE *f = fopen(log_path, "a");
    if (!f) return;
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm; localtime_r(&ts.tv_sec, &tm);
    fprintf(f, "%02d:%02d:%02d.%03ld [native] ", tm.tm_hour, tm.tm_min,
            tm.tm_sec, ts.tv_nsec / 1000000);
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fputc('\n', f);
    fclose(f);
}

static char mono_path[512];
static int find_mono(struct dl_phdr_info *i, size_t n, void *d)
{
    (void)n; (void)d;
    if (i->dlpi_name && strstr(i->dlpi_name, "libmonobdwgc")) {
        snprintf(mono_path, sizeof mono_path, "%s", i->dlpi_name);
        return 1;
    }
    return 0;
}

#define SYM(var, name) if (!(*(void **)&var = dlsym(h, name))) { plog("no %s", name); return -1; }
static int bind_mono(void *h)
{
    SYM(p_root_domain, "mono_get_root_domain");
    SYM(p_image_loaded, "mono_image_loaded");
    SYM(p_domain_foreach, "mono_domain_foreach");
    SYM(p_thread_attach, "mono_thread_attach");
    SYM(p_domain_set, "mono_domain_set");
    SYM(p_assembly_open, "mono_domain_assembly_open");
    SYM(p_assembly_image, "mono_assembly_get_image");
    SYM(p_class_from_name, "mono_class_from_name");
    SYM(p_method_from_name, "mono_class_get_method_from_name");
    SYM(p_runtime_invoke, "mono_runtime_invoke");
    SYM(p_object_to_string, "mono_object_to_string");
    SYM(p_string_to_utf8, "mono_string_to_utf8");
    SYM(p_domain_name, "mono_domain_get_friendly_name");
    return 0;
}

/* Unity runs scripts in a child domain ("Unity Child Domain") on some
 * versions and in the root domain on others: take the last one created. */
static MonoDomain *last_domain;
static void each_domain(MonoDomain *d, void *u)
{
    (void)u;
    plog("domain %p \"%s\"", d, p_domain_name ? p_domain_name(d) : "?");
    last_domain = d;
}

static void *loader(void *arg)
{
    (void)arg;
    void *h = NULL;
    for (int t = 0; t < 1200 && !h; t++) {       /* up to 10 min */
        if (dl_iterate_phdr(find_mono, NULL))
            h = dlopen(mono_path, RTLD_NOW | RTLD_NOLOAD);
        if (!h) usleep(500000);
    }
    if (!h) { plog("Mono never loaded (IL2CPP build?)"); return NULL; }
    plog("Mono is %s", mono_path);
    if (bind_mono(h)) return NULL;
    for (;;) {                       /* the game's scripts are loaded */
        if (p_root_domain() && p_image_loaded("Assembly-CSharp")) break;
        usleep(200000);
    }
    usleep(500000);
    p_domain_foreach(each_domain, NULL);
    MonoDomain *dom = last_domain ? last_domain : p_root_domain();
    p_thread_attach(dom);
    p_domain_set(dom, 0);

    const char *dll = getenv("PADUNITY_DLL");
    char beside[600];
    if (!dll) {
        snprintf(beside, sizeof beside, "%s/PadModes.dll", so_dir);
        dll = access(beside, R_OK) == 0 ? beside : PADUNITY_DLL_DEFAULT;
    }
    MonoAssembly *a = p_assembly_open(dom, dll);
    if (!a) { plog("cannot open %s", dll); return NULL; }
    MonoClass *k = p_class_from_name(p_assembly_image(a), "PadModes", "Loader");
    MonoMethod *m = k ? p_method_from_name(k, "Init", 0) : NULL;
    if (!m) { plog("PadModes.Loader.Init not in %s", dll); return NULL; }
    plog("calling PadModes.Loader.Init from %s in domain %p", dll, dom);
    MonoObject *exc = NULL;
    p_runtime_invoke(m, NULL, NULL, &exc);
    if (exc) {
        MonoString *s = p_object_to_string(exc, NULL);
        plog("Init threw: %s", s ? p_string_to_utf8(s) : "?");
    }
    /* Stay attached (the managed side keeps its own threads); park. */
    for (;;) pause();
    return NULL;
}

__attribute__((constructor)) static void padunity_init(void)
{
    char exe[512] = {0};
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0) return;
    const char *base = strrchr(exe, '/'); base = base ? base + 1 : exe;
    if (!strstr(base, ".x86_64")) return;          /* not the Unity player */
    const char *l = getenv("PADUNITY_LOG");
    if (l && *l) snprintf(log_path, sizeof log_path, "%s", l);
    Dl_info di;
    if (dladdr((void *)padunity_init, &di) && di.dli_fname) {
        snprintf(so_dir, sizeof so_dir, "%s", di.dli_fname);
        char *s = strrchr(so_dir, '/'); if (s) *s = 0;
    }
    plog("preloaded into %s (pid %d)", exe, (int)getpid());
    pthread_t t;
    pthread_attr_t at; pthread_attr_init(&at);
    pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    pthread_create(&t, &at, loader, NULL);
}
