"""
kb2pad - configuracion compartida entre la GUI (app.py) y el motor (engine.py).

El archivo vive en ~/.config/kb2pad/config.json y se puede editar a mano.
Las teclas se escriben con su nombre de evdev: KEY_Q, KEY_LEFTCTRL, BTN_SIDE...
Las salidas del control son: A B X Y LB RB LT RT BACK START L3 R3
"""
import copy
import json
import os
import re
import shlex
import shutil
from pathlib import Path

from keycodes import e

IS_WINDOWS = os.name == "nt"
APP_NAME = "kb2pad-dock"
APP_VERSION = "0.4.0"

if IS_WINDOWS:
    CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "kb2pad"
else:
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "kb2pad"
CONFIG_PATH = CONFIG_DIR / "config.json"

# ---------------------------------------------------------------- salidas
OUTPUTS = ["A", "B", "X", "Y", "LB", "RB", "LT", "RT", "BACK", "START", "L3", "R3",
           "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"]
OUTPUT_LABELS = {
    "BACK": "Select",
    "START": "Start",
    "L3": "L3",
    "R3": "R3",
    "DPAD_UP": "D-pad ↑",
    "DPAD_DOWN": "D-pad ↓",
    "DPAD_LEFT": "D-pad ←",
    "DPAD_RIGHT": "D-pad →",
}


def output_label(name):
    return OUTPUT_LABELS.get(name, name)


# ---------------------------------------------------------------- entradas
MOUSE_BUTTONS = ["BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE", "BTN_SIDE", "BTN_EXTRA",
                 "BTN_FORWARD", "BTN_BACK", "BTN_TASK"]
# La rueda del mouse como "teclas": cada muesca es un toque corto.
WHEEL_CODES = {"WHEEL_UP": 0x1000, "WHEEL_DOWN": 0x1001, "WHEEL_LEFT": 0x1002, "WHEEL_RIGHT": 0x1003}
WHEEL_BY_CODE = {v: k for k, v in WHEEL_CODES.items()}

FRIENDLY = {
    "BTN_LEFT": "Click izq", "BTN_RIGHT": "Click der", "BTN_MIDDLE": "Click rueda",
    "BTN_SIDE": "Lateral 1", "BTN_EXTRA": "Lateral 2", "BTN_FORWARD": "Mouse adelante",
    "BTN_BACK": "Mouse atras", "BTN_TASK": "Mouse extra",
    "WHEEL_UP": "Rueda arriba", "WHEEL_DOWN": "Rueda abajo",
    "WHEEL_LEFT": "Rueda izq", "WHEEL_RIGHT": "Rueda der",
    "KEY_LEFTCTRL": "Ctrl izq", "KEY_RIGHTCTRL": "Ctrl der",
    "KEY_LEFTSHIFT": "Shift izq", "KEY_RIGHTSHIFT": "Shift der",
    "KEY_LEFTALT": "Alt izq", "KEY_RIGHTALT": "Alt der",
    "KEY_LEFTMETA": "Win" if IS_WINDOWS else "Super",
    "KEY_SPACE": "Espacio", "KEY_CAPSLOCK": "Bloq Mayus", "KEY_ESC": "Esc",
    "KEY_TAB": "Tab", "KEY_ENTER": "Enter", "KEY_BACKSPACE": "Retroceso",
    "KEY_UP": "Flecha arriba", "KEY_DOWN": "Flecha abajo",
    "KEY_LEFT": "Flecha izq", "KEY_RIGHT": "Flecha der",
    "KEY_GRAVE": "` (grave)", "KEY_MINUS": "-", "KEY_EQUAL": "=",
    "KEY_SEMICOLON": "; / N", "KEY_APOSTROPHE": "'", "KEY_COMMA": ",", "KEY_DOT": ".",
    "KEY_SLASH": "/", "KEY_BACKSLASH": "\\",
}


def _key_names():
    names = set()
    for _code, n in e.KEY.items():
        for nm in (n if isinstance(n, (list, tuple)) else [n]):
            if nm.startswith("KEY_") and nm not in ("KEY_RESERVED", "KEY_MAX", "KEY_CNT"):
                names.add(nm)
    return sorted(names)


INPUT_NAMES = _key_names() + MOUSE_BUTTONS + list(WHEEL_CODES)
_INPUT_SET = set(INPUT_NAMES)


def is_valid_input(name):
    return name in _INPUT_SET


def input_code(name):
    if not is_valid_input(name):
        raise ValueError(f"tecla desconocida: {name}")
    if name in WHEEL_CODES:
        return WHEEL_CODES[name]
    return e.ecodes[name]


def code_to_name(code):
    """Codigo evdev de teclado -> nombre KEY_* (None si no existe)."""
    n = e.KEY.get(code)
    if n is None:
        return None
    for nm in (n if isinstance(n, (list, tuple)) else [n]):
        if nm.startswith("KEY_"):
            return nm
    return None


def input_label(name):
    if name in FRIENDLY:
        return FRIENDLY[name]
    if name.startswith("KEY_"):
        rest = name[4:]
        return rest if len(rest) <= 3 else rest.capitalize()
    return name


# ---------------------------------------------------------------- defaults
def binding(inp, outs, note="", modifier=None, radial=False, hold=0.0, camera_only=False):
    return {
        "input": inp,
        "outputs": list(outs),
        "modifier": list(modifier or []),
        "radial": radial,
        "radial_hold": hold,
        "camera_only": camera_only,
        "note": note,
    }


DEFAULT_MODE = "Por defecto"     # solo para leer configs viejas (antes era la capa base)

# Teclas que se usan igual con cualquier arma (las que no cambian en combate)
COMMON_BINDINGS = [
    binding("KEY_SPACE", ["A"], "Saltar"),
    binding("KEY_Q", ["RB"], "Mirar al frente / eslinga; sostener = menu radial",
            radial=True, hold=0.20),
    binding("KEY_F", ["B"], "Golpe fuerte"),
    binding("BTN_RIGHT", ["B"], "Golpe fuerte (click der)"),
    binding("KEY_R", ["RT"], "Cubrirse"),
    binding("BTN_LEFT", ["Y"], "Golpe normal (click izq)", camera_only=True),
    binding("KEY_C", ["Y", "B"], "Golpe fuerte + normal"),
    binding("KEY_E", ["X"], "Consumir objeto"),
    binding("KEY_LEFTCTRL", ["LB"], "Menu radial de objetos", radial=True, hold=0.0),
    binding("KEY_LEFTSHIFT", ["L3"], "Correr"),
    binding("BTN_EXTRA", ["RT"], "Cubrirse (lateral 2)"),
    binding("BTN_SIDE", ["A"], "Eslinga (lateral 1)", modifier=["RB"]),
    binding("BTN_MIDDLE", ["A"], "Disparar eslinga (click rueda)", modifier=["RB"]),
    binding("KEY_U", ["LT"], "LT"),
    binding("KEY_O", ["RT"], "RT"),
    binding("KEY_1", ["Y"], "Compañero (LT+Y)", modifier=["LT"]),
    binding("KEY_2", ["B"], "Compañero (LT+B)", modifier=["LT"]),
    binding("KEY_3", ["X"], "Compañero (LT+X)", modifier=["LT"]),
    binding("KEY_4", ["A"], "Especial (LT+A)", modifier=["LT"]),
    binding("KEY_5", ["LT"], "Especial Felyne (LT+RT)", modifier=["RT"]),
    binding("KEY_G", ["LT"], "Fabricar", modifier=["DPAD_UP"]),
    binding("WHEEL_UP", ["DPAD_LEFT"], "D-pad izq (rueda arriba)", camera_only=True),
    binding("WHEEL_DOWN", ["DPAD_RIGHT"], "D-pad der (rueda abajo)", camera_only=True),
    binding("KEY_T", ["RB"], "Preparar trampa", modifier=["B"]),
    binding("KEY_M", ["BACK"], "Select"),
    binding("KEY_ESC", ["START"], "Start / menu"),
]
DEFAULT_BINDINGS = COMMON_BINDINGS       # nombre viejo

# Lo que cada plantilla cambia respecto a las teclas comunes (solo para armar los valores
# por defecto: despues cada modo es una plantilla completa y se edita como quieras).
_TEMPLATE_CHANGES = {
    "Espada": [],
    "Ballesta": [
        binding("BTN_LEFT", ["RT"], "Disparar (click izq)", camera_only=True),
        binding("BTN_RIGHT", ["Y"], "Cubrirse (click der)"),
        binding("KEY_R", ["RB"], "Recargar (LT + RB)", modifier=["LT"]),
        binding("KEY_V", ["B"], "Modo misil"),
    ],
    "Arco": [
        binding("BTN_LEFT", ["RT"], "Disparar (click izq)", camera_only=True),
        binding("BTN_RIGHT", ["Y"], "Y (click der)"),
        binding("KEY_R", ["Y"], "Y"),
    ],
}
_TEMPLATE_INFO = {"Espada": ("KEY_1", "sword"), "Ballesta": ("KEY_2", "crossbow"),
                  "Arco": ("KEY_3", "bow")}

ICON_KINDS = ["gamepad", "sword", "crossbow", "bow", "letter"]


def binding_key(b):
    """Identidad de una asignacion: tecla + 'solo mouse-camara'."""
    return (b.get("input", ""), bool(b.get("camera_only")))


def _apply_changes(base, changes):
    """Copia de 'base' con 'changes' encima: reemplaza en su lugar la misma tecla y agrega las nuevas.
    Un cambio sin salidas quita esa tecla."""
    by_key = {}
    for c in changes:
        by_key.setdefault(binding_key(c), []).append(c)
    out, used = [], set()
    for b in base:
        k = binding_key(b)
        if k in by_key:
            if k not in used:
                out += [copy.deepcopy(c) for c in by_key[k] if c.get("outputs")]
                used.add(k)
        else:
            out.append(copy.deepcopy(b))
    for k, cs in by_key.items():
        if k not in used:
            out += [copy.deepcopy(c) for c in cs if c.get("outputs")]
    return out


def template_names():
    return list(_TEMPLATE_CHANGES)


def default_mode(name):
    """La plantilla de fabrica con ese nombre (Espada, Ballesta, Arco), o None."""
    if name not in _TEMPLATE_CHANGES:
        return None
    hotkey, icon = _TEMPLATE_INFO[name]
    return {"name": name, "hotkey": hotkey, "icon": icon, "icon_file": "",
            "bindings": _apply_changes(COMMON_BINDINGS, _TEMPLATE_CHANGES[name])}


def guess_icon(name):
    """Icono por defecto para un modo nuevo, segun su nombre (palabras completas)."""
    words = set(re.findall(r"[a-záéíóúñ]+", (name or "").lower()))
    if words & {"ballesta", "ballestas", "artillero", "artilleria", "artillería"}:
        return "crossbow"
    if words & {"arco", "arquero"}:
        return "bow"
    if words & {"espada", "mandoble", "cuerpo", "katana", "espadas"}:
        return "sword"
    return "letter"


CONFIG_VERSION = 5

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "special": {
        "pause": "KEY_F12",
        "mouselook": "KEY_CAPSLOCK",
        "alt_blocks": True,          # con Alt presionado no se manda nada al juego
        "hide_cursor": True,         # ocultar el cursor con el mouse como camara
        "chat": "KEY_T",             # Alt + T: modo chat (el teclado deja de ser control)
        "mode_back": "KEY_Q",        # Alt + Q: sale del chat al modo que tenias (fuera del chat: modo de inicio)
        "chat_window": True,         # chat activado: la ventana de scrcpy lleva teclado (kb2pad lo bloquea al jugar)
        "chat_keyboard": "uhid",     # uhid = teclado fisico (Android oculta su teclado); sdk = teclado del cel
        "profile_toggle": "KEY_P",   # Alt + P: alterna entre los dos perfiles de video (reabre la ventana)
    },
    "sticks": {   # (arriba, abajo, izquierda, derecha)
        "move": ["KEY_W", "KEY_S", "KEY_A", "KEY_D"],
        "camera": ["KEY_I", "KEY_K", "KEY_J", "KEY_L"],
        "dpad": ["KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"],
    },
    # Cada modo es una plantilla completa: Alt + hotkey lo activa.
    "modes": [default_mode(n) for n in template_names()],
    "start_mode": "Espada",
    "combo_delay": 0.05,
    "mouse": {
        "full_speed": 1500.0,
        "anti_deadzone": 0.20,
        "smoothing": 0.5,
        "invert_y": False,
    },
    "radial": {
        "radius": 250.0,
        "deadzone": 0.35,
        "release_delay": 0.06,
    },
    "scrcpy": {
        "scrcpy_dir": "",                   # carpeta de scrcpy/adb (vacio = buscar en el PATH)
        "serial": "",
        "codec": "h265",
        "bitrate": "30M",
        "max_fps": 120,
        "no_mipmaps": True,
        "stay_awake": True,
        "borderless": True,
        "set_geometry": True,
        "x": 0,
        "y": 96,
        "width": 1920,
        "height": 887,
        "force_x11": False,
        "extra_args": "",
        "max_size": 0,                      # lado mayor del video en px (0 = resolucion original)
        "no_audio": False,                  # sin audio en la PC (suena el celular)
        "encoder": "",                      # codificador del celular ("" = el de por defecto)
        "encoder_codec": "",                # codec al que pertenece ese codificador
        # optimizacion del codificador (avanzado, apagado por defecto)
        "lowlat_enabled": False,
        "lowlat_realtime": False,           # priority=0, latency=1 (scrcpy < 4.0; despues ya viene)
        "lowlat_bframes": False,            # max-bframes=0
        "lowlat_qcom": False,               # vendor.qti-ext-enc-low-latency.enable=1
        "lowlat_mtk": False,                # mtk.ext.venc.scenario.based.sdk.mode=1
        "soc": "",                          # chip detectado (texto)
        "soc_vendor": "",                   # qcom | mtk | exynos | tensor | unisoc | kirin | other
        "profile_a": "calidad",             # Alt + P alterna entre estos dos perfiles de video
        "profile_b": "maximo",
        "launch_app": True,                 # abre el juego en el cel antes de scrcpy
        "package": "com.garena.game.mho",
        "ask_on_start": True,               # preguntar: abrir una app o solo mostrar la pantalla
        "wait_landscape": True,             # espera a que el cel este en horizontal
        "keep_geometry": True,              # (viejo) ahora es rotate_fit
        "rotate_fit": "screen",             # al pasar a horizontal: screen = toda la pantalla,
                                            # fixed = posicion/tamaño fijos, off = no tocar
        "connection": "usb",                # usb | wifi
        "wifi_address": "",                 # ip:puerto del celular en modo red
    },
    "thermal": {
        "enabled": True,                    # leer la temperatura del celular mientras el juego esta abierto
        "interval": 5,                      # segundos entre lecturas
        "warn": 42.0,                       # grados (piel o bateria, la mas alta)
        "critical": 46.0,                   # notificacion del sistema
        "danger": 50.0,                     # notificacion de peligro + accion
        "danger_action": "stream",          # stream = cerrar la transmision; stream_game = y el juego; notify = solo avisar
        "notify": True,                     # notificaciones del sistema (solo critico y peligro)
        "tray_icon": True,                  # segundo icono en la bandeja con la temperatura
    },
    "hud": {
        "enabled": True,                    # cuadro con temperatura/bateria/FPS encima del juego
        "corner": "tl",                     # tl tr bl br
        "show_fps": True,                   # FPS del video que llegan a la PC (scrcpy --print-fps)
    },
}


ROTATE_FIT = {"screen": "Ocupar toda la pantalla", "fixed": "Usar la posicion y tamaño fijos",
              "off": "No tocar la ventana"}


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


# ---------------------------------------------------------------- modos
MODE_MODIFIERS = ("KEY_LEFTALT", "KEY_RIGHTALT")   # el atajo de modo es Alt + tecla


def find_mode(cfg, name):
    for m in cfg.get("modes") or []:
        if m.get("name") == name:
            return m
    return None


def mode_names(cfg):
    return [m.get("name", "") for m in cfg.get("modes") or []]


def effective_bindings(cfg, mode_name):
    """Las asignaciones de un modo (cada modo es una plantilla completa)."""
    m = find_mode(cfg, mode_name)
    return list(m.get("bindings") or []) if m else []


# ---------------------------------------------------------------- carga / guardado
def _migrate(out):
    """Configs viejas -> plantillas (v3).
    v1: una sola tabla 'bindings'.  v2: 'bindings' como base + modos con solo sus cambios."""
    base = _norm_bindings(out.get("bindings")) if "bindings" in out else None
    old_modes = [m for m in out.get("modes") or [] if isinstance(m, dict) and m.get("name")]
    if base is None:
        return
    if int(out.get("version") or 1) >= 2 and old_modes:
        new = []
        for m in old_modes:
            changes = _norm_bindings(m.get("bindings"))
            new.append({"name": m["name"], "hotkey": m.get("hotkey") or "",
                        "icon": m.get("icon") or guess_icon(m["name"]), "icon_file": "",
                        "bindings": _apply_changes(base, changes)})
        out["modes"] = new
    else:
        new = []
        for name in template_names():
            hotkey, icon = _TEMPLATE_INFO[name]
            new.append({"name": name, "hotkey": hotkey, "icon": icon, "icon_file": "",
                        "bindings": _apply_changes(base, _TEMPLATE_CHANGES[name])})
        out["modes"] = new
    if out.get("start_mode") == DEFAULT_MODE or not out.get("start_mode"):
        out["start_mode"] = out["modes"][0]["name"] if out["modes"] else "Espada"
    out.pop("bindings", None)
    sp = out.get("special") or {}
    for k in ("mode_default", "notify_mode", "notify_mouse", "notify_control"):
        sp.pop(k, None)


def _migrate_v4(out):
    """v3 -> v4: la recarga de la Ballesta de fabrica era LB + RB (es LT + RB) y
    'mantener tamaño al rotar' pasa a 'rotate_fit'."""
    for m in out.get("modes") or []:
        if not isinstance(m, dict) or m.get("name") != "Ballesta":
            continue
        for b in m.get("bindings") or []:
            if (isinstance(b, dict) and b.get("input") == "KEY_R" and list(b.get("modifier") or []) == ["LB"]
                    and list(b.get("outputs") or []) == ["RB"]):
                b["modifier"] = ["LT"]
                if b.get("note") in ("", None, "Recargar (LB + RB)"):
                    b["note"] = "Recargar (LT + RB)"
    sc = out.get("scrcpy")
    if isinstance(sc, dict) and "rotate_fit" not in sc and "keep_geometry" in sc:
        sc["rotate_fit"] = "screen" if sc.get("keep_geometry") else "off"


def _migrate_v5(out):
    """v4 -> v5: --max-size, --no-audio y --video-encoder pasan de 'argumentos extra' a sus campos."""
    sc = out.get("scrcpy")
    if not isinstance(sc, dict) or not sc.get("extra_args"):
        return
    try:
        tokens = shlex.split(sc["extra_args"])
    except ValueError:
        return
    keep, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        m = re.fullmatch(r"(?:--max-size=|-m)(\d+)", t)
        if m:
            sc["max_size"] = int(m.group(1))
        elif t in ("--max-size", "-m") and nxt and nxt.isdigit():
            sc["max_size"] = int(nxt)
            i += 1
        elif t == "--no-audio":
            sc["no_audio"] = True
        elif t.startswith("--video-encoder="):
            sc["encoder"], sc["encoder_codec"] = t.split("=", 1)[1], sc.get("codec", "h265")
        else:
            keep.append(t)
        i += 1
    sc["extra_args"] = shlex.join(keep)


def normalize(data):
    """Rellena lo que falte con los defaults (por si el archivo es viejo o se edito a mano)."""
    out = copy.deepcopy(data) if isinstance(data, dict) else {}
    old_version = int(out.get("version") or 1) if out else CONFIG_VERSION
    _migrate(out)
    if old_version < 4:
        _migrate_v4(out)
    if old_version < 5:
        _migrate_v5(out)
    base = default_config()
    for key, val in base.items():
        if key not in out:
            out[key] = copy.deepcopy(val)
        elif isinstance(val, dict) and isinstance(out[key], dict):
            for sk, sv in val.items():
                out[key].setdefault(sk, copy.deepcopy(sv))
    modes = []
    for m in out.get("modes") or []:
        if isinstance(m, dict) and m.get("name"):
            icon = m.get("icon") if m.get("icon") in ICON_KINDS else guess_icon(m["name"])
            modes.append({"name": str(m["name"]), "hotkey": m.get("hotkey") or "",
                          "icon": icon, "icon_file": m.get("icon_file") or "",
                          "bindings": _norm_bindings(m.get("bindings"))})
    if not modes:
        modes = copy.deepcopy(base["modes"])
    out["modes"] = modes
    out["version"] = CONFIG_VERSION
    sc = out["scrcpy"]
    if sc.get("rotate_fit") not in ROTATE_FIT:
        sc["rotate_fit"] = "screen"
    try:
        sc["max_size"] = max(0, int(sc.get("max_size") or 0))
    except (TypeError, ValueError):
        sc["max_size"] = 0
    if sc.get("connection") not in ("usb", "wifi"):
        sc["connection"] = "usb"
    if out.get("start_mode") not in mode_names(out):
        out["start_mode"] = modes[0]["name"]
    return out


def _norm_bindings(items):
    bl = []
    for b in items or []:
        if not isinstance(b, dict):
            continue
        nb = binding("", [])
        nb.update(b)
        nb["outputs"] = list(nb.get("outputs") or [])
        nb["modifier"] = list(nb.get("modifier") or [])
        bl.append(nb)
    return bl


def load_config(path=CONFIG_PATH, create=True):
    path = Path(path)
    if not path.exists():
        cfg = default_config()
        if create:
            save_config(cfg, path)
        return cfg
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} no es JSON valido: {exc}") from exc
    return normalize(data)


def save_config(cfg, path=CONFIG_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- validacion
def validate(cfg):
    """Regresa (errores, avisos). Con errores el motor no carga la config."""
    errors, warnings = [], []
    used = {}

    def check(name, where):
        if not is_valid_input(name):
            errors.append(f"{where}: tecla desconocida '{name}'")
            return False
        return True

    def use(key, where):
        used.setdefault(key, []).append(where)

    for k, label in (("pause", "Pausa"), ("mouselook", "Mouse-camara")):
        n = cfg["special"].get(k, "")
        if check(n, f"Tecla especial {label}"):
            use(n, f"especial {label}")

    hotkeys, names = {}, set()
    for k, label in (("chat", "Chat"), ("mode_back", "Volver de modo"), ("profile_toggle", "Perfil de video")):
        hk = cfg["special"].get(k) or ""
        if hk and check(hk, f"Atajo {label}"):
            if hk in hotkeys:
                errors.append(f"Alt + {input_label(hk)} es el atajo de '{hotkeys[hk]}' y de '{label}'")
            hotkeys[hk] = label
    if not cfg.get("modes"):
        errors.append("Tiene que haber al menos un modo")
    for m in cfg.get("modes") or []:
        name = m.get("name", "").strip()
        if not name:
            errors.append("Hay un modo sin nombre")
        elif name in names:
            errors.append(f"Hay dos modos llamados '{name}'")
        names.add(name)
        hk = m.get("hotkey", "")
        if hk and check(hk, f"Atajo del modo {name}"):
            if hk in hotkeys:
                errors.append(f"Alt + {input_label(hk)} es el atajo de '{hotkeys[hk]}' y de '{name}'")
            hotkeys[hk] = name

    dirs = ("arriba", "abajo", "izquierda", "derecha")
    for sk, label in (("move", "Movimiento"), ("camera", "Camara"), ("dpad", "D-pad")):
        keys = cfg["sticks"].get(sk) or []
        if len(keys) != 4:
            errors.append(f"{label}: se necesitan 4 teclas")
            continue
        for n, d in zip(keys, dirs):
            if check(n, f"{label} {d}"):
                use(n, f"{label} {d}")

    for m in cfg.get("modes") or []:
        mname = m.get("name")
        mused = {k: list(v) for k, v in used.items()}       # especiales y sticks valen en todos
        for i, b in enumerate(m.get("bindings") or [], 1):
            where = f"{mname}: asignacion {i} ({b.get('note') or b.get('input')})"
            inp = b.get("input", "")
            if check(inp, where):
                mused.setdefault(inp + ("#cam" if b.get("camera_only") else ""), []).append(where)
            if not b.get("outputs"):
                errors.append(f"{where}: no tiene salida")
            for o in list(b.get("outputs", [])) + list(b.get("modifier", [])):
                if o not in OUTPUTS:
                    errors.append(f"{where}: salida desconocida '{o}'")
            if b.get("modifier") and b.get("radial"):
                warnings.append(f"{where}: un combo no puede ser radial; se ignora el radial")
            if b.get("camera_only") and (b.get("modifier") or b.get("radial")):
                warnings.append(f"{where}: 'solo mouse-camara' ignora combo y radial")
            try:
                if float(b.get("radial_hold", 0)) < 0:
                    errors.append(f"{where}: espera del radial negativa")
            except (TypeError, ValueError):
                errors.append(f"{where}: espera del radial no es un numero")
        for key, wheres in mused.items():
            if len(wheres) > 1 and any(w.startswith(f"{mname}:") for w in wheres):
                warnings.append(f"'{input_label(key.split('#')[0])}' se usa en varios lugares: "
                                + "; ".join(wheres))

    for key, wheres in used.items():
        if len(wheres) > 1:
            name = key.split("#")[0]
            warnings.append(f"'{input_label(name)}' se usa en varios lugares: " + "; ".join(wheres))

    for section, field in (("mouse", "full_speed"), ("radial", "radius")):
        try:
            if float(cfg[section][field]) <= 0:
                errors.append(f"{section}.{field} debe ser mayor que 0")
        except (TypeError, ValueError, KeyError):
            errors.append(f"{section}.{field} no es un numero")

    try:
        shlex.split(cfg["scrcpy"].get("extra_args", ""))
    except ValueError as exc:
        errors.append(f"scrcpy: argumentos extra invalidos ({exc})")
    th = cfg.get("thermal") or {}
    try:
        if not float(th.get("warn", 42)) < float(th.get("critical", 46)) < float(th.get("danger", 50)):
            warnings.append("Temperatura: los limites deben ir de menor a mayor (aviso < critico < peligro)")
    except (TypeError, ValueError):
        errors.append("Temperatura: los limites no son numeros")
    extra = cfg["scrcpy"].get("extra_args", "")
    for flag, field in (("--max-size", "Resolucion maxima"), ("--no-audio", "Sin audio"),
                        ("--video-encoder", "Codificador")):
        if flag in extra:
            warnings.append(f"scrcpy: '{flag}' en argumentos extra; usa el campo '{field}' de la pestaña Juego")
    if cfg["scrcpy"].get("connection") == "wifi" and not cfg["scrcpy"].get("wifi_address", "").strip():
        warnings.append("Modo red sin direccion IP: se usara el serial/cable")

    return errors, warnings


# ---------------------------------------------------------------- scrcpy
SCRCPY_FIXED = ["--mouse=sdk", "--mouse-bind=----:----", "--gamepad=uhid"]


def tool_path(sc, name):
    """Ruta de scrcpy/adb: dentro de la carpeta configurada si existe ahi, si no el del PATH."""
    exe = name + (".exe" if IS_WINDOWS else "")
    folder = (sc or {}).get("scrcpy_dir") or ""
    if folder:
        cand = Path(folder).expanduser() / exe
        if cand.is_file():
            return str(cand)
    return shutil.which(name) or name


def tool_exists(sc, name):
    p = tool_path(sc, name)
    return Path(p).is_file() or shutil.which(p) is not None


def wifi_address(sc):
    """ip:puerto normalizado ('' si no hay). Sin puerto se usa el 5555."""
    addr = (sc.get("wifi_address") or "").strip()
    if not addr:
        return ""
    if ":" not in addr:
        addr += ":5555"
    return addr


def effective_serial(sc):
    """El serial que se le pasa a adb/scrcpy: la IP en modo red, si no el serial del cable."""
    if sc.get("connection") == "wifi" and wifi_address(sc):
        return wifi_address(sc)
    return (sc.get("serial") or "").strip()


def build_scrcpy_cmd(sc, window=None, version=None, keyboard="disabled", print_fps=False):
    """window: (x, y, w, h) para abrir la ventana ahi (si no, la posicion fija si esta activada).
    version: (mayor, menor) de scrcpy; desde la 4.0 la ventana guarda la proporcion del video y no
    deja ocupar toda la pantalla si no se le quita ese candado."""
    cmd = [tool_path(sc, "scrcpy")]
    serial = effective_serial(sc)
    if serial:
        cmd += ["-s", serial]
    cmd += [f"--keyboard={keyboard}"] + SCRCPY_FIXED
    cmd += [f"--video-codec={sc['codec']}",
            f"--video-bit-rate={sc['bitrate']}",
            f"--max-fps={int(sc['max_fps'])}"]
    if sc.get("encoder") and sc.get("encoder_codec") == sc["codec"]:
        cmd.append(f"--video-encoder={sc['encoder']}")
    if int(sc.get("max_size") or 0) > 0:
        cmd.append(f"--max-size={int(sc['max_size'])}")
    if sc.get("no_audio"):
        cmd.append("--no-audio")
    if print_fps and "--print-fps" not in (sc.get("extra_args") or ""):
        cmd.append("--print-fps")
    if sc.get("no_mipmaps"):
        cmd.append("--no-mipmaps")
    if sc.get("stay_awake"):
        cmd.append("--stay-awake")
    if sc.get("borderless"):
        cmd.append("--window-borderless")
    if window is None and sc.get("set_geometry"):
        window = (sc["x"], sc["y"], sc["width"], sc["height"])
    if window is not None:
        x, y, w, h = (int(v) for v in window)
        cmd += [f"--window-x={x}", f"--window-y={y}", f"--window-width={w}", f"--window-height={h}"]
    extra = shlex.split(sc["extra_args"]) if sc.get("extra_args") else []
    if (version and tuple(version) >= (4, 0) and sc.get("rotate_fit") == "screen"
            and "--no-window-aspect-ratio-lock" not in extra):
        cmd.append("--no-window-aspect-ratio-lock")
    # opciones del codificador: las de la seccion avanzada + las que pusiste a mano, en un solo argumento
    user_opts, rest, i = [], [], 0
    while i < len(extra):
        t = extra[i]
        if t.startswith("--video-codec-options="):
            user_opts += [o for o in t.split("=", 1)[1].split(",") if o]
        elif t == "--video-codec-options" and i + 1 < len(extra):
            user_opts += [o for o in extra[i + 1].split(",") if o]
            i += 1
        else:
            rest.append(t)
        i += 1
    user_keys = {o.split("=", 1)[0].split(":", 1)[0] for o in user_opts}
    opts = user_opts + [o for o in codec_options(sc, version)
                        if o.split("=", 1)[0].split(":", 1)[0] not in user_keys]
    if opts:
        cmd.append("--video-codec-options=" + ",".join(opts))
    return cmd + rest


# ---------------------------------------------------------------- optimizacion del codificador
LOWLAT_OPTIONS = {
    # clave de config: (opciones, texto, advertencia)
    "lowlat_realtime": (["priority=0", "latency=1"], "Tiempo real (priority=0, latency=1)",
                        "Codifica con prioridad de tiempo real y entrega cada frame en cuanto lo tiene. "
                        "scrcpy 4.0 o mas reciente ya lo hace solo; con esas versiones no se manda."),
    "lowlat_bframes": (["max-bframes=0"], "Sin B-frames (max-bframes=0)",
                       "Los B-frames esperan al frame siguiente y agregan retraso. Casi todos los "
                       "codificadores de celular ya no los usan; el video puede pesar un poco mas."),
    "lowlat_qcom": (["vendor.qti-ext-enc-low-latency.enable=1"], "Qualcomm: modo de baja latencia",
                    "Recorta 1-2 frames segun las pruebas de los desarrolladores de scrcpy. Puede bajar la "
                    "calidad en movimiento (imagen con bloques), sobre todo en chips viejos, y calentar mas."),
    "lowlat_mtk": (["mtk.ext.venc.scenario.based.sdk.mode=1"], "MediaTek: modo conferencia",
                   "Modo de MediaTek que prioriza el retraso bajo. Solo existe en chips con su SDK de video "
                   "2.0; si el chip no lo tiene lo ignora. Puede bajar la calidad."),
}
SOC_NAMES = {"qcom": "Qualcomm Snapdragon", "mtk": "MediaTek", "exynos": "Samsung Exynos",
             "tensor": "Google Tensor", "unisoc": "Unisoc", "kirin": "HiSilicon Kirin", "other": "Desconocido"}


def codec_options(sc, version=None):
    """Opciones del codificador de la seccion avanzada (solo si esta activada)."""
    if not sc.get("lowlat_enabled"):
        return []
    opts = []
    for key, (values, _label, _warn) in LOWLAT_OPTIONS.items():
        if not sc.get(key):
            continue
        if key == "lowlat_realtime" and version and tuple(version) >= (4, 0):
            continue                      # ya viene en scrcpy 4.0+
        opts += values
    return opts


def recommended_lowlat(vendor, version=None):
    """Lo que 'Bajar latencia' activa segun el chip."""
    rec = {"lowlat_realtime": not (version and tuple(version) >= (4, 0)), "lowlat_bframes": True,
           "lowlat_qcom": vendor == "qcom", "lowlat_mtk": vendor == "mtk"}
    return rec


# ---------------------------------------------------------------- perfiles de video
PROFILES = {
    "calidad": ("Mejor calidad",
                "Se ve muy bien, pero con mas retraso. Para videos, mostrar la pantalla, juegos casuales o que "
                "no piden reacciones rapidas.",
                {"codec": "h265", "max_size": 0, "bitrate": "30M"}),
    "balanceado": ("Balanceado",
                   "Buena imagen con retraso moderado. Para la mayoria de los juegos sin combates exigentes.",
                   {"codec": "h265", "max_size": 1920, "bitrate": "20M"}),
    "rendimiento": ("Rendimiento",
                    "Menos retraso con buena imagen: h264, 1920 px y 16M, sin opciones avanzadas. Para juegos de "
                    "accion.",
                    {"codec": "h264", "max_size": 1920, "bitrate": "16M"}),
    "maximo": ("Maximo rendimiento",
               "El menor retraso: h264, 1920 px, 8M, codificador de hardware y las optimizaciones del codificador "
               "de tu chip. El celular trabaja mas y se calienta mas.",
               {"codec": "h264", "max_size": 1920, "bitrate": "8M"}),
}
PROFILE_RISKY = {"maximo"}


def profile_settings(name, sc, version=None, encoders=()):
    """Valores del perfil para la seccion scrcpy. encoders: [(codec, codificador, tipo)] del celular."""
    _label, _desc, base = PROFILES[name]
    out = dict(base)
    out.update({"encoder": "", "encoder_codec": "", "lowlat_enabled": False,
                **{k: False for k in LOWLAT_OPTIONS}})
    if name == "maximo":
        hw = [e for e in encoders if e[0] == "h264" and e[2] == "hw" and not e[1].startswith("c2.android")]
        if hw:
            out["encoder"], out["encoder_codec"] = hw[0][1], "h264"
        out["lowlat_enabled"] = True
        out.update(recommended_lowlat(sc.get("soc_vendor") or "other", version))
    return out


def current_profile(sc):
    """Nombre del perfil que coincide con los valores actuales, o '' (personalizado)."""
    for name, (_l, _d, base) in PROFILES.items():
        if all(str(sc.get(k)) == str(v) for k, v in base.items()):
            if bool(sc.get("lowlat_enabled")) == (name in PROFILE_RISKY):
                return name
    return ""


def detect_soc(props, encoders=()):
    """props: dict de getprop; encoders: nombres de codificadores. -> (fabricante, texto)."""
    p = {k: (v or "").strip() for k, v in (props or {}).items()}
    man = p.get("ro.soc.manufacturer", "").lower()
    model = p.get("ro.soc.model", "")
    plat = (p.get("ro.board.platform") or p.get("ro.hardware.chipname") or p.get("ro.hardware") or "").lower()
    vendor = None
    for keys, v in ((("qti", "qualcomm"), "qcom"), (("mediatek",), "mtk"), (("google",), "tensor"),
                    (("samsung",), "exynos"), (("unisoc", "spreadtrum"), "unisoc"), (("hisilicon",), "kirin")):
        if any(k in man for k in keys):
            vendor = v
            break
    if vendor is None and plat:
        if re.match(r"(msm|sdm|sm\d|qcom|kona|lahaina|taro|kalama|pineapple|sun|canoe|parrot|crow|holi|bengal|"
                    r"lito|trinket|atoll|yupik|cape|ukee|waipio|volcano|blair|cliffs)", plat):
            vendor = "qcom"
        elif re.match(r"mt\d|mt6|mt8", plat):
            vendor = "mtk"
        elif re.match(r"(gs\d|zuma|zumapro|laguna)", plat):
            vendor = "tensor"
        elif re.match(r"(exynos|s5e|universal)", plat):
            vendor = "exynos"
        elif re.match(r"(ums|sp\d|sc\d|t\d{3})", plat):
            vendor = "unisoc"
        elif re.match(r"(kirin|hi\d)", plat):
            vendor = "kirin"
    if vendor is None:
        names = " ".join(encoders).lower()
        for keys, v in ((("c2.qti", "omx.qcom"), "qcom"), (("c2.mtk", "omx.mtk"), "mtk"),
                        (("c2.exynos", "omx.exynos", "c2.sec"), "exynos"), (("sprd", "unisoc"), "unisoc"),
                        (("hisi",), "kirin")):
            if any(k in names for k in keys):
                vendor = v
                break
    vendor = vendor or "other"
    detail = " / ".join(x for x in (model, plat) if x)
    return vendor, SOC_NAMES[vendor] + (f" ({detail})" if detail else "")


def parse_encoders(text):
    """Salida de 'scrcpy --list-encoders' -> [(codec, codificador, tipo)] solo de video.
    tipo: hw, sw, hybrid o '' (Android < 10 no lo dice)."""
    out = []
    for m in re.finditer(r"--video-codec=(\S+)\s+--video-encoder=(\S+)(?:\s+\((hw|sw|hybrid)\))?", text):
        enc = (m.group(1), m.group(2), m.group(3) or "")
        if enc not in out:
            out.append(enc)
    return out


CHAT_KEYBOARDS = {"uhid": "Teclado fisico: Android oculta su teclado (recomendado)",
                  "sdk": "Teclado del celular en pantalla"}


def scrcpy_keyboard(special, shield_ok=True):
    """Teclado de la ventana de scrcpy. Con el chat activado lleva teclado (uhid o sdk) y kb2pad se
    traga las teclas mientras juegas; si no se puede proteger (o el chat esta apagado), sin teclado."""
    kb = (special or {}).get("chat_keyboard", "uhid")
    if not (special or {}).get("chat_window", True) or not shield_ok or kb not in CHAT_KEYBOARDS:
        return "disabled"
    return kb


def wayland_session():
    return not IS_WINDOWS and (os.environ.get("XDG_SESSION_TYPE") == "wayland"
                               or bool(os.environ.get("WAYLAND_DISPLAY")))


def scrcpy_env_overrides(sc, keyboard="disabled"):
    """X11 si se pide, o en Wayland si hay que acomodar la ventana o saber si tiene el foco (escudo del
    teclado): xdotool no ve ventanas Wayland. SDL3 (scrcpy 3.3+) lee SDL_VIDEO_DRIVER; SDL2 SDL_VIDEODRIVER."""
    x11 = sc.get("force_x11") or (wayland_session() and (sc.get("rotate_fit", "screen") != "off"
                                                         or keyboard != "disabled"))
    return {"SDL_VIDEODRIVER": "x11", "SDL_VIDEO_DRIVER": "x11"} if x11 else {}
