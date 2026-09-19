"""Build the OpenMontage desktop application with PyInstaller."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "openmontage.spec"
RUNTIME_SCRIPT = ROOT / "scripts" / "fetch_desktop_runtime.py"


def main() -> int:
    subprocess.run([sys.executable, str(RUNTIME_SCRIPT)], cwd=ROOT, check=True)
    runtime_dir = ROOT / "packaging" / "runtime"
    if not (runtime_dir / "node").is_dir() or not (runtime_dir / "ffmpeg").is_dir():
        raise SystemExit("Desktop runtime preparation did not produce Node.js and FFmpeg")
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
    print(f"Built desktop artifacts under {ROOT / 'dist'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
