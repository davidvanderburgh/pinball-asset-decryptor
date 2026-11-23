/* padmenu: "Write to a card with PAD" and "Compact with PAD" on the Windows 11
 * short right-click menu (PAD-1523).
 *
 * Windows 11's first right-click menu lists no verb from the registry but a
 * file type's default one: the app's verbs (webui/open_image.py) live only
 * under "Show more options" there.  What it does list are IExplorerCommand
 * handlers that a package declares (desktop4:FileExplorerContextMenus), so
 * this DLL is one, carried by the app's sparse package (tools/padmenu, the
 * package's manifest beside this file; webui/shell_menu.py registers it).
 *
 * It is a BRIDGE to the registry verbs, not a second copy of them: each of
 * its two classes names one verb, and reads that verb's label, icon and
 * command from SystemFileAssociations\<ext>\shell\<verb>, exactly what the
 * classic menu runs.  So the app keeps one place that says what an entry
 * says and does, an entry whose verb the app no longer registers (an app
 * uninstalled, a package left behind) is simply not shown, and nothing in
 * here knows where the app is installed.
 *
 * Compact is shown only for a card that takes its whole size on disk: one
 * already stored compact has nothing to gain (the rule is padicon.c's and the
 * app's sparse_card.takes_less, read from the directory entry only).
 *
 * Windows runs a packaged handler in a COM surrogate that carries the
 * package's identity; the verb's command is started outside it
 * (PROCESS_CREATION_DESKTOP_APP_BREAKAWAY_OVERRIDE), so the app runs as it
 * does from the classic menu, not as part of the package.
 *
 * Built by tools/padmenu/build.py; the built DLL is committed
 * (pinball_decryptor/shell/padmenu64.dll).
 */
#define WIN32_LEAN_AND_MEAN
#define CINTERFACE
#define COBJMACROS
#include <stddef.h>
#include <windows.h>
#include <objbase.h>
#include <shlobj.h>
#include <shobjidl.h>

/* {6E1B5C0A-52D4-4F0B-9C55-1A1523CA4D02} Write, ...D03 Compact: the
 * package manifest (tools/padmenu/AppxManifest.xml) names the same two */
static const GUID CLSID_PadWrite =
    {0x6e1b5c0a, 0x52d4, 0x4f0b, {0x9c, 0x55, 0x1a, 0x15, 0x23, 0xca, 0x4d, 0x02}};
static const GUID CLSID_PadCompact =
    {0x6e1b5c0a, 0x52d4, 0x4f0b, {0x9c, 0x55, 0x1a, 0x15, 0x23, 0xca, 0x4d, 0x03}};

static const WCHAR VERB_WRITE[] = L"PinballAssetDecryptor.Write";
static const WCHAR VERB_COMPACT[] = L"PinballAssetDecryptor.Compact";

#define PATH_CCH 1024
#define CMD_CCH 4096
#define MIN_HOLE (1024u * 1024u)

static LONG g_objects;
static LONG g_locks;

typedef struct {
    IExplorerCommand cmd;           /* must stay first: the object's identity */
    LONG refs;
    int compact;                    /* 1: the Compact class, 0: Write */
} PadCommand;

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

/* padicon.c's rule: flagged sparse AND at least MIN_HOLE less on disk than
 * its size.  0 on every error. */
static int takes_less(const WCHAR *path)
{
    WIN32_FILE_ATTRIBUTE_DATA fa;
    ULONGLONG size, alloc;
    DWORD lo, hi = 0;

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

static const WCHAR *verb_of(const PadCommand *o)
{
    return o->compact ? VERB_COMPACT : VERB_WRITE;
}

/* The extension of *path* (".raw"), or "" */
static const WCHAR *ext_of(const WCHAR *path)
{
    const WCHAR *dot = NULL, *p;
    for (p = path; *p; p++) {
        if (*p == L'.')
            dot = p;
        else if (*p == L'\\' || *p == L'/')
            dot = NULL;
    }
    return dot ? dot : L"";
}

/* Read the verb's value *name* ("" = its label, L"Icon") or, with *command*,
 * its command, for files of extension *ext*.  1 when there is one. */
static int verb_value(const PadCommand *o, const WCHAR *ext, int command,
                      const WCHAR *name, WCHAR *out, DWORD cch)
{
    WCHAR key[256];
    DWORD bytes = cch * sizeof(WCHAR);
    int n = wsprintfW(key, L"SystemFileAssociations\\%s\\shell\\%s%s", ext,
                      verb_of(o), command ? L"\\command" : L"");
    if (n <= 0 || lstrlenW(ext) > 16)
        return 0;
    out[0] = 0;
    if (RegGetValueW(HKEY_CLASSES_ROOT, key, name && name[0] ? name : NULL,
                     RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ, NULL, out, &bytes)
            != ERROR_SUCCESS)
        return 0;
    return out[0] != 0;
}

/* The file-system path of item *i* of *items*, into *out*; 1 when it has
 * one. */
static int item_path(IShellItemArray *items, DWORD i, WCHAR *out)
{
    IShellItem *item = NULL;
    LPWSTR name = NULL;
    int ok = 0;
    if (FAILED(IShellItemArray_GetItemAt(items, i, &item)) || !item)
        return 0;
    if (SUCCEEDED(IShellItem_GetDisplayName(item, SIGDN_FILESYSPATH, &name))
            && name) {
        if (lstrlenW(name) < PATH_CCH) {
            lstrcpyW(out, name);
            ok = 1;
        }
        CoTaskMemFree(name);
    }
    IShellItem_Release(item);
    return ok;
}

/* 1 when this entry applies to *path*: its verb is registered for the
 * file's extension, and (Compact) the card is not stored compact already */
static int applies(const PadCommand *o, const WCHAR *path)
{
    WCHAR buf[CMD_CCH];
    if (!verb_value(o, ext_of(path), 1, NULL, buf, CMD_CCH))
        return 0;
    if (o->compact && takes_less(path))
        return 0;
    return 1;
}

/* The first item's extension, for the label and icon; ".raw" without one */
static void first_ext(IShellItemArray *items, WCHAR *ext)
{
    WCHAR path[PATH_CCH];
    lstrcpyW(ext, L".raw");
    if (items && item_path(items, 0, path)) {
        const WCHAR *e = ext_of(path);
        if (e[0] && lstrlenW(e) < 16)
            lstrcpyW(ext, e);
    }
}

static HRESULT dup_string(const WCHAR *s, LPWSTR *out)
{
    size_t n = ((size_t)lstrlenW(s) + 1) * sizeof(WCHAR);
    *out = (LPWSTR)CoTaskMemAlloc(n);
    if (!*out)
        return E_OUTOFMEMORY;
    CopyMemory(*out, s, n);
    return S_OK;
}

/* The verb's command with every %1 (and %L) made *path*, into *out* */
static int fill_command(const WCHAR *tmpl, const WCHAR *path, WCHAR *out,
                        int cch)
{
    int n = 0, plen = lstrlenW(path);
    const WCHAR *t;
    for (t = tmpl; *t; t++) {
        if (t[0] == L'%' && (t[1] == L'1' || t[1] == L'L' || t[1] == L'l')) {
            if (n + plen >= cch)
                return 0;
            CopyMemory(out + n, path, plen * sizeof(WCHAR));
            n += plen;
            t++;
            continue;
        }
        if (n + 1 >= cch)
            return 0;
        out[n++] = *t;
    }
    out[n] = 0;
    return 1;
}

/* Start *cmdline* outside the package this DLL runs in, as the classic
 * menu would start it.  Falls back to a plain start where the breakaway is
 * refused. */
static int start(WCHAR *cmdline)
{
    STARTUPINFOEXW si;
    PROCESS_INFORMATION pi;
    SIZE_T size = 0;
    DWORD policy = PROCESS_CREATION_DESKTOP_APP_BREAKAWAY_OVERRIDE;
    char attrs[256];
    BOOL ok = FALSE;

    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.StartupInfo.cb = sizeof(si);
    InitializeProcThreadAttributeList(NULL, 1, 0, &size);
    if (size && size <= sizeof(attrs)) {
        si.lpAttributeList = (LPPROC_THREAD_ATTRIBUTE_LIST)attrs;
        if (InitializeProcThreadAttributeList(si.lpAttributeList, 1, 0, &size)
                && UpdateProcThreadAttribute(
                    si.lpAttributeList, 0,
                    PROC_THREAD_ATTRIBUTE_DESKTOP_APP_POLICY, &policy,
                    sizeof(policy), NULL, NULL)) {
            ok = CreateProcessW(NULL, cmdline, NULL, NULL, FALSE,
                                EXTENDED_STARTUPINFO_PRESENT, NULL, NULL,
                                &si.StartupInfo, &pi);
        }
        DeleteProcThreadAttributeList(si.lpAttributeList);
    }
    if (!ok) {
        si.StartupInfo.cb = sizeof(STARTUPINFOW);
        ok = CreateProcessW(NULL, cmdline, NULL, NULL, FALSE, 0, NULL, NULL,
                            &si.StartupInfo, &pi);
    }
    if (!ok)
        return 0;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 1;
}

/* ------------------------------------------------------- IExplorerCommand */

static HRESULT STDMETHODCALLTYPE ec_qi(IExplorerCommand *t, REFIID riid,
                                      void **out)
{
    if (!out)
        return E_POINTER;
    if (guid_eq(riid, &IID_IUnknown) || guid_eq(riid, &IID_IExplorerCommand)) {
        *out = t;
        IExplorerCommand_AddRef(t);
        return S_OK;
    }
    *out = NULL;
    return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE ec_addref(IExplorerCommand *t)
{
    return (ULONG)InterlockedIncrement(&((PadCommand *)t)->refs);
}

static ULONG STDMETHODCALLTYPE ec_release(IExplorerCommand *t)
{
    PadCommand *o = (PadCommand *)t;
    LONG n = InterlockedDecrement(&o->refs);
    if (n == 0) {
        HeapFree(GetProcessHeap(), 0, o);
        InterlockedDecrement(&g_objects);
    }
    return (ULONG)n;
}

static HRESULT STDMETHODCALLTYPE ec_title(IExplorerCommand *t,
                                          IShellItemArray *items, LPWSTR *out)
{
    PadCommand *o = (PadCommand *)t;
    WCHAR ext[16], buf[256];
    *out = NULL;
    first_ext(items, ext);
    if (!verb_value(o, ext, 0, NULL, buf, 256))
        lstrcpyW(buf, o->compact ? L"Compact with PAD"
                                 : L"Write to a card with PAD");
    return dup_string(buf, out);
}

static HRESULT STDMETHODCALLTYPE ec_icon(IExplorerCommand *t,
                                         IShellItemArray *items, LPWSTR *out)
{
    PadCommand *o = (PadCommand *)t;
    WCHAR ext[16], buf[PATH_CCH];
    *out = NULL;
    first_ext(items, ext);
    if (!verb_value(o, ext, 0, L"Icon", buf, PATH_CCH))
        return E_NOTIMPL;
    return dup_string(buf, out);
}

static HRESULT STDMETHODCALLTYPE ec_tip(IExplorerCommand *t,
                                        IShellItemArray *items, LPWSTR *out)
{
    (void)t; (void)items;
    *out = NULL;
    return E_NOTIMPL;
}

static HRESULT STDMETHODCALLTYPE ec_name(IExplorerCommand *t, GUID *out)
{
    *out = ((PadCommand *)t)->compact ? CLSID_PadCompact : CLSID_PadWrite;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE ec_state(IExplorerCommand *t,
                                          IShellItemArray *items, BOOL slow,
                                          EXPCMDSTATE *out)
{
    PadCommand *o = (PadCommand *)t;
    WCHAR path[PATH_CCH];
    DWORD n = 0, i;
    (void)slow;                      /* a directory entry is all it reads */
    *out = ECS_HIDDEN;
    if (!items) {
        *out = ECS_ENABLED;
        return S_OK;
    }
    if (FAILED(IShellItemArray_GetCount(items, &n)))
        return S_OK;
    /* shown when it applies to any card picked, and run on those */
    for (i = 0; i < n; i++)
        if (item_path(items, i, path) && applies(o, path)) {
            *out = ECS_ENABLED;
            break;
        }
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE ec_invoke(IExplorerCommand *t,
                                           IShellItemArray *items,
                                           IBindCtx *ctx)
{
    PadCommand *o = (PadCommand *)t;
    WCHAR path[PATH_CCH], tmpl[CMD_CCH], cmd[CMD_CCH + PATH_CCH];
    DWORD n = 0, i;
    (void)ctx;
    if (!items || FAILED(IShellItemArray_GetCount(items, &n)))
        return E_INVALIDARG;
    for (i = 0; i < n; i++) {
        if (!item_path(items, i, path) || !applies(o, path))
            continue;
        if (!verb_value(o, ext_of(path), 1, NULL, tmpl, CMD_CCH))
            continue;
        if (fill_command(tmpl, path, cmd, CMD_CCH + PATH_CCH))
            start(cmd);
    }
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE ec_flags(IExplorerCommand *t,
                                          EXPCMDFLAGS *out)
{
    (void)t;
    *out = ECF_DEFAULT;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE ec_subs(IExplorerCommand *t,
                                         IEnumExplorerCommand **out)
{
    (void)t;
    *out = NULL;
    return E_NOTIMPL;
}

static IExplorerCommandVtbl ec_vtbl = {
    ec_qi, ec_addref, ec_release, ec_title, ec_icon, ec_tip, ec_name,
    ec_state, ec_invoke, ec_flags, ec_subs,
};

/* ----------------------------------------------------------- the factory */

typedef struct {
    IClassFactory factory;
    int compact;
} PadFactory;

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
    PadCommand *o;
    HRESULT hr;
    if (!out)
        return E_POINTER;
    *out = NULL;
    if (outer)
        return CLASS_E_NOAGGREGATION;
    o = (PadCommand *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY,
                                sizeof(*o));
    if (!o)
        return E_OUTOFMEMORY;
    o->cmd.lpVtbl = &ec_vtbl;
    o->refs = 1;
    o->compact = ((PadFactory *)t)->compact;
    InterlockedIncrement(&g_objects);
    hr = ec_qi(&o->cmd, riid, out);
    ec_release(&o->cmd);
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

static IClassFactoryVtbl cf_vtbl = {
    cf_qi, cf_addref, cf_release, cf_create, cf_lock,
};
static PadFactory g_write = {{&cf_vtbl}, 0};
static PadFactory g_compact = {{&cf_vtbl}, 1};

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(inst);
    return TRUE;
}

HRESULT WINAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void **out)
{
    PadFactory *f;
    if (!out)
        return E_POINTER;
    *out = NULL;
    if (guid_eq(clsid, &CLSID_PadWrite))
        f = &g_write;
    else if (guid_eq(clsid, &CLSID_PadCompact))
        f = &g_compact;
    else
        return CLASS_E_CLASSNOTAVAILABLE;
    return cf_qi(&f->factory, riid, out);
}

HRESULT WINAPI DllCanUnloadNow(void)
{
    return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE;
}
