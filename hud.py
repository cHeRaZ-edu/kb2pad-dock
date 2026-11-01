"""
HUD de kb2pad: un cuadro chico encima de la ventana del juego (estilo MangoHud) con datos del
celular: temperatura, estado termico, bateria, FPS del video y perfil.

Corre como proceso aparte (kb2pad --hud / python app.py --hud) y recibe por stdin una linea JSON
por actualizacion:

    {"show": true, "rows": [[["CEL ", "key"], ["41.3°C", "#3fbf3f"]], ...], "level": 0-3,
     "rect": [x, y, w, h], "corner": "tl", "layout": "vertical", "theme": {...}, "font_size": 10}

Cada renglon es una lista de tramos [texto, color]; color "key"/"text" = los del tema.

rect es la ventana del juego (si no se conoce, se usa la pantalla). En Linux con Wayland la GUI lo
lanza con QT_QPA_PLATFORM=xcb: una ventana Wayland no puede colocarse encima de otra, pero en X11
(XWayland) si, igual que la ventana de scrcpy. No recibe clics ni toma el foco.
"""
import json
import os
import sys
import threading

from PyQt6.QtCore import QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

IS_WINDOWS = os.name == "nt"
LEVEL_COLORS = ["#e9edf2", "#ffd24d", "#ff9a3c", "#ff5050"]
DEFAULT_THEME = {"bg": [12, 14, 18, 175], "key": "#8b949e", "text": "#e6edf3", "outline": False}
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
        self.font_.setBold(True)
        self.rows, self.level, self.theme = [], 0, dict(DEFAULT_THEME)
        # algunas ventanas "siempre encima" (la del juego al enfocarla) pueden taparlo: se vuelve a subir
        self.raiser = QTimer(self)
        self.raiser.setInterval(1500)
        self.raiser.timeout.connect(lambda: self.isVisible() and self.raise_())
        self.raiser.start()

    def _color(self, token):
        if token == "key":
            return QColor(self.theme.get("key", "#8b949e"))
        if token in ("text", None, ""):
            return QColor(self.theme.get("text", "#e6edf3"))
        return QColor(token)

    def apply(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        rows = msg.get("rows")
        if rows is None and msg.get("lines"):                      # formato viejo: texto plano
            rows = [[[str(t), "text"]] for t in msg["lines"]]
        if not msg.get("show") or not rows:
            self.hide()
            return
        self.theme = {**DEFAULT_THEME, **(msg.get("theme") or {})}
        self.font_.setPointSize(max(7, min(24, int(msg.get("font_size", 10)))))
        rows = [[(str(seg[0]), seg[1] if len(seg) > 1 else "text") for seg in row] for row in rows[:12]]
        fm = QFontMetrics(self.font_)
        rect = msg.get("rect")
        if not rect:
            scr = QGuiApplication.primaryScreen().geometry()
            rect = (scr.x(), scr.y(), scr.width(), scr.height())
        x, y, rw, rh = (int(v) for v in rect)

        def width(row):
            return sum(fm.horizontalAdvance(t) for t, _c in row)

        if msg.get("layout") == "horizontal" and len(rows) > 1:
            # todo en un renglon; si no cabe en la ventana del juego, salta al siguiente
            limit = max(200, rw - 2 * MARGIN - 22)
            sep = ("  |  ", "key")
            packed, cur = [], []
            for row in rows:
                cand = cur + [sep] + row if cur else list(row)
                if cur and width(cand) > limit:
                    packed.append(cur)
                    cur = list(row)
                else:
                    cur = cand
            if cur:
                packed.append(cur)
            rows = packed
        self.rows = rows
        self.level = max(0, min(3, int(msg.get("level", 0))))
        w = max(width(row) for row in rows) + 22
        h = fm.height() * len(rows) + 12
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
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        bg = self.theme.get("bg") or [12, 14, 18, 175]
        if len(bg) == 4 and bg[3] > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(*bg))
            p.drawRoundedRect(box, 7, 7)
        if self.level:
            p.setPen(QPen(QColor(LEVEL_COLORS[self.level]), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 7, 7)
        fm = QFontMetrics(self.font_)
        p.setFont(self.font_)
        outline = bool(self.theme.get("outline"))
        y = 6 + fm.ascent()
        for row in self.rows:
            x = 11
            for text, token in row:
                color = self._color(token)
                if outline:
                    path = QPainterPath()
                    path.addText(x, y, self.font_, text)
                    p.setPen(QPen(QColor(0, 0, 0, 230), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                  Qt.PenJoinStyle.RoundJoin))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(path)
                    p.fillPath(path, color)
                else:
                    p.setPen(color)
                    p.drawText(x, y, text)
                x += fm.horizontalAdvance(text)
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
