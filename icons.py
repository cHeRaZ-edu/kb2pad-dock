"""
Iconos de los modos, dibujados con QPainter (sin archivos ni plugins de imagen).

    mode_icon("sword" | "crossbow" | "bow" | "gamepad" | "keyboard" | "letter", letter="M", active=True) -> QIcon

Se dibujan en una caja de 64x64 y se escalan; llevan contorno oscuro para verse
en barras claras y oscuras.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTransform

ICON_KINDS = [("gamepad", "Mando"), ("sword", "Espada"), ("crossbow", "Ballesta"),
              ("bow", "Arco"), ("letter", "Letra")]

OUTLINE = QColor("#1b1e24")
STEEL = QColor("#cfd6de")
STEEL_DARK = QColor("#8a949e")
GOLD = QColor("#d9a441")
WOOD = QColor("#9a6233")
WOOD_DARK = QColor("#6e4322")
WOOD_LIGHT = QColor("#c07a3c")
METAL = QColor("#4a5260")
STRING = QColor("#e8e2d0")
PAD = QColor("#e9edf2")
GREY = QColor("#9aa0a8")


def _pen(width=2.2, color=OUTLINE):
    p = QPen(color, width)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    return p


def _poly(*pts):
    path = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def _fill(p, path, color, width=2.2):
    p.setPen(_pen(width))
    p.setBrush(QBrush(color))
    p.drawPath(path)


# ---------------------------------------------------------------- dibujos (caja 64x64)
def _line(p, a, b, color, width, outline=True):
    """Linea con contorno oscuro (se ve en fondo claro y oscuro)."""
    if outline:
        p.setPen(_pen(width + 2.2))
        p.drawLine(QPointF(*a), QPointF(*b))
    p.setPen(_pen(width, color))
    p.drawLine(QPointF(*a), QPointF(*b))


def _band(p, path, color, width):
    """Trazo grueso con contorno: para palas de arco."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(width + 2.6))
    p.drawPath(path)
    p.setPen(_pen(width, color))
    p.drawPath(path)


def _sword(p, c):
    """Mandoble en diagonal: hoja larga y ancha con canal, guarda ancha, mango largo a dos manos."""
    p.save()
    p.translate(32, 32)
    p.rotate(45)
    p.translate(-32, -32)
    # hoja (punta arriba)
    _fill(p, _poly((32, -9), (39.5, 1), (39.5, 37), (24.5, 37), (24.5, 1)), c(STEEL))
    p.setPen(_pen(1.8, c(STEEL_DARK)))
    p.drawLine(QPointF(32, 2), QPointF(32, 34))                  # canal
    # guarda
    _fill(p, _poly((11, 37), (53, 37), (50.5, 43), (13.5, 43)), c(GOLD))
    # mango largo (dos manos)
    _fill(p, _poly((28.8, 43), (35.2, 43), (35.2, 63), (28.8, 63)), c(WOOD_DARK))
    p.setPen(_pen(1.3, c(WOOD)))
    for y in (47, 51, 55, 59):
        p.drawLine(QPointF(29.6, y), QPointF(34.4, y))
    # pomo
    p.setPen(_pen())
    p.setBrush(QBrush(c(GOLD)))
    p.drawEllipse(QPointF(32, 66), 3.8, 3.8)
    p.restore()


def _crossbow(p, c):
    """Ballesta de perfil con culata de escopeta, empuñadura de pistola y arco al frente."""
    # cuerda (detras del arco): de las puntas a la nuez
    _line(p, (50, 10), (34, 29), c(STRING), 1.6)
    _line(p, (50, 52), (34, 33), c(STRING), 1.6)
    # culata tipo escopeta (cantonera, caida y garganta) + empuñadura de pistola
    stock = QPainterPath(QPointF(2.5, 26))
    stock.lineTo(6, 25)
    stock.cubicTo(13, 26.5, 19, 27, 25, 27)          # lomo de la culata
    stock.lineTo(25, 35)
    stock.lineTo(27, 35)
    stock.lineTo(30.5, 47)                            # empuñadura hacia abajo
    stock.lineTo(24.5, 48)
    stock.lineTo(21.5, 37.5)
    stock.cubicTo(16, 38, 9, 40.5, 4.5, 44)           # parte baja de la culata
    stock.lineTo(2, 43)
    stock.closeSubpath()
    _fill(p, stock, c(WOOD))
    p.setPen(_pen(1.4, c(WOOD_DARK)))
    p.drawLine(QPointF(4.3, 27.5), QPointF(3.8, 42))  # cantonera
    # cuerpo / riel
    _fill(p, _poly((22, 26.5), (56, 26.5), (58, 29), (58, 34), (22, 35)), c(METAL))
    # canon
    _fill(p, _poly((56, 28.5), (62.5, 28.5), (62.5, 32.5), (56, 32.5)), c(METAL), 1.8)
    # guardamonte
    p.setPen(_pen(2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    guard = QPainterPath(QPointF(30, 35))
    guard.cubicTo(30, 41.5, 37.5, 41.5, 37.5, 35)
    p.drawPath(guard)
    # arco (palas) al frente, visto de lado
    prod = QPainterPath(QPointF(49, 7))
    prod.cubicTo(59, 17, 59, 45, 49, 55)
    prod.cubicTo(54, 45, 54, 17, 49, 7)
    _fill(p, prod, c(STEEL_DARK), 2.2)


def _bow(p, c):
    """Arco recurvo de pie: palas rectas inclinadas (trapecio levantado), puntas recurvas, sin flecha."""
    # cuerda recta de punta a punta (lado largo del trapecio)
    _line(p, (47, 6.5), (47, 57.5), c(STRING), 1.6)
    # palas: linea central gruesa
    limbs = QPainterPath(QPointF(49.5, 4.5))
    limbs.cubicTo(45.5, 2, 40.5, 3, 39.5, 8)          # punta recurva superior
    limbs.lineTo(18.5, 27)                            # pala superior inclinada
    limbs.cubicTo(15.5, 29.5, 15.5, 34.5, 18.5, 37)   # empuñadura (lado corto)
    limbs.lineTo(39.5, 56)                            # pala inferior inclinada
    limbs.cubicTo(40.5, 61, 45.5, 62, 49.5, 59.5)     # punta recurva inferior
    _band(p, limbs, c(WOOD_LIGHT), 5.2)
    # empuñadura forrada
    grip = QPainterPath(QPointF(17.3, 28.6))
    grip.cubicTo(16.2, 30.5, 16.2, 33.5, 17.3, 35.4)
    p.setPen(_pen(5.6, c(WOOD_DARK)))
    p.drawPath(grip)


def _gamepad(p, c):
    body = QPainterPath()
    body.moveTo(18, 20)
    body.lineTo(46, 20)
    body.cubicTo(56, 20, 61, 30, 61, 40)
    body.cubicTo(61, 50, 54, 52, 50, 47)
    body.lineTo(45, 41)
    body.lineTo(19, 41)
    body.lineTo(14, 47)
    body.cubicTo(10, 52, 3, 50, 3, 40)
    body.cubicTo(3, 30, 8, 20, 18, 20)
    body.closeSubpath()
    _fill(p, body, c(PAD))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(c(METAL)))
    p.drawRoundedRect(QRectF(13, 27, 10, 3.6), 1, 1)       # cruceta
    p.drawRoundedRect(QRectF(16.2, 23.8, 3.6, 10), 1, 1)
    for (x, y), col in (((45, 25.5), "#3fae6a"), ((50, 29.5), "#d9534f"),
                        ((40, 29.5), "#3b82c4"), ((45, 33.5), "#e0b33c")):
        p.setBrush(QBrush(c(QColor(col))))
        p.drawEllipse(QPointF(x, y), 2.6, 2.6)


def _keyboard(p, c):
    """Teclado (modo chat)."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(3, 17, 58, 32), 5, 5)
    _fill(p, body, c(PAD))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(c(METAL)))
    for row, (y, n, x0) in enumerate(((22, 9, 7.5), (29, 8, 10.5), (36, 7, 13.5))):
        for i in range(n):
            p.drawRoundedRect(QRectF(x0 + i * 5.6, y, 4.2, 4.6), 1, 1)
    p.drawRoundedRect(QRectF(17, 42.5, 30, 3.6), 1, 1)          # espacio


def _letter(p, c, letter):
    p.setPen(_pen())
    p.setBrush(QBrush(c(METAL)))
    p.drawRoundedRect(QRectF(6, 6, 52, 52), 12, 12)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(36)
    p.setFont(f)
    p.setPen(QPen(c(PAD)))
    p.drawText(QRectF(6, 6, 52, 52), Qt.AlignmentFlag.AlignCenter, (letter or "?")[:1].upper())


_DRAW = {"sword": _sword, "crossbow": _crossbow, "bow": _bow, "gamepad": _gamepad, "keyboard": _keyboard}


def render(kind, size=64, letter="", active=True):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setTransform(QTransform().scale(size / 64.0, size / 64.0))

    def c(col):
        if active:
            return col
        g = int(0.6 * col.lightness() + 0.4 * GREY.lightness())
        return QColor(g, g, g)

    if kind == "letter":
        _letter(p, c, letter)
    else:
        _DRAW.get(kind, _gamepad)(p, c)
    p.end()
    return pm


def mode_icon(kind, letter="", active=True):
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64, 128):
        icon.addPixmap(render(kind, size, letter, active))
    return icon
