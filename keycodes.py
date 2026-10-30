"""
Codigos de teclas/botones con nombres de evdev (KEY_Q, BTN_SIDE, ABS_X...).

En Linux usa python-evdev. En Windows (sin evdev) usa la tabla generada _ecodes_data.py,
asi el config.json es el mismo en los dos sistemas.

Uso:  from keycodes import e      ->  e.KEY_Q, e.KEY, e.ecodes, e.bytype
"""
try:
    from evdev import ecodes as e  # noqa: F401
except ImportError:
    import types

    import _ecodes_data as _d

    e = types.SimpleNamespace(**_d.CONSTS)
    e.KEY = _d.KEY
    e.BTN = _d.BTN
    e.ABS = _d.ABS
    e.ecodes = dict(_d.CONSTS)

    _keys = dict(_d.KEY)
    _keys.update(_d.BTN)
    e.bytype = {e.EV_KEY: _keys, e.EV_ABS: _d.ABS}


# ================================================================ Windows: scancode -> evdev
# Para la mayoria de teclas el scancode de PC (set 1) es igual al codigo de evdev.
_EXTENDED = {
    0x1C: e.KEY_KPENTER, 0x1D: e.KEY_RIGHTCTRL, 0x35: e.KEY_KPSLASH, 0x37: e.KEY_SYSRQ,
    0x38: e.KEY_RIGHTALT, 0x45: e.KEY_NUMLOCK, 0x47: e.KEY_HOME, 0x48: e.KEY_UP,
    0x49: e.KEY_PAGEUP, 0x4B: e.KEY_LEFT, 0x4D: e.KEY_RIGHT, 0x4F: e.KEY_END,
    0x50: e.KEY_DOWN, 0x51: e.KEY_PAGEDOWN, 0x52: e.KEY_INSERT, 0x53: e.KEY_DELETE,
    0x5B: e.KEY_LEFTMETA, 0x5C: e.KEY_RIGHTMETA, 0x5D: e.KEY_COMPOSE,
}
_BY_VK = {0x13: e.KEY_PAUSE, 0x2C: e.KEY_SYSRQ, 0x90: e.KEY_NUMLOCK}
_F13_F24 = {0x64 + i: getattr(e, f"KEY_F{13 + i}") for i in range(12) if hasattr(e, f"KEY_F{13 + i}")}


def win_scan_to_code(scan, extended, vk=0):
    """Scancode de Windows (+ bandera extendida y virtual key) -> codigo evdev, o None."""
    if vk in _BY_VK:
        return _BY_VK[vk]
    if extended:
        return _EXTENDED.get(scan)
    if 1 <= scan <= 0x58:
        return scan
    return _F13_F24.get(scan)
