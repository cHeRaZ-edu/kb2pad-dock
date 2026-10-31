# kb2pad-dock

**Juega en tu PC juegos de celular que no existen para PC y que no tienen soporte de teclado.**

El juego corre en tu celular Android, tal cual lo instalaste de la Play Store. Tu PC funciona
como un *dock*: muestra la pantalla con [scrcpy](https://github.com/Genymobile/scrcpy) y
convierte tu teclado y mouse en un **control de Xbox 360 virtual**. El juego ve un control
real, no toques falsos.

Funciona en **Linux** y **Windows**, desde la misma app y con el mismo archivo de configuración.

![kb2pad-dock en Linux](docs/img/linux-botones.png)

---

## ¿Para qué sirve?

Hay juegos de celular que:

- **no tienen versión de PC** ni de consola,
- **no se dejan emular**: la Play Store marca el emulador como "no compatible" o el juego
  revisa que lo hayas instalado desde la tienda,
- y **no aceptan teclado y mouse**, aunque **sí aceptan un control**.

kb2pad-dock resuelve justo eso: el juego no se toca y corre nativo en tu celular, y en la PC
juegas con teclado y mouse en una ventana sin bordes del tamaño de tu monitor, incluso con la
pantalla del celular apagada.

Nació para jugar **Monster Hunter Outlanders** (solo para celular) desde la PC, pero sirve
para cualquier juego de Android que acepte control.

## Cómo funciona

```mermaid
flowchart LR
    T["Teclado + mouse"] --> K["kb2pad<br/>control Xbox 360 virtual"]
    K --> S["scrcpy<br/>--gamepad=uhid"]
    S -- "USB o Wi-Fi" --> P["Celular Android<br/>el juego corre aquí"]
    P -- "video" --> S
```

1. **kb2pad** lee tu teclado y mouse y los convierte en un control de Xbox 360 virtual
   (`uinput` en Linux, driver **ViGEmBus** en Windows).
2. **scrcpy** detecta ese control y se lo pasa al celular como un control físico conectado.
3. El juego lo reconoce como cualquier control: muestra los íconos de botones (A, B, LT...).

## Características

- **Modos por estilo de juego** (por ejemplo espada, ballesta, arco) que cambias en plena
  partida con `Alt + tecla`. Cada modo solo guarda lo que cambia; lo demás lo comparten todos.
- **Mapeo editable desde la app**: tabla de asignaciones con captura de teclas y botones del
  mouse (incluye los laterales de un mouse gamer).
- **Combos con modificador**: una tecla manda `LT` y luego `B`, para menús tipo "LT + botón".
  También con el D-pad (por ejemplo `LT + D-pad ↑`).
- **Varias salidas en una tecla**: por ejemplo `C` = `Y + B`.
- **Mouse como cámara** (stick derecho) que se activa y desactiva con Bloq Mayús.
- **Menú radial con el mouse**: mientras sostienes la tecla, el mouse apunta y se queda en el
  objeto; al soltar, lo selecciona.
- **Tocar o sostener**: la misma tecla puede ser un botón normal si la tocas y abrir el radial si
  la sostienes.
- **Cambios en caliente**: guardas y el control aplica el mapeo al momento, sin reiniciar.
- **Lanza el juego por ti**: abre la app en el celular, espera a que gire a horizontal y abre la
  ventana sin bordes con el tamaño calculado para tu monitor. Si la ventana cambia al rotar, la
  regresa a su lugar.
- **Pantalla del celular apagada** mientras juegas (ver las guías).
- Con **Alt presionado** no se manda nada al juego: `Alt+Tab` y los atajos de scrcpy (`Alt+O`)
  no disparan botones.

## Capturas

| Linux | Windows |
|---|---|
| ![Botones](docs/img/linux-botones.png) | ![Botones en Windows](docs/img/windows-botones.png) |
| ![Juego (scrcpy)](docs/img/linux-juego.png) | ![Juego en Windows](docs/img/windows-juego.png) |

| Modo Ballesta (lo heredado sale en gris) | Combo con modificador (LT + X) |
|---|---|
| ![Modo Ballesta](docs/img/linux-modo-ballesta.png) | ![Combo](docs/img/dialogo-combo.png) |

| Mouse y menú radial | Sticks y teclas especiales |
|---|---|
| ![Mouse y radial](docs/img/linux-mouse-radial.png) | ![Sticks](docs/img/linux-sticks.png) |

| Asignación con menú radial (tocar / sostener) |
|---|
| ![Asignación radial](docs/img/dialogo-asignacion.png) |

## Descargas

En **[Releases](https://github.com/cHeRaZ-edu/kb2pad-dock/releases)**:

| Archivo | Para |
|---|---|
| `kb2pad-dock-v0.1.0-windows-x64.zip` | Windows 10/11 de 64 bits: trae `kb2pad.exe`, no necesitas Python |
| `kb2pad-dock-v0.1.0-linux.tar.gz` | Linux: el código, se corre con Python |

## Guías paso a paso

- 🪟 **[Windows](docs/guia-windows.md)**: instalación, configuración, jugar y apagar la pantalla del celular.
- 🐧 **[Linux](docs/guia-linux.md)**: lo mismo para Linux (probado en CachyOS / Arch).

## Requisitos

- Un celular **Android** con **depuración USB** activada, conectado por USB o por Wi-Fi.
- El juego debe **aceptar control** (gamepad).
- **scrcpy 2.7 o más reciente** (es la versión que trae el soporte de control `--gamepad=uhid`).
- **Windows**: el driver **ViGEmBus**. El instalador va incluido en la app (*Archivo → Instalar ViGEmBus*).
- **Linux**: Python 3 con PyQt6 y python-evdev.

## Controles por defecto

Todo se cambia desde la pestaña **Botones** de la app. Las acciones son las de Monster Hunter
Outlanders, como ejemplo. En los combos (`LT + B`), el primer botón entra primero y el segundo
50 ms después, como cuando lo haces en un control.

| Tecla / botón | Control | Ejemplo en el juego |
|---|---|---|
| `W A S D` | Stick izquierdo | Moverse |
| Mouse (con `Bloq Mayús`) | Stick derecho | Cámara |
| `I J K L` | Stick derecho | Cámara con teclas |
| Flechas | D-pad | |
| `Espacio` | A | Saltar |
| Click izquierdo* | Y | Golpe normal |
| `F` / click derecho | B | Golpe fuerte |
| `C` | Y + B (juntos) | Golpe fuerte + normal |
| `R` / lateral 2 / `O` | RT | Cubrirse |
| `E` | X | Consumir objeto |
| `Ctrl` | LB + menú radial con el mouse | Menú de objetos |
| `Q` | RB al tocar / RB + menú radial al sostener | Mirar al frente, eslinga |
| Lateral 1 / click de rueda | RB + A | Eslinga |
| `U` | LT | |
| `1` `2` `3` | LT + Y / B / X | Compañeros |
| `4` | LT + A | Especial |
| `5` | RT + LT | Especial Felyne |
| `G` | D-pad ↑ + LT | Fabricar |
| `Tab` | D-pad → + RB | Cambiar objetivo |
| `T` | B + RB | Preparar trampa |
| `Shift` | L3 | Correr |
| `M` / `Esc` | Select / Start | |
| `F12` | Pausar o reanudar kb2pad | Para escribir en otras apps |
| `Bloq Mayús` | Mouse como cámara sí/no | |

\* El click izquierdo solo cuenta como botón con el mouse en modo cámara. Fuera de ese modo,
el mouse funciona normal en la ventana.

## Modos

Cada arma se juega distinto, así que en vez de cambiar teclas a cada rato hay **modos**.
**Por defecto** es la tabla de arriba y la heredan todos; cada modo solo guarda las teclas que
cambia. Si cambias algo en *Por defecto* (por ejemplo `G` = fabricar), aplica en todos los modos
que no lo cambien.

| Atajo | Modo | Qué cambia |
|---|---|---|
| `Alt + Q` | **Por defecto** | Nada: es la tabla de arriba (armas cuerpo a cuerpo). |
| `Alt + 1` | **Espada** | Empieza igual que *Por defecto*, listo para que lo ajustes. |
| `Alt + 2` | **Ballesta** | Click izq = RT (disparar) · Click der = Y (cubrirse) · `R` = LB + RB (recargar) · `V` = B (modo misil). `C` sigue siendo Y + B. |
| `Alt + 3` | **Arco** | Click izq = RT (disparar) · Click der = Y · `R` = Y. `F` = B y `C` = Y + B siguen igual. |

- Cambias de modo **en plena partida**, sin soltar lo que tienes presionado (sigues corriendo).
- La app muestra el modo actual y avisa con una notificación al cambiar.
- En la pestaña **Botones** eliges el modo arriba: lo que viene de *Por defecto* sale en gris, y
  si lo editas se copia a ese modo. Puedes crear modos nuevos, ponerles su `Alt + tecla`,
  desactivar una tecla solo en un modo y elegir con qué modo arranca el control.

![Modo Ballesta en la pestaña Botones](docs/img/linux-modo-ballesta.png)

## Notas

- **No modifica el juego** ni inyecta toques: solo hay un control conectado. Aun así, evita
  macros o automatizar acciones en juegos en línea.
- kb2pad lee el teclado **de forma global** mientras está activo. Pausa con `F12` si vas a
  escribir en otra ventana (`Alt + Tab` no manda nada al juego).
- **Xiaomi / POCO / Redmi**: para que el mouse funcione en los menús, activa
  *Depuración USB (Configuración de seguridad)* (viene en las guías).
- **Windows**: el `.exe` no está firmado, así que SmartScreen puede advertir la primera vez.

## Estructura del proyecto

| Archivo | Qué hace |
|---|---|
| `app.py` | La GUI (PyQt6). Es lo que abres. |
| `core.py` | La lógica del mapeo: combos, radial, mouse-cámara. Es la misma en los dos sistemas. |
| `engine.py` | El control virtual en Linux (`evdev` / `uinput`). |
| `engine_win.py` | El control virtual en Windows (ViGEmBus + hooks de teclado y mouse). |
| `config.py` | Valores por defecto, carga, guardado y validación del `config.json`. |
| `keycodes.py`, `_ecodes_data.py` | Códigos de teclas (nombres de evdev en los dos sistemas). |
| `platform_tools.py` | adb, rotación del celular y manejo de la ventana de scrcpy según el sistema. |
| `kb2pad.spec`, `vigem/` | Build de Windows (PyInstaller) y el cliente/instalador de ViGEmBus. |

La configuración se guarda en:

- Linux: `~/.config/kb2pad/config.json`
- Windows: `%APPDATA%\kb2pad\config.json`

El formato es el mismo, así que puedes copiarla de un sistema a otro.

## Compilar desde el código

**Linux** (no se compila, se corre):

```fish
sudo pacman -S --needed python-pyqt6 python-evdev scrcpy android-tools xdotool
python app.py
```

**Windows** (`.exe` con PyInstaller):

```bat
pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm kb2pad.spec
```

El resultado queda en `dist\kb2pad\kb2pad.exe`.

## Créditos

- [scrcpy](https://github.com/Genymobile/scrcpy) de Genymobile: el puente con el celular.
- [ViGEmBus / ViGEmClient](https://github.com/nefarius/ViGEmBus) de Nefarius: el control virtual en Windows.
- [vgamepad](https://github.com/yannbouteiller/vgamepad): de ahí viene el cliente de ViGEm incluido.
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) y [python-evdev](https://github.com/gvalkov/python-evdev).

## Licencia

El código de kb2pad-dock está bajo licencia [MIT](LICENSE). El `.exe` de Windows incluye
componentes de terceros con sus propias licencias (entre ellas PyQt6, GPL-3.0); el detalle está
en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

kb2pad-dock no está afiliado a Capcom, TiMi Studio Group, Garena ni Genymobile. Los nombres de
juegos se mencionan solo como ejemplo de uso.
