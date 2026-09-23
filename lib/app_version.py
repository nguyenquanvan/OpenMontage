"""Application identity and release version for MOSA TOOL ALL."""

from __future__ import annotations

import os


APP_NAME = "MOSA TOOL ALL"
APP_VERSION = os.environ.get("MOSA_APP_VERSION", "1.6.2")
APP_BUILD = os.environ.get("MOSA_APP_BUILD", "20260923.19")
APP_VERSION_LABEL = f"v{APP_VERSION} · build {APP_BUILD}"


def version_payload() -> dict[str, str]:
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "build": APP_BUILD,
        "label": APP_VERSION_LABEL,
    }
