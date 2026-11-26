"""
kb2pad touch - toques en la pantalla del celular, junto al control virtual.

Un segundo scrcpy-server (solo control, sin video ni audio) recibe toques multi-dedo por un
socket. Lo usa el Mapper (core.py) para:
  - botones tactiles: una tecla, boton del mouse o combinacion (Click izq + Click der) toca un
    punto de la pantalla mientras se sostiene; un boton puede tener varias formas de activarse.
  - radial tactil: mientras el boton se sostiene, el mouse arrastra ese dedo (menu de objetos,
    fijar partes del monstruo).
  - mouse-camara por toque: con mouse-camara activado, el mouse arrastra un dedo en la zona de
    la camara en vez de mover el stick derecho.

Las posiciones se guardan de 0 a 1 sobre la pantalla del celular en horizontal.
"""
import math
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import config as C

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEVICE_JAR = "/data/local/tmp/kb2pad-touch.jar"

PID_CAM = 10
PID_BTN0 = 20               # botones: 20, 21, 22...

SETTLE_S = 0.04             # el dedo baja y espera ~2 frames antes de moverse (si no, el juego no ve el arrastre)
RESETTLE_S = 0.025          # igual, pero al recentrar la camara (mas corto para no cortar el giro)
CATCHUP = 1.5               # el dedo alcanza al mouse a lo mucho 1.5x la velocidad del mouse (sin brincos)
SEND_S = 0.004              # como maximo un movimiento cada 4 ms por dedo
CAM_IDLE_S = 0.12           # mouse quieto: se levanta el dedo de la camara
RELIFT_S = 0.016            # al recentrar: pausa (~1 frame) entre levantar y volver a poner el dedo
RELIFT_BACK = 0.8           # al recentrar, el dedo baja del lado contrario (fraccion del radio)
EDGE_MARGIN = 0.03          # modo vector: el dedo se recentra al acercarse a esta distancia del borde (fraccion del alto)

ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
MSG_INJECT_TOUCH = 2


def _log(msg):
    from core import log        # import tardio: core importa este modulo
    log(msg)


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        return r.returncode, (r.stdout or b"").decode(errors="ignore"), (r.stderr or b"").decode(errors="ignore")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", str(exc)


# ================================================================ conexion
class TouchError(RuntimeError):
    pass


def find_server_jar(scrcpy):
    """El scrcpy-server que trae tu scrcpy (tiene que ser de la misma version)."""
    cands = [os.environ.get("SCRCPY_SERVER_PATH")]
    exe = shutil.which(scrcpy) or scrcpy
    if exe and Path(exe).exists():
        d = Path(os.path.realpath(exe)).parent
        cands += [d / "scrcpy-server", d.parent / "share" / "scrcpy" / "scrcpy-server"]
    cands += ["/usr/share/scrcpy/scrcpy-server", "/usr/local/share/scrcpy/scrcpy-server"]
    for c in cands:
        if c and Path(c).is_file():
            return str(c)
    raise TouchError("no encontre scrcpy-server (va junto a scrcpy; o define SCRCPY_SERVER_PATH)")


def scrcpy_full_version(scrcpy):
    _code, out, err = _run([scrcpy, "--version"], timeout=8)
    m = re.search(r"scrcpy v?(\d+(?:\.\d+)+)", out + err)
    if not m:
        raise TouchError("no pude leer la version de scrcpy")
    return m.group(1)


def phone_size(adb, serial):
    """Tamaño de la pantalla en horizontal (ancho > alto)."""
    _code, out, err = _run(C_adb(adb, serial, "shell", "wm", "size"), timeout=8)
    m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(r"Physical size:\s*(\d+)x(\d+)", out)
    if not m:
        raise TouchError(f"no pude leer el tamaño de la pantalla ({(out + err).strip() or 'sin celular'})")
    a, b = int(m.group(1)), int(m.group(2))
    return max(a, b), min(a, b)


def C_adb(adb, serial, *args):
    return [adb, *(["-s", serial] if serial else []), *args]


class TouchClient:
    """scrcpy-server solo de control (otro scid, corre junto al scrcpy del juego)."""

    def __init__(self, adb, scrcpy, serial=""):
        self.adb, self.serial = adb, serial
        self.proc = self.sock = None
        self.port = None
        self.lock = threading.Lock()
        self.w, self.h = phone_size(adb, serial)
        version, jar = scrcpy_full_version(scrcpy), find_server_jar(scrcpy)
        code, _out, err = _run(C_adb(adb, serial, "push", jar, DEVICE_JAR), timeout=20)
        if code != 0:
            raise TouchError(f"adb push fallo: {err.strip()}")
        scid = random.randint(0, 0x7FFFFFFF)
        params = [version, f"scid={scid:08x}", "log_level=warn", "tunnel_forward=true",
                  "video=false", "audio=false", "control=true", "cleanup=false",
                  "send_device_meta=false", "clipboard_autosync=false"]
        shell = f"CLASSPATH={DEVICE_JAR} app_process / com.genymobile.scrcpy.Server " + " ".join(params)
        self.proc = subprocess.Popen(C_adb(adb, serial, "shell", shell), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=NO_WINDOW)
        threading.Thread(target=self._logs, daemon=True).start()

        for _ in range(5):
            port = random.randint(27300, 27999)
            if _run(C_adb(adb, serial, "forward", f"tcp:{port}", f"localabstract:scrcpy_{scid:08x}"))[0] == 0:
                self.port = port
                break
        if self.port is None:
            self.close()
            raise TouchError("adb forward fallo")
        for _ in range(100):
            if self.proc.poll() is not None:
                self.close()
                raise TouchError("el server de toques se cerro al arrancar (¿version de scrcpy-server distinta?)")
            s = socket.socket()
            try:
                s.settimeout(1.0)
                s.connect(("127.0.0.1", self.port))
                if s.recv(1):                       # byte "dummy": el server ya escucha
                    s.settimeout(None)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.sock = s
                    break
            except OSError:
                pass
            s.close()
            time.sleep(0.1)
        if not self.sock:
            self.close()
            raise TouchError("no pude conectar con el server de toques")
        threading.Thread(target=self._drain, daemon=True).start()

    def _logs(self):
        try:
            for raw in self.proc.stdout:
                line = raw.decode(errors="ignore").strip()
                if line:
                    _log(f"[toques] {line}")
        except (OSError, ValueError):
            pass

    def _drain(self):
        try:
            while self.sock and self.sock.recv(4096):
                pass
        except OSError:
            pass

    @property
    def alive(self):
        return self.sock is not None and self.proc is not None and self.proc.poll() is None

    def touch(self, action, pid, x, y):
        x = min(max(int(x), 0), self.w - 1)
        y = min(max(int(y), 0), self.h - 1)
        msg = struct.pack(">BBqiiHHHII", MSG_INJECT_TOUCH, action, pid, x, y, self.w, self.h,
                          0 if action == ACTION_UP else 0xFFFF, 0, 0)
        with self.lock:
            if self.sock:
                try:
                    self.sock.sendall(msg)
                except OSError:
                    self.sock = None

    def down(self, pid, x, y):
        self.touch(ACTION_DOWN, pid, x, y)

    def up(self, pid, x, y):
        self.touch(ACTION_UP, pid, x, y)

    def move(self, pid, x, y):
        self.touch(ACTION_MOVE, pid, x, y)

    def close(self):
        with self.lock:
            try:
                if self.sock:
                    self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self.port is not None:
            _run(C_adb(self.adb, self.serial, "forward", "--remove", f"tcp:{self.port}"), timeout=4)
            self.port = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


# ================================================================ configuracion
class TouchButton:
    def __init__(self, raw, index):
        self.pid = PID_BTN0 + index
        self.name = raw.get("name") or f"Toque {index + 1}"
        self.pos = (float(raw["pos"][0]), float(raw["pos"][1]))
        self.triggers = [frozenset(C.input_code(n) for n in chord)
                         for chord in raw.get("inputs") or [] if chord]
        self.radial = bool(raw.get("radial"))
        self.radial_r = float(raw.get("radial_r", 0.12))
        self.modes = set(raw.get("modes") or [])      # vacio = todos los modos

    def in_mode(self, mode):
        return not self.modes or mode in self.modes


class TouchConfig:
    def __init__(self, raw):
        t = raw.get("touch") or {}
        self.enabled = bool(t.get("enabled"))
        self.camera = bool(t.get("camera"))
        self.cam_pos = tuple(float(v) for v in (t.get("camera_pos") or (0.72, 0.45)))
        self.cam_radius = float(t.get("camera_radius", 0.10))
        self.sens = float(t.get("sensitivity", 1.0))
        self.smooth = min(0.95, max(0.0, float(t.get("camera_smooth", 0.5))))
        # drag = el dedo sigue lo que se movio el mouse; en el borde del radio se levanta y recentra
        # vector = el dedo sigue al mouse sin radio y nunca regresa presionado: se levanta solo cuando
        #          el mouse se detiene (o al llegar al borde de la pantalla)
        self.cam_mode = t.get("camera_mode") if t.get("camera_mode") in ("drag", "vector") else "drag"
        self.buttons = [TouchButton(b, i) for i, b in enumerate(t.get("buttons") or [])]
        sc = raw.get("scrcpy") or {}
        self.adb = C.tool_path(sc, "adb")
        self.scrcpy = C.tool_path(sc, "scrcpy")
        self.serial = C.effective_serial(sc)


# ================================================================ logica
class TouchLayer:
    """Estado de los dedos. Todo corre en el hilo del motor; solo la conexion va en otro hilo."""

    def __init__(self, raw, mode):
        self.cfg = TouchConfig(raw)
        self.mode = mode
        self.client = None
        self.connecting = False
        self.want = False            # la GUI pidio conectar (el juego esta abierto)
        self.held = set()            # entradas presionadas (codigos)
        self.consumed = set()        # entradas usadas por una combinacion, hasta soltarlas
        self.combo_on = set()
        self.active = set()          # pids de botones tocando
        self.suppressed = frozenset()
        self.rad = {}                # pid -> {"f" destino, "s" enviado, "t0", "sent", "in", "rate"}
        self.rad_order = []
        self.cam = None              # igual que rad + "last" y "relift" (dedo arriba hasta ese momento)
        self.debug = False
        self._gen = 0

    # ---------- conexion
    @property
    def ready(self):
        return self.cfg.enabled and self.client is not None and self.client.alive

    def connect(self):
        self.want = True
        if not self.cfg.enabled or self.ready or self.connecting:
            return
        self.connecting = True
        self._gen += 1
        gen, cfg = self._gen, self.cfg

        def run():
            try:
                client = TouchClient(cfg.adb, cfg.scrcpy, cfg.serial)
            except (TouchError, OSError) as exc:
                _log(f"Toques: no conecte ({exc})")
                client = None
            if client is not None and (gen != self._gen or not self.want):
                client.close()             # se cancelo mientras conectaba
                client = None
            if client is not None:
                self.client = client
                _log(f"Toques: conectado ({client.w}x{client.h})")
            self.connecting = False

        threading.Thread(target=run, daemon=True).start()

    def disconnect(self):
        self.want = False
        self._gen += 1
        self.release_all()
        if self.client is not None:
            self.client.close()
            self.client = None
            _log("Toques: desconectado")

    def close(self):
        self.disconnect()

    def set_config(self, raw, mode):
        self.release_all()
        old = self.cfg
        self.cfg = TouchConfig(raw)
        self.mode = mode
        if self.client is not None and (not self.cfg.enabled or (old.adb, old.serial) != (self.cfg.adb, self.cfg.serial)):
            self.client.close()
            self.client = None
        if self.want and self.cfg.enabled and self.client is None:
            self.connect()

    def set_mode(self, mode):
        self.mode = mode
        self._update()

    # ---------- coordenadas
    def _px(self, pos):
        c = self.client
        return pos[0] * c.w, pos[1] * c.h

    # ---------- botones
    def key(self, code, down):
        """Tecla/boton del mouse (ya filtrado por el Mapper: sin Alt, chat ni pausa)."""
        if down:
            self.held.add(code)
        else:
            self.held.discard(code)
            self.consumed.discard(code)
        self._update()

    def _update(self):
        if not self.ready:
            self.active, self.suppressed = set(), frozenset()
            return
        sat = []
        for b in self.cfg.buttons:
            if not b.in_mode(self.mode):
                continue
            for t in b.triggers:
                if not t <= self.held:
                    continue
                if t & self.consumed and t not in self.combo_on:
                    continue                  # tecla aun "usada" por una combinacion que ya se solto
                sat.append((b, t))
        active, combos, used = set(), set(), set()
        for b, t in sat:
            if not any(t < other for _, other in sat):      # la combinacion mas grande gana
                active.add(b.pid)
                used |= t
                if len(t) > 1:
                    combos.add(t)
        self.combo_on = combos
        for t in combos:
            self.consumed |= t
        self.suppressed = frozenset(used | self.consumed)

        c = self.client
        by_pid = {b.pid: b for b in self.cfg.buttons}
        for pid in active - self.active:
            b = by_pid[pid]
            if self.debug:
                _log(f"[toque] {b.name}" + (" (radial)" if b.radial else ""))
            x, y = self._px(b.pos)
            c.down(pid, x, y)
            if b.radial:
                now = time.monotonic()
                self.rad[pid] = {"f": [x, y], "s": [x, y], "t0": now, "sent": now}
                self.rad_order.append(pid)
                self.cam_release()            # el mouse pasa al radial
        for pid in self.active - active:
            b = by_pid.get(pid)
            st = self.rad.pop(pid, None)
            if pid in self.rad_order:
                self.rad_order.remove(pid)
            if st:
                c.up(pid, *st["s"])
            elif b:
                c.up(pid, *self._px(b.pos))
        self.active = active

    @property
    def radial_active(self):
        return bool(self.rad_order)

    # ---------- mouse
    def mouse(self, dx, dy, mouselook):
        """Movimiento del mouse. True si lo uso (radial tactil o camara por toque)."""
        if not self.ready:
            return False
        if self.rad_order:
            pid = self.rad_order[-1]
            b = next((x for x in self.cfg.buttons if x.pid == pid), None)
            st = self.rad.get(pid)
            if b and st:
                h = self.client.h
                bx, by = self._px(b.pos)
                fx, fy = st["f"][0] + dx * self.cfg.sens, st["f"][1] + dy * self.cfg.sens
                d, lim = math.hypot(fx - bx, fy - by), b.radial_r * h
                if d > lim:                    # se queda en el borde, no se levanta
                    fx, fy = bx + (fx - bx) / d * lim, by + (fy - by) / d * lim
                st["f"] = [fx, fy]
                st["in"] = st.get("in", 0.0) + math.hypot(dx, dy) * self.cfg.sens
            return True
        if mouselook and self.cfg.camera:
            now = time.monotonic()
            if self.cam is None:
                ax, ay = self._px(self.cfg.cam_pos)
                self.client.down(PID_CAM, ax, ay)
                self.cam = {"f": [ax, ay], "s": [ax, ay], "t0": now, "sent": now, "last": now, "relift": None}
            self.cam["f"][0] += dx * self.cfg.sens
            self.cam["f"][1] += dy * self.cfg.sens
            self.cam["in"] = self.cam.get("in", 0.0) + math.hypot(dx, dy) * self.cfg.sens
            self.cam["last"] = now
            return True
        return False

    def cam_release(self):
        if self.cam is not None and self.client is not None and self.cam["relift"] is None:
            self.client.up(PID_CAM, *self.cam["s"])
        self.cam = None

    # ---------- tiempo
    def service(self, now):
        """Manda los movimientos pendientes. Regresa cuanto esperar (None = nada pendiente)."""
        if not self.ready:
            if self.client is not None and not self.client.alive:
                _log("Toques: se perdio la conexion")
                self.client.close()
                self.client = None
                self.active, self.rad, self.rad_order, self.cam = set(), {}, [], None
                self.suppressed = frozenset()
            return None
        c = self.client
        waits = []
        for pid, st in self.rad.items():
            if st["f"] != st["s"]:
                w = self._due(st, now)
                if w <= 0:
                    self._step(st, now)
                    c.move(pid, *st["s"])
                else:
                    waits.append(w)
        cam = self.cam
        if cam is not None:
            waits.append(self._service_cam(cam, now))
        waits = [w for w in waits if w is not None]
        return min(waits) if waits else None

    def _service_cam(self, cam, now):
        c = self.client
        if cam["relift"] is not None:                 # recentrando: el dedo esta arriba
            if now < cam["relift"]:
                return cam["relift"] - now
            c.down(PID_CAM, *cam["s"])
            cam["relift"], cam["t0"], cam["sent"] = None, now - (SETTLE_S - RESETTLE_S), now
            return RESETTLE_S
        if cam["f"] != cam["s"]:
            w = self._due(cam, now)
            if w > 0:
                return w
            self._step(cam, now)
            c.move(PID_CAM, *cam["s"])
            ax, ay = self._px(self.cfg.cam_pos)
            vx, vy = cam["s"][0] - ax, cam["s"][1] - ay
            d, r = math.hypot(vx, vy), self.cfg.cam_radius * c.h
            if self.cfg.cam_mode == "vector":
                m = EDGE_MARGIN * c.h                 # sin radio: solo el borde de la pantalla lo recentra
                sx, sy = cam["s"]
                out = sx < m or sy < m or sx > c.w - 1 - m or sy > c.h - 1 - m
                back = 0.0                            # y vuelve a bajar en su punto
            else:
                out = d > r
                back = r * RELIFT_BACK                # baja del lado contrario: casi dos radios de recorrido
            if out and d > 0:
                c.up(PID_CAM, *cam["s"])
                rest = (cam["f"][0] - cam["s"][0], cam["f"][1] - cam["s"][1])
                ox = min(max(ax - vx / d * back, 0), c.w - 1)
                oy = min(max(ay - vy / d * back, 0), c.h - 1)
                cam["s"] = [ox, oy]
                cam["f"] = [ox + rest[0], oy + rest[1]]
                cam["relift"] = now + RELIFT_S
                return RELIFT_S
            return SEND_S if cam["f"] != cam["s"] else CAM_IDLE_S
        idle = cam["last"] + CAM_IDLE_S - now
        if idle <= 0:
            self.cam_release()
            return None
        return idle

    def _step(self, st, now):
        """Acerca el dedo a donde va el mouse sin brincar: un porcentaje del camino en cada envio, y
        nunca mas rapido que CATCHUP veces la velocidad del mouse (lo que se junto mientras el dedo
        esperaba sale parejo, no de golpe)."""
        dt = max(now - st["sent"], 1e-3)
        rate = st["in"] / dt if "in" in st else 0.0           # px/s del mouse desde el ultimo envio
        st["rate"] = rate if "rate" not in st else 0.6 * st["rate"] + 0.4 * rate
        st["in"] = 0.0
        fx, fy = st["f"]
        sx, sy = st["s"]
        dx, dy = fx - sx, fy - sy
        dist = math.hypot(dx, dy)
        if dist <= 1.0:
            st["s"] = [fx, fy]
        else:
            k = 1.0 - self.cfg.smooth
            step = dist * k
            cap = max(4.0, st["rate"] * SEND_S * CATCHUP)
            step = min(step, cap) if self.cfg.smooth > 0 else min(dist, max(cap, dist * 0.5))
            st["s"] = [sx + dx / dist * step, sy + dy / dist * step]
        st["sent"] = now

    @staticmethod
    def _due(st, now):
        return max(st["t0"] + SETTLE_S, st["sent"] + SEND_S) - now

    def release_all(self):
        c = self.client
        if c is not None:
            for pid in list(self.active):
                st = self.rad.get(pid)
                b = next((x for x in self.cfg.buttons if x.pid == pid), None)
                if st:
                    c.up(pid, *st["s"])
                elif b:
                    c.up(pid, *self._px(b.pos))
        self.cam_release()
        self.held.clear()
        self.consumed.clear()
        self.combo_on.clear()
        self.active = set()
        self.rad.clear()
        self.rad_order.clear()
        self.suppressed = frozenset()
