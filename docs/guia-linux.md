# Guía paso a paso: Linux

Al terminar vas a jugar en tu PC con teclado y mouse, el juego corriendo en tu celular y la
pantalla del celular apagada.

Probado en **CachyOS / Arch** con KDE Plasma (Wayland). En otras distribuciones los pasos son los
mismos; solo cambian los nombres de los paquetes.

**Necesitas:** un celular Android, un cable USB de datos (no solo de carga) y un juego que acepte
control.

---

## Parte 1. Preparar el celular (una sola vez)

1. **Activa las opciones de desarrollador.**
   Ajustes → *Acerca del teléfono* → toca 7 veces *Número de compilación*.
   En Xiaomi, POCO y Redmi es *Versión de HyperOS* (o *Versión de MIUI*).
2. **Activa la depuración USB.**
   Ajustes → *Opciones de desarrollador* → *Depuración USB*.
   En Xiaomi está en Ajustes → *Ajustes adicionales* → *Opciones de desarrollador*.
3. **Solo Xiaomi, POCO y Redmi:** en esa misma pantalla activa también
   **Depuración USB (Configuración de seguridad)**.
   - Te pide iniciar sesión con tu cuenta Xiaomi y, a veces, tener SIM y datos activos.
   - Reinicia el celular después de activarla.
   - Sin esta opción el mouse no puede tocar en los menús y el log muestra un error de
     `INJECT_EVENTS`.
4. **Instala el juego** desde la Play Store del celular y ábrelo una vez para que termine de
   descargar sus datos.
5. **Conecta el celular por USB** a la PC. En el celular, en la notificación de USB, elige
   *Transferencia de archivos*. Cuando aparezca **"¿Permitir depuración USB?"**, marca
   *Permitir siempre desde esta computadora* y acepta.

## Parte 2. Instalar en la PC (una sola vez)

1. **Instala las dependencias.**

   CachyOS / Arch:
   ```fish
   sudo pacman -S --needed python-pyqt6 python-evdev scrcpy android-tools xdotool xcb-util-cursor
   ```
   En Debian, Ubuntu o Fedora instala los equivalentes (PyQt6, python-evdev, adb, xdotool,
   libxcb-cursor0). `xcb-util-cursor` hace falta para que el HUD se vea encima del juego en Wayland.
   Revisa que **scrcpy sea 2.7 o más reciente** (`scrcpy --version`); si el de tu distribución es
   más viejo, usa el de los [releases de scrcpy](https://github.com/Genymobile/scrcpy/releases).

2. **Descarga kb2pad-dock.**
   En [Releases](https://github.com/cHeRaZ-edu/kb2pad-dock/releases) baja
   `kb2pad-dock-v0.6.0-linux.tar.gz` y descomprímelo:
   ```fish
   mkdir -p ~/Apps
   tar xzf ~/Descargas/kb2pad-dock-v0.6.0-linux.tar.gz -C ~/Apps
   ```
   O clona el repo:
   ```fish
   git clone https://github.com/cHeRaZ-edu/kb2pad-dock ~/Apps/kb2pad-dock
   ```

3. **Ábrelo.**
   ```fish
   python ~/Apps/kb2pad-dock/app.py
   ```

4. **Permisos del control virtual.** Para crear el control, kb2pad necesita leer `/dev/input`
   y escribir en `/dev/uinput`. Tienes dos opciones:
   - **Sin configurar nada:** al iniciar el control, la app usa `pkexec` y te pide tu contraseña.
   - **Para no escribir la contraseña cada vez:**
     ```fish
     echo 'KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/60-kb2pad-uinput.rules
     echo uinput | sudo tee /etc/modules-load.d/uinput.conf
     sudo usermod -aG input $USER
     ```
     Cierra sesión y vuelve a entrar. Ojo: el grupo `input` deja que cualquier programa de tu
     usuario lea el teclado sin root. Si prefieres no abrir eso, quédate con `pkexec`.

5. **Opcional: acceso en el menú de aplicaciones.**
   ```fish
   printf '[Desktop Entry]\nType=Application\nName=kb2pad-dock\nComment=Control virtual para scrcpy\nExec=python %s/Apps/kb2pad-dock/app.py\nIcon=input-gaming\nCategories=Game;\n' $HOME > ~/.local/share/applications/kb2pad-dock.desktop
   ```

## Parte 3. Configurar (una sola vez)

Todo esto se hace en la pestaña **Juego (scrcpy)**:

![Pestaña Juego en Linux](img/linux-juego.png)

1. **Carpeta de scrcpy**: déjala vacía si instalaste scrcpy con tu gestor de paquetes (lo busca
   en el `PATH`). Si bajaste scrcpy suelto, elige su carpeta.
2. **Serial (cable)**: clic en *Detectar*. Debe aparecer tu celular.
3. **Pantalla** → elige tu monitor → **Toda la pantalla**. Con *Al pasar a horizontal* en
   *Ocupar toda la pantalla* (viene así), la ventana se acomoda sola cada vez que el celular gira,
   aunque salgas del juego y vuelvas.
4. Clic en **Guardar** (o `Ctrl+S`).

La app que se abre en el celular se elige al iniciar (Parte 4), con un buscador; ya viene
Monster Hunter Outlanders (`com.garena.game.mho`).

Los controles se cambian en la pestaña **Botones** (doble clic en una fila para editarla).
Cualquier cambio que guardes se aplica al momento, aunque el control esté corriendo. También
puedes editar `~/.config/kb2pad/config.json` a mano: el control detecta el cambio y lo recarga.

## Parte 4. Jugar

1. Con el celular conectado, clic en **Iniciar todo**. La app:
   - inicia el control virtual (con `pkexec` te pide la contraseña),
   - te pregunta si **abrir una app** (escribe para buscarla entre las instaladas) o **solo
     mostrar la pantalla**,
   - abre la app en el celular y espera a que gire a horizontal,
   - y abre la ventana sin bordes del juego, del tamaño de la pantalla.

   ![Diálogo al iniciar](img/dialogo-inicio.png)
2. En el juego, revisa que aparezcan los íconos de botones de control (A, B, LT…).
3. **Bloq Mayús** activa el **mouse como cámara**: el mouse mueve el stick derecho, el cursor
   se oculta sobre el juego y la rueda manda D-pad ← / →. Presiónalo otra vez para
   soltar el mouse (en menús, por ejemplo).
4. **F12** pausa kb2pad. Úsalo cuando vayas a escribir en otra ventana, porque kb2pad lee el
   teclado aunque la ventana del juego no tenga el foco. `Alt + Tab` no manda nada al juego.

5. **Chat**: abre el chat en el juego y presiona **Alt + T**. El icono de la bandeja cambia a un
   teclado: lo que escribes en la ventana del juego llega al celular y las letras ya no disparan
   botones; el mouse sigue funcionando. Android no saca su teclado en pantalla porque la ventana
   se conecta como teclado físico. Para volver: **Alt + 1/2/3** o **Alt + 0** (regresa al modo que
   tenías). Mientras juegas, kb2pad no deja que las teclas lleguen al celular.
   - **La primera vez**, con el juego abierto, pulsa **Idioma del teclado en el celular...** en
     *Sticks y teclas especiales* y en el celular elige el teclado **scrcpy** → *Español
     (Latinoamérica)*, para que salgan la `ñ` y los acentos.
   - En el chat solo cuenta el Alt izquierdo (`AltGr + Q` escribe `@`).

**Wayland:** para poder acomodar la ventana, la app abre scrcpy con X11 (XWayland) mientras *Al
pasar a horizontal* no esté en *No tocar la ventana*. Necesitas `xdotool`. Si aun así no respeta
la posición, activa **Forzar X11** en la pestaña Juego.

**Modos por arma**: cambia en plena partida con **Alt + 1** (Espada), **Alt + 2** (Ballesta)
o **Alt + 3** (Arco). El icono del modo actual (espada, ballesta o arco) se ve en la bandeja del
sistema y en la barra de la app; sale en gris si el control está detenido o en pausa. Cada modo es
una plantilla completa que editas en la pestaña **Botones** (elige el modo arriba); ahí también
cambias su icono por una imagen tuya.

Si no ves el icono en la bandeja de KDE, abre la flecha de la bandeja → *Configurar la bandeja
del sistema* → *Entradas* y pon **kb2pad-dock** en *Mostrar siempre*.

La tabla de controles y de modos está en el [README](../README.md#controles-por-defecto).

**Si sientes retraso en la imagen**: en la pestaña *Juego (scrcpy)* pon *Codec* `h264`,
*Resolución máxima* `1920` y, en *Codificador*, pulsa *Buscar codificadores* y elige uno de
hardware. Para ir más allá está *Optimización del codificador (avanzado)* con el botón
**Bajar latencia (automático)**; viene apagada y te muestra sus advertencias antes de aplicar
(ver el [README](../README.md#bajar-el-retraso-del-video)).

**Perfiles y temperatura**: en *Video* eliges un perfil (Mejor calidad, Balanceado, Rendimiento o
Máximo rendimiento o Enfriar) y con **Alt + L** alternas entre dos en plena partida. Si el celular se
calienta, **Alt + E** pone el perfil Enfriar (video ligero y el juego limitado a 30 FPS) y otra vez
regresa al que tenías. Mientras juegas, kb2pad
lee la temperatura del celular: la ves en el HUD encima del juego (donde también puedes poner los FPS
del juego, la batería, el procesador, la GPU y el modelo, con el orden, estilo y colores que quieras),
en la barra de la app y en un icono de la bandeja; te avisa con una notificación al llegar a crítico y, en peligro, cierra la
transmisión. Se ajusta en la pestaña **Temperatura y HUD** (ver el
[README](../README.md#temperatura-y-hud)).

## Parte 5. Apagar la pantalla del celular

scrcpy tiene la opción `--turn-screen-off`, pero en algunos celulares (por ejemplo con HyperOS)
también apaga la imagen que se transmite y la ventana queda en negro. Lo que sí funciona es el
atajo de scrcpy **una vez que el juego ya está en pantalla**:

1. Con el juego ya visible, haz clic en la ventana del juego para que tenga el foco.
2. Presiona **Alt + O**. La pantalla del celular se apaga y el juego sigue en la ventana.

Para volver a prenderla: **Alt + Shift + O**.

Mientras Alt está presionado, kb2pad no manda nada al juego, así que la `O` (que es `RT`) no
llega al juego. Si desactivaste esa opción en *Sticks y teclas especiales*, pausa antes con
**F12** y reanuda después.

Si con `Alt + O` la ventana también se pone negra, prende la pantalla con `Alt + Shift + O` y baja
el brillo al mínimo desde la PC:
```fish
adb shell settings put system screen_brightness_mode 0
adb shell settings put system screen_brightness 1
```
Para regresar al brillo automático: `adb shell settings put system screen_brightness_mode 1`.

## Parte 6. Jugar sin cable (opcional)

1. En la pestaña **Juego (scrcpy)**, con el celular **conectado por cable** y en el mismo Wi-Fi que
   la PC, clic en **Activar red con el cable**. La app activa adb por Wi-Fi, lee la IP del celular
   y se conecta; *Conexión* cambia a **Red (Wi-Fi)**.
2. Clic en **Guardar** y desconecta el cable.
3. **Iniciar todo** como siempre: la app se conecta sola a esa IP.

Sin cable desde el principio (Android 11+): en el celular, *Opciones de desarrollador →
Depuración inalámbrica → Vincular dispositivo con código*, y en la app **Emparejar...** con la IP,
el puerto y el código que muestra el celular; en *Conectar a* va la IP y el puerto de la pantalla
principal de Depuración inalámbrica.

Por Wi-Fi el video tiene más retraso: usa una red de 5 GHz y baja el **Bitrate** a 8M–16M. Si el
celular se reinicia, repite el paso 1. Para volver al cable: *Conexión* = **Cable USB**.

## Parte 7. Terminar

- **Cerrar juego** cierra la ventana de scrcpy (el juego sigue abierto en el celular).
- **Detener control** quita el control virtual.
- Al cerrar la app se cierran los dos.

---

## Sin GUI

El control también se puede correr solo, por ejemplo para ver qué tecla manda cada botón:

```fish
sudo python ~/Apps/kb2pad-dock/engine.py --config ~/.config/kb2pad/config.json --debug
```

## Problemas comunes

| Qué pasa | Qué hacer |
|---|---|
| *Detectar* no muestra el celular | Revisa el cable de datos y la depuración USB, y acepta el aviso en el celular. Si `adb devices` dice `unauthorized`, vuelve a aceptarlo. |
| El celular se desconecta a media transferencia | Prueba otro puerto (sin hub) y otro cable, o desactiva el autosuspend de USB: `echo -1 \| sudo tee /sys/module/usbcore/parameters/autosuspend`. |
| El log de scrcpy dice `INJECT_EVENTS` | Xiaomi/POCO/Redmi: activa *Depuración USB (Configuración de seguridad)* y reinicia el celular. |
| El control no inicia por permisos | Usa `pkexec` (te pide la contraseña) o configura la regla de udev de la Parte 2. |
| El juego no reacciona al teclado | Revisa que el control esté **activo** (no en pausa con F12) y que el juego muestre íconos de control. scrcpy debe ser 2.7 o más reciente. |
| Los botones laterales del mouse no hacen nada | Activa *Mostrar teclas en el log*, presiónalos y mira qué código aparece. Asígnalo en la pestaña Botones con *Capturar*. |
| "No encontré la ventana de scrcpy" en el log | Instala `xdotool` y, en Wayland, activa *Forzar X11*. |
| En el chat no se escribe nada | Activa *Mandar lo que escribo al celular* en *Sticks y teclas especiales* y vuelve a abrir el juego (el teclado se pone al abrir la ventana). En Linux instala `xdotool`. |
| Jugando, las teclas hacen cosas raras en el celular | Desactiva *Mandar lo que escribo al celular* y vuelve a abrir el juego, y abre un issue en el repo con lo que pasó. |
| En el chat salen símbolos en vez de `ñ` o acentos | Falta el idioma del teclado *scrcpy* en el celular: botón *Idioma del teclado en el celular...* con el juego abierto. |
| El HUD no aparece (log: `[hud] no pudo abrirse`) | En Wayland instala `xcb-util-cursor`. Si aparece pero queda detrás del juego, abre un issue en el repo con tu escritorio; mientras, la temperatura sigue en la bandeja y en la barra de la app. |
| En red no conecta | Celular y PC en la misma red. Si el celular se reinició, conecta el cable y usa *Activar red con el cable* otra vez. |
