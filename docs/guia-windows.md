# Guía paso a paso: Windows

Al terminar vas a jugar en tu PC con teclado y mouse, el juego corriendo en tu celular y la
pantalla del celular apagada.

**Necesitas:** Windows 10 u 11 de 64 bits, un celular Android, un cable USB de datos (no solo de
carga) y un juego que acepte control.

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

1. **Descarga kb2pad-dock.**
   En [Releases](https://github.com/cHeRaZ-edu/kb2pad-dock/releases) baja
   `kb2pad-dock-v0.1.0-windows-x64.zip` y **descomprímelo** (por ejemplo en `C:\kb2pad-dock`).
   No lo abras desde dentro del zip.
2. **Descarga scrcpy.**
   En [scrcpy Releases](https://github.com/Genymobile/scrcpy/releases) baja el zip
   `scrcpy-win64-…` (versión 2.7 o más reciente) y descomprímelo (por ejemplo en `C:\scrcpy`).
   Esa carpeta trae `scrcpy.exe` y `adb.exe`.
3. **Abre `kb2pad.exe`.**
   Si Windows SmartScreen dice *"Windows protegió su PC"*: clic en *Más información* →
   *Ejecutar de todas formas*. Aparece porque el `.exe` no está firmado.
4. **Instala el driver del control virtual.**
   En la app: **Archivo → Instalar ViGEmBus**. Acepta los permisos de administrador y sigue el
   instalador. Es una sola vez.

## Parte 3. Configurar (una sola vez)

Todo esto se hace en la pestaña **Juego (scrcpy)**:

![Pestaña Juego en Windows](img/windows-juego.png)

1. **Carpeta de scrcpy**: clic en *Buscar…* y elige la carpeta donde descomprimiste scrcpy.
2. **Serial (adb)**: clic en *Detectar*. Debe aparecer tu celular. Si no aparece, revisa el
   cable, la depuración USB y el aviso de "¿Permitir depuración USB?" en el celular.
3. **Abrir la app en el celular**: ya viene con el paquete de Monster Hunter Outlanders
   (`com.garena.game.mho`). Para otro juego, conecta el celular y busca su paquete con:
   ```bat
   C:\scrcpy\adb.exe shell pm list packages | findstr /i nombre
   ```
4. **Pantalla** → elige tu monitor → **Ajustar a la pantalla**. Calcula el tamaño de la ventana
   para que el juego llene el monitor sin barras negras.
5. Clic en **Guardar** (o `Ctrl+S`).

Los controles se cambian en la pestaña **Botones** (doble clic en una fila para editarla).
Cualquier cambio que guardes se aplica al momento, aunque el control esté corriendo.

## Parte 4. Jugar

1. Con el celular conectado, clic en **Iniciar todo**. La app:
   - inicia el control virtual,
   - abre el juego en el celular,
   - espera a que el celular gire a horizontal,
   - y abre la ventana sin bordes del juego.
2. En el juego, revisa que aparezcan los íconos de botones de control (A, B, LT…). Eso confirma
   que el juego ve el control.
3. **Bloq Mayús** activa el **mouse como cámara**: el cursor se queda quieto y el mouse mueve el
   stick derecho. Presiónalo otra vez para soltar el mouse (en menús, por ejemplo).
4. **F12** pausa kb2pad. Úsalo cuando vayas a escribir en otra ventana, porque kb2pad lee el
   teclado aunque la ventana del juego no tenga el foco.

La tabla de controles por defecto está en el [README](../README.md#controles-por-defecto).

## Parte 5. Apagar la pantalla del celular

scrcpy tiene la opción `--turn-screen-off`, pero en algunos celulares (por ejemplo con HyperOS)
también apaga la imagen que se transmite y la ventana queda en negro. Lo que sí funciona es el
atajo de scrcpy **una vez que el juego ya está en pantalla**:

1. Con el juego ya visible en la ventana, presiona **F12** para pausar kb2pad.
   (La `O` es `RT` en el mapeo, y así no se la mandas al juego.)
2. Haz clic en la ventana del juego para que tenga el foco.
3. Presiona **Alt + O**. La pantalla del celular se apaga y el juego sigue en la ventana.
4. Presiona **F12** otra vez para reanudar kb2pad y sigue jugando.

Para volver a prender la pantalla del celular: **F12**, clic en la ventana, **Alt + Shift + O**,
y **F12** para reanudar.

Si con `Alt + O` la ventana también se pone negra, prende la pantalla con `Alt + Shift + O` y, en
su lugar, baja el brillo del celular al mínimo.

## Parte 6. Terminar

- **Cerrar juego** cierra la ventana de scrcpy (el juego sigue abierto en el celular).
- **Detener control** quita el control virtual.
- Al cerrar la app se cierran los dos.

---

## Problemas comunes

| Qué pasa | Qué hacer |
|---|---|
| Al iniciar el control dice que falta ViGEmBus | **Archivo → Instalar ViGEmBus** y vuelve a iniciar el control. |
| *Detectar* no muestra el celular | Revisa el cable de datos, la depuración USB y acepta el aviso en el celular. Prueba otro puerto USB. |
| El log de scrcpy dice `INJECT_EVENTS` | Xiaomi/POCO/Redmi: activa *Depuración USB (Configuración de seguridad)* y reinicia el celular. |
| El juego no reacciona al teclado | Revisa que el control esté **activo** (no en pausa con F12) y que el juego muestre íconos de control. scrcpy debe ser 2.7 o más reciente. |
| Los botones laterales del mouse no hacen nada | Activa *Mostrar teclas en el log*, presiónalos y mira qué código aparece. Asígnalo en la pestaña Botones con *Capturar*. |
| La ventana no queda donde esperas | Si tu Windows tiene escalado distinto de 100 %, ajusta X, Y, Ancho y Alto a mano en la pestaña Juego. |
| SmartScreen o el antivirus bloquean `kb2pad.exe` | El `.exe` no está firmado y usa hooks de teclado para leer las teclas. Puedes revisar el código en este repo o compilarlo tú mismo (ver el README). |
