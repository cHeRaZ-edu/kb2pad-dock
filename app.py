#!/usr/bin/env python3
"""
kb2pad - GUI para configurar el control virtual (teclado + mouse -> Xbox 360)
y lanzar el juego con scrcpy en ventana sin bordes.

    python app.py

Linux (CachyOS): sudo pacman -S python-pyqt6 python-evdev scrcpy android-tools xdotool
Windows: kb2pad.exe (necesita el driver ViGEmBus y scrcpy para Windows)
"""
import glob
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (QEvent, QLibraryInfo, QLocale, QProcess, QProcessEnvironment, Qt, QTimer,
                          QTranslator, QUrl, pyqtSignal)
from PyQt6.QtGui import QAction, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QStyle, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

import config as C
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
        msg = QLabel("Presiona una tecla o un boton del mouse\n"
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
        return super().event(ev)


class KeyField(QWidget):
    """Combo editable con todos los nombres + boton para capturar."""
    changed = pyqtSignal()

    def __init__(self, name="", parent=None):
        super().__init__(parent)
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
        if C.is_valid_input(n):
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
class BindingsTab(QWidget):
    """Asignaciones de "Por defecto" y de cada modo. Un modo solo guarda lo que cambia."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bindings = []           # "Por defecto"
        self.modes = []              # [{"name", "hotkey", "bindings"}]
        self.mode_default = ""       # atajo de "Por defecto"
        self.start_mode = C.DEFAULT_MODE
        self.rows = []               # [(origen, indice)]: origen = "base" | "mode"
        self._loading = False
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Modo:"))
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(200)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        bar.addWidget(self.mode_combo)
        bar.addWidget(QLabel("  Atajo: Alt +"))
        self.hotkey = KeyField()
        self.hotkey.changed.connect(self._hotkey_changed)
        bar.addWidget(self.hotkey)
        for text, slot in (("Nuevo modo", self.new_mode), ("Renombrar", self.rename_mode),
                           ("Eliminar modo", self.delete_mode)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
            if text != "Nuevo modo":
                setattr(self, "btn_" + ("rename" if text == "Renombrar" else "delete"), b)
        bar.addStretch()
        lay.addLayout(bar)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Al iniciar el control:"))
        self.start_combo = QComboBox()
        self.start_combo.currentTextChanged.connect(self._start_changed)
        bar.addWidget(self.start_combo)
        self.info = QLabel()
        self.info.setStyleSheet("color: gray;")
        self.info.setWordWrap(True)
        bar.addWidget(self.info, 1)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Tecla", "Salida", "Modificador", "Tipo", "Nota", "Origen"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        for col in (0, 1, 2, 3, 5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.edit)
        lay.addWidget(self.table)

        row = QHBoxLayout()
        for text, slot in (("Agregar", self.add), ("Editar", self.edit),
                           ("Duplicar", self.duplicate), ("Eliminar", self.remove),
                           ("Subir", lambda: self.move(-1)), ("Bajar", lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
            if text in ("Subir", "Bajar"):
                setattr(self, "btn_up" if text == "Subir" else "btn_down", b)
        self.btn_reset = QPushButton("Quitar todos los cambios del modo")
        self.btn_reset.clicked.connect(self.reset_mode)
        row.addWidget(self.btn_reset)
        row.addStretch()
        lay.addLayout(row)

    # ---------- datos ----------
    def load(self, cfg):
        self.bindings = cfg["bindings"]
        self.modes = cfg.get("modes") or []
        self.mode_default = cfg["special"].get("mode_default", "")
        self.start_mode = cfg.get("start_mode") or C.DEFAULT_MODE
        self._fill_modes(0)

    def store(self, cfg):
        cfg["bindings"] = self.bindings
        cfg["modes"] = self.modes
        cfg["start_mode"] = self.start_mode
        cfg["special"]["mode_default"] = self.mode_default

    def mode(self):
        """El modo seleccionado, o None si es "Por defecto"."""
        i = self.mode_combo.currentIndex()
        return self.modes[i - 1] if i > 0 else None

    def _label(self, name, hotkey):
        return name + (f"   (Alt+{C.input_label(hotkey)})" if hotkey else "")

    def _fill_modes(self, select):
        self._loading = True
        self.mode_combo.clear()
        self.mode_combo.addItem(self._label(C.DEFAULT_MODE, self.mode_default))
        for m in self.modes:
            self.mode_combo.addItem(self._label(m["name"], m.get("hotkey")))
        self.start_combo.clear()
        self.start_combo.addItems([C.DEFAULT_MODE] + [m["name"] for m in self.modes])
        names = [C.DEFAULT_MODE] + [m["name"] for m in self.modes]
        if self.start_mode not in names:
            self.start_mode = C.DEFAULT_MODE
        self.start_combo.setCurrentText(self.start_mode)
        self.mode_combo.setCurrentIndex(max(0, min(select, len(self.modes))))
        self._loading = False
        self._mode_changed()

    def _mode_changed(self, *_):
        if self._loading:
            return
        m = self.mode()
        self._loading = True
        self.hotkey.set_value(m.get("hotkey", "") if m else self.mode_default)
        self._loading = False
        base = m is None
        for b in (self.btn_rename, self.btn_delete, self.btn_reset):
            b.setEnabled(not base)
        self.btn_up.setEnabled(base)
        self.btn_down.setEnabled(base)
        self.info.setText(
            "Lo que pongas aqui lo heredan todos los modos." if base else
            f"El modo {m['name']} solo guarda lo que cambia (Origen = {m['name']}). "
            "Lo demas viene de Por defecto; si lo editas, se copia a este modo.")
        self.refresh()

    def _hotkey_changed(self):
        if self._loading:
            return
        value = self.hotkey.value()
        if value and not C.is_valid_input(value):
            return
        m = self.mode()
        if m is None:
            self.mode_default = value
        else:
            m["hotkey"] = value
        i = self.mode_combo.currentIndex()
        self._loading = True
        self.mode_combo.setItemText(i, self._label(m["name"] if m else C.DEFAULT_MODE, value))
        self._loading = False
        self.changed.emit()

    def _start_changed(self, text):
        if self._loading or not text:
            return
        self.start_mode = text
        self.changed.emit()

    # ---------- tabla ----------
    def _binding(self, row):
        origin, i = self.rows[row]
        return self.bindings[i] if origin == "base" else self.mode()["bindings"][i]

    def refresh(self, select=None):
        m = self.mode()
        if m is None:
            self.rows = [("base", i) for i in range(len(self.bindings))]
        else:
            ov = m["bindings"]
            by_key = {}
            for j, b in enumerate(ov):
                by_key.setdefault(C.binding_key(b), []).append(j)
            shown = set()
            self.rows = []
            for i, b in enumerate(self.bindings):
                k = C.binding_key(b)
                if k in by_key:
                    if k not in shown:
                        self.rows += [("mode", j) for j in by_key[k]]
                        shown.add(k)
                else:
                    self.rows.append(("base", i))
            for k, js in by_key.items():
                if k not in shown:
                    self.rows += [("mode", j) for j in js]

        gray = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        self.table.setRowCount(len(self.rows))
        for r, (origin, _i) in enumerate(self.rows):
            b = self._binding(r)
            off = origin == "mode" and not b.get("outputs")
            if off:
                kind = "Desactivada en este modo"
            elif b.get("camera_only"):
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
                "—" if off else " + ".join(C.output_label(o) for o in b.get("outputs", [])),
                "" if off else " + ".join(C.output_label(o) for o in b.get("modifier", [])),
                kind,
                b.get("note", ""),
                "" if m is None else (m["name"] if origin == "mode" else C.DEFAULT_MODE),
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if m is not None:
                    if origin == "base":
                        item.setForeground(gray)
                    else:
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                self.table.setItem(r, c, item)
        if select is not None and 0 <= select < len(self.rows):
            self.table.selectRow(select)

    def _select(self, origin, i):
        for r, row in enumerate(self.rows):
            if row == (origin, i):
                self.table.selectRow(r)
                return

    def current(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    # ---------- acciones ----------
    def add(self):
        dlg = BindingDialog(C.binding("", []), self)
        if dlg.exec():
            m = self.mode()
            target = self.bindings if m is None else m["bindings"]
            target.append(dlg.binding())
            self.refresh()
            self._select("base" if m is None else "mode", len(target) - 1)
            self.changed.emit()

    def edit(self, *_):
        r = self.current()
        if r < 0:
            return
        origin, i = self.rows[r]
        m = self.mode()
        b = self._binding(r)
        if origin == "mode" and not b.get("outputs"):
            b = dict(b)
            base = [x for x in self.bindings if C.binding_key(x) == C.binding_key(b)]
            if base:
                b = dict(base[0])
        dlg = BindingDialog(b, self)
        if not dlg.exec():
            return
        if m is None:
            self.bindings[i] = dlg.binding()
            self.refresh(r)
        elif origin == "mode":
            m["bindings"][i] = dlg.binding()
            self.refresh(r)
        else:                                    # de "Por defecto": se copia al modo
            m["bindings"].append(dlg.binding())
            self.refresh()
            self._select("mode", len(m["bindings"]) - 1)
        self.changed.emit()

    def duplicate(self):
        r = self.current()
        if r < 0:
            return
        origin, i = self.rows[r]
        m = self.mode()
        if m is None:
            self.bindings.insert(i + 1, dict(self.bindings[i]))
            self.refresh(r + 1)
        else:
            m["bindings"].append(dict(self._binding(r)))
            self.refresh()
            self._select("mode", len(m["bindings"]) - 1)
        self.changed.emit()

    def remove(self):
        r = self.current()
        if r < 0:
            return
        origin, i = self.rows[r]
        m = self.mode()
        b = self._binding(r)
        name = C.input_label(b["input"])
        if m is None:
            if QMessageBox.question(self, "Eliminar",
                                    f"¿Eliminar {name} -> {' + '.join(b.get('outputs', []))}?\n"
                                    "Se quita de todos los modos que no lo cambien.") \
                    != QMessageBox.StandardButton.Yes:
                return
            del self.bindings[i]
        elif origin == "mode":
            del m["bindings"][i]                 # vuelve a lo de "Por defecto"
        else:
            if QMessageBox.question(self, "Desactivar",
                                    f"¿Desactivar {name} solo en el modo {m['name']}?") \
                    != QMessageBox.StandardButton.Yes:
                return
            off = dict(b)
            off["outputs"], off["modifier"], off["radial"] = [], [], False
            off["note"] = (b.get("note") or "") + " (desactivada)"
            m["bindings"].append(off)
        self.refresh(min(r, len(self.rows) - 1))
        self.changed.emit()

    def move(self, delta):
        if self.mode() is not None:
            return
        r = self.current()
        n = r + delta
        if r < 0 or not (0 <= n < len(self.bindings)):
            return
        self.bindings[r], self.bindings[n] = self.bindings[n], self.bindings[r]
        self.refresh(n)
        self.changed.emit()

    def reset_mode(self):
        m = self.mode()
        if m is None or not m["bindings"]:
            return
        if QMessageBox.question(self, "Quitar cambios",
                                f"¿Quitar los {len(m['bindings'])} cambios del modo {m['name']}?\n"
                                "Queda igual que Por defecto.") == QMessageBox.StandardButton.Yes:
            m["bindings"].clear()
            self.refresh()
            self.changed.emit()

    # ---------- modos ----------
    def _ask_name(self, title, current=""):
        name, ok = QInputDialog.getText(self, title, "Nombre del modo:", text=current)
        name = name.strip()
        if not ok or not name:
            return None
        taken = [C.DEFAULT_MODE] + [m["name"] for m in self.modes if m["name"] != current]
        if name in taken:
            QMessageBox.warning(self, title, f"Ya hay un modo llamado '{name}'.")
            return None
        return name

    def new_mode(self):
        name = self._ask_name("Nuevo modo")
        if not name:
            return
        self.modes.append({"name": name, "hotkey": "", "bindings": []})
        self._fill_modes(len(self.modes))
        self.changed.emit()

    def rename_mode(self):
        m = self.mode()
        if m is None:
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
        if m is None:
            return
        if QMessageBox.question(self, "Eliminar modo", f"¿Eliminar el modo {m['name']}?") \
                != QMessageBox.StandardButton.Yes:
            return
        if self.start_mode == m["name"]:
            self.start_mode = C.DEFAULT_MODE
        self.modes.remove(m)
        self._fill_modes(0)
        self.changed.emit()


class SticksTab(QWidget):
    changed = pyqtSignal()
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

        box = QGroupBox("Modos (Alt + tecla)")
        form = QFormLayout(box)
        self.alt_blocks = QCheckBox("Con Alt presionado no mandar nada al juego "
                                    "(Alt+Tab, Alt+O de scrcpy, cambios de modo)")
        self.notify_mode = QCheckBox("Avisar con una notificacion al cambiar de modo")
        self.alt_blocks.toggled.connect(self.changed.emit)
        self.notify_mode.toggled.connect(self.changed.emit)
        form.addRow(self.alt_blocks)
        form.addRow(self.notify_mode)
        hint = QLabel("Los modos y sus atajos se editan en la pestaña Botones.")
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
        self.alt_blocks.setChecked(bool(cfg["special"].get("alt_blocks", True)))
        self.notify_mode.setChecked(bool(cfg["special"].get("notify_mode", True)))

    def store(self, cfg):
        for key, fs in self.fields.items():
            cfg["sticks"][key] = [f.value() for f in fs]
        cfg["special"]["pause"] = self.pause.value()
        cfg["special"]["mouselook"] = self.mouselook.value()
        cfg["special"]["alt_blocks"] = self.alt_blocks.isChecked()
        cfg["special"]["notify_mode"] = self.notify_mode.isChecked()


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
        form.addRow("Serial (adb):", row)
        form.addRow("", self._hint("Vacio = el unico dispositivo conectado."))
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
        fit.clicked.connect(self.fit_to_screen)
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
        grid.addWidget(self.screen, 3, 1, 1, 2)
        grid.addWidget(fit, 3, 3)
        grid.addWidget(self.force_x11, 4, 0, 1, 4)
        self.force_x11.setVisible(not IS_WINDOWS)
        lay.addWidget(box)

        box = QGroupBox("Al iniciar el juego")
        form = QFormLayout(box)
        row = QHBoxLayout()
        self.launch_app = QCheckBox("Abrir la app en el celular")
        self.package = QLineEdit()
        self.package.setPlaceholderText("com.garena.game.mho")
        row.addWidget(self.launch_app)
        row.addWidget(self.package, 1)
        form.addRow(row)
        self.wait_landscape = QCheckBox("Esperar a que el celular este en horizontal antes de abrir la ventana")
        self.keep_geometry = QCheckBox("Mantener el tamaño y posicion si la ventana cambia al rotar"
                                       + ("" if IS_WINDOWS else " (necesita xdotool)"))
        form.addRow(self.wait_landscape)
        form.addRow(self.keep_geometry)
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
                  self.launch_app, self.wait_landscape, self.keep_geometry):
            w.toggled.connect(self._changed)
        self.package.textChanged.connect(self._changed)
        self.scrcpy_dir.textChanged.connect(self._changed)
        self.bitrate.textChanged.connect(self._changed)
        self.extra.textChanged.connect(self._changed)
        self.codec.currentTextChanged.connect(self._changed)
        self.serial.currentTextChanged.connect(self._changed)
        self.set_geometry.toggled.connect(self._sync)

    @staticmethod
    def _hint(text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: gray;")
        return lbl

    def _sync(self):
        on = self.set_geometry.isChecked()
        for w in (self.x, self.y, self.w, self.h):
            w.setEnabled(on)

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
            "wait_landscape": self.wait_landscape.isChecked(),
            "keep_geometry": self.keep_geometry.isChecked(),
        }

    def _update_preview(self):
        try:
            cmd = C.build_scrcpy_cmd(self.values())
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
        self.keep_geometry.setChecked(bool(sc["keep_geometry"]))
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
        serial = self.serial.currentText().strip()
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
        self.lbl_mode = QLabel()
        for w in (self.btn_engine, self.lbl_engine, self.btn_game, self.lbl_game, self.btn_all,
                  self.lbl_mode):
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
        self.tabs.addTab(self.t_bind, "Botones")
        self.tabs.addTab(self.t_sticks, "Sticks y teclas especiales")
        self.tabs.addTab(self.t_mouse, "Mouse y radial")
        self.tabs.addTab(self.t_scrcpy, "Juego (scrcpy)")
        for t in (self.t_bind, self.t_sticks, self.t_mouse, self.t_scrcpy):
            t.changed.connect(self.mark_dirty)
        self.t_scrcpy.log.connect(self.append_log)

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
        self.game.finished.connect(lambda *_: self.geo_timer.stop())

        # espera de rotacion antes de abrir scrcpy
        self.wait_timer = QTimer(self)
        self.wait_timer.setInterval(700)
        self.wait_timer.timeout.connect(self._wait_landscape_tick)
        self.wait_deadline = 0.0

        # mantener tamaño/posicion de la ventana al rotar
        self.geo_timer = QTimer(self)
        self.geo_timer.setInterval(800)
        self.geo_timer.timeout.connect(self._keep_geometry_tick)
        self.geo_wid = None
        self.geo_misses = 0

        icon = QIcon.fromTheme("input-gaming")
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip(C.APP_NAME)
            self.tray.activated.connect(lambda *_: (self.showNormal(), self.activateWindow()))
            self.tray.show()
        self.engine.stateChanged.connect(
            lambda st: st == QProcess.ProcessState.NotRunning and self.lbl_mode.setText(""))

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
                if tag == "control" and line.startswith("Modo: "):
                    self._mode_changed(line[6:].strip())

    def _mode_changed(self, name):
        self.lbl_mode.setText(f"   Modo: {name}")
        self.lbl_mode.setStyleSheet("font-weight: bold;")
        if self.tray and self.cfg["special"].get("notify_mode", True):
            self.tray.showMessage(C.APP_NAME, f"Modo: {name}",
                                  QSystemTrayIcon.MessageIcon.Information, 1500)

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

        if sc.get("launch_app") and sc.get("package"):
            args = PT.adb_cmd(C.tool_path(sc, "adb"), sc.get("serial", ""), "shell", "monkey",
                              "-p", sc["package"], "-c", "android.intent.category.LAUNCHER", "1")
            PT.spawn(args)
            self.append_log(f"[juego] abriendo {sc['package']} en el celular")

        if sc.get("wait_landscape"):
            self.wait_deadline = time.monotonic() + 25
            self.append_log("[juego] esperando a que el celular este en horizontal...")
            self.wait_timer.start()
            self.update_status()
            return
        self._launch_scrcpy()

    def _wait_landscape_tick(self):
        sc = self.cfg["scrcpy"]
        rot = PT.device_rotation(C.tool_path(sc, "adb"), sc.get("serial", ""))
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
        cmd = C.build_scrcpy_cmd(sc)
        env = QProcessEnvironment.systemEnvironment()
        for k, v in C.scrcpy_env_overrides(sc).items():
            env.insert(k, v)
        self.game.setProcessEnvironment(env)
        self.append_log("[juego] " + " ".join(cmd))
        self.game.start(cmd[0], cmd[1:])
        self.update_status()

    def _on_game_started(self):
        sc = self.cfg["scrcpy"]
        if not (sc.get("keep_geometry") and sc.get("set_geometry")):
            return
        missing = PT.window_tool_missing()
        if missing:
            self.append_log(f"[juego] para mantener el tamaño al rotar {missing}")
            return
        self.geo_wid = None
        self.geo_misses = 0
        QTimer.singleShot(1200, self.geo_timer.start)

    def _find_game_window(self):
        pid = self.game.processId()
        return PT.find_window(pid) if pid else None

    def _keep_geometry_tick(self):
        if not self.game_running():
            self.geo_timer.stop()
            return
        sc = self.cfg["scrcpy"]
        if self.geo_wid is None:
            self.geo_wid = self._find_game_window()
            if self.geo_wid is None:
                self.geo_misses += 1
                if self.geo_misses >= 10:
                    self.geo_timer.stop()
                    self.append_log("[juego] no encontre la ventana de scrcpy" + ("" if IS_WINDOWS else
                                    " con xdotool; si estas en Wayland activa 'Forzar X11' en la pestaña Juego"))
                return
        geo = PT.window_geometry(self.geo_wid)
        if geo is None:
            self.geo_wid = None
            return
        x, y, w, h = geo
        tx, ty, tw, th = int(sc["x"]), int(sc["y"]), int(sc["width"]), int(sc["height"])
        if w <= h:
            return                                   # en vertical (menus del cel): no se toca
        if max(abs(x - tx), abs(y - ty), abs(w - tw), abs(h - th)) <= 2:
            return
        PT.set_window_geometry(self.geo_wid, tx, ty, tw, th)
        self.append_log(f"[juego] ventana ajustada a {tw}x{th} en {tx},{ty}")

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
        if self.game_running():
            self.game.terminate()
            if not self.game.waitForFinished(2000):
                self.game.kill()
        if self.engine_running():
            self.engine.write(b"quit\n")
            self.engine.closeWriteChannel()
            if not self.engine.waitForFinished(2500):
                self.engine.kill()
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
