# -*- mode: python ; coding: utf-8 -*-
# Spécification PyInstaller : produit dist/LeStitcheurFouCars.exe (fichier unique, fenêtré).
# Usage : pyinstaller --noconfirm --clean packaging/LeStitcheurFouCars.spec

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 (variable fournie par PyInstaller)
sys.path.insert(0, str(ROOT / "src"))
from lsfcars import APP_ID, APP_NAME, __version__  # noqa: E402

numbers = tuple(int(part) for part in __version__.split(".")[:3]) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040C04B0",
                    [
                        StringStruct("CompanyName", "LeStitcheur"),
                        StringStruct("FileDescription", APP_NAME),
                        StringStruct("FileVersion", __version__),
                        StringStruct("InternalName", APP_ID),
                        StringStruct("OriginalFilename", f"{APP_ID}.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x040C, 1200])]),
    ],
)

datas = [
    (str(ROOT / "samples" / "vehicule_test.glb"), "samples"),
    (str(ROOT / "samples" / "vehicule_test.obj"), "samples"),
    (str(ROOT / "src" / "lsfcars" / "resources"), "lsfcars/resources"),
]
datas += collect_data_files("trimesh")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=[],
    excludes=["tkinter", "matplotlib", "scipy", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_ID,
    icon=str(ROOT / "packaging" / "icon.ico"),
    version=version_info,
    console=False,
    upx=False,
    debug=False,
    strip=False,
)
