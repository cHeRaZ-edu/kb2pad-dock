"""
Temperatura del celular por adb.

    adb shell "dumpsys thermalservice; echo =====BATTERY=====; dumpsys battery"

- dumpsys thermalservice (Android 10+): temperaturas por tipo (CPU, GPU, bateria, piel) y el estado
  termico de Android (0 normal ... 6 apagado: ya esta bajando rendimiento por calor).
- dumpsys battery: nivel, temperatura de la bateria (en decimas de grado) y si esta cargando.

Para los avisos cuenta la temperatura de la piel o de la bateria (la mas alta). La del CPU sube a
70-80 grados en juegos y es normal, por eso solo se muestra.
"""
import re

SEPARATOR = "=====BATTERY====="
SHELL_CMD = f"dumpsys thermalservice; echo {SEPARATOR}; dumpsys battery"

STATUS_NAMES = ["normal", "ligero", "moderado", "severo", "critico", "emergencia", "apagado"]
TYPES = {0: "cpu", 1: "gpu", 2: "bateria", 3: "piel"}
LEVELS = ["ok", "aviso", "critico", "peligro"]
OK, WARN, CRITICAL, DANGER = range(4)

_TEMP = re.compile(r"Temperature\{mValue=(-?[\d.]+(?:E-?\d+)?), mType=(-?\d+), mName=([^,}]*), mStatus=(-?\d+)\}")


def parse(text):
    """Salida del comando de arriba -> dict con:
    status (int o None), temps {cpu, gpu, bateria, piel} (maximo de cada tipo), battery_level,
    charging (bool o None)."""
    thermal, _, battery = (text or "").partition(SEPARATOR)
    temps = {}
    for m in _TEMP.finditer(thermal):
        try:
            value, kind = float(m.group(1)), int(m.group(2))
        except ValueError:
            continue
        name = TYPES.get(kind)
        if name is None or not -30.0 < value < 150.0:      # sensores sin dato reportan -273 o basura
            continue
        temps[name] = max(temps.get(name, value), value)
    m = re.search(r"Thermal Status:\s*(\d+)", thermal)
    status = int(m.group(1)) if m else None

    level = re.search(r"^\s*level:\s*(\d+)", battery, re.M)
    btemp = re.search(r"^\s*temperature:\s*(-?\d+)", battery, re.M)
    if btemp and "bateria" not in temps:
        value = int(btemp.group(1)) / 10.0
        if -30.0 < value < 150.0:
            temps["bateria"] = value
    charging = None
    if battery.strip():
        powered = re.findall(r"^\s*(?:AC|USB|Wireless|Dock) powered:\s*(true|false)", battery, re.M)
        st = re.search(r"^\s*status:\s*(\d+)", battery, re.M)
        charging = "true" in powered and (st is None or int(st.group(1)) in (2, 5))
    return {"status": status, "temps": temps,
            "battery_level": int(level.group(1)) if level else None, "charging": charging}


def metric(info):
    """(grados, sensor) que se usa para los avisos: piel o bateria, la mas alta. None si no hay."""
    best = None
    for name in ("piel", "bateria"):
        v = info["temps"].get(name)
        if v is not None and (best is None or v > best[0]):
            best = (v, name)
    return best


def classify(info, warn, critical, danger, previous=OK, hysteresis=1.0):
    """Nivel (OK, WARN, CRITICAL, DANGER) y el motivo. Para bajar de nivel la temperatura tiene que
    quedar 'hysteresis' grados por debajo del umbral (asi no parpadea)."""
    level, reason = OK, ""
    m = metric(info)
    if m is not None:
        value, sensor = m
        for lvl, limit in ((DANGER, danger), (CRITICAL, critical), (WARN, warn)):
            margin = hysteresis if previous >= lvl else 0.0
            if value >= limit - margin:
                level, reason = lvl, f"{sensor} {value:.1f} °C (limite {limit:g} °C)"
                break
    st = info.get("status")
    if st is not None:
        by_status = DANGER if st >= 4 else CRITICAL if st >= 3 else WARN if st >= 2 else OK
        if by_status > level:
            level, reason = by_status, f"Android reporta estado termico '{status_name(st)}'"
    return level, reason


def status_name(st):
    if st is None:
        return "?"
    return STATUS_NAMES[st] if 0 <= st < len(STATUS_NAMES) else str(st)
