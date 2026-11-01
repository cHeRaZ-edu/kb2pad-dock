"""
HUD de kb2pad: un cuadro chico encima de la ventana del juego (estilo MangoHud) con datos del
celular: temperatura, estado termico, bateria, FPS del video y perfil.

Corre como proceso aparte (kb2pad --hud / python app.py --hud) y recibe por stdin una linea JSON
por actualizacion:

    {"show": true, "lines": ["CEL 41.3 C", ...], "level": 0-3, "rect": [x, y, w, h], "corner": "tl"}

rect es la ventana del juego (si no se conoce, se usa la pantalla). En Linux con Wayland la GUI lo
lanza con QT_QPA_PLATFORM=xcb: una ventana Wayland no puede colocarse encima de otra, pero en X11
(XWayland) si, igual que la ventana de scrcpy. No recibe clics ni toma el foco.
"""
import json
import os
import sys
import threading

from PyQt6.QtCore import QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

IS_WINDOWS = os.name == "nt"
LEVEL_COLORS = ["#e9edf2", "#ffd24d", "#ff9a3c", "#ff5050"]
MARGIN = 14


class _Reader(QObject):
    line = pyqtSignal(str)
    eof = pyqtSignal()

    def run(self):
        # bytes + utf-8: en Windows stdin usa la codificacion del sistema y el "°" llegaria mal
        stream = getattr(sys.stdin, "buffer", None) or sys.stdin
        try:
            for raw in stream:
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                if text.strip():
                    self.line.emit(text)
        except (OSError, ValueError, AttributeError):
            pass
        self.eof.emit()


class Hud(QWidget):
    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool |
                 Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        if not IS_WINDOWS:
            # X11: ventana sin gestor de ventanas (override-redirect): siempre encima y nunca toma el foco
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("kb2pad-hud")
        self.font_ = QFont()
        self.font_.setFamilies(["Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Noto Sans Mono", "monospace"])
        self.font_.setStyleHint(QFont.StyleHint.Monospace)
        self.font_.setPointSize(10)
        self.font_.setBold(True)
        self.lines, self.level = [], 0
        # algunas ventanas "siempre encima" (la del juego al enfocarla) pueden taparlo: se vuelve a subir
        self.raiser = QTimer(self)
        self.raiser.setInterval(1500)
        self.raiser.timeout.connect(lambda: self.isVisible() and self.raise_())
        self.raiser.start()

    def apply(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not msg.get("show") or not msg.get("lines"):
            self.hide()
            return
        self.lines = [str(x) for x in msg["lines"]][:8]
        self.level = max(0, min(3, int(msg.get("level", 0))))
        fm = QFontMetrics(self.font_)
        w = max(fm.horizontalAdvance(t) for t in self.lines) + 20
        h = fm.height() * len(self.lines) + 12
        rect = msg.get("rect")
        if not rect:
            scr = QGuiApplication.primaryScreen().geometry()
            rect = (scr.x(), scr.y(), scr.width(), scr.height())
        x, y, rw, rh = (int(v) for v in rect)
        corner = msg.get("corner", "tl")
        px = x + MARGIN if corner in ("tl", "bl") else x + rw - w - MARGIN
        py = y + MARGIN if corner in ("tl", "tr") else y + rh - h - MARGIN
        self.setGeometry(px, py, w, h)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        border = QColor(LEVEL_COLORS[self.level]) if self.level else QColor(0, 0, 0, 0)
        p.setBrush(QColor(12, 14, 18, 175))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        if self.level:
            p.setPen(border)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        p.setFont(self.font_)
        fm = QFontMetrics(self.font_)
        y = 6 + fm.ascent()
        for i, text in enumerate(self.lines):
            p.setPen(QColor(LEVEL_COLORS[self.level] if i == 0 else "#c9d1d9"))
            p.drawText(10, y, text)
            y += fm.height()


def main(argv=None):
    if IS_WINDOWS:
        try:
            import engine_win      # el .exe sin consola puede tener stdin en None: lo recupera
            engine_win._fix_stdio()
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(list(argv or sys.argv[:1]))
    app.setQuitOnLastWindowClosed(False)
    hud = Hud()
    reader = _Reader()
    reader.line.connect(hud.apply)
    reader.eof.connect(app.quit)
    threading.Thread(target=reader.run, daemon=True).start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
