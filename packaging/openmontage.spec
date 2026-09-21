# PyInstaller build for the MOSA TOOL ALL desktop shell.
from pathlib import Path
import sys

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

if sys.platform == "darwin":
    from PyInstaller.building.osx import BUNDLE

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

from lib.app_version import APP_BUILD, APP_VERSION


def data_dir(relative: str) -> tuple[str, str]:
    source = ROOT / relative
    return str(source), relative


datas = [
    data_dir("backlot/ui"),
    data_dir("pipeline_defs"),
    data_dir("schemas"),
    data_dir("styles"),
    data_dir("skills"),
    data_dir("config.yaml"),
    data_dir("remotion-composer"),
    data_dir("runtime_workers"),
    (str(ROOT / "packaging" / "runtime"), "runtime"),
]
hiddenimports = []

# pywebview discovers platform backends dynamically; tool discovery does the
# same for MOSA TOOL ALL providers, so both package trees need hidden imports.
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
    name="MOSA TOOL ALL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "build" / "mosa-tool-all.ico") if sys.platform == "win32" else None,
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="MOSA TOOL ALL",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collect,
        name="MOSA TOOL ALL.app",
        bundle_identifier="com.mosa.toolall.desktop",
        info_plist={
            "CFBundleDisplayName": "MOSA TOOL ALL",
            "CFBundleName": "MOSA TOOL ALL",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_BUILD,
            "NSHighResolutionCapable": True,
        },
    )
