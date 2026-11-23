/* padicon: Explorer's icon for a card image, per file (PAD-1522).
 *
 * A card image stored COMPACT (a sparse file, core/sparse_card.py) is the
 * same .raw as a full-size one, so Explorer drew both alike.  This is a shell
 * icon handler: Explorer asks it for each card image's icon, and it answers
 * with one of the two .ico files that sit beside this DLL:
 *
 *     card_image.ico          a card that takes its whole size on disk
 *     card_image_compact.ico  a card that takes less (it has holes)
 *
 * "Compact" is read from the file's directory entry only (its sparse flag,
 * its size and its size on disk): the file itself is never opened, so asking
 * costs nothing on a 62 GB card and never touches a card another program
 * holds.  The rule is the app's own (sparse_card.takes_less): the sparse
 * flag is set AND at least 1 MiB of the file has no disk space behind it.
 *
 * Explorer loads this DLL into its own process, so it does as little as it
 * can: no allocation but the one small object, no registry, no
 * threads, nothing kept open.  Built by tools/padicon/build.py; the built
 * DLL is committed (pinball_decryptor/shell/padicon64.dll).
 *
 * The app registers it for its user (webui/shell_icon.py) from a COPY under
 * %LOCALAPPDATA%, never from the install folder: Explorer keeps a loaded
 * handler open, and an open file in the install folder would stop an update.
 */
#define WIN32_LEAN_AND_MEAN
#define CINTERFACE
#define COBJMACROS
#include <stddef.h>
#include <windows.h>
#include <objbase.h>
#include <shlobj.h>

/* IExtractIconW, spelled out: the C form in some toolkits' shlobj.h leaves
 * the three IUnknown slots out of its table. */
typedef struct PadExtract PadExtract;
typedef struct {
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(PadExtract *, REFIID, void **);
    ULONG (STDMETHODCALLTYPE *AddRef)(PadExtract *);
    ULONG (STDMETHODCALLTYPE *Release)(PadExtract *);
    HRESULT (STDMETHODCALLTYPE *GetIconLocation)(PadExtract *, UINT, LPWSTR,
                                                 UINT, int *, UINT *);
    HRESULT (STDMETHODCALLTYPE *Extract)(PadExtract *, LPCWSTR, UINT, HICON *,
                                         HICON *, UINT);
} PadExtractVtbl;
struct PadExtract { const PadExtractVtbl *lpVtbl; };
/* {000214FA-0000-0000-C000-000000000046} */
static const GUID IID_PadExtractIconW =
    {0x000214fa, 0, 0, {0xc0, 0, 0, 0, 0, 0, 0, 0x46}};

/* {6E1B5C0A-52D4-4F0B-9C55-1A1522CA4D01}: webui/shell_icon.py CLSID and the
 * uninstaller name the same one */
static const GUID CLSID_PadCardIcon =
    {0x6e1b5c0a, 0x52d4, 0x4f0b, {0x9c, 0x55, 0x1a, 0x15, 0x22, 0xca, 0x4d, 0x01}};

#define PATH_CCH 1024
#define MIN_HOLE (1024u * 1024u)

static HINSTANCE g_inst;
static LONG g_objects;
static LONG g_locks;

typedef struct {
    IPersistFile persist;           /* must stay first: the object's identity */
    PadExtract extract;
    LONG refs;
    WCHAR path[PATH_CCH];
} PadIcon;

static int guid_eq(const GUID *a, const GUID *b)
{
    const unsigned char *x = (const unsigned char *)a;
    const unsigned char *y = (const unsigned char *)b;
    int i;
    for (i = 0; i < (int)sizeof(GUID); i++)
        if (x[i] != y[i])
            return 0;
    return 1;
}

/* 1 when the file takes at least MIN_HOLE less disk than its size and is
 * flagged sparse; 0 otherwise and on every error. */
static int takes_less(const WCHAR *path)
{
    WIN32_FILE_ATTRIBUTE_DATA fa;
    ULONGLONG size, alloc;
    DWORD lo, hi = 0;

    if (!path[0])
        return 0;
    if (!GetFileAttributesExW(path, GetFileExInfoStandard, &fa))
        return 0;
    if (fa.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
        return 0;
    if (!(fa.dwFileAttributes & FILE_ATTRIBUTE_SPARSE_FILE))
        return 0;
    size = ((ULONGLONG)fa.nFileSizeHigh << 32) | fa.nFileSizeLow;
    SetLastError(NO_ERROR);
    lo = GetCompressedFileSizeW(path, &hi);
    if (lo == INVALID_FILE_SIZE && GetLastError() != NO_ERROR)
        return 0;
    alloc = ((ULONGLONG)hi << 32) | lo;
    return alloc + MIN_HOLE <= size;
}

/* ------------------------------------------------------------ the object */

static HRESULT obj_qi(PadIcon *o, REFIID riid, void **out)
{
    if (!out)
        return E_POINTER;
    *out = NULL;
    if (guid_eq(riid, &IID_IUnknown) || guid_eq(riid, &IID_IPersist)
            || guid_eq(riid, &IID_IPersistFile))
        *out = &o->persist;
    else if (guid_eq(riid, &IID_PadExtractIconW))
        *out = &o->extract;
    else
        return E_NOINTERFACE;
    InterlockedIncrement(&o->refs);
    return S_OK;
}

static ULONG obj_release(PadIcon *o)
{
    LONG n = InterlockedDecrement(&o->refs);
    if (n == 0) {
        HeapFree(GetProcessHeap(), 0, o);
        InterlockedDecrement(&g_objects);
    }
    return (ULONG)n;
}

#define FROM_EXTRACT(p) \
    ((PadIcon *)((char *)(p) - offsetof(PadIcon, extract)))

/* IPersistFile */
static HRESULT STDMETHODCALLTYPE pf_qi(IPersistFile *t, REFIID r, void **o)
{ return obj_qi((PadIcon *)t, r, o); }
static ULONG STDMETHODCALLTYPE pf_addref(IPersistFile *t)
{ return (ULONG)InterlockedIncrement(&((PadIcon *)t)->refs); }
static ULONG STDMETHODCALLTYPE pf_release(IPersistFile *t)
{ return obj_release((PadIcon *)t); }
static HRESULT STDMETHODCALLTYPE pf_classid(IPersistFile *t, CLSID *id)
{
    (void)t;
    if (!id)
        return E_POINTER;
    *id = CLSID_PadCardIcon;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE pf_isdirty(IPersistFile *t)
{ (void)t; return S_FALSE; }
static HRESULT STDMETHODCALLTYPE pf_load(IPersistFile *t, LPCOLESTR name,
                                         DWORD mode)
{
    PadIcon *o = (PadIcon *)t;
    int n;
    (void)mode;
    o->path[0] = 0;
    if (!name)
        return E_POINTER;
    n = lstrlenW(name);
    if (n > 0 && n < PATH_CCH)          /* a longer path: the plain icon */
        lstrcpynW(o->path, name, PATH_CCH);
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE pf_save(IPersistFile *t, LPCOLESTR n, BOOL r)
{ (void)t; (void)n; (void)r; return E_NOTIMPL; }
static HRESULT STDMETHODCALLTYPE pf_savedone(IPersistFile *t, LPCOLESTR n)
{ (void)t; (void)n; return E_NOTIMPL; }
static HRESULT STDMETHODCALLTYPE pf_curfile(IPersistFile *t, LPOLESTR *n)
{
    (void)t;
    if (n)
        *n = NULL;
    return E_NOTIMPL;
}

static IPersistFileVtbl g_pf_vtbl = {
    pf_qi, pf_addref, pf_release, pf_classid, pf_isdirty, pf_load, pf_save,
    pf_savedone, pf_curfile
};

/* IExtractIconW */
static HRESULT STDMETHODCALLTYPE ex_qi(PadExtract *t, REFIID r, void **o)
{ return obj_qi(FROM_EXTRACT(t), r, o); }
static ULONG STDMETHODCALLTYPE ex_addref(PadExtract *t)
{ return (ULONG)InterlockedIncrement(&FROM_EXTRACT(t)->refs); }
static ULONG STDMETHODCALLTYPE ex_release(PadExtract *t)
{ return obj_release(FROM_EXTRACT(t)); }

static const WCHAR ICON_PLAIN[] = L"card_image.ico";
static const WCHAR ICON_COMPACT[] = L"card_image_compact.ico";

static HRESULT STDMETHODCALLTYPE ex_location(PadExtract *t, UINT flags,
                                             LPWSTR file, UINT cch,
                                             int *index, UINT *out_flags)
{
    PadIcon *o = FROM_EXTRACT(t);
    WCHAR dir[MAX_PATH];
    const WCHAR *leaf;
    DWORD n;
    int i, cut = -1;
    (void)flags;

    if (!file || !index || !out_flags || cch == 0)
        return E_POINTER;
    n = GetModuleFileNameW(g_inst, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH)
        return E_FAIL;
    for (i = 0; i < (int)n; i++)
        if (dir[i] == L'\\' || dir[i] == L'/')
            cut = i;
    if (cut < 0)
        return E_FAIL;
    dir[cut + 1] = 0;
    leaf = takes_less(o->path) ? ICON_COMPACT : ICON_PLAIN;
    if ((UINT)(lstrlenW(dir) + lstrlenW(leaf) + 1) > cch)
        return E_FAIL;
    lstrcpyW(file, dir);
    lstrcatW(file, leaf);
    *index = 0;
    /* each file is asked for itself: two .raw files differ */
    *out_flags = GIL_PERINSTANCE;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE ex_extract(PadExtract *t, LPCWSTR file,
                                            UINT index, HICON *large,
                                            HICON *small, UINT size)
{
    (void)t; (void)file; (void)index; (void)large; (void)small; (void)size;
    return S_FALSE;                     /* Explorer reads the .ico itself */
}

static const PadExtractVtbl g_ex_vtbl = {
    ex_qi, ex_addref, ex_release, ex_location, ex_extract
};

/* ------------------------------------------------------------ the factory */

static HRESULT STDMETHODCALLTYPE cf_qi(IClassFactory *t, REFIID r, void **o)
{
    if (!o)
        return E_POINTER;
    if (guid_eq(r, &IID_IUnknown) || guid_eq(r, &IID_IClassFactory)) {
        *o = t;
        return S_OK;
    }
    *o = NULL;
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE cf_addref(IClassFactory *t)
{ (void)t; return 2; }
static ULONG STDMETHODCALLTYPE cf_release(IClassFactory *t)
{ (void)t; return 1; }
static HRESULT STDMETHODCALLTYPE cf_create(IClassFactory *t, IUnknown *outer,
                                           REFIID riid, void **out)
{
    PadIcon *o;
    HRESULT hr;
    (void)t;
    if (!out)
        return E_POINTER;
    *out = NULL;
    if (outer)
        return CLASS_E_NOAGGREGATION;
    o = (PadIcon *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(*o));
    if (!o)
        return E_OUTOFMEMORY;
    o->persist.lpVtbl = &g_pf_vtbl;
    o->extract.lpVtbl = &g_ex_vtbl;
    o->refs = 1;
    InterlockedIncrement(&g_objects);
    hr = obj_qi(o, riid, out);
    obj_release(o);
    return hr;
}
static HRESULT STDMETHODCALLTYPE cf_lock(IClassFactory *t, BOOL lock)
{
    (void)t;
    if (lock)
        InterlockedIncrement(&g_locks);
    else
        InterlockedDecrement(&g_locks);
    return S_OK;
}

static IClassFactoryVtbl g_cf_vtbl = {
    cf_qi, cf_addref, cf_release, cf_create, cf_lock
};
static IClassFactory g_factory = { &g_cf_vtbl };

/* ------------------------------------------------------------ the exports */

HRESULT WINAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void **out)
{
    if (!out)
        return E_POINTER;
    *out = NULL;
    if (!guid_eq(clsid, &CLSID_PadCardIcon))
        return CLASS_E_CLASSNOTAVAILABLE;
    return cf_qi(&g_factory, riid, out);
}

HRESULT WINAPI DllCanUnloadNow(void)
{
    return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE;
}

/* The test hook (tests/test_pad1522_*.py): the rule alone, no COM. */
int WINAPI PadIconTakesLess(const WCHAR *path)
{
    return path ? takes_less(path) : 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, void *reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        g_inst = inst;
        DisableThreadLibraryCalls(inst);
    }
    return TRUE;
}
