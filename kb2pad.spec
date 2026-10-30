# PyInstaller spec para Windows:  python -m PyInstaller --noconfirm kb2pad.spec
# Resultado: dist/kb2pad/kb2pad.exe (carpeta: arranca rapido y el motor no se re-extrae)

a = Analysis(
    ["app.py"],
    pathex=["."],
    datas=[
        ("vigem/ViGEmClient.dll", "vigem"),
        ("vigem/ViGEmBusSetup_x64.msi", "vigem"),
        ("vigem/LICENSE-vgamepad.txt", "vigem"),
    ],
    hiddenimports=["engine_win", "core", "keycodes", "_ecodes_data", "platform_tools"],
    excludes=["evdev", "tkinter", "unittest", "pydoc", "PyQt6.QtNetwork", "PyQt6.QtQml",
              "PyQt6.QtQuick", "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtMultimedia",
              "PyQt6.QtPdf", "PyQt6.QtSvg", "PyQt6.QtOpenGL", "PyQt6.QtDBus"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kb2pad",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="kb2pad", upx=False)
