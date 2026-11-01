"""
kb2pad core - logica del control virtual compartida por Linux (engine.py) y Windows (engine_win.py).

El Mapper recibe eventos con nombres/codigos de evdev y escribe el estado del control
en un objeto "ui" con write(tipo, codigo, valor) y syn(), igual que evdev.UInput.
Cada sistema pone su propio ui (uinput en Linux, ViGEm en Windows).
"""
import math
import time
import types

import config as C
from keycodes import e

LT, RT = "LT", "RT"
OUT_CODES = {
    "A": e.BTN_A, "B": e.BTN_B, "X": e.BTN_X, "Y": e.BTN_Y,
    "LB": e.BTN_TL, "RB": e.BTN_TR, "BACK": e.BTN_SELECT, "START": e.BTN_START,
    "L3": e.BTN_THUMBL, "R3": e.BTN_THUMBR, "LT": LT, "RT": RT,
    "DPAD_UP": "DPAD_UP", "DPAD_DOWN": "DPAD_DOWN",
    "DPAD_LEFT": "DPAD_LEFT", "DPAD_RIGHT": "DPAD_RIGHT",
}
# direccion del D-pad -> (eje del hat, valor)
DPAD_OUT = {"DPAD_UP": (e.ABS_HAT0Y, -1), "DPAD_DOWN": (e.ABS_HAT0Y, 1),
            "DPAD_LEFT": (e.ABS_HAT0X, -1), "DPAD_RIGHT": (e.ABS_HAT0X, 1)}
STICK_MAX = 32767
TICK = 1 / 250
PAD_NAME = "Microsoft X-Box 360 pad (kb2pad)"
PAD_BUTTONS = (e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y, e.BTN_TL, e.BTN_TR,
               e.BTN_SELECT, e.BTN_START, e.BTN_MODE, e.BTN_THUMBL, e.BTN_THUMBR)
TRIGGER_AXIS = {LT: e.ABS_Z, RT: e.ABS_RZ}
WHEEL_GAP = 0.04          # pausa entre toques cuando giras varias muescas seguidas
WHEEL_MAX_QUEUE = 4



_log_fn = None


def set_logger(fn):
    global _log_fn
    _log_fn = fn


def log(msg):
    if _log_fn is not None:
        _log_fn(msg)
        return
    try:
        print(msg, flush=True)
    except (OSError, ValueError, AttributeError):
        pass


class EngineConfig:
    """Config JSON (nombres) -> codigos evdev listos para usar."""

    def __init__(self, raw, mode=None):
        k = C.input_code
        sp = raw["special"]
        self.toggle_key = k(sp["pause"])
        self.mouselook_key = k(sp["mouselook"])

        # modos: Alt + tecla
        self.alt_keys = {k(n) for n in C.MODE_MODIFIERS}
        self.alt_blocks = bool(sp.get("alt_blocks", True))
        self.chat_key = k(sp["chat"]) if sp.get("chat") else None
        self.back_key = k(sp["mode_back"]) if sp.get("mode_back") else None
        self.profile_key = k(sp["profile_toggle"]) if sp.get("profile_toggle") else None
        self.chat_alt = k("KEY_LEFTALT")     # en el chat solo Alt izq: AltGr + Q escribe @
        self.mode_hotkeys = {}       # tecla -> nombre del modo
        for m in raw.get("modes") or []:
            if m.get("hotkey"):
                self.mode_hotkeys[k(m["hotkey"])] = m["name"]
        self.mode_maps = {name: self._build(C.effective_bindings(raw, name))
                          for name in C.mode_names(raw)}
        names = C.mode_names(raw)
        self.start_mode = raw.get("start_mode") if raw.get("start_mode") in names else names[0]

        st = raw["sticks"]
        self.move_keys = tuple(k(n) for n in st["move"])
        self.cam_keys = tuple(k(n) for n in st["camera"])
        self.dpad_keys = tuple(k(n) for n in st["dpad"])

        m = raw["mouse"]
        self.mouse_full_speed = float(m["full_speed"])
        self.anti_deadzone = float(m["anti_deadzone"])
        self.smoothing = float(m["smoothing"])
        self.invert_y = bool(m["invert_y"])

        r = raw["radial"]
        self.radial_radius = float(r["radius"])
        self.radial_deadzone = float(r["deadzone"])
        self.radial_release_delay = float(r["release_delay"])

        self.combo_delay = float(raw["combo_delay"])
        self.set_mode(mode if mode in self.mode_maps else self.start_mode)

    @staticmethod
    def _build(bindings):
        k = C.input_code
        buttons = {}            # tecla -> salidas
        mouselook_buttons = {}  # solo con mouse-camara
        combos = {}             # tecla -> (modificador, salidas)
        radial_keys = {}        # tecla -> segundos antes de entrar al radial
        for b in bindings:
            code = k(b["input"])
            outs = tuple(OUT_CODES[o] for o in b["outputs"])
            mods = tuple(OUT_CODES[o] for o in b.get("modifier") or [])
            if b.get("camera_only"):
                mouselook_buttons[code] = outs
            elif mods:
                combos[code] = (mods, outs)
            else:
                buttons[code] = outs
                if b.get("radial"):
                    radial_keys[code] = max(0.0, float(b.get("radial_hold", 0.0)))
        return buttons, mouselook_buttons, combos, radial_keys

    def set_mode(self, name):
        if name not in self.mode_maps:
            name = self.start_mode
        self.mode = name
        self.buttons, self.mouselook_buttons, self.combos, self.radial_keys = self.mode_maps[name]


def load_engine_config(path):
    raw = C.load_config(path, create=False)
    errors, warnings = C.validate(raw)
    return raw, errors, warnings


# ================================================================ helpers
def code_name(code):
    if code in C.WHEEL_BY_CODE:
        return C.WHEEL_BY_CODE[code]
    name = e.bytype[e.EV_KEY].get(code, str(code))
    return name if isinstance(name, str) else "/".join(name)


def dir_xy(pressed, keys):
    up, down, left, right = keys
    return (right in pressed) - (left in pressed), (down in pressed) - (up in pressed)


def unit_stick(x, y):
    m = math.hypot(x, y)
    if m > 1:
        x, y = x / m, y / m
    return int(round(x * STICK_MAX)), int(round(y * STICK_MAX))


def press_outputs(st, outputs):
    for out in outputs:
        if out in TRIGGER_AXIS:
            st[(e.EV_ABS, TRIGGER_AXIS[out])] = 255
        elif out in DPAD_OUT:
            axis, value = DPAD_OUT[out]
            st[(e.EV_ABS, axis)] = value
        else:
            st[(e.EV_KEY, out)] = 1


# ================================================================ mapper
class Mapper:
    def __init__(self, ui, mice, cfg, debug=False):
        self.ui = ui
        self.mice = mice
        self.cfg = cfg
        self.debug = debug
        self.pressed = set()
        self.enabled = True
        self.mouselook = False
        self.grabbed = False
        self.acc_x = self.acc_y = 0
        self.vel_x = self.vel_y = 0.0
        self.mouse_xy = (0.0, 0.0)
        self.radial_key = None
        self.radial_pos = [0.0, 0.0]
        self.radial_out = (0.0, 0.0)
        self.radial_pending = {}
        self.radial_release = {}
        self.combo_t = {}
        self.combo_fired = set()
        self.consumed = set()         # teclas usadas con Alt: su "soltar" se ignora
        self.chat = False             # modo chat: el teclado no es control (el mouse si)
        self.prev_mode = cfg.mode
        self.wheel = {}               # codigo de rueda -> {"down", "until", "left"}
        self.last = {}
        self.last_tick = time.monotonic()
        self.push()
        log(f"Modo: {cfg.mode}")

    # ---------- salida ----------
    def compute(self):
        cfg = self.cfg
        p = self.pressed
        st = {}
        mx, my = dir_xy(p, cfg.move_keys)
        st[(e.EV_ABS, e.ABS_X)], st[(e.EV_ABS, e.ABS_Y)] = unit_stick(mx, my)

        cx, cy = dir_xy(p, cfg.cam_keys)            # teclas de camara ganan
        if not (cx or cy):
            cx, cy = self.cam_xy()
        st[(e.EV_ABS, e.ABS_RX)], st[(e.EV_ABS, e.ABS_RY)] = unit_stick(cx, cy)

        hx, hy = dir_xy(p, cfg.dpad_keys)
        st[(e.EV_ABS, e.ABS_HAT0X)] = hx
        st[(e.EV_ABS, e.ABS_HAT0Y)] = hy

        for axis in TRIGGER_AXIS.values():
            st[(e.EV_ABS, axis)] = 0
        for b in PAD_BUTTONS:
            st[(e.EV_KEY, b)] = 0

        maps = (cfg.buttons, cfg.mouselook_buttons) if self.mouselook else (cfg.buttons,)
        for mp in maps:
            for code, outs in mp.items():
                if code in p:
                    press_outputs(st, outs)
        for code, (mods, outs) in cfg.combos.items():
            if code in p:
                press_outputs(st, mods)
                if code in self.combo_fired:
                    press_outputs(st, outs)
        return st

    def cam_xy(self):
        if self.radial_key is not None:
            return self.radial_out
        if self.radial_release:
            return (0.0, 0.0)
        if self.mouselook:
            return self.mouse_xy
        return (0.0, 0.0)

    def push(self):
        new = self.compute()
        changed = False
        for (etype, code), value in new.items():
            if self.last.get((etype, code)) != value:
                self.ui.write(etype, code, value)
                changed = True
        if changed:
            self.ui.syn()
        self.last = new

    # ---------- mouse ----------
    def update_grab(self):
        want = self.enabled and (self.mouselook or self.radial_key is not None)
        if want == self.grabbed:
            return
        for m in self.mice:
            try:
                m.grab() if want else m.ungrab()
            except OSError:
                pass
        self.grabbed = want

    def reset_mouse_motion(self):
        self.acc_x = self.acc_y = 0
        self.vel_x = self.vel_y = 0.0
        self.mouse_xy = (0.0, 0.0)
        self.last_tick = time.monotonic()

    # ---------- modos ----------
    def release_all(self):
        self.pressed.clear()
        self.consumed.clear()
        self.wheel.clear()
        self.combo_t.clear()
        self.combo_fired.clear()
        self.radial_key = None
        self.radial_out = (0.0, 0.0)
        self.radial_pending.clear()
        self.radial_release.clear()

    def set_config(self, cfg):
        self.release_all()
        self.push()                    # suelta todo con la config vieja
        if self.cfg.mode in cfg.mode_maps:
            cfg.set_mode(self.cfg.mode)   # al recargar se queda en el mismo modo
        self.cfg = cfg
        self.reset_mouse_motion()
        self.update_grab()
        self.push()

    def switch_mode(self, name):
        """Cambia de modo sin soltar las teclas que sigues presionando (moverte, correr)."""
        if self.chat:
            self.chat = False
            log("Chat: OFF")
        if self.radial_key is not None:
            self.radial_key = None
            self.radial_out = (0.0, 0.0)
        self.radial_pending.clear()
        self.radial_release.clear()
        self.combo_t.clear()
        self.combo_fired.clear()
        self.cfg.set_mode(name)
        self.reset_mouse_motion()
        self.update_grab()
        self.push()
        log(f"Modo: {self.cfg.mode}")

    def set_chat(self, on):
        """Modo chat: el teclado deja de mandar botones/sticks (para escribir); el mouse sigue igual."""
        if on == self.chat:
            return
        cfg = self.cfg
        if on:
            self.prev_mode = cfg.mode
        self.chat = on
        if on:
            kb = {c for c in self.pressed if c < e.BTN_MISC and c not in cfg.alt_keys}
            self.pressed -= kb
            for d in (self.radial_pending, self.combo_t):
                for c in [c for c in d if c in kb]:
                    del d[c]
            self.combo_fired -= kb
            if self.radial_key in kb:
                self.radial_key = None
                self.radial_out = (0.0, 0.0)
                self.reset_mouse_motion()
                self.update_grab()
        self.push()
        log("Chat: ON" if on else "Chat: OFF")
        if not on:
            log(f"Modo: {cfg.mode}")

    def set_mouselook(self, on):
        self.mouselook = on
        self.reset_mouse_motion()
        self.pressed -= set(self.cfg.mouselook_buttons)
        self.update_grab()
        log("Mouse = camara (stick derecho)" if on else "Mouse = normal (scrcpy)")
        self.push()

    def radial_start(self, key):
        self.radial_key = key
        self.radial_pos = [0.0, 0.0]
        self.radial_out = (0.0, 0.0)
        self.reset_mouse_motion()
        self.update_grab()

    def radial_end(self, key):
        # centra el stick con el boton aun presionado (el juego selecciona) y lo suelta despues
        self.radial_key = None
        self.radial_out = (0.0, 0.0)
        self.radial_release[key] = time.monotonic() + self.cfg.radial_release_delay
        self.reset_mouse_motion()
        self.update_grab()

    def radial_move(self, dx, dy):
        cfg = self.cfg
        x = self.radial_pos[0] + dx / cfg.radial_radius
        y = self.radial_pos[1] + dy / cfg.radial_radius * (-1 if cfg.invert_y else 1)
        m = math.hypot(x, y)
        if m > 1:
            x, y = x / m, y / m
            m = 1.0
        self.radial_pos = [x, y]
        if m >= cfg.radial_deadzone:
            self.radial_out = (x / m, y / m)

    def radial_key_down(self, key):
        self.radial_release.pop(key, None)
        self.pressed.add(key)
        if self.radial_key is not None:
            return
        if self.cfg.radial_keys[key] <= 0:
            self.radial_start(key)
        else:
            self.radial_pending[key] = time.monotonic()

    def radial_key_up(self, key):
        if key == self.radial_key:
            self.radial_end(key)
        else:
            self.radial_pending.pop(key, None)
            self.pressed.discard(key)

    # ---------- eventos ----------
    def handle(self, dev, ev):
        cfg = self.cfg
        if ev.type == e.EV_REL:
            if not self.enabled:
                return
            if ev.code in (e.REL_WHEEL, e.REL_HWHEEL):
                if ev.value:
                    if ev.code == e.REL_WHEEL:
                        name = "WHEEL_UP" if ev.value > 0 else "WHEEL_DOWN"
                    else:
                        name = "WHEEL_RIGHT" if ev.value > 0 else "WHEEL_LEFT"
                    self.wheel_notch(C.WHEEL_CODES[name], abs(ev.value))
                return
            if self.radial_key is not None:
                if ev.code == e.REL_X:
                    self.radial_move(ev.value, 0)
                    self.push()
                elif ev.code == e.REL_Y:
                    self.radial_move(0, ev.value)
                    self.push()
            elif self.mouselook:
                if ev.code == e.REL_X:
                    self.acc_x += ev.value
                elif ev.code == e.REL_Y:
                    self.acc_y += ev.value
            return
        if ev.type != e.EV_KEY or ev.value == 2:
            return
        if self.debug and ev.value == 1:
            dname = getattr(dev, "name", "?")
            log(f"[tecla] {code_name(ev.code)} ({ev.code})  <- {dname}")

        if ev.code == cfg.toggle_key:
            if ev.value == 1:
                self.enabled = not self.enabled
                self.release_all()
                if self.mouselook:
                    self.set_mouselook(False)
                else:
                    self.update_grab()
                    self.push()
                log("ACTIVO" if self.enabled else "PAUSADO")
            return
        if not self.enabled:
            return

        # Alt + tecla: cambio de modo; con Alt presionado no se manda nada mas al juego
        if ev.value == 0 and ev.code in self.consumed:
            self.consumed.discard(ev.code)
            return
        alts = (cfg.chat_alt,) if self.chat else cfg.alt_keys
        if ev.value == 1 and ev.code not in cfg.alt_keys and any(a in self.pressed for a in alts):
            if ev.code == cfg.chat_key:
                self.consumed.add(ev.code)
                if self.chat:
                    log("Chat: ON")        # ya estaba: la GUI le regresa el foco a la ventanita
                else:
                    self.set_chat(True)
                return
            if ev.code == cfg.profile_key:
                self.consumed.add(ev.code)
                log("Perfil: alternar")         # la GUI cambia el perfil de video y reabre scrcpy
                return
            if ev.code == cfg.back_key:
                self.consumed.add(ev.code)
                if self.chat:
                    self.set_chat(False)
                    if self.prev_mode != cfg.mode:
                        self.switch_mode(self.prev_mode)
                else:
                    self.switch_mode(cfg.start_mode)
                return
            name = cfg.mode_hotkeys.get(ev.code)
            if name is not None:
                self.consumed.add(ev.code)
                self.switch_mode(name)
                return
            if cfg.alt_blocks and not self.chat:
                self.consumed.add(ev.code)
                return

        if self.chat and ev.code < e.BTN_MISC:
            # escribiendo: el teclado no es control; solo se sigue Alt para los atajos
            if ev.code in cfg.alt_keys:
                (self.pressed.add if ev.value else self.pressed.discard)(ev.code)
            return

        if ev.code == cfg.mouselook_key:
            if ev.value == 1:
                self.set_mouselook(not self.mouselook)
            return

        if ev.code in cfg.radial_keys:
            if ev.value == 1:
                self.radial_key_down(ev.code)
            else:
                self.radial_key_up(ev.code)
            self.push()
            return

        if ev.value == 1:
            self.pressed.add(ev.code)
            if ev.code in cfg.combos:
                self.combo_t[ev.code] = time.monotonic()
                self.combo_fired.discard(ev.code)
        else:
            self.pressed.discard(ev.code)
            self.combo_t.pop(ev.code, None)
            self.combo_fired.discard(ev.code)
        self.push()

    # ---------- rueda ----------
    def _wheel_key(self, code, value):
        self.handle(types.SimpleNamespace(name="rueda"),
                    types.SimpleNamespace(type=e.EV_KEY, code=code, value=value))

    def _wheel_tap(self):
        return max(0.06, self.cfg.combo_delay + 0.05)

    def wheel_notch(self, code, n=1):
        """Cada muesca de la rueda es un toque corto de su asignacion (las demas se encolan)."""
        st = self.wheel.get(code)
        if st is None:
            self.wheel[code] = {"down": True, "until": time.monotonic() + self._wheel_tap(),
                                "left": min(n - 1, WHEEL_MAX_QUEUE)}
            self._wheel_key(code, 1)
        else:
            st["left"] = min(st["left"] + n, WHEEL_MAX_QUEUE)

    def _wheel_service(self, now, waits):
        for code, st in list(self.wheel.items()):
            if now < st["until"]:
                waits.append(st["until"] - now)
                continue
            if st["down"]:
                self._wheel_key(code, 0)
                if st["left"] > 0:
                    st["down"], st["until"] = False, now + WHEEL_GAP
                    waits.append(WHEEL_GAP)
                else:
                    del self.wheel[code]
            else:
                st["left"] -= 1
                st["down"], st["until"] = True, now + self._wheel_tap()
                waits.append(self._wheel_tap())
                self._wheel_key(code, 1)

    # ---------- tiempo ----------
    def mouse_tick(self, now):
        cfg = self.cfg
        dt = now - self.last_tick
        if dt < TICK:
            return TICK - dt
        self.last_tick = now
        ix, iy = self.acc_x / dt, self.acc_y / dt
        self.acc_x = self.acc_y = 0
        self.vel_x += cfg.smoothing * (ix - self.vel_x)
        self.vel_y += cfg.smoothing * (iy - self.vel_y)
        sx = self.vel_x / cfg.mouse_full_speed
        sy = self.vel_y / cfg.mouse_full_speed
        if cfg.invert_y:
            sy = -sy
        m = math.hypot(sx, sy)
        if m < 0.02:
            self.vel_x = self.vel_y = 0.0
            self.mouse_xy = (0.0, 0.0)
        else:
            mag = cfg.anti_deadzone + (1 - cfg.anti_deadzone) * min(m, 1.0)
            self.mouse_xy = (sx / m * mag, sy / m * mag)
        self.push()
        return TICK

    def service(self):
        """Lo que depende del tiempo. Regresa el timeout para select (None = nada pendiente)."""
        if not self.enabled:
            return None
        now = time.monotonic()
        waits = []
        changed = False

        for key, until in list(self.radial_release.items()):
            if now >= until:
                del self.radial_release[key]
                self.pressed.discard(key)
                changed = True
            else:
                waits.append(until - now)

        for key, t0 in list(self.radial_pending.items()):
            remaining = t0 + self.cfg.radial_keys.get(key, 0.0) - now
            if remaining <= 0:
                del self.radial_pending[key]
                if self.radial_key is None:
                    self.radial_start(key)
                    changed = True
            else:
                waits.append(remaining)

        if self.mouselook and self.radial_key is None and not self.radial_release:
            waits.append(self.mouse_tick(now))

        if self.wheel:
            self._wheel_service(now, waits)

        for code, t0 in self.combo_t.items():
            if code in self.combo_fired:
                continue
            remaining = t0 + self.cfg.combo_delay - now
            if remaining <= 0:
                self.combo_fired.add(code)
                changed = True
            else:
                waits.append(remaining)

        if changed:
            self.push()
        return min(waits) if waits else None


# ================================================================ resumen
def summary(cfg_raw):
    parts = []
    for m in cfg_raw.get("modes") or []:
        hk = f" (Alt+{C.input_label(m['hotkey'])})" if m.get("hotkey") else ""
        parts.append(f"{m['name']}{hk}: {len(m.get('bindings') or [])} asignaciones")
    return "; ".join(parts)
