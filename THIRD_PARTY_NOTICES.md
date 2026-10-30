# Componentes de terceros

El código propio de kb2pad-dock está bajo licencia MIT (ver [LICENSE](LICENSE)).

## Incluidos en este repositorio

| Componente | Archivos | Licencia |
|---|---|---|
| ViGEmClient (Nefarius Software Solutions), vía [vgamepad](https://github.com/yannbouteiller/vgamepad) | `vigem/ViGEmClient.dll` | ver [ViGEmClient](https://github.com/nefarius/ViGEmClient) |
| Instalador de ViGEmBus (Nefarius Software Solutions), vía vgamepad | `vigem/ViGEmBusSetup_x64.msi` | ver [ViGEmBus](https://github.com/nefarius/ViGEmBus) |
| vgamepad (Yann Bouteiller) | redistribución de los dos anteriores | MIT, `vigem/LICENSE-vgamepad.txt` |

## Incluidos en el `.exe` de Windows (release)

El paquete de Windows se genera con PyInstaller y lleva dentro:

| Componente | Licencia |
|---|---|
| Python 3.12 | PSF License |
| PyQt6 (Riverbank Computing) | **GPL-3.0-only** |
| Qt 6 (The Qt Company) | LGPL-3.0 |
| PyQt6-sip | BSD-2-Clause |
| OpenSSL, libffi, bzip2, xz, zlib y el runtime de Visual C++ | sus respectivas licencias |

Como PyQt6 es GPL-3.0, el `.exe` en conjunto se distribuye bajo los términos de la GPL-3.0.
El código fuente correspondiente es este repositorio, y los textos de las licencias van en la
carpeta `licencias/` dentro del zip de Windows.

En Linux no se distribuyen binarios: PyQt6 y python-evdev se instalan desde tu distribución.
