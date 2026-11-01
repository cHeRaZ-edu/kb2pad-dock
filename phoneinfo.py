"""
Datos del celular para el HUD, por adb:

- Modelo, procesador y GPU (una vez al abrir el juego):
      adb shell "getprop; echo =====GLES=====; dumpsys SurfaceFlinger | grep -m1 GLES"
- FPS del juego en el celular (cada 2 s): FPS_SCRIPT busca la capa del juego en SurfaceFlinger
  (la app con el foco) y pide sus ultimos ~128 frames con --latency. Si eso no da datos, usa el
  contador de frames de la pantalla (service call SurfaceFlinger 1013) y la GUI calcula la diferencia.
"""
import re

INFO_SEP = "=====GLES====="
# GPU: la linea GLES de SurfaceFlinger (Android 15+ con Vulkan ya no la trae), el modelo del driver
# Adreno (kgsl) o Mali, y ro.hardware.egl como ultimo recurso
INFO_CMD = (f"getprop; echo {INFO_SEP}; dumpsys SurfaceFlinger | grep -m1 GLES; "
            "echo \"KGSL=$(cat /sys/class/kgsl/kgsl-3d0/gpu_model 2>/dev/null)\"; "
            "echo \"MALI=$(cat /sys/class/misc/mali0/device/gpuinfo 2>/dev/null | head -n1)\"")

# Nombres comerciales de los chips mas comunes (ro.soc.model). Si no esta, se muestra el codigo.
SNAPDRAGON = {
    "SM8850": "8 Elite Gen 5", "SM8750": "8 Elite", "SM8735": "8s Gen 4", "SM8650": "8 Gen 3",
    "SM8635": "8s Gen 3", "SM8550": "8 Gen 2", "SM8475": "8+ Gen 1", "SM8450": "8 Gen 1", "SM8350": "888",
    "SM8250": "865/870", "SM8150": "855", "SM7675": "7+ Gen 3", "SM7635": "7s Gen 3", "SM7550": "7 Gen 3",
    "SM7475": "7+ Gen 2", "SM7435": "7s Gen 2", "SM7450": "7 Gen 1", "SM7325": "778G", "SM7250": "765G",
    "SM7150": "730", "SM6450": "6 Gen 1", "SM6375": "695", "SM6225": "680", "SM4450": "4 Gen 2",
    "SM4375": "4 Gen 1",
}
DIMENSITY = {
    "MT6991": "Dimensity 9400", "MT6989": "Dimensity 9300", "MT6985": "Dimensity 9200",
    "MT6983": "Dimensity 9000", "MT6897": "Dimensity 8300", "MT6896": "Dimensity 8200",
    "MT6895": "Dimensity 8100", "MT6893": "Dimensity 1200", "MT6877": "Dimensity 900",
    "MT6833": "Dimensity 700", "MT6789": "Helio G99", "MT6785": "Helio G90T",
}

FPS_LAT = "=====LATENCY====="
FPS_FLIP = "=====FLIPS====="
# sh del celular (toybox): app con el foco -> capa SurfaceView de esa app -> sus tiempos de frames
FPS_SCRIPT = (
    "P=$(dumpsys window | grep -m1 mCurrentFocus | grep -oE '[A-Za-z0-9_.]+/' | head -n1 | tr -d /); "
    "[ -z \"$P\" ] && P=$(dumpsys activity activities | grep -m1 -E 'topResumedActivity|mResumedActivity' "
    "| grep -oE '[A-Za-z0-9_.]+/' | head -n1 | tr -d /); "
    # la capa con frames es la "(BLAST)" de la SurfaceView del juego (la otra solo es el contenedor)
    # Android 16 lista 'RequestedLayerState{<nombre> parentId=...}': se deja solo el nombre
    "S=$(dumpsys SurfaceFlinger --list | grep -F \"$P\" | grep -v Background "
    "| sed -E 's/^RequestedLayerState[{]//; s/ (parentId|relativeParentId|z)=.*$//; s/[}]$//'); "
    "L=$(echo \"$S\" | grep -F SurfaceView | grep -F BLAST | head -n1); "
    "[ -z \"$L\" ] && L=$(echo \"$S\" | grep -F BLAST | head -n1); "
    "[ -z \"$L\" ] && L=$(echo \"$S\" | grep -F SurfaceView | head -n1); "
    f"echo \"FOCUS=$P\"; echo \"LAYER=$L\"; echo {FPS_LAT}; [ -n \"$L\" ] && dumpsys SurfaceFlinger --latency \"$L\"; "
    f"echo {FPS_FLIP}; service call SurfaceFlinger 1013"
)
_INVALID = (0, 9223372036854775807)


def _props(text):
    return dict(re.findall(r"^\[([^\]]+)\]: \[(.*)\]\s*$", text or "", re.M))


def soc_name(props):
    """'Snapdragon 8s Gen 4 (SM8735)' / 'Dimensity 9300 (MT6989)' / codigo tal cual."""
    model = (props.get("ro.soc.model") or "").strip()
    man = (props.get("ro.soc.manufacturer") or "").lower()
    plat = (props.get("ro.board.platform") or props.get("ro.hardware") or "").strip()
    code = model.upper()
    if code in SNAPDRAGON:
        return f"Snapdragon {SNAPDRAGON[code]} ({model})"
    if code in DIMENSITY:
        return f"{DIMENSITY[code]} ({model})"
    if "qti" in man or "qualcomm" in man:
        return f"Snapdragon {model or plat}".strip()
    if model:
        return model
    return plat or "?"


def phone_name(props):
    for key in ("ro.product.marketname", "ro.product.vendor.marketname", "ro.product.odm.marketname",
                "ro.config.marketing_name", "ro.vendor.product.display"):
        v = (props.get(key) or "").strip()
        if v:
            return v
    brand = (props.get("ro.product.brand") or "").strip()
    model = (props.get("ro.product.model") or "").strip()
    return f"{brand.capitalize()} {model}".strip() or "?"


def gpu_name(text, props=None):
    """GPU a partir de (en orden): 'GLES: Qualcomm, Adreno (TM) 825, ...', 'KGSL=Adreno825v2',
    'MALI=Mali-G715 ...' o ro.hardware.egl."""
    text = text or ""
    m = re.search(r"GLES:\s*([^,\n]*),\s*([^,\n]*)", text)
    if m:
        renderer = re.sub(r"\s+", " ", m.group(2).replace("(TM)", "").replace("(R)", "")).strip()
        if renderer:
            return renderer
    m = re.search(r"KGSL=\s*Adreno\s*(\d+)", text, re.I)
    if m:
        return f"Adreno {m.group(1)}"
    m = re.search(r"MALI=\s*(Mali-[\w-]+)", text, re.I)
    if m:
        return m.group(1)
    egl = ((props or {}).get("ro.hardware.egl") or "").strip()
    return {"adreno": "Adreno", "mali": "Mali", "powervr": "PowerVR"}.get(egl.lower(), egl.capitalize())


def parse_info(text):
    props_text, _, gles = (text or "").partition(INFO_SEP)
    props = _props(props_text)
    return {"phone": phone_name(props), "soc": soc_name(props), "gpu": gpu_name(gles, props),
            "model": (props.get("ro.product.model") or "").strip()}


def parse_fps(text):
    """Salida de FPS_SCRIPT -> (ultimo_frame_ns, fps_en_el_ultimo_segundo, contador_1013, capa).
    Cualquiera puede ser None si el celular no lo da."""
    head, _, rest = (text or "").partition(FPS_LAT)
    lat, _, flips = rest.partition(FPS_FLIP)
    m = re.search(r"LAYER=(.*)", head)
    layer = m.group(1).strip() if m else ""
    times = []
    for line in lat.splitlines():
        parts = line.split()
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        desired, actual, ready = (int(p) for p in parts)
        t = actual if actual not in _INVALID else desired
        if t not in _INVALID:
            times.append(t)
    last = fps = None
    if len(times) >= 2:
        times.sort()
        last = times[-1]
        fps = sum(1 for t in times if t > last - 1_000_000_000)
    counter = None
    m = re.search(r"Parcel\(\s*([0-9a-fA-F]{8})", flips)
    if m:
        counter = int(m.group(1), 16)
    return last, fps, counter, layer
