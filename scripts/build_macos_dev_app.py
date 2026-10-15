"""Build a clickable macOS development app backed by this checkout's venv."""

from __future__ import annotations

import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "dist-dev" / "SelfIndex.app"
ICON_SOURCE = PROJECT_ROOT / "assets" / "icons" / "tray-icon.png"


def build_icon(destination: Path) -> None:
    subprocess.run(
        ["sips", "-s", "format", "icns", str(ICON_SOURCE), "--out", str(destination)],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("This development app can only be built on macOS.")
    python_exe = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not python_exe.is_file():
        raise SystemExit(f"Virtual environment Python not found: {python_exe}")

    contents = APP_PATH / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    plist = {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleDisplayName": "SelfIndex",
        "CFBundleExecutable": "SelfIndex",
        "CFBundleIdentifier": "local.selfindex.desktop.dev",
        "CFBundleIconFile": "SelfIndex.icns",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "SelfIndex",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(plist, sort_keys=False))
    launcher = macos / "SelfIndex"
    launcher.write_text(
        "#!/bin/sh\n"
        f"cd {shlex.quote(str(PROJECT_ROOT))}\n"
        f"{shlex.quote(str(python_exe))} -m scripts.macos_launch_agent ensure || true\n"
        f"exec {shlex.quote(str(python_exe))} -m desktop_mac.main\n",
        encoding="ascii",
    )
    launcher.chmod(0o755)
    build_icon(resources / "SelfIndex.icns")
    print(APP_PATH)


if __name__ == "__main__":
    main()
