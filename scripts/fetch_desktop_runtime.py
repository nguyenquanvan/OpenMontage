"""Fetch the portable runtime shipped inside desktop builds.

The desktop application owns its Python process, Node/Remotion runtime, and
FFmpeg toolchain. API keys and large model weights stay outside the bundle and
are configured by the user at runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = ROOT / "packaging" / "runtime"
DOWNLOAD_ROOT = ROOT / "packaging" / ".runtime-downloads"
DEFAULT_NODE_VERSION = "24.14.1"
DEFAULT_UV_VERSION = "0.12.17"
FFPROBE_PACKAGES = {
    ("darwin", "arm64"): ("darwin-arm64", "5.0.1"),
    ("darwin", "x64"): ("darwin-x64", "5.1.0"),
    ("win", "x64"): ("win32-x64", "5.1.0"),
}


def target_platform() -> tuple[str, str]:
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    if os.name == "nt":
        return "win", architecture
    if sys_platform() == "darwin":
        return "darwin", architecture
    if sys_platform() == "linux":
        return "linux", architecture
    raise RuntimeError(f"Unsupported desktop build platform: {sys_platform()}")


def sys_platform() -> str:
    return platform.system().lower()


def download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    print(f"Downloading {url}")
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def clean_directory(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def extract_node(version: str, force: bool) -> dict[str, str]:
    target, architecture = target_platform()
    extension = "zip" if target == "win" else "tar.gz"
    archive_name = f"node-v{version}-{target}-{architecture}.{extension}"
    url = f"https://nodejs.org/dist/v{version}/{archive_name}"
    archive = download(url, DOWNLOAD_ROOT / archive_name)
    destination = RUNTIME_ROOT / "node"
    marker = destination / ".openmontage-node-version"
    if marker.is_file() and not force and marker.read_text().strip() == version:
        return {"version": version, "target": target, "architecture": architecture}
    clean_directory(destination)
    with tempfile.TemporaryDirectory(prefix="openmontage-node-") as temporary:
        extraction = Path(temporary)
        if extension == "zip":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extraction)
        else:
            with tarfile.open(archive, "r:gz") as bundle:
                bundle.extractall(extraction, filter="data")
        roots = [path for path in extraction.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(f"Unexpected Node.js archive layout: {roots}")
        for child in roots[0].iterdir():
            target_path = destination / child.name
            if child.is_symlink():
                target_path.symlink_to(child.readlink())
            elif child.is_dir():
                shutil.copytree(child, target_path, symlinks=True)
            else:
                shutil.copy2(child, target_path)
    marker.write_text(version + "\n")
    return {"version": version, "target": target, "architecture": architecture}


def extract_uv(version: str, force: bool) -> dict[str, str]:
    target, architecture = target_platform()
    if target == "darwin":
        uv_target = f"{'aarch64' if architecture == 'arm64' else 'x86_64'}-apple-darwin"
        extension = "tar.gz"
    elif target == "win" and architecture == "x64":
        uv_target = "x86_64-pc-windows-msvc"
        extension = "zip"
    else:
        uv_target = f"{'aarch64' if architecture == 'arm64' else 'x86_64'}-unknown-linux-gnu"
        extension = "tar.gz"
    archive_name = f"uv-{uv_target}.{extension}"
    url = f"https://github.com/astral-sh/uv/releases/download/{version}/{archive_name}"
    archive = download(url, DOWNLOAD_ROOT / f"uv-{version}-{uv_target}.{extension}")
    destination = RUNTIME_ROOT / "uv"
    marker = destination / ".openmontage-uv-version"
    executable_name = "uv.exe" if target == "win" else "uv"
    executable = destination / executable_name
    if marker.is_file() and executable.is_file() and not force and marker.read_text().strip() == version:
        return {"version": version, "target": uv_target, "executable": executable_name}
    clean_directory(destination)
    with tempfile.TemporaryDirectory(prefix="openmontage-uv-") as temporary:
        extraction = Path(temporary)
        if extension == "zip":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extraction)
        else:
            with tarfile.open(archive, "r:gz") as bundle:
                bundle.extractall(extraction, filter="data")
        matches = list(extraction.rglob(executable_name))
        if not matches:
            raise RuntimeError(f"Unexpected uv archive layout: {archive}")
        shutil.copy2(matches[0], executable)
    if target != "win":
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    marker.write_text(version + "\n")
    return {"version": version, "target": uv_target, "executable": executable_name}


def copy_ffmpeg(force: bool) -> dict[str, object]:
    destination = RUNTIME_ROOT / "ffmpeg"
    destination.mkdir(parents=True, exist_ok=True)
    executable_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    target = destination / executable_name
    source = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if force or not target.is_file():
        shutil.copy2(source, target)
    if os.name != "nt":
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"bundled": True, "filename": executable_name}


def copy_ffprobe(force: bool) -> dict[str, object]:
    """Bundle an architecture-matched ffprobe package when available."""
    destination = RUNTIME_ROOT / "ffmpeg"
    destination.mkdir(parents=True, exist_ok=True)
    executable_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    target = destination / executable_name
    target_name, architecture = target_platform()
    package = FFPROBE_PACKAGES.get((target_name, architecture))
    if package:
        package_name, version = package
        archive_name = f"ffprobe-installer-{package_name}-{version}.tgz"
        url = f"https://registry.npmjs.org/@ffprobe-installer/{package_name}/-/{package_name}-{version}.tgz"
        archive = download(url, DOWNLOAD_ROOT / archive_name)
        with tempfile.TemporaryDirectory(prefix="openmontage-ffprobe-") as temporary:
            extraction = Path(temporary)
            with tarfile.open(archive, "r:gz") as bundle:
                bundle.extractall(extraction, filter="data")
            source_path = extraction / "package" / "ffprobe"
            if not source_path.is_file():
                raise RuntimeError(f"Unexpected ffprobe archive layout: {archive}")
            shutil.copy2(source_path, target)
        if os.name != "nt":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return {"bundled": True, "package": f"@ffprobe-installer/{package_name}@{version}"}

    source = shutil.which("ffprobe")
    if source and _portable_ffprobe(Path(source)) and (force or not target.is_file()):
        shutil.copy2(source, target)
        if os.name != "nt":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    elif force or (source and not _portable_ffprobe(Path(source))):
        target.unlink(missing_ok=True)
    return {"bundled": target.is_file(), "filename": executable_name if target.is_file() else None}


def _portable_ffprobe(source: Path) -> bool:
    """Avoid copying a build-host ffprobe that depends on Homebrew paths."""
    if os.name == "nt":
        return True
    if sys_platform() != "darwin":
        return True
    try:
        result = subprocess.run(["otool", "-L", str(source)], capture_output=True, text=True, check=False)
    except OSError:
        return False
    dependencies = result.stdout + result.stderr
    return "/opt/homebrew/" not in dependencies and "/usr/local/Cellar/" not in dependencies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-version", default=os.environ.get("OPENMONTAGE_NODE_VERSION", DEFAULT_NODE_VERSION))
    parser.add_argument("--uv-version", default=os.environ.get("OPENMONTAGE_UV_VERSION", DEFAULT_UV_VERSION))
    parser.add_argument("--force", action="store_true", help="Replace an existing runtime")
    args = parser.parse_args()

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    node = extract_node(args.node_version, args.force)
    uv = extract_uv(args.uv_version, args.force)
    ffmpeg = copy_ffmpeg(args.force)
    ffprobe = copy_ffprobe(args.force)
    manifest = {
        "node": node,
        "uv": uv,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "platform": sys_platform(),
        "architecture": platform.machine(),
        "model_weights": "downloaded separately by the user or configured local provider",
    }
    (RUNTIME_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    if not ffprobe["bundled"]:
        print("WARNING: ffprobe was not found on the build host; bundled post-render probing will use system ffprobe if available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
