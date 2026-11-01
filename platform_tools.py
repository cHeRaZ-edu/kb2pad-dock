"""
Utilidades que cambian segun el sistema: correr adb, leer la rotacion del celular
y mover/redimensionar la ventana de scrcpy.

Linux: xdotool (X11 / XWayland).   Windows: WinAPI con ctypes.
"""
import os
import re
import shutil
import subprocess

IS_WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0     # CREATE_NO_WINDOW: sin ventana de consola


def run(cmd, timeout=5):
    """subprocess.run sin abrir consola en Windows. Regresa stdout+stderr ('' si fallo)."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             creationflags=NO_WINDOW)
        return (res.stdout or "") + (res.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def spawn(cmd):
    """Lanza un proceso y no espera (sin consola en Windows)."""
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        return True
    except OSError:
        return False


def adb_cmd(adb, serial, *args):
    return [adb, *(["-s", serial] if serial else []), *args]


def device_rotation(adb, serial):
    """0/1/2/3 (1 y 3 = horizontal en un cel vertical). None si no se pudo leer."""
    out = run(adb_cmd(adb, serial, "shell", "dumpsys", "input"), timeout=4)
    m = re.search(r"SurfaceOrientation:\s*(\d)", out)
    if m:
        return int(m.group(1))
    out = run(adb_cmd(adb, serial, "shell", "dumpsys", "window", "displays"), timeout=4)
    m = re.search(r"mCurrentRotation=(?:ROTATION_)?(\d+)", out)
    if m:
        v = int(m.group(1))
        return v // 90 if v >= 90 else v
    return None


_version_cache = {}


def scrcpy_version(scrcpy):
    """(mayor, menor) de scrcpy, o None si no se pudo leer."""
    if scrcpy not in _version_cache:
        m = re.search(r"scrcpy\s+v?(\d+)\.(\d+)", run([scrcpy, "--version"], timeout=6))
        _version_cache[scrcpy] = (int(m.group(1)), int(m.group(2))) if m else None
    return _version_cache[scrcpy]


_PKG = re.compile(r"^[A-Za-z][\w]*(\.[\w]+)+$")


def parse_app_list(text):
    """Salida de 'scrcpy --list-apps' -> [(nombre, paquete, es_del_sistema)]."""
    apps, pending = [], None
    started = False
    for raw in text.splitlines():
        if "List of apps" in raw:
            started = True
            continue
        if not started:
            continue
        m = re.match(r"^ ([*-]) (.+)$", raw)
        if m:
            system, rest = m.group(1) == "*", m.group(2).rstrip()
            parts = rest.rsplit(None, 1)
            if len(parts) == 2 and _PKG.match(parts[1]):
                apps.append((parts[0].strip(), parts[1], system))
                pending = None
            else:
                pending = (rest.strip(), system)      # nombre largo: el paquete va en la linea siguiente
            continue
        token = raw.strip()
        if pending and _PKG.match(token):
            apps.append((pending[0], token, pending[1]))
            pending = None
        elif token and not raw.startswith(" "):
            break                                     # termino la lista
    return apps


def parse_pm_packages(text):
    """Salida de 'pm list packages' -> [(paquete, paquete, False)]."""
    pkgs = re.findall(r"^package:(\S+)", text, re.M)
    return [(p, p, False) for p in sorted(set(pkgs))]


def phone_ip(adb, serial):
    """IP del celular en el Wi-Fi (para adb tcpip), o None."""
    out = run(adb_cmd(adb, serial, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"), timeout=5)
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    if m:
        return m.group(1)
    out = run(adb_cmd(adb, serial, "shell", "ip", "route"), timeout=5)
    for line in out.splitlines():
        if "wlan" in line:
            m = re.search(r"src (\d+\.\d+\.\d+\.\d+)", line)
            if m:
                return m.group(1)
    return None


def adb_connect(adb, addr):
    """adb connect ip:puerto -> (ok, salida)."""
    out = run([adb, "connect", addr], timeout=8).strip()
    low = out.lower()
    return ("connected to" in low and "cannot" not in low and "failed" not in low), out


def adb_usb_serial(adb, preferred=""):
    """Serial de un celular conectado por cable (no ip:puerto ni emulador)."""
    if preferred and ":" not in preferred:
        return preferred
    for ln in run([adb, "devices"], timeout=6).splitlines():
        if ln.endswith("\tdevice"):
            ser = ln.split("\t")[0]
            if ":" not in ser and not ser.startswith("emulator-") and "._adb-tls" not in ser:
                return ser
    return None


# ================================================================ ventanas
def window_tool_missing():
    """Texto de lo que falta para mover ventanas, o None si se puede."""
    if IS_WINDOWS:
        return None
    if not shutil.which("xdotool"):
        return "instala xdotool: sudo pacman -S xdotool"
    return None


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes as W

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _ENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    _u32.EnumWindows.argtypes = (_ENUMPROC, W.LPARAM)
    _u32.GetWindowThreadProcessId.argtypes = (W.HWND, ctypes.POINTER(W.DWORD))
    _u32.GetWindowThreadProcessId.restype = W.DWORD
    _u32.IsWindowVisible.argtypes = (W.HWND,)
    _u32.GetWindowRect.argtypes = (W.HWND, ctypes.POINTER(W.RECT))
    _u32.IsWindow.argtypes = (W.HWND,)
    _u32.SetWindowPos.argtypes = (W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_uint)
    _u32.GetForegroundWindow.restype = W.HWND
    _u32.SetForegroundWindow.argtypes = (W.HWND,)
    _u32.BringWindowToTop.argtypes = (W.HWND,)
    _u32.AttachThreadInput.argtypes = (W.DWORD, W.DWORD, W.BOOL)
    _u32.IsIconic.argtypes = (W.HWND,)
    _u32.ShowWindow.argtypes = (W.HWND, ctypes.c_int)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010

    class _DpiUnaware:
        """Coordenadas logicas (como scrcpy/SDL y Qt) aunque haya escalado de Windows."""

        def __enter__(self):
            self.prev = None
            try:
                fn = _u32.SetThreadDpiAwarenessContext
                fn.restype = ctypes.c_void_p
                fn.argtypes = (ctypes.c_void_p,)
                self.prev = fn(ctypes.c_void_p(-1))
            except AttributeError:
                pass
            return self

        def __exit__(self, *exc):
            if self.prev:
                _u32.SetThreadDpiAwarenessContext(ctypes.c_void_p(self.prev))

    def _rect(hwnd):
        r = W.RECT()
        if not _u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def find_window(pid):
        found = []

        def cb(hwnd, _lparam):
            p = W.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid and _u32.IsWindowVisible(hwnd):
                g = _rect(hwnd)
                if g and g[2] > 100 and g[3] > 100:
                    found.append((g[2] * g[3], hwnd))
            return True

        with _DpiUnaware():
            _u32.EnumWindows(_ENUMPROC(cb), 0)
        return max(found)[1] if found else None

    def window_geometry(wid):
        if not wid or not _u32.IsWindow(wid):
            return None
        with _DpiUnaware():
            return _rect(wid)

    def set_window_geometry(wid, x, y, w, h):
        with _DpiUnaware():
            _u32.SetWindowPos(wid, None, int(x), int(y), int(w), int(h), SWP_NOZORDER | SWP_NOACTIVATE)

    def focus_window(wid):
        """Trae la ventana al frente con el foco del teclado (Windows no deja si no 'le toca':
        se pega al hilo de la ventana que tiene el foco mientras tanto)."""
        if not wid or not _u32.IsWindow(wid):
            return False
        fg = _u32.GetForegroundWindow()
        me = _k32.GetCurrentThreadId()
        other = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(other and other != me and _u32.AttachThreadInput(other, me, True))
        try:
            if _u32.IsIconic(wid):
                _u32.ShowWindow(wid, 9)          # SW_RESTORE
            _u32.BringWindowToTop(wid)
            return bool(_u32.SetForegroundWindow(wid))
        finally:
            if attached:
                _u32.AttachThreadInput(other, me, False)

else:
    def _xdotool(*args):
        return run(["xdotool", *args], timeout=2)

    def window_geometry(wid):
        out = _xdotool("getwindowgeometry", "--shell", str(wid))
        vals = dict(re.findall(r"^(\w+)=(-?\d+)$", out, re.M))
        try:
            return int(vals["X"]), int(vals["Y"]), int(vals["WIDTH"]), int(vals["HEIGHT"])
        except KeyError:
            return None

    def find_window(pid):
        best = None
        for line in _xdotool("search", "--pid", str(pid)).split():
            if not line.isdigit():
                continue
            g = window_geometry(line)
            if g and g[2] > 100 and g[3] > 100:
                if best is None or g[2] * g[3] > best[1]:
                    best = (line, g[2] * g[3])
        return best[0] if best else None

    def set_window_geometry(wid, x, y, w, h):
        _xdotool("windowsize", str(wid), str(int(w)), str(int(h)))
        _xdotool("windowmove", str(wid), str(int(x)), str(int(y)))

    def focus_window(wid):
        if not wid or not shutil.which("xdotool"):
            return False
        _xdotool("windowactivate", str(wid))
        return True
