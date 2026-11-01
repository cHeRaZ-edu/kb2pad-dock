#!/usr/bin/env python3
"""
kb2pad - GUI para configurar el control virtual (teclado + mouse -> Xbox 360)
y lanzar el juego con scrcpy en ventana sin bordes.

    python app.py

Linux (CachyOS): sudo pacman -S python-pyqt6 python-evdev scrcpy android-tools xdotool
Windows: kb2pad.exe (necesita el driver ViGEmBus y scrcpy para Windows)
"""
import copy
import glob
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (QEvent, QLibraryInfo, QLocale, QPoint, QProcess, QProcessEnvironment, QSize, Qt, QTimer,
                          QTranslator, QUrl, pyqtSignal)
from PyQt6.QtGui import (QAction, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence,
                         QPainter)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QSpinBox, QSplitter, QStyle, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

import config as C
import icons
import platform_tools as PT
from keycodes import win_scan_to_code

IS_WINDOWS = os.name == "nt"
FROZEN = getattr(sys, "frozen", False)
HERE = Path(__file__).resolve().parent
ENGINE = HERE / "engine.py"

QT_MOUSE = {
    Qt.MouseButton.LeftButton: "BTN_LEFT",
    Qt.MouseButton.RightButton: "BTN_RIGHT",
    Qt.MouseButton.MiddleButton: "BTN_MIDDLE",
    Qt.MouseButton.BackButton: "BTN_SIDE",
    Qt.MouseButton.ForwardButton: "BTN_EXTRA",
    Qt.MouseButton.TaskButton: "BTN_TASK",
}


def needs_pkexec():
    """Linux: True si el usuario no puede leer /dev/input o escribir /dev/uinput."""
    if IS_WINDOWS:
        return False
    if not os.access("/dev/uinput", os.R_OK | os.W_OK):
        return True
    events = glob.glob("/dev/input/event*")
    return not any(os.access(p, os.R_OK) for p in events)


def no_console(proc):
    """En Windows, que el QProcess no abra ventana de consola (scrcpy, adb)."""
    if not IS_WINDOWS:
        return

    def modifier(args):
        args.flags |= PT.NO_WINDOW

    try:
        proc.setCreateProcessArgumentsModifier(modifier)
    except AttributeError:
        pass


def vigem_installer():
    base = Path(getattr(sys, "_MEIPASS", HERE)) if FROZEN else HERE
    return base / "vigem" / "ViGEmBusSetup_x64.msi"


# ================================================================ captura de teclas
class CaptureDialog(QDialog):
    """Espera una tecla o boton del mouse y regresa su nombre evdev."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capturar tecla")
        self.setMinimumSize(380, 170)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.result_name = None
        lay = QVBoxLayout(self)
        msg = QLabel("Presiona una tecla, un boton del mouse o gira la rueda\n"
                     "(con el cursor dentro de esta ventana)\n\n"
                     "Se cancela solo en 6 segundos.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = msg.font()
        f.setPointSize(f.pointSize() + 1)
        msg.setFont(f)
        lay.addWidget(msg)
        QTimer.singleShot(6000, self.reject)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.activateWindow()
        self.setFocus()

    def event(self, ev):
        t = ev.type()
        if t == QEvent.Type.ShortcutOverride:
            ev.accept()
            return True
        if t == QEvent.Type.KeyPress:
            if ev.isAutoRepeat():
                return True
            if IS_WINDOWS:
                sc = ev.nativeScanCode()
                code = win_scan_to_code(sc & 0xFF, sc & 0x100, ev.nativeVirtualKey())
                name = C.code_to_name(code) if code else None
            else:
                name = C.code_to_name(ev.nativeScanCode() - 8)   # XKB keycode = evdev + 8
            if name:
                self.result_name = name
                self.accept()
            return True
        if t == QEvent.Type.MouseButtonPress:
            name = QT_MOUSE.get(ev.button())
            if name:
                self.result_name = name
                self.accept()
            return True
        if t == QEvent.Type.Wheel:
            d = ev.angleDelta()
            if abs(d.y()) >= abs(d.x()) and d.y():
                self.result_name = "WHEEL_UP" if d.y() > 0 else "WHEEL_DOWN"
            elif d.x():
                self.result_name = "WHEEL_LEFT" if d.x() > 0 else "WHEEL_RIGHT"
            if self.result_name:
                self.accept()
            return True
        return super().event(ev)


class KeyField(QWidget):
    """Combo editable con todos los nombres + boton para capturar."""
    changed = pyqtSignal()

    def __init__(self, name="", parent=None, allow_empty=False):
        super().__init__(parent)
        self.allow_empty = allow_empty
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.addItems(C.INPUT_NAMES)
        self.combo.setMinimumWidth(170)
        comp = self.combo.completer()
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.label = QLabel()
        self.label.setMinimumWidth(110)
        btn = QPushButton("Capturar")
        btn.clicked.connect(self.capture)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.label)
        lay.addWidget(btn)
        self.combo.currentTextChanged.connect(self._update)
        self.set_value(name)

    def value(self):
        return self.combo.currentText().strip().upper()

    def set_value(self, name):
        self.combo.setCurrentText(name or "")
        self._update()

    def _update(self):
        n = self.value()
        if not n and self.allow_empty:
            self.label.setText("(sin atajo)")
            self.label.setStyleSheet("color: gray;")
        elif C.is_valid_input(n):
            self.label.setText(C.input_label(n))
            self.label.setStyleSheet("")
        else:
            self.label.setText("desconocida")
            self.label.setStyleSheet("color: #d9534f;")
        self.changed.emit()

    def capture(self):
        dlg = CaptureDialog(self)
        if dlg.exec() and dlg.result_name:
            self.set_value(dlg.result_name)


class OutputPicker(QWidget):
    """Casillas para elegir salidas del control."""
    changed = pyqtSignal()

    def __init__(self, values=(), parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        self.boxes = {}
        for i, name in enumerate(C.OUTPUTS):
            cb = QCheckBox(C.output_label(name))
            cb.toggled.connect(self.changed.emit)
            self.boxes[name] = cb
            grid.addWidget(cb, i // 6, i % 6)
        self.set_values(values)

    def values(self):
        return [n for n in C.OUTPUTS if self.boxes[n].isChecked()]

    def set_values(self, values):
        for n, cb in self.boxes.items():
            cb.setChecked(n in values)


# ================================================================ dialogo de asignacion
class BindingDialog(QDialog):
    def __init__(self, b, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asignacion")
        self.setMinimumWidth(620)
        form = QFormLayout(self)

        self.input = KeyField(b.get("input", ""))
        form.addRow("Tecla / boton:", self.input)

        self.outputs = OutputPicker(b.get("outputs", []))
        form.addRow("Salida(s):", self.outputs)
        form.addRow("", self._hint("Varias salidas se presionan juntas (ej. Y + B)."))

        self.modifier = OutputPicker(b.get("modifier", []))
        form.addRow("Modificador:", self.modifier)
        form.addRow("", self._hint("Combo: el modificador entra primero y la salida despues "
                                   "(ej. LT y luego B = LT+B)."))

        radial_row = QHBoxLayout()
        self.radial = QCheckBox("Menu radial con el mouse mientras se sostiene")
        self.radial.setChecked(bool(b.get("radial")))
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0.0, 3.0)
        self.hold.setSingleStep(0.05)
        self.hold.setDecimals(2)
        self.hold.setSuffix(" s")
        self.hold.setValue(float(b.get("radial_hold", 0.0)))
        radial_row.addWidget(self.radial)
        radial_row.addWidget(QLabel("entra tras sostener:"))
        radial_row.addWidget(self.hold)
        radial_row.addStretch()
        form.addRow("Radial:", radial_row)
        form.addRow("", self._hint("0 s = radial inmediato. Con espera, tocar rapido manda "
                                   "el boton normal y sostener activa el radial."))

        self.camera_only = QCheckBox("Solo cuando el mouse es camara")
        self.camera_only.setChecked(bool(b.get("camera_only")))
        form.addRow("Modo:", self.camera_only)

        self.note = QLineEdit(b.get("note", ""))
        form.addRow("Nota:", self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.modifier.changed.connect(self._sync)
        self.radial.toggled.connect(self._sync)
        self.camera_only.toggled.connect(self._sync)
        self._sync()

    @staticmethod
    def _hint(text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: gray;")
        return lbl

    def _sync(self):
        cam = self.camera_only.isChecked()
        combo = bool(self.modifier.values())
        self.modifier.setEnabled(not cam)
        self.radial.setEnabled(not cam and not combo)
        self.hold.setEnabled(self.radial.isEnabled() and self.radial.isChecked())

    def _accept(self):
        if not C.is_valid_input(self.input.value()):
            QMessageBox.warning(self, "Asignacion", "La tecla no es valida.")
            return
        if not self.outputs.values():
            QMessageBox.warning(self, "Asignacion", "Elige al menos una salida.")
            return
        self.accept()

    def binding(self):
        cam = self.camera_only.isChecked()
        mods = [] if cam else self.modifier.values()
        return C.binding(
            self.input.value(),
            self.outputs.values(),
            note=self.note.text().strip(),
            modifier=mods,
            radial=self.radial.isChecked() and not cam and not mods,
            hold=round(self.hold.value(), 2),
            camera_only=cam,
        )


# ================================================================ pestanas
def mode_qicon(mode, active=True):
    """Icono de un modo: la imagen que eligio el usuario o el dibujo por defecto."""
    path = (mode or {}).get("icon_file") or ""
    if path and Path(path).is_file():
        icon = QIcon(path)
        if not icon.isNull():
            if active:
                return icon
            gray = QIcon()
            for size in (16, 22, 24, 32, 48, 64):
                gray.addPixmap(icon.pixmap(size, size, QIcon.Mode.Disabled))
            return gray
    kind = (mode or {}).get("icon") or "gamepad"
    return icons.mode_icon(kind, letter=(mode or {}).get("name", "?"), active=active)


class BindingsTab(QWidget):
    """Modos como plantillas: cada uno tiene su tabla completa, atajo (Alt + tecla) e icono."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.modes = []              # [{"name", "hotkey", "icon", "icon_file", "bindings"}]
        self.start_mode = ""
        self._loading = False
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Modo:"))
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(190)
        self.mode_combo.setIconSize(QSize(22, 22))
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        bar.addWidget(self.mode_combo)
        bar.addWidget(QLabel("  Atajo: Alt +"))
        self.hotkey = KeyField()
        self.hotkey.changed.connect(self._hotkey_changed)
        bar.addWidget(self.hotkey)
        self.btn_icon = QPushButton("Icono")
        self.btn_icon.setIconSize(QSize(22, 22))
        self.icon_menu = QMenu(self)
        for kind, label in icons.ICON_KINDS:
            act = self.icon_menu.addAction(icons.mode_icon(kind, letter="A"), label)
            act.triggered.connect(lambda _c=False, k=kind: self._set_icon(kind=k))
        self.icon_menu.addSeparator()
        self.icon_menu.addAction("Imagen propia (PNG, SVG, ICO)...").triggered.connect(self._pick_icon_file)
        self.btn_icon.setMenu(self.icon_menu)
        bar.addWidget(self.btn_icon)
        bar.addStretch()
        lay.addLayout(bar)

        bar = QHBoxLayout()
        for text, slot in (("Nuevo modo", self.new_mode), ("Renombrar", self.rename_mode),
                           ("Eliminar modo", self.delete_mode), ("Restaurar plantilla", self.restore_mode)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
            if text == "Restaurar plantilla":
                self.btn_restore = b
            elif text == "Eliminar modo":
                self.btn_delete = b
        bar.addSpacing(20)
        bar.addWidget(QLabel("Al iniciar el control:"))
        self.start_combo = QComboBox()
        self.start_combo.currentTextChanged.connect(self._start_changed)
        bar.addWidget(self.start_combo)
        bar.addStretch()
        lay.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Tecla", "Salida", "Modificador", "Tipo", "Nota"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        for col in range(4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.edit)
        lay.addWidget(self.table)

        row = QHBoxLayout()
        for text, slot in (("Agregar", self.add), ("Editar", self.edit),
                           ("Duplicar", self.duplicate), ("Eliminar", self.remove),
                           ("Subir", lambda: self.move(-1)), ("Bajar", lambda: self.move(1)),
                           ("Copiar a todos los modos", self.copy_to_all)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

    # ---------- datos ----------
    def load(self, cfg):
        self.modes = cfg["modes"]
        self.start_mode = cfg.get("start_mode") or (self.modes[0]["name"] if self.modes else "")
        self._fill_modes(0)

    def store(self, cfg):
        cfg["modes"] = self.modes
        cfg["start_mode"] = self.start_mode

    def mode(self):
        i = self.mode_combo.currentIndex()
        return self.modes[i] if 0 <= i < len(self.modes) else None

    @property
    def bindings(self):
        m = self.mode()
        return m["bindings"] if m else []

    def _label(self, m):
        return m["name"] + (f"   (Alt+{C.input_label(m['hotkey'])})" if m.get("hotkey") else "")

    def _fill_modes(self, select):
        self._loading = True
        self.mode_combo.clear()
        for m in self.modes:
            self.mode_combo.addItem(mode_qicon(m), self._label(m))
        self.start_combo.clear()
        names = [m["name"] for m in self.modes]
        self.start_combo.addItems(names)
        if self.start_mode not in names and names:
            self.start_mode = names[0]
        self.start_combo.setCurrentText(self.start_mode)
        self.mode_combo.setCurrentIndex(max(0, min(select, len(self.modes) - 1)))
        self._loading = False
        self._mode_changed()

    def _mode_changed(self, *_):
        if self._loading:
            return
        m = self.mode()
        self._loading = True
        self.hotkey.set_value(m.get("hotkey", "") if m else "")
        self._loading = False
        self.btn_icon.setIcon(mode_qicon(m) if m else QIcon())
        self.btn_restore.setEnabled(bool(m) and C.default_mode(m["name"]) is not None)
        self.btn_delete.setEnabled(len(self.modes) > 1)
        self.refresh()

    def _refresh_mode_item(self):
        m = self.mode()
        if not m:
            return
        i = self.mode_combo.currentIndex()
        self._loading = True
        self.mode_combo.setItemText(i, self._label(m))
        self.mode_combo.setItemIcon(i, mode_qicon(m))
        self._loading = False
        self.btn_icon.setIcon(mode_qicon(m))

    def _hotkey_changed(self):
        if self._loading:
            return
        value = self.hotkey.value()
        m = self.mode()
        if not m or (value and not C.is_valid_input(value)):
            return
        m["hotkey"] = value
        self._refresh_mode_item()
        self.changed.emit()

    def _set_icon(self, kind=None, path=""):
        m = self.mode()
        if not m:
            return
        if kind:
            m["icon"] = kind
        m["icon_file"] = path
        self._refresh_mode_item()
        self.changed.emit()

    def _pick_icon_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Icono del modo", "",
                                              "Imagenes (*.png *.svg *.ico *.jpg *.jpeg *.webp)")
        if path:
            if QIcon(path).isNull():
                QMessageBox.warning(self, "Icono", "No pude abrir esa imagen.")
                return
            self._set_icon(path=path)

    def _start_changed(self, text):
        if self._loading or not text:
            return
        self.start_mode = text
        self.changed.emit()

    # ---------- tabla ----------
    def refresh(self, select=None):
        rows = self.bindings
        self.table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            if b.get("camera_only"):
                kind = "Solo mouse-camara"
            elif b.get("modifier"):
                kind = "Combo"
            elif b.get("radial"):
                hold = float(b.get("radial_hold", 0))
                kind = f"Radial (sostener {hold:.2f} s)" if hold > 0 else "Radial (inmediato)"
            else:
                kind = "Normal"
            cells = [
                f"{C.input_label(b['input'])}   [{b['input']}]",
                " + ".join(C.output_label(o) for o in b.get("outputs", [])),
                " + ".join(C.output_label(o) for o in b.get("modifier", [])),
                kind,
                b.get("note", ""),
            ]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        if select is not None and 0 <= select < len(rows):
            self.table.selectRow(select)

    def current(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    # ---------- acciones sobre asignaciones ----------
    def add(self):
        if not self.mode():
            return
        dlg = BindingDialog(C.binding("", []), self)
        if dlg.exec():
            self.bindings.append(dlg.binding())
            self.refresh(len(self.bindings) - 1)
            self.changed.emit()

    def edit(self, *_):
        r = self.current()
        if r < 0:
            return
        dlg = BindingDialog(self.bindings[r], self)
        if dlg.exec():
            self.bindings[r] = dlg.binding()
            self.refresh(r)
            self.changed.emit()

    def duplicate(self):
        r = self.current()
        if r < 0:
            return
        self.bindings.insert(r + 1, copy.deepcopy(self.bindings[r]))
        self.refresh(r + 1)
        self.changed.emit()

    def remove(self):
        r = self.current()
        if r < 0:
            return
        b = self.bindings[r]
        if QMessageBox.question(self, "Eliminar",
                                f"¿Eliminar {C.input_label(b['input'])} -> "
                                f"{' + '.join(b.get('outputs', []))} del modo {self.mode()['name']}?") \
                == QMessageBox.StandardButton.Yes:
            del self.bindings[r]
            self.refresh(min(r, len(self.bindings) - 1))
            self.changed.emit()

    def move(self, delta):
        r = self.current()
        n = r + delta
        if r < 0 or not (0 <= n < len(self.bindings)):
            return
        self.bindings[r], self.bindings[n] = self.bindings[n], self.bindings[r]
        self.refresh(n)
        self.changed.emit()

    def copy_to_all(self):
        """Pone la asignacion seleccionada igual en los otros modos (reemplaza la misma tecla)."""
        r = self.current()
        cur = self.mode()
        if r < 0 or not cur or len(self.modes) < 2:
            return
        b = self.bindings[r]
        others = [m for m in self.modes if m is not cur]
        if QMessageBox.question(self, "Copiar a todos los modos",
                                f"¿Poner {C.input_label(b['input'])} -> "
                                f"{' + '.join(C.output_label(o) for o in b.get('outputs', []))} "
                                f"igual en {', '.join(m['name'] for m in others)}?") \
                != QMessageBox.StandardButton.Yes:
            return
        key = C.binding_key(b)
        for m in others:
            lst = m["bindings"]
            idx = [i for i, x in enumerate(lst) if C.binding_key(x) == key]
            if idx:
                lst[idx[0]] = copy.deepcopy(b)
                for i in reversed(idx[1:]):
                    del lst[i]
            else:
                lst.append(copy.deepcopy(b))
        self.changed.emit()

    # ---------- modos ----------
    def _ask_name(self, title, current=""):
        name, ok = QInputDialog.getText(self, title, "Nombre del modo:", text=current)
        name = name.strip()
        if not ok or not name:
            return None
        if name in [m["name"] for m in self.modes if m["name"] != current]:
            QMessageBox.warning(self, title, f"Ya hay un modo llamado '{name}'.")
            return None
        return name

    def new_mode(self):
        cur = self.mode()
        name = self._ask_name("Nuevo modo")
        if not name:
            return
        base = copy.deepcopy(cur["bindings"]) if cur else copy.deepcopy(C.COMMON_BINDINGS)
        self.modes.append({"name": name, "hotkey": "", "icon": C.guess_icon(name), "icon_file": "",
                           "bindings": base})
        self._fill_modes(len(self.modes) - 1)
        self.changed.emit()

    def rename_mode(self):
        m = self.mode()
        if not m:
            return
        name = self._ask_name("Renombrar modo", m["name"])
        if not name or name == m["name"]:
            return
        if self.start_mode == m["name"]:
            self.start_mode = name
        m["name"] = name
        self._fill_modes(self.mode_combo.currentIndex())
        self.changed.emit()

    def delete_mode(self):
        m = self.mode()
        if not m or len(self.modes) < 2:
            return
        if QMessageBox.question(self, "Eliminar modo", f"¿Eliminar el modo {m['name']}?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.modes.remove(m)
        if self.start_mode == m["name"]:
            self.start_mode = self.modes[0]["name"]
        self._fill_modes(0)
        self.changed.emit()

    def restore_mode(self):
        m = self.mode()
        d = C.default_mode(m["name"]) if m else None
        if not d:
            return
        if QMessageBox.question(self, "Restaurar plantilla",
                                f"¿Regresar el modo {m['name']} a sus teclas de fabrica?\n"
                                "El atajo y el icono se quedan como estan.") \
                != QMessageBox.StandardButton.Yes:
            return
        m["bindings"] = d["bindings"]
        self.refresh()
        self.changed.emit()


class SticksTab(QWidget):
    changed = pyqtSignal()
    keyboard_settings = pyqtSignal()
    DIRS = ("Arriba", "Abajo", "Izquierda", "Derecha")

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.fields = {}
        for key, title in (("move", "Movimiento (stick izquierdo)"),
                           ("camera", "Camara con teclas (stick derecho)"),
                           ("dpad", "D-pad")):
            box = QGroupBox(title)
            form = QFormLayout(box)
            fs = []
            for d in self.DIRS:
                f = KeyField()
                f.changed.connect(self.changed.emit)
                form.addRow(d + ":", f)
                fs.append(f)
            self.fields[key] = fs
            lay.addWidget(box)

        box = QGroupBox("Teclas especiales")
        form = QFormLayout(box)
        self.pause = KeyField()
        self.mouselook = KeyField()
        self.pause.changed.connect(self.changed.emit)
        self.mouselook.changed.connect(self.changed.emit)
        form.addRow("Pausar / reanudar:", self.pause)
        form.addRow("Mouse como camara on/off:", self.mouselook)
        lay.addWidget(box)

        box = QGroupBox("Chat (escribir en el juego)")
        form = QFormLayout(box)
        self.chat = KeyField(allow_empty=True)
        self.mode_back = KeyField(allow_empty=True)
        self.chat_window = QCheckBox("Mandar lo que escribo al celular (abre una ventana invisible de scrcpy)")
        self.chat_keyboard = QComboBox()
        for key, label in C.CHAT_KEYBOARDS.items():
            self.chat_keyboard.addItem(label, key)
        kb_layout = QPushButton("Idioma del teclado en el celular...")
        kb_layout.setToolTip("Abre en el celular Ajustes > Teclado fisico. Hazlo con el chat activo (Alt+T) "
                             "y elige el teclado 'scrcpy' > Español (Latinoamerica) o el de tu teclado.")
        kb_layout.clicked.connect(self.keyboard_settings.emit)
        for f in (self.chat, self.mode_back):
            f.changed.connect(self.changed.emit)
        self.chat_window.toggled.connect(self.changed.emit)
        self.chat_keyboard.currentIndexChanged.connect(self.changed.emit)
        form.addRow("Entrar al chat:  Alt +", self.chat)
        form.addRow("Volver al modo:  Alt +", self.mode_back)
        form.addRow(self.chat_window)
        row = QHBoxLayout()
        row.addWidget(self.chat_keyboard, 1)
        row.addWidget(kb_layout)
        form.addRow("Teclado:", row)
        hint = QLabel("En el chat el teclado deja de ser control (el mouse sigue igual) y lo que escribes "
                      "llega al celular. Se sale con Alt + el atajo de un modo (Alt+1, Alt+2...) o con "
                      "'Volver al modo', que regresa al modo que tenias. Si haces clic en el juego mientras "
                      "escribes, presiona Alt+T otra vez para seguir escribiendo. Con 'Teclado fisico', la "
                      "primera vez configura el idioma (boton de arriba, con el chat activo) para que salgan "
                      "la ñ y los acentos. En el chat solo cuenta el Alt izquierdo (AltGr escribe @).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        form.addRow(hint)
        lay.addWidget(box)

        box = QGroupBox("Modos y mouse")
        form = QFormLayout(box)
        self.alt_blocks = QCheckBox("Con Alt presionado no mandar nada al juego "
                                    "(Alt+Tab, Alt+O de scrcpy, cambios de modo)")
        self.hide_cursor = QCheckBox("Ocultar el cursor con el mouse como camara")
        for w in (self.alt_blocks, self.hide_cursor):
            w.toggled.connect(self.changed.emit)
            form.addRow(w)
        hint = QLabel("Los modos, sus atajos y sus iconos se editan en la pestaña Botones. "
                      "El icono del modo actual se ve en la bandeja del sistema.")
        hint.setStyleSheet("color: gray;")
        form.addRow(hint)
        lay.addWidget(box)
        lay.addStretch()

    def load(self, cfg):
        for key, fs in self.fields.items():
            for f, name in zip(fs, cfg["sticks"][key]):
                f.set_value(name)
        self.pause.set_value(cfg["special"]["pause"])
        self.mouselook.set_value(cfg["special"]["mouselook"])
        sp = cfg["special"]
        self.alt_blocks.setChecked(bool(sp.get("alt_blocks", True)))
        self.hide_cursor.setChecked(bool(sp.get("hide_cursor", True)))
        self.chat.set_value(sp.get("chat", ""))
        self.mode_back.set_value(sp.get("mode_back", ""))
        self.chat_window.setChecked(bool(sp.get("chat_window", True)))
        self.chat_keyboard.setCurrentIndex(max(0, self.chat_keyboard.findData(sp.get("chat_keyboard", "uhid"))))

    def store(self, cfg):
        for key, fs in self.fields.items():
            cfg["sticks"][key] = [f.value() for f in fs]
        cfg["special"]["pause"] = self.pause.value()
        cfg["special"]["mouselook"] = self.mouselook.value()
        cfg["special"]["alt_blocks"] = self.alt_blocks.isChecked()
        cfg["special"]["hide_cursor"] = self.hide_cursor.isChecked()
        cfg["special"]["chat"] = self.chat.value()
        cfg["special"]["mode_back"] = self.mode_back.value()
        cfg["special"]["chat_window"] = self.chat_window.isChecked()
        cfg["special"]["chat_keyboard"] = self.chat_keyboard.currentData() or "uhid"


def _dspin(lo, hi, step, decimals=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    if suffix:
        s.setSuffix(suffix)
    return s


def _ispin(lo, hi, step=1, suffix=""):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    return s


class MouseTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)

        box = QGroupBox("Mouse como camara (stick derecho)")
        form = QFormLayout(box)
        self.full_speed = _dspin(50, 20000, 50, 0, " cuentas/s")
        self.anti_dz = _dspin(0.0, 0.6, 0.01)
        self.smoothing = _dspin(0.05, 1.0, 0.05)
        self.invert_y = QCheckBox("Invertir eje vertical")
        form.addRow("Velocidad para 100% de stick:", self.full_speed)
        form.addRow("", self._hint("Mas bajo = mas sensible. La velocidad maxima de giro "
                                   "se ajusta en el juego."))
        form.addRow("Anti zona muerta:", self.anti_dz)
        form.addRow("", self._hint("Sube si los movimientos chicos no mueven la camara."))
        form.addRow("Suavizado:", self.smoothing)
        form.addRow("", self._hint("Mas alto = responde mas rapido, menos suave."))
        form.addRow("", self.invert_y)
        lay.addWidget(box)

        box = QGroupBox("Menu radial")
        form = QFormLayout(box)
        self.radius = _dspin(20, 3000, 10, 0, " cuentas")
        self.radial_dz = _dspin(0.05, 0.9, 0.05)
        self.release_delay = _dspin(0.0, 0.5, 0.01, 2, " s")
        form.addRow("Recorrido del centro al borde:", self.radius)
        form.addRow("", self._hint("Mas bajo = eliges con menos movimiento de mouse."))
        form.addRow("Zona muerta:", self.radial_dz)
        form.addRow("Pausa al soltar:", self.release_delay)
        form.addRow("", self._hint("Al soltar se centra el stick (selecciona) y el boton "
                                   "se suelta despues de esta pausa."))
        lay.addWidget(box)

        box = QGroupBox("Combos")
        form = QFormLayout(box)
        self.combo_delay = _dspin(0.0, 0.5, 0.01, 2, " s")
        form.addRow("Espera entre modificador y boton:", self.combo_delay)
        lay.addWidget(box)
        lay.addStretch()

        for w in (self.full_speed, self.anti_dz, self.smoothing, self.radius,
                  self.radial_dz, self.release_delay, self.combo_delay):
            w.valueChanged.connect(self.changed.emit)
        self.invert_y.toggled.connect(self.changed.emit)

    @staticmethod
    def _hint(text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: gray;")
        return lbl

    def load(self, cfg):
        m, r = cfg["mouse"], cfg["radial"]
        self.full_speed.setValue(float(m["full_speed"]))
        self.anti_dz.setValue(float(m["anti_deadzone"]))
        self.smoothing.setValue(float(m["smoothing"]))
        self.invert_y.setChecked(bool(m["invert_y"]))
        self.radius.setValue(float(r["radius"]))
        self.radial_dz.setValue(float(r["deadzone"]))
        self.release_delay.setValue(float(r["release_delay"]))
        self.combo_delay.setValue(float(cfg["combo_delay"]))

    def store(self, cfg):
        cfg["mouse"] = {
            "full_speed": self.full_speed.value(),
            "anti_deadzone": round(self.anti_dz.value(), 3),
            "smoothing": round(self.smoothing.value(), 3),
            "invert_y": self.invert_y.isChecked(),
        }
        cfg["radial"] = {
            "radius": self.radius.value(),
            "deadzone": round(self.radial_dz.value(), 3),
            "release_delay": round(self.release_delay.value(), 3),
        }
        cfg["combo_delay"] = round(self.combo_delay.value(), 3)


class ScrcpyTab(QWidget):
    changed = pyqtSignal()
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)

        box = QGroupBox("Celular")
        form = QFormLayout(box)
        row = QHBoxLayout()
        self.scrcpy_dir = QLineEdit()
        self.scrcpy_dir.setPlaceholderText("vacio = buscar scrcpy y adb en el PATH")
        browse = QPushButton("Buscar...")
        browse.clicked.connect(self.browse_scrcpy)
        row.addWidget(self.scrcpy_dir, 1)
        row.addWidget(browse)
        form.addRow("Carpeta de scrcpy:", row)
        if IS_WINDOWS:
            form.addRow("", self._hint("La carpeta donde descomprimiste scrcpy (trae scrcpy.exe y adb.exe)."))
        row = QHBoxLayout()
        self.serial = QComboBox()
        self.serial.setEditable(True)
        self.serial.setMinimumWidth(220)
        detect = QPushButton("Detectar")
        detect.clicked.connect(self.detect_devices)
        row.addWidget(self.serial, 1)
        row.addWidget(detect)
        form.addRow("Serial (cable):", row)
        form.addRow("", self._hint("Vacio = el unico dispositivo conectado."))
        self.connection = QComboBox()
        self.connection.addItem("Cable USB", "usb")
        self.connection.addItem("Red (Wi-Fi)", "wifi")
        form.addRow("Conexion:", self.connection)
        row = QHBoxLayout()
        self.wifi_address = QLineEdit()
        self.wifi_address.setPlaceholderText("192.168.1.50:5555")
        b_setup = QPushButton("Activar red con el cable")
        b_setup.setToolTip("Con el celular conectado por USB: activa adb por Wi-Fi (adb tcpip 5555), "
                           "lee la IP del celular y se conecta. Despues puedes desconectar el cable.")
        b_setup.clicked.connect(self.wifi_setup)
        b_pair = QPushButton("Emparejar...")
        b_pair.setToolTip("Android 11+: Depuracion inalambrica > Vincular con codigo (sin cable)")
        b_pair.clicked.connect(self.wifi_pair)
        b_conn = QPushButton("Conectar")
        b_conn.clicked.connect(self.wifi_connect)
        row.addWidget(self.wifi_address, 1)
        row.addWidget(b_setup)
        row.addWidget(b_pair)
        row.addWidget(b_conn)
        form.addRow("IP del celular:", row)
        self.wifi_hint = self._hint("Misma red que la PC (mejor 5 GHz) y bitrate de 8M a 16M. "
                                    "Si el celular se reinicia, vuelve a activar la red.")
        form.addRow("", self.wifi_hint)
        lay.addWidget(box)

        box = QGroupBox("Video")
        form = QFormLayout(box)
        self.codec = QComboBox()
        self.codec.addItems(["h265", "h264", "av1"])
        self.bitrate = QLineEdit()
        self.max_fps = _ispin(10, 240, 10, " fps")
        self.no_mipmaps = QCheckBox("Sin mipmaps (mas nitido al reducir)")
        self.stay_awake = QCheckBox("Mantener el celular despierto")
        form.addRow("Codec:", self.codec)
        form.addRow("Bitrate:", self.bitrate)
        form.addRow("FPS maximos:", self.max_fps)
        form.addRow("", self.no_mipmaps)
        form.addRow("", self.stay_awake)
        lay.addWidget(box)

        box = QGroupBox("Ventana")
        grid = QGridLayout(box)
        self.borderless = QCheckBox("Sin bordes")
        self.set_geometry = QCheckBox("Fijar posicion y tamaño")
        self.force_x11 = QCheckBox("Forzar X11 (si en Wayland no respeta la posicion)")
        self.x = _ispin(-10000, 10000)
        self.y = _ispin(-10000, 10000)
        self.w = _ispin(100, 10000)
        self.h = _ispin(100, 10000)
        self.screen = QComboBox()
        for s in QGuiApplication.screens():
            g = s.geometry()
            self.screen.addItem(f"{s.name()}  {g.width()}x{g.height()} @ {g.x()},{g.y()}")
        fit = QPushButton("Ajustar a la pantalla")
        fit.setToolTip("Del tamaño del video del celular, centrada (sin barras negras)")
        fit.clicked.connect(self.fit_to_screen)
        full = QPushButton("Toda la pantalla")
        full.setToolTip("Ventana del tamaño de la pantalla (el video queda centrado con barras negras)")
        full.clicked.connect(self.full_screen)
        grid.addWidget(self.borderless, 0, 0, 1, 2)
        grid.addWidget(self.set_geometry, 0, 2, 1, 2)
        grid.addWidget(QLabel("X:"), 1, 0)
        grid.addWidget(self.x, 1, 1)
        grid.addWidget(QLabel("Y:"), 1, 2)
        grid.addWidget(self.y, 1, 3)
        grid.addWidget(QLabel("Ancho:"), 2, 0)
        grid.addWidget(self.w, 2, 1)
        grid.addWidget(QLabel("Alto:"), 2, 2)
        grid.addWidget(self.h, 2, 3)
        grid.addWidget(QLabel("Pantalla:"), 3, 0)
        grid.addWidget(self.screen, 3, 1, 1, 1)
        grid.addWidget(fit, 3, 2)
        grid.addWidget(full, 3, 3)
        grid.addWidget(self.force_x11, 4, 0, 1, 4)
        self.force_x11.setVisible(not IS_WINDOWS)
        lay.addWidget(box)

        box = QGroupBox("Al iniciar el juego")
        form = QFormLayout(box)
        self.ask_on_start = QCheckBox("Preguntar al iniciar: abrir una app (con buscador) o solo mostrar la pantalla")
        form.addRow(self.ask_on_start)
        row = QHBoxLayout()
        self.launch_app = QCheckBox("Abrir la app en el celular")
        self.package = QLineEdit()
        self.package.setPlaceholderText("com.garena.game.mho")
        row.addWidget(self.launch_app)
        row.addWidget(self.package, 1)
        form.addRow(row)
        self.wait_landscape = QCheckBox("Esperar a que el celular este en horizontal antes de abrir la ventana")
        form.addRow(self.wait_landscape)
        self.rotate_fit = QComboBox()
        for key, label in C.ROTATE_FIT.items():
            self.rotate_fit.addItem(label, key)
        form.addRow("Al pasar a horizontal:", self.rotate_fit)
        form.addRow("", self._hint("Se revisa todo el tiempo que la ventana este abierta: si sales del juego "
                                   "y vuelves, la ventana se acomoda sola"
                                   + ("." if IS_WINDOWS else " (necesita xdotool; en Wayland abre scrcpy con X11).")))
        lay.addWidget(box)

        box = QGroupBox("Avanzado")
        form = QFormLayout(box)
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("ej. --turn-screen-off --audio-buffer=60")
        form.addRow("Argumentos extra:", self.extra)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(70)
        form.addRow("Comando:", self.preview)
        lay.addWidget(box)
        lay.addStretch()

        for w in (self.max_fps, self.x, self.y, self.w, self.h):
            w.valueChanged.connect(self._changed)
        for w in (self.no_mipmaps, self.stay_awake, self.borderless, self.set_geometry, self.force_x11,
                  self.launch_app, self.wait_landscape, self.ask_on_start):
            w.toggled.connect(self._changed)
        self.rotate_fit.currentIndexChanged.connect(self._changed)
        self.connection.currentIndexChanged.connect(self._changed)
        self.wifi_address.textChanged.connect(self._changed)
        self.package.textChanged.connect(self._changed)
        self.scrcpy_dir.textChanged.connect(self._changed)
        self.bitrate.textChanged.connect(self._changed)
        self.extra.textChanged.connect(self._changed)
        self.codec.currentTextChanged.connect(self._changed)
        self.serial.currentTextChanged.connect(self._changed)
        self.set_geometry.toggled.connect(self._sync)
        self.connection.currentIndexChanged.connect(self._sync)

    @staticmethod
    def _hint(text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: gray;")
        lbl.setWordWrap(True)
        return lbl

    def _sync(self):
        on = self.set_geometry.isChecked()
        for w in (self.x, self.y, self.w, self.h):
            w.setEnabled(on)
        self.wifi_hint.setVisible(self.connection.currentData() == "wifi")

    def _changed(self, *_):
        self._update_preview()
        self.changed.emit()

    def values(self):
        return {
            "scrcpy_dir": self.scrcpy_dir.text().strip(),
            "serial": self.serial.currentText().strip(),
            "codec": self.codec.currentText(),
            "bitrate": self.bitrate.text().strip() or "30M",
            "max_fps": self.max_fps.value(),
            "no_mipmaps": self.no_mipmaps.isChecked(),
            "stay_awake": self.stay_awake.isChecked(),
            "borderless": self.borderless.isChecked(),
            "set_geometry": self.set_geometry.isChecked(),
            "x": self.x.value(), "y": self.y.value(),
            "width": self.w.value(), "height": self.h.value(),
            "force_x11": self.force_x11.isChecked(),
            "extra_args": self.extra.text().strip(),
            "launch_app": self.launch_app.isChecked(),
            "package": self.package.text().strip(),
            "ask_on_start": self.ask_on_start.isChecked(),
            "wait_landscape": self.wait_landscape.isChecked(),
            "rotate_fit": self.rotate_fit.currentData() or "screen",
            "keep_geometry": (self.rotate_fit.currentData() or "screen") != "off",
            "connection": self.connection.currentData() or "usb",
            "wifi_address": self.wifi_address.text().strip(),
        }

    def _update_preview(self):
        try:
            vals = self.values()
            window = None
            if vals["rotate_fit"] == "screen":
                center = QPoint(vals["x"] + vals["width"] // 2, vals["y"] + vals["height"] // 2)
                g = (QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()).geometry()
                window = (g.x(), g.y(), g.width(), g.height())
            cmd = C.build_scrcpy_cmd(vals, window)
            env = C.scrcpy_env_overrides(self.values())
            prefix = " ".join(f"{k}={v}" for k, v in env.items())
            self.preview.setPlainText((prefix + " " if prefix else "") + " ".join(cmd))
        except ValueError as exc:
            self.preview.setPlainText(f"Error en argumentos: {exc}")

    def load(self, cfg):
        sc = cfg["scrcpy"]
        self.scrcpy_dir.setText(sc.get("scrcpy_dir", ""))
        self.serial.setCurrentText(sc["serial"])
        self.codec.setCurrentText(sc["codec"])
        self.bitrate.setText(str(sc["bitrate"]))
        self.max_fps.setValue(int(sc["max_fps"]))
        self.no_mipmaps.setChecked(bool(sc["no_mipmaps"]))
        self.stay_awake.setChecked(bool(sc["stay_awake"]))
        self.borderless.setChecked(bool(sc["borderless"]))
        self.set_geometry.setChecked(bool(sc["set_geometry"]))
        self.x.setValue(int(sc["x"]))
        self.y.setValue(int(sc["y"]))
        self.w.setValue(int(sc["width"]))
        self.h.setValue(int(sc["height"]))
        self.force_x11.setChecked(bool(sc["force_x11"]))
        self.extra.setText(sc["extra_args"])
        self.launch_app.setChecked(bool(sc["launch_app"]))
        self.package.setText(sc["package"])
        self.wait_landscape.setChecked(bool(sc["wait_landscape"]))
        self.ask_on_start.setChecked(bool(sc.get("ask_on_start", True)))
        self.rotate_fit.setCurrentIndex(max(0, self.rotate_fit.findData(sc.get("rotate_fit", "screen"))))
        self.connection.setCurrentIndex(max(0, self.connection.findData(sc.get("connection", "usb"))))
        self.wifi_address.setText(sc.get("wifi_address", ""))
        self._sync()
        self._update_preview()

    def store(self, cfg):
        cfg["scrcpy"] = self.values()

    def browse_scrcpy(self):
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de scrcpy", self.scrcpy_dir.text())
        if folder:
            self.scrcpy_dir.setText(folder)

    def _adb(self, *args):
        sc = self.values()
        if not C.tool_exists(sc, "adb"):
            raise RuntimeError("no encontre adb. " + (
                "Elige la carpeta de scrcpy (trae adb.exe)." if IS_WINDOWS else "Instala android-tools."))
        return PT.run([C.tool_path(sc, "adb"), *args], timeout=8)

    def detect_devices(self):
        try:
            out = self._adb("devices")
        except RuntimeError as exc:
            QMessageBox.warning(self, "adb", str(exc))
            return
        serials = [ln.split("\t")[0] for ln in out.splitlines()
                   if ln.endswith("\tdevice")]
        current = self.serial.currentText()
        self.serial.clear()
        self.serial.addItems(serials)
        phones = [s for s in serials if not s.startswith("emulator-")]
        if current in serials:
            self.serial.setCurrentText(current)
        elif phones:
            self.serial.setCurrentText(phones[0])
        self.log.emit(f"adb: {len(serials)} dispositivo(s): {', '.join(serials) or 'ninguno'}")
        if not serials:
            QMessageBox.information(self, "adb", "No hay dispositivos. Revisa la depuracion USB.")

    def fit_to_screen(self):
        serial = C.effective_serial(self.values())
        try:
            out = self._adb(*(["-s", serial] if serial else []), "shell", "wm", "size")
        except RuntimeError as exc:
            QMessageBox.warning(self, "adb", str(exc))
            return
        sizes = re.findall(r"(\d+)x(\d+)", out)
        if not sizes:
            QMessageBox.warning(self, "adb", f"No pude leer la resolucion del celular:\n{out}")
            return
        a, b = map(int, sizes[-1])
        vw, vh = max(a, b), min(a, b)            # el juego va en horizontal
        screens = QGuiApplication.screens()
        g = screens[max(0, self.screen.currentIndex())].geometry()
        scale = min(g.width() / vw, g.height() / vh)
        ww, wh = round(vw * scale), round(vh * scale)
        self.set_geometry.setChecked(True)
        self.w.setValue(ww)
        self.h.setValue(wh)
        self.x.setValue(g.x() + (g.width() - ww) // 2)
        self.y.setValue(g.y() + (g.height() - wh) // 2)
        self.log.emit(f"Celular {vw}x{vh} -> ventana {ww}x{wh} centrada en {g.width()}x{g.height()}")

    def full_screen(self):
        screens = QGuiApplication.screens()
        g = screens[max(0, self.screen.currentIndex())].geometry()
        self.set_geometry.setChecked(True)
        self.x.setValue(g.x())
        self.y.setValue(g.y())
        self.w.setValue(g.width())
        self.h.setValue(g.height())
        self.rotate_fit.setCurrentIndex(max(0, self.rotate_fit.findData("screen")))
        self.log.emit(f"Ventana: toda la pantalla {g.width()}x{g.height()} en {g.x()},{g.y()}")

    # ---------- red ----------
    def _adb_path(self):
        sc = self.values()
        if not C.tool_exists(sc, "adb"):
            QMessageBox.warning(self, "adb", "No encontre adb. " + (
                "Elige la carpeta de scrcpy (trae adb.exe)." if IS_WINDOWS else "Instala android-tools."))
            return None
        return C.tool_path(sc, "adb")

    def _set_wifi(self, addr):
        self.wifi_address.setText(addr)
        self.connection.setCurrentIndex(self.connection.findData("wifi"))

    def wifi_setup(self):
        adb = self._adb_path()
        if not adb:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            serial = PT.adb_usb_serial(adb, self.serial.currentText().strip())
            if not serial:
                raise RuntimeError("No veo el celular por cable. Conectalo por USB con la depuracion activada.")
            ip = PT.phone_ip(adb, serial)
            if not ip:
                raise RuntimeError("No pude leer la IP del celular. ¿Esta conectado al Wi-Fi?")
            self.log.emit(f"adb: activando red en {serial} ({ip})")
            PT.run([adb, "-s", serial, "tcpip", "5555"], timeout=8)
            addr = f"{ip}:5555"
            ok, out = False, ""
            for _ in range(6):             # el celular tarda un poco en abrir el puerto
                time.sleep(0.8)
                ok, out = PT.adb_connect(adb, addr)
                if ok:
                    break
        except RuntimeError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Red", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.log.emit(f"adb: {out}")
        if ok:
            self._set_wifi(addr)
            QMessageBox.information(self, "Red", f"Conectado a {addr}.\n\nYa puedes desconectar el cable. "
                                    "Guarda para que se use al iniciar el juego.")
        else:
            QMessageBox.warning(self, "Red", f"No me pude conectar a {addr}:\n{out}")

    def wifi_pair(self):
        adb = self._adb_path()
        if not adb:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Emparejar por Wi-Fi (Android 11+)")
        form = QFormLayout(dlg)
        info = QLabel("En el celular: Opciones de desarrollador > Depuracion inalambrica > "
                      "Vincular dispositivo con codigo de vinculacion.")
        info.setWordWrap(True)
        form.addRow(info)
        pair_addr = QLineEdit()
        pair_addr.setPlaceholderText("192.168.1.50:37123  (IP y puerto de vinculacion)")
        code = QLineEdit()
        code.setPlaceholderText("123456")
        conn_addr = QLineEdit()
        conn_addr.setPlaceholderText("192.168.1.50:41234  (IP y puerto de la pantalla principal)")
        form.addRow("Vincular en:", pair_addr)
        form.addRow("Codigo:", code)
        form.addRow("Conectar a:", conn_addr)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        out = PT.run([adb, "pair", pair_addr.text().strip(), code.text().strip()], timeout=20).strip()
        self.log.emit(f"adb pair: {out}")
        ok, cout = (False, "")
        if "success" in out.lower() and conn_addr.text().strip():
            ok, cout = PT.adb_connect(adb, conn_addr.text().strip())
            self.log.emit(f"adb: {cout}")
        QApplication.restoreOverrideCursor()
        if ok:
            self._set_wifi(conn_addr.text().strip())
            QMessageBox.information(self, "Red", "Emparejado y conectado. Guarda para usarlo al iniciar.")
        elif "success" in out.lower():
            QMessageBox.information(self, "Red", "Emparejado. Escribe la IP:puerto de la pantalla de "
                                    "Depuracion inalambrica y pulsa Conectar." + (f"\n\n{cout}" if cout else ""))
        else:
            QMessageBox.warning(self, "Red", f"No se pudo emparejar:\n{out or 'sin respuesta'}")

    def wifi_connect(self):
        adb = self._adb_path()
        if not adb:
            return
        addr = C.wifi_address(self.values())
        if not addr:
            QMessageBox.information(self, "Red", "Escribe la IP del celular (ej. 192.168.1.50:5555).")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok, out = PT.adb_connect(adb, addr)
        QApplication.restoreOverrideCursor()
        self.log.emit(f"adb: {out or 'sin respuesta'}")
        if ok:
            self._set_wifi(self.wifi_address.text().strip())
        else:
            QMessageBox.warning(self, "Red", f"No me pude conectar a {addr}:\n{out}")


# ================================================================ inicio: app o solo pantalla
APPS_CACHE = C.CONFIG_DIR / "apps.json"


def load_apps_cache():
    try:
        with open(APPS_CACHE, encoding="utf-8") as f:
            return [tuple(a[:3]) for a in json.load(f).get("apps", []) if len(a) >= 2]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def save_apps_cache(apps):
    try:
        APPS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(APPS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"apps": [list(a) for a in apps]}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


class LaunchDialog(QDialog):
    """Al iniciar: abrir una app del celular (lista con buscador) o solo mostrar la pantalla."""

    def __init__(self, sc, parent=None):
        super().__init__(parent)
        self.sc = sc
        self.setWindowTitle("Iniciar el celular")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)

        self.r_app = QRadioButton("Abrir una app en el celular")
        self.r_screen = QRadioButton("Solo mostrar la pantalla (no abre nada)")
        lay.addWidget(self.r_app)

        row = QHBoxLayout()
        row.addSpacing(24)
        self.apps = QComboBox()
        self.apps.setEditable(True)
        self.apps.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.apps.lineEdit().setPlaceholderText("Escribe para buscar (nombre o paquete)")
        comp = self.apps.completer()
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.btn_refresh = QPushButton("Actualizar lista")
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.apps, 1)
        row.addWidget(self.btn_refresh)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addSpacing(24)
        self.status = QLabel()
        self.status.setStyleSheet("color: gray;")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addSpacing(24)
        self.wait = QCheckBox("Esperar a que el celular este en horizontal antes de abrir la ventana")
        self.wait.setChecked(bool(sc.get("wait_landscape", True)))
        row.addWidget(self.wait)
        lay.addLayout(row)

        lay.addWidget(self.r_screen)
        lay.addSpacing(8)
        self.ask = QCheckBox("Preguntar cada vez (se vuelve a activar en la pestaña Juego)")
        self.ask.setChecked(True)
        lay.addWidget(self.ask)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Iniciar")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.finished.connect(self._list_done)
        no_console(self.proc)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self.proc.kill)

        self.r_app.toggled.connect(self._sync)
        (self.r_app if sc.get("launch_app", True) else self.r_screen).setChecked(True)
        self._fill(load_apps_cache())
        if self.apps.count() <= 1:
            QTimer.singleShot(0, self.refresh)
        else:
            self.status.setText(f"{self.apps.count()} apps (lista guardada; 'Actualizar lista' la vuelve a leer)")
        self._sync()

    def _sync(self):
        on = self.r_app.isChecked()
        for w in (self.apps, self.btn_refresh, self.wait):
            w.setEnabled(on)

    def _fill(self, apps):
        current = self.package() if self.apps.count() else (self.sc.get("package") or "")
        apps = sorted(apps, key=lambda a: (bool(a[2]) if len(a) > 2 else False, a[0].lower()))
        if current and not any(a[1] == current for a in apps):
            apps.insert(0, (current, current, False))
        self.apps.clear()
        for a in apps:
            name, pkg = a[0], a[1]
            system = len(a) > 2 and a[2]
            text = pkg if name == pkg else f"{name}   ({pkg})"
            self.apps.addItem(text + ("   · sistema" if system else ""), pkg)
        idx = self.apps.findData(current)
        if idx >= 0:
            self.apps.setCurrentIndex(idx)

    def package(self):
        text = self.apps.currentText().strip()
        idx = self.apps.findText(text)
        if idx >= 0:
            return self.apps.itemData(idx)
        if re.fullmatch(r"[A-Za-z][\w]*(\.[\w]+)+", text):
            return text
        low = text.lower()
        for i in range(self.apps.count()):
            if low and low in self.apps.itemText(i).lower():
                return self.apps.itemData(i)
        return ""

    def refresh(self):
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            return
        sc = self.sc
        serial = C.effective_serial(sc)
        if not C.tool_exists(sc, "scrcpy"):
            self._fallback()
            return
        self.status.setText("Buscando las apps del celular... (tarda unos segundos)")
        self.btn_refresh.setEnabled(False)
        args = (["-s", serial] if serial else []) + ["--list-apps"]
        self.proc.start(C.tool_path(sc, "scrcpy"), args)
        self.kill_timer.start(30000)

    def _list_done(self, *_):
        self.kill_timer.stop()
        self.btn_refresh.setEnabled(self.r_app.isChecked())
        out = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        apps = PT.parse_app_list(out)
        if apps:
            save_apps_cache(apps)
            self._fill(apps)
            self.status.setText(f"{len(apps)} apps en el celular")
        else:
            self._fallback(out)

    def _fallback(self, out=""):
        sc = self.sc
        apps = []
        if C.tool_exists(sc, "adb"):
            res = PT.run(PT.adb_cmd(C.tool_path(sc, "adb"), C.effective_serial(sc),
                                    "shell", "pm", "list", "packages", "-3"), timeout=10)
            apps = PT.parse_pm_packages(res)
        if apps:
            save_apps_cache(apps)
            self._fill(apps)
            self.status.setText(f"{len(apps)} apps (solo paquetes: tu scrcpy no tiene --list-apps)")
        else:
            last = [ln for ln in out.splitlines() if ln.strip()][-1:] or [""]
            self.status.setText("No pude leer las apps. ¿El celular esta conectado?  " + last[0][:120])

    def reject(self):
        self.proc.kill()
        super().reject()

    def _accept(self):
        if self.r_app.isChecked() and not self.package():
            QMessageBox.information(self, "Iniciar", "Elige una app de la lista (o escribe su paquete).")
            return
        self.proc.kill()
        self.accept()

    def choice(self):
        launch = self.r_app.isChecked()
        out = {"launch_app": launch, "ask_on_start": self.ask.isChecked()}
        if launch:
            out["package"] = self.package()
            out["wait_landscape"] = self.wait.isChecked()
        return out


class CursorBlanker(QWidget):
    """Ventana invisible encima del juego con cursor en blanco, mientras el mouse es camara.
    No recibe clics (el mouse esta capturado por el control) ni toma el foco."""

    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                 Qt.WindowType.WindowDoesNotAcceptFocus)
        if IS_WINDOWS:
            flags |= Qt.WindowType.Tool
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setWindowTitle("kb2pad-cursor")

    def paintEvent(self, _ev):
        # alfa 1/255: invisible, pero la ventana si "cuenta" para el cursor (con alfa 0 Windows la ignora)
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 1))

    def cover(self, screen):
        if IS_WINDOWS:
            self.setGeometry(screen.geometry())
            self.show()
            self.raise_()
            try:      # el cursor cambia hasta que Windows lo "mueve": se reacomoda en el mismo lugar
                import ctypes
                from ctypes import wintypes
                pt = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                ctypes.windll.user32.SetCursorPos(pt.x, pt.y)
            except (OSError, AttributeError):
                pass
        else:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())
            self.showFullScreen()
            self.raise_()


# ================================================================ ventana principal
class MainWindow(QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.dirty = False
        self._loading = False
        self.resize(1050, 820)

        try:
            self.cfg = C.load_config(self.path)
        except ValueError as exc:
            QMessageBox.critical(None, "kb2pad", f"{exc}\n\nSe usaran los valores por defecto.")
            self.cfg = C.default_config()

        central = QWidget()
        root = QVBoxLayout(central)

        # --- barra de control
        bar = QHBoxLayout()
        self.btn_engine = QPushButton("Iniciar control")
        self.btn_engine.clicked.connect(self.toggle_engine)
        self.lbl_engine = QLabel()
        self.btn_game = QPushButton("Iniciar juego")
        self.btn_game.clicked.connect(self.toggle_game)
        self.lbl_game = QLabel()
        self.btn_all = QPushButton("Iniciar todo")
        self.btn_all.clicked.connect(self.start_all)
        self.btn_save = QPushButton("Guardar")
        self.btn_save.clicked.connect(self.save)
        self.chk_debug = QCheckBox("Mostrar teclas en el log")
        self.chk_debug.toggled.connect(self.toggle_debug)
        self.lbl_mode_icon = QLabel()
        self.lbl_mode = QLabel()
        for w in (self.btn_engine, self.lbl_engine, self.btn_game, self.lbl_game, self.btn_all,
                  self.lbl_mode_icon, self.lbl_mode):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.chk_debug)
        bar.addWidget(self.btn_save)
        root.addLayout(bar)

        # --- pestanas
        self.tabs = QTabWidget()
        self.t_bind = BindingsTab()
        self.t_sticks = SticksTab()
        self.t_mouse = MouseTab()
        self.t_scrcpy = ScrcpyTab()
        def scrolled(widget):
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.Shape.NoFrame)
            area.setWidget(widget)
            return area

        self.tabs.addTab(self.t_bind, "Botones")
        self.tabs.addTab(scrolled(self.t_sticks), "Sticks y teclas especiales")
        self.tabs.addTab(scrolled(self.t_mouse), "Mouse y radial")
        self.tabs.addTab(scrolled(self.t_scrcpy), "Juego (scrcpy)")
        for t in (self.t_bind, self.t_sticks, self.t_mouse, self.t_scrcpy):
            t.changed.connect(self.mark_dirty)
        self.t_scrcpy.log.connect(self.append_log)
        self.t_sticks.keyboard_settings.connect(self.open_keyboard_settings)

        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumBlockCount(3000)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.logbox.setFont(mono)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(self.logbox)
        split.setSizes([560, 220])
        root.addWidget(split, 1)
        self.setCentralWidget(central)

        # --- menu
        menu = self.menuBar().addMenu("Archivo")
        act = QAction("Guardar", self)
        act.setShortcut(QKeySequence.StandardKey.Save)
        act.triggered.connect(self.save)
        menu.addAction(act)
        act = QAction("Recargar desde el archivo", self)
        act.triggered.connect(self.reload_from_disk)
        menu.addAction(act)
        act = QAction("Abrir config en el editor", self)
        act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path))))
        menu.addAction(act)
        menu.addSeparator()
        act = QAction("Restaurar valores por defecto", self)
        act.triggered.connect(self.restore_defaults)
        menu.addAction(act)
        if IS_WINDOWS:
            menu.addSeparator()
            act = QAction("Instalar ViGEmBus (driver del control virtual)", self)
            act.triggered.connect(self.install_vigem)
            menu.addAction(act)
        menu.addSeparator()
        act = QAction("Salir", self)
        act.triggered.connect(self.close)
        menu.addAction(act)

        # --- procesos
        self.engine = QProcess(self)
        self.engine.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.engine.readyReadStandardOutput.connect(
            lambda: self._read_proc(self.engine, "control"))
        self.engine.stateChanged.connect(self.update_status)
        self.engine.finished.connect(self._engine_finished)
        self.engine.errorOccurred.connect(lambda err: self.append_log(f"[control] error: {err.name}"))

        self.game = QProcess(self)
        self.game.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.game.readyReadStandardOutput.connect(lambda: self._read_proc(self.game, "juego"))
        self.game.stateChanged.connect(self.update_status)
        self.game.finished.connect(lambda code, _s: self.append_log(f"[juego] termino (codigo {code})"))
        self.game.errorOccurred.connect(lambda err: self.append_log(f"[juego] error: {err.name}"))
        self.game.started.connect(self._on_game_started)
        no_console(self.engine)
        no_console(self.game)
        self.game.finished.connect(lambda *_: (self.geo_timer.stop(), self._close_chat()))

        # ventanita de scrcpy para escribir en el chat (solo teclado)
        self.chat_proc = QProcess(self)
        self.chat_proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.chat_proc.readyReadStandardOutput.connect(lambda: self._read_proc(self.chat_proc, "chat"))
        self.chat_proc.errorOccurred.connect(lambda err: self.append_log(f"[chat] error: {err.name}"))
        no_console(self.chat_proc)
        self.chat_focus = QTimer(self)
        self.chat_focus.setInterval(250)
        self.chat_focus.timeout.connect(self._chat_focus_tick)
        self.chat_focus_until = 0.0

        # espera de rotacion antes de abrir scrcpy
        self.wait_timer = QTimer(self)
        self.wait_timer.setInterval(700)
        self.wait_timer.timeout.connect(self._wait_landscape_tick)
        self.wait_deadline = 0.0

        # acomodar la ventana cada vez que el celular pasa a horizontal
        self.geo_timer = QTimer(self)
        self.geo_timer.setInterval(800)
        self.geo_timer.timeout.connect(self._fit_tick)
        self.geo_wid = None
        self.geo_misses = 0
        self.geo_fails = 0

        icon = QIcon.fromTheme("input-gaming")
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self._connected = False
        self._paused = False
        self._mouselook = False
        self._chat = False
        self._mode_name = ""
        self.blanker = CursorBlanker()
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip(C.APP_NAME)
            self.tray.activated.connect(lambda *_: (self.showNormal(), self.activateWindow()))
            self.tray.show()
        self._update_tray()

        self.load_into_ui()
        self.update_status()
        self.append_log(f"Config: {self.path}")
        if needs_pkexec():
            self.append_log("Sin permisos directos a /dev/input o /dev/uinput: el control se "
                            "iniciara con pkexec (te pedira tu contraseña).")

    def install_vigem(self):
        msi = vigem_installer()
        if not msi.is_file():
            QMessageBox.warning(self, "ViGEmBus", f"No encontre el instalador:\n{msi}")
            return
        self.append_log(f"Abriendo el instalador de ViGEmBus: {msi}")
        try:
            os.startfile(str(msi))       # noqa: windows
        except OSError as exc:
            QMessageBox.warning(self, "ViGEmBus", f"No pude abrir el instalador: {exc}")

    # ---------- config <-> UI ----------
    def load_into_ui(self):
        self._loading = True
        self.t_bind.load(self.cfg)
        self.t_sticks.load(self.cfg)
        self.t_mouse.load(self.cfg)
        self.t_scrcpy.load(self.cfg)
        self._loading = False
        self.set_dirty(False)

    def collect(self):
        self.t_sticks.store(self.cfg)
        self.t_mouse.store(self.cfg)
        self.t_scrcpy.store(self.cfg)
        self.t_bind.store(self.cfg)
        return self.cfg

    def mark_dirty(self):
        if not self._loading:
            self.set_dirty(True)

    def set_dirty(self, dirty):
        self.dirty = dirty
        self.setWindowTitle(("* " if dirty else "") + f"{C.APP_NAME} {C.APP_VERSION} - control virtual")

    def save(self, quiet=False):
        cfg = self.collect()
        errors, warnings = C.validate(cfg)
        if errors:
            QMessageBox.critical(self, "No se guardo",
                                 "Corrige esto primero:\n\n" + "\n".join(f"- {e}" for e in errors))
            return False
        C.save_config(cfg, self.path)
        self.set_dirty(False)
        self._update_tray()
        self.append_log("Config guardada" + (" y enviada al control" if self.engine_running() else ""))
        for w in warnings:
            self.append_log(f"Aviso: {w}")
        if self.engine_running():
            self.engine.write(b"reload\n")
        if warnings and not quiet:
            QMessageBox.information(self, "Guardado con avisos", "\n".join(f"- {w}" for w in warnings))
        return True

    def reload_from_disk(self):
        if self.dirty and QMessageBox.question(
                self, "Recargar", "Perderas los cambios sin guardar. ¿Continuar?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self.cfg = C.load_config(self.path)
        except ValueError as exc:
            QMessageBox.critical(self, "kb2pad", str(exc))
            return
        self.load_into_ui()
        self.append_log("Config recargada desde el archivo")

    def restore_defaults(self):
        if QMessageBox.question(self, "Restaurar",
                                "¿Volver a los botones, modos y teclas por defecto?\n"
                                "La pestaña Juego (scrcpy) se queda como esta. Se aplica al guardar.") \
                != QMessageBox.StandardButton.Yes:
            return
        scrcpy = self.collect()["scrcpy"]
        self.cfg = C.default_config()
        self.cfg["scrcpy"] = scrcpy
        self.load_into_ui()
        self.set_dirty(True)

    # ---------- procesos ----------
    def engine_running(self):
        return self.engine.state() != QProcess.ProcessState.NotRunning

    def game_running(self):
        return self.game.state() != QProcess.ProcessState.NotRunning

    def update_status(self, *_):
        on_e, on_g = self.engine_running(), self.game_running()
        self.lbl_engine.setText("● activo" if on_e else "○ detenido")
        self.lbl_engine.setStyleSheet("color: #3c9a3c;" if on_e else "color: gray;")
        self.btn_engine.setText("Detener control" if on_e else "Iniciar control")
        waiting = hasattr(self, "wait_timer") and self.wait_timer.isActive()
        if waiting:
            self.lbl_game.setText("◌ esperando horizontal")
            self.lbl_game.setStyleSheet("color: #c9a227;")
            self.btn_game.setText("Cancelar")
            return
        self.lbl_game.setText("● abierto" if on_g else "○ cerrado")
        self.lbl_game.setStyleSheet("color: #3c9a3c;" if on_g else "color: gray;")
        self.btn_game.setText("Cerrar juego" if on_g else "Iniciar juego")

    def _read_proc(self, proc, tag):
        data = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        for line in data.splitlines():
            if line.strip():
                self.append_log(f"[{tag}] {line}")
                if tag == "control":
                    self._engine_line(line.strip())

    def _engine_line(self, line):
        if line.startswith("Modo: "):
            self._mode_changed(line[6:].strip())
        elif line.startswith("Mouse = camara"):
            self._set_mouselook(True)
        elif line.startswith("Mouse = normal"):
            self._set_mouselook(False)
        elif line == "Chat: ON":
            self._chat = True
            self._update_tray()
            self._open_chat()
        elif line == "Chat: OFF":
            self._chat = False
            self._update_tray()
            self._close_chat(refocus=True)
        elif line == "ACTIVO":
            self._connected, self._paused = True, False
            self._update_tray()
        elif line == "PAUSADO":
            self._paused = True
            self._update_tray()

    def _mode_changed(self, name):
        self._mode_name = name
        self._update_tray()

    def _update_tray(self):
        """Icono del modo actual en la bandeja y en la barra de la app; gris si el control
        esta detenido o en pausa."""
        mode = C.find_mode(self.cfg, self._mode_name) if self._connected else None
        active = self._connected and not self._paused
        if self._connected and self._chat:
            icon = icons.mode_icon("keyboard", active=active)
            text = "Chat: el teclado escribe" + ("" if active else " (en pausa)")
        elif mode:
            icon = mode_qicon(mode, active)
            state = "" if active else " (en pausa)"
            text = f"Modo: {mode['name']}{state}"
        else:
            icon = icons.mode_icon("gamepad", active=False)
            text = "Control detenido"
        self.lbl_mode_icon.setPixmap(icon.pixmap(22, 22))
        self.lbl_mode.setText(text if self._connected else "")
        self.lbl_mode.setStyleSheet("font-weight: bold;")
        if self.tray:
            self.tray.setIcon(icon)
            self.tray.setToolTip(f"{C.APP_NAME} - {text}")

    def _game_screen(self):
        sc = self.cfg["scrcpy"]
        center = QPoint(int(sc["x"]) + int(sc["width"]) // 2, int(sc["y"]) + int(sc["height"]) // 2)
        return QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()

    def _set_mouselook(self, on):
        if on == self._mouselook:
            return
        self._mouselook = on
        if on and self.cfg["special"].get("hide_cursor", True):
            self.blanker.cover(self._game_screen())
        else:
            self.blanker.hide()

    def append_log(self, text):
        self.logbox.appendPlainText(text)

    def ensure_saved(self):
        if self.dirty:
            return self.save(quiet=True)
        if not self.path.exists():
            C.save_config(self.collect(), self.path)
        return True

    def _engine_finished(self, code, _status):
        self.append_log(f"[control] termino (codigo {code})")
        self._set_mouselook(False)
        self._connected, self._paused, self._chat = False, False, False
        self._close_chat()
        self._update_tray()
        if IS_WINDOWS and code == 3:
            if QMessageBox.question(
                    self, "Falta ViGEmBus",
                    "El control virtual necesita el driver ViGEmBus.\n\n¿Abrir el instalador ahora? "
                    "(pide permisos de administrador; despues vuelve a iniciar el control)") \
                    == QMessageBox.StandardButton.Yes:
                self.install_vigem()

    def toggle_engine(self):
        if self.engine_running():
            self.stop_engine()
        else:
            self.start_engine()

    def start_engine(self):
        if self.engine_running():
            return
        if not self.ensure_saved():
            return
        if IS_WINDOWS:
            # mismo .exe en modo motor (o app.py --engine si corre desde el codigo)
            args = ([] if FROZEN else ["-u", str(HERE / "app.py")]) + ["--engine", "--config", str(self.path)]
            if self.chk_debug.isChecked():
                args.append("--debug")
            self.append_log("[control] iniciando...")
            self.engine.start(sys.executable, args)
            return
        args = ["-u", str(ENGINE), "--config", str(self.path)]
        if self.chk_debug.isChecked():
            args.append("--debug")
        if needs_pkexec():
            if not shutil.which("pkexec"):
                QMessageBox.critical(self, "Permisos",
                                     "No tengo permisos para /dev/input ni pkexec disponible.\n"
                                     "Revisa el README (grupo input + regla udev).")
                return
            program, args = "pkexec", [sys.executable] + args
        else:
            program = sys.executable
        self.append_log("[control] iniciando" + (" con pkexec..." if program == "pkexec" else "..."))
        self.engine.start(program, args)

    def stop_engine(self):
        if not self.engine_running():
            return
        self.engine.write(b"quit\n")
        self.engine.closeWriteChannel()
        QTimer.singleShot(3000, self._kill_engine_if_alive)

    def _kill_engine_if_alive(self):
        if self.engine_running():
            self.append_log("[control] no respondio, forzando cierre")
            self.engine.kill()

    def toggle_debug(self, on):
        if self.engine_running():
            self.engine.write(b"debug on\n" if on else b"debug off\n")

    def toggle_game(self):
        if self.wait_timer.isActive():
            self.wait_timer.stop()
            self.append_log("[juego] espera cancelada")
            self.update_status()
        elif self.game_running():
            self.game.terminate()
            QTimer.singleShot(3000, lambda: self.game_running() and self.game.kill())
        else:
            self.start_game()

    def start_game(self):
        if self.game_running() or self.wait_timer.isActive():
            return
        if not self.ensure_saved():
            return
        sc = self.cfg["scrcpy"]
        if not C.tool_exists(sc, "scrcpy"):
            QMessageBox.critical(self, "scrcpy", "No encontre scrcpy.\n\n" + (
                "Descarga scrcpy para Windows (github.com/Genymobile/scrcpy/releases), descomprimelo "
                "y elige esa carpeta en la pestaña Juego." if IS_WINDOWS else
                "Instalalo: sudo pacman -S scrcpy"))
            return
        try:
            C.build_scrcpy_cmd(sc)
        except ValueError as exc:
            QMessageBox.critical(self, "scrcpy", f"Argumentos extra invalidos: {exc}")
            return
        if sc.get("connection") == "wifi" and C.wifi_address(sc) and not self._wifi_connect(sc):
            return

        if sc.get("ask_on_start", True):
            dlg = LaunchDialog(sc, self)
            if not dlg.exec():
                return
            sc.update(dlg.choice())
            C.save_config(self.cfg, self.path)       # recuerda la eleccion (y la app) para la proxima
            self._loading = True
            self.t_scrcpy.load(self.cfg)
            self._loading = False

        launch = bool(sc.get("launch_app") and sc.get("package"))
        if launch:
            args = PT.adb_cmd(C.tool_path(sc, "adb"), C.effective_serial(sc), "shell", "monkey",
                              "-p", sc["package"], "-c", "android.intent.category.LAUNCHER", "1")
            PT.spawn(args)
            self.append_log(f"[juego] abriendo {sc['package']} en el celular")
        else:
            self.append_log("[juego] solo pantalla (no abro ninguna app)")

        if launch and sc.get("wait_landscape"):
            self.wait_deadline = time.monotonic() + 25
            self.append_log("[juego] esperando a que el celular este en horizontal...")
            self.wait_timer.start()
            self.update_status()
            return
        self._launch_scrcpy()

    def _wifi_connect(self, sc):
        """Modo red: adb connect antes de abrir scrcpy (si ya estaba conectado no tarda nada)."""
        if not C.tool_exists(sc, "adb"):
            QMessageBox.critical(self, "Red", "No encontre adb para conectarme por Wi-Fi.")
            return False
        addr = C.wifi_address(sc)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok, out = PT.adb_connect(C.tool_path(sc, "adb"), addr)
        QApplication.restoreOverrideCursor()
        self.append_log(f"[red] {out or 'sin respuesta de adb'}")
        if not ok:
            QMessageBox.warning(self, "Red", f"No me pude conectar al celular en {addr}.\n\n{out}\n\n"
                                "Revisa que este en la misma red. Si se reinicio, conecta el cable y usa "
                                "'Activar red con el cable' en la pestaña Juego (o cambia a Cable USB).")
        return ok

    def _wait_landscape_tick(self):
        sc = self.cfg["scrcpy"]
        rot = PT.device_rotation(C.tool_path(sc, "adb"), C.effective_serial(sc))
        if rot in (1, 3):
            self.wait_timer.stop()
            self.append_log("[juego] celular en horizontal")
            QTimer.singleShot(400, self._launch_scrcpy)   # deja terminar la animacion de giro
        elif time.monotonic() > self.wait_deadline:
            self.wait_timer.stop()
            self.append_log("[juego] no detecte horizontal en 25 s" +
                            (" (no pude leer la rotacion)" if rot is None else "") + ", abro de todos modos")
            self._launch_scrcpy()

    def _launch_scrcpy(self):
        if self.game_running():
            return
        sc = self.cfg["scrcpy"]
        window = self._screen_rect() if sc.get("rotate_fit") == "screen" else None
        cmd = C.build_scrcpy_cmd(sc, window, PT.scrcpy_version(C.tool_path(sc, "scrcpy")))
        env = QProcessEnvironment.systemEnvironment()
        for k, v in C.scrcpy_env_overrides(sc).items():
            env.insert(k, v)
        self.game.setProcessEnvironment(env)
        self.append_log("[juego] " + " ".join(cmd))
        self.game.start(cmd[0], cmd[1:])
        self.update_status()

    def _screen_rect(self, geo=None):
        """Rectangulo de la pantalla donde esta la ventana (o donde se configuro)."""
        scr = None
        if geo:
            x, y, w, h = geo
            scr = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2))
        g = (scr or self._game_screen()).geometry()
        return g.x(), g.y(), g.width(), g.height()

    def _on_game_started(self):
        sc = self.cfg["scrcpy"]
        if sc.get("rotate_fit", "screen") == "off":
            return
        missing = PT.window_tool_missing()
        if missing:
            self.append_log(f"[juego] para acomodar la ventana al girar {missing}")
            return
        self.geo_wid = None
        self.geo_misses = 0
        self.geo_fails = 0
        QTimer.singleShot(1200, self.geo_timer.start)

    def _find_game_window(self):
        pid = self.game.processId()
        return PT.find_window(pid) if pid else None

    def _fit_tick(self):
        """Cada vez que la ventana pasa a horizontal (abriste el juego, volviste del menu del cel...)
        la acomoda: toda la pantalla o la posicion fija. En vertical no se toca."""
        if not self.game_running():
            self.geo_timer.stop()
            return
        sc = self.cfg["scrcpy"]
        mode = sc.get("rotate_fit", "screen")
        if mode == "off":
            return
        if self.geo_wid is None:
            self.geo_wid = self._find_game_window()
            if self.geo_wid is None:
                self.geo_misses += 1
                if self.geo_misses == 12:
                    self.append_log("[juego] no encontre la ventana de scrcpy para acomodarla" + ("" if IS_WINDOWS
                                    else " (xdotool solo ve ventanas X11; activa 'Forzar X11' en la pestaña Juego)"))
                return
        geo = PT.window_geometry(self.geo_wid)
        if geo is None:
            self.geo_wid = None
            return
        x, y, w, h = geo
        if w <= h:
            self.geo_fails = 0                      # en vertical (menus del cel): no se toca
            return
        if mode == "fixed":
            tx, ty, tw, th = int(sc["x"]), int(sc["y"]), int(sc["width"]), int(sc["height"])
        else:
            tx, ty, tw, th = self._screen_rect(geo)
        if max(abs(x - tx), abs(y - ty), abs(w - tw), abs(h - th)) <= 2:
            self.geo_fails = 0
            return
        if self.geo_fails >= 4:
            return                                  # no acepta ese tamaño: no insistir hasta el proximo giro
        self.geo_fails += 1
        PT.set_window_geometry(self.geo_wid, tx, ty, tw, th)
        if self.geo_fails == 1:
            self.append_log(f"[juego] ventana ajustada a {tw}x{th} en {tx},{ty}")
        elif self.geo_fails == 4:
            self.append_log(f"[juego] la ventana no acepta {tw}x{th} (se queda {w}x{h})")

    # ---------- chat ----------
    def _open_chat(self):
        sc = self.cfg["scrcpy"]
        if not self.cfg["special"].get("chat_window", True):
            return
        if not self.game_running():
            self.append_log("[chat] el teclado ya no es control; abre el juego para escribir en el celular")
            return
        if self.chat_proc.state() != QProcess.ProcessState.NotRunning:
            self._refocus_chat()                   # Alt+T otra vez: seguir escribiendo
            return
        gx, gy, gw, gh = (PT.window_geometry(self.geo_wid) if self.geo_wid else None) or self._screen_rect()
        window = (gx + gw - 8, gy + gh - 8, 8, 8)    # diminuta en la esquina; ademas se vuelve transparente
        cmd = C.build_chat_cmd(sc, window, self.cfg["special"].get("chat_keyboard", "uhid"))
        env = QProcessEnvironment.systemEnvironment()
        for k, v in C.scrcpy_env_overrides(sc).items():
            env.insert(k, v)
        self.chat_proc.setProcessEnvironment(env)
        self.append_log("[chat] escribiendo en el celular (Alt+1/2/3 o Alt+Q para volver)")
        self.chat_proc.start(cmd[0], cmd[1:])
        self.chat_focus_until = time.monotonic() + 6
        self.chat_focus.start()

    def _chat_focus_tick(self):
        """Espera a que aparezca la ventanita del chat y le da el foco para escribir de inmediato."""
        wid = self._chat_window()
        if wid is not None:
            self.chat_focus.stop()
            PT.set_window_opacity(wid, 0.0)
            QTimer.singleShot(150, lambda: PT.focus_window(wid))
        elif time.monotonic() > self.chat_focus_until or not self.chat_proc.processId():
            self.chat_focus.stop()

    def _chat_window(self):
        pid = self.chat_proc.processId()
        return PT.find_window(pid, min_size=1) if pid else None

    def _refocus_chat(self):
        wid = self._chat_window()
        if wid is not None:
            PT.focus_window(wid)

    def open_keyboard_settings(self):
        """Ajustes > Teclado fisico en el celular (para elegir el idioma del teclado 'scrcpy')."""
        sc = self.collect()["scrcpy"]
        if not C.tool_exists(sc, "adb"):
            QMessageBox.warning(self, "adb", "No encontre adb.")
            return
        if self.chat_proc.state() == QProcess.ProcessState.NotRunning:
            QMessageBox.information(self, "Teclado", "Primero entra al chat con Alt+T (con el juego abierto): "
                                    "el teclado 'scrcpy' solo aparece en el celular mientras el chat esta activo.")
        PT.spawn(PT.adb_cmd(C.tool_path(sc, "adb"), C.effective_serial(sc), "shell", "am", "start",
                            "-a", "android.settings.HARD_KEYBOARD_SETTINGS"))
        self.append_log("[chat] abriendo Ajustes > Teclado fisico en el celular: elige 'scrcpy' y el idioma "
                        "de tu teclado (ej. Español (Latinoamerica))")

    def _close_chat(self, refocus=False):
        self.chat_focus.stop()
        if self.chat_proc.state() != QProcess.ProcessState.NotRunning:
            self.chat_proc.terminate()
            QTimer.singleShot(1500, lambda: self.chat_proc.state() != QProcess.ProcessState.NotRunning
                              and self.chat_proc.kill())
            if refocus and self.game_running():
                wid = self.geo_wid or self._find_game_window()
                if wid:
                    QTimer.singleShot(200, lambda: PT.focus_window(wid))

    def start_all(self):
        if not self.engine_running():
            self.start_engine()
            # scrcpy detecta controles conectados despues, pero damos tiempo a que exista
            QTimer.singleShot(1500, self.start_game)
        else:
            self.start_game()

    # ---------- cierre ----------
    def closeEvent(self, ev):
        if self.dirty:
            ans = QMessageBox.question(
                self, "Salir", "Hay cambios sin guardar. ¿Guardar antes de salir?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                ev.ignore()
                return
            if ans == QMessageBox.StandardButton.Save and not self.save(quiet=True):
                ev.ignore()
                return
        if self.chat_proc.state() != QProcess.ProcessState.NotRunning:
            self.chat_proc.kill()
            self.chat_proc.waitForFinished(1000)
        if self.game_running():
            self.game.terminate()
            if not self.game.waitForFinished(2000):
                self.game.kill()
        if self.engine_running():
            self.engine.write(b"quit\n")
            self.engine.closeWriteChannel()
            if not self.engine.waitForFinished(2500):
                self.engine.kill()
        self.blanker.close()
        if self.tray:
            self.tray.hide()
        ev.accept()


def main():
    if "--engine" in sys.argv:                 # modo motor (el .exe se lanza a si mismo)
        argv = [a for a in sys.argv[1:] if a != "--engine"]
        if IS_WINDOWS:
            import engine_win
            sys.exit(engine_win.main(argv))
        import engine
        sys.exit(engine.main(argv))

    app = QApplication(sys.argv)
    app.setApplicationName(C.APP_NAME)
    app.setApplicationVersion(C.APP_VERSION)
    # botones estandar (Si/No, Aceptar/Cancelar) en español
    tr = QTranslator(app)
    if tr.load(QLocale("es"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    path = Path(args[0]).expanduser() if args else C.CONFIG_PATH
    win = MainWindow(path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
