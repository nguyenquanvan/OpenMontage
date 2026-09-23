"""Create a credential-free source bundle that can be continued on Windows."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.app_version import APP_VERSION


def main() -> int:
    output_dir = ROOT / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"MOSA-TOOL-ALL-{APP_VERSION}-source.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", f"--output={destination}", "HEAD"],
        cwd=ROOT,
        check=True,
    )
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
