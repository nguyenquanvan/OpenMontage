"""Push the current MOSA source and publish a version tag for desktop CI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.app_version import APP_BUILD, APP_VERSION


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a MOSA TOOL ALL desktop release")
    parser.add_argument("--remote", default="fork", help="Git remote receiving source and tag")
    parser.add_argument("--push", action="store_true", help="Actually push branch and release tag")
    parser.add_argument("--skip-tests", action="store_true", help="Skip the focused release tests")
    args = parser.parse_args()

    dirty = run("git", "status", "--porcelain", capture=True)
    if dirty:
        raise SystemExit("Working tree chưa sạch. Hãy commit thay đổi trước khi phát hành.")
    branch = run("git", "branch", "--show-current", capture=True)
    if not branch:
        raise SystemExit("Không thể phát hành từ detached HEAD")
    tag = f"v{APP_VERSION}"
    existing = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if existing.returncode == 0:
        raise SystemExit(f"Tag {tag} đã tồn tại")

    if not args.skip_tests:
        run(sys.executable, "-m", "pytest", "-q", "tests/backlot/test_app_updater.py", "tests/desktop/test_app.py", "tests/backlot/test_server.py")

    print(f"MOSA TOOL ALL {APP_VERSION} · build {APP_BUILD}")
    print(f"Nguồn: {branch} -> {args.remote}; tag: {tag}")
    if not args.push:
        print("Chế độ kiểm tra. Thêm --push để đẩy source và kích hoạt GitHub Actions.")
        return 0

    run("git", "push", args.remote, branch)
    run("git", "tag", "-a", tag, "-m", f"MOSA TOOL ALL {APP_VERSION} ({APP_BUILD})")
    try:
        run("git", "push", args.remote, tag)
    except Exception:
        subprocess.run(["git", "tag", "-d", tag], cwd=ROOT, check=False)
        raise
    print(f"Đã đẩy {tag}. GitHub Actions đang tạo bộ cài Windows và macOS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
