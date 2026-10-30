"""
kb2pad - configuracion compartida entre la GUI (app.py) y el motor (engine.py).

El archivo vive en ~/.config/kb2pad/config.json y se puede editar a mano.
Las teclas se escriben con su nombre de evdev: KEY_Q, KEY_LEFTCTRL, BTN_SIDE...
Las salidas del control son: A B X Y LB RB LT RT BACK START L3 R3
"""
import copy
import json
import os
import shlex
import shutil
from pathlib import Path

from keycodes import e

IS_WINDOWS = os.name == "nt"
APP_NAME = "kb2pad-dock"
APP_VERSION = "0.1.0"

if IS_WINDOWS:
    CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "kb2pad"
else:
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "kb2pad"
CONFIG_PATH = CONFIG_DIR / "config.json"

# ---------------------------------------------------------------- salidas
OUTPUTS = ["A", "B", "X", "Y", "LB", "RB", "LT", "RT", "BACK", "START", "L3", "R3"]
OUTPUT_LABELS = {
    "BACK": "Select",
    "START": "Start",
    "L3": "L3",
    "R3": "R3",
}


def output_label(name):
    return OUTPUT_LABELS.get(name, name)


# ---------------------------------------------------------------- entradas
MOUSE_BUTTONS = ["BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE", "BTN_SIDE", "BTN_EXTRA",
                 "BTN_FORWARD", "BTN_BACK", "BTN_TASK"]

FRIENDLY = {
    "BTN_LEFT": "Click izq", "BTN_RIGHT": "Click der", "BTN_MIDDLE": "Click rueda",
    "BTN_SIDE": "Lateral 1", "BTN_EXTRA": "Lateral 2", "BTN_FORWARD": "Mouse adelante",
    "BTN_BACK": "Mouse atras", "BTN_TASK": "Mouse extra",
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


INPUT_NAMES = _key_names() + MOUSE_BUTTONS
_INPUT_SET = set(INPUT_NAMES)


def is_valid_input(name):
    return name in _INPUT_SET


def input_code(name):
    if not is_valid_input(name):
        raise ValueError(f"tecla desconocida: {name}")
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


DEFAULT_CONFIG = {
    "version": 1,
    "special": {
        "pause": "KEY_F12",
        "mouselook": "KEY_CAPSLOCK",
    },
    "sticks": {   # (arriba, abajo, izquierda, derecha)
        "move": ["KEY_W", "KEY_S", "KEY_A", "KEY_D"],
        "camera": ["KEY_I", "KEY_K", "KEY_J", "KEY_L"],
        "dpad": ["KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"],
    },
    "bindings": [
        binding("KEY_SPACE", ["A"], "Saltar"),
        binding("KEY_Q", ["RB"], "Mirar al frente / eslinga; sostener = menu radial",
                radial=True, hold=0.20),
        binding("KEY_V", ["RB"], "RB sin radial (apuntar moviendo la camara)"),
        binding("KEY_F", ["B"], "Golpe fuerte"),
        binding("BTN_RIGHT", ["B"], "Golpe fuerte (click der)"),
        binding("KEY_R", ["Y"], "Golpe normal"),
        binding("BTN_LEFT", ["Y"], "Golpe normal (click izq)", camera_only=True),
        binding("KEY_C", ["Y", "B"], "Golpe fuerte + normal"),
        binding("KEY_E", ["X"], "Consumir objeto"),
        binding("KEY_LEFTCTRL", ["LB"], "Menu radial de objetos", radial=True, hold=0.0),
        binding("KEY_LEFTSHIFT", ["L3"], "Correr"),
        binding("BTN_EXTRA", ["RT"], "Cubrirse (lateral 2)"),
        binding("BTN_SIDE", ["A"], "Eslinga (lateral 1)", modifier=["RB"]),
        binding("BTN_MIDDLE", ["R3"], "Click de rueda"),
        binding("KEY_U", ["LT"], "LT"),
        binding("KEY_O", ["RT"], "RT"),
        binding("KEY_1", ["B"], "Compañero (LT+B)", modifier=["LT"]),
        binding("KEY_2", ["X"], "Compañero (LT+X)", modifier=["LT"]),
        binding("KEY_3", ["A"], "Compañero (LT+A)", modifier=["LT"]),
        binding("KEY_4", ["Y"], "LT+Y", modifier=["LT"]),
        binding("KEY_M", ["BACK"], "Select"),
        binding("KEY_ESC", ["START"], "Start / menu"),
    ],
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
        "launch_app": True,                 # abre el juego en el cel antes de scrcpy
        "package": "com.garena.game.mho",
        "wait_landscape": True,             # espera a que el cel este en horizontal
        "keep_geometry": True,              # si la ventana cambia al rotar, la regresa a su tamaño
    },
}


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


# ---------------------------------------------------------------- carga / guardado
def normalize(data):
    """Rellena lo que falte con los defaults (por si el archivo es viejo o se edito a mano)."""
    base = default_config()
    out = copy.deepcopy(data) if isinstance(data, dict) else {}
    for key, val in base.items():
        if key not in out:
            out[key] = copy.deepcopy(val)
        elif isinstance(val, dict) and isinstance(out[key], dict):
            for sk, sv in val.items():
                out[key].setdefault(sk, copy.deepcopy(sv))
    bl = []
    for b in out.get("bindings") or []:
        if not isinstance(b, dict):
            continue
        nb = binding("", [])
        nb.update(b)
        nb["outputs"] = list(nb.get("outputs") or [])
        nb["modifier"] = list(nb.get("modifier") or [])
        bl.append(nb)
    out["bindings"] = bl
    return out


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

    dirs = ("arriba", "abajo", "izquierda", "derecha")
    for sk, label in (("move", "Movimiento"), ("camera", "Camara"), ("dpad", "D-pad")):
        keys = cfg["sticks"].get(sk) or []
        if len(keys) != 4:
            errors.append(f"{label}: se necesitan 4 teclas")
            continue
        for n, d in zip(keys, dirs):
            if check(n, f"{label} {d}"):
                use(n, f"{label} {d}")

    for i, b in enumerate(cfg["bindings"], 1):
        where = f"Asignacion {i} ({b.get('note') or b.get('input')})"
        inp = b.get("input", "")
        if check(inp, where):
            use(inp + ("#cam" if b.get("camera_only") else ""), where)
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

    return errors, warnings


# ---------------------------------------------------------------- scrcpy
SCRCPY_FIXED = ["--keyboard=disabled", "--mouse=sdk", "--mouse-bind=----:----", "--gamepad=uhid"]


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


def build_scrcpy_cmd(sc):
    cmd = [tool_path(sc, "scrcpy")]
    if sc.get("serial"):
        cmd += ["-s", sc["serial"]]
    cmd += SCRCPY_FIXED
    cmd += [f"--video-codec={sc['codec']}",
            f"--video-bit-rate={sc['bitrate']}",
            f"--max-fps={int(sc['max_fps'])}"]
    if sc.get("no_mipmaps"):
        cmd.append("--no-mipmaps")
    if sc.get("stay_awake"):
        cmd.append("--stay-awake")
    if sc.get("borderless"):
        cmd.append("--window-borderless")
    if sc.get("set_geometry"):
        cmd += [f"--window-x={int(sc['x'])}", f"--window-y={int(sc['y'])}",
                f"--window-width={int(sc['width'])}", f"--window-height={int(sc['height'])}"]
    if sc.get("extra_args"):
        cmd += shlex.split(sc["extra_args"])
    return cmd


def scrcpy_env_overrides(sc):
    return {"SDL_VIDEODRIVER": "x11"} if sc.get("force_x11") else {}
