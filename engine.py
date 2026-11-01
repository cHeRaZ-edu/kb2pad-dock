#!/usr/bin/env python3
"""
kb2pad engine - teclado + mouse -> control Xbox 360 virtual (uinput).

Lee la configuracion de ~/.config/kb2pad/config.json (o --config) y la recarga
en caliente cuando el archivo cambia, sin soltar el control virtual.

Normalmente lo lanza app.py. Para usarlo solo:
    sudo python engine.py --config ~/.config/kb2pad/config.json [--debug]

Comandos por stdin (uno por linea): reload | debug on | debug off | focus on | focus off | quit
("focus on" = la ventana del juego tiene el foco: la GUI lo avisa para activar el escudo del teclado)
Si stdin es una tuberia y se cierra, el motor termina (asi la GUI lo apaga aunque corra como root).
"""
import argparse
import os
import select
import stat
import sys
import time
from pathlib import Path

from evdev import AbsInfo, InputDevice, UInput, ecodes as e, list_devices

import config as C
from core import (PAD_BUTTONS, PAD_NAME, EngineConfig, Mapper, load_engine_config,
                  log, summary)


def build_pad():
    """Mismo layout que el driver xpad (Xbox 360) para que SDL/scrcpy lo mapee solo."""
    stick = AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)
    trig = AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)
    hat = AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)
    caps = {
        e.EV_KEY: list(PAD_BUTTONS),
        e.EV_ABS: [(e.ABS_X, stick), (e.ABS_Y, stick), (e.ABS_Z, trig),
                   (e.ABS_RX, stick), (e.ABS_RY, stick), (e.ABS_RZ, trig),
                   (e.ABS_HAT0X, hat), (e.ABS_HAT0Y, hat)],
    }
    return UInput(caps, name=PAD_NAME, vendor=0x045E, product=0x028E,
                  version=0x110, bustype=e.BUS_USB)


def has_rel_xy(dev):
    rel = dev.capabilities().get(e.EV_REL, [])
    return e.REL_X in rel and e.REL_Y in rel


def has_keyboard(dev):
    return any(1 <= c < 0x100 for c in dev.capabilities().get(e.EV_KEY, []))


PASS_MODS = frozenset((e.KEY_LEFTALT, e.KEY_RIGHTALT, e.KEY_LEFTMETA, e.KEY_RIGHTMETA))


class KeyboardShield:
    """Mientras juegas con la ventana del juego enfocada, las teclas no deben llegar a scrcpy
    (que tiene el teclado activo para el chat). Se 'agarran' los teclados (EVIOCGRAB) y solo se
    reenvian por un teclado virtual Alt/Super y lo que se presione con ellos: Alt+Tab, Alt+O de scrcpy
    y los atajos de kb2pad siguen funcionando (con Alt, scrcpy no le manda nada al celular)."""

    def __init__(self, keyboards):
        self.kbds = list(keyboards)
        self.grabbed = False
        self.held = set()          # teclas fisicas presionadas ahora
        self.vpressed = set()      # teclas que el teclado virtual tiene presionadas
        self.vkbd = None
        try:
            keys = sorted(c for c in e.KEY if 1 <= c < 0x100)
            self.vkbd = UInput({e.EV_KEY: keys}, name="kb2pad passthrough keyboard")
        except OSError as exc:
            log(f"Aviso: sin teclado virtual de paso ({exc}); el escudo del teclado queda apagado")

    def remove(self, dev):
        if dev in self.kbds:
            self.kbds.remove(dev)

    def key(self, dev, ev):
        """Evento de un teclado (antes de pasarlo al mapper)."""
        if dev not in self.kbds:
            return
        if ev.value == 1:
            mods = any(m in self.held for m in PASS_MODS)
            self.held.add(ev.code)
            if self.grabbed and (ev.code in PASS_MODS or mods):
                self._emit(ev.code, 1)
        elif ev.value == 0:
            self.held.discard(ev.code)
            if ev.code in self.vpressed:
                self._emit(ev.code, 0)
        elif ev.value == 2 and ev.code in self.vpressed:
            self._emit(ev.code, 2)

    def _emit(self, code, value):
        if self.vkbd is None:
            return
        self.vkbd.write(e.EV_KEY, code, value)
        self.vkbd.syn()
        if value == 1:
            self.vpressed.add(code)
        elif value == 0:
            self.vpressed.discard(code)

    def update(self, want):
        want = bool(want) and self.vkbd is not None
        if want and not self.grabbed:
            if self.held:
                return             # esperar a que sueltes todo, si no el escritorio se queda con teclas pegadas
            for d in self.kbds:
                try:
                    d.grab()
                except OSError:
                    pass
            self.grabbed = True
        elif not want and self.grabbed:
            for d in self.kbds:
                try:
                    d.ungrab()
                except OSError:
                    pass
            for code in list(self.vpressed):
                self._emit(code, 0)
            self.grabbed = False

    def close(self):
        self.update(False)
        if self.vkbd is not None:
            self.vkbd.close()


def find_devices():
    """Todos los teclados y mouse (no depende de la config, asi recargar no reabre nada)."""
    devs = []
    for path in list_devices():
        dev = InputDevice(path)
        if "kb2pad" in dev.name:
            dev.close()
            continue
        keys = dev.capabilities().get(e.EV_KEY, [])
        has_kb = any(1 <= c < 0x100 for c in keys)
        has_mouse_btn = any(e.BTN_LEFT <= c <= e.BTN_TASK for c in keys)
        if has_kb or has_mouse_btn or has_rel_xy(dev):
            devs.append(dev)
        else:
            dev.close()
    return devs

class StdinCommands:
    """Lee comandos por stdin sin bloquear. Solo si stdin es tuberia o terminal."""

    def __init__(self):
        self.fd = None
        self.buf = b""
        self.is_pipe = False
        try:
            mode = os.fstat(0).st_mode
        except OSError:
            return
        if stat.S_ISFIFO(mode) or os.isatty(0):
            self.fd = 0
            self.is_pipe = stat.S_ISFIFO(mode)

    def read(self):
        """Regresa (lista_de_comandos, eof)."""
        try:
            data = os.read(self.fd, 4096)
        except OSError:
            data = b""
        if not data:
            self.fd = None
            return [], True
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        return [ln.decode(errors="ignore").strip().lower() for ln in lines if ln.strip()], False


# ================================================================ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="kb2pad: teclado + mouse -> control Xbox 360 virtual")
    ap.add_argument("--config", default=str(C.CONFIG_PATH), help="ruta del config.json")
    ap.add_argument("--debug", action="store_true", help="imprime cada tecla/boton presionado")
    args = ap.parse_args(argv)
    path = Path(args.config).expanduser()

    try:
        raw, errors, warnings = load_engine_config(path)
    except ValueError as exc:
        log(f"ERROR: {exc}")
        sys.exit(2)
    for w in warnings:
        log(f"Aviso: {w}")
    if errors:
        for err in errors:
            log(f"ERROR: {err}")
        sys.exit(2)
    cfg = EngineConfig(raw)

    devs = find_devices()
    if not devs:
        log("ERROR: no encontre teclado ni mouse. Faltan permisos (corre con sudo o configura el grupo input).")
        sys.exit(1)
    mice = [d for d in devs if has_rel_xy(d)]

    try:
        ui = build_pad()
    except OSError as exc:
        log(f"ERROR: no pude crear el control virtual ({exc}). Revisa permisos de /dev/uinput.")
        sys.exit(1)

    log(f"Config: {path}")
    log(f"Leyendo {len(devs)} dispositivos ({len(mice)} mouse)")
    log(f"Control virtual creado: {PAD_NAME}")
    log(f"Config cargada: {summary(raw)}")
    log("ACTIVO")

    mapper = Mapper(ui, mice, cfg, debug=args.debug)
    shield = KeyboardShield(d for d in devs if has_keyboard(d) and not has_rel_xy(d))
    game_focused = False
    fds = {d.fd: d for d in devs}
    cmds = StdinCommands()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    last_mtime_check = time.monotonic()

    def reload(reason):
        nonlocal mtime
        try:
            mtime = path.stat().st_mtime
        except OSError:
            pass
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

    running = True
    try:
        while running and fds:
            timeout = mapper.service()
            timeout = 0.5 if timeout is None else min(timeout, 0.5)
            rlist = list(fds) + ([cmds.fd] if cmds.fd is not None else [])
            ready, _, _ = select.select(rlist, [], [], timeout)

            for fd in ready:
                if fd == cmds.fd:
                    lines, eof = cmds.read()
                    if eof and cmds.is_pipe:
                        running = False
                    for cmd in lines:
                        if cmd == "quit":
                            running = False
                        elif cmd == "reload":
                            reload("guardado")
                        elif cmd in ("debug on", "debug off"):
                            mapper.debug = cmd.endswith("on")
                            log("Debug de teclas " + ("activado" if mapper.debug else "desactivado"))
                        elif cmd in ("focus on", "focus off"):
                            game_focused = cmd.endswith("on")
                    continue
                dev = fds.get(fd)
                if dev is None:
                    continue
                try:
                    events = list(dev.read())
                except OSError:
                    log(f"Se desconecto: {dev.name}")
                    del fds[fd]
                    if dev in mice:
                        mice.remove(dev)
                    shield.remove(dev)
                    continue
                for ev in events:
                    if ev.type == e.EV_KEY:
                        shield.key(dev, ev)
                    mapper.handle(dev, ev)

            shield.update(game_focused and mapper.enabled and not mapper.chat)

            now = time.monotonic()
            if now - last_mtime_check >= 0.5:
                last_mtime_check = now
                try:
                    current = path.stat().st_mtime
                except OSError:
                    current = mtime
                if current != mtime:
                    reload("archivo modificado")
    except KeyboardInterrupt:
        pass
    finally:
        shield.close()
        mapper.release_all()
        mapper.mouselook = False
        mapper.update_grab()
        mapper.push()
        ui.close()
        log("Control virtual cerrado.")


if __name__ == "__main__":
    main()

