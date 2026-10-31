"""
kb2pad engine para Windows - teclado + mouse -> control Xbox 360 virtual.

- Control virtual: driver ViGEmBus via ViGEmClient.dll (incluida en la app).
- Teclado y mouse: hooks de bajo nivel (WH_KEYBOARD_LL / WH_MOUSE_LL). El teclado no se
  bloquea (igual que en Linux); el mouse se bloquea solo mientras es camara o radial.
- Movimiento del mouse: Raw Input (sin aceleracion de Windows); si Windows no lo entrega
  mientras el mouse esta capturado, usa el movimiento del hook como respaldo.

Lo lanza la GUI:  kb2pad.exe --engine --config <ruta> [--debug]
Comandos por stdin: reload | debug on | debug off | quit
"""
import argparse
import ctypes
import os
import queue
import sys
import threading
import time
import types
from ctypes import POINTER, WINFUNCTYPE, byref, c_int, c_long, c_short, c_ubyte, c_uint, c_ushort, c_void_p, sizeof
from ctypes import wintypes as W
from pathlib import Path

import config as C
from core import EngineConfig, Mapper, load_engine_config, log, summary
from keycodes import e, win_scan_to_code as scan_to_code

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = W.LPARAM
HOOKPROC = WINFUNCTYPE(LRESULT, c_int, W.WPARAM, W.LPARAM)
WNDPROC = WINFUNCTYPE(LRESULT, W.HWND, c_uint, W.WPARAM, W.LPARAM)

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_QUIT, WM_INPUT = 0x0012, 0x00FF
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_MOUSEMOVE = 0x200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x201, 0x202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x204, 0x205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x207, 0x208
WM_MOUSEWHEEL, WM_XBUTTONDOWN, WM_XBUTTONUP, WM_MOUSEHWHEEL = 0x20A, 0x20B, 0x20C, 0x20E
LLKHF_EXTENDED, LLKHF_INJECTED = 0x01, 0x10
LLMHF_INJECTED = 0x01
RIDEV_INPUTSINK, RID_INPUT, RIM_TYPEMOUSE, MOUSE_MOVE_ABSOLUTE = 0x100, 0x10000003, 0, 0x01


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", c_ushort), ("usUsage", c_ushort),
                ("dwFlags", W.DWORD), ("hwndTarget", W.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", W.DWORD), ("dwSize", W.DWORD),
                ("hDevice", W.HANDLE), ("wParam", W.WPARAM)]


class _RMBTNS(ctypes.Structure):
    _fields_ = [("usButtonFlags", c_ushort), ("usButtonData", c_ushort)]


class _RMUNION(ctypes.Union):
    _fields_ = [("ulButtons", W.ULONG), ("s", _RMBTNS)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", c_ushort), ("u", _RMUNION), ("ulRawButtons", W.ULONG),
                ("lLastX", c_long), ("lLastY", c_long), ("ulExtraInformation", W.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", c_uint), ("style", c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", c_int), ("cbWndExtra", c_int), ("hInstance", W.HINSTANCE),
                ("hIcon", W.HICON), ("hCursor", c_void_p), ("hbrBackground", W.HBRUSH),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR), ("hIconSm", W.HICON)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]


def _sig(fn, res, *args):
    fn.restype = res
    fn.argtypes = args
    return fn


_sig(user32.SetWindowsHookExW, W.HHOOK, c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
_sig(user32.CallNextHookEx, LRESULT, W.HHOOK, c_int, W.WPARAM, W.LPARAM)
_sig(user32.UnhookWindowsHookEx, W.BOOL, W.HHOOK)
_sig(user32.GetMessageW, W.BOOL, POINTER(W.MSG), W.HWND, c_uint, c_uint)
_sig(user32.TranslateMessage, W.BOOL, POINTER(W.MSG))
_sig(user32.DispatchMessageW, LRESULT, POINTER(W.MSG))
_sig(user32.PostThreadMessageW, W.BOOL, W.DWORD, c_uint, W.WPARAM, W.LPARAM)
_sig(user32.DefWindowProcW, LRESULT, W.HWND, c_uint, W.WPARAM, W.LPARAM)
_sig(user32.RegisterClassExW, W.ATOM, POINTER(WNDCLASSEXW))
_sig(user32.CreateWindowExW, W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, c_int, c_int,
     c_int, c_int, W.HWND, W.HMENU, W.HINSTANCE, c_void_p)
_sig(user32.DestroyWindow, W.BOOL, W.HWND)
_sig(user32.RegisterRawInputDevices, W.BOOL, POINTER(RAWINPUTDEVICE), c_uint, c_uint)
_sig(user32.GetRawInputData, c_uint, W.HANDLE, c_uint, c_void_p, POINTER(c_uint), c_uint)
_sig(user32.GetCursorPos, W.BOOL, POINTER(W.POINT))
_sig(user32.SetCursorPos, W.BOOL, c_int, c_int)
_sig(user32.MonitorFromPoint, W.HANDLE, W.POINT, W.DWORD)
_sig(user32.GetMonitorInfoW, W.BOOL, W.HANDLE, POINTER(MONITORINFO))
_sig(kernel32.GetModuleHandleW, W.HMODULE, W.LPCWSTR)
_sig(kernel32.GetCurrentThreadId, W.DWORD)
_sig(kernel32.GetStdHandle, W.HANDLE, W.DWORD)


_MOUSE_BTN = {
    WM_LBUTTONDOWN: (e.BTN_LEFT, 1), WM_LBUTTONUP: (e.BTN_LEFT, 0),
    WM_RBUTTONDOWN: (e.BTN_RIGHT, 1), WM_RBUTTONUP: (e.BTN_RIGHT, 0),
    WM_MBUTTONDOWN: (e.BTN_MIDDLE, 1), WM_MBUTTONUP: (e.BTN_MIDDLE, 0),
}


# ================================================================ control virtual (ViGEm)
VIGEM_ERROR_NONE = 0x20000000
VIGEM_ERROR_BUS_NOT_FOUND = 0xE0000001

XUSB = {
    e.BTN_A: 0x1000, e.BTN_B: 0x2000, e.BTN_X: 0x4000, e.BTN_Y: 0x8000,
    e.BTN_TL: 0x0100, e.BTN_TR: 0x0200, e.BTN_SELECT: 0x0020, e.BTN_START: 0x0010,
    e.BTN_MODE: 0x0400, e.BTN_THUMBL: 0x0040, e.BTN_THUMBR: 0x0080,
}
DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT = 0x0001, 0x0002, 0x0004, 0x0008


class XUSB_REPORT(ctypes.Structure):
    _fields_ = [("wButtons", c_ushort), ("bLeftTrigger", c_ubyte), ("bRightTrigger", c_ubyte),
                ("sThumbLX", c_short), ("sThumbLY", c_short),
                ("sThumbRX", c_short), ("sThumbRY", c_short)]


class VigemError(RuntimeError):
    def __init__(self, what, code):
        super().__init__(f"{what}: 0x{code:08X}")
        self.code = code


def _clamp16(v):
    return max(-32768, min(32767, int(v)))


class X360Pad:
    """Control Xbox 360 virtual con la misma interfaz que evdev.UInput: write() + syn()."""

    def __init__(self, dll_path):
        self.dll = ctypes.CDLL(str(dll_path))
        d = self.dll
        _sig(d.vigem_alloc, c_void_p)
        _sig(d.vigem_free, None, c_void_p)
        _sig(d.vigem_connect, c_uint, c_void_p)
        _sig(d.vigem_disconnect, None, c_void_p)
        _sig(d.vigem_target_x360_alloc, c_void_p)
        _sig(d.vigem_target_free, None, c_void_p)
        _sig(d.vigem_target_add, c_uint, c_void_p, c_void_p)
        _sig(d.vigem_target_remove, c_uint, c_void_p, c_void_p)
        _sig(d.vigem_target_x360_update, c_uint, c_void_p, c_void_p, XUSB_REPORT)

        self.client = d.vigem_alloc()
        self.target = None
        err = d.vigem_connect(self.client)
        if err != VIGEM_ERROR_NONE:
            d.vigem_free(self.client)
            self.client = None
            raise VigemError("vigem_connect", err)
        self.target = d.vigem_target_x360_alloc()
        err = d.vigem_target_add(self.client, self.target)
        if err != VIGEM_ERROR_NONE:
            self.close()
            raise VigemError("vigem_target_add", err)
        self.buttons = set()
        self.abs = {}

    def write(self, etype, code, value):
        if etype == e.EV_KEY:
            if value:
                self.buttons.add(code)
            else:
                self.buttons.discard(code)
        elif etype == e.EV_ABS:
            self.abs[code] = value

    def syn(self):
        a = self.abs.get
        w = 0
        for code in self.buttons:
            w |= XUSB.get(code, 0)
        hx, hy = a(e.ABS_HAT0X, 0), a(e.ABS_HAT0Y, 0)
        if hy < 0:
            w |= DPAD_UP
        elif hy > 0:
            w |= DPAD_DOWN
        if hx < 0:
            w |= DPAD_LEFT
        elif hx > 0:
            w |= DPAD_RIGHT
        rep = XUSB_REPORT(
            wButtons=w,
            bLeftTrigger=max(0, min(255, a(e.ABS_Z, 0))),
            bRightTrigger=max(0, min(255, a(e.ABS_RZ, 0))),
            # evdev: Y positivo = abajo.  XInput: Y positivo = arriba.
            sThumbLX=_clamp16(a(e.ABS_X, 0)), sThumbLY=_clamp16(-a(e.ABS_Y, 0)),
            sThumbRX=_clamp16(a(e.ABS_RX, 0)), sThumbRY=_clamp16(-a(e.ABS_RY, 0)),
        )
        self.dll.vigem_target_x360_update(self.client, self.target, rep)

    def close(self):
        d = self.dll
        if self.client and self.target:
            try:
                d.vigem_target_remove(self.client, self.target)
            except OSError:
                pass
        if self.target:
            d.vigem_target_free(self.target)
            self.target = None
        if self.client:
            d.vigem_disconnect(self.client)
            d.vigem_free(self.client)
            self.client = None


class FakePad:
    """Para probar sin ViGEmBus: imprime los cambios del control."""

    def __init__(self):
        self.state = {}

    def write(self, etype, code, value):
        self.state[(etype, code)] = value

    def syn(self):
        on = [f"{e.bytype[t].get(c, c) if t in e.bytype else c}={v}" for (t, c), v in self.state.items() if v]
        log("[pad] " + (" ".join(str(x) for x in on) or "(nada)"))

    def close(self):
        pass


# ================================================================ hooks
class Hooks(threading.Thread):
    """Hilo con los hooks de bajo nivel y la ventana de Raw Input. Mete eventos en una cola."""

    def __init__(self, events):
        super().__init__(name="kb2pad-hooks", daemon=True)
        self.q = events
        self.grab_active = False          # lo cambia MouseGrab desde el hilo principal
        self.anchor = (0, 0)
        self.kdown = set()
        self.passed_down = set()          # botones cuyo "down" paso a Windows
        self.wheel_acc = {WM_MOUSEWHEEL: 0, WM_MOUSEHWHEEL: 0}   # acumula ruedas de alta resolucion
        self.tid = None
        self.ready = threading.Event()
        self.error = None
        self._kb = HOOKPROC(self._kb_proc)
        self._ms = HOOKPROC(self._ms_proc)
        self._wndproc = WNDPROC(self._wnd_proc)
        self._rawbuf = ctypes.create_string_buffer(256)

    # --- callbacks (rapidos: nunca deben lanzar excepcion) ---
    def _kb_proc(self, n, wparam, lparam):
        try:
            if n == 0:
                k = ctypes.cast(lparam, POINTER(KBDLLHOOKSTRUCT)).contents
                if not k.flags & LLKHF_INJECTED:
                    code = scan_to_code(k.scanCode, k.flags & LLKHF_EXTENDED, k.vkCode)
                    if code:
                        if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            if code not in self.kdown:
                                self.kdown.add(code)
                                self.q.put(("key", code, 1))
                        elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                            self.kdown.discard(code)
                            self.q.put(("key", code, 0))
        except Exception:  # noqa: BLE001
            pass
        return user32.CallNextHookEx(None, n, wparam, lparam)

    def _ms_proc(self, n, wparam, lparam):
        block = False
        try:
            if n == 0:
                m = ctypes.cast(lparam, POINTER(MSLLHOOKSTRUCT)).contents
                if not m.flags & LLMHF_INJECTED:
                    grabbed = self.grab_active
                    if wparam == WM_MOUSEMOVE:
                        if grabbed:
                            block = True
                            dx, dy = m.pt.x - self.anchor[0], m.pt.y - self.anchor[1]
                            if dx or dy:
                                self.q.put(("rel_ll", dx, dy, time.monotonic()))
                    elif wparam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                        block = grabbed
                        delta = c_short((m.mouseData >> 16) & 0xFFFF).value   # 120 por muesca
                        acc = self.wheel_acc[wparam] + delta
                        notches = int(acc / 120)
                        self.wheel_acc[wparam] = acc - notches * 120
                        if notches:
                            # vertical: positivo = arriba.  horizontal: positivo = derecha
                            axis = e.REL_WHEEL if wparam == WM_MOUSEWHEEL else e.REL_HWHEEL
                            self.q.put(("wheel", axis, notches))
                    else:
                        if wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                            which = (m.mouseData >> 16) & 0xFFFF
                            code = e.BTN_SIDE if which == 1 else e.BTN_EXTRA if which == 2 else None
                            val = 1 if wparam == WM_XBUTTONDOWN else 0
                        else:
                            code, val = _MOUSE_BTN.get(wparam, (None, 0))
                        if code is not None:
                            self.q.put(("key", code, val))
                            if val:
                                block = grabbed
                                if not block:
                                    self.passed_down.add(code)
                            else:
                                # si el "down" llego a Windows, el "up" tambien, para no trabar el boton
                                block = grabbed and code not in self.passed_down
                                self.passed_down.discard(code)
        except Exception:  # noqa: BLE001
            pass
        if block:
            return 1
        return user32.CallNextHookEx(None, n, wparam, lparam)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT and self.grab_active:
            try:
                size = c_uint(len(self._rawbuf))
                got = user32.GetRawInputData(lparam, RID_INPUT, self._rawbuf, byref(size),
                                             sizeof(RAWINPUTHEADER))
                if got != 0xFFFFFFFF and got >= sizeof(RAWINPUTHEADER):
                    ri = RAWINPUT.from_buffer_copy(self._rawbuf.raw[:sizeof(RAWINPUT)])
                    if ri.header.dwType == RIM_TYPEMOUSE and not ri.mouse.usFlags & MOUSE_MOVE_ABSOLUTE:
                        dx, dy = ri.mouse.lLastX, ri.mouse.lLastY
                        if dx or dy:
                            self.q.put(("rel_raw", dx, dy, time.monotonic()))
            except Exception:  # noqa: BLE001
                pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # --- hilo ---
    def run(self):
        hinst = kernel32.GetModuleHandleW(None)
        self.tid = kernel32.GetCurrentThreadId()
        hk = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb, hinst, 0)
        hm = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms, hinst, 0)
        if not hk or not hm:
            self.error = f"no pude instalar los hooks de teclado/mouse (error {ctypes.get_last_error()})"
            for h in (hk, hm):
                if h:
                    user32.UnhookWindowsHookEx(h)
            self.ready.set()
            return

        hwnd = None
        try:
            wc = WNDCLASSEXW()
            wc.cbSize = sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = "kb2pad_rawinput"
            user32.RegisterClassExW(byref(wc))
            # ventana normal pero nunca visible (INPUTSINK no siempre funciona con HWND_MESSAGE)
            hwnd = user32.CreateWindowExW(0, "kb2pad_rawinput", "kb2pad", 0, 0, 0, 0, 0,
                                          None, None, hinst, None)
            if hwnd:
                rid = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)
                if not user32.RegisterRawInputDevices(byref(rid), 1, sizeof(RAWINPUTDEVICE)):
                    log("Aviso: Raw Input no disponible; uso el movimiento del hook")
        except Exception as exc:  # noqa: BLE001
            log(f"Aviso: Raw Input no disponible ({exc}); uso el movimiento del hook")

        self.ready.set()
        msg = W.MSG()
        while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))

        user32.UnhookWindowsHookEx(hk)
        user32.UnhookWindowsHookEx(hm)
        if hwnd:
            user32.DestroyWindow(hwnd)

    def stop(self):
        self.grab_active = False
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


class MouseGrab:
    """Lo que el Mapper llama grab()/ungrab(): bloquea el mouse y fija el cursor al centro."""

    name = "mouse"

    def __init__(self, hooks, on_grab):
        self.hooks = hooks
        self.on_grab = on_grab
        self.saved = None

    def grab(self):
        pt = W.POINT()
        user32.GetCursorPos(byref(pt))
        self.saved = (pt.x, pt.y)
        cx, cy = pt.x, pt.y
        mi = MONITORINFO()
        mi.cbSize = sizeof(MONITORINFO)
        mon = user32.MonitorFromPoint(pt, 2)
        if mon and user32.GetMonitorInfoW(mon, byref(mi)):
            r = mi.rcMonitor
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        user32.SetCursorPos(cx, cy)
        self.hooks.anchor = (cx, cy)
        self.on_grab()
        self.hooks.grab_active = True

    def ungrab(self):
        self.hooks.grab_active = False
        if self.saved:
            user32.SetCursorPos(*self.saved)
            self.saved = None


# ================================================================ main
def _fix_stdio():
    """En el .exe sin consola, sys.stdout/stdin pueden ser None aunque la GUI pase tuberias."""
    import msvcrt
    for std, name, mode in ((-10, "stdin", "r"), (-11, "stdout", "w"), (-12, "stderr", "w")):
        stream = getattr(sys, name)
        if stream is None:
            h = kernel32.GetStdHandle(std & 0xFFFFFFFF)
            if h and h != c_void_p(-1).value:
                try:
                    fd = msvcrt.open_osfhandle(h, os.O_RDONLY if mode == "r" else os.O_WRONLY)
                    setattr(sys, name, open(fd, mode, buffering=1, encoding="utf-8",
                                            errors="replace", closefd=False))
                except OSError:
                    pass
        elif mode == "w":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except (AttributeError, ValueError):
                pass


def _dpi_aware():
    try:
        user32.SetProcessDpiAwarenessContext(c_void_p(-4))   # per monitor v2
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def resource_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def vigem_dll():
    return resource_dir() / "vigem" / "ViGEmClient.dll"


def vigem_installer():
    return resource_dir() / "vigem" / "ViGEmBusSetup_x64.msi"


def _stdin_reader(events):
    try:
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd:
                events.put(("cmd", cmd))
    except (OSError, ValueError, AttributeError):
        pass
    events.put(("cmd", "eof"))


def main(argv=None):
    _fix_stdio()
    _dpi_aware()
    ap = argparse.ArgumentParser(description="kb2pad (Windows): teclado + mouse -> control Xbox 360 virtual")
    ap.add_argument("--config", default=str(C.CONFIG_PATH))
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--fake-pad", action="store_true", help="no crea el control: imprime su estado (pruebas)")
    args = ap.parse_args(argv)
    path = Path(args.config).expanduser()

    try:
        raw, errors, warnings = load_engine_config(path)
    except ValueError as exc:
        log(f"ERROR: {exc}")
        return 2
    for w in warnings:
        log(f"Aviso: {w}")
    if errors:
        for err in errors:
            log(f"ERROR: {err}")
        return 2
    cfg = EngineConfig(raw)

    if args.fake_pad:
        pad = FakePad()
    else:
        dll = vigem_dll()
        if not dll.is_file():
            log(f"ERROR: falta {dll}")
            return 1
        try:
            pad = X360Pad(dll)
        except VigemError as exc:
            if exc.code == VIGEM_ERROR_BUS_NOT_FOUND:
                log("ERROR: no encontre el driver ViGEmBus. Instalalo desde Archivo > Instalar ViGEmBus "
                    "(pide permisos de administrador) y vuelve a iniciar el control.")
            else:
                log(f"ERROR: ViGEm fallo ({exc})")
            return 3
        except OSError as exc:
            log(f"ERROR: no pude cargar ViGEmClient.dll ({exc})")
            return 1

    events = queue.Queue()
    hooks = Hooks(events)
    hooks.start()
    hooks.ready.wait(5)
    if hooks.error or not hooks.ready.is_set():
        log(f"ERROR: {hooks.error or 'los hooks no respondieron'}")
        pad.close()
        return 1

    # movimiento: por sesion de captura se decide si llega por Raw Input o por el hook
    rel = types.SimpleNamespace(mode="?", pending=[0, 0], pending_t=None)

    def reset_rel():
        rel.mode, rel.pending, rel.pending_t = "?", [0, 0], None

    mouse = MouseGrab(hooks, reset_rel)
    keyboard = types.SimpleNamespace(name="teclado")
    mapper = Mapper(pad, [mouse], cfg, debug=args.debug)
    threading.Thread(target=_stdin_reader, args=(events,), daemon=True).start()

    log(f"Config: {path}")
    log(f"Control virtual: {'FALSO (prueba)' if args.fake_pad else 'Xbox 360 (ViGEmBus)'}")
    log(f"Config cargada: {summary(raw)}")
    log("ACTIVO")

    def ev(etype, code, value):
        return types.SimpleNamespace(type=etype, code=code, value=value)

    def move(dx, dy):
        if dx:
            mapper.handle(mouse, ev(e.EV_REL, e.REL_X, dx))
        if dy:
            mapper.handle(mouse, ev(e.EV_REL, e.REL_Y, dy))

    def reload(reason):
        try:
            new_raw, errs, warns = load_engine_config(path)
        except ValueError as exc:
            log(f"No recargue la config: {exc}")
            return
        if errs:
            log("No recargue la config, tiene errores:")
            for err in errs:
                log(f"  - {err}")
            return
        for w in warns:
            log(f"Aviso: {w}")
        mapper.set_config(EngineConfig(new_raw))
        log(f"Config recargada ({reason}): {summary(new_raw)}")

    def mtime():
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    last_mtime, last_check = mtime(), time.monotonic()
    running = True
    try:
        while running:
            timeout = mapper.service()
            timeout = 0.5 if timeout is None else min(timeout, 0.5)
            if rel.pending_t is not None:
                timeout = min(timeout, max(0.0, rel.pending_t + 0.04 - time.monotonic()))
            try:
                items = [events.get(timeout=timeout)]
            except queue.Empty:
                items = []
            while True:
                try:
                    items.append(events.get_nowait())
                except queue.Empty:
                    break

            for item in items:
                kind = item[0]
                if kind == "key":
                    mapper.handle(keyboard if item[1] < e.BTN_MISC else mouse, ev(e.EV_KEY, item[1], item[2]))
                elif kind == "wheel":
                    mapper.handle(mouse, ev(e.EV_REL, item[1], item[2]))
                elif kind == "rel_raw":
                    if rel.mode != "ll":
                        rel.mode, rel.pending, rel.pending_t = "raw", [0, 0], None
                        move(item[1], item[2])
                elif kind == "rel_ll":
                    if rel.mode == "ll":
                        move(item[1], item[2])
                    elif rel.mode == "?":
                        rel.pending[0] += item[1]
                        rel.pending[1] += item[2]
                        if rel.pending_t is None:
                            rel.pending_t = item[3]
                elif kind == "cmd":
                    cmd = item[1]
                    if cmd in ("quit", "eof"):
                        running = False
                    elif cmd == "reload":
                        last_mtime = mtime()
                        reload("guardado")
                    elif cmd in ("debug on", "debug off"):
                        mapper.debug = cmd.endswith("on")
                        log("Debug de teclas " + ("activado" if mapper.debug else "desactivado"))

            # si en 40 ms no llego Raw Input con el mouse capturado, el respaldo es el hook
            if rel.mode == "?" and rel.pending_t is not None and time.monotonic() - rel.pending_t > 0.04:
                rel.mode = "ll"
                dx, dy = rel.pending
                rel.pending, rel.pending_t = [0, 0], None
                log("Mouse: uso el movimiento del hook (Raw Input no llega con el mouse capturado)")
                move(dx, dy)

            now = time.monotonic()
            if now - last_check >= 0.5:
                last_check = now
                current = mtime()
                if current != last_mtime:
                    last_mtime = current
                    reload("archivo modificado")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            mapper.release_all()
            mapper.mouselook = False
            mapper.update_grab()
            mapper.push()
        finally:
            hooks.stop()
            pad.close()
            log("Control virtual cerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
