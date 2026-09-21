"""Build the OpenMontage desktop application with PyInstaller."""

from __future__ import annotations

import shutil
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.app_version import APP_BUILD, APP_NAME, APP_VERSION, version_payload

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "openmontage.spec"
RUNTIME_SCRIPT = ROOT / "scripts" / "fetch_desktop_runtime.py"
WINDOWS_ICON = ROOT / "build" / "mosa-tool-all.ico"


def prepare_windows_icon() -> None:
    if sys.platform != "win32":
        return
    from PIL import Image

    WINDOWS_ICON.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(ROOT / "assets" / "logo.png") as source:
        source.convert("RGBA").save(
            WINDOWS_ICON,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )


def main() -> int:
    prepare_windows_icon()
    subprocess.run([sys.executable, str(RUNTIME_SCRIPT)], cwd=ROOT, check=True)
    runtime_dir = ROOT / "packaging" / "runtime"
    if not (runtime_dir / "node").is_dir() or not (runtime_dir / "ffmpeg").is_dir() or not (runtime_dir / "uv").is_dir():
        raise SystemExit("Desktop runtime preparation did not produce Node.js, FFmpeg and uv")
    npm = (runtime_dir / "node" / "bin" / "npm") if sys.platform != "win32" else (runtime_dir / "node" / "npm.cmd")
    if not npm.exists():
        raise SystemExit(f"Bundled npm not found: {npm}")
    subprocess.run([str(npm), "ci", "--omit=dev"], cwd=ROOT / "remotion-composer", check=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    version_file = ROOT / "dist" / f"{APP_NAME.replace(' ', '-')}-version.json"
    version_file.write_text(
        json.dumps(version_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built {APP_NAME} {APP_VERSION} ({APP_BUILD}) under {ROOT / 'dist'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
