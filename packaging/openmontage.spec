# PyInstaller build for the OpenMontage desktop shell.
from pathlib import Path
import sys

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

if sys.platform == "darwin":
    from PyInstaller.building.osx import BUNDLE

ROOT = Path(SPECPATH).parent


def data_dir(relative: str) -> tuple[str, str]:
    source = ROOT / relative
    return str(source), relative


datas = [
    data_dir("backlot/ui"),
    data_dir("pipeline_defs"),
    data_dir("schemas"),
    data_dir("styles"),
    data_dir("config.yaml"),
    data_dir("remotion-composer"),
    (str(ROOT / "packaging" / "runtime"), "runtime"),
]
hiddenimports = []

# pywebview discovers platform backends dynamically; tool discovery does the
# same for OpenMontage providers, so both package trees need hidden imports.
for package in ("webview", "tools", "backlot"):
    hiddenimports.extend(collect_submodules(package))
    datas.extend(collect_data_files(package))

analysis = Analysis(
    [str(ROOT / "desktop" / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    excludes=["pytest", "tests", "notebook", "jupyter"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="OpenMontage",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="OpenMontage",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collect,
        name="OpenMontage.app",
        bundle_identifier="video.openmontage.desktop",
        info_plist={
            "CFBundleDisplayName": "OpenMontage",
            "CFBundleName": "OpenMontage",
            "NSHighResolutionCapable": True,
        },
    )
